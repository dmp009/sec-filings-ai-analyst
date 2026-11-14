import io
import re

import pytest
from pypdf import PdfReader

from secanalyst.config import load_settings
from secanalyst.outputs.brief import brief_content, brief_pdf
from secanalyst.retrieval.search import Index
from secanalyst.warehouse.snapshot import SNAPSHOT_DIR, load_snapshot

CITE = re.compile(r"^[A-Z]+ · 10-K FY\d{4}( \(period end \d{4}-\d{2}-\d{2}\))? · Item \w+$")


@pytest.fixture(scope="module")
def data():
    return load_snapshot(), Index.load(SNAPSHOT_DIR, with_vectors=False)


@pytest.mark.parametrize(
    "ticker", ["AAPL", "NVDA", "AVGO", "MSFT", "AMZN", "META", "GOOGL", "TSLA"]
)
def test_single_a4_page_with_disclaimer(data, ticker):
    con, index = data
    pdf = brief_pdf(ticker, con, index)
    r = PdfReader(io.BytesIO(pdf))
    assert len(r.pages) == 1
    w, h = (float(x) for x in r.pages[0].mediabox[2:])
    assert abs(w - 595.3) < 2 and abs(h - 841.9) < 2  # A4 in points
    text = " ".join(r.pages[0].extract_text().split())
    assert load_settings().disclaimer in text
    assert ticker in text and "as of" in text.lower()


def test_every_risk_line_has_a_citation(data):
    con, index = data
    c = brief_content("NVDA", con, index)
    assert 1 <= len(c.risks) <= 5
    for line, cite in c.risks:
        assert line and CITE.match(cite), cite
    text = " ".join(PdfReader(io.BytesIO(brief_pdf("NVDA", con, index))).pages[0]
                   .extract_text().split())  # fmt: skip
    for _, cite in c.risks:
        assert cite.split(" (")[0] in text


def test_metrics_compare_with_peer_median(data):
    con, index = data
    c = brief_content("AAPL", con, index)
    assert c.metrics and all(len(m) == 3 for m in c.metrics)  # label, company, peer median


def test_unknown_ticker_raises(data):
    con, index = data
    with pytest.raises(ValueError):
        brief_pdf("ZZZZ", con, index)


from secanalyst.outputs.brief import _best_sentence, _fmt, _title_ok

_KW = re.compile(r"(?i)export control|cyber|customer|litigation|legal")


def _best(text, pat=_KW, category=""):
    return _best_sentence([{"text": text, "item": "1A"}], pat, category)[0]


def test_best_sentence_rejects_fragments():
    assert _best("and generally fulfill our contractual obligations under export controls and law.") == ""
    assert _best("for such future increases, we may face cyber incidents and other related risks here.") == ""
    assert _best("The market is hit by cyber incidents although it has no closing punctuation at all") == ""


def test_best_sentence_strips_headings():
    caps = "CYBERSECURITY, DATA PRIVACY, AND PLATFORM ABUSE RISKS Cyberattacks could lead to reduced revenue and harm our reputation."
    assert _best(caps).startswith("Cyberattacks could")
    leg = "Legal and Regulatory Compliance Risks The Company is subject to the risks of legal proceedings and investigations."
    assert _best(leg).startswith("The Company is subject")


def test_best_sentence_customer_concentration_skips_distributors():
    d = "For fiscal year 2025, sales to distributors accounted for 48% of our net revenue overall."
    top = "One customer accounted for 32% of our net revenue for fiscal year 2025 as a distributor."
    assert _best(d, category="customer_concentration") == ""
    assert _best(d + " " + top, category="customer_concentration") == top


def test_risk_title_filter():
    assert not _title_ok("Any one of the foregoing factors may adversely affect our operating results.")
    assert not _title_ok("Any of these events could harm us significantly.")
    assert not _title_ok("Short risk title only")
    assert _title_ok("We depend on a small number of customers for most revenue.")


def test_debt_ebitda_two_decimals():
    assert _fmt(1.234, "x") == "1.23x"
