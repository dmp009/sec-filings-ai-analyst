"""Pure helpers for the Benchmarking page: ratio metadata, formatting, latest-FY ranking.
No Streamlit imports so they are unit-testable."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class RatioInfo:
    label: str
    unit: str  # pct | x | days | usd
    definition: str


RATIO_INFO: dict[str, RatioInfo] = {
    "revenue_growth": RatioInfo(
        "Revenue growth", "pct", "Revenue divided by prior-year revenue, minus 1."
    ),
    "gross_margin": RatioInfo(
        "Gross margin",
        "pct",
        "Gross profit / revenue. Gross profit is the reported tag, else revenue minus cost of revenue.",
    ),
    "operating_margin": RatioInfo("Operating margin", "pct", "Operating income / revenue."),
    "net_margin": RatioInfo("Net margin", "pct", "Net income / revenue."),
    "fcf_margin": RatioInfo(
        "FCF margin",
        "pct",
        "Free cash flow / revenue. FCF = operating cash flow minus capex. Amazon's capex is "
        "gross purchases of property and equipment (finance-lease additions are not deducted).",
    ),
    "fcf_conversion": RatioInfo(
        "FCF conversion", "pct", "Free cash flow / net income. n/m when net income <= 0."
    ),
    "capex_intensity": RatioInfo("Capex intensity", "pct", "Capex / revenue."),
    "roic": RatioInfo(
        "ROIC",
        "pct",
        "NOPAT / invested capital. NOPAT = operating income x (1 - tax rate), rate = income tax "
        "/ pretax income clamped to 0-35%. Invested capital = equity + total debt - cash and "
        "marketable securities. n/m when equity or invested capital <= 0, or when invested "
        "capital is below 10% of total assets (dominated by netting cash against debt).",
    ),
    "roe": RatioInfo("ROE", "pct", "Net income / year-end equity. n/m when equity <= 0."),
    "net_cash": RatioInfo(
        "Net cash",
        "usd",
        "Cash, short-term investments and long-term marketable securities minus total debt "
        "(incl. finance leases). Negative means net debt.",
    ),
    "debt_to_ebitda": RatioInfo(
        "Debt / EBITDA",
        "x",
        "Total debt / (operating income + depreciation and amortization). n/m when EBITDA <= 0. "
        "D&A may omit minor amortization items for Alphabet, Tesla and Microsoft.",
    ),
    "dso": RatioInfo(
        "Receivable days (DSO)", "days", "Receivables / revenue x 365, year-end balances."
    ),
    "dio": RatioInfo(
        "Inventory days (DIO)", "days", "Inventory / cost of revenue x 365, year-end balances."
    ),
    "dpo": RatioInfo(
        "Payable days (DPO)", "days", "Payables / cost of revenue x 365, year-end balances."
    ),
    "ccc": RatioInfo("Cash conversion cycle", "days", "DSO + DIO - DPO."),
}

FY_NOTE = (
    "Fiscal years differ: NVIDIA's ends in late January, Microsoft's in June, Apple's in "
    "September and Broadcom's around the start of November; the others end in December. "
    "A fiscal-year label is the calendar year in which the year ends, so columns are not "
    "calendar-aligned across companies."
)


def fmt_value(ratio: str, value: float | None, status: str = "ok") -> str:
    if status != "ok" or value is None or pd.isna(value):
        return status if status in ("n/a", "n/m") else "n/a"
    unit = RATIO_INFO[ratio].unit
    if unit == "pct":
        return f"{value * 100:.1f}%"
    if unit == "x":
        return f"{value:.1f}x"
    if unit == "days":
        return f"{value:.0f} days"
    return f"${value / 1e9:.1f}bn"


def chart_values(ratio: str, s: pd.Series) -> pd.Series:
    """Values in display units (percent, ratio, days, $bn)."""
    unit = RATIO_INFO[ratio].unit
    return s * 100 if unit == "pct" else s / 1e9 if unit == "usd" else s


def axis_title(ratio: str) -> str:
    return {"pct": "%", "x": "x", "days": "days", "usd": "$bn"}[RATIO_INFO[ratio].unit]


def latest_ranking(df: pd.DataFrame) -> tuple[pd.DataFrame, float | None, str]:
    """Each company's latest fiscal year of one ratio, ranked high to low.

    Only status ``ok`` rows are ranked and enter the peer median; n/a and n/m never do.
    Returns (ranked rows, median or None, latest fiscal-year label overall).
    """
    latest = df.sort_values("period_end").groupby("ticker").tail(1)
    label = str(df["fiscal_year_label"].max())
    ok = latest[latest["status"] == "ok"].dropna(subset=["value"])
    ranked = ok.sort_values("value", ascending=False).reset_index(drop=True)
    median = float(ranked["value"].median()) if len(ranked) else None
    return ranked, median, label
