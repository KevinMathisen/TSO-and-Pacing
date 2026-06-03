#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <speed_mbps> # 250, 500, 1000, 2000"
    exit 2
fi

MBPS="$1"
RATE="${MBPS}mbit"
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

# ---- ingress 4 Gbps ---- 
QLEN=3000

tc qdisc add dev ifb0 root fq \
    maxrate "$RATE" \
    limit "$QLEN" \
    flow_limit "$QLEN"

echo "Interface $DEV configured with Datacenter (${RATE}, queue length ${QLEN})"

cpufreq-set -g performance