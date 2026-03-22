import csv
import sys


def ts_from_payload(payload: str):
    payload = payload.strip()
    if not payload or len(payload) < 32:
        return "", ""

    try:
        b = bytes.fromhex(payload[:32])
    except Exception:
        return "", ""

    if b[0] != 0x0F or b[1] != 0x10:
        return "", ""
    
    ts1 = int.from_bytes(b[2:8], "big")
    ts2 = int.from_bytes(b[10:16], "big")
    return str(ts1), str(ts2)


def main():
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} INPUT.csv OUTPUT.csv RUN_NAME RUN_NUM", file=sys.stderr)
        exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2]
    run_name = sys.argv[3]
    run_num = int(sys.argv[4])

    with open(in_path, "r", newline="") as fin, open(out_path, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)

        writer.writerow(["run_name", "run_num", "stream_id", "tcp_len", "p4_timestamp_ns", "p4_timestamp_prev_ns"])

        for row in reader:
            stream = row["tcp.stream"]
            tcp_len = row["tcp.len"]
            ts1, ts2 = ts_from_payload(row["data.data"])

            # Only keep full packets with timestamps
            if int(tcp_len) < 1448 or not ts1:
                continue

            # Make stream ids unique across runs
            stream_id = run_num * 10 + int(stream)

            writer.writerow([run_name, run_num, stream_id, tcp_len, ts1, ts2])


if __name__ == "__main__":
    main()