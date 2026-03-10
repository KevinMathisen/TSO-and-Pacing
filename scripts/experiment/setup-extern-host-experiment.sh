#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp2s0np0"

# Ensure no lro/gro
ethtool -K "$DEV" lro off gro off

# Set cpu to performance
cpufreq-set -g performance