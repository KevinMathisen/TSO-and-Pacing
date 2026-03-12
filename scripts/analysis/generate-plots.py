import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mp
mp.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


MICRO_BIN_US = 40
FIRST_FLOW_TIMESERIES_MS = 5

SETUPS = [
    "direct-link",
    "datacenter",
    "datacenter-hc",
    "internet",
]

SOLUTIONS = {
    "no-tso": "No TSO",
    "tso": "TSO",
    "tso-pacing": "TSO + Our Solution",
}

COLORS = {
    "no-tso": "#E69F00",
    "tso": "#009E73",
    "tso-pacing": "#0072B2",
}


def packet_times_s(df: pd.DataFrame) -> np.ndarray:
    return df["p4_timestamp_ns"].to_numpy(dtype=np.float64) / 1e9


def build_packets_per_bin_timeseries(t_s: np.ndarray, bin_us: int) -> pd.DataFrame:
    bin_width_s = bin_us / 1e6
    t0 = float(t_s.min())
    idx = np.floor((t_s - t0) / bin_width_s).astype(np.int64)
    n_bins = int(idx.max() + 1)

    packets_per_bin = np.bincount(idx, minlength=n_bins)
    bin_starts = t0 + np.arange(n_bins) * bin_width_s

    return pd.DataFrame({
        "start_s": bin_starts,
        "bin_packets": packets_per_bin,
    })


def get_first_flow_times(df: pd.DataFrame) -> np.ndarray:
    first_run_num = int(df["run_num"].min())
    df_run = df[df["run_num"] == first_run_num]

    first_stream_id = int(df_run["stream_id"].min())
    df_flow = df_run[df_run["stream_id"] == first_stream_id].sort_values(
        "p4_timestamp_ns", kind="mergesort"
    )

    return packet_times_s(df_flow)


def get_first_flow_timeseries(df_packets: pd.DataFrame, bin_us: int) -> pd.DataFrame:
    t_s = get_first_flow_times(df_packets)
    return build_packets_per_bin_timeseries(t_s, bin_us)


def per_flow_packets_per_bin_distribution(df: pd.DataFrame, bin_us: int) -> np.ndarray:
    """
    Compute packets-per-bin distribution across all runs, but bin each flow in each run separately.
    """
    all_bin_counts = []

    for _, df_flow in df.groupby(["run_num", "stream_id"], sort=True):
        t_s = packet_times_s(df_flow)
        if len(t_s) == 0:
            continue

        bin_width_s = bin_us / 1e6
        t0 = float(t_s.min())
        idx = np.floor((t_s - t0) / bin_width_s).astype(np.int64)
        n_bins = int(idx.max() + 1)

        flow_bin_counts = np.bincount(idx, minlength=n_bins)
        all_bin_counts.append(flow_bin_counts)

    return np.concatenate(all_bin_counts)


def per_flow_inter_departure_us(df: pd.DataFrame) -> np.ndarray:
    """
    For each flow in each run:
      - sort packets by timestamp
      - calculate IDTs within that flow
    Then combine all such IDTs across all runs and flows.
    """
    all_idts = []

    for _, df_flow in df.groupby(["run_num", "stream_id"], sort=True):
        t_s = packet_times_s(df_flow)
        if len(t_s) < 2:
            continue

        idts_us = np.diff(t_s) * 1e6
        all_idts.append(idts_us)

    return np.concatenate(all_idts)


def aggregate_inter_departure_us(df: pd.DataFrame) -> np.ndarray:
    """
    For each run:
      - sort all payload packets by timestamp
      - calculate IDTs across all packets in that run
    Then combine all such IDTs across runs.
    """
    all_idts = []

    for _, df_run in df.groupby("run_num", sort=True):
        t_s = packet_times_s(df_run)
        if len(t_s) < 2:
            continue

        idts_us = np.diff(t_s) * 1e6
        all_idts.append(idts_us)

    return np.concatenate(all_idts)


def load_solution(base_dir: Path, setup: str, solution: str) -> dict:
    sol_dir = base_dir / f"{setup}_fq_{solution}"

    packets = pd.read_csv(sol_dir / "packets.csv")
    metrics = pd.read_csv(sol_dir / "metrics.csv")
    with open(sol_dir / "rtt.json", "r") as f:
        rtts = json.load(f)

    packets["run_num"] = pd.to_numeric(packets["run_num"])
    packets["stream_id"] = pd.to_numeric(packets["stream_id"])
    packets["tcp_len"] = pd.to_numeric(packets["tcp_len"])
    packets["p4_timestamp_ns"] = pd.to_numeric(packets["p4_timestamp_ns"])

    # remove flows with less than 100 packets
    flow_packet_counts = packets.groupby("stream_id").size()
    valid_stream_ids = flow_packet_counts[flow_packet_counts >= 100].index
    packets = packets[packets["stream_id"].isin(valid_stream_ids)]

    # remove packets with no payload
    packets = packets[packets["tcp_len"] > 0]

    # sort all packets
    packets = packets.sort_values("p4_timestamp_ns", kind="mergesort")

    metrics["run_num"] = pd.to_numeric(metrics["run_num"])
    metrics["throughput_bps"] = pd.to_numeric(metrics["throughput_bps"])

    rtts = np.array(rtts, dtype=np.float64)

    return {
        "setup": setup,
        "solution": solution,
        "label": SOLUTIONS[solution],
        "color": COLORS[solution],
        "dir": sol_dir,
        "packets": packets,
        "metrics": metrics,
        "rtts": rtts,
    }


def prepare_solution_data(solution_data: dict) -> dict:
    packets = solution_data["packets"]
    metrics = solution_data["metrics"]

    throughput_bps = metrics["throughput_bps"].dropna().to_numpy(dtype=np.float64)

    first_flow_timeseries = get_first_flow_timeseries(packets, MICRO_BIN_US)
    first_flow_t_s = get_first_flow_times(packets)

    per_flow_packets_per_bin = per_flow_packets_per_bin_distribution(packets, MICRO_BIN_US)
    per_flow_idt_us = per_flow_inter_departure_us(packets)
    aggregate_idt_us = aggregate_inter_departure_us(packets)

    return {
        **solution_data,
        "throughput_bps": throughput_bps,
        "first_flow_timeseries": first_flow_timeseries,
        "first_flow_t_s": first_flow_t_s,
        "packets_per_bin": per_flow_packets_per_bin,
        "per_flow_idt_us": per_flow_idt_us,
        "aggregate_idt_us": aggregate_idt_us,
    }


def analyze_setup(base_dir: Path, setup: str) -> dict:
    solutions = []

    for solution_key in SOLUTIONS:
        solution = load_solution(base_dir, setup, solution_key)
        solutions.append(prepare_solution_data(solution))

    return {
        "setup": setup,
        "solutions": solutions,
    }


# ===== Plot functions =====

def cdf_xy(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(values)
    y = np.linspace(0, 1, len(x))
    return x, y

def _save_close(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)


def plot_throughput_boxplot(solutions: list[dict], out_path: Path):
    fig = plt.figure(figsize=(8, 6))

    data = []
    labels = []
    for sol in solutions:
        data.append(sol["throughput_bps"] / 1e9)  # bps -> Gbps
        labels.append(sol["label"])

    bp = plt.boxplot(data, patch_artist=True, labels=labels, widths=0.6)

    for patch, sol in zip(bp["boxes"], solutions):
        patch.set_facecolor(sol["color"])
        patch.set_alpha(0.45)

    plt.ylabel("Throughput (Gbps)")
    plt.title("Throughput distribution")
    plt.grid(True, axis="y", linestyle="--", alpha=0.5)

    _save_close(fig, out_path)


def plot_rtt_boxplot(solutions: list[dict], out_path: Path):
    fig = plt.figure(figsize=(8, 6))

    data = []
    labels = []
    for sol in solutions:
        data.append(sol["rtts"])
        labels.append(sol["label"])

    bp = plt.boxplot(data, patch_artist=True, labels=labels, widths=0.6)

    for patch, sol in zip(bp["boxes"], solutions):
        patch.set_facecolor(sol["color"])
        patch.set_alpha(0.45)

    plt.ylabel("RTT")
    plt.title("RTT distribution")
    plt.grid(True, axis="y", linestyle="--", alpha=0.5)

    _save_close(fig, out_path)


def plot_firstflow_timeseries(solutions: list[dict], out_path: Path):
    fig = plt.figure(figsize=(10, 6))

    for sol in solutions:
        df = sol["first_flow_timeseries"]
        x = df["start_s"].to_numpy()
        x_ms = (x - float(x[0])) * 1000.0
        y = df["bin_packets"].to_numpy()

        mask = x_ms <= FIRST_FLOW_TIMESERIES_MS
        x_ms = x_ms[mask]
        y = y[mask]

        plt.plot(x_ms, y, label=sol["label"], color=sol["color"], linewidth=1.4)
        plt.fill_between(x_ms, y, 0, color=sol["color"], alpha=0.22, linewidth=0)

    ax = plt.gca()
    ax.xaxis.set_major_locator(mticker.MultipleLocator(1))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(2))

    ax.minorticks_on()
    ax.xaxis.set_minor_locator(mp.ticker.NullLocator())
    ax.grid(True, which="major", axis="y", alpha=0.85, linestyle="--", linewidth=0.7)
    ax.grid(True, which="minor", axis="y", alpha=0.35, linestyle="--", linewidth=0.5)

    ax.yaxis.set_minor_formatter(mp.ticker.FormatStrFormatter('%d'))
    ax.tick_params(axis="y", which="minor", length=3, width=0.8, labelsize=12)
    ax.tick_params(axis="y", which="major", length=6, width=1.0, labelsize=14)
    ax.tick_params(axis="x", which="major", length=6, width=1.0, labelsize=14)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    plt.xlim(0, FIRST_FLOW_TIMESERIES_MS)
    plt.xlabel("Time elapsed (ms)")
    plt.ylabel(f"Packets per {MICRO_BIN_US} µs bin")
    plt.title(f"Packet timeseries ({FIRST_FLOW_TIMESERIES_MS} ms)")
    plt.legend(loc='upper right')

    _save_close(fig, out_path)


def plot_packets_per_bin_violin(solutions: list[dict], out_path: Path):
    fig = plt.figure(figsize=(8, 6))

    data = [sol["packets_per_bin"] for sol in solutions]
    positions = np.arange(1, len(solutions) + 1)

    parts = plt.violinplot(
        data,
        positions=positions,
        showmeans=False,
        showmedians=True,
        showextrema=True,
    )

    for body, sol in zip(parts["bodies"], solutions):
        body.set_facecolor(sol["color"])
        body.set_edgecolor(sol["color"])
        body.set_alpha(0.35)

    for k in ("cbars", "cmins", "cmaxes", "cmedians"):
        if k in parts:
            parts[k].set_color("black")
            parts[k].set_linewidth(1.0)

    plt.xticks(positions, [sol["label"] for sol in solutions])
    plt.ylabel(f"Packets per {MICRO_BIN_US} µs bin")
    plt.title(f"Distribution of packets per {MICRO_BIN_US} µs bin")
    plt.grid(True, axis="y", linestyle="--", alpha=0.5)

    _save_close(fig, out_path)


def plot_cdf(solutions: list[dict], value_key: str, xlabel: str, out_path: Path):
    fig = plt.figure(figsize=(10, 6))

    for s in solutions:
        values = s[value_key]
        x, y = cdf_xy(values)
        plt.plot(x, y, label=s["label"], color=s["color"], linewidth=1.6)

    ax = plt.gca()
    ax.set_xscale("log")

    plt.gca().yaxis.set_major_locator(mticker.MultipleLocator(0.1))

    ax.grid(True, axis="x", linestyle="--", alpha=0.5)
    ax.tick_params(axis="x", which="both", top=True, labeltop=False)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    ax.grid(True, which="major", axis="x", alpha=0.7, linestyle="--", linewidth=0.5)

    plt.xlabel(xlabel)
    plt.ylabel("Cumulative Probability")
    plt.legend()

    _save_close(fig, out_path)


def write_setup_plots(setup_result: dict, plots_dir: Path):
    setup = setup_result["setup"]
    solutions = setup_result["solutions"]

    setup_dir = plots_dir / setup
    setup_dir.mkdir(parents=True, exist_ok=True)

    plot_throughput_boxplot(
        solutions,
        setup_dir / "throughput_boxplot.png",
    )

    plot_rtt_boxplot(
        solutions,
        setup_dir / "rtt_boxplot.png",
    )

    plot_firstflow_timeseries(
        solutions,
        setup_dir / f"timeseries_{MICRO_BIN_US}us.png",
    )

    plot_packets_per_bin_violin(
        solutions,
        setup_dir / f"packets_per_{MICRO_BIN_US}us_bin_violin.png",
    )

    plot_cdf(
        solutions, "per_flow_idt_us",
        xlabel="Inter-departure time within flow (µs)",
        out_path=setup_dir / "per_flow_idt_cdf.png",
    )

    plot_cdf(
        solutions, "aggregate_idt_us",
        xlabel="Inter-departure time across all flows in run (µs)",
        out_path=setup_dir / "aggregate_idt_cdf.png",
    )


def main():
    base_dir = Path("aggregates")
    plots_dir = Path("plots")
    plots_dir.mkdir(exist_ok=True)

    for setup in SETUPS:
        print(f"Generating data for {setup}...")
        setup_data = analyze_setup(base_dir, setup)
        
        print(f"Generating plots for {setup}...")
        write_setup_plots(setup_data, plots_dir)

    print("")
    print(f"Done! Plots written to {plots_dir}/")


if __name__ == "__main__":
    main()
