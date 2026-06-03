#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <condition_label>"
  echo "Example: $0 tso"
  exit 2
fi

CONDITION="$1"
RESULTS_ROOT="results/${CONDITION}"
OUTFILE="cwnd_summary_${CONDITION}.txt"

QUEUE_LENS=(8 16 24 32 48 64 128 256 512 1024)

for qlen in "${QUEUE_LENS[@]}"; do
  qdir="${RESULTS_ROOT}/q${qlen}"
  if [[ ! -d "${qdir}" ]]; then
    echo "${qlen} MISSING_DIR" >> "${OUTFILE}"
    continue
  fi

  mapfile -t files < <(ls -1 "${qdir}/${CONDITION}_q${qlen}_run"*.txt 2>/dev/null | sort -V || true)

  # Build row: qlen <val1> <val2> ...
  row="${qlen}"
  for f in "${files[@]}"; do
    val="$(tr -d ' \t\r\n' < "$f")"
    if [[ -z "${val}" ]]; then
      val="NA"
    fi
    row+=" ${val}"
  done

  echo "${row}" >> "${OUTFILE}"
done

echo "Wrote ${OUTFILE}"