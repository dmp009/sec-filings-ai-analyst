import pandas as pd
import plotly.graph_objects as go

from app.benchmarking import RATIO_INFO, fmt_value, latest_ranking
from app.charts import ranking_bar, ratio_lines
from secanalyst.financials.ratios import RATIOS


def _df():
    return pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D", "A", "B"],
            "fiscal_year_label": ["2025", "2025", "2025", "2025", "2024", "2024"],
            "period_end": pd.to_datetime(["2025-12-31"] * 4 + ["2024-12-31"] * 2),
            "ratio": ["roe"] * 6,
            "value": [0.1, 0.3, None, None, 0.2, 0.4],
            "status": ["ok", "ok", "n/m", "n/a", "ok", "ok"],
            "reason": [None, None, "equity <= 0", "missing concept x", None, None],
        }
    )


def test_ranking_excludes_nm_and_na_and_median_on_ok_only():
    ranked, median, label = latest_ranking(_df())
    assert label == "2025"
    assert list(ranked["ticker"]) == ["B", "A"]
    assert median == 0.2


def test_ranking_all_invalid_gives_none_median():
    df = _df()
    df["status"] = "n/m"
    df["value"] = None
    ranked, median, _ = latest_ranking(df)
    assert ranked.empty and median is None


def test_fmt_value_units():
    assert fmt_value("roe", 0.1234) == "12.3%"
    assert fmt_value("debt_to_ebitda", 1.5) == "1.5x"
    assert fmt_value("dso", 30.4) == "30 days"
    assert fmt_value("net_cash", 12.5e9) == "$12.5bn"
    assert fmt_value("roe", None, "n/m") == "n/m"


def test_every_ratio_has_info():
    for r in RATIOS:
        assert RATIO_INFO[r].label and RATIO_INFO[r].definition


def test_charts_are_pure_figures():
    assert isinstance(ratio_lines(_df(), "roe"), go.Figure)
    ranked, median, _ = latest_ranking(_df())
    assert isinstance(ranking_bar(ranked, "roe", median), go.Figure)
    assert isinstance(ranking_bar(ranked.iloc[0:0], "roe", None), go.Figure)
