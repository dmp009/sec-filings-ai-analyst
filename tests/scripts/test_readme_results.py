import pandas as pd
import pytest

from scripts.readme_results import (
    END,
    START,
    radar_precision,
    render_benchmark_table,
    render_block,
    render_radar_line,
    render_retrieval_table,
    replace_block,
)

RES = {
    ("ticker", "fy"): {"recall_at_5": 0.7667, "mrr": 0.645},
    ("ticker",): {"recall_at_5": 0.5667, "mrr": 0.335},
    (): {"recall_at_5": 0.4667, "mrr": 0.263},
}


def _ratios():
    from secanalyst.warehouse.quality import KEY_RATIOS

    rows = []
    for fy, pe in [("2025", "2025-09-27"), ("2026", "2026-09-26")]:
        for name, _, _ in KEY_RATIOS:
            rows.append(("AAPL", fy, pe, name, 0.25, "ok", None))
    rows.append(("AAPL", "2026", "2026-09-26", "roic", None, "n/m", "x"))
    df = pd.DataFrame(rows, columns=["ticker", "fiscal_year_label", "period_end", "ratio", "value", "status", "reason"])
    return df.drop_duplicates(["ticker", "fiscal_year_label", "ratio"], keep="last")


def test_retrieval_table():
    t = render_retrieval_table(RES, 30)
    assert "| company + fiscal year | 0.767 | 0.645 |" in t
    assert "| no filter | 0.467 | 0.263 |" in t


def test_radar_precision_uses_holdout_round():
    labels = pd.DataFrame({"round": [1, 1, 2, 2, 2, 2], "label": ["y", "n", "y", "y", "y", "n"]})
    assert radar_precision(labels) == (3, 4)
    assert "0.750 (3/4)" in render_radar_line(3, 4)


def test_benchmark_latest_year_and_status():
    t = render_benchmark_table(_ratios())
    row = t.splitlines()[2]
    assert row.startswith("| AAPL | 2026 | 2026-09-26 |") and "n/m" in row
    assert "2025" not in row


def test_replace_block_is_idempotent_and_requires_markers():
    readme = f"intro\n{START}\nSTALE\n{END}\noutro\n"
    block = render_block(RES, 30, (35, 40), _ratios(), "2026-11-13")
    once = replace_block(readme, block)
    assert "STALE" not in once and "0.875 (35/40)" in once and "2026-11-13" in once
    assert replace_block(once, block) == once
    assert once.startswith("intro\n") and once.endswith("outro\n")
    with pytest.raises(ValueError):
        replace_block("none", "x")
