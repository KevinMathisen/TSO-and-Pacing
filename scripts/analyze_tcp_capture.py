import contextlib
import io
import pandas as pd
import numpy as np
import matplotlib as mp
mp.use("Agg")
import matplotlib.pyplot as plt
import re
from pathlib import Path

# Constants
MICRO_BIN_US = 50
BIN_FOR_PPS_MEDIAN_US = 10
MS_BIN = 1

PACKETS_CSV_FILE_NAME = "./packets.csv"
CAPTURE_LOG_FILE_NAME = "./capture.log"
BEFORE_STATS_FILE_NAME = "./ethtool_stats.before"
AFTER_STATS_FILE_NAME = "./ethtool_stats.after"

health_metrics = {}
aggregate_metrics = {}
per_flow_metrics = {}

# ------ functions for generating per-flow metrics --------------------------------------------------------------------------------------------

def _ipg_stats_from_us(t: np.ndarray) -> dict:
    """
    Compute basic inter-packet-gap stats/distribution
    """

    gaps_us = np.diff(t) * 1e6

    quartiles = np.quantile(gaps_us, [0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999])

    return {
        "count": int(gaps_us.size),
        "mean_us": float(np.mean(gaps_us)),
        "median_us": float(quartiles[3]),
        "p90_us": float(quartiles[4]),
        "p99_us": float(quartiles[5]),
        "p999_us": float(quartiles[6]),
        "max_us": float(np.max(gaps_us)),
        "std_us": float(np.std(gaps_us, ddof=0)),
        "min_us": float(np.min(gaps_us)),
        "p01_us": float(quartiles[0]),
        "p1_us": float(quartiles[1]),
        "p10_us": float(quartiles[2]),
    }

def _extract_flow_payload(df_flow: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Return arrays (t, seq, tcp_len, frame_len) for packets with payload sorted by time
    """
    df_pl = df_flow[df_flow["tcp.len"] > 0].sort_values("frame.time_epoch", kind="mergesort")
    if df_pl.empty: exit(1)

    t = df_pl["frame.time_epoch"].to_numpy(dtype=np.float64)
    seq = df_pl["tcp.seq"].to_numpy(dtype=np.int64)
    tcp_len = df_pl["tcp.len"].to_numpy(dtype=np.int64)
    frame_len = df_pl["frame.len"].to_numpy(dtype=np.int64)

    # convert empty flags to 0
    df_pl["tcp.analysis.retransmission"] = df_pl["tcp.analysis.retransmission"].fillna(0).astype(int)
    df_pl["tcp.analysis.out_of_order"]   = df_pl["tcp.analysis.out_of_order"].fillna(0).astype(int)
    df_pl["tcp.analysis.lost_segment"]   = df_pl["tcp.analysis.lost_segment"].fillna(0).astype(int)

    is_retrans = df_pl["tcp.analysis.retransmission"].to_numpy(dtype=np.int8)
    is_ooo = df_pl["tcp.analysis.out_of_order"].to_numpy(dtype=np.int8)
    is_lost = df_pl["tcp.analysis.lost_segment"].to_numpy(dtype=np.int8)

    return t, seq, tcp_len, frame_len, is_retrans, is_ooo, is_lost

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

def pps_in_bins(t: np.ndarray, bin_us: int) -> dict:
    """
    Quartile stats/distribution for PPS across given bin width
    """
    bin_width_s = bin_us / 1e6 # convert us to s

    # round each timestamp down to the bin they belong to
    t0 = t.min()
    idx = np.floor((t - t0) / bin_width_s).astype(np.int64)

    n_bins = int(idx.max() + 1)

    packets_per_bin = np.bincount(idx, minlength=n_bins)

    quartiles = np.quantile(packets_per_bin, [0.001, 0.01, 0.1, 0.5, 0.9, 0.99, 0.999])

    # This returns stats for packets per bin, not packets/s per bin. This is intentional, as it is easier to read packets in bin
    #   TODO: update variable names from pps to ppb/packets-per-bin
    return {
        "count": int(n_bins),
        "mean_pps": float(np.mean(packets_per_bin)),
        "median_pps": float(quartiles[3]),
        "p90_pps": float(quartiles[4]),
        "p99_pps": float(quartiles[5]),
        "p999_pps": float(quartiles[6]),
        "max_pps": float(np.max(packets_per_bin)),
        "std_pps": float(np.std(packets_per_bin, ddof=0)),
        "min_pps": float(np.min(packets_per_bin)),
        "p01_pps": float(quartiles[0]),
        "p1_pps": float(quartiles[1]),
        "p10_pps": float(quartiles[2]),
    }


def _build_micro_timeseries(t: np.ndarray, width_us: int) -> tuple[pd.DataFrame]:
    """
    calculate bins based on bin width, then get the following for each bin:
      - number of packets
      - inter-packet-gap quantiles (1, median, 99) 
    """
    bin_width_s = width_us / 1e6
    t0 = t.min()
    packets_bin_num = np.floor((t - t0) / bin_width_s).astype(np.int64)
    n_bins = int(packets_bin_num.max() + 1)

    packets_per_bin = np.bincount(packets_bin_num, minlength=n_bins)

    packet_gaps_us = np.diff(t) * 1e6

    # Place gaps in one array for each bin
    gaps_grouped_by_bin = [[] for _ in range(n_bins)]
    for bin_index, gap_us in zip(packets_bin_num[1:], packet_gaps_us):  # ignore first packet, as no gap
        gaps_grouped_by_bin[bin_index].append(gap_us)

    def safe_quantile(gaps, percentile):
        if not gaps: return np.nan
        if len(gaps) == 1: return float(gaps[0])
        return float(np.quantile(gaps, percentile))

    gap_p01 = np.array([safe_quantile(gaps_in_bin, 0.01) for gaps_in_bin in gaps_grouped_by_bin], dtype=np.float64)
    gap_p50 = np.array([safe_quantile(gaps_in_bin, 0.50) for gaps_in_bin in gaps_grouped_by_bin], dtype=np.float64)
    gap_p99 = np.array([safe_quantile(gaps_in_bin, 0.99) for gaps_in_bin in gaps_grouped_by_bin], dtype=np.float64)

    bins_start_timestamp = t0 + np.arange(n_bins)*bin_width_s

    # one row for each bin, with its values
    return pd.DataFrame({
        "start_s": bins_start_timestamp,
        "bin_packets": packets_per_bin,
        "ipg_p01_us": gap_p01,
        "ipg_p50_us": gap_p50,
        "ipg_p99_us": gap_p99,
    })

def _build_ms_timeseries(t: np.ndarray, is_retrans: np.ndarray, is_ooo: np.ndarray, is_lost: np.ndarray, width_ms: int) -> pd.DataFrame:
    """
    calculate bins based on bin width, then get the following for each bin:
      - packet count
      - event count (retransmission, out-of-order packets, lost packets)
    """
    bin_width_s = width_ms / 1e3
    t0 = t.min()
    packets_bin_num = np.floor((t - t0) / bin_width_s).astype(np.int64)
    n_bins = int(packets_bin_num.max() + 1)

    packets_per_bin = np.bincount(packets_bin_num, minlength=n_bins)

    retrans_per_bin = np.bincount(packets_bin_num, weights=is_retrans, minlength=n_bins).astype(int)
    ooo_per_bin = np.bincount(packets_bin_num, weights=is_ooo, minlength=n_bins).astype(int)
    lost_per_bin = np.bincount(packets_bin_num, weights=is_lost, minlength=n_bins).astype(int)

    bins_start_timestamp = t0 + np.arange(n_bins)*bin_width_s

    return pd.DataFrame({
        "start_s": bins_start_timestamp,
        "bin_pkts": packets_per_bin,
        "retrans_pkts": retrans_per_bin,
        "ooo_pkts": ooo_per_bin,
        "lost_pkts": lost_per_bin
    })

def _zero_time(x: np.ndarray) -> np.ndarray:
    return x - float(x[0])

# -------------- Functions for printing ----------------------------------------------------------------------------------------------------------------------------

def _line(width=100, ch="─"):
    print(ch * width)

def _title(text, width=100):
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

# ----------------- functions for plotting -----------------------------------------------------------------------------------------

def plot_flow_micro_timeseries(flow_id: int, df_micro: pd.DataFrame, plots_dir: Path):  # TODO: use 100us bins for IPG
    """
    Plots packets per bin over time + IPG over time, using 50us bin data
    """
    x = _zero_time(df_micro["start_s"].to_numpy())
    stop_time = 0.04

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    # how many packets per bin
    axes[0].plot(x, df_micro["bin_packets"].to_numpy())
    axes[0].set_xlim(0.0, stop_time)
    axes[0].set_ylabel(f"Packets / {MICRO_BIN_US}µs")
    axes[0].set_title(f"Flow {flow_id} — Packets per {MICRO_BIN_US}µs bin")
    axes[0].grid(True, alpha=0.3)

    # plot on bottom, containing inter-packet-gap quartiles for the bins
    axes[1].plot(x, df_micro["ipg_p99_us"].to_numpy(), label="IPG p99", alpha=0.65, linewidth=1.6)
    axes[1].plot(x, df_micro["ipg_p50_us"].to_numpy(), label="IPG p50", alpha=0.65, linewidth=1.6)
    axes[1].plot(x, df_micro["ipg_p01_us"].to_numpy(), label="IPG p1", alpha=0.65, linewidth=1.6)
    axes[1].set_ylim(0.0, 500)
    axes[1].set_xlabel("Time since flow start (s)")
    axes[1].set_ylabel("IPG (µs)")
    axes[1].set_title(f"Flow {flow_id} — IPG quantiles per {MICRO_BIN_US}µs bin")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(plots_dir / f"flow_{flow_id}_ipg_timeseries_{MICRO_BIN_US}us.png", dpi=300)
    plt.close(fig)

def plot_flow_ms_events(flow_id: int, df_ms: pd.DataFrame, plots_dir: Path):
    """
    Plots packets per bin + retransmissions and ooo packets over time, using 1ms bin data
    """
    x = _zero_time(df_ms["start_s"].to_numpy())
    stop_time = 0.04

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    # plot on top for packets per bin
    axes[0].plot(x, df_ms["bin_pkts"].to_numpy())
    axes[0].set_xlim(0.0, stop_time)
    axes[0].set_ylabel(f"Packets / {MS_BIN}ms")
    axes[0].set_title(f"Flow {flow_id} Packets per {MS_BIN}ms bin")
    axes[0].grid(True, alpha=0.3)
    axes[1].set_ylim(bottom=0)

    # separate plot on bottom for retrans, ooo, lost packets
    axes[1].plot(x, df_ms["retrans_pkts"].to_numpy(), label="Retrans", alpha=0.65, linewidth=1.6)
    axes[1].plot(x, df_ms["ooo_pkts"].to_numpy(), label="Out-of-order", alpha=0.65, linewidth=1.6)
    axes[1].plot(x, df_ms["lost_pkts"].to_numpy(), label="Lost", alpha=0.65, linewidth=1.6)
    axes[1].set_xlabel("Time since flow start (s)")
    axes[1].set_ylabel("Count / ms")
    axes[1].set_title(f"Flow {flow_id} Events per {MS_BIN}ms bin")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    axes[1].set_ylim(bottom=0)

    fig.tight_layout()
    fig.savefig(plots_dir / f"flow_{flow_id}_events_{MS_BIN}ms.png", dpi=300)
    plt.close(fig)

def plot_flow_ipg_histograms(flow_id: int, gaps_us: np.ndarray, plots_dir: Path):
    """
    Plot IPG histograms (zoomed in and not)
    """
    MAX_US_FULL = 600
    MAX_COUNT_FULL = 1000
    MAX_US_ZOOM = 15
    BIN_US_FULL = 1
    BIN_US_ZOOM = 0.25

    # full plot
    full_edges = np.arange(0.0, MAX_US_FULL + BIN_US_FULL, BIN_US_FULL)
    fig = plt.figure(figsize=(10, 6))
    plt.hist(gaps_us, bins=full_edges)
    plt.ylim(0.0, MAX_COUNT_FULL)
    plt.xlabel("IPG (µs)")
    plt.ylabel("Count")
    plt.title(f"Flow {flow_id} — IPG histogram (0–{MAX_US_FULL} µs, bin={BIN_US_FULL} µs)")
    plt.grid(True, alpha=0.3)

    ax = plt.gca()
    max_x = ax.get_xlim()[1]
    ax.set_xticks(np.arange(0, max_x + 1, 50))

    plt.tight_layout()
    plt.savefig(plots_dir / f"flow_{flow_id}_ipg_hist_full.png", dpi=300)
    plt.close(fig)

    # zoomed in plot
    zoom_mask = (gaps_us >= 0.0) & (gaps_us <= MAX_US_ZOOM)
    zoom_edges = np.arange(0.0, MAX_US_ZOOM + BIN_US_ZOOM, BIN_US_ZOOM)
    fig = plt.figure(figsize=(10, 6))
    plt.hist(gaps_us[zoom_mask], bins=zoom_edges)
    plt.xlim(0.0, MAX_US_ZOOM)
    plt.xlabel("IPG (µs)")
    plt.ylabel("Count")
    plt.title(f"Flow {flow_id} — IPG histogram (0–{MAX_US_ZOOM} µs, bin={BIN_US_ZOOM} µs)")
    plt.grid(True, alpha=0.3)

    ax = plt.gca()
    max_x = ax.get_xlim()[1]
    ax.set_xticks(np.arange(0, max_x + 1, 1))

    plt.tight_layout()
    plt.savefig(plots_dir / f"flow_{flow_id}_ipg_hist_zoom.png", dpi=300)
    plt.close(fig)

def plot_flow_ppb_hist(flow_id: int, t: np.ndarray, plots_dir: Path):
    """
    Plot packets-per-10µs-bin distribution
    """
    bin_width_s = BIN_FOR_PPS_MEDIAN_US / 1e6
    t0 = float(t.min())
    idx = np.floor((t - t0) / bin_width_s).astype(np.int64)
    n_bins = int(idx.max() + 1)
    pkts_per_bin = np.bincount(idx, minlength=n_bins)

    max_ppb = int(pkts_per_bin.max())
    edges = np.arange(-0.5, max_ppb + 1.5, 1.0)

    fig = plt.figure(figsize=(10, 6))
    plt.hist(pkts_per_bin, bins=edges)
    plt.xlabel(f"Packets per {BIN_FOR_PPS_MEDIAN_US}µs bin")
    plt.ylabel("Bin count")
    plt.title(f"Flow {flow_id} — Packets/{BIN_FOR_PPS_MEDIAN_US}µs-bin distribution")
    plt.grid(True, alpha=0.3)
    
    ax = plt.gca()
    max_x = ax.get_xlim()[1]
    ax.set_xticks(np.arange(0, max_x + 1, 1))  # set x ticks increment to 1

    plt.tight_layout()
    plt.savefig(plots_dir / f"flow_{flow_id}_ppb_{BIN_FOR_PPS_MEDIAN_US}us_hist.png", dpi=300)
    plt.close(fig)


# ------------- Main functions -----------------------------------------------------------------------------------------------

def print_test_health_check():
    """
    print total packets captured and dropped by netsniff,
    and the differnce in ethtool counters for the interface  
    """
    global health_metrics

    def parse_capture_log(p):
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
    
    capture_log = parse_capture_log(CAPTURE_LOG_FILE_NAME)
    ethtool_before = parse_ethtool_stats(BEFORE_STATS_FILE_NAME)
    ethtool_after = parse_ethtool_stats(AFTER_STATS_FILE_NAME)

    if not ethtool_before or not ethtool_after:
        print("Error parsing ethtool before/after")
        return

    ethtool_deltas = {key: ethtool_after[key] - ethtool_before[key] for key in ethtool_before.keys()}
    ethtool_changed = {k: v for k, v in ethtool_deltas.items() if v != 0}

    _title("HEALTH CHECKS")
    print(f"netsniff-ng:  captured = {capture_log.get('packets_captured')},  dropped = {capture_log.get('packets_dropped')}")

    print("\nChanges in ethtool counters for NIC:")
    for k, v in ethtool_changed.items():
        print(f"    {k:36s} {v:+d}")

    _line()

    health_metrics.update({
        "capture_log": capture_log,
        "ethtool_changed": ethtool_changed,
    })

def generate_aggregate_metrics(packets):
    """
    Compute combined metrics for all flows (duration, total packets/bytes, throughput, pps)
    """
    print("    computing aggregate metrics...")

    global aggregate_metrics
    
    packets_with_payload = packets[packets["tcp.len"] > 0]
    if packets_with_payload.empty: exit(1)

    duration = float(packets.iloc[-1]['frame.time_epoch']) - float(packets.iloc[0]['frame.time_epoch'])
    total_bytes = int(packets['frame.len'].sum())
    total_packets = int(packets.shape[0])

    average_throughput_mbps = (total_bytes*8 / duration) / 1e6
    pps = total_packets / duration

    aggregate_metrics.update({
        "duration_s": duration,
        "total_bytes": total_bytes,
        "total_packets": total_packets,
        "average_throughput_mbps": average_throughput_mbps,
        "pps": pps,
    })

def generate_per_flow_metrics(packets):
    """
    Compute metrics per flow:
      - basic metrics (duration, throughput, pps)
      - amount of retransmissions, out-of-order packets, lost packets
      - inter packet gaps distribution
      - pps distribution 
      - pps and ipg distribution in bins (to see bursts etc.)
      - pps and retrans+out-of-order in bins
    """
    print("    computing per-flow metrics...")

    global per_flow_metrics

    for flow_id, df_flow in packets.groupby("tcp.stream", sort=True):
        print(f"        flow {flow_id}...")
        t, seq, tcp_len, frame_len, is_retrans, is_ooo, is_lost = _extract_flow_payload(df_flow)

        # calculcate basics
        # - Duration 
        # - throughput/bytes 
        # - PPS 
        basics = _compute_flow_basics(t, frame_len)

        if basics["packets"] <= 100:
            print(f"            skipping flow {flow_id} with only {basics["packets"]} packets")
            continue

        # amount of Retransmissions, Out-of-order and lost packets
        retrans_pkts = np.sum(is_retrans)
        ooo_pkts = np.sum(is_ooo)
        lost_pkts = np.sum(is_lost)

        # Inter packet gaps
        #   compute the gap between each packet
        #       based on this, calculcate mean, median, p90, p99, p99.9, max, as well as min, p0.1, p1, p10
        #       also calculate jitter as standard deviation of IPG (i.e. how stable is the IPG in the transmission?)     
        ipg_stats = _ipg_stats_from_us(t)

        # 10us bin PPS stats 
        #   calculate PPS stats so we can see if some bins have way higher amount of packets (bursts)
        #       (mean, median, p90, p99, p99.9, max, as well as min, p0.1, p1, p10)
        pps_stats = pps_in_bins(t, BIN_FOR_PPS_MEDIAN_US)

        # 50us bins Packets per bin + IPG quantiles
        #   calculate IPG quartiles so we can also see bursts, and how close we follow pacing rates
        timeseries_micro = _build_micro_timeseries(t, MICRO_BIN_US)

        # 1ms bins Packets per bin + retransmissions + out of order
        timeseries_ms = _build_ms_timeseries(t, is_retrans, is_ooo, is_lost, MS_BIN)

        per_flow_metrics[int(flow_id)] = {
            "duration_s": basics["duration_s"],
            "packets": basics["packets"],
            "bytes": basics["bytes"],
            "throughput_mbps": basics["throughput_mbps"],
            "pps": basics["pps"],
            "retrans_packets": int(retrans_pkts),
            "ooo_packets": int(ooo_pkts),
            "lost_packets": int(lost_pkts),
            "ipg_stats": ipg_stats,
            "pps_stats": pps_stats,
            "timeseries_micro": timeseries_micro,
            "timeseries_ms": timeseries_ms,
        }

def print_aggregate_metrics():
    """
    Print metrics from all flows (duration, bytes, packets, throughput, PPS)
    """

    _title("METRICS FOR ALL FLOWS")
    print(f"Duration:            { _format_s(aggregate_metrics.get('duration_s', 0.0)) } s")
    print(f"Total bytes:         { _format_bytes(aggregate_metrics.get('total_bytes', 0)) }")
    print(f"Total packets:       { _format_int(aggregate_metrics.get('total_packets', 0)) }")
    print(f"Avg throughput:      { _format_float(aggregate_metrics.get('average_throughput_mbps', 0.0), 2) } Mb/s")
    print(f"Avg PPS:             { _format_float(aggregate_metrics.get('pps', 0.0), 0) } pkts/s")

def print_per_flow_metrics():
    """
    print per-flow table of metrics
    """

    _title("PER-FLOW SUMMARY")

    # table header
    headers = [
        "Flow", "Dur (s)", "Pkts", "Bytes", "Mb/s", "PPS",
        "Retr", "OOO", "Lost",
        "IPG p50 (µs)", "p90", "p99", "p99.9", "max",
        "jitter (µs)"
    ]
    # column widths
    widths = [6, 10, 10, 14, 9, 10, 6, 6, 6, 14, 8, 8, 9, 10, 14]

    def row(values):
        return " ".join(str(v).rjust(w) for v, w in zip(values, widths))

    print(row(headers).replace(" ", " "))
    _line(sum(widths) + len(widths) - 1)

    for flow_id in sorted(per_flow_metrics.keys()):
        m = per_flow_metrics[flow_id]
        ipg = m.get("ipg_stats", {})

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
            _format_us(ipg.get("median_us", 0.0)),
            _format_us(ipg.get("p90_us", 0.0)),
            _format_us(ipg.get("p99_us", 0.0)),
            _format_us(ipg.get("p999_us", 0.0)),
            _format_us(ipg.get("max_us", 0.0)),
            _format_us(ipg.get("std_us", 0.0)),
        ]
        print(row(values))

    _line(sum(widths) + len(widths) - 1)

    # print another table containig all pps metrics per flow
    print()
    _title("PER-FLOW PACKETS-PER-BIN DISTRIBUTION (bin={}µs)".format(BIN_FOR_PPS_MEDIAN_US))
    pps_headers = [
        "Flow", "Bins", "Mean", "Median",
        "p90", "p99", "p99.9", "Max",
        "Std", "Min", "p0.1", "p1", "p10"
    ]
    pps_widths = [6, 10, 10, 10, 12, 12, 12, 12, 10, 10, 8, 8, 8]

    def pps_row(vals):
        return " ".join(str(v).rjust(w) for v, w in zip(vals, pps_widths))

    print(pps_row(pps_headers))
    _line(sum(pps_widths) + len(pps_widths) - 1)

    for flow_id in sorted(per_flow_metrics.keys()):
        stats = per_flow_metrics[flow_id].get("pps_stats", {})
        vals = [
            flow_id,
            _format_int(stats.get("count", 0)),
            _format_float(stats.get("mean_pps", 0.0), 0),
            _format_float(stats.get("median_pps", 0.0), 0),
            _format_float(stats.get("p90_pps", 0.0), 0),
            _format_float(stats.get("p99_pps", 0.0), 0),
            _format_float(stats.get("p999_pps", 0.0), 0),
            _format_float(stats.get("max_pps", 0.0), 0),
            _format_float(stats.get("std_pps", 0.0), 0),
            _format_float(stats.get("min_pps", 0.0), 0),
            _format_float(stats.get("p01_pps", 0.0), 0),
            _format_float(stats.get("p1_pps", 0.0), 0),
            _format_float(stats.get("p10_pps", 0.0), 0),
        ]
        print(pps_row(vals))
    _line(sum(pps_widths) + len(pps_widths) - 1)


def write_to_files():
    """
    write all captures data to files (under ./metrics)
      cli.txt - same as what was written to cli
      per_flow.csv - per flow metrics, but dont save bins
    """

    metrics_dir = Path("metrics")
    metrics_dir.mkdir(exist_ok=True)

    # print cli output to txt file
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_test_health_check()
        print_aggregate_metrics()
        print_per_flow_metrics()
    (metrics_dir / "cli.txt").write_text(buf.getvalue(), encoding="utf-8")

    rows = []
    for flow_id, m in per_flow_metrics.items():
        row = {
            "flow": flow_id,
            "duration_s": m.get("duration_s"),
            "packets": m.get("packets"),
            "bytes": m.get("bytes"),
            "throughput_mbps": m.get("throughput_mbps"),
            "pps": m.get("pps"),
            "retrans_packets": m.get("retrans_packets"),
            "ooo_packets": m.get("ooo_packets"),
            "lost_packets": m.get("lost_packets"),
        }
        for k, v in m.get("ipg_stats", {}).items():
            row[f"ipg_{k}"] = v
        for k, v in m.get("pps_stats", {}).items():
            row[f"pps_{k}"] = v
        rows.append(row)

    pd.DataFrame(rows).to_csv(metrics_dir / "per_flow.csv", index=False)


def write_plots(packets: pd.DataFrame):
    """
    create and save plots (under ./metrics)
    """

    metrics_dir = Path("metrics")
    metrics_dir.mkdir(exist_ok=True)

    for flow_id in sorted(per_flow_metrics.keys()):
        print(f"    generating plots for flow {flow_id}...")

        m = per_flow_metrics[flow_id]

        # plot ppb, ipg, retrans, and ooo over time
        plot_flow_micro_timeseries(flow_id, m["timeseries_micro"], metrics_dir)
        plot_flow_ms_events(flow_id, m["timeseries_ms"], metrics_dir)

        # get packet timestamps for flow
        df_flow = packets[packets["tcp.stream"] == flow_id]
        t, seq, tcp_len, frame_len, is_retrans, is_ooo, is_lost = _extract_flow_payload(df_flow)

        print(f"        generating histograms...")
        gaps_us = np.diff(t) * 1e6
        plot_flow_ipg_histograms(flow_id, gaps_us, metrics_dir)
        plot_flow_ppb_hist(flow_id, t, metrics_dir)

def main():
    print("-- Analysis of captured tcp started --")

    # get data needed
    packets = pd.read_csv("./packets.csv")

    print_test_health_check()

    generate_aggregate_metrics(packets)

    generate_per_flow_metrics(packets)

    print_aggregate_metrics()

    print_per_flow_metrics()
    
    write_to_files()

    write_plots(packets)

    print("-- Analysis of packets finished --")

if __name__ == "__main__":
    main()


# https://github.com/enfiskutensykkel/analyseTCP
# https://github.com/enfiskutensykkel/tcpstreamer