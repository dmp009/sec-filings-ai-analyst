"""Pure plotly figure builders for the Streamlit app (no Streamlit imports)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.benchmarking import RATIO_INFO, axis_title, chart_values

# Sober portfolio palette, shared with .streamlit/config.toml (validated with the dataviz palette checker).
BLUE = "#2558A8"  # main series (deep blue)
ORANGE = "#B7791F"  # muted gold: second series, reference lines
RED = "#C2362B"  # status: below / price
GREY = "#9AA5B4"  # "before" / neutral comparison
INK = "#0B0D10"
GRID = "#E5E7EB"
_LAYOUT = {
    "margin": {"l": 10, "r": 10, "t": 50, "b": 10},
    "template": "plotly_white",
    "colorway": ["#2558A8", "#B7791F", "#1F9D55", "#7C3AED", "#C2362B", "#0E9AA7", "#E8590C", "#DB2777"],
    "font": {"family": "Inter, Arial, sans-serif", "color": INK, "size": 13},
    "title_x": 0,
    "title_xanchor": "left",
    "title_font_size": 16,
    "legend": {"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 1, "xanchor": "right"},
    "xaxis": {"gridcolor": GRID, "zeroline": False},
    "yaxis": {"gridcolor": GRID, "zeroline": False},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
}


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
                x=ranked["ticker"], y=chart_values(ratio, ranked["value"]), marker_color=BLUE,
                marker={"cornerradius": 6},
                customdata=ranked["fiscal_year_label"],
                hovertemplate="%{x} FY%{customdata}: %{y:.2f}<extra></extra>",
            )
        )  # fmt: skip
    if median is not None:
        m = chart_values(ratio, pd.Series([median])).iloc[0]
        fig.add_hline(y=m, line_dash="dash", line_color=ORANGE, annotation_text="Peer median")
    fig.update_layout(
        title=f"{RATIO_INFO[ratio].label}, latest fiscal year",
        yaxis_title=axis_title(ratio),
        showlegend=False,
        **_LAYOUT,
    )
    return fig
