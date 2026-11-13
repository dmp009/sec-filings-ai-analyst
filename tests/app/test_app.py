from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
PAGES = ["Home.py", "pages/3_Benchmarking.py", "pages/5_Data_quality.py", "pages/6_About.py"]
DISCLAIMER = "Educational project — not investment advice. Source: SEC EDGAR."


def _run(page):
    return AppTest.from_file(str(ROOT / "app" / page), default_timeout=120).run()


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_with_disclaimer(page):
    at = _run(page)
    assert not at.exception, [e.value for e in at.exception]
    assert any(DISCLAIMER in c.value for c in at.caption)


def test_benchmarking_every_ratio_runs():
    at = _run("pages/3_Benchmarking.py")
    for opt in at.selectbox(key="ratio_select").options:
        at.selectbox(key="ratio_select").select(opt).run()
        assert not at.exception, (opt, [e.value for e in at.exception])
    assert at.dataframe  # table rendered


def test_benchmarking_shows_na_cells():
    at = _run("pages/3_Benchmarking.py")
    at.selectbox(key="ratio_select").select("Inventory days (DIO)").run()
    assert not at.exception
    cells = " ".join(str(v) for d in at.dataframe for v in d.value.to_numpy().ravel())
    assert "n/a" in cells
