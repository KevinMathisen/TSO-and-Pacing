#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

NFP_IF="enp2s0np0"
IP1="10.111.0.1"
IP2="10.111.0.3"
SENDER=kevinnm@192.168.1.98
DUR=5   # seconds to run (assuming 10Gb/s, will result in under 1GB pcap file)
FLOWS=2 # parallel flows to run
OUT=/tmp/tcp-test-output
PERSIST=/var/tmp/tcp-test-output
mkdir -p "$OUT"
mkdir -p "$PERSIST"

pin_rx_to_cpu3() {
  echo "Pinning all received packets on $NFP_IF to cpu 3"

  # stop irqbalance so it doesnt move around IRQs
  systemctl stop irqbalance || true

  # force nic to place all packets in same RX queue
  ethtool -L "$NFP_IF" combined 1 || true

  # disable RPS (Receive Packet Steering) (so kernel wont send packet processing to other CPUs)
  for q in /sys/class/net/$NFP_IF/queues/rx-*; do
    echo 0 | tee $q/rps_cpus >/dev/null
    echo 0 | tee $q/rps_flow_cnt >/dev/null 2>&1 || true
  done
  echo 0 | tee /proc/sys/net/core/rps_sock_flow_entries >/dev/null


  # get rx interrupt (IRQ) number for the nic queue (we know we only have rxtx-0)
  IRQ=$(awk -v iface="$NFP_IF" '$0 ~ iface && /rxtx-0/ { gsub(/:/,"",$1); print $1; exit }' /proc/interrupts)
  
  MASK=8 # 8 is mask for cpu 3, can set ut to this if we want other cpus: $(printf '%x' $((1<<3)))

  # pin rx interrupt (IRQ) for receive queue to cpu 3
  echo $MASK | tee /proc/irq/$IRQ/smp_affinity >/dev/null
}

# ensure everything is killed when ctrl c!!
trap 'kill ${SRV_PID-} 2>/dev/null; kill -INT ${PC_PID-} 2>/dev/null; umount "$OUT" 2>/dev/null || true' EXIT

# store pcap files in memory while running script to reduce disk pressure
umount "$OUT" 2>/dev/null || true
mount -t tmpfs -o size=3G tmpfs "$OUT"

echo "Disabling GRO and LRO on $NFP_IF"
ethtool -K "$NFP_IF" gro off lro off
ethtool -C "$NFP_IF" adaptive-rx off rx-usecs 0 rx-frames 1

pin_rx_to_cpu3

echo ""
echo "Save $NFP_IF stats before test"
ethtool -S "$NFP_IF" > "$OUT/ethtool_stats.before"

echo ""
echo "Starting iperf3 server (pinned to cpu 1)"
chrt -f 20 taskset -c 1 iperf3 -s > "$OUT/iperf_server.log" 2>&1 &
SRV_PID=$!

echo ""
echo "Starting packet capture (pinned to cpu 2)"
# (ignore ACKs for now, and pin to cpu 2 to keep cpu 3 as idle as possible. )
sudo chrt -f 20 netsniff-ng \
  --in "$NFP_IF" \
  --out "$OUT" \
  --interval 1GiB \
  --prefix cap- \
  --snaplen 128 \
  --filter "tcp and host $IP2 and dst port 5201" \
  --bind-cpu 2 \
  --notouch-irq \
  --sg \
  --silent \
  -T 0xa1b23c4d \          
  --ring-size 128MiB \
  > "$OUT/capture.log" 2>&1 &
PC_PID=$!
sleep 1

echo ""
echo "Starting sending data on netronome2"
# (2 flows, 4MB window size, 256KB read from buffer each send call, send output to client)
ssh -o StrictHostKeyChecking=no "$SENDER" \
  "iperf3 -c $IP1 -t $DUR -i 1 -w 4M -l 256K -P $FLOWS --get-server-output" \
  | tee "$OUT/iperf_client.log"

echo ""
echo "Data transmission done, stopping iperf3 server and capture"
kill $SRV_PID || true
kill -INT $PC_PID || true
wait $PC_PID || true

echo ""
echo "Save $NFP_IF stats after test"
ethtool -S "$NFP_IF" > "$OUT/ethtool_stats.after"

echo "Copying output to $PERSIST"
cp -a "$OUT"/cap-* "$OUT"/*.log "$PERSIST"/

umount "$OUT"

echo "Test finished sucessfully, output in $PERSIST"
