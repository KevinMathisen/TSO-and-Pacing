#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

DEV="enp1s0np0"

# Ensure no lro/gro
ethtool -K enp1s0np0 gro off

# Set cpu to performance
cpufreq-set -g performance