"""SEC company-facts XBRL -> annual values per fiscal year (design §6.3, §9.2, §9.4).

Rules:
- Only facts from form ``10-K`` in USD (``as_of``, when given, drops facts filed after it).
- Flow concepts (income statement, cash flow) use duration facts of 350–380 days ending at the
  fiscal period end; balance concepts use instant facts dated at the period end.
- Fiscal years: the period ends of the given 10-K filings (label = the filing's own
  ``fiscal_year_label``) plus ``n_years - len(filings)`` earlier years, each one year before the
  previous one, matched to the nearest annual period end reported in the facts within
  ``MATCH_DAYS`` days (52/53-week years drift by a few days). Label = previous label - 1.
- Same tag, same period reported by several filings (prior-year comparatives, restatements):
  the latest ``filed`` wins and its accession number is kept.
- Tag fallback is resolved **per year**: the first tag in the configured order that has a value
  for that year (a company that switches tags across years keeps all its years).

Derived concepts (§9.4), with the path recorded in ``tag``:
- ``debt_noncurrent``: when it falls back to ``LongTermDebt`` (by definition a total including
  current maturities) and ``LongTermDebtCurrent`` is reported, the value is ``LongTermDebt -
  LongTermDebtCurrent`` (tag ``LongTermDebt-LongTermDebtCurrent``). ``LongTermDebt`` paired with
  ``DebtCurrent`` is left as is: Tesla reports its *non-current* debt under ``LongTermDebt``
  (current + LongTermDebt = principal outstanding).
- ``total_debt`` = sum of the reported components short-term borrowings + commercial paper +
  current debt + non-current debt + finance-lease liabilities (tag ``sum:A+B+...``). When the
  current debt is ``DebtCurrent`` (which already includes short-term borrowings and commercial
  paper) those two are not added again; when the non-current debt is
  ``LongTermDebtAndCapitalLeaseObligations`` (finance leases included) the non-current finance
  lease is not added again. The lumped ``total_debt`` tags are used only when no component is
  reported for the year (tag ``fallback:<Tag>``).
- ``liquidity`` = cash and equivalents + short-term investments + long-term marketable
  securities; a missing component counts as 0 when cash is present. When neither short- nor
  long-term securities are tagged, ``marketable_securities_total`` (all available-for-sale debt
  securities; NVIDIA FY2026) is added instead. Without cash, the lumped
  ``cash_short_term_investments`` tag is used (``fallback:<Tag>``), otherwise no row.
- ``depreciation_amortization``: when no combined tag is reported, depreciation + amortization
  of intangibles (missing amortization = 0; tag ``sum:Depreciation+...``).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

FINANCIAL_COLUMNS = [
    "ticker",
    "fiscal_year_label",
    "period_end",
    "concept",
    "value",
    "tag",
    "accession",
]
BALANCE_CONCEPTS = {
    "total_assets", "total_equity", "total_debt", "cash_short_term_investments", "receivables",
    "inventory", "payables", "short_term_borrowings", "commercial_paper", "debt_current",
    "debt_noncurrent", "finance_lease_liability_current", "finance_lease_liability_noncurrent",
    "cash_and_equivalents", "short_term_investments", "marketable_securities_noncurrent",
    "marketable_securities_total",
}  # fmt: skip
DEBT_COMPONENTS = [
    "short_term_borrowings",
    "commercial_paper",
    "debt_current",
    "debt_noncurrent",
    "finance_lease_liability_current",
    "finance_lease_liability_noncurrent",
]
LIQUIDITY_COMPONENTS = [
    "cash_and_equivalents",
    "short_term_investments",
    "marketable_securities_noncurrent",
]
FLOW_DAYS = (350, 380)
MATCH_DAYS = 7
N_YEARS = 5

# (concept, value, tag, accession, filed)
_Hit = tuple[str, float, str, str, str]


def _usd(facts_json: dict, tag: str) -> list[dict]:
    for ns in ("us-gaap", "ifrs-full"):
        node = facts_json.get("facts", {}).get(ns, {}).get(tag)
        if node:
            return node.get("units", {}).get("USD", [])
    return []


def _annual(facts: list[dict], flow: bool, as_of: date | None) -> dict[date, dict]:
    """{period end: latest-filed 10-K fact} for annual durations (flow) or instants."""
    best: dict[date, dict] = {}
    for f in facts:
        if f.get("form") != "10-K" or (as_of and f.get("filed", "") > as_of.isoformat()):
            continue
        end = date.fromisoformat(f["end"])
        if flow:
            if "start" not in f:
                continue
            days = (end - date.fromisoformat(f["start"])).days
            if not FLOW_DAYS[0] <= days <= FLOW_DAYS[1]:
                continue
        elif "start" in f:
            continue
        cur = best.get(end)
        if cur is None or f.get("filed", "") >= cur.get("filed", ""):
            best[end] = f
    return best


def _one_year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year - 1, day=28)


def _nearest(target: date, candidates: set[date]) -> date | None:
    near = [c for c in candidates if abs((c - target).days) <= MATCH_DAYS]
    return min(near, key=lambda c: (abs((c - target).days), c)) if near else None


def _years(filings: pd.DataFrame, candidates: set[date], n_years: int) -> list[tuple[str, date]]:
    """[(fiscal_year_label, period end used to match facts)], latest first."""
    tenk = filings[filings["form"] == "10-K"].sort_values("period_end", ascending=False)
    years: list[tuple[str, date]] = []
    for r in tenk.itertuples():
        pe = pd.Timestamp(r.period_end).date()
        years.append((str(r.fiscal_year_label), _nearest(pe, candidates) or pe))
    while years and len(years) < n_years:
        label, pe = years[-1]
        target = _one_year_before(pe)
        years.append((str(int(label) - 1), _nearest(target, candidates) or target))
    return years


def extract_annual(
    facts_json: dict,
    tags: dict[str, list[str]],
    filings: pd.DataFrame,
    as_of: date | None = None,
    n_years: int = N_YEARS,
) -> pd.DataFrame:
    """Annual values in ``fact_financials`` shape for one company.

    ``filings``: that company's rows of ``fact_filings`` (only 10-K rows are used; columns
    ticker, form, period_end, fiscal_year_label). ``tags``: concept -> ordered XBRL tags.
    """
    if filings.empty:
        return pd.DataFrame(columns=FINANCIAL_COLUMNS)
    ticker = str(filings["ticker"].iloc[0])
    by_tag: dict[tuple[str, str], dict[date, dict]] = {}
    for concept, tag_list in tags.items():
        flow = concept not in BALANCE_CONCEPTS
        for tag in tag_list:
            by_tag[(concept, tag)] = _annual(_usd(facts_json, tag), flow, as_of)
    flow_ends = {
        d for (c, _), v in by_tag.items() if c not in BALANCE_CONCEPTS for d in v
    }  # annual duration ends are the fiscal year ends
    rows = []
    for label, pe in _years(filings, flow_ends, n_years):
        hits: dict[str, _Hit] = {}
        for concept, tag_list in tags.items():
            for tag in tag_list:
                f = by_tag[(concept, tag)].get(pe)
                if f is not None:
                    hits[concept] = (concept, float(f["val"]), tag, f["accn"], f.get("filed", ""))
                    break
        _derive(hits)
        for concept, value, tag, accn, _ in hits.values():
            rows.append((ticker, label, pe, concept, value, tag, accn))
    df = pd.DataFrame(rows, columns=FINANCIAL_COLUMNS)
    return df.sort_values(["fiscal_year_label", "concept"], ascending=[False, True]).reset_index(
        drop=True
    )


def _accessions(parts: list[_Hit]) -> str:
    return ",".join(sorted({p[3] for p in parts}))


def _sum(concept: str, parts: list[_Hit]) -> _Hit:
    return (
        concept,
        sum(p[1] for p in parts),
        "sum:" + "+".join(p[2] for p in parts),
        _accessions(parts),
        max(p[4] for p in parts),
    )


def _derive(h: dict[str, _Hit]) -> None:
    """Add/replace the derived concepts in place (see module docstring)."""
    # non-current debt from a LongTermDebt total
    nc, cur = h.get("debt_noncurrent"), h.get("debt_current")
    lt_total = nc and cur and nc[2] == "LongTermDebt" and cur[2] == "LongTermDebtCurrent"
    if lt_total and nc[1] >= cur[1]:
        h["debt_noncurrent"] = (
            "debt_noncurrent",
            nc[1] - cur[1],
            "LongTermDebt-LongTermDebtCurrent",
            _accessions([nc, cur]),
            max(nc[4], cur[4]),
        )

    # total debt
    skip = set()
    if cur and cur[2] == "DebtCurrent":
        skip |= {"short_term_borrowings", "commercial_paper"}
    if h.get("debt_noncurrent", ("",) * 3)[2] == "LongTermDebtAndCapitalLeaseObligations":
        skip.add("finance_lease_liability_noncurrent")
    parts = [h[c] for c in DEBT_COMPONENTS if c in h and c not in skip]
    if parts:
        h["total_debt"] = _sum("total_debt", parts)
    elif "total_debt" in h:
        c, v, tag, accn, filed = h["total_debt"]
        h["total_debt"] = (c, v, f"fallback:{tag}", accn, filed)

    # liquidity
    if "cash_and_equivalents" in h:
        parts = [h[c] for c in LIQUIDITY_COMPONENTS if c in h]
        if len(parts) == 1 and "marketable_securities_total" in h:
            parts.append(h["marketable_securities_total"])
        h["liquidity"] = _sum("liquidity", parts)
    elif "cash_short_term_investments" in h:
        _, v, tag, accn, filed = h["cash_short_term_investments"]
        h["liquidity"] = ("liquidity", v, f"fallback:{tag}", accn, filed)

    # D&A
    if "depreciation_amortization" not in h and "depreciation" in h:
        parts = [h[c] for c in ("depreciation", "amortization_intangibles") if c in h]
        h["depreciation_amortization"] = _sum("depreciation_amortization", parts)
