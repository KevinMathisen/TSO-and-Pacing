#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

RUNS_PER_SETUP=20

# run experiments for all speeds
# 1 2 4 8
SPEEDS=(250 500 1000 2000)
for speed in "${SPEEDS[@]}"; do

  echo "============================================================"
  echo "Setup: speed=$speed"
  echo "============================================================"

  for ((i=1; i<=RUNS_PER_SETUP; i++)); do
    ./run-experiment-external-capture.sh "$i" "$speed"
    sleep 5
  done
done

echo "================================================================="
echo ""
echo "All experiments ran!!"
echo ""
echo "================================================================="