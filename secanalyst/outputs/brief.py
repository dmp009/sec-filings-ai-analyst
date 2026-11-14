"""One-page client brief (A4 PDF): metrics against the peer median, top risks, what changed in
the latest 10-K and red flags, every risk line with its filing citation."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepInFrame,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from secanalyst.answer.extractive import filing_citation
from secanalyst.config import load_red_flags, load_settings
from secanalyst.diligence.redflags import (
    CATEGORY_LABELS,
    customer_concentration_detail,
    risk_citation,
)
from secanalyst.diligence.redflags import _pattern as _kw_pattern
from secanalyst.warehouse.snapshot import SNAPSHOT_DIR

# (ratio key, label, unit): the seven numbers a client reads first
METRICS = [
    ("revenue_growth", "Revenue growth", "pct"),
    ("gross_margin", "Gross margin", "pct"),
    ("operating_margin", "Operating margin", "pct"),
    ("net_margin", "Net margin", "pct"),
    ("fcf_margin", "FCF margin", "pct"),
    ("roic", "ROIC", "pct"),
    ("debt_to_ebitda", "Debt / EBITDA", "x"),
]
MAX_RISKS = 5
LINE_CHARS = 210


@dataclass
class BriefContent:
    ticker: str
    name: str
    as_of: str
    fy: str  # latest fiscal-year label of the financial metrics
    metrics: list[tuple[str, str, str]] = field(default_factory=list)  # label, company, median
    risks: list[tuple[str, str]] = field(default_factory=list)  # text, citation
    changes: str = ""
    removed_titles: list[tuple[str, str]] = field(default_factory=list)  # title, citation
    red_flags: list[tuple[str, int, str]] = field(default_factory=list)  # label, hits, citation
    concentration: list[tuple[str, str]] = field(default_factory=list)  # text, citation


def _fmt(value, unit: str) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value * 100:.1f}%" if unit == "pct" else f"{value:.2f}x"


def _clip(text: str, n: int = LINE_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3].rsplit(" ", 1)[0] + "..."


def _metrics(con, ticker: str) -> tuple[str, list[tuple[str, str, str]]]:
    df = con.execute("SELECT * FROM fact_ratios").df()
    latest = df.sort_values("period_end").groupby(["ticker", "ratio"]).tail(1)
    ok = latest[latest["status"] == "ok"].dropna(subset=["value"])
    fy = str(latest[latest["ticker"] == ticker]["fiscal_year_label"].max())
    out = []
    for key, label, unit in METRICS:
        r = ok[ok["ratio"] == key]
        mine = r[r["ticker"] == ticker]["value"]
        out.append(
            (
                label,
                _fmt(mine.iloc[0] if len(mine) else None, unit),
                _fmt(r["value"].median() if len(r) else None, unit),
            )
        )
    return fy, out


_SPLIT = re.compile(
    r"(?<=[.!?])(?<!U\.S\.)(?<!U\.K\.)(?<!Inc\.)(?<!Corp\.)(?<!Co\.)(?<!No\.)\s+(?=[A-Z“\"(])"
)
_RISKS_HEADING = re.compile(
    r"^(?:(?:[A-Z][\w,&'/-]*|and|of|the|for|to)\s+){1,8}Risks\s+(?=[A-Z])"
)
_BAD_TITLE = re.compile(r"(?i)\bforegoing\b|^(any|each) (one )?of (the|these)\b")
_ONE_CUSTOMER = re.compile(r"(?i)\b(one|single|a|another)\b[^.]{0,40}\bcustomers?\b")


def _clean_sentence(s: str) -> str:
    """Strip a leading ALL-CAPS heading run (2+ words) or a Title-Case '... Risks' heading."""
    words = s.split()
    n = 0
    while n < len(words) and words[n].isupper() and len(words[n]) > 1 or (
        n < len(words) and n > 0 and words[n] in (",", "&") and words[n - 1].isupper()
    ):
        n += 1
    if n >= 2:
        s = " ".join(words[n:])
    return _RISKS_HEADING.sub("", s.strip(), count=1)


def _title_ok(t: str) -> bool:
    return len(t.split()) >= 5 and not _BAD_TITLE.search(t.strip())


def _best_sentence(rows: list, pat: re.Pattern, category: str = "") -> tuple[str, str]:
    """(sentence, item) of the first complete sentence of 8-40 words that has a keyword;
    the sentence is empty when none qualifies."""
    for r in rows:
        for raw in _SPLIT.split(r["text"]):
            s = _clean_sentence(raw)
            words = s.split()
            caps = sum(w.isupper() and len(w) > 1 for w in words)
            if not (s[:1].isupper() and re.search(r"[.!?][\"”’)]?$", s)):
                continue
            if (
                category == "customer_concentration"
                and re.search(r"(?i)distributors?", s)
                and not _ONE_CUSTOMER.search(s)
            ):
                continue
            if pat.search(s) and 8 <= len(words) <= 40 and caps / len(words) <= 0.6:
                return s, r["item"]
    return "", rows[0]["item"]  # no clean sentence: the caller omits the risk line


def brief_content(ticker: str, con, index, snapshot_dir: Path | str = SNAPSHOT_DIR) -> BriefContent:
    """Gather everything the PDF shows. ``index`` supplies passages (vectors are not used)."""
    row = con.execute("SELECT name FROM dim_company WHERE ticker = ?", [ticker]).fetchone()
    if row is None:
        raise ValueError(f"unknown ticker {ticker!r}")
    meta = con.execute("SELECT value FROM meta WHERE key = 'as_of'").fetchone()
    snapshot_dir = Path(snapshot_dir)
    chunks = index.chunks
    period = chunks[chunks["ticker"] == ticker].groupby("fiscal_year")["period_end"].first()
    c = BriefContent(ticker, row[0], meta[0] if meta else "unknown", "")
    c.fy, c.metrics = _metrics(con, ticker)

    diff = pd.read_parquet(snapshot_dir / "risk_diff.parquet")
    diff = diff[diff["ticker"] == ticker]
    rad = pd.read_parquet(snapshot_dir / "radar.parquet")
    rad = rad[rad["ticker"] == ticker]
    fy_curr = diff["fy_curr"].iloc[0] if len(diff) else None
    if fy_curr is None and len(rad):
        fy_curr = rad["fy"].max()
    cite = risk_citation(ticker, fy_curr, period.get(fy_curr, "")) if fy_curr else ""

    if len(diff):
        n = diff["status"].value_counts()
        same = int(n.get("minor", 0) + n.get("unchanged", 0))
        total = int(n.get("new", 0) + n.get("changed", 0)) + same
        c.changes = (
            f"10-K FY{fy_curr} against FY{diff['fy_prev'].iloc[0]}: {int(n.get('new', 0))} new, "
            f"{int(n.get('removed', 0))} removed and {int(n.get('changed', 0))} reworded risk "
            f"factors out of {total}; {same} carried over ({int(n.get('minor', 0))} with minor edits)."
        )
        new = diff[diff["status"] == "new"]
        prev_cite = risk_citation(
            ticker, diff["fy_prev"].iloc[0], period.get(diff["fy_prev"].iloc[0], "")
        )
        c.removed_titles = [
            (_clip(t, 150), prev_cite)
            for t in diff[diff["status"] == "removed"]["prev_title"].head(2)
        ]
        # risks: new ones first, then the most heavily reworded
        pool = list(new["curr_title"]) + list(
            diff[diff["status"] == "changed"].sort_values("similarity")["curr_title"]
        )
        pool = [t for t in pool if _title_ok(t)]
        for t in pool[:3]:
            c.risks.append((_clip(t), cite))
    else:
        c.changes = "Fewer than two 10-Ks with a risk-factor section: no comparison."

    # red flags from the radar (latest 10-K), strongest first
    if len(rad):
        cur = rad[rad["fy"] == rad["fy"].max()].sort_values("hits", ascending=False)
        by_id = chunks.set_index("chunk_id")
        spec = load_red_flags()
        for r in cur.itertuples():
            sent, it = _best_sentence(
                [by_id.loc[i] for i in r.chunk_ids],
                _kw_pattern(spec[r.category]["keywords"]),
                r.category,
            )
            cit = filing_citation(ticker, "10-K", r.fy, it, period.get(r.fy, ""))
            c.red_flags.append((CATEGORY_LABELS[r.category], int(r.hits), cit))
            if sent and len(c.risks) < MAX_RISKS:
                c.risks.append((f"{CATEGORY_LABELS[r.category]}: {_clip(sent, 170)}", cit))
    conc = [r for r in customer_concentration_detail(chunks) if r[0] == ticker]
    if conc:
        latest = max(r[1] for r in conc)  # filing fiscal year, not the XBRL label
        for _, _, _, cit, sent in [r for r in conc if r[1] == latest][:3]:
            c.concentration.append(
                (f"Customer concentration (FY{latest}): " + _clip(sent, 190), cit)
            )
    c.risks = c.risks[:MAX_RISKS]
    return c


def _p(text: str) -> str:
    """Escape for reportlab Paragraph and keep to the WinAnsi (cp1252) range of the built-in fonts."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.encode("cp1252", "replace").decode("cp1252")


def brief_pdf(ticker: str, con, index, snapshot_dir: Path | str = SNAPSHOT_DIR) -> bytes:
    """Render the brief as a one-page A4 PDF (content is shrunk to fit if it would overflow)."""
    c = brief_content(ticker, con, index, snapshot_dir)
    disclaimer = load_settings().disclaimer
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=18)
    h2 = ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=9.5, leading=12, spaceBefore=6, spaceAfter=2,
        textColor=colors.HexColor("#1f3a5f"),
    )  # fmt: skip
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=8.2, leading=10.4)
    small = ParagraphStyle(
        "s", parent=body, fontSize=7, leading=8.8, textColor=colors.HexColor("#555555")
    )
    item = ParagraphStyle("i", parent=body, leftIndent=8, bulletIndent=0, spaceAfter=2)

    flow = [
        Paragraph(_p(f"{c.name} ({c.ticker}): client brief"), h1),
        Paragraph(_p(f"Data as of {c.as_of}. Financial metrics are for fiscal year {c.fy}."), small),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#1f3a5f"), spaceBefore=3),
        Paragraph("Key metrics against the peer median (eight companies, latest fiscal year)", h2),
    ]  # fmt: skip
    rows = [["Metric", c.ticker, "Peer median (incl. this company)"]] + [list(m) for m in c.metrics]
    t = Table(rows, colWidths=[60 * mm, 25 * mm, 55 * mm], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f9")]),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    flow.append(t)

    flow.append(Paragraph("Top risks (from the risk-factor changes and the red-flag radar)", h2))
    for text, cit in c.risks or [("No risk items available.", "")]:
        cite_html = f' <font size="6.8" color="#555555">[{_p(cit)}]</font>' if cit else ""
        flow.append(Paragraph(_p(text) + cite_html, item, bulletText="-"))

    flow.append(Paragraph("What changed in the latest 10-K", h2))
    flow.append(Paragraph(_p(c.changes), body))
    for title, cit in c.removed_titles:
        flow.append(
            Paragraph(
                "No longer listed: "
                + _p(title)
                + f' <font size="6.8" color="#555555">[{_p(cit)}]</font>',
                item,
                bulletText="-",
            )
        )

    flow.append(Paragraph("Red flags", h2))
    if c.red_flags:
        for label, hits, cit in c.red_flags:
            flow.append(
                Paragraph(
                    f"{_p(label)}: {hits} passage(s) "
                    f'<font size="6.8" color="#555555">[{_p(cit)}]</font>',
                    item,
                    bulletText="-",
                )
            )
    else:
        flow.append(Paragraph("No red-flag keywords matched.", body))
    for text, cit in c.concentration:
        flow.append(
            Paragraph(
                _p(text) + f' <font size="6.8" color="#555555">[{_p(cit)}]</font>',
                item,
                bulletText="-",
            )
        )
    flow += [
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=0.4, color=colors.grey),
        Paragraph(_p(disclaimer), small),
        Paragraph(
            "Generated from SEC EDGAR 10-K text and XBRL data. Passages are filing text; red "
            "flags are keyword matches, a pointer for reading, not a conclusion.",
            small,
        ),
    ]

    buf = io.BytesIO()
    frame_w, frame_h = A4[0] - 30 * mm, A4[1] - 28 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
        bottomMargin=14 * mm, title=f"{c.ticker} client brief", author="SEC filings analyst",
    )  # fmt: skip
    doc.build([KeepInFrame(frame_w, frame_h, flow, mode="shrink")])
    return buf.getvalue()
