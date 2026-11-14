"""Regenerate the README images in docs/img/ (matplotlib re-plots of the data, not screenshots).

Usage: python -m scripts.readme_figures  (or `make figures`)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts.readme_results import FILTER_LABELS, collect

OUT = Path("docs/img")
NAVY, BLUE, GREY = "#1f3a5f", "#4a78b0", "#9aa5b1"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "figure.dpi": 110})  # fmt: skip


def retrieval_figure(results: dict, n: int) -> Path:
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    labels = [label for _, label in FILTER_LABELS]
    x = range(len(labels))
    r5 = [results[k]["recall_at_5"] for k, _ in FILTER_LABELS]
    mrr = [results[k]["mrr"] for k, _ in FILTER_LABELS]
    ax.bar([i - 0.19 for i in x], r5, 0.38, color=NAVY, label="recall@5")
    ax.bar([i + 0.19 for i in x], mrr, 0.38, color=BLUE, label="MRR")
    for i, (a, b) in enumerate(zip(r5, mrr, strict=True)):
        ax.text(i - 0.19, a + 0.015, f"{a:.2f}", ha="center", fontsize=9)
        ax.text(i + 0.19, b + 0.015, f"{b:.2f}", ha="center", fontsize=9)
    ax.set_xticks(list(x), labels)
    ax.set_ylim(0, 1)
    ax.set_title(f"Retrieval quality by filters set ({n} labelled questions)")
    ax.legend(frameon=False)
    return _save(fig, "retrieval_eval.png")


def margins_figure(ratios) -> Path:
    latest = ratios.sort_values("period_end").groupby("ticker").tail(1)
    keep = ratios.merge(latest[["ticker", "fiscal_year_label"]], on=["ticker", "fiscal_year_label"])
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.4), sharey=True)
    for ax, ratio, title in zip(
        axes,
        ["operating_margin", "fcf_margin"],
        ["Operating margin", "Free-cash-flow margin"],
        strict=True,
    ):
        d = keep[(keep["ratio"] == ratio) & (keep["status"] == "ok")].sort_values("value")
        ax.barh(d["ticker"], d["value"] * 100, color=BLUE)
        ax.axvline(d["value"].median() * 100, color=GREY, ls="--", lw=1)
        ax.set_title(title)
        ax.set_xlabel("% of revenue (latest fiscal year; dashed = median)")
    return _save(fig, "margins_latest_fy.png")


def _save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def main() -> None:
    results, n, _radar, ratios, _as_of = collect()
    for p in (retrieval_figure(results, n), margins_figure(ratios)):
        print("wrote", p)


if __name__ == "__main__":
    main()
