PY ?= .venv/bin/python

.PHONY: install test lint pipeline app readme

install:
	python3.13 -m venv .venv
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

pipeline:
	$(PY) -m secanalyst.pipeline ingest

app:
	$(PY) -m streamlit run app/Home.py

readme:
	$(PY) -m secanalyst.readme
