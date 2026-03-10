#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp1s0np0"
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

    # ---- ingress 2 Gbps ---- 

    # 500 Mbps per flow -> 2 Gbps total
    # Max 10000 pkts -> 10000*1500 B = 15 MB buffer
    tc qdisc replace dev ifb0 root fq \
      maxrate 500mbit \
      limit 10000 flow_limit 4000

    echo "Interface $DEV configured with Internet (50 ms RTT, 1 Gbps)"

elif [[ "$CONNECTION_MODE" = "datacenter" || "$CONNECTION_MODE" = "datacenter-high-contention" ]]; then
    # egress no delay
    # ...

    # ---- ingress 4 Gbps ----

    # 1 Gbps per flow -> 4 Gbps total
    # Max 3000 pkts -> 3000*1500 B = 4.5 MB buffer
    tc qdisc replace dev ifb0 root fq \
      maxrate 1gbit ce_threshold 90us \
      limit 3000 flow_limit 4000

    if [ "$CONNECTION_MODE" = "datacenter-high-contention" ]; then
      # Max 200 pkts -> 200*1500 B = 300 kB buffer
      tc qdisc replace dev ifb0 root fq \
        maxrate 1gbit ce_threshold 90us \
        limit 200 flow_limit 4000
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