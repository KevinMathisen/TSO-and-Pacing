#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

TREATMENT=""
RUNS_PER_SETUP=20

for arg in "$@"; do
  case "$arg" in
    --no-tso)       TREATMENT="no-tso" ;;
    --tso)          TREATMENT="tso" ;;
    --tso-pacing)   TREATMENT="tso-pacing" ;;
    --help)         echo " usage (--no-tso|--tso|--tso-pacing)"; exit 0 ;;
    *) echo "Unknown argument: $arg, usage (--no-tso|--tso|--tso-pacing)"; exit 1 ;;
  esac
done

[ -z "$TREATMENT" ] || { echo "Missing TREATMENT: $TREATMENT"; exit 1; }

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

# run experiments for all connection modes (all with fq)
MODES=(--direct-link --internet --datacenter --datacenter-hc)

for mode in "${MODES[@]}"; do
  run_setup "$mode" --fq "$TREATMENT"
done

# run experiment with fq_codel and direct link
run_setup --direct-link --fq-codel "$TREATMENT"



echo "================================================================="
echo ""
echo "All experiments for $TREATMENT ran!!"
echo ""
echo "================================================================="