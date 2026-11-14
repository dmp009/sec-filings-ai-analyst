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
