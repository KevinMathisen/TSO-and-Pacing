import csv
import json
import re
import sys
from pathlib import Path


def parse_iperf_throughput_cpu(run_path: Path):
    path = run_path / "server_iperf_client.json"
    if not path.exists():
        return -1, -1, -1

    try:
        data = json.loads(path.read_text())
        throughput = data["end"]["sum_received"]["bits_per_second"]
        cpu_s = data["end"]["cpu_utilization_percent"]["host_total"]
        cpu_r = data["end"]["cpu_utilization_percent"]["remote_total"]
        return throughput, cpu_s, cpu_r
    except Exception:
        return -1, -1, -1




def parse_iplink_total_drops(path: Path):
    text = path.read_text()
    if not path.exists():
        return -1

    try:
        lines = [line.strip() for line in text.splitlines()]

        # find rx/tx header + values lines
        rx_header_idx = next(i for i, line in enumerate(lines) if line.startswith("RX:"))
        rx_vals_idx = rx_header_idx + 1
        tx_header_idx = next(i for i, line in enumerate(lines) if line.startswith("TX:"))
        tx_vals_idx = tx_header_idx + 1

        rx_vals = lines[rx_vals_idx].split()
        tx_vals = lines[tx_vals_idx].split()

        # iplink prints:
        # rx: bytes packets errors dropped overrun mcast
        # tx: bytes packets errors dropped carrier collsns
        rx_dropped = int(rx_vals[3])
        tx_dropped = int(tx_vals[3])

        return rx_dropped + tx_dropped
    except Exception:
        return -1


def parse_tc_drops(path: Path):
    text = path.read_text()
    if not path.exists():
        return -1

    try:
        m = re.search(r"dropped\s+(\d+)", text)
        if not m:
            return -1
        return int(m.group(1))
    except Exception:
        return -1


def parse_dumpcap_drops(path: Path):
    text = path.read_text()
    if not path.exists():
        return -1

    try:
        m = re.search(r"received/dropped on interface .*:\s*\d+/(\d+)", text)
        if not m:
            return -1
        return int(m.group(1))
    except Exception:
        return -1


def diff_or_minus_one(before, after):
    if before == -1 or after == -1:
        return -1
    return after - before


def find_dumpcap_log(run_path: Path):
    matches = list(run_path.glob("dumpcap*.log"))
    if not matches:
        return None
    return matches[0]

def find_bpf_log(run_path: Path):
    matches = list(run_path.glob("bpf_monitor_*.txt"))
    if not matches:
        return None
    return matches[0]

def update_queue_lengths(in_path: Path, out_json_path: Path):
    try:
        agg_data = {}
        with open(out_json_path, 'r') as f:
            agg_data = json.load(f)

        with open(in_path, 'r') as f:
            for line in f:
                m = re.search(r"@qlen_counts\[(\d+)\]:\s*(\d+)", line)
                if m:
                    qlen = m.group(1)
                    count = int(m.group(2))
                    agg_data[qlen] = agg_data.get(qlen, 0) + count

        with open(out_json_path, 'w') as f:
            json.dump(agg_data, f)
    except Exception:
        pass

def parse_dpdk_drops(path: Path):
    if not path.exists():
        return -1

    try:
        text = path.read_text()
        m = re.search(r"Chain check PASSED", text)
        # m = re.search(r"Correct:\s+(\d+)\s+/\s+(\d+)", text)
        if not m:
            return -1
        return 0
        # correct = int(m.group(1))
        # total = int(m.group(2))
        # return total - correct
    except Exception:
        return -1

def main():
    if len(sys.argv) != 7:
        print(
            f"Usage: {sys.argv[0]} RUN_PATH RAW_CSV OUT_CSV RUN_NAME RUN_NUM QLEN_JSON",
            file=sys.stderr,
        )
        sys.exit(1)

    run_path = Path(sys.argv[1])
    dpdk_path = Path(sys.argv[2])
    out_csv_path = Path(sys.argv[3])
    run_name = sys.argv[4]
    run_num = sys.argv[5]
    qlen_json = Path(sys.argv[6])

    throughput_bps, cpu_s, cpu_r = parse_iperf_throughput_cpu(run_path)

    server_before = parse_iplink_total_drops(run_path / "server_iplink_before.txt")
    server_after = parse_iplink_total_drops(run_path / "server_iplink_after.txt")
    server_drops = diff_or_minus_one(server_before, server_after)

    client_before = parse_iplink_total_drops(run_path / "client_iplink_before.txt")
    client_after = parse_iplink_total_drops(run_path / "client_iplink_after.txt")
    client_drops = diff_or_minus_one(client_before, client_after)

    client_ifb_before = parse_tc_drops(run_path / "client_tc_ifb0_before.txt")
    client_ifb_after = parse_tc_drops(run_path / "client_tc_ifb0_after.txt")
    client_ifb_drops = diff_or_minus_one(client_ifb_before, client_ifb_after)

    external_drops = parse_dpdk_drops(dpdk_path)

    dumpcap_log = find_dumpcap_log(run_path)
    dumpcap_drops = parse_dumpcap_drops(dumpcap_log) if dumpcap_log else -1

    bpf_log = find_bpf_log(run_path)
    if bpf_log:
        update_queue_lengths(bpf_log, qlen_json)

    with open(out_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "run_name", "run_num", "throughput_bps", "cpu_sender", "cpu_receiver",
            "server_drops", "client_drops", "client_ifb_drops", 
            "external_drops", "dumpcap_drops",
        ])
        writer.writerow([
            run_name, run_num, throughput_bps, cpu_s, cpu_r,
            server_drops, client_drops, client_ifb_drops, 
            external_drops, dumpcap_drops,
        ])


if __name__ == "__main__":
    main()