import json
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} IPERF_JSON EXISTING_RTT_JSON", file=sys.stderr)
        sys.exit(1)

    iperf_json_path = Path(sys.argv[1])
    rtt_json_path = Path(sys.argv[2])

    try:
        with open(rtt_json_path, "r") as f:
            rtts = json.load(f)
    except Exception:
        rtts = []

    try:
        with open(iperf_json_path, "r") as f:
            data = json.load(f)

        for interval in data.get("intervals", []):
            for stream in interval.get("streams", []):
                if "rtt" in stream:
                    rtts.append(stream["rtt"])
    except Exception:
        pass

    with open(rtt_json_path, "w") as f:
        json.dump(rtts, f)


if __name__ == "__main__":
    main()