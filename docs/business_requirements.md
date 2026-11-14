# Business requirements

## Context

Analysts who cover large listed companies read the same documents every year: the 10-K and the
10-Q filed with the SEC. The useful content (risk factors, MD&A, customer concentration, legal
proceedings) is buried in documents of 100 to 200 pages, and the financial statements use
different fiscal calendars and different XBRL tags from one company to the next. This project
answers the questions an analyst asks first, with every number and quote traceable to a filing.

Scope: 8 companies (AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, TSLA), the latest three 10-Ks of
each (24) plus the latest 10-Q when one follows the latest 10-K (7 companies; Apple has none), XBRL company facts for five fiscal years, data as of 2026-11-13.

## Personas

| Persona | Job | What they need from the tool |
|---|---|---|
| **Equity research analyst** (buy-side or sell-side, covers the tech sector) | Updates a model and a note after each filing | Find what a company says about a topic, with the exact passage and filing; see what changed in the risk factors since last year |
| **Credit or due-diligence analyst** (bank, fund, M&A team) | Screens a counterparty before a committee | Red flags in one view (litigation, export controls, concentration, cyber), comparable leverage and liquidity ratios |
| **Client-facing banker or advisor** | Prepares a meeting with a corporate client or a company in a portfolio | A one-page brief with key metrics against peers, top risks and recent changes, each with a citation |

## User stories and acceptance criteria

| ID | Story | Acceptance criteria |
|---|---|---|
| US1 | As an analyst, I search the filings in plain English so that I find the relevant passage fast | Results show the passage, company, form, fiscal year, item and period end; filters by company, year, form and item; each result is a citation |
| US2 | As an analyst, I read the key sentences without an API key so that the tool is usable offline | Without a key the answer is a set of verbatim sentences, labelled "extractive"; nothing is generated |
| US3 | As an analyst, I can get a drafted answer when a key is configured, and trust it | Drafted answer cites only retrieved passages; every number matches a cited passage in unit, scale and sign; failing answers are dropped, never shown; identical questions hit a cache; a daily cap limits calls |
| US4 | As an analyst, I see what changed in the risk factors between the latest two 10-Ks | Risks are listed as new, removed, reworded, minor edit or identical, with old and new text side by side; thresholds are documented |
| US5 | As a due-diligence analyst, I get red flags per company and year | Six categories; each hit is a passage with its filing citation; precision on a holdout is published with its confidence interval; customer concentration shows percentages |
| US6 | As an analyst, I compare companies on comparable ratios | Latest fiscal year ranked per ratio, peer median, definition shown, fiscal-year end shown; n/a (input missing) and n/m (not meaningful) shown with their reason, never imputed |
| US7 | As a banker, I export a one-page client brief | A4 PDF per company: key metrics against the peer median, top risks with citations, changes in the latest 10-K, red flags, disclaimer |
| US8 | As a user, I can judge the data quality | A quality page and `data_quality_report.md` list the checks run, the errors (0 expected), the warnings and the ratios not computed, each with its reason |

## KPIs

| KPI | Target | Where measured |
|---|---|---|
| Retrieval recall@5 with company and year filters | at least 0.75 | `pipeline eval`, 30 labelled questions |
| Retrieval MRR (same setting) | reported, no target | same |
| Red-flag precision on a holdout never used for tuning | at least 0.80, reported with its interval | `docs/design/radar_labelled_hits.csv` |
| Quality errors in the data run | 0 | `data_quality_report.md` |
| Drafted answers shown with an unsupported number | 0 | verification step, `tests/test_answer.py`, `tests/test_llm.py` |
| Fiscal years of revenue per company | at least 5 | `financials_years` check |

## Out of scope

Market prices and valuation, investment recommendations, companies beyond the eight, real-time
filings, non-US filers.
