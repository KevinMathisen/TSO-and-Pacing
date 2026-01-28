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
  - `iperf3`

#### Server 2
Also, for running the test you need a machine with another Agilio CX SmartNIC, directly attached to the one we are modifying:
- A Netronome Agilio CX 4000 SmartNIC 2x10GbE
- Ubuntu 18.04, with Linux kernel 5.4
- `netsniff-ng`
- `iperf3`
- `mergecap`

#### PC
And a personal machine for generating plots based on the packet captures from tests:
- Ssh access to server 2
- `tshark`
- `python3` (pandas, numpy, matplotlib)

## Modifying the NFP driver and CoreNIC firmware
The NFP drivers can be modified by changing the files in the NFP driver directory you installed, then compiling it. The [`nfp_net_common.c`](modified-nfd-driver/nfp_net_common.c) file contains our modifications to the driver, and can be copied to the oot NDF driver as follows:
```bash
cp ./modified-nfd-driver/nfp_net_common.c <path>/modified-nfp-oot-driver-2019/src/
```

The CoreNIC firmware can similarly be modified by changing the files in the CoreNIC directory you installed, then compiling it. The [`notify.c`](modified-nfd-firmware/notify.c) file contains our modifications to the firmware, and can be copied into the CoreNIC firmware as follows:
```bash
cp ./modified-nfd-firmware/notify.c <path>/modified-nfp-firmware/deps/ng-nfd.git/me/blocks/vnic/pci_in/
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
