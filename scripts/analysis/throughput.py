import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} IPERF_JSON EXISTING_THROUGHPUT_JSON", file=sys.stderr)
        sys.exit(1)

    iperf_json_path = Path(sys.argv[1])
    throughput_json_path = Path(sys.argv[2])

    try:
        with open(throughput_json_path, "r") as f:
            throughput = json.load(f)
    except Exception:
        throughput = []

    try:
        with open(iperf_json_path, "r") as f:
            data = json.load(f)

        for interval in data.get("intervals", []):
            for stream in interval.get("streams", []):
                if "bits_per_second" in stream:
                    throughput.append(stream["bits_per_second"])
    except Exception:
        pass

    with open(throughput_json_path, "w") as f:
        json.dump(throughput, f)


if __name__ == "__main__":
    main()