#!/bin/bash
set -euo pipefail


SERVER=net1
SERVER_DIR="~/"

ts="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="./run-$ts"
DUMP_DIR="$RUN_DIR/tmp"


mkdir -p "$RUN_DIR"
echo "Placing metrics and data in $RUN_DIR"

echo ""
echo "Retrieving logs and packet captures from $SERVER:$SERVER_DIR..."

# Retrieve packet traces from testbed...
# TODO

# --- For each packet trace/experiment run ---

PCAP_IN="$RUN_DIR/capture.pcapng"
CSV_OUT="$RUN_DIR/packets.csv"


# parse name to make it unique
# TODO

# Convert pcap to csv using thsark to extract 
#   1) tcp.len, 2) tcp.stream, and 3) timestamp in tcp options
tshark -n -r "$PCAP_IN" \
  -T fields -E header=y -E separator=, -E quote=d \
  -o tcp.desegment_tcp_streams:FALSE \
  -o ip.defragment:FALSE -o ipv6.defragment:FALSE \
  -o tcp.check_checksum:FALSE \
  -e tcp.stream \
  -e tcp.len \
  -e tcp.options \
  > "$CSV_OUT.raw"

# Run python script to extract timestamp 1 from tcp options
# tcp.options -> first 48 bit timestamp
#       by finding signature 0x0f in tcp options, then extacting 48 bit
python3 parse-p4sta-timestamps.py "$CSV_OUT.raw" "$CSV_OUT"

# Ensure packets are sorted (column 3 has timestamp)
{ head -n1 "$CSV_OUT"; tail -n +2 "$CSV_OUT" | LC_ALL=C sort -t, -k3,3n; } > "$CSV_OUT.sorted"
mv "$CSV_OUT.sorted" "$CSV_OUT"

# Run Python script to generate summary and plots for this run
# TODO...