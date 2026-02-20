#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp2s0np0"
CONNECTION_MODE="internet"  # internet or datacenter


# reset
tc qdisc del dev $DEV root    2>/dev/null || true
tc qdisc del dev $DEV ingress 2>/dev/null || true
tc qdisc del dev ifb0 root    2>/dev/null || true

if [ "$CONNECTION_MODE" = "internet" ]; then 
    # egress 50 ms delay + 500 Mbps
    tc qdisc replace dev $DEV root netem delay 50ms rate 500mbit limit 5000
    # check if leaky or token bucket (netem htb?)
    # delay + rate limit interacts poorly (use same buffer)
    # check if separate modules

    # create/enable IFB
    modprobe ifb numifbs=1
    ip link add ifb0 type ifb 2>/dev/null || true
    ip link set ifb0 up

    # redirect ingress to ifb0
    tc qdisc add dev $DEV handle ffff: ingress
    tc filter add dev $DEV parent ffff: protocol ip u32 match u32 0 0 \
    action mirred egress redirect dev ifb0

    # ingress 50 ms delay + 500 Mbps
    tc qdisc replace dev ifb0 root netem delay 50ms rate 500mbit limit 5000

    echo "Interface $DEV configured with 100 ms RTT and 500 Mbps bandwidth"
else


    echo "Interface $DEV configured fq_codel (default behavior)"
fi

cpufreq-set -g performance
echo "Also set CPU freq to performance (use 'cpufreq-set -g powersave' to revert)"

echo ""
echo "You can now start iperf server... (iperf3 -s)"


# See:
# https://std.rocks/gnulinux_network_traffic_control.html