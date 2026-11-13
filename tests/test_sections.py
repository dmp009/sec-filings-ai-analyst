"""Parsing and sectioning: HTML -> text -> Items (design §6.2, §9.2, §9.5)."""

import json
from datetime import date
from pathlib import Path

import pytest

from secanalyst.config import REPO_ROOT
from secanalyst.ingest.edgar import FilingRef
from secanalyst.parse.sections import (
    ITEMS_10K,
    SECTION_COLUMNS,
    fiscal_year_label,
    html_to_text,
    period_end,
    section_rows,
    split_items,
)

FIX = Path(__file__).parent / "fixtures" / "sections"
FILLER = "This paragraph is long enough to look like the body of a real section. " * 6


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def doc(headings: list[str], toc: bool = True, extra_body: str = "") -> str:
    """Synthetic filing: optional TOC table, then each heading followed by body paragraphs."""
    parts = ["<html><body>"]
    if toc:
        rows = "".join(
            f"<tr><td>{h.split(' ', 2)[0]} {h.split(' ', 2)[1]}</td><td>{h}</td><td>{i + 3}</td></tr>"
            for i, h in enumerate(headings)
        )
        parts.append(f"<table>{rows}</table>")
    for h in headings:
        parts.append(f"<div><span>{h}</span></div><div>{FILLER}</div><div>{FILLER}</div>")
    parts.append(extra_body + "</body></html>")
    return "".join(parts)


# ---------------------------------------------------------------- html_to_text


def test_html_to_text_strips_hidden_xbrl_scripts_and_styles():
    html = (
        "<html><head><style>.x{color:red}</style></head><body>"
        '<div style="display:none"><ix:header><ix:hidden>'
        '<ix:nonNumeric name="dei:AmendmentFlag">false</ix:nonNumeric>'
        "</ix:hidden></ix:header></div>"
        "<script>var hidden = 1;</script>"
        "<div><span>First&#160;&#160;paragraph</span> <span>continues.</span></div>"
        "<p>Second paragraph.</p></body></html>"
    )
    assert html_to_text(html) == "First paragraph continues.\nSecond paragraph."


def test_html_to_text_drops_numeric_tables_and_keeps_text_tables():
    numeric = (
        "<table><tr><td>Net sales</td><td>$</td><td>391,035</td><td>383,285</td></tr>"
        "<tr><td>Cost of sales</td><td>$</td><td>(210,352)</td><td>214,137</td></tr></table>"
    )
    text_tbl = "<table><tr><td>•</td><td>Supply chain disruptions may hurt us.</td></tr></table>"
    out = html_to_text(f"<html><body><p>Intro.</p>{numeric}{text_tbl}<p>End.</p></body></html>")
    assert "391,035" not in out and "Net sales" not in out
    assert out.split("\n") == ["Intro.", "• Supply chain disruptions may hurt us.", "End."]


def test_html_to_text_drops_page_artifacts():
    html = (
        "<html><body><p>Body text.</p><p>23</p><p>Table of Contents</p><p>More.</p></body></html>"
    )
    assert html_to_text(html) == "Body text.\nMore."


# ---------------------------------------------------------------- real-shaped fixtures


@pytest.mark.parametrize(
    "name, body_start",
    [
        ("aapl_10k_2026_trim.htm", "The following summarizes factors"),
        ("goog_10k_2025_trim.htm", "Our operations and financial results are subject"),
    ],
)
def test_toc_entries_are_not_taken_as_sections(name, body_start):
    text = html_to_text(fixture(name))
    items = split_items(text, "10-K")
    toc_1a = text.lower().index("item 1a")  # first occurrence is the TOC row
    toc_1b = text.lower().index("item 1b")
    risk = items["1A"]
    assert text.index(risk) > toc_1a  # body occurrence, after the TOC
    assert risk.split("\n")[1].startswith(body_start)
    assert len(risk) > toc_1b - toc_1a  # longer than the TOC entry
    assert set(items) == set(ITEMS_10K)
    assert all(v.strip() for v in items.values())
    assert len(set(items.values())) == len(items)  # no duplicated sections


def test_short_sections_are_kept_without_swallowing_neighbours():
    items = split_items(html_to_text(fixture("aapl_10k_2026_trim.htm")), "10-K")
    assert items["1B"] == "Item 1B. Unresolved Staff Comments\nNone."
    assert items["1C"].startswith("Item 1C. Cybersecurity")


@pytest.mark.parametrize(
    "name, p12_start, p21a_start",
    [
        ("nvda_10q_trim.htm", "Item 2. Management", "Item 1A. Risk Factors\nOther than the risk"),
        ("tsla_10q_trim.htm", "ITEM 2. MANAGEMENT", "ITEM 1A. RISK FACTORS\nOur operations"),
    ],
)
def test_10q_items_are_keyed_by_part(name, p12_start, p21a_start):
    items = split_items(html_to_text(fixture(name)), "10-Q")
    assert set(items) == {"P1-2", "P2-1A"}
    assert items["P1-2"].startswith(p12_start)
    assert items["P2-1A"].startswith(p21a_start)
    assert "Item 2. Unregistered" not in items["P2-1A"]


@pytest.mark.parametrize(
    "name, label, pe",
    [
        ("aapl_10k_2026_trim.htm", "2026", date(2026, 9, 26)),
        ("goog_10k_2025_trim.htm", "2025", date(2025, 12, 31)),
        ("nvda_10q_trim.htm", "2027", date(2026, 7, 26)),  # NVIDIA's FY2027 starts Jan 2026
    ],
)
def test_fiscal_year_label_and_period_end_from_dei(name, label, pe):
    html = fixture(name)
    assert fiscal_year_label(html) == label
    assert period_end(html) == pe


def test_fiscal_year_label_missing_raises():
    with pytest.raises(ValueError):
        fiscal_year_label("<html><body><p>No cover data.</p></body></html>")


# ---------------------------------------------------------------- heading variants


@pytest.mark.parametrize(
    "h1a",
    [
        "ITEM 1A. RISK FACTORS",
        "Item 1A — Risk Factors",
        "Item 1A: Risk Factors",
        "Item 1A.Risk Factors",
        "Item&#160;1A.&#160;&#160;Risk Factors",
    ],
)
def test_heading_variants_detected(h1a):
    heads = ["Item 1. Business", h1a, "Item 7. MD&amp;A", "Item 8. Financial Statements"]
    items = split_items(html_to_text(doc(heads)), "10-K")
    assert set(items) == {"1", "1A", "7", "8"}
    assert items["1A"].lower().startswith("item 1a")
    assert items["1A"].count("This paragraph") == 12  # body, not the TOC row


def test_heading_split_across_tags_and_table_cells():
    html = (
        "<html><body>"
        "<div><span>Item</span><span>&#160;1.</span><span> Business</span></div>"
        f"<div>{FILLER}</div>"
        "<table><tr><td><span>ITEM</span> <b>1A.</b></td><td>RISK FACTORS</td></tr></table>"
        f"<div>{FILLER}</div>"
        "<div><span>Item 7.</span></div><div><span>Management’s Discussion</span></div>"
        f"<div>{FILLER}</div></body></html>"
    )
    items = split_items(html_to_text(html), "10-K")
    assert items["1"].startswith("Item 1. Business")
    assert items["1A"].startswith("ITEM 1A. RISK FACTORS")
    assert items["7"].startswith("Item 7.\nManagement’s Discussion")


def test_toc_with_sub_entries_is_skipped():
    toc = (
        "<table><tr><td>Item 1.</td><td>Business</td><td>3</td></tr>"
        + "".join(f"<tr><td></td><td>Sub-topic {i} of the business</td></tr>" for i in range(12))
        + "<tr><td>Item 1A.</td><td>Risk Factors</td><td>9</td></tr>"
        "<tr><td>Item 7.</td><td>MD&amp;A</td><td>20</td></tr></table>"
    )
    html = doc(["Item 1. Business", "Item 1A. Risk Factors", "Item 7. MD&amp;A"], toc=False)
    html = html.replace("<body>", "<body>" + toc)
    items = split_items(html_to_text(html), "10-K")
    assert "Sub-topic" not in items["1"]
    assert items["1"].count("This paragraph") == 12


def test_missing_item_is_absent_not_empty():
    items = split_items(html_to_text(doc(["Item 1. Business", "Item 7. MD&amp;A"])), "10-K")
    assert "1A" not in items
    assert set(items) == {"1", "7"}
    assert all(items.values())


def test_running_page_headers_do_not_hide_the_body_heading():
    body = (
        "<html><body><div>Item 7. MD&amp;A</div>"
        f"<div>{FILLER}</div><div>Item 8</div><div>Item 8. Financial Statements</div>"
        "<div>Income statement page.</div><div>Item 8</div>"
        f"<div>{FILLER}</div><div>Item 9A. Controls</div><div>{FILLER}</div></body></html>"
    )
    items = split_items(html_to_text(body), "10-K")
    assert items["8"].startswith("Item 8\nItem 8. Financial Statements")
    assert items["8"].count("This paragraph") == 6


# ---------------------------------------------------------------- fact_sections rows


def test_section_rows_match_fact_sections():
    ref = FilingRef(
        "AAPL", "0000320193", "10-K", "0000320193-26-000026", date(2026, 11, 3),
        date(2026, 9, 26), "https://www.sec.gov/x.htm",
    )  # fmt: skip
    df = section_rows(ref, "2026", {"1A": "Item 1A. Risk Factors\nText.", "7": "Item 7. MD&A"})
    assert list(df.columns) == SECTION_COLUMNS
    assert SECTION_COLUMNS == [
        "filing_id", "ticker", "form", "fiscal_year", "item", "title", "text", "n_chars",
    ]  # fmt: skip
    row = df.set_index("item").loc["1A"]
    assert row.filing_id == "0000320193-26-000026" and row.ticker == "AAPL"
    assert row.form == "10-K" and row.fiscal_year == "2026"
    assert row.title == "Risk Factors" and row.n_chars == len("Item 1A. Risk Factors\nText.")
    assert section_rows(ref, "2026", {}).empty


# ---------------------------------------------------------------- real-data acceptance

MANIFEST = REPO_ROOT / "data" / "raw" / "manifest.json"


def _real_filings():
    if not MANIFEST.exists():
        return []
    m = json.loads(MANIFEST.read_text())
    return [f for c in m["companies"].values() for f in c["filings"]]


@pytest.mark.realdata
@pytest.mark.skipif(not MANIFEST.exists(), reason="data/raw not downloaded")
def test_every_downloaded_filing_sections_cleanly(capsys):
    failures, table = [], []
    for f in _real_filings():
        html = (REPO_ROOT / f["path"]).read_bytes()
        text = html_to_text(html)
        items = split_items(text, f["form"])
        label, pe = fiscal_year_label(html), period_end(html)
        name = f"{f['ticker']} {f['form']} {f['accession']}"
        table.append((name, label, pe, len(text), {k: len(v) for k, v in items.items()}))
        if pe.isoformat() != f["period_end"]:
            failures.append(f"{name}: period_end {pe} != manifest {f['period_end']}")
        if not abs(int(label) - pe.year) <= 1:
            failures.append(f"{name}: label {label} inconsistent with period end {pe}")
        if any(not v.strip() for v in items.values()) or len(set(items.values())) < len(items):
            failures.append(f"{name}: empty or duplicated section")
        if any(len(v) > 0.6 * len(text) for v in items.values()):
            failures.append(f"{name}: an item exceeds 60% of the document")
        if f["form"] == "10-K":
            if len(items.get("1A", "")) <= 20_000:
                failures.append(f"{name}: Item 1A too short ({len(items.get('1A', ''))})")
            if len(items.get("7", "")) <= 10_000:
                failures.append(f"{name}: Item 7 too short ({len(items.get('7', ''))})")
        elif "P1-2" not in items:
            failures.append(f"{name}: Part I Item 2 missing")
    with capsys.disabled():
        for name, label, pe, n, lens in table:
            print(f"\n{name} FY{label} {pe} doc={n} {lens}", end="")
        print()
    assert len(table) == len(_real_filings()) > 0
    assert not failures, "\n".join(failures)
