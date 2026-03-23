#!/bin/bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

# ============== Usage ===========
# Ensure you have ssh access to client and external host, and can run sudo there with no password.



# ============== Ensure everything killed on exit function ===========
CLIENT_IPERF_PID=""
EXTERNAL_DUMPCAP_PID=""
SERVER_IPERF_PID=""

cleanup() {
  set +e
  if [[ -n "$SERVER_IPERF_PID" ]]; then
    kill "$SERVER_IPERF_PID" 2>/dev/null
  fi
  if [[ -n "$CLIENT_IPERF_PID" ]]; then
    ssh "$CLIENT_SSH" "sudo kill $CLIENT_IPERF_PID" 2>/dev/null
  else
    ssh "$CLIENT_SSH" "sudo pkill -f 'iperf3 -s'" 2>/dev/null
  fi
  if [[ -n "$CLIENT_BPF_PID" ]]; then
    ssh "$CLIENT_SSH" "sudo kill -INT $CLIENT_BPF_PID" 2>/dev/null
  fi
  if [[ -n "$EXTERNAL_DUMPCAP_PID" ]]; then
    ssh "$EXTERNAL_SSH" "sudo kill $EXTERNAL_DUMPCAP_PID" 2>/dev/null
  else
    ssh "$EXTERNAL_SSH" "sudo pkill -f dumpcap" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM


# ========= Functions for setup ==========

setup_server() {
  local tso_flag mode_flag qdisc_flag
  case "$TREATMENT" in
    no-tso) tso_flag="--no-tso" ;;
    tso) tso_flag="--tso" ;;
    tso-pacing) tso_flag="--tso-pacing" ;;
  esac
  case "$CONNECTION_MODE" in
    direct-link) mode_flag="--direct-link" ;;
    internet) mode_flag="--internet" ;;
    datacenter) mode_flag="--datacenter" ;;
    datacenter-hc) mode_flag="--datacenter-hc" ;;
  esac
  case "$QDISC" in
    fq) qdisc_flag="--fq" ;;
    fq_codel) qdisc_flag="--fq-codel" ;;
  esac

  "$SCRIPT_PATH"./setup-server-experiment "$tso_flag" "$mode_flag" "$qdisc_flag"
}

setup_client() {
  local mode_flag
  case "$CONNECTION_MODE" in
    direct-link) mode_flag="--direct-link" ;;
    internet) mode_flag="--internet" ;;
    datacenter) mode_flag="--datacenter" ;;
    datacenter-hc) mode_flag="--datacenter-hc" ;;
  esac

  ssh -o BatchMode=yes "$CLIENT_SSH" "sudo $SCRIPT_PATH/setup-client-experiment.sh $mode_flag"
  # ensure no running iperf3
  ssh "$CLIENT_SSH" "sudo pkill -f 'iperf3 -s'" 2>/dev/null || true
}

setup_external() {
  ssh -o BatchMode=yes "$EXTERNAL_SSH" "sudo $SCRIPT_PATH/setup-external-host-experiment"
}

# ========= Functions for saving interface stats ==========

save_server_stats() {
  ethtool -S "$SERVER_DEV" > "$OUT_DIR/server_ethtool_${1}.txt"
  ip -s link show dev "$SERVER_DEV" > "$OUT_DIR/server_iplink_${1}.txt"
}

save_client_stats() {
  ssh -o BatchMode=yes "$CLIENT_SSH" "sudo ethtool -S '$CLIENT_DEV'" > "$OUT_DIR/client_ethtool_${1}.txt"
  ssh -o BatchMode=yes "$CLIENT_SSH" "sudo ip -s link show dev '$CLIENT_DEV'" > "$OUT_DIR/client_iplink_${1}.txt"
  ssh -o BatchMode=yes "$CLIENT_SSH" "sudo tc -s qdisc show dev ifb0" > "$OUT_DIR/client_tc_ifb0_${1}.txt" || true
}

save_external_stats() {
  ssh -o BatchMode=yes "$EXTERNAL_SSH" "sudo ethtool -S '$EXTERNAL_HOST_DEV'" > "$OUT_DIR/external_ethtool_${1}.txt"
  ssh -o BatchMode=yes "$EXTERNAL_SSH" "sudo ip -s link show dev '$EXTERNAL_HOST_DEV'" > "$OUT_DIR/external_iplink_${1}.txt"
}



# ========= Configuration ==========

SERVER_IP="10.111.0.1" # fleming
CLIENT_IP="10.111.0.2" # munnin

SERVER_DEV="enp2s0np0"
CLIENT_DEV="enp1s0np0"
EXTERNAL_HOST_DEV="enp1s0np0"

USER="kevinm"
CLIENT_SSH="$USER@172.16.5.201"
EXTERNAL_SSH="$USER@172.16.5.150"

SCRIPT_PATH="$HOME/master/TSO-and-Pacing/scripts/experiment"

DUR=8   # seconds to run
START_CAPTURE=5 # second to start capture
IPERF_PORT=5201
CAPTURE_FILTER="tcp and src host $SERVER_IP and dst host $CLIENT_IP and dst port $IPERF_PORT"

RUN_NUM=""
TREATMENT=""
CONNECTION_MODE=""
FLOWS=0 # direct-link -> 2 flows, internet -> 4 flows, datacenter -> 4 flows
QDISC=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-num)
      RUN_NUM="$2"; shift 2 ;;
    --no-tso)       TREATMENT="no-tso"; shift ;;
    --tso)          TREATMENT="tso"; shift ;;
    --tso-pacing)   TREATMENT="tso-pacing"; shift ;;
    --direct-link)  CONNECTION_MODE="direct-link"; FLOWS=2; shift ;;
    --internet)     CONNECTION_MODE="internet"; FLOWS=4; shift ;;
    --datacenter)   CONNECTION_MODE="datacenter"; FLOWS=4; shift ;;
    --datacenter-hc) CONNECTION_MODE="datacenter-hc"; FLOWS=4; shift ;;
    --fq)           QDISC="fq"; shift ;;
    --fq-codel)     QDISC="fq_codel"; shift ;;
    --help)
      echo "usage: $0 --run-num N (--no-tso|--tso|--tso-pacing) (--direct-link|--internet|--datacenter|--datacenter-hc) (--fq|--fq-codel)"
      exit 0 ;;
    *)
      echo "Unknown argument: $1"; exit 1 ;;
  esac
done

[[ -n "$RUN_NUM" ]] || { echo "Must specify run number (--run-num N)"; exit 1; }
[[ -n "$TREATMENT" ]] || { echo "Must specify treatment"; exit 1; }
[[ -n "$CONNECTION_MODE" ]] || { echo "Must specify connection mode"; exit 1; }
[[ -n "$QDISC" ]] || { echo "Must specify qdisc"; exit 1; }


TS="$(date +%Y%m%d)"
RUN_NAME="${TS}___${CONNECTION_MODE}_${QDISC}_${TREATMENT}_run_${RUN_NUM}"
OUT_DIR="./runs/$RUN_NAME"
mkdir -p "$OUT_DIR"

cat > "$OUT_DIR/meta.txt" <<EOF
run_name=$RUN_NAME
run_num=$RUN_NUM
treatment=$TREATMENT
mode=$CONNECTION_MODE
qdisc=$QDISC
flows=$FLOWS
dur=$DUR
start_capture=$START_CAPTURE
EOF

# =========================================

echo ""
echo "Running experiment $RUN_NAME!"
echo ""


# ====== Configure all machines ====== 
echo ""
echo "Configuring all machines"
setup_server
setup_client
setup_external



# ====== Save interface stats before ====== 
echo ""
echo "Saving interface stats before test"
save_server_stats before
save_client_stats before
save_external_stats before



# ====== Run experiment ======
# ensure everything is killed when ctrl c!!


echo ""
echo "Starting iperf3 server on CLIENT"
CLIENT_IPERF_PID="$(ssh -o BatchMode=yes "$CLIENT_SSH" "sudo sh -c 'nohup iperf3 -s -p $IPERF_PORT > /tmp/iperf_server_${RUN_NAME}.log 2>&1 & echo \$!'")"
echo "Client iperf3 server pid: $CLIENT_IPERF_PID"

# probe fq queue length if not direct link
if [[ "$CONNECTION_MODE" != "direct-link" ]]; then
  echo ""
  echo "Starting bpftrace on CLIENT (for ifb0)"
  CLIENT_BPF_PID="$(ssh -o BatchMode=yes "$CLIENT_SSH" "sudo sh -c 'BPFTRACE_MAP_KEYS_MAX=65536 nohup bpftrace $SCRIPT_PATH/monitor_qlen.bt > /tmp/bpf_monitor_${RUN_NAME}.txt 2>&1 & echo \$!'")"
  echo "Client bpftrace pid: $CLIENT_BPF_PID"
fi

sleep 1

echo ""
echo "Starting data transmission from SERVER (starting iperf3 client)"
iperf3 -c "$CLIENT_IP" -p "$IPERF_PORT" -t "$DUR" -P "$FLOWS" --json \
  > "$OUT_DIR/server_iperf_client.json" 2> "$OUT_DIR/server_iperf_client.err" &
SERVER_IPERF_PID="$!"


# Wait START_CAPTURE
sleep "$START_CAPTURE"

echo ""
echo "Starting pcap on EXTERNAL HOST"
CAPTURE_OUT="capture_${RUN_NAME}.pcapng"

ssh "$EXTERNAL_SSH" "sudo dumpcap -q -i $EXTERNAL_HOST_DEV -w /dev/shm/$CAPTURE_OUT -f '$CAPTURE_FILTER' -s 128 -B 256 -a duration:1 &> /tmp/dumpcap_${RUN_NAME}.log 2>&1"


# Wait until everything done
wait "$SERVER_IPERF_PID"
sleep 1

if [[ -n "$CLIENT_BPF_PID" ]]; then
  echo "Stopping bpftrace on CLIENT"
  ssh "$CLIENT_SSH" "sudo kill -INT $CLIENT_BPF_PID" || true
  CLIENT_BPF_PID=""
  sleep 1
fi

echo ""
echo "Data transmission done, stopping iperf3 server on CLIENT"
ssh "$CLIENT_SSH" "sudo kill $CLIENT_IPERF_PID" || true
CLIENT_IPERF_PID=""

# capture done, retrieve output (wait until iperf done)
echo "Copying "
ssh "$EXTERNAL_SSH" "sudo chown $USER:$USER /dev/shm/$CAPTURE_OUT /tmp/dumpcap_${RUN_NAME}.log"
scp "$EXTERNAL_SSH:/dev/shm/$CAPTURE_OUT" "$OUT_DIR/$CAPTURE_OUT"
scp "$EXTERNAL_SSH:/tmp/dumpcap_${RUN_NAME}.log" "$OUT_DIR/dumpcap_${RUN_NAME}.log" || true
if [[ "$CONNECTION_MODE" != "direct-link" ]]; then
  ssh "$CLIENT_SSH" "sudo chown $USER:$USER /tmp/bpf_monitor_${RUN_NAME}.txt 2>/dev/null" || true
  scp "$CLIENT_SSH:/tmp/bpf_monitor_${RUN_NAME}.txt" "$OUT_DIR/bpf_monitor_${RUN_NAME}.txt" || true
fi

# Then remove capture
ssh "$EXTERNAL_SSH" "sudo rm /dev/shm/$CAPTURE_OUT /tmp/dumpcap_${RUN_NAME}.log"
ssh "$CLIENT_SSH" "sudo rm -f /tmp/bpf_monitor_${RUN_NAME}.txt"

# ====== Save interface stats after ====== 
# should save all interfaces, if EXTERNAL HOST PCAP dropped any packets, client IFB, and of course iperf client on SERVER statistics.  
echo ""
echo "Saving interface stats after test"
save_server_stats after
save_client_stats after
save_external_stats after

# save qdisc used on server
tc -s qdisc show dev "$SERVER_DEV" > "$OUT_DIR/server_qdisc.txt" || true


# change owner of output to user
chown -R "$USER:$USER" "$OUT_DIR"


echo ""
echo ""
echo "Experiment run $RUN_NAME finished sucessfully, output in $OUT_DIR"
echo ""
echo ""