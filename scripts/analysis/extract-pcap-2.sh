#!/bin/bash
set -euo pipefail


SERVER=fleming
SERVER_DIR="~/master/TSO-and-Pacing/scripts/experiment/runs/"

RUNS_NUM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs-amt)
      RUNS_NUM=$2; shift 2 ;;
    --help)
      echo "usage: $0 --date YYYYMMDD --runs-amt N"
      exit 0 ;;
    *)
      echo "Unknown argument: $1"; exit 1 ;;
  esac
done

[[ "$RUNS_NUM" -gt 0 ]] || { echo "Must specify --runs-amt N"; exit 1; }

ts="$(date +%Y%m%d-%H%M)"
RUN_DIR="./run-$ts"
DUMP_DIR="$RUN_DIR/dump"
AGG_DIR="$RUN_DIR/aggregates"


mkdir -p "$RUN_DIR" "$DUMP_DIR" "$AGG_DIR"
echo "Placing metrics and data in $RUN_DIR"

echo ""
echo "Retrieving logs and packet captures from $SERVER:$SERVER_DIR..."
# Assume server only has directories we need, so copy all!
ssh "$SERVER" "cd $SERVER_DIR && tar -czf - ." | tar -xzf - -C "$DUMP_DIR/"

# For each of the predefined combinations
RUN_TYPES=(
  direct-link_fq_no-tso
  direct-link_fq_tso
  direct-link_fq_tso-pacing 
  
  datacenter_fq_no-tso
  datacenter_fq_tso
  datacenter_fq_tso-pacing 

  internet_fq_no-tso
  internet_fq_tso
  internet_fq_tso-pacing

  direct-link_fq_codel_no-tso
  direct-link_fq_codel_tso
  direct-link_fq_codel_tso-pacing 
)

for run_type in "${RUN_TYPES[@]}"; do
  (
    echo ""
    echo "Processing run type: $run_type"

    OUT_DIR="$AGG_DIR/$run_type"
    mkdir -p "$OUT_DIR"

    PACKETS_CSV="$OUT_DIR/packets.csv"
    METRICS_CSV="$OUT_DIR/metrics.csv"
    RTT_JSON="$OUT_DIR/rtt.json"
    THROUGHPUT_JSON="$OUT_DIR/throughput.json"
    QLEN_JSON="$OUT_DIR/qlen.json"

    # initial aggregate files for run type
    echo 'run_name,run_num,stream_id,tcp_len,p4_timestamp_ns,p4_timestamp_prev_ns' > "$PACKETS_CSV"
    echo 'run_name,run_num,throughput_bps,cpu_sender,cpu_receiver,retransmissions,fast_retransmissions,out_of_order,lost_segments,server_drops,client_drops,client_ifb_drops,external_drops,dumpcap_drops' > "$METRICS_CSV"
    echo '[]' > "$RTT_JSON"
    echo '[]' > "$THROUGHPUT_JSON"
    echo '{}' > "$QLEN_JSON"

    for (( run_num=1; run_num<=RUNS_NUM; run_num++ )); do
      echo "  $run_type: Run $run_num"

      # Assume one dir matching <run_type>_run_<run_num>________<timestamp>
      # NEW dir naming: <timestamp>___<run_type>_run_<run_num>
      RUN_PATH="$(find "$DUMP_DIR" -maxdepth 1 -type d -name "*_${run_type}_run_${run_num}*" | head -n1)"
      RUN_NAME="${run_type}_run_${run_num}"

      TMP_DIR="$OUT_DIR/tmp_run_${run_num}"
      mkdir -p "$TMP_DIR"

      PCAP_IN="$(find "$RUN_PATH" -maxdepth 1 -name 'capture_*.pcapng' | head -n1)"
      RAW_CSV="$TMP_DIR/tshark_raw.csv"
      PARSED_CSV="$TMP_DIR/packets_parsed.csv"
      METRICS_ROW="$TMP_DIR/metrics_row.csv"

      # Convert pcap to csv using thsark to extract following for timestamp analysis
      tshark -n -r "$PCAP_IN" \
        -T fields -E header=y -E separator=, -E quote=d \
        -o tcp.desegment_tcp_streams:FALSE \
        -o ip.defragment:FALSE -o ipv6.defragment:FALSE \
        -o tcp.check_checksum:FALSE \
        -e frame.time_epoch -e frame.number \
        -e tcp.stream -e tcp.seq -e tcp.len \
        -e tcp.analysis.retransmission -e tcp.analysis.fast_retransmission \
        -e tcp.analysis.out_of_order -e tcp.analysis.lost_segment \
        -e data.data \
        > "$RAW_CSV"

      # Run parse-p4sta-timestamps.py to extract timestamps from tcp payload
      # payload -> extract first 48 bit timestamp by finding signature 0x0f in tcp options, then extacting 48 bit
      python3 parse-p4sta-timestamps.py "$RAW_CSV" "$PARSED_CSV" "$RUN_NAME" "$run_num"
      # Resulting csv contains: run_name,run_num,stream_id,tcp_len,p4_timestamp_ns

      # Ensure packets are sorted (column 5 has timestamp)
      { head -n1 "$PARSED_CSV"; tail -n +2 "$PARSED_CSV" | LC_ALL=C sort -t, -k5,5n; } > "$PARSED_CSV.sorted"
      mv "$PARSED_CSV.sorted" "$PARSED_CSV"

      tail -n +2 "$PARSED_CSV" >> "$PACKETS_CSV"

      # Run metrics.py to use .tmp csv and other logs/counters to generate metrics.csv
      python3 metrics.py "$RUN_PATH" "$RAW_CSV" "$METRICS_ROW" "$RUN_NAME" "$run_num" "$QLEN_JSON"

      tail -n +2 "$METRICS_ROW" >> "$METRICS_CSV"

      # Run rrt.py to use 'server_iperf_client.json' to generate an array of RTTS and THROUGHPUT over time
      python3 rtt.py "$RUN_PATH/server_iperf_client.json" "$RTT_JSON"
      python3 throughput.py "$RUN_PATH/server_iperf_client.json" "$THROUGHPUT_JSON"
    done
  ) &
done

wait

echo ""
echo "==================================================="
echo "Aggregate outputs for all runs written to $AGG_DIR!"
echo "==================================================="
echo ""


# We now have packets.csv, metrics.csv, and rrt.json which is aggregate data from all runs for each setup/solution combination

# Run script to generate plots to compare the different solutions for EACH setup
cd $RUN_DIR
python3 ../generate-plots.py

echo ""
echo "====================================="
echo "We are done analyzing experiment $ts!"
echo "====================================="