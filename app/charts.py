"""Pure plotly figure builders for the Streamlit app (no Streamlit imports)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.benchmarking import RATIO_INFO, axis_title, chart_values

NAVY = "#1f3a5f"
ACCENT = "#c0392b"
_LAYOUT = {"margin": {"l": 10, "r": 10, "t": 40, "b": 10}, "template": "plotly_white"}


def ratio_lines(df: pd.DataFrame, ratio: str) -> go.Figure:
    """One line per company over fiscal years; only status-ok points are drawn."""
    fig = go.Figure()
    ok = df[df["status"] == "ok"].sort_values("period_end")
    for ticker, g in ok.groupby("ticker"):
        fig.add_trace(
            go.Scatter(
                x=g["period_end"], y=chart_values(ratio, g["value"]), mode="lines+markers",
                name=ticker, customdata=g["fiscal_year_label"],
                hovertemplate="%{customdata} (ends %{x|%Y-%m-%d}): %{y:.2f}<extra>" + ticker + "</extra>",
            )
        )  # fmt: skip
    fig.update_layout(
        title=RATIO_INFO[ratio].label,
        yaxis_title=axis_title(ratio),
        xaxis_title="Fiscal year end",
        **_LAYOUT,
    )
    return fig


def ranking_bar(ranked: pd.DataFrame, ratio: str, median: float | None) -> go.Figure:
    """Latest-FY bars (valid values only) with the peer median as a dashed line."""
    fig = go.Figure()
    if len(ranked):
        fig.add_trace(
            go.Bar(
                x=ranked["ticker"], y=chart_values(ratio, ranked["value"]), marker_color=NAVY,
                customdata=ranked["fiscal_year_label"],
                hovertemplate="%{x} FY%{customdata}: %{y:.2f}<extra></extra>",
            )
        )  # fmt: skip
    if median is not None:
        m = chart_values(ratio, pd.Series([median])).iloc[0]
        fig.add_hline(y=m, line_dash="dash", line_color=ACCENT, annotation_text="Peer median")
    fig.update_layout(
        title=f"{RATIO_INFO[ratio].label}, latest fiscal year",
        yaxis_title=axis_title(ratio),
        showlegend=False,
        **_LAYOUT,
    )
    return fig
