import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mp
mp.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


MICRO_BIN_US = 20
FIRST_FLOW_TIMESERIES_MS = 10

SETUPS = [
    "direct-link_fq",
    "datacenter_fq",
    "internet_fq",
    "direct-link_fq_codel",
]
# SETUPS = ["direct-link_fq"]

SOLUTIONS = {
    "no-tso": "TSO Off",
    "tso": "TSO On",
    "tso-pacing": "TSO Pacing",
}

COLORS = {
    "no-tso": "#009E73",
    "tso": "#E69F00",
    "tso-pacing": "#0072B2",
}

plt.rcParams.update({
    "axes.titlesize": 26,
    "axes.labelsize": 26,
    "legend.fontsize": 23,
    "xtick.labelsize": 21,
    "ytick.labelsize": 21,
})

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

def get_all_flows_timeseries(df: pd.DataFrame, bin_us: int) -> dict[int, pd.DataFrame]:
    first_run_num = int(df["run_num"].min())
    df_run = df[df["run_num"] == first_run_num]
    
    flow_timeseries = {}
    for stream_id, df_flow in df_run.groupby("stream_id", sort=True):
        t_s = packet_times_s(df_flow)
        flow_timeseries[int(stream_id)] = build_packets_per_bin_timeseries(t_s, bin_us)
        
    return flow_timeseries

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
    sol_dir = base_dir / f"{setup}_{solution}"

    packets = pd.read_csv(sol_dir / "packets.csv")
    metrics = pd.read_csv(sol_dir / "metrics.csv")
    with open(sol_dir / "rtt.json", "r") as f:
        rtts = json.load(f)
    with open(sol_dir / "qlen.json", "r") as f:
        qlens = json.load(f)

    packets["run_num"] = pd.to_numeric(packets["run_num"])
    packets["stream_id"] = pd.to_numeric(packets["stream_id"])
    packets["p4_timestamp_ns"] = pd.to_numeric(packets["p4_timestamp_ns"])

    # remove flows with less than 100 packets
    flow_packet_counts = packets.groupby("stream_id").size()
    valid_stream_ids = flow_packet_counts[flow_packet_counts >= 100].index
    packets = packets[packets["stream_id"].isin(valid_stream_ids)]

    # sort all packets (although also do this in parse-p4sta.py)
    packets = packets.sort_values("p4_timestamp_ns", kind="mergesort")

    metrics["run_num"] = pd.to_numeric(metrics["run_num"])
    metrics["throughput_bps"] = pd.to_numeric(metrics["throughput_bps"])
    metrics["cpu_sender"] = pd.to_numeric(metrics["cpu_sender"])
    metrics["cpu_receiver"] = pd.to_numeric(metrics["cpu_receiver"])

    rtts = np.array(rtts, dtype=np.float64)

    # to plot cdf, we want qlengths as array of each occured value
    if qlens:
        qlen_lengths = [int(k) for k in qlens.keys()]
        qlen_counts = [int(v) for v in qlens.values()]
        qlens = np.repeat(qlen_lengths, qlen_counts)
    else:
        qlens = np.array([])

    return {
        "setup": setup,
        "solution": solution,
        "label": SOLUTIONS[solution],
        "color": COLORS[solution],
        "dir": sol_dir,
        "packets": packets,
        "metrics": metrics,
        "rtts": rtts,
        "qlens": qlens,
    }


def prepare_solution_data(solution_data: dict) -> dict:
    packets = solution_data["packets"]
    metrics = solution_data["metrics"]

    throughput_bps = metrics["throughput_bps"].dropna().to_numpy(dtype=np.float64)
    cpu_sender = metrics["cpu_sender"].dropna().to_numpy(dtype=np.float64)
    cpu_receiver = metrics["cpu_receiver"].dropna().to_numpy(dtype=np.float64)

    first_flow_timeseries = get_first_flow_timeseries(packets, MICRO_BIN_US)
    all_flows_timeseries = get_all_flows_timeseries(packets, MICRO_BIN_US)

    per_flow_idt_us = per_flow_inter_departure_us(packets)
    aggregate_idt_us = aggregate_inter_departure_us(packets)

    return {
        **solution_data,
        "throughput_bps": throughput_bps,
        "cpu_sender": cpu_sender,
        "cpu_receiver": cpu_receiver,
        "first_flow_timeseries": first_flow_timeseries,
        "all_flows_timeseries": all_flows_timeseries,
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
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)

def plot_throughput_and_rtt_boxplots(solutions: list[dict], setup: str, out_path: Path):
    fig, (ax_thr, ax_rtt) = plt.subplots(1, 2, figsize=(8, 6), sharex=True)

    labels = [sol["label"] for sol in solutions]
    positions = np.arange(1, len(solutions) + 1)
    colors = [sol["color"] for sol in solutions]

    # throughput
    thr_data = [(sol["throughput_bps"] / 1e9) for sol in solutions]
    thr_means = [np.mean(sol_thr) for sol_thr in thr_data]
    thr_stds = [np.std(sol_thr, ddof=1) if len(sol_thr) > 1 else 0.0 for sol_thr in thr_data]

    ax_thr.bar(positions, thr_means, yerr=thr_stds, color=colors,
               edgecolor="black", capsize=5, zorder=3)
    
    # set ylim based on expected throughput
    if setup in ["direct-link_fq", "direct-link_fq_codel"]:
        ax_thr.set_ylim(8.6, 9.6)
    elif setup == "datacenter_fq":
        ax_thr.set_ylim(3.4, 4.4)
    elif setup == "internet_fq":
        ax_thr.set_ylim(0.8, 1.8)

    ax_thr.set_title("Throughput")
    ax_thr.set_ylabel("Throughput (Gbps)")
    ax_thr.grid(True, axis="y", linestyle="--", alpha=0.5)

    # RTT
    rtt_data = [(sol["rtts"] / 1000.0) for sol in solutions]  # us -> ms
    bp_rtt = ax_rtt.boxplot(
        rtt_data,
        positions=positions,
        widths=0.6,
        patch_artist=True,
        labels=labels,
    )

    for i, sol in enumerate(solutions):
        bp_rtt["boxes"][i].set_facecolor(sol["color"])
        bp_rtt["boxes"][i].set_alpha(1)
    for med in bp_rtt["medians"]:
        med.set_color("black")

    ax_rtt.set_title("RTT")
    ax_rtt.set_ylabel("RTT (ms)")

    if setup in ["direct-link_fq", "direct-link_fq_codel", "datacenter_fq"]:
        ax_rtt.set_ylim(bottom=0)
    elif setup == "internet_fq":
        ax_rtt.set_ylim(bottom=20)

    ax_rtt.grid(True, axis="y", linestyle="--", alpha=0.5)

    for ax in (ax_thr, ax_rtt):
        ax.tick_params(axis="x", labelrotation=25, labelsize=20)
        ax.margins(x=0.05)

    _save_close(fig, out_path)

def plot_cpu_boxplot(solutions: list[dict], setup: str, out_path: Path):
    fig, (ax_sender, ax_receiver) = plt.subplots(1, 2, figsize=(8, 6), sharex=True)

    labels = [sol["label"] for sol in solutions]
    positions = np.arange(1, len(solutions) + 1)
    colors = [sol["color"] for sol in solutions]

    sender_data = [sol["cpu_sender"] for sol in solutions]
    sender_means = [np.mean(d) for d in sender_data]
    sender_stds = [np.std(d, ddof=1) if len(d) > 1 else 0.0 for d in sender_data]

    receiver_data = [sol["cpu_receiver"] for sol in solutions]
    receiver_means = [np.mean(d) for d in receiver_data]
    receiver_stds = [np.std(d, ddof=1) if len(d) > 1 else 0.0 for d in receiver_data]

    ax_sender.bar(positions, sender_means, yerr=sender_stds, width=0.6, 
                  color=colors, edgecolor="black", capsize=5, zorder=3)

    ax_receiver.bar(positions, receiver_means, yerr=receiver_stds, width=0.6, 
                    color=colors, edgecolor="black", capsize=5, zorder=3)

    ax_sender.set_title("Sender CPU")
    ax_receiver.set_title("Receiver CPU")

    ax_sender.set_ylabel("Average CPU usage (%)")

    ax_sender.grid(True, axis="y", linestyle="--", alpha=0.5)
    ax_receiver.grid(True, axis="y", linestyle="--", alpha=0.5)

    for ax in (ax_sender, ax_receiver):
        ax.set_xticks(positions)
        ax.set_xticklabels(labels)
        ax.tick_params(axis="x", labelrotation=25, labelsize=20)
        ax.margins(x=0.05)
    
    # no legend needed
    _save_close(fig, out_path)


def plot_firstflow_timeseries(solutions: list[dict], setup: str, out_path: Path):
    fig = plt.figure(figsize=(8, 6))

    x_start, x_end = 0, FIRST_FLOW_TIMESERIES_MS
    if setup in ["direct-link_fq", "direct-link_fq_codel"]:
        x_start, x_end = 100, 103
    elif setup == "datacenter_fq":
        x_start, x_end = 100, 105
    elif setup == "internet_fq":
        x_start, x_end = 100, 108

    for sol in solutions:
        df = sol["first_flow_timeseries"]
        x = df["start_s"].to_numpy()
        x_ms = (x - float(x[0])) * 1000.0
        y = df["bin_packets"].to_numpy()

        mask = (x_ms >= x_start) & (x_ms <= x_end)
        x_ms = x_ms[mask]
        y = y[mask]
        
        # place tso pacing behind
        if sol["label"] == "TSO Pacing":
            plt.plot(x_ms, y, label=sol["label"], color=sol["color"], linewidth=1.4, zorder=-1)
            plt.fill_between(x_ms, y, 0, color=sol["color"], alpha=0.22, linewidth=0)
        else:
            plt.plot(x_ms, y, label=sol["label"], color=sol["color"], linewidth=1.4, zorder=1)

    ax = plt.gca()
    ax.xaxis.set_major_locator(mticker.MultipleLocator(1))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(5))

    ax.minorticks_on()
    ax.xaxis.set_minor_locator(mp.ticker.NullLocator())
    ax.grid(True, which="major", axis="y", alpha=0.85, linestyle="--", linewidth=0.7)
    ax.grid(True, which="minor", axis="y", alpha=0.35, linestyle="--", linewidth=0.5)

    ax.yaxis.set_minor_formatter(mp.ticker.FormatStrFormatter('%d'))
    ax.tick_params(axis="y", which="minor", length=3, width=0.8, labelsize=16)
    ax.tick_params(axis="y", which="major", length=6, width=1.0, labelsize=20)
    ax.tick_params(axis="x", which="major", length=6, width=1.0, labelsize=20)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    plt.ylim(0, 35.1)
    plt.xlim(x_start, x_end)
    print(f"hello, {MICRO_BIN_US}!")
    plt.xlabel("Time elapsed (ms)")
    plt.ylabel(f"Packets per {MICRO_BIN_US} µs bin")
    # plt.title(f"Packet timeseries ({FIRST_FLOW_TIMESERIES_MS} ms)")
    plt.legend(loc='upper right')

    _save_close(fig, out_path)

def plot_flows_tso_pacing_timeseries(solutions: list[dict], setup: str, out_path: Path):
    fig = plt.figure(figsize=(10, 6))

    x_start, x_end = 0, FIRST_FLOW_TIMESERIES_MS
    if setup in ["direct-link_fq", "direct-link_fq_codel"]:
        x_start, x_end = 200, 203
    elif setup == "datacenter_fq":
        x_start, x_end = 100, 105
    elif setup == "internet_fq":
        x_start, x_end = 100, 108

    tso_pacing_sol = next((s for s in solutions if s["solution"] == "tso-pacing"), None)
    
    if not tso_pacing_sol:
        print("Warning: TSO-Pacing solution not found for plot_flows_tso_pacing_timeseries")
        return

    flows_timeseries = tso_pacing_sol["all_flows_timeseries"]
    
    global_t0 = None
    for df in flows_timeseries.values():
        if len(df) > 0:
            if global_t0 is None:
                global_t0 = float(df["start_s"].iloc[0])
            else:
                global_t0 = min(global_t0, float(df["start_s"].iloc[0]))
    
    if global_t0 is None:
        return

    for stream_id, df in flows_timeseries.items():
        x = df["start_s"].to_numpy()
        x_ms = (x - global_t0) * 1000.0
        y = df["bin_packets"].to_numpy()

        mask = (x_ms >= x_start) & (x_ms <= x_end)
        x_ms = x_ms[mask]
        y = y[mask]
        
        plt.plot(x_ms, y, linewidth=1.4, alpha=0.8, label=f"Flow {stream_id}")

    ax = plt.gca()
    ax.xaxis.set_major_locator(mticker.MultipleLocator(1))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(10))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(5))

    ax.minorticks_on()
    ax.xaxis.set_minor_locator(mp.ticker.NullLocator())
    ax.grid(True, which="major", axis="y", alpha=0.85, linestyle="--", linewidth=0.7)
    ax.grid(True, which="minor", axis="y", alpha=0.35, linestyle="--", linewidth=0.5)

    ax.yaxis.set_minor_formatter(mp.ticker.FormatStrFormatter('%d'))
    ax.tick_params(axis="y", which="minor", length=3, width=0.8, labelsize=16)
    ax.tick_params(axis="y", which="major", length=6, width=1.0, labelsize=20)
    ax.tick_params(axis="x", which="major", length=6, width=1.0, labelsize=20)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    plt.ylim(0, 35.1)
    plt.xlim(x_start, x_end)
    
    plt.xlabel("Time elapsed (ms)")
    plt.ylabel(f"Packets per {MICRO_BIN_US} µs bin")
    
    # Only show up to 10 items in legend to avoid cluttering
    handles, labels = ax.get_legend_handles_labels()
    plt.legend(handles[:10], labels[:10], loc='upper right', fontsize=12)

    _save_close(fig, out_path)

def plot_cdf(solutions: list[dict], setup: str, value_key: str, xlabel: str, out_path: Path, xlim: int):
    fig = plt.figure(figsize=(8, 6))

    for s in solutions:
        values = s[value_key]
        x, y = cdf_xy(values)
        plt.plot(x, y, label=s["label"], color=s["color"], linewidth=2)

    ax = plt.gca()
    ax.set_xscale("log")

    plt.gca().yaxis.set_major_locator(mticker.MultipleLocator(0.1))

    ax.grid(True, axis="x", linestyle="--", alpha=0.5)
    ax.tick_params(axis="x", which="both", top=True, labeltop=False)
    ax.tick_params(axis="y", which="both", right=True, labelright=False)

    ax.grid(True, which="major", axis="x", alpha=0.7, linestyle="--", linewidth=0.7)

    if xlim and False:
        plt.xlim(1, xlim)
    plt.xlabel(xlabel)
    plt.ylabel("Cumulative Probability")
    plt.legend()

    _save_close(fig, out_path)


def write_setup_plots(setup_result: dict, plots_dir: Path):
    setup = setup_result["setup"]
    solutions = setup_result["solutions"]

    setup_dir = plots_dir / setup
    setup_dir.mkdir(parents=True, exist_ok=True)

    plot_throughput_and_rtt_boxplots(
        solutions, setup,
        setup_dir / "throughput_rtt_boxplots.png",
    )

    plot_cpu_boxplot(
        solutions, setup,
        setup_dir / "cpu_boxplot.png"
    )

    plot_firstflow_timeseries(
        solutions, setup,
        setup_dir / f"timeseries_{MICRO_BIN_US}us.png",
    )

    plot_flows_tso_pacing_timeseries(
        solutions, setup,
        setup_dir / f"timeseries_tso_pacing_all_flows_{MICRO_BIN_US}us.png"
    )

    return

    plot_cdf(
        solutions, setup, "per_flow_idt_us",
        xlabel="Inter-departure time within flow (µs)",
        out_path=setup_dir / "per_flow_idt_cdf.png", xlim=1100,
    )

    plot_cdf(
        solutions, setup, "aggregate_idt_us",
        xlabel="Inter-departure time across all flows in run (µs)",
        out_path=setup_dir / "aggregate_idt_cdf.png", xlim=1100,
    )

    if len(solutions[0]["qlens"]) > 0:
        plot_cdf(
            solutions, setup, "qlens",
            xlabel="FQ/pacing IFB queue length",
            out_path=setup_dir / "qlens_cdf.png", xlim=0
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
