import csv
import json
import re
import sys
from pathlib import Path


def parse_iperf_throughput(run_path: Path):
    path = run_path / "server_iperf_client.json"
    if not path.exists():
        return -1

    try:
        data = json.loads(path.read_text())
        return data["end"]["sum_received"]["bits_per_second"]
    except Exception:
        return -1


def count_tshark_flags(raw_csv_path: Path):
    retransmissions = 0
    fast_retransmissions = 0
    out_of_order = 0
    lost_segments = 0

    try:
        with open(raw_csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("tcp.analysis.retransmission", ""):
                    retransmissions += 1
                if row.get("tcp.analysis.fast_retransmission", ""):
                    fast_retransmissions += 1
                if row.get("tcp.analysis.out_of_order", ""):
                    out_of_order += 1
                if row.get("tcp.analysis.lost_segment", ""):
                    lost_segments += 1

        return retransmissions, fast_retransmissions, out_of_order, lost_segments
    except Exception:
        return -1, -1, -1, -1


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


def main():
    if len(sys.argv) != 6:
        print(
            f"Usage: {sys.argv[0]} RUN_PATH RAW_CSV OUT_CSV RUN_NAME RUN_NUM",
            file=sys.stderr,
        )
        sys.exit(1)

    run_path = Path(sys.argv[1])
    raw_csv_path = Path(sys.argv[2])
    out_csv_path = Path(sys.argv[3])
    run_name = sys.argv[4]
    run_num = sys.argv[5]

    throughput_bps = parse_iperf_throughput(run_path)

    retransmissions, fast_retransmissions, out_of_order, lost_segments = count_tshark_flags(raw_csv_path)

    server_before = parse_iplink_total_drops(run_path / "server_iplink_before.txt")
    server_after = parse_iplink_total_drops(run_path / "server_iplink_after.txt")
    server_drops = diff_or_minus_one(server_before, server_after)

    client_before = parse_iplink_total_drops(run_path / "client_iplink_before.txt")
    client_after = parse_iplink_total_drops(run_path / "client_iplink_after.txt")
    client_drops = diff_or_minus_one(client_before, client_after)

    client_ifb_before = parse_tc_drops(run_path / "client_tc_ifb0_before.txt")
    client_ifb_after = parse_tc_drops(run_path / "client_tc_ifb0_after.txt")
    client_ifb_drops = diff_or_minus_one(client_ifb_before, client_ifb_after)

    external_before = parse_iplink_total_drops(run_path / "external_iplink_before.txt")
    external_after = parse_iplink_total_drops(run_path / "external_iplink_after.txt")
    external_drops = diff_or_minus_one(external_before, external_after)

    dumpcap_log = find_dumpcap_log(run_path)
    dumpcap_drops = parse_dumpcap_drops(dumpcap_log) if dumpcap_log else -1

    with open(out_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "run_name", "run_num", "throughput_bps", "retransmissions", 
            "fast_retransmissions", "out_of_order", "lost_segments", 
            "server_drops", "client_drops", "client_ifb_drops", 
            "external_drops", "dumpcap_drops",
        ])
        writer.writerow([
            run_name, run_num, throughput_bps, retransmissions, 
            fast_retransmissions, out_of_order, lost_segments, 
            server_drops, client_drops, client_ifb_drops, 
            external_drops, dumpcap_drops,
        ])


if __name__ == "__main__":
    main()