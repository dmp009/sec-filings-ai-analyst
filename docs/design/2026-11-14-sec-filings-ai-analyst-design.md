# SEC Filings AI Analyst — Design

Date: 2026-11-14 · Status: draft for review · Portfolio project 3 of 6

## 1. Intent and why

**What it is.** An analyst tool that turns the official SEC filings (10-K, 10-Q and XBRL
financial data) of the 8 largest non-financial S&P 500 companies into due-diligence
findings, peer benchmarks and client-ready briefs, with every statement traceable to the
exact filing, year and section.

**Who it is for.** One tool, three users, three views over the same data:
- **M&A / due diligence analyst:** what are the risks, what changed year over year, which
  red flags appear, with citations.
- **FP&A / corporate finance:** how the company compares with its peers on growth,
  margins, cash conversion, returns and working capital over 5 years.
- **Data / business analyst or consultant:** a downloadable one-page brief for a client.

**Why.** Portfolio piece for an M2 internship in France (DAIS track: Data Analyst,
Business Analyst, Data Consultant; finance focus). It must show retrieval-augmented
generation (RAG) and NLP on real documents, financial analysis from structured data,
data governance, and BI deployment. It is the most "AI" project of the portfolio.

**Success looks like.** A recruiter opens the live Streamlit link, types a question about
NVIDIA's customer concentration or Apple's China risk, and gets the exact passages with
citations within seconds; sees which risk factors are new in the latest 10-K; compares
free-cash-flow conversion across the 8 companies; downloads a one-page brief — all without
any API key.

## 2. Goals, non-goals, anti-goals

**Goals**
- Companies (binding): Apple (AAPL), Microsoft (MSFT), NVIDIA (NVDA), Amazon (AMZN),
  Alphabet (GOOGL), Meta (META), Broadcom (AVGO), Tesla (TSLA).
- Filings: the last 3 annual reports (10-K) and the latest quarterly report (10-Q) per
  company; XBRL "company facts" for 5 fiscal years.
- Everything in the public demo works **without an API key** (user decision: no paid
  credits for now).
- Views: **Due diligence**, **Benchmarking**, **Client brief**, **Ask the filings**,
  plus **Data quality** and **About**. UI in English; README with a French summary.
- Same DAIS layer and engineering hygiene as projects 1 and 2.

**Non-goals**
- No financial companies (banks/insurers: different statements; excluded by design).
- No investment recommendation, no price targets, no real-time data.
- No paid LLM calls in the demo; no hosted vector database.

**Anti-goals (failure even if it runs)**
- Any answer, highlight or finding without a citation to filing + year + section.
- Any number shown that is not traceable to XBRL facts or the filing text.
- Text presented as AI-written when it is extractive (and vice versa).
- A demo that looks empty without a key.

## 3. Constraints

- Free data only: SEC EDGAR (`data.sec.gov` submissions and company-facts APIs,
  `www.sec.gov/Archives` filing documents). SEC fair-access rules: max 10 requests/second
  and a descriptive `User-Agent` with contact. The User-Agent is read from the env var
  `SEC_USER_AGENT`; the default is a generic project identifier. **Before the first real
  download the builder asks the user which contact to use** (privacy: never put the
  user's email in requests without their approval).
- Streamlit Community Cloud (≈1 GB RAM, no GPU): the app must load the committed index
  and a small CPU embedding model; no torch-heavy stack if avoidable.
- Runs with no network at app runtime except downloading the embedding model on first
  start (or bundling it — builder's call, documented).
- Python ≥ 3.11; tests and CI make no network calls; committed snapshot of processed data.
- LLM generation (Anthropic, model in config) is optional: off unless `ANTHROPIC_API_KEY`
  is present.

## 4. Approaches considered

| | Approach | Trade-off | Decision |
|---|---|---|---|
| **A** | Local retrieval live in the demo + LLM answers pre-generated for curated questions (cached, committed) | Demo always works, zero running cost; free-form drafted answers only where a key exists | **Chosen by the user** |
| B | Live chat with the user's key stored in Streamlit secrets, daily limit | Most impressive; variable cost; demo breaks if key or budget ends | Rejected for now; kept as an optional switch |
| C | Fully local, no LLM at all | Always free; weak for a generative-AI showcase | Rejected as the whole design, but it is the fallback inside A |

**Consequence of the user's "no credits for now":** the cached drafted answers do not
exist at launch. The demo therefore relies on local NLP features (§6.4–6.6) that need no
LLM, and the drafted-answer layer ships ready but empty, switched on automatically when
a key is present (cache generation + optional live chat with a daily limit).

Same stack as projects 1–2 (designer's call): Python package, DuckDB warehouse, pandera
quality checks, committed parquet snapshot, Streamlit multipage app, reportlab PDF,
pytest + ruff + GitHub Actions.

## 5. The views (what the user sees)

```
Ask the filings                        Due diligence (one company)
───────────────                        ───────────────────────────
Question box + filters (company,       Risk factors: new / removed / changed
year, section)                         in the latest 10-K vs the previous one
→ top passages with citation chips     (side-by-side text, similarity score)
  [NVDA · 10-K FY2026 · Item 1A]       Red-flag radar: categories × years
→ "Key sentences" (extractive,         (customer concentration, litigation,
  labelled as such)                    material weakness, going concern,
→ drafted answer only if cached or     China/geopolitics, AI regulation,
  a key is configured                  export controls, cybersecurity)
                                       with links to the passages

Benchmarking (8 companies)             Client brief
──────────────────────────             ────────────
Ratio table + charts, 5 fiscal years   Pick a company → one-page PDF:
growth, margins, FCF conversion,       key metrics vs peer median, top risks
ROIC, capex intensity, CCC, net cash   (cited), what changed this year,
Rank + peer median, fiscal-year note   red flags, disclaimer
```

## 6. Components

### 6.1 Ingestion (`secanalyst/ingest/`)
- `config/companies.yaml`: ticker, name, CIK, fiscal-year end month.
- Submissions API → list of 10-K/10-Q accession numbers; download the primary HTML
  document for the last 3 10-K and the latest 10-Q. Raw files saved under `data/raw/`
  (gitignored) with timestamps (lineage). Rate limited to ≤ 8 req/s.
- Company-facts API → XBRL facts JSON per company (raw saved).

### 6.2 Parsing and sectioning (`secanalyst/parse/`)
- HTML → clean text; split into Items (1, 1A, 1B, 1C, 2, 3, 7, 7A, 8, 9A for 10-K; Part I
  Item 2 and Part II Item 1A for 10-Q). Handle table of contents duplicates and varied
  heading formats; tables converted to short text or dropped (documented).
- Output: `fact_sections(filing_id, ticker, form, fiscal_year, item, title, text, n_chars)`.
- Quality checks: every 10-K has Items 1A and 7 non-empty; section length within sane
  bounds; no duplicated sections.

### 6.3 Financials from XBRL (`secanalyst/financials/`)
- Tag mapping with fallbacks per concept (e.g. revenue: `Revenues`,
  `RevenueFromContractWithCustomerExcludingAssessedTax`, …), annual (FY, form 10-K) values
  only, 5 fiscal years, deduplicated by fiscal year and period end.
- Concepts: revenue, cost of revenue, gross profit, operating income, net income, D&A,
  operating cash flow, capex, SBC, total assets, total equity, total debt, cash and
  short-term investments, receivables, inventory, payables, income tax, pretax income.
- Ratios: revenue growth, gross / operating / net margin, FCF (= OCF − capex) margin,
  FCF conversion (FCF / net income), capex intensity, ROIC (NOPAT / (debt + equity − cash)),
  ROE, net cash, debt / EBITDA, DSO / DIO / DPO / cash conversion cycle.
- Fiscal years differ (Apple Sept, Microsoft June, NVIDIA Jan): compare by fiscal year label
  and show the period-end date; documented.
- Every value keeps its source tag and accession number (traceability). Missing concept →
  ratio shown as "n/a" with the reason, never imputed.

### 6.4 Retrieval (`secanalyst/retrieval/`)
- Chunking: within each section, ~250–400 words with overlap; chunk id encodes
  ticker/form/year/item/position.
- Embeddings: small CPU model (e.g. `BAAI/bge-small-en-v1.5` via a light ONNX runtime such
  as `fastembed`), vectors stored as a committed matrix + metadata parquet.
- Hybrid search: BM25 + cosine similarity, merged with reciprocal-rank fusion; filters by
  company, year, form, item.
- **Retrieval evaluation:** a labelled set of ~30 questions with the expected
  (ticker, year, item) and a key phrase; report recall@5 and MRR in the README and tests
  (threshold to be set from the first run, documented).

### 6.5 Extractive answers (`secanalyst/answer/extractive.py`)
- From the top passages, score sentences against the question (embedding similarity +
  keyword overlap) and show the top 3–5 sentences with their citations, labelled
  "Key sentences from the filings (extractive, not AI-written)".

### 6.6 Due-diligence analytics (`secanalyst/diligence/`)
- **Risk-factor diff:** split Item 1A of the latest two 10-Ks into risk paragraphs (by
  headings/bold lead sentences); match across years by embedding similarity; classify
  new (no match ≥ threshold), removed, changed (match but text similarity < threshold),
  unchanged. Thresholds in config, validated on a few hand-checked examples.
- **Red-flag radar:** categories defined in `config/red_flags.yaml` with keyword patterns
  and seed sentences; count matching passages per company-year, with links to them.
  Customer concentration also pulls explicit percentages when stated ("one customer
  accounted for X % of revenue") with the citation.

### 6.7 Drafted answers (optional LLM layer, `secanalyst/answer/llm.py`)
- Provider-agnostic client (Claude default, model in config), forced structured output,
  answer must cite chunk ids; a verifier rejects answers whose citations are not in the
  retrieved set or whose numbers do not appear in the cited text (same fail-closed idea
  as project 2).
- Curated question set (`config/questions.yaml`, ~40). `python -m secanalyst.pipeline
  ai --refresh` generates and caches verified answers (cache key = hash of question +
  retrieved chunk ids + prompt version). Without a key: logs and exits 0; app shows the
  extractive answer only.
- If `ANTHROPIC_API_KEY` is set in the app's secrets: free-form drafted answers enabled
  with a daily cap (config, default 50 questions/day, counter in a small local file).

### 6.8 Client brief (`secanalyst/outputs/brief.py`)
- One-page PDF per company (reportlab): metrics vs peer median, top 5 risks with
  citations, what changed in the latest 10-K, red flags, data as-of date, disclaimer.
  English; French version optional (builder's call — documented if skipped).

### 6.9 App (`app/`)
- Pages: Home, Ask the filings, Due diligence, Benchmarking, Client brief, Data quality,
  About. Reads only committed files. Disclaimer on every page: "Educational project — not
  investment advice. Source: SEC EDGAR."

## 7. DAIS layer and engineering
`docs/business_requirements.md` (3 personas, user stories with acceptance criteria, KPI
definitions), `docs/data_dictionary.md`, `docs/data_model.md` (Mermaid),
`docs/methodology.md` (sectioning rules, XBRL tag mapping, ratio formulas, retrieval and
diff methods, evaluation results, limitations), pytest with no network (fixtures from
small saved filing extracts), ruff, GitHub Actions, README for recruiters with a
"Résumé en français".

## 8. Delivery order
1. Ingestion + parsing + XBRL ratios + Benchmarking page (publishable on its own).
2. Retrieval + evaluation + Ask the filings (extractive).
3. Due-diligence analytics + page; client brief.
4. Optional LLM layer (code + tests with fakes; real cache is a user step).
5. Docs, README, publish with the `publicar-proyecto-github` skill.

## 9. Decisions settled after the builder check (designer's calls)

**9.1 Size and performance budget.** Committed processed data ≤ 60 MB in total, no Git
LFS. Chunk text is committed (needed for display); vectors stored as float16 `.npy`;
BM25 rebuilt at app start from the committed chunks (cached by Streamlit). The embedding
model is downloaded on first start and cached, not committed. Targets: cold start ≤ 90 s,
warm query ≤ 3 s on Streamlit Community Cloud.

**9.2 Cut-off and fiscal-year labels.**
- The ingest run freezes an `as_of` date (recorded in the snapshot): "last 3 10-Ks" = the
  3 most recent 10-K filed on or before `as_of`; "latest 10-Q" = the most recent 10-Q
  filed after the latest 10-K, if any (otherwise none, shown as a note).
- Fiscal-year label = the company's own label from the 10-K cover data
  (`dei:DocumentFiscalYearFocus` of that filing), cross-checked against the period-end
  date; the period-end date is always shown next to the label.
- XBRL facts are matched to fiscal years by period end date (annual duration ≈ 1 year,
  form 10-K), not by the company-facts `fy` field.
- "5 fiscal years" = the 3 filing years plus the 2 earlier ones available in company facts.

**9.3 Evaluation ground truth.**
- The builder writes ~30 retrieval questions from the filings (expected ticker, year, item,
  key phrase); a separate reviewer spot-checks at least 10 of them; the README states the set
  was labelled by the author and shows recall@5 and MRR.
- Red-flag radar: precision measured on 40 hand-checked hits; target ≥ 80 %; result
  reported in the methodology.
- Risk-factor diff thresholds tuned on Apple and NVIDIA (latest two 10-Ks) with
  hand-checked pairs; the examples and thresholds are documented.

**9.4 Financial definitions (binding for benchmarks, brief and docs).**
- Total debt = short-term borrowings + commercial paper + current and long-term debt
  (finance leases included when tagged); operating leases excluded.
- Liquidity = cash and equivalents + short-term investments + long-term marketable
  securities; net cash = liquidity − total debt.
- NOPAT = operating income × (1 − effective tax rate), effective rate clamped to 0–35 %.
- Invested capital = equity + total debt − liquidity; if invested capital ≤ 0 or
  equity ≤ 0, ROIC / ROE are shown as "n/m" with the reason (relevant for Apple).
- Every derived definition appears in the methodology and as a tooltip in the app.

**9.5 Structural edge cases.**
- If Items 1A or 7 are missing from the primary document (cross-reference / annual-report
  exhibit), fetch the referenced exhibit (e.g. Exhibit 13); if still missing, the quality
  check flags it and the filing is excluded from the risk diff with a visible note.
- Multiple share classes (Alphabet) do not change the analysis; per-share data is not used.

**9.6 Publishing.** Step 5 (publish) is independent of the build; if it cannot run, all
earlier steps still finish.

## 10. Left to the builder
- Exact parsing approach for Item boundaries (regex vs an HTML-structure library),
  provided §6.2 quality checks pass for all 8 companies × 3 years.
- Embedding model and runtime within the Streamlit Cloud memory constraint.
- Chart library, page layouts, PDF styling.
- Module boundaries inside each package, as long as each component is testable alone.
