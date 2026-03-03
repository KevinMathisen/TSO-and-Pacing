import contextlib
import io
import pandas as pd
import numpy as np
import matplotlib as mp
mp.use("Agg")
import matplotlib.pyplot as plt
import re
import sys
from pathlib import Path

# Constants
MICRO_BIN_US = 40
BIN_FOR_PPB_MEDIAN_US = 20
MS_BIN = 1



METRICS_DIR = Path("metrics")
FILE_NAMES = [
    {
        "PACKETS_CSV": "./org/packets.csv",
        "CAPTURE_LOG": "./org/capture.log",
        "BEFORE_STATS": "./org/ethtool_stats.before",
        "AFTER_STATS": "./org/ethtool_stats.after",
    },
    {
        "PACKETS_CSV": "./it4/packets.csv",
        "CAPTURE_LOG": "./it4/capture.log",
        "BEFORE_STATS": "./it4/ethtool_stats.before",
        "AFTER_STATS": "./it4/ethtool_stats.after",
    },
]

EXPERIMENT_NAME = "it4_1Gbps"
EXPERIMENT_NAMES = ['CoreNIC (Original Firmware)', 'Iteration 4 (TSO Pacing)']
EXPERIMENT_KEYS = ['org', 'it4']
EXPERIMENT_COLORS = ['#E69F00', '#0072B2'] # Orange, Blue


plt.rcParams.update({
    "axes.titlesize": 20,
    "axes.labelsize": 16,
    "legend.fontsize": 16,
    "xtick.labelsize": 14,
    "ytick.labelsize": 14,
})

# ------ functions for generating per-flow metrics --------------------------------------------------------------------------------------------



def _extract_flow_payload(df_flow: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Return arrays (t, tcp_len) for packets with payload sorted by time
    """
    df_pl = df_flow[df_flow["tcp.len"] > 0].sort_values("frame.time_epoch", kind="mergesort")
    if df_pl.empty: exit(1)

    t = df_pl["frame.time_epoch"].to_numpy(dtype=np.float64)
    frame_len = df_pl["frame.len"].to_numpy(dtype=np.int64)

    # convert empty flags to 0
    df_pl["tcp.analysis.retransmission"] = df_pl["tcp.analysis.retransmission"].fillna(0).astype(int)
    df_pl["tcp.analysis.out_of_order"]   = df_pl["tcp.analysis.out_of_order"].fillna(0).astype(int)
    df_pl["tcp.analysis.lost_segment"]   = df_pl["tcp.analysis.lost_segment"].fillna(0).astype(int)

    is_retrans = df_pl["tcp.analysis.retransmission"].to_numpy(dtype=np.int8)
    is_ooo = df_pl["tcp.analysis.out_of_order"].to_numpy(dtype=np.int8)
    is_lost = df_pl["tcp.analysis.lost_segment"].to_numpy(dtype=np.int8)

    return t, frame_len, is_retrans, is_ooo, is_lost

def _compute_flow_basics(t: np.ndarray, frame_len: np.ndarray) -> dict:
    """
    Get basic metrics from a flow (total duration, bytes, packets, throughput, PPS)
    """
    duration_s = float(t[-1] - t[0])
    bytes = int(frame_len.sum())
    packets = int(t.size)
    return {
        "duration_s": duration_s,
        "bytes": bytes,
        "packets": packets,
        "throughput_mbps": (bytes * 8 / duration_s) / 1000000,
        "pps": packets/duration_s,  
    }


def _build_micro_timeseries(t: np.ndarray, width_us: int) -> tuple[pd.DataFrame]:
    """
    calculate bins based on bin width, then get the number of packets in each bin
    """
    bin_width_s = width_us / 1e6
    t0 = t.min()
    packets_bin_num = np.floor((t - t0) / bin_width_s).astype(np.int64)
    n_bins = int(packets_bin_num.max() + 1)

    packets_per_bin = np.bincount(packets_bin_num, minlength=n_bins)

    bins_start_timestamp = t0 + np.arange(n_bins)*bin_width_s

    # one row for each bin, with its values
    return pd.DataFrame({
        "start_s": bins_start_timestamp,
        "bin_packets": packets_per_bin,
    })

def _zero_time(x: np.ndarray) -> np.ndarray:
    return x - float(x[0])


# -------------- Functions for printing ----------------------------------------------------------------------------------------------------------------------------

def _line(width=100, ch="─"):
    print(ch * width)

def _title(text, width=100):
    print("")
    _line(width)
    print(text.center(width))
    _line(width)

def _format_bytes(n:int) -> str:
    units = ["B", "KB", "MB", "GB"]
    bytes_f = float(n)
    for unit in units:
        if bytes_f < 1024.0:
            return f"{bytes_f:.1f} {unit}"
        bytes_f /= 1024.0
    return f"{bytes_f:.1f} GB"

def _format_int(n) -> str:
    return f"{int(n):,}"

def _format_float(n, decimals=2) -> str:
    return f"{n:,.{decimals}f}"

def _format_us(us) -> str:
    return f"{us:,.2f}"

def _format_s(s) -> str:
    return f"{s:.5f}"


# ------------- Parse files -----------------------------------------------------------------------------------------------

def parse_capture_log(p):
    # TODO: update to use dumpcap output instead of netsniff
    res = { "packets_captured": None, "packets_dropped": None }

    captured_re = re.compile(r'^\s*(\d+)\s+packets passed filter', re.I)
    dropped_re = re.compile(r'^\s*(\d+)\s+packets failed filter', re.I)

    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            captured_m = captured_re.search(line)
            dropped_m = dropped_re.search(line)
            if captured_m:  res["packets_captured"] = int(captured_m.group(1))
            elif dropped_m: res["packets_dropped"] = int(dropped_m.group(1))

    return res
    
def parse_ethtool_stats(p):
    stats = {}

    line_re = re.compile(r'^\s*([A-Za-z0-9._]+):\s*([0-9]+)\s*$') # match lines with stats
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line_m = line_re.search(line)
            if line_m: stats[line_m.group(1)] = int(line_m.group(2))
    
    return stats
    
def compute_health_metrics(files: dict) -> dict:
    capture_log = parse_capture_log(files["CAPTURE_LOG"])
    ethtool_before = parse_ethtool_stats(files["BEFORE_STATS"])
    ethtool_after = parse_ethtool_stats(files["AFTER_STATS"])

    if not ethtool_before or not ethtool_after:
        ethtool_changed = {}
    else:
        deltas = {k: ethtool_after.get(k, 0) - ethtool_before.get(k, 0) for k in ethtool_before.keys()}
        ethtool_changed = {k: v for k, v in deltas.items() if v != 0}

    return {
        "capture_log": capture_log,
        "ethtool_changed": ethtool_changed,
    }


# ------------- generate metrics -----------------------------------------------------------------------------------------------

def generate_aggregate_metrics(packets):
    """
    Compute combined metrics for all flows (duration, total packets/bytes, throughput, pps)
    """
    print("    computing aggregate metrics...")
    
    packets_with_payload = packets[packets["tcp.len"] > 0]
    if packets_with_payload.empty: exit(1)

    # TODO: update time extraction
    duration = float(packets.iloc[-1]['frame.time_epoch']) - float(packets.iloc[0]['frame.time_epoch'])
    total_bytes = int(packets['frame.len'].sum())
    total_packets = int(packets.shape[0])

    average_throughput_mbps = (total_bytes*8 / duration) / 1e6
    pps = total_packets / duration

    # extract retrans, ooo, lost
    pl = packets_with_payload[packets_with_payload["tcp.len"] > 0].copy()
    pl["tcp.analysis.retransmission"] = pl["tcp.analysis.retransmission"].fillna(0).astype(int)
    pl["tcp.analysis.out_of_order"] = pl["tcp.analysis.out_of_order"].fillna(0).astype(int)
    pl["tcp.analysis.lost_segment"] = pl["tcp.analysis.lost_segment"].fillna(0).astype(int)
    retrans_total = int(pl["tcp.analysis.retransmission"].sum())
    ooo_total = int(pl["tcp.analysis.out_of_order"].sum())
    lost_total = int(pl["tcp.analysis.lost_segment"].sum())

    return {
        "duration_s": duration,
        "total_bytes": total_bytes,
        "total_packets": total_packets,
        "average_throughput_mbps": average_throughput_mbps,
        "pps": pps,
        "retrans_packets": retrans_total,
        "ooo_packets": ooo_total,
        "lost_packets": lost_total,
    }

def generate_per_flow_metrics(packets):
    """
    Compute metrics per flow:
      - basic metrics (duration, throughput, pps)
      - amount of retransmissions, out-of-order packets, lost packets
    """
    print("    computing per-flow metrics...")

    per_flow_metrics: dict[int, dict] = {}

    for flow_id, df_flow in packets.groupby("tcp.stream", sort=True):
        print(f"        flow {flow_id}...")
        t, frame_len, is_retrans, is_ooo, is_lost = _extract_flow_payload(df_flow)

        # calculcate basics (duration, throughput/byte, PPS) 
        basics = _compute_flow_basics(t, frame_len)

        if basics["packets"] <= 100:
            print(f"            skipping flow {flow_id} with only {basics["packets"]} packets")
            continue

        # amount of Retransmissions, Out-of-order and lost packets
        retrans_pkts = np.sum(is_retrans)
        ooo_pkts = np.sum(is_ooo)
        lost_pkts = np.sum(is_lost)

        # 40us bins Packets per bin + IPG quantiles
        #   calculate IPG quartiles so we can also see bursts, and how close we follow pacing rates
        timeseries_micro = _build_micro_timeseries(t, MICRO_BIN_US)

        per_flow_metrics[int(flow_id)] = {
            "duration_s": basics["duration_s"],
            "packets": basics["packets"],
            "bytes": basics["bytes"],
            "throughput_mbps": basics["throughput_mbps"],
            "pps": basics["pps"],
            "retrans_packets": int(retrans_pkts),
            "ooo_packets": int(ooo_pkts),
            "lost_packets": int(lost_pkts),
            "timeseries_micro": timeseries_micro,
        }
    
    return per_flow_metrics

# ----------------- functions for plotting -----------------------------------------------------------------------------------------

def plot_flow_micro_timeseries(df_micro_a: pd.DataFrame, label_a: str, color_a: str,
                               df_micro_b: pd.DataFrame, label_b: str, color_b: str,
                               path: Path):
    """
    Plots packets per bin over time, using MICRO_BIN_US bin data
    """
    start_time_ms = 500
    stop_time_ms = 505

    fig = plt.figure(figsize=(10, 6))  

    # how many packets per bin per configuration
    x_a_ms = _zero_time(df_micro_a["start_s"].to_numpy()) * 1000.0
    y_a = df_micro_a["bin_packets"].to_numpy()
    x_b_ms = _zero_time(df_micro_b["start_s"].to_numpy()) * 1000.0
    y_b = df_micro_b["bin_packets"].to_numpy()

    plt.plot(x_a_ms, y_a, color=color_a, linewidth=1.3, label=label_a)
    plt.plot(x_b_ms, y_b, color=color_b, linewidth=1.3, label=label_b)

    ax = plt.gca()
    ax.yaxis.set_major_locator(mp.ticker.MultipleLocator(10))
    ax.yaxis.set_minor_locator(mp.ticker.MultipleLocator(2))
    ax.xaxis.set_major_locator(mp.ticker.MultipleLocator(1))

    ax.minorticks_on()
    ax.xaxis.set_minor_locator(mp.ticker.NullLocator())
    ax.grid(True, which="major", axis="y", alpha=0.85, linestyle="--", linewidth=0.7)
    ax.grid(True, which="minor", axis="y", alpha=0.35, linestyle="--", linewidth=0.5)

    ax.yaxis.set_minor_formatter(mp.ticker.FormatStrFormatter('%d'))
    ax.tick_params(axis="y", which="minor", length=3, width=0.8, labelsize=12)
    ax.tick_params(axis="y", which="major", length=6, width=1.0, labelsize=14)
    ax.tick_params(axis="x", which="major", length=6, width=1.0, labelsize=14)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    ax.fill_between(x_a_ms, y_a, 0, color=color_a, alpha=0.22, linewidth=0)
    ax.fill_between(x_b_ms, y_b, 0, color=color_b, alpha=0.22, linewidth=0)

    plt.xlim(start_time_ms, stop_time_ms)
    plt.ylim(0, 35)
    plt.xlabel('Time elapsed (ms)')
    plt.ylabel(f"Packets received per {MICRO_BIN_US} µs bin")
    plt.title(f"Timeseries of packets sent over 5 ms")
    plt.legend(loc='upper right')

    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)

    # Comment in thesis should include configuration specs (bandwidth, what each config entails, how many flows (First Flow in Each Config), setup we recorded in.)


def plot_ipa_cdf(label_a: str, gaps_us_a: np.ndarray, color_a: str,
                             label_b: str, gaps_us_b: np.ndarray, color_b: str,
                             path: Path):
    """
    Plot inter packet arrival CDF
    """
    fig = plt.figure(figsize=(10, 6))

    x_a = np.sort(gaps_us_a)
    y_a = np.linspace(0, 1, len(x_a))
    x_b = np.sort(gaps_us_b)
    y_b = np.linspace(0, 1, len(x_b))   

    plt.plot(x_a, y_a, color=color_a, linewidth=1.6, label=label_a)
    plt.plot(x_b, y_b, color=color_b, linewidth=1.6, label=label_b)

    ax = plt.gca()
    ax.set_xscale("log")

    ax.xaxis.set_major_formatter(mp.ticker.FuncFormatter(lambda v, pos: f"{v:g}"))
    
    ax.tick_params(axis="x", which="both", top=True, labeltop=False)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    ax.grid(True, which="major", axis="x", alpha=0.7, linestyle="--", linewidth=0.5)

    plt.xscale("log")
    plt.xlabel("Inter-Packet Arrival (µs)")
    plt.ylabel("Cumulative Probability")
    
    # TODO: might remove title
    plt.title(f"CDF of measured Inter-Packet Arrival by Configurations")
    plt.gca().yaxis.set_major_locator(mp.ticker.MultipleLocator(0.1))
    # plt.gca().yaxis.set_major_formatter(mp.ticker.PercentFormatter(1))
    plt.legend()

    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)

    # Comment in thesis should include configuration specs (bandwidth, what each config entails, how many flows (First Flow in Each Config), setup we recorded in.)


def plot_ppb_cdf(label_a: str, t_a: np.ndarray, color_a: str,
                       label_b: str, t_b: np.ndarray, color_b: str,
                       path: Path):
    """
    Plot packets-per-40µs-bin distribution
    """
    bin_width_s = BIN_FOR_PPB_MEDIAN_US / 1e6

    fig = plt.figure(figsize=(10, 6))

    def sorted_pkts_per_bin(t: np.ndarray) -> np.ndarray:
        t0 = float(t.min())
        idx = np.floor((t - t0) / bin_width_s).astype(np.int64)
        n_bins = int(idx.max() + 1)
        pkts_per_bin = np.bincount(idx, minlength=n_bins)
        return np.sort(pkts_per_bin)

    # CDF of packets per 10us bin
    x_a = sorted_pkts_per_bin(t_a)
    y_a = np.linspace(0, 1, (len(x_a)))
    x_b = sorted_pkts_per_bin(t_b)
    y_b = np.linspace(0, 1, (len(x_b)))

    plt.plot(x_a, y_a, label=label_a, linewidth=1.6, color=color_a)
    plt.plot(x_b, y_b, label=label_b, linewidth=1.6, color=color_b)

    ax = plt.gca()
    ax.xaxis.set_minor_locator(mp.ticker.MultipleLocator(1))
    ax.xaxis.set_major_locator(mp.ticker.MultipleLocator(2))
    ax.yaxis.set_major_locator(mp.ticker.MultipleLocator(0.1))

    # ax.xaxis.set_minor_formatter(mp.ticker.FormatStrFormatter('%d'))
    # ax.tick_params(axis="x", which="minor", labelsize=12)
    ax.tick_params(axis="x", which="both", top=True, labeltop=False)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    ax.grid(True, which="major", axis="x", alpha=0.7, linestyle="--", linewidth=0.5)

    plt.xlabel(f"Packets received per {BIN_FOR_PPB_MEDIAN_US} µs bin")
    plt.ylabel("Cumulative Probability")
    plt.title(f"CDF of Packets received per {BIN_FOR_PPB_MEDIAN_US} µs bin")
    plt.legend()

    

    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close(fig)

    # (First Flow in Each Config)...


# TODO: function for plotting delay distribution
# maybe boxplot


def write_plots(results_a: dict, results_b: dict):
    """
    create and save plots (under ./metrics)
    """

    # plot for one flow from each config
    label_a=results_a["name"]
    label_b=results_b["name"]
    color_a=results_a["color"]
    color_b=results_b["color"]
    micro_a = results_a["per_flow"][results_a["first_flow_id"]]["timeseries_micro"]
    micro_b = results_b["per_flow"][results_b["first_flow_id"]]["timeseries_micro"]
    t_flow_a = results_a["flow_t"]
    t_flow_b = results_b["flow_t"]
    gaps_us_a=np.diff(t_flow_a) * 1e6
    gaps_us_b=np.diff(t_flow_b) * 1e6


    plot_flow_micro_timeseries(
        micro_a, label_a, color_a, micro_b, label_b, color_b,
        path=METRICS_DIR / f"{EXPERIMENT_NAME}_compare_firstflow_timeseries_ppb_{MICRO_BIN_US}us.png",
    )

    plot_ppb_cdf( 
        label_a, t_flow_a, color_a, label_b, t_flow_b, color_b,
        path=METRICS_DIR / f"{EXPERIMENT_NAME}_compare_firstflow_ppb_{BIN_FOR_PPB_MEDIAN_US}us_cdf.png",
    )

    plot_ipa_cdf(
        label_a, gaps_us_a, color_a, label_b, gaps_us_b, color_b,
        path=METRICS_DIR / f"{EXPERIMENT_NAME}_compare_firstflow_ipa_cdf.png",
    )

    # TODO: also plot for all flows from each config
    # (to look for inter flow bursts, and possible reduction in this)
    # most interesting for lower speeds where we might spread more even

# ----------------- CLI output ------------------------

def print_health_block(name: str, health: dict):
    _title(f"HEALTH CHECKS for {name}")
    capture_log = health.get("capture_log", {})
    print(f"netsniff-ng:  captured = {capture_log.get('packets_captured')},  dropped = {capture_log.get('packets_dropped')}")

    changed = health.get("ethtool_changed", {})
    print("\nChanges in ethtool counters for NIC:")
    for k, v in changed.items():
        print(f"    {k:36s} {v:+d}")
    _line()


def print_aggregate_metrics(name: str, agg: dict):
    """
    Print metrics from all flows (duration, bytes, packets, throughput, PPS)
    """

    _title(f"METRICS FOR {name}")
    print(f"Duration:            { _format_s(agg.get('duration_s', 0.0)) } s")
    print(f"Total bytes:         { _format_bytes(agg.get('total_bytes', 0)) }")
    print(f"Total packets:       { _format_int(agg.get('total_packets', 0)) }")
    print(f"Avg throughput:      { _format_float(agg.get('average_throughput_mbps', 0.0), 2) } Mb/s")
    print(f"Avg PPS:             { _format_float(agg.get('pps', 0.0), 0) } pkts/s")
    print(f"Retrans (payload):   {_format_int(agg.get('retrans_packets', 0))}")
    print(f"OOO (payload):       {_format_int(agg.get('ooo_packets', 0))}")
    print(f"Lost (payload):      {_format_int(agg.get('lost_packets', 0))}")


def print_per_flow_summary(name: str, per_flow: dict[int, dict]):
    """
    print per-flow table of metrics
    """

    _title(f"PER-FLOW SUMMARY for {name}")

    # table header
    headers = [
        "Flow", "Dur (s)", "Pkts", "Bytes", "Mb/s", "PPS",
        "Retr", "OOO", "Lost",
    ]
    # column widths
    widths = [6, 10, 10, 14, 9, 10, 6, 6, 6]

    def row(values):
        return " ".join(str(v).rjust(w) for v, w in zip(values, widths))

    print(row(headers))
    _line(sum(widths) + len(widths) - 1)

    for flow_id in sorted(per_flow.keys()):
        m = per_flow[flow_id]

        values = [
            flow_id,
            _format_s(m.get("duration_s", 0.0)),
            _format_int(m.get("packets", 0)),
            _format_bytes(m.get("bytes", 0)),
            _format_float(m.get("throughput_mbps", 0.0), 2),
            _format_float(m.get("pps", 0.0), 0),
            _format_int(m.get("retrans_packets", 0)),
            _format_int(m.get("ooo_packets", 0)),
            _format_int(m.get("lost_packets", 0)),
        ]
        print(row(values))

    _line(sum(widths) + len(widths) - 1)


def print_comparison_summary(name_a: str, agg_a: dict, name_b: str, agg_b: dict):
    _title("COMPARISON SUMMARY (ALL FLOWS)")
    print(f"'{name_b}' and '{name_a}'\n")

    print("Deltas (how much 'better' is it4):")
    print(f"  Avg throughput:  {_format_float(agg_b.get('average_throughput_mbps', 0.0) - agg_a.get('average_throughput_mbps', 0.0), 2)} Mb/s")
    print(f"  Avg PPS:         {_format_float(agg_b.get('pps', 0.0) - agg_a.get('pps', 0.0), 0)} pkts/s")
    print(f"  Retrans:         {_format_int(agg_b.get('retrans_packets', 0) - agg_a.get('retrans_packets', 0))}")
    print(f"  OOO:             {_format_int(agg_b.get('ooo_packets', 0) - agg_a.get('ooo_packets', 0))}")
    print(f"  Lost:            {_format_int(agg_b.get('lost_packets', 0) - agg_a.get('lost_packets', 0))}")



# ------------------ Main ----------------------

def load_and_analyze_experiment(files: dict, name: str, key: str, color: str) -> dict:
    packets = pd.read_csv(files["PACKETS_CSV"])

    # remove empty packets (ACKs, etc.) and sort
    packets_sorted = packets[packets["tcp.len"] > 0].sort_values("frame.time_epoch", kind="mergesort")
    if packets_sorted.empty: exit(1)

    health = compute_health_metrics(files)
    aggregate = generate_aggregate_metrics(packets)

    per_flow = generate_per_flow_metrics(packets)
    first_flow_id = sorted(per_flow.keys())[0]

    # store timestamps for flow to plot
    df_flow = packets[packets["tcp.stream"] == first_flow_id]
    t_flow, *_ = _extract_flow_payload(df_flow)

    return {
        "key": key,
        "name": name,
        "color": color,
        "files": files,
        "packets": packets,
        "packets_sorted": packets_sorted,
        "health": health,
        "aggregate": aggregate,
        "per_flow": per_flow,
        "first_flow_id": first_flow_id,
        "flow_t": t_flow,
    }


def main():

    print(f"-- Analysis of experiments started! --")

    METRICS_DIR.mkdir(exist_ok=True)

    # get data needed
    results_a = load_and_analyze_experiment(FILE_NAMES[0], EXPERIMENT_NAMES[0], EXPERIMENT_KEYS[0], EXPERIMENT_COLORS[0])
    results_b = load_and_analyze_experiment(FILE_NAMES[1], EXPERIMENT_NAMES[1], EXPERIMENT_KEYS[1], EXPERIMENT_COLORS[1])


    # CLI output
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_health_block(results_a["name"], results_a["health"])
        print_health_block(results_b["name"], results_b["health"])

        print_aggregate_metrics(results_a["name"], results_a["aggregate"])
        print_per_flow_summary(results_a["name"], results_a["per_flow"])
        
        print_aggregate_metrics(results_b["name"], results_b["aggregate"])
        print_per_flow_summary(results_b["name"], results_b["per_flow"])

        print_comparison_summary(results_a["name"], results_a["aggregate"], results_b["name"], results_b["aggregate"])

    cli_text = buf.getvalue()
    print(cli_text, end="")
    (METRICS_DIR / "cli.txt").write_text(cli_text, encoding="utf-8")

    print("\n\nGenerating plots...\n\n")
    write_plots(results_a, results_b)

    print(f"-- Analysis finished --")



if __name__ == "__main__":
    main()