#!/bin/bash
set -euo pipefail

SERVER=net1
#SERVER=muninn

NET1_DIR="/var/tmp/tcp-test-output"
OUT_DIR="./test-data"
IP="10.111.0.3"
PORT=5201
SNAPLEN=128

ts="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUT_DIR/run-$ts"

if [ $# -eq 1 ]; then
  RUN_DIR="$OUT_DIR/$1"
fi

mkdir -p "$RUN_DIR"
echo "Placing metrics and data in $RUN_DIR"

CSV_OUT="$RUN_DIR"/packets.csv

echo ""
echo "Extract headers from pcap files on net1:$NET1_DIR"

ssh $SERVER NET1_DIR="$NET1_DIR" SNAPLEN="$SNAPLEN" 'bash -s' <<'REMOTE'
set -euo pipefail
cd "$NET1_DIR"
shopt -s nullglob
rm -f merged-pruned.pcap merged-pruned.pcap.gz
pcaps=(cap-*.pcap)
mergecap -s "$SNAPLEN" -w merged-pruned.pcap "${pcaps[@]}"
gzip -f merged-pruned.pcap
rm -f -- *.pcap
ls -lth merged-pruned.pcap.gz || true
REMOTE

echo ""
echo "Get files from netronome puter"
rsync -a $SERVER:"$NET1_DIR"/ "$RUN_DIR"/

echo ""
echo "Decompress pcap"
gunzip -f "$RUN_DIR/merged-pruned.pcap.gz"

echo ""
echo "Create CSV from pcap"
tshark -n -r "$RUN_DIR/merged-pruned.pcap" \
  -T fields -E header=y -E separator=, \
  -o tcp.desegment_tcp_streams:FALSE \
  -o ip.defragment:FALSE -o ipv6.defragment:FALSE \
  -o tcp.check_checksum:FALSE \
  -e frame.time_epoch -e frame.len -e tcp.stream -e tcp.seq -e tcp.len \
  -e tcp.analysis.retransmission -e tcp.analysis.out_of_order -e tcp.analysis.lost_segment \
  > "$CSV_OUT.tmp"

echo "(ensuring packets are sorted)"
{ head -n1 "$CSV_OUT.tmp"; tail -n +2 "$CSV_OUT.tmp" | LC_ALL=C sort -t, -k1,1n; } > "$CSV_OUT"
rm -f "$CSV_OUT.tmp"

echo ""
echo "Generating metrics from csv"
cd "$RUN_DIR"

if [ $# -eq 1 ]; then
  python3 ./../../analyze_tcp_capture.py "$1"
else
  python3 ./../../analyze_tcp_capture.py
fi

echo ""
