#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp2s0np0"
CONNECTION_MODE="direct-link"  # direct-link, internet, datacenter, or datacenter-high-contention 

for arg in "$@"; do
  case "$arg" in
    --direct-link)   CONNECTION_MODE="direct-link" ;;
    --internet)      CONNECTION_MODE="internet" ;;
    --datacenter)    CONNECTION_MODE="datacenter" ;;
    --datacenter-hc) CONNECTION_MODE="datacenter-high-contention" ;;
    --help)         echo " usage (--help --direct-link --internet --datacenter --datacenter-hc)"; exit 0 ;;
    *) echo "Unknown argument: $arg, usage (--help --direct-link --internet --datacenter --datacenter-hc)"; exit 1 ;;
  esac
done


# disable gro to make ingress qdisc operate on individual packets, 
#  more closely mirroring a real network device.
ethtool -K $DEV gro off
# TODO: know still achieve line rate on IFI machines for this, but need to test on darmstadt.

# reset
tc qdisc del dev $DEV root    2>/dev/null || true
tc qdisc del dev $DEV ingress 2>/dev/null || true
tc qdisc del dev ifb0 root    2>/dev/null || true
sysctl -w net.ipv4.tcp_congestion_control=cubic
sysctl -w net.ipv4.tcp_ecn=0

if [ "$CONNECTION_MODE" != "direct-link" ]; then 
    # create/enable IFB
    modprobe ifb numifbs=1
    ip link add ifb0 type ifb 2>/dev/null || true
    ip link set ifb0 up

    # redirect ingress to ifb0
    tc qdisc add dev $DEV handle ffff: ingress
    tc filter add dev $DEV parent ffff: protocol ip u32 match u32 0 0 \
          action mirred egress redirect dev ifb0
fi

# Does not provide us with that much useful data, but is interesting to see that we dont always show benefit
if [ "$CONNECTION_MODE" = "internet" ]; then 
    # egress 50 ms delay
    tc qdisc replace dev $DEV root netem delay 50ms limit 5000

    # ---- ingress 1 Gbps ---- 
    RATE=1gbit

    # HTB
    tc qdisc replace dev ifb0 root handle 1: htb default 10
    tc class replace dev ifb0 parent 1: classid 1:1  htb rate $RATE ceil $RATE
    tc class replace dev ifb0 parent 1:1 classid 1:10 htb rate $RATE ceil $RATE

    # Leaf fq_codel
    tc qdisc replace dev ifb0 parent 1:10 handle 10: fq_codel \
      noecn target 5ms interval 50ms memory_limit 16mb

    echo "Interface $DEV configured with Internet (50 ms RTT, 1 Gbps)"

elif [[ "$CONNECTION_MODE" = "datacenter" || "$CONNECTION_MODE" = "datacenter-high-contention" ]]; then
    # egress no delay
    # ...

    # ---- ingress 4 Gbps ----
    RATE=4gbit

    tc qdisc replace dev ifb0 root handle 1: htb default 10
    tc class replace dev ifb0 parent 1: classid 1:1  htb rate $RATE ceil $RATE
    tc class replace dev ifb0 parent 1:1 classid 1:10 htb rate $RATE ceil $RATE

    # Leaf fq_codel (shallow ecn marking)
    tc qdisc replace dev ifb0 parent 1:10 handle 10: fq_codel \
      ecn target 2ms interval 20ms ce_threshold 200us memory_limit 4mb

    if [ "$CONNECTION_MODE" = "datacenter-high-contention" ]; then
      tc qdisc replace dev ifb0 parent 1:10 handle 10: fq_codel \
        ecn target 2ms interval 20ms ce_threshold 200us memory_limit 200kb
    fi

    sysctl -w net.ipv4.tcp_congestion_control=dctcp
    sysctl -w net.ipv4.tcp_ecn=1

    echo "Interface $DEV configured with Datacenter (no delay, 8 Gbps)"

else 
    # egress no delay
    # ingress no rate-limit

    echo "Interface $DEV configured with Direct link (no delay, no rate limit)"
fi

cpufreq-set -g performance
echo "Also set CPU freq to performance (use 'cpufreq-set -g powersave' to revert)"

echo ""
echo "You can now start iperf server... (iperf3 -s)"
echo "Use 'tc -s qdisc show dev ifb0' to view ingress stats"


# See:
# https://std.rocks/gnulinux_network_traffic_control.html