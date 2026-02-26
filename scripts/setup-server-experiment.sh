#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp2s0np0"
# 1 = no TSO, 2 = TSO, 3 = TSO + our solution
TREATMENT=1

# direct-link -> 2, internet -> 4 flows, datacenter -> 8 flows
CONNECTION_MODE="internet" 

CCA="cubic" # cubic, dctcp, bbr

QDISC="fq" # fq, fq_codel  (in future maybe pfifo_fast, cake)

for arg in "$@"; do
  case "$arg" in
    --no-tso)       TREATMENT=1 ;;
    --tso)          TREATMENT=2 ;;
    --tso-pacing)   TREATMENT=3 ;;
    --cubic)        CCA="cubic" ;;
    --dctcp)        CCA="dctcp" ;;
    --bbr)          CCA="bbr" ;;
    --fq)           QDISC="fq" ;;
    --fq-codel)     QDISC="fq_codel" ;;
    --help)         echo " usage (--help --no-tso --tso --tso-pacing --cubic --dctcp --bbr --fq --fq-codel)"; exit 0 ;;
    *) echo "Unknown argument: $arg, usage (--help --no-tso --tso --tso-pacing --cubic --dctcp --bbr --fq --fq-codel)"; exit 1 ;;
  esac
done

# ======= Load driver/firmware =======
if [ "$TREATMENT" = 3 ]; then
    ./build-nfp.sh 
else
    ./build-nfp.sh --org
fi

# ======= Configure machine =======
cpufreq-set -g performance

if [ "$TREATMENT" = 1 ]; then
    ethtool -K "$DEV" tso off gso off
else
    ethtool -K "$DEV" tso on gso on
fi

sysctl net.ipv4.tcp_congestion_control="$CCA"
if [ "$CCA" = "dctcp" ]; then
    sysctl -w net.ipv4.tcp_ecn=1
else
    sysctl -w net.ipv4.tcp_ecn=2
fi

tc qdisc replace dev "$DEV" root "$QDISC"

