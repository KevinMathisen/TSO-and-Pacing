#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

RUNS_PER_SETUP=20

run_setup () {
  local mode="$1"
  local qdisc="$2"
  local treatment="$3"

  echo "============================================================"
  echo "Setup: mode=$mode qdisc=$qdisc treatment=$treatment"
  echo "============================================================"

  for ((i=1; i<=RUNS_PER_SETUP; i++)); do
    ./run-one-experiment.sh --run-num "$i" "$mode" "$qdisc" "$treatment"
  done
}

# all treatment + connection modes combination (all with fq)
MODES=(--direct-link --internet --datacenter --datacenter-hc)
TREATMENTS=(--no-tso --tso --tso-pacing)

for mode in "${MODES[@]}"; do
  for tr in "${TREATMENTS[@]}"; do
    run_setup "$mode" --fq "$tr"
  done
done

for tr in --tso --tso-pacing; do
  run_setup --direct-link --fq-codel "$tr"
done


# ...

echo "================================================================="
echo ""
echo "All experiments ran!!"
echo ""
echo "================================================================="