#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi


DEV="enp3s0np0"


# ======= Load driver/firmware =======
# NB: assume correct driver/firmware already loaded

# ======= Configure machine =======
cpufreq-set -g performance

ethtool -K "$DEV" tso on gso on
tc qdisc replace dev "$DEV" root fq

# Set lower mtu to allow space for P4 timestamps
ip link set dev "$DEV" mtu 1480


echo "Configured for Datacenter timestamping (MTU, tso/gso on, fq/pacing)"