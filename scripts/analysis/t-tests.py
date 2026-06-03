import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


SETUPS = [
    "direct-link_fq",
    "datacenter_fq",
    "internet_fq",
    "datacenter_fq_codel",
]
SETUPS = [
    "datacenter_fq",
]

SOLUTIONS = {
    "no-tso": "TSO Off",
    "tso": "TSO On",
    "tso-pacing": "TSO Pacing",
}

METRICS = [
    ("throughput_bps", "Throughput (bps)"),
    ("cpu_sender", "Sender CPU (%)"),
    ("cpu_receiver", "Receiver CPU (%)"),
    ("rtt_mean_per_run", "RTT mean per run (us)"),
]

ALPHA = 0.05
RTT_SAMPLES_PER_RUN = 12*4


def load_solution(base_dir: Path, setup: str, solution: str) -> dict:
    sol_dir = base_dir / f"{setup}_{solution}"

    metrics = pd.read_csv(sol_dir / "metrics.csv")
    with open(sol_dir / "rtt.json", "r") as f:
        rtts = json.load(f)

    metrics["run_num"] = pd.to_numeric(metrics["run_num"])
    metrics["throughput_bps"] = pd.to_numeric(metrics["throughput_bps"])
    metrics["cpu_sender"] = pd.to_numeric(metrics["cpu_sender"])
    metrics["cpu_receiver"] = pd.to_numeric(metrics["cpu_receiver"])

    rtts = np.array(rtts, dtype=np.float64)

    return {
        "setup": setup,
        "solution": solution,
        "label": SOLUTIONS[solution],
        "dir": sol_dir,
        "metrics": metrics,
        "rtts": rtts,
    }


def prepare_solution_data(solution_data: dict) -> dict:
    metrics = solution_data["metrics"]
    rtts = solution_data["rtts"]

    throughput_bps = metrics["throughput_bps"].dropna().to_numpy(dtype=np.float64)
    cpu_sender = metrics["cpu_sender"].dropna().to_numpy(dtype=np.float64)
    cpu_receiver = metrics["cpu_receiver"].dropna().to_numpy(dtype=np.float64)

    if len(rtts) % RTT_SAMPLES_PER_RUN != 0:
        raise ValueError(
            f"{solution_data['dir']} has {len(rtts)} RTT values, "
            f"so it is not {RTT_SAMPLES_PER_RUN} samples per run!"
        )

    rtt_mean_per_run = rtts.reshape(-1, RTT_SAMPLES_PER_RUN).mean(axis=1)

    expected_runs = len(metrics)
    if len(rtt_mean_per_run) != expected_runs:
        raise ValueError(
            f"{solution_data['dir']}: metrics.csv has {expected_runs} runs, "
            f"but rtt.json corresponds to {len(rtt_mean_per_run)} runs"
        )

    return {
        **solution_data,
        "throughput_bps": throughput_bps,
        "cpu_sender": cpu_sender,
        "cpu_receiver": cpu_receiver,
        "rtt_mean_per_run": rtt_mean_per_run,
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


def welch_ttest(x: np.ndarray, y: np.ndarray) -> dict:
    result = stats.ttest_ind(x, y, equal_var=False, alternative="two-sided")

    return {
        "t_stat": float(result.statistic),
        "p_value": float(result.pvalue),
    }


def analyze_metric(solutions: list[dict], metric_key: str) -> list[dict]:
    comparisons = [(0, 1), (0, 2), (1, 2)]
    results = []

    for i, j in comparisons:
        x = solutions[i][metric_key]
        y = solutions[j][metric_key]

        test_result = welch_ttest(x, y)

        results.append({
            "solution_a": solutions[i]["label"],
            "solution_b": solutions[j]["label"],
            "t_stat": test_result["t_stat"],
            "p_value": test_result["p_value"],
            "significant": test_result["p_value"] < ALPHA,
        })

    return results


def print_metric_results(solutions: list[dict], metric_key: str, metric_label: str):
    print(f"  {metric_label}")

    for solution in solutions:
        values = solution[metric_key]
        mean = float(np.mean(values))
        std = float(np.std(values, ddof=1))
        print(
            f"    {solution['label']}: "
            f"n={len(values)}, mean={mean:.6f}, std={std:.6f}"
        )

    print("")

    test_results = analyze_metric(solutions, metric_key)
    for result in test_results:
        significance = "SIGNIFICANT" if result["significant"] else "not significant"
        print(
            f"    {result['solution_a']} vs {result['solution_b']}: "
            f"t={result['t_stat']:.6f}, "
            f"p={result['p_value']:.6g} -> {significance}"
        )

    print("")


def print_setup_results(setup_result: dict):
    print(f"=== {setup_result['setup']} ===")
    print("")

    solutions = setup_result["solutions"]

    for metric_key, metric_label in METRICS:
        print_metric_results(solutions, metric_key, metric_label)

    print("")


def main():
    base_dir = Path("aggregates")

    for setup in SETUPS:
        print(f"Analyzing {setup}...")
        setup_data = analyze_setup(base_dir, setup)
        print("")
        print_setup_results(setup_data)

        print(f"Done. Welch two-sided t-tests run with alpha={ALPHA:.2f}, confidence={1 - ALPHA:.2f}")


if __name__ == "__main__":
    main()