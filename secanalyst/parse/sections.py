"""SEC 10-K / 10-Q HTML -> clean text -> Items.

Text rules (design §6.2):
- Dropped: the hidden inline-XBRL header (``ix:header``), any ``display:none`` block, scripts,
  styles, head/title and comments.
- Block elements (div, p, tr, li, headings, br, hr) end a line, so paragraph breaks survive;
  inline elements (span, a, font, ix:*) are concatenated as written.
- Tables: a table whose non-empty cells are mostly numbers (financial statements, segment
  tables) is dropped. Any other table is kept as text, one line per row, cells joined by a
  space (bullet lists, headings and the table of contents are often laid out as tables).
- Whitespace (incl. non-breaking spaces) is collapsed inside a line; blank lines and page
  artifacts (a line that is only a page number, "Table of Contents", or a running header naming
  several items such as "Item 1B, 1C") are dropped.
- Running page headers/footers: page breaks (``<hr>`` or ``page-break-*`` styles) are marked.
  A short line (< ``RUNNING_MAX_LEN`` chars) that, after digit normalisation, sits within
  ``RUNNING_WINDOW`` lines of a page break at least ``RUNNING_MIN_REPEAT`` times and next to
  at least ``RUNNING_MIN_SHARE`` of the page breaks is a running
  header/footer ("Apple Inc. | 2026 Form 10-K | 19", "PART I" / "Item 1A",
  "Table of Contents Alphabet Inc.") and is removed wherever it sits next to a page break.
  Repeated subheadings inside the body ("Overview", "Automotive") are kept. A paragraph split
  by a page break is re-joined when the first part does not end in sentence punctuation and
  the second starts in lower case. A lone bullet line is joined to the line it marks.

Item detection: a heading is a line starting with "Item <n><letter>" (any case, followed by
'.', ':', '-', an em/en dash, a space or nothing; split tags and table cells are joined first).
A "PART I/II" line sets the part (10-Q keys ``P1-2`` = MD&A, ``P2-1A`` = Risk Factors).
An occurrence is TOC-like when it ends in a page number or the next heading of a *different*
item follows within ``TOC_GAP`` chars (running page headers repeating the same item do not
count). Items are taken in canonical order: the first non-TOC occurrence after the previous
item's start, else the first occurrence there (a genuinely short section such as "Item 1B.
Unresolved Staff Comments - None."). A start still followed by a cluster of TOC entries
(a TOC row with sub-entries) is moved past it. A section runs from its heading to the next
item heading. A missing item is absent from the result, never an empty string; an item
found out of canonical order is treated as missing.
A heading line is at most ``HEADING_MAX_LEN`` chars, so a body paragraph starting with
"Item 7 of this report ..." is not taken as a heading (a *short* such line still would be).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import NamedTuple

import lxml.html
import pandas as pd

from secanalyst.ingest.edgar import FilingRef

ITEMS_10K = ["1", "1A", "1B", "1C", "2", "3", "7", "7A", "8", "9A"]
ITEMS_10Q = ["P1-2", "P2-1A"]
ITEM_TITLES = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "7": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9A": "Controls and Procedures",
    "P1-2": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "P2-1A": "Risk Factors",
}
SECTION_COLUMNS = [
    "filing_id",
    "ticker",
    "form",
    "fiscal_year",
    "item",
    "title",
    "text",
    "n_chars",
]
HEADING_MAX_LEN = 200  # longer lines starting with "Item N" are body text, not headings
RUNNING_MAX_LEN = 80
RUNNING_WINDOW = 3  # content lines on each side of a page break inspected for headers/footers
RUNNING_MIN_REPEAT = 3
RUNNING_MIN_SHARE = 0.10  # ... and next to at least 10 % of the page breaks
_PAGE = "\x00"  # page-break marker inside the raw text (removed before returning)
_BULLET = re.compile(r"^[•●◦▪■o\-–]$")
# running header naming several items ("Item 1B, 1C", "PART II, III Item 9B, 9C, 10"): never
# a real heading
_MULTI_ITEM = re.compile(
    r"^(part [ivx]+(, ?[ivx]+)* )?item \d+[a-c]?(, ?\d+[a-c]?)+$", re.IGNORECASE
)
_SHORT_ANSWER = re.compile(r"^(none|not applicable)\.?$")  # whole content of a short item
_SENTENCE_END = re.compile(r"[.!?:;”\")]$")
TOC_GAP = 250  # chars between consecutive headings below which a heading is a TOC entry
NUMERIC_TABLE_SHARE = 0.4  # share of numeric cells above which a table is dropped

_BLOCK = {
    "div", "p", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "br", "hr", "center", "blockquote", "section", "article", "body", "dt", "dd", "pre",
}  # fmt: skip
_SKIP = {"script", "style", "head", "title", "ix:header", "noscript"}
_HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)
# numbers, or dash/blank placeholders for zero ("—") in financial tables
_NUMERIC_CELL = re.compile(r"^[\s$€£%()\-—–.,*0-9]*[\d—–-][\s$€£%()\-—–.,*0-9]*$")
# a line that is only a page number or the "Table of Contents" back-link
_PAGE_ARTIFACT = re.compile(r"^(\d{1,3}\.?|table of contents)$", re.IGNORECASE)
_WS = re.compile(r"[ \t\r\f\v\u00a0\u2002\u2003\u2009\u200b]+")

_ITEM_HEAD = re.compile(
    r"^item\s*(\d{1,2})\s*([a-c](?![a-z]))?\s*(?:[.:\-–—]|\s|$)\s*(.*)$", re.IGNORECASE
)
_PART_HEAD = re.compile(r"^part\s+(i{1,3}|iv|[1-4])\b\s*[.:\-–—]?\s*(.*)$", re.IGNORECASE)
_PAGE_TAIL = re.compile(r"\s(\d{1,3}|[ivx]{1,5})\s*$", re.IGNORECASE)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


# ---------------------------------------------------------------- HTML -> text


def _tag(el) -> str:
    return el.tag.lower() if isinstance(el.tag, str) else ""


def _is_hidden(el) -> bool:
    return bool(_HIDDEN.search(el.get("style") or ""))


def _table_lines(table) -> list[str] | None:
    """Text lines of a table, or None when it is a numeric table (dropped)."""
    rows, cells_total, cells_num = [], 0, 0
    for tr in table.iter("tr"):
        if next(tr.iterancestors("table"), None) is not table:
            continue  # row of a nested table: its text is already in the outer cell
        cells = []
        for td in tr:
            if _tag(td) not in ("td", "th") or _is_hidden(td):
                continue
            txt = _clean_line(_inline_text(td))
            if txt:
                cells.append(txt)
                cells_total += 1
                cells_num += bool(_NUMERIC_CELL.match(txt))
        if cells:
            rows.append(" ".join(cells))
    if cells_total and cells_num / cells_total >= NUMERIC_TABLE_SHARE:
        return None
    return rows


def _inline_text(el) -> str:
    """All visible text under an element, block boundaries turned into spaces."""
    parts: list[str] = []
    _walk(el, parts, inline=True)
    return "".join(parts)


def _walk(el, out: list[str], inline: bool = False) -> None:
    tag = _tag(el)
    if tag in _SKIP or _is_hidden(el):
        return
    sep = " " if inline else "\n"
    if tag == "table" and not inline:
        lines = _table_lines(el)
        if lines:
            out.append("\n" + "\n".join(lines) + "\n")
        return
    style = (el.get("style") or "").replace(" ", "").lower()
    if not inline and "page-break-before:always" in style:
        out.append(f"\n{_PAGE}\n")
    block = tag in _BLOCK
    if block:
        out.append(sep)
    if el.text and tag:
        out.append(el.text)
    for child in el:
        if isinstance(child.tag, str):
            _walk(child, out, inline)
        if child.tail:
            out.append(child.tail)
    if block:
        out.append(sep)
    if not inline and (tag == "hr" or "page-break-after:always" in style):
        out.append(f"\n{_PAGE}\n")


def _clean_line(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def parse_html(html: str | bytes):
    """Parse once; the returned root can be passed to html_to_text, fiscal_year_label and
    period_end instead of the raw HTML."""
    if not isinstance(html, (str, bytes)):
        return html  # already parsed
    text = _decode(html) if isinstance(html, bytes) else html
    # lxml refuses str input that carries an XML encoding declaration
    return lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text))


def _norm(line: str) -> str:
    return re.sub(r"\d+", "#", line.lower())


def _strip_running(lines: list[str]) -> list[str]:
    """Drop running headers/footers next to page breaks; re-join split paragraphs."""
    near: list[int] = []  # indexes of content lines within RUNNING_WINDOW of a page break
    for i, line in enumerate(lines):
        if line != _PAGE:
            continue
        for step in (-1, 1):
            j, seen = i + step, 0
            while 0 <= j < len(lines) and lines[j] != _PAGE and seen < RUNNING_WINDOW:
                near.append(j)
                j, seen = j + step, seen + 1
    near_set = set(near)
    counts: dict[str, int] = {}
    for j in near_set:
        if len(lines[j]) < RUNNING_MAX_LEN:
            counts[_norm(lines[j])] = counts.get(_norm(lines[j]), 0) + 1
    n_breaks = lines.count(_PAGE)
    min_repeat = max(RUNNING_MIN_REPEAT, RUNNING_MIN_SHARE * n_breaks)
    running = {k for k, n in counts.items() if n >= min_repeat and not _SHORT_ANSWER.match(k)}
    kept = [
        x for j, x in enumerate(lines)
        if not (j in near_set and len(x) < RUNNING_MAX_LEN and _norm(x) in running)
    ]  # fmt: skip
    out: list[str] = []
    joinable = False  # a page break was crossed since the last content line
    for x in kept:
        if x == _PAGE:
            joinable = True
            continue
        split_paragraph = joinable and not _SENTENCE_END.search(out[-1] if out else ".")
        if out and ((split_paragraph and x[:1].islower()) or _BULLET.match(out[-1])):
            out[-1] = f"{out[-1]} {x}"
        else:
            out.append(x)
        joinable = False
    return out


def html_to_text(html) -> str:
    """Visible text of a filing, one paragraph / table row per line. ``html`` may be the raw
    HTML (str/bytes) or a root returned by :func:`parse_html`."""
    parts: list[str] = []
    _walk(parse_html(html), parts)
    lines = (_clean_line(x) if x != _PAGE else x for x in "".join(parts).split("\n"))
    lines = [x for x in lines if x and not (_PAGE_ARTIFACT.match(x) or _MULTI_ITEM.match(x))]
    return "\n".join(_strip_running(lines))


# ---------------------------------------------------------------- cover data (dei)


def _dei(html, name: str) -> str | None:
    root = parse_html(html)
    for el in root.iter("ix:nonnumeric"):
        if (el.get("name") or "").lower() == name.lower():
            return _clean_line(el.text_content())
    return None


def fiscal_year_label(html) -> str:
    """dei:DocumentFiscalYearFocus of the filing (the company's own label), e.g. '2026'."""
    val = _dei(html, "dei:DocumentFiscalYearFocus")
    if not val or not re.fullmatch(r"\d{4}", val):
        raise ValueError(f"no usable dei:DocumentFiscalYearFocus ({val!r})")
    return val


_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d %B %Y", "%B %d %Y")


def period_end(html) -> date:
    """dei:DocumentPeriodEndDate of the filing."""
    val = _dei(html, "dei:DocumentPeriodEndDate")
    if val:
        s = re.sub(r"\s*,\s*", ", ", val.replace(".", "")).strip()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"no usable dei:DocumentPeriodEndDate ({val!r})")


def expected_fiscal_year(period_end: date, fy_end_month: int) -> int:
    """Fiscal year (named after the calendar year in which it ends) that contains
    ``period_end``. A 52/53-week year may end up to a week into the next month (Broadcom:
    FY2024 ended 3 Nov 2024 with fy_end_month 10), which still counts as the fiscal year end."""
    m, y = period_end.month, period_end.year
    if period_end.day <= 7 and m == fy_end_month % 12 + 1:
        m, y = fy_end_month, y - (fy_end_month == 12)
    return y if m <= fy_end_month else y + 1


# ---------------------------------------------------------------- items


class _Head(NamedTuple):
    off: int  # character offset of the heading line in the text
    key: str  # "1A" (10-K) or "P2-1A" (10-Q)
    toc: bool  # looks like a table-of-contents entry


def _order(key: str) -> tuple[int, int, str]:
    m = re.fullmatch(r"(?:P(\d)-)?(\d{1,2})([A-C]?)", key)
    return (int(m.group(1) or 0), int(m.group(2)), m.group(3))


def _headings(text: str, form: str) -> list[_Head]:
    """Every item heading line, in document order, with its TOC-likeness."""
    is_q = form.upper().startswith("10-Q")
    found: list[tuple[int, str, bool]] = []
    part, pos = 1, 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        pm = _PART_HEAD.match(line)
        if pm:
            p = pm.group(1).lower()
            part = _ROMAN.get(p) or int(p)
            im = _ITEM_HEAD.match(pm.group(2)) if pm.group(2) else None  # "PART I — Item 2."
        else:
            im = _ITEM_HEAD.match(line) if len(line) <= HEADING_MAX_LEN else None
        if im:
            item = im.group(1) + (im.group(2) or "").upper()
            title = im.group(3).strip() or (lines[i + 1] if i + 1 < len(lines) else "")
            page = len(title) < 150 and bool(_PAGE_TAIL.search(title))
            found.append((pos, f"P{part}-{item}" if is_q else item, page))
        pos += len(line) + 1
    out = []
    for j, (off, key, page) in enumerate(found):
        # gap to the next heading of a *different* item: running page headers repeating the
        # same item ("PART II / Item 8" on every page) do not make a heading TOC-like
        nxt = next((h[0] for h in found[j + 1 :] if h[1] != key), len(text))
        out.append(_Head(off, key, page or nxt - off < TOC_GAP))
    return out


def _select(heads: list[_Head]) -> dict[str, int]:
    """Start offset of the body occurrence of each item.

    Forward pass in canonical item order: the first non-TOC occurrence after the previous
    item's start (else the first occurrence there: a genuinely short section). Then, if the
    span up to the next start still contains a cluster (>= 2) of TOC-like headings of other
    items, the start was a TOC entry with sub-entries: move it past that cluster.
    """
    by_key: dict[str, list[_Head]] = {}
    for h in heads:
        by_key.setdefault(h.key, []).append(h)
    chosen: dict[str, int] = {}
    prev = -1
    for key in sorted(by_key, key=_order):
        after = [h for h in by_key[key] if h.off > prev]
        if not after:
            continue  # out of canonical order: treated as missing
        pick = next((h for h in after if not h.toc), after[0])
        chosen[key] = prev = pick.off
    starts = sorted(chosen.values())
    for key, off in list(chosen.items()):
        end = next((s for s in starts if s > off), float("inf"))
        foreign = [h for h in heads if off < h.off < end and h.key != key and h.toc]
        if len(foreign) >= 2:
            later = [h for h in by_key[key] if foreign[-1].off < h.off < end]
            if later:
                chosen[key] = later[0].off
    return chosen


def split_items(text: str, form: str) -> dict[str, str]:
    """{item key: section text}. 10-K keys: 1, 1A, 1B, 1C, 2, 3, 7, 7A, 8, 9A;
    10-Q keys: P1-2 (Part I Item 2, MD&A) and P2-1A (Part II Item 1A, Risk Factors).
    A section runs from its heading to the next item heading; missing items are absent."""
    wanted = ITEMS_10Q if form.upper().startswith("10-Q") else ITEMS_10K
    chosen = _select(_headings(text, form))
    starts = sorted((off, key) for key, off in chosen.items())
    out = {}
    for i, (off, key) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[off:end].strip()
        if key in wanted and body:
            out[key] = body
    return {k: out[k] for k in wanted if k in out}


def section_rows(ref: FilingRef, fiscal_year_label: str, items: dict[str, str]) -> pd.DataFrame:
    """Rows of ``fact_sections``; ``filing_id`` is the accession number, ``title`` the
    standard SEC item name."""
    rows = [
        {
            "filing_id": ref.accession,
            "ticker": ref.ticker,
            "form": ref.form,
            "fiscal_year": fiscal_year_label,
            "item": key,
            "title": ITEM_TITLES.get(key, ""),
            "text": body,
            "n_chars": len(body),
        }
        for key, body in items.items()
    ]
    return pd.DataFrame(rows, columns=SECTION_COLUMNS)
