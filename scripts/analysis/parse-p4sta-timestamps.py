import csv
import sys


def ts1_from_tcp_options(opts: str):
    # tshark prints tcp options as 0a:05:01...
    try:
        b = bytes(int(x, 16) for x in opts.split(":") if x)
    except Exception:
        return ""

    i = 0
    while i < len(b)-1:
        kind = b[i]
        if kind == 0:  # EOL
            break
        if kind == 1:  # NOP
            i += 1
            continue

        length = b[i + 1]

        # P4STA signature: kind 0x0f, length 0x10,
        #  timestamp1 (6B), unused (2B), timestamp2 (6B)
        if kind == 0x0F and length == 0x10:
            ts1 = int.from_bytes(b[i+2 : i+8], "big")
            return str(ts1)

        i += length

    return ""


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} INPUT.csv OUTPUT.csv", file=sys.stderr)
        exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]

    with open(in_path, "r", newline="") as fin, open(out_path, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)
        writer.writerow(["tcp.stream", "tcp.len", "timestamp1"])

        for row in reader:
            stream = row.get("tcp.stream", "")
            tcplen = row.get("tcp.len", "")
            ts1 = ts1_from_tcp_options(row.get("tcp.options", ""))
            writer.writerow([stream, tcplen, ts1])


if __name__ == "__main__":
    main()