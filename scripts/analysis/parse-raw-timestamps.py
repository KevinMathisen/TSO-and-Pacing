import csv
import sys

port_to_stream_ids = {}
stream_ids = 0

def get_unique_stream_id(srcport: str, dstport: str):
    global port_to_stream_ids, stream_ids
    if (srcport + dstport) in port_to_stream_ids:
        return port_to_stream_ids[srcport + dstport]

    stream_ids+=1
    port_to_stream_ids[srcport + dstport] = stream_ids
    return stream_ids


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

        writer.writerow(["run_name", "run_num", "stream_id", "p4_timestamp_ns"])

        for row in reader:
            stream_id = get_unique_stream_id(row["src_port"], row["dst_port"])
            ts = row["timestamp"]

            writer.writerow([run_name, run_num, stream_id+run_num*10, ts])

if __name__ == "__main__":
    main()