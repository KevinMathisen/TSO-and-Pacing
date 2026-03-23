#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp2s0np0"
# 1 = no TSO, 2 = TSO, 3 = TSO + our solution
TREATMENT=1

CONNECTION_MODE="direct-link"  # direct-link, internet, datacenter
# direct-link -> 2 flows, internet -> 4 flows, datacenter -> 4 flows

CCA="cubic" # cubic, dctcp, bbr

QDISC="fq" # fq, fq_codel  (in future maybe pfifo_fast, cake)

for arg in "$@"; do
  case "$arg" in
    --no-tso)       TREATMENT=1 ;;
    --tso)          TREATMENT=2 ;;
    --tso-pacing)   TREATMENT=3 ;;
    --direct-link)   CONNECTION_MODE="direct-link" ;;
    --internet)      CONNECTION_MODE="internet" ;;
    --datacenter)    CONNECTION_MODE="datacenter" ;;
    --fq)           QDISC="fq" ;;
    --fq-codel)     QDISC="fq_codel" ;;
    --help)         echo " usage (--help --no-tso --tso --tso-pacing --direct-link --internet --datacenter --fq --fq-codel)"; exit 0 ;;
    *) echo "Unknown argument: $arg, usage (--help --no-tso --tso --tso-pacing --direct-link --internet --datacenter --fq --fq-codel)"; exit 1 ;;
  esac
done

# ======= Load driver/firmware =======
# NB: assume correct driver/firmware already loaded

# ======= Configure machine =======
cpufreq-set -g performance

if [ "$TREATMENT" = 1 ]; then
    ethtool -K "$DEV" tso off gso off
else
    ethtool -K "$DEV" tso on gso on
fi

sysctl -w net.ipv4.tcp_congestion_control="$CCA"
if [ "$CCA" = "dctcp" ]; then
    sysctl -w net.ipv4.tcp_ecn=1
else
    sysctl -w net.ipv4.tcp_ecn=0
fi

tc qdisc replace dev "$DEV" root "$QDISC"

if [ "$CONNECTION_MODE" = "internet" ]; then 
    echo "Configured for Internet (cubic)"

elif [[ "$CONNECTION_MODE" = "datacenter" ]]; then
    echo "Configured for Datacenter (cubic)"

else 
    echo "Configured for Direct-link (cubic)"

fi