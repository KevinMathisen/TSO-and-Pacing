#!/usr/bin/env python3

import numpy as np
import matplotlib.pyplot as plt

# Hardcoded configuration
TSO_FILE = "tso-4gbps-10ms.txt"
TSO_PACING_FILE = "tso_pacing-4gbps-10ms.txt"
OUTPUT_FILE = "slow_start_cwnd.png"

RATE_BPS = 1_000_000_000
RTT_S = 20.4 / 1000
MSS_BYTES = 1460
bdp = RATE_BPS * RTT_S / (8 * MSS_BYTES) # if we want to plot bdp
# in that case, cwnd should grow to about double this value before experiencing packet loss


RUNS = 20


def read_results(filename):
    data = {}
    with open(filename) as f:
        for line in f:
            qlen, values = line.split(":")
            data[int(qlen)] = np.array([float(x) for x in values.split()])
    return data


def mean_std(values):
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return mean, std


tso = read_results(TSO_FILE)
tso_pacing = read_results(TSO_PACING_FILE)
qlens = sorted(tso.keys())

fig, ax = plt.subplots(figsize=(6, 2.5))

bar_width_in_log2 = 0.30


for data, label, marker, offset, color in [
    (tso, "Standard TSO", "o", -0.2, "#E69F00"),
    (tso_pacing, "TSO Pacing", "s", 0.2, "#0072B2"),
]:
    x = np.array(qlens) * 2**offset

    stats = [mean_std(data[q]) for q in qlens]
    means = [s[0] for s in stats]
    stds = [s[1] for s in stats]

    ax.bar(
        x,
        means,
        width=x * (2**bar_width_in_log2 - 1),
        yerr=stds,
        capsize=3,
        label=label,
        color=color,
        alpha=0.9,
        edgecolor="black",
        linewidth=0.8,
        zorder=3,
        error_kw=dict(elinewidth=1.2),
    )


ax.set_xscale("log", base=2)
ax.set_xticks(qlens)
ax.set_xticklabels(qlens)
ax.set_ylim(bottom=0)

ax.set_xlabel("Bottleneck queue limit (pkts)")
ax.set_ylabel("Max CWND (pkts)")
ax.grid(axis="y", alpha=0.3)
ax.legend(frameon=False)

fig.tight_layout()
fig.savefig(OUTPUT_FILE, bbox_inches="tight")

print(f"Saved {OUTPUT_FILE}")