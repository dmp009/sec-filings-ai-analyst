"""Peer ratios from annual financials (design §6.3, §9.4).

Every (ticker, fiscal year, ratio) gets a row with ``status``:
- ``ok``  — value computed;
- ``n/a`` — an input concept is missing; reason ``missing concept <name>`` (never imputed);
- ``n/m`` — inputs present but the ratio is not meaningful (e.g. equity <= 0), reason given.

Definitions (year-end balances, 365-day year):
- revenue_growth = revenue / prior-year revenue - 1
- gross_margin = gross profit / revenue, gross profit = ``gross_profit`` tag, else revenue -
  cost of revenue; operating_margin, net_margin likewise over revenue
- FCF = operating cash flow - capex; fcf_margin = FCF / revenue; fcf_conversion = FCF / net
  income (n/m when net income <= 0); capex_intensity = capex / revenue
- NOPAT = operating income x (1 - effective tax rate), rate = income tax / pretax income
  clamped to [0, 35 %] (0 when pretax income <= 0)
- invested capital = equity + total debt - liquidity; roic = NOPAT / invested capital,
  roe = net income / equity; n/m when equity <= 0 or invested capital <= 0. Ruling R4 (extends
  §9.4): roic is also n/m when invested capital < 10 % of total assets — ROIC is then dominated
  by netting cash against debt and equity (Apple FY2022–24)
- net_cash = liquidity - total debt (USD)
- debt_to_ebitda = total debt / (operating income + D&A); n/m when EBITDA <= 0. D&A for
  Alphabet, Tesla (depreciation only) and Microsoft (depreciation + intangibles amortization)
  may exclude minor amortization items; a depreciation-only year is withheld (n/a) when the
  company reports material intangibles amortization in other years (Broadcom FY2021–22)
- dso = receivables / revenue x 365; dio = inventory / cost of revenue x 365;
  dpo = payables / cost of revenue x 365; ccc = dso + dio - dpo
  (cost of revenue = ``cost_of_revenue`` tag, else revenue - gross profit)
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

RATIO_COLUMNS = [
    "ticker",
    "fiscal_year_label",
    "period_end",
    "ratio",
    "value",
    "status",
    "reason",
]
RATIOS = [
    "revenue_growth", "gross_margin", "operating_margin", "net_margin", "fcf_margin",
    "fcf_conversion", "capex_intensity", "roic", "roe", "net_cash", "debt_to_ebitda",
    "dso", "dio", "dpo", "ccc",
]  # fmt: skip
TAX_RATE_CAP = 0.35
MIN_IC_TO_ASSETS = 0.10  # R4
DAYS = 365


class _Missing(Exception):
    def __init__(self, concept: str):
        self.reason = f"missing concept {concept}"


class _NotMeaningful(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:g}"


class _Year:
    """Accessors over one company-year of financials (and the prior year)."""

    def __init__(self, cur: dict[str, float], prior: dict[str, float] | None):
        self.cur, self.prior = cur, prior

    def get(self, concept: str) -> float:
        if concept not in self.cur or pd.isna(self.cur[concept]):
            raise _Missing(concept)
        return float(self.cur[concept])

    def positive(self, concept: str, what: str | None = None) -> float:
        v = self.get(concept)
        if v <= 0:
            raise _NotMeaningful(f"{what or concept} <= 0 ({_fmt(v)})")
        return v

    def revenue(self) -> float:
        return self.positive("revenue")

    def gross_profit(self) -> float:
        if "gross_profit" in self.cur:
            return self.get("gross_profit")
        try:
            return self.revenue() - self.get("cost_of_revenue")
        except _Missing:
            raise _Missing("cost_of_revenue") from None

    def cost_of_revenue(self) -> float:
        if "cost_of_revenue" in self.cur:
            v = self.get("cost_of_revenue")
        elif "gross_profit" in self.cur:
            v = self.revenue() - self.get("gross_profit")
        else:
            raise _Missing("cost_of_revenue")
        if v <= 0:
            raise _NotMeaningful(f"cost of revenue <= 0 ({_fmt(v)})")
        return v

    def fcf(self) -> float:
        return self.get("operating_cash_flow") - self.get("capex")

    def nopat(self) -> float:
        oi, tax, pretax = (
            self.get("operating_income"),
            self.get("income_tax"),
            self.get("pretax_income"),
        )
        rate = min(max(tax / pretax, 0.0), TAX_RATE_CAP) if pretax > 0 else 0.0
        return oi * (1 - rate)

    def equity(self) -> float:
        return self.positive("total_equity", "equity")

    def invested_capital(self) -> float:
        ic = self.equity() + self.get("total_debt") - self.get("liquidity")
        if ic <= 0:
            raise _NotMeaningful(f"invested capital <= 0 ({_fmt(ic)})")
        return ic

    def dso(self) -> float:
        return self.get("receivables") / self.revenue() * DAYS

    def dio(self) -> float:
        inv = self.get("inventory")
        return inv / self.cost_of_revenue() * DAYS

    def dpo(self) -> float:
        pay = self.get("payables")
        return pay / self.cost_of_revenue() * DAYS


class _MissingPrior(_Missing):
    def __init__(self):
        self.reason = "missing concept revenue (prior fiscal year)"


def _growth(y: _Year) -> float:
    if not y.prior or "revenue" not in y.prior or pd.isna(y.prior["revenue"]):
        y.get("revenue")  # current revenue missing takes precedence
        raise _MissingPrior()
    prev = y.prior["revenue"]
    if prev <= 0:
        raise _NotMeaningful(f"prior-year revenue <= 0 ({_fmt(prev)})")
    return y.get("revenue") / prev - 1


def _fcf_conversion(y: _Year) -> float:
    fcf = y.fcf()
    return fcf / y.positive("net_income", "net income")


def _roic(y: _Year) -> float:
    ic = y.invested_capital()  # n/m checks (equity, invested capital) before NOPAT inputs
    assets = y.get("total_assets")
    if ic < MIN_IC_TO_ASSETS * assets:
        raise _NotMeaningful(
            f"invested capital ${ic / 1e9:.1f}bn < 10% of total assets (${assets / 1e9:.1f}bn); "
            "ROIC dominated by cash netting"
        )
    return y.nopat() / ic


def _roe(y: _Year) -> float:
    equity = y.equity()
    return y.get("net_income") / equity


def _debt_to_ebitda(y: _Year) -> float:
    debt = y.get("total_debt")
    ebitda = y.get("operating_income") + y.get("depreciation_amortization")
    if ebitda <= 0:
        raise _NotMeaningful(f"EBITDA <= 0 ({_fmt(ebitda)})")
    return debt / ebitda


FORMULAS: dict[str, Callable[[_Year], float]] = {
    "revenue_growth": _growth,
    "gross_margin": lambda y: y.gross_profit() / y.revenue(),
    "operating_margin": lambda y: y.get("operating_income") / y.revenue(),
    "net_margin": lambda y: y.get("net_income") / y.revenue(),
    "fcf_margin": lambda y: y.fcf() / y.revenue(),
    "fcf_conversion": _fcf_conversion,
    "capex_intensity": lambda y: y.get("capex") / y.revenue(),
    "roic": _roic,
    "roe": _roe,
    "net_cash": lambda y: y.get("liquidity") - y.get("total_debt"),
    "debt_to_ebitda": _debt_to_ebitda,
    "dso": _Year.dso,
    "dio": _Year.dio,
    "dpo": _Year.dpo,
    "ccc": lambda y: y.dso() + y.dio() - y.dpo(),
}
assert list(FORMULAS) == RATIOS


def compute_ratios(fin: pd.DataFrame) -> pd.DataFrame:
    """``fact_ratios`` rows from long-format ``fact_financials`` rows (any number of companies)."""
    rows = []
    for ticker, g in fin.groupby("ticker", sort=True):
        by_year = {
            fy: dict(zip(gy["concept"], gy["value"], strict=True))
            for fy, gy in g.groupby("fiscal_year_label")
        }
        period_end = g.groupby("fiscal_year_label")["period_end"].first()
        for fy in sorted(by_year):
            y = _Year(by_year[fy], by_year.get(str(int(fy) - 1)))
            for name, formula in FORMULAS.items():
                try:
                    value, status, reason = float(formula(y)), "ok", None
                except (_Missing, _NotMeaningful) as e:
                    value = None
                    status = "n/a" if isinstance(e, _Missing) else "n/m"
                    reason = e.reason
                rows.append((ticker, fy, period_end[fy], name, value, status, reason))
    return pd.DataFrame(rows, columns=RATIO_COLUMNS)
