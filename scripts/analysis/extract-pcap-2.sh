#!/bin/bash
set -euo pipefail


SERVER=fleming
SERVER_DIR="~/master/TSO-and-Pacing/scripts/experiment/runs/"

RUNS_DATE=""
RUNS_NUM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      RUNS_DATE="$2"; shift 2 ;;
    --runs-amt)
      RUNS_NUM=$2; shift 2 ;;
    --help)
      echo "usage: $0 --date YYYYMMDD --runs-amt N"
      exit 0 ;;
    *)
      echo "Unknown argument: $1"; exit 1 ;;
  esac
done


ts="$(date +%Y%m%d-%H%M)"
RUN_DIR="./run-$ts"
DUMP_DIR="$RUN_DIR/tmp"

SERVER_WILDCARD_DIRS="*_RUNS_DATE_*"


mkdir -p "$RUN_DIR"
mkdir -p "$DUMP_DIR"
echo "Placing metrics and data in $RUN_DIR"

echo ""
echo "Retrieving logs and packet captures from $SERVER:$SERVER_DIR..."

# Retrieve packet traces from testbed...
# TODO: use scp to place all directories in $SERVER_DIR which matches SERVER_WILDCARD_DIRS into DUMP_DIR

# ----- For each packet trace/experiment run -----
# For each setup (direct link/datacenter/internet)
#   For each solution (no-tso/tso/tso-pacing)
#     Use all runs to generate:
#       - tshark to ONE csv file (packets.csv) containing columns (one row per packet):
#           1) TCP stream (should be made unique by us accross all flows, e.g. by adding run_num*10 to it)
#           2) TCP len
#           3) P4 timestamp extracted
#               (packets.csv comes from *.pcapng file in run dir)
#
#       - Another CSV file (metrics.csv), containing columns (one row per run):
#           1) Average throughput (from iperf.json)
#           2,3,4) Total packet loss/reordering/ooo packets as reported by tshark based on pcap
#                (again, from  *.pcapng file in run dir)
#           6) Server NIC ip link reported packet loss (before/after diff in packet drops)
#               (from file server_iplink_before.txt and server_iplink_after.txt)
#           7) Client NIC ip link reported packet loss
#               (from file client_iplink_before.txt and client_iplink_after.txt)
#           8) Client IFB tc qdisc reported packet loss
#               (from file client_tc_ifb0_before.txt and client_tc_ifb0_after.txt)
#           9) External-host NIC ip link reported packet loss
#               (from file axternal_iplink_before.txt and external_iplink_after.txt)
#           10) External-host dumpcap reported packet loss
#               (from file server_iplink_before.txt and server_iplink_after.txt)
#
#       - A json file containing the reported RTT throughout the runs, so an array of number values
#           Each value is retrieved from server_iperf_client.json/intervals/[]/streams/[]/rtt

# (directories placed in $SERVER_DIR)
# <setup>_<solution>_run_<run_num>_____<YYYYMMDD_HHMM>

# direct-link_fq_no-tso_run_x
# direct-link_fq_tso_run_x
# direct-link_fq_tso-pacing_run_x

# datacenter_fq_no-tso_run_x
# datacenter_fq_tso_run_x
# datacenter_fq_tso-pacing_run_x

# datacenter-hc_fq_no-tso_run_x
# datacenter-hc_fq_tso_run_x
# datacenter-hc_fq_tso-pacing_run_x

# internet_fq_no-tso_run_x
# internet_fq_tso_run_x
# internet_fq_tso-pacing_run_x



# ========= For future use ==========

# Convert pcap to csv using thsark to extract following for timestamp analysis
#   1) tcp.len, 2) tcp.stream, and 3) timestamp in tcp options
# And to extract retrans, out of order, and lost segments
tshark -n -r "$PCAP_IN" \
  -T fields -E header=y -E separator=, -E quote=d \
  -o tcp.desegment_tcp_streams:FALSE \
  -o ip.defragment:FALSE -o ipv6.defragment:FALSE \
  -o tcp.check_checksum:FALSE \
  -e frame.time_epoch -e frame.number \
  -e tcp.stream -e tcp.seq -e tcp.len -e tcp.options \
  -e tcp.analysis.retransmission -e tcp.analysis.fast_retransmission \
  -e tcp.analysis.out_of_order -e tcp.analysis.lost_segment \
  > "$CSV_OUT.tmp"

# Run python script parse-p4sta-timestamps.py to extract timestamp 1 from tcp options
# tcp.options -> first 48 bit timestamp by finding signature 0x0f in tcp options, then extacting 48 bit
python3 parse-p4sta-timestamps.py "$CSV_OUT.raw" "$CSV_OUT"
# Resulting csv contains 1) tcp.len, 2) tcp.stream, and 3) timestamp

# Ensure packets are sorted (column 3 has timestamp)
{ head -n1 "$CSV_OUT"; tail -n +2 "$CSV_OUT" | LC_ALL=C sort -t, -k3,3n; } > "$CSV_OUT.sorted"
mv "$CSV_OUT.sorted" "$CSV_OUT"


# Run python script metrics.py to use .tmp csv and other logs/counters to generate metrics.csv


# Run python script rrt.py to use 'server_iperf_client.json' to generate an array of RTTS over time (simple one dimentional array)


# -------
# We now have packets.csv, metrics.csv, and rrt.json which is aggregate data from all runs for each setup/solution combination
#  Next is to generate plots comparing the solutions

# Run python script analyze-experiments.py which generates plots to compare the different solutions for EACH setup:
# - Throughput distribution for each solution (boxplot)
# - RTT distribution (boxplot)
# - Timeseries of packets of first 5 ms of packet capture. Compared the first tcp stream from each solution
# - Distribution of packets recieved each 40us bin (e.g. we received 50 packets in a single 40us bin 10 times). (Violin plot)
# - Distribution of inter-departure time of packets (i.e. inter-departure times of packets within a flow/stream) (CDF)
#   - Also distribution of idt of packets from all flows (i.e. inter-flow bursts) (CDF)
