# SEC Filings AI Analyst — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an analyst tool over the SEC filings and XBRL data of the 8 largest non-financial S&P 500 companies: cited search, risk-factor diff, red-flag radar, peer benchmarking and a one-page brief, all working without an API key.

**Architecture:** Python package `secanalyst` (ingest → parse → financials → retrieval → answer/diligence → outputs) feeding a DuckDB warehouse exported to a committed parquet snapshot plus a float16 vector matrix; a Streamlit multipage app reads only committed files. An optional LLM layer (cached, verified) is wired but inactive without a key.

**Tech Stack:** Python 3.11+, requests, pandas≥2.2, numpy, duckdb≥1.1, pandera≥0.24, pydantic v2, pyyaml, beautifulsoup4 + lxml, fastembed (ONNX, `BAAI/bge-small-en-v1.5`), rank-bm25, anthropic (optional), reportlab, plotly, streamlit≥1.50, pytest, ruff, GitHub Actions.

**Spec:** `docs/design/2026-11-14-sec-filings-ai-analyst-design.md` (§9 decisions are binding).

## Global Constraints

- Companies (ticker, CIK, FY end month): AAPL 0000320193 9; MSFT 0000789019 6; NVDA 0001045810 1; AMZN 0001018724 12; GOOGL 0001652044 12; META 0001326801 12; AVGO 0001730168 10; TSLA 0001318605 12.
- Filings: last 3 10-K filed on or before `as_of`; latest 10-Q filed after the latest 10-K (else none). XBRL: 5 fiscal years (3 filing years + 2 earlier).
- SEC access: ≤ 8 requests/second; `User-Agent` from env `SEC_USER_AGENT` (default `"sec-filings-ai-analyst research project"`); no real download until the user has chosen the contact.
- No network in tests, CI or app runtime (except the embedding model download on first app start).
- Committed processed data ≤ 60 MB; vectors float16; no Git LFS; embedding model not committed.
- Every answer, highlight, finding and number carries a citation: ticker, form, fiscal-year label, period end, item (or XBRL tag + accession).
- Extractive output labelled "Key sentences from the filings (extractive, not AI-written)"; AI-drafted text labelled as such.
- Financial definitions (§9.4) verbatim: total debt = short-term borrowings + commercial paper + current and long-term debt (+ finance leases when tagged), operating leases excluded; liquidity = cash & equivalents + short-term investments + long-term marketable securities; net cash = liquidity − total debt; NOPAT = operating income × (1 − effective tax rate clamped to [0, 0.35]); invested capital = equity + total debt − liquidity; ROIC/ROE "n/m" when invested capital ≤ 0 or equity ≤ 0.
- Fiscal-year label = filing's `dei:DocumentFiscalYearFocus`, always shown with period end.
- UI and docs in English; README ends with "Résumé en français"; disclaimer on every page and PDF: "Educational project — not investment advice. Source: SEC EDGAR."
- LLM model only in `config/settings.yaml` (default `claude-sonnet-5-5`); LLM used only with `ANTHROPIC_API_KEY`.

## Review Focus

1. **A filing whose Item 1A / 7 cannot be found** (cross-reference, odd headings): flagged by quality checks, excluded from the diff with a visible note — never a crash or an empty "no risks" result. → Tasks 3, 8.
2. **Missing XBRL concept or tag change across years** (e.g. revenue tag switch): fallback tags tried in order; still missing → "n/a" with reason, never 0. → Task 4.
3. **Query with no good match / out-of-scope question** ("What is Apple's share price today?"): app says no relevant passage above the score floor instead of showing weak passages as answers. → Task 7.
4. **Companies with negative or tiny equity / net cash** (Apple ROE, many with net cash): n/m and sign handled, ranks computed only on valid values. → Task 4.
5. **Fiscal-year misalignment** (NVDA FY ends January): benchmark tables show label + period end; peer medians use same fiscal-year label, documented. → Tasks 4, 5.

---

## File structure

```
pyproject.toml, Makefile, .gitignore, requirements.txt, .github/workflows/ci.yml
config/settings.yaml, companies.yaml, red_flags.yaml, questions.yaml, xbrl_tags.yaml
secanalyst/
  config.py
  ingest/edgar.py            # client, rate limit, raw save, filing selection
  parse/sections.py          # HTML → text → items
  financials/facts.py, ratios.py
  warehouse/schema.sql, db.py, quality.py, snapshot.py
  retrieval/chunk.py, embed.py, search.py, evaluate.py
  answer/extractive.py, llm.py, verify.py, prompts/answer_v1.md
  diligence/riskdiff.py, redflags.py
  outputs/brief.py
  pipeline.py                # ingest | build | eval | quality | ai
app/Home.py, app/pages/1_Ask_the_filings.py, 2_Due_diligence.py, 3_Benchmarking.py,
    4_Client_brief.py, 5_Data_quality.py, 6_About.py, app/common.py, app/charts.py
data/snapshot/ (parquet + vectors.npy), data/eval/retrieval_eval.yaml, data/ai_cache/
tests/ (mirrors package; tests/fixtures/ small saved filing extracts + companyfacts JSON)
docs/ business_requirements.md, data_dictionary.md, data_model.md, methodology.md
```

---

### Task 1: Scaffold, config and CI
**Files:** pyproject, Makefile (`install test lint pipeline app readme`), .gitignore (`.venv/ data/raw/ data/*.duckdb .env .superpowers/`), CI (3.11, pip cache, ruff, pytest), `config/*.yaml`, `secanalyst/config.py`. Test `tests/test_config.py`.
**Produces:** `Company(ticker, name, cik: str, fy_end_month: int)`; `Settings(llm_model, as_of: date | None, chunk_words: int=320, chunk_overlap: int=60, top_k: int=8, score_floor: float, daily_llm_cap: int=50, user_agent_default: str, disclaimer: str)`; `load_companies()`, `load_settings()`, `load_red_flags() -> dict[str, {keywords: list[str], seeds: list[str]}]`, `load_questions()`, `load_xbrl_tags() -> dict[concept, list[tag]]`, `REPO_ROOT`.
- [ ] Failing tests: 8 companies with exact tickers/CIKs/FY months from Global Constraints; red-flag categories exactly `customer_concentration, litigation, material_weakness, going_concern, china_geopolitics, ai_regulation, export_controls, cybersecurity`; xbrl_tags has every concept listed in spec §6.3, each with ≥ 1 tag; disclaimer text exact.
- [ ] RED → implement (venv `python3.13 -m venv .venv`; `--only-binary :all:` where builds fail) → GREEN → commit `chore: scaffold package, config and CI`.

### Task 2: EDGAR client and filing selection
**Files:** `secanalyst/ingest/edgar.py`, `secanalyst/pipeline.py` (`ingest`), tests with fixtures `tests/fixtures/submissions_AAPL.json` (trimmed real-shape JSON).
**Produces:** `EdgarClient(user_agent: str, max_rps: float = 8)` with `get_json(url) -> dict`, `get_text(url) -> str` (raw saved to `data/raw/<kind>/<ts>_<name>`); `select_filings(submissions: dict, as_of: date) -> list[FilingRef]`, `FilingRef(ticker, cik, form, accession, filing_date, period_end, primary_doc_url)`; `fetch_company_facts(client, cik) -> dict`.
- [ ] Failing tests: `select_filings` on fixture returns exactly 3 10-K (most recent ≤ as_of) + the latest 10-Q filed after the latest 10-K, none if absent; amended forms (10-K/A) ignored; rate limiter: 20 calls with a fake clock never exceed 8 per second; User-Agent header = env var when set, default otherwise.
- [ ] RED → implement → GREEN → commit `feat(ingest): EDGAR client and filing selection`.
- [ ] Real download is GATED: do not run until the controller confirms the SEC contact.

### Task 3: Parsing and sectioning
**Files:** `secanalyst/parse/sections.py`; fixtures: 2–3 small real-shaped 10-K HTML extracts (incl. a table of contents duplicate and a variant heading style).
**Produces:** `html_to_text(html: str) -> str`; `split_items(text: str, form: str) -> dict[str, str]` (keys `1, 1A, 1B, 1C, 2, 3, 7, 7A, 8, 9A` for 10-K; `P1-2`, `P2-1A` for 10-Q); `section_rows(ref: FilingRef, fiscal_year_label: str, items) -> pd.DataFrame` matching `fact_sections`.
- [ ] Failing tests: TOC entries are not taken as sections (body Item 1A text length > TOC length and starts after the TOC); "ITEM 1A. RISK FACTORS" and "Item 1A — Risk Factors" both detected; missing 1A → key absent (not empty string), caller flags it.
- [ ] RED → implement → GREEN → commit `feat(parse): split filings into items`.

### Task 4: XBRL financials, ratios, warehouse, quality, snapshot
**Files:** `secanalyst/financials/facts.py, ratios.py`, `secanalyst/warehouse/*`; fixture companyfacts JSON (trimmed).
**Produces:** tables `dim_company`, `fact_filings(filing_id, ticker, form, accession, filing_date, period_end, fiscal_year_label)`, `fact_sections(...)`, `fact_financials(ticker, fiscal_year_label, period_end, concept, value, tag, accession)`, `fact_ratios(ticker, fiscal_year_label, period_end, ratio, value, status: Literal['ok','n/a','n/m'], reason)`, `fact_chunks`, `fact_ai_answers`; `extract_annual(facts_json, tags, filings) -> DataFrame` (annual 10-K values matched by period end, duration 350–380 days, dedupe latest filed); `compute_ratios(fin: DataFrame) -> DataFrame`; `run_quality_checks(con) -> list[QualityIssue]`; `export_snapshot(con)`, `load_snapshot() -> duckdb connection`.
- [ ] Failing tests (hand values): revenue 100, cost 40 → gross margin 0.60; OCF 30, capex 10, NI 25 → FCF 20, FCF conversion 0.80; operating income 50, tax 50 on pretax 100 → effective rate clamped 0.35 → NOPAT 32.5; equity 100, debt 50, liquidity 30 → invested capital 120 → ROIC 32.5/120 = 0.270833; equity −5 → ROE and ROIC status `n/m` with reason; AR 20, revenue 100 → DSO 73.0; missing capex → FCF ratios `n/a` with reason "missing concept capex"; revenue tag switch across years resolved by fallback order; quality: 10-K without Item 1A or 7 → error issue naming the filing.
- [ ] RED → implement → GREEN → commit `feat(financials): XBRL extraction, ratios, warehouse and snapshot`.

### Task 5: App skeleton and Benchmarking page (phase 1 publishable)
**Files:** `app/Home.py`, `app/common.py`, `app/pages/3_Benchmarking.py, 5_Data_quality.py, 6_About.py`, `app/charts.py`, `requirements.txt`.
- Benchmarking: ratio selector, 5-year table (label + period end), line chart per company, ranking + peer median for the latest fiscal year (valid values only), tooltips with §9.4 definitions, n/a / n/m shown with reasons.
- [ ] Failing tests: AppTest each page without exception on the committed snapshot (use a small test snapshot fixture until Task 2's real data exists); ranking excludes n/m; charts pure functions return figures.
- [ ] RED → implement → GREEN; headless health check; commit `feat(app): benchmarking, data quality and about pages`.

### Task 6: Retrieval (chunks, embeddings, hybrid search, evaluation)
**Files:** `secanalyst/retrieval/*`, `data/eval/retrieval_eval.yaml`, pipeline `build` and `eval`.
**Produces:** `chunk_sections(sections: DataFrame, words=320, overlap=60) -> DataFrame` (chunk_id = `{ticker}-{form}-{fy}-{item}-{n:04d}`); `Embedder` protocol + `FastEmbedder(model="BAAI/bge-small-en-v1.5")` + `FakeEmbedder` (deterministic hashing, tests); `Index(chunks, vectors: np.ndarray[float16])`; `search(index, query, filters: dict | None, k=8) -> list[Hit(chunk_id, score, ticker, form, fy, item, text)]` = BM25 + cosine merged with RRF `Σ 1/(60 + rank)`; `evaluate(index, eval_set) -> {recall_at_5, mrr, per_question}`.
- [ ] Failing tests (FakeEmbedder): chunk overlap correct and no chunk crosses sections; filters restrict results; RRF ranks a doc first that is #1 in BM25 and #2 in vectors over one that is #3/#1; evaluate computes recall@5 and MRR on a toy set exactly.
- [ ] RED → implement → GREEN.
- [ ] After real data: write ~30 eval questions (ticker, fy, item, key phrase) by reading the filings; run eval; report numbers; vectors committed as float16; total snapshot size ≤ 60 MB (assert in a test).
- [ ] Commit `feat(retrieval): hybrid search with evaluation`.

### Task 7: Extractive answers and Ask the filings page
**Files:** `secanalyst/answer/extractive.py`, `app/pages/1_Ask_the_filings.py`.
**Produces:** `key_sentences(query, hits, embedder, n=5) -> list[Sentence(text, chunk_id, citation, score)]`; `citation(hit) -> str` like `"NVDA · 10-K FY2026 (period end 2026-01-25) · Item 1A"`.
- Page: question box, filters, top passages with citation chips, "Key sentences (extractive, not AI-written)", drafted answer only if cached/key (Task 10), "No relevant passage found" below `score_floor` (Review Focus 3), example questions from `config/questions.yaml`.
- [ ] Failing tests: every key sentence has a citation; out-of-scope query against fixture index returns the no-match message; AppTest with a fixture index.
- [ ] RED → implement → GREEN → commit `feat(answer): extractive answers and ask page`.

### Task 8: Risk-factor diff, red-flag radar, Due diligence page
**Files:** `secanalyst/diligence/riskdiff.py, redflags.py`, `app/pages/2_Due_diligence.py`.
**Produces:** `split_risks(item_1a: str) -> list[Risk(title, text)]`; `diff_risks(prev, curr, embedder, match=0.80, change=0.95) -> list[RiskChange(status: Literal['new','removed','changed','unchanged'], prev, curr, similarity)]`; `radar(chunks, red_flags) -> DataFrame (ticker, fy, category, hits, chunk_ids)`; `customer_concentration(chunks) -> list[(ticker, fy, percent, citation)]`.
- [ ] Failing tests: diff on synthetic risks (identical, reworded, removed, added) gives exactly unchanged/changed/removed/new; thresholds from config; missing 1A → excluded with note (Review Focus 1); radar counts on fixture text; "one customer accounted for 12% of revenue" parsed as 12.0 with citation.
- [ ] RED → implement → GREEN.
- [ ] After real data: tune thresholds on AAPL and NVDA hand-checked pairs; measure radar precision on 40 hand-checked hits (target ≥ 0.80); record both in methodology.
- [ ] Commit `feat(diligence): risk diff, red-flag radar and page`.

### Task 9: Client brief
**Files:** `secanalyst/outputs/brief.py`, `app/pages/4_Client_brief.py`.
**Produces:** `brief_pdf(ticker, con, index) -> bytes` (one A4 page: metrics vs peer median, top 5 risks by radar/diff with citations, what changed in latest 10-K, red flags, as-of, disclaimer).
- [ ] Failing tests: single page; disclaimer present; every risk line contains a citation; AppTest download button.
- [ ] RED → implement → GREEN → commit `feat(outputs): client brief PDF`.

### Task 10: Optional LLM layer
**Files:** `secanalyst/answer/llm.py, verify.py, prompts/answer_v1.md`, pipeline `ai`.
**Produces:** `LLMClient` protocol, `AnthropicClient` (lazy import, key from env, forced tool `write_answer` → `{answer, citations: list[chunk_id]}`, raise on `max_tokens`); `verify_answer(answer, hits) -> list[str]` (citations ⊆ retrieved chunk ids; every number in the answer appears in a cited chunk's text, EN number formats); `answer_cached(question, hits, client=None, refresh=False) -> DraftAnswer | None` (cache key sha256(question + chunk ids + prompt version), only verified cached); app: free-form drafting only if key in `st.secrets`/env and today's counter < `daily_llm_cap`.
- [ ] Failing tests with fake clients: uncited / foreign citation rejected; number not in cited text rejected; one retry then unverified; cache hit; no key → `ai` exits 0 with message; daily cap blocks the 51st call.
- [ ] RED → implement → GREEN → commit `feat(ai): optional verified drafted answers`.

### Task 11: Docs, README, final data run
**Files:** README, `docs/*`, LICENSE (MIT, "Copyright (c) 2026 sec-filings-ai-analyst contributors"), `scripts/readme_results.py` (retrieval metrics, radar precision, one benchmark table between `<!-- RESULTS:START/END -->`).
- README order: badge (`dmp009/sec-filings-ai-analyst`) + "Live demo: coming soon" → business problem (3 personas) → what it shows (no fake screenshots; matplotlib figures allowed) → results (generated) → how it works (Mermaid) → AI without a key (extractive vs drafted, labelling) → data governance (sources, User-Agent, citations, quality) → quickstart → structure → limitations (fiscal-year differences, XBRL tag gaps, author-labelled eval set, keyword radar, no LLM answers until a key) → disclaimer → Résumé en français (~120 words).
- [ ] Write docs; data dictionary covers every column in schema.sql; `make test && make lint`; commit `docs: README and documentation`.
