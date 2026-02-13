# TSO-and-Pacing-on-modified-Netronome-Firmware
A modification of Netronome Agilio CX 4000 firmware (CoreNIC) to support TSO and Pacing. Developed for a master thesis at UiO.

## Requirements

#### Server 1
For compiling the modified NFP driver and CoreNIC firmware a machine with the following is needed:
- A Netronome Agilio CX 4000 SmartNIC 2x10GbE
- Ubuntu 18.04, with Linux kernel 5.4
- NFP Kernel drivers (should come preinstalled with Ubuntu 18.04)
- Netronome’s NFP Linux Toochain
  - Can be retrieved by asking Netronome, as outlined [here](https://github.com/Netronome/nic-firmware?tab=readme-ov-file#toolchain-and-reference-manuals).
- GNU awk
  - `apt-get install gawk`
- The original CoreNIC firmware for Ubuntu 18.04
  - [Install from here](https://github.com/Netronome/nic-firmware/releases/tag/nic-2.1.16.1)
- The out-of-tree NFP drivers for Ubuntu 18.04
  - Download drivers: `git clone https://github.com/Netronome/nfp-drv-kmods.git`
  - Go back to correct version: `git checkout c44a501006f85050c4a1f0fbfd1031d56743ce7b`
- (For testing)
  - `iperf3`, `ethtool`

#### Server 2
Also, for running the test you need a machine with another Agilio CX SmartNIC, directly attached to the one we are modifying:
- A Netronome Agilio CX 4000 SmartNIC 2x10GbE
- Ubuntu 18.04, with Linux kernel 5.4
- `netsniff-ng`, `iperf3`, `mergecap`, `cpufrequtils`, `ethtool`

#### PC
And a personal machine for generating plots based on the packet captures from tests:
- Ssh access to server 2
- `tshark`
- `python3` (pandas, numpy, matplotlib)

## Modifying the NFP driver and CoreNIC firmware
The NFP drivers can be modified by changing the files in the NFP driver directory you installed, then compiling it. The [`nfp_net_common.c`](modified-nfd-driver/nfp_net_common.c) file contains our modifications to the driver, and can be copied to the oot NDF driver as follows:
```bash
cp ./modified-nfd-driver/nfp_net_common.c $HOME/master/modified-nfp-oot-driver-2019/src/
```

The CoreNIC firmware can similarly be modified by changing the files in the CoreNIC directory you installed, then compiling it. The [`notify.c`](modified-nfd-firmware/notify.c) file contains our modifications to the firmware, and can be copied into the CoreNIC firmware as follows:
```bash
cp ./modified-nfd-firmware/notify.c $HOME/master/modified-nfp-firmware/deps/ng-nfd.git/me/blocks/vnic/pci_in/
```

## Compiling and loading modified driver and firmware
To compile and load modified drivers and firmware, the [`build-nfp.sh`](scripts/build-nfp.sh) script can be used. 

First, modify its variables to reflect your environment. 

If wanted, the script can switch between modified and the original drivers/firmware. To do this, you should have copies of the un-modified driver and firmware, and provide the path to these in the script. 

Running the build script:
```bash
sudo build-nfp.sh
```

The build script can be ran with the following options
- `--help`
- `--skip-fw/--skip-driver/--skip-check`
  - Skips build/install for this part
- ` --skip-build `
  - skips building, just loads
- `--clean`
  - Runs make clean
- `--org/--org-fw/--org-driver`
  - Build the original firmware/driver
  - By default this skips building, to prevent rebuilding the same drivers/fimware here. When running for the first time, you need to explicitly build here (by modifying the script or running the commands yourself).

### Configuring the Netronome interface
Set the IP address (as the IP address might disapear after loading updated drivers. Alternatively, you can add a netplan file to set `enp2s0np0` to a static ip).
```bash
sudo ip addr add 192.168.50.1/24 dev enp2s0np0

# Confirm with:
ip -br addr show dev enp2s0np0
```

Enable/disale TSO:
```bash
sudo ethtool -K enp2s0np0 tso on gso on
sudo ethtool -K enp2s0np0 tso off gso off

# Confirm with:
sudo ethtool -k enp2s0np0
```

Setting the qdisc:
```bash
# fq
sudo tc qdisc replace dev enp2s0np0 root fq
# fq_codel
sudo tc qdisc replace dev enp2s0np0 root fq_codel
# Cake (with 1 Gbps cap)
sudo tc qdisc replace dev enp2s0np0 root cake bandwidth 1gbit besteffort flows no-split-gso

# Confirm with:
sudo tc qdisc show dev enp2s0np0
```

## Testing modifications

### Debugging
View memory of NIC:
```bash
sudo nfp-rtsym _wire_debug
```

Log/print statements from NFP driver:
```bash
dmesg | grep nfp
```

### Running test
To run a test, run the [`run-tcp-test.sh`](scripts/run-tcp-test.sh) script on Server 2:
```bash
sudo ./run-tcp-test.sh
```
(You might want to change some of the values, such as the ip addresses and folder names)

This generates a packet capture, which can be extracted by running the [`extract-pcap.sh`](scripts/extract-pcap.sh) script on your own machine (PC):
```bash
sudo ./extract-pcap.sh
```


## Help, nothing works! 
So, you want to modify and compile custom drivers+firmware for a 10 Gbps SmartNIC. And nothing works? Here are some common pitfalls I encountered at least.

#### Hardware not recoginized
Sometimes (seemingly at random) the NFP driver load fails. This can be seen by... the fact that the interface does not work, e.g. you can't ping the other netronome card.
```bash
dmesg | grep nfp | tail -n 300
[51949.364539] nfp 0000:02:00.0 enp2s0np0: enp2s0np0 down
[51949.540390] nfp 0000:02:00.0 enp2s0np1: enp2s0np1 down
[51953.015350] nfp 0000:02:00.0: Firmware safely unloaded
...
[51953.099385] nfp 0000:02:00.0: Model: 0x40010010, SN: 00:15:4d:13:5c:8c, Ifc: 0x10ff
[51953.104454] nfp 0000:02:00.0: nfp_hwinfo: Unknown HWInfo version: 0x60000000
...
[53668.201353] nfp 0000:02:00.0: nfp_hwinfo: Unknown HWInfo version: 0x60000000
[53668.306517] nfp 0000:02:00.0: nfp_hwinfo: NFP access error
[53668.306526] nfp 0000:02:00.0: nfp: NFP board initialization timeout
[53668.306854] nfp: probe of 0000:02:00.0 failed with error -22
```
HFInfo is something the ARM firmware on netronome card builds after the chip resets ([source](https://coral.googlesource.com/linux-imx/%2B/refs/tags/11-2/drivers/net/ethernet/netronome/nfp/nfpcore/nfp_hwinfo.c)). If the version field is never set it implies something goes wrong when loading the custom firmware on the card. 

The solution? Reboot the machine (and possibly rebuild and load the firmware). Do this as many times it takes. I have found no other way to fix the issue, where resetting (or unbind/binding) the card does not work. 

#### Random behavior
Hopefully I will be able to fix this. If not I am sorry.

The current solution works perfectly, as long as you dont load the NFP module with `nfp_dev_cpp=1`. For some reason, when using `nfp_dev_cpp`, it interacts with our pacing solution and causes it to randomly drop packets, reduce the time wheel's throughput, and eventually cause a complete loss of transmissions. 

This seems to happen per-flow, so for multiple active flows, only one may excibit this behavior at first, with the others following later (up to several seconds, millions of packets, later). Other times all flows imediatelly stop sending data. When trying to ping after e.g. 4 flows causes their transmission to stop, sometimes it works, sometimes not. 
Other times the solution works as expected (for several hours) even with `nfp_dev_cpp`, but this is only 1 out of 10 runs. 

The per-flow behavior seems to indicate that `nfp_dev_cpp` somehow interacts with the per-flow state, either in the driver or firmware, which causes the erratic behavior. 

So far, our only solution is to disable `nfp_dev_cpp`. This of course prevents you from reading the memory of the NIC. 

(Can also mention that is it not the firmware which freezes which cause this, debugging shows that the Notify ME continues to run after stopping to transmit, not placing any packets in the time wheel. Moreover, packet reception still works.)

#### Card stops transmission
Another case of card freezes is if the `halt()` command runs in Notify, or if there is a deadlock (i.e. the threads are waiting for signals which are never raised.)

Try to place debug statements to find out if these are your culprint.

---

---

## IFI Subject recommendations
Recommendations for other students working on the Netronome cards at IFI.

**IN5050 – Programming heterogeneous multi-core architectures**
Fun and educational course. A lot of practial programming (as opposed to many other IFI courses...). Good practice for writing reports, troubleshooting, and benchmarking. Also good for low-level programming/hardware architecture, which is essential for working on the Netronome Cards.
And no final exam! Only 3 reports during the semester.

**IN5170 – Models of Concurrency** 
This course is all right, decent lecturers and a decent workload. Exam was relatively easy (ask me for previous exams for practice if you want, they dont publish them for some reason).
Good for gaining intuitive understanding of concurrency, deadlocks, and synchronization mechanisms, and practical real-world implementations of these (Java, Golang <3, and Rust) (also brief mention of Erland :( and C#)).
Also, only 2 small obligs the whole semester, each took only one afternoon to complete! 

**IN5060 – Quantitative Performance Analysis**
Not that technical, but good practice for handling and anlysing data sets for research purposes, visualizing data/results, and presenting this for a crowd. 

**IN4230 – Computer Networks** 
Course I proabably should have taken. Introduction to networks (in detail), and especially relevant in that you program network protocols in C. Very relevant for both driver and firmware modifications for the netronome cards.

**IN4120 – Search Technology** 
Good course+lecturer, fun exercises, however not *that* relevant to the thesis. Covers lot of different topics within search engines which can also be applied in other fields (compression, data stuctures, fun text handling, vectors/embedding of language/text, basic machine learning)

(Also, use [karakterweb](https://www.karakterweb.no/) to see difficulty and ratings of IFI subjects)

