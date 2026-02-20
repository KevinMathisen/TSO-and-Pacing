#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp2s0np0"
# 1 = no TSO, 2 = TSO, 3 = TSO + our solution
TREATMENT=1

# internet -> 2 flows, datacenter -> 4 flows
CONNECTION_MODE="internet" 

CCA="CUBIC" # CUBIC or BBR

QDISC="fq" # fq (in future, maybe pfifo_fast, fq_codel, cake)

# ======= Load driver/firmware =======
if [ "$TREATMENT" = 3 ]; then
    ./build-nfp.sh 
else
    ./build-nfp.sh --org
fi

# ======= Configure machine =======
cpufreq-set -g performance

if [ "$TREATMENT" = 1 ]; then
    ethtool -K "$DEV" tso off
else
    ethtool -K "$DEV" tso on
fi

if [ "$CCA" = "BBR" ]; then
    sysctl net.ipv4.tcp_congestion_control=bbr
else
    sysctl net.ipv4.tcp_congestion_control=cubic
fi

tc qdisc replace dev "$DEV" root "$QDISC"

