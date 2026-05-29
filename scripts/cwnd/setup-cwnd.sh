#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <qlen> # 8, 16, 24, 32, 48, 64, 128, 256, 512"
    exit 2
fi

QLEN="$1"
DEV="enp1s0np0"

ethtool -K "$DEV" gro off lro off gso off tso off

# reset
tc qdisc del dev $DEV root    2>/dev/null || true
tc qdisc del dev $DEV ingress 2>/dev/null || true
tc qdisc del dev ifb0 root    2>/dev/null || true

# create/enable IFB
modprobe ifb numifbs=1
ip link add ifb0 type ifb 2>/dev/null || true
ip link set ifb0 up

# redirect ingress to ifb0
tc qdisc add dev $DEV handle ffff: ingress
tc filter add dev $DEV parent ffff: protocol ip u32 match u32 0 0 \
        action mirred egress redirect dev ifb0

# egress 20 ms delay
tc qdisc replace dev $DEV root netem delay 20ms limit 50000

# ---- ingress 1 Gbps ---- 
RATE=1000mbit

tc qdisc add dev ifb0 root fq \
    maxrate "$RATE" \
    limit "$QLEN" \
    flow_limit "$QLEN"

echo "Interface $DEV configured with Internet (50 ms RTT, 1 Gbps)"

cpufreq-set -g performance
echo "Also set CPU freq to performance (use 'cpufreq-set -g powersave' to revert)"
