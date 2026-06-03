#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  echo "Please run as root (sudo $0 ...)"
  exit 1
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <condition_label>"
    exit 2
fi

# ============== Usage ===========
# Ensure you have ssh access to client/receiver, and can run sudo there with no password.


# ============== Ensure everything killed on exit function ===========
cleanup() {
    if [[ -n "${CAP_PID}" ]]; then
        sudo pkill tcpdump || true
    fi
}

trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

sudo -v

# =======================

CONDITION="$1"

# ----------------
SENDER_IP="10.0.2.1"
RECEIVER_IP="10.0.2.2"       # Receiver IP address
IFACE="enp3s0np1"        # Sender interface carrying the TCP flow

USER="kevinm"
RECEIVER_SSH="$USER@172.16.5.201"
SCRIPT_PATH="$HOME/master/TSO-and-Pacing/scripts/cwnd"

PORT="5201"
CC="reno"

RUNS=20 # 2 for testing, 20 for final
DURATION=2              # seconds per iperf3 run
OUT_ROOT="results/"
# ----------------

CAP_PID=""

QUEUE_LENS=(8 16 32 64 128 256 512)

for QUEUE_PKTS in "${QUEUE_LENS[@]}"; do

    OUT_DIR="${OUT_ROOT}/${CONDITION}/q${QUEUE_PKTS}"
    mkdir -p "${OUT_DIR}"

    # Record configuration and sender state for reproducibility.
    {
        echo "timestamp=$(date -Is)"
        echo "RECEIVER_IP=${RECEIVER_IP}"
        echo "interface=${IFACE}"
        echo "port=${PORT}"
        echo "congestion_control=${CC}"
        echo "condition=${CONDITION}"
        echo "queue_packets=${QUEUE_PKTS}"
        echo "runs=${RUNS}"
        echo "duration_seconds=${DURATION}"
        echo "=== Sender offload features ==="
        ethtool -k "${IFACE}" || true
        echo "=== Sender qdisc ==="
        tc -s qdisc show dev "${IFACE}" || true
    } > "${OUT_DIR}/metadata.txt"

    # Run setup script on receiver
    ssh -o BatchMode=yes "$RECEIVER_SSH" "sudo $SCRIPT_PATH/setup-cwnd.sh $QUEUE_PKTS"


    for RUN in $(seq -f "%02g" 1 "${RUNS}"); do
        STEM="${OUT_DIR}/${CONDITION}_q${QUEUE_PKTS}_run${RUN}"

        echo "Run ${RUN}/${RUNS}: condition=${CONDITION}, queue=${QUEUE_PKTS} packets"

        # Capture outgoing data and returning ACKs for this single flow.
        sudo tcpdump -i "${IFACE}" -nn -U \
            -s 256 -B 16384 -w "${STEM}.pcap" \
            "tcp and host ${RECEIVER_IP} and port ${PORT}" \
            2> "${STEM}.tcpdump.log" &
        CAP_PID=$!

        sleep 0.25

        iperf3 -c "${RECEIVER_IP}" -p "${PORT}" -P 1 -t "${DURATION}" \
            -C "${CC}" -J > "${STEM}.iperf3.json" \
            2> "${STEM}.iperf3.err"

        sleep 0.25
        sudo pkill tcpdump

        # Analyze pcap 
        tcpdump -ntt -r "${STEM}.pcap" > "${STEM}_input.txt"
        python3 pcap_ss.py "${STEM}_input.txt" "${SENDER_IP}" X "${RECEIVER_IP}" X 1448 > ${STEM}.txt

        # delete pcap
        rm "${STEM}.pcap" "${STEM}_input.txt"


        sleep 1
    done

    echo "Completed ${RUNS} runs for Qlen ${QUEUE_PKTS}"
done

echo ""
echo "Completed all qlens. PCAPs and iperf3 output are in ${OUT_DIR}/"