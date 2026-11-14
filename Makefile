PYTHON ?= python3.13
PY ?= .venv/bin/python

.PHONY: install test lint ingest build app readme figures

install:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

ingest:
	$(PY) -m secanalyst.pipeline ingest

build:
	$(PY) -m secanalyst.pipeline build
	$(PY) -m secanalyst.pipeline index
	$(PY) -m secanalyst.pipeline diligence
	$(PY) -m secanalyst.pipeline eval

app:
	$(PY) -m streamlit run app/Home.py

readme:
	$(PY) -m scripts.readme_results

figures:
	$(PY) -m scripts.readme_figures
