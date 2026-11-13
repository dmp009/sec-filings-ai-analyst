-- Warehouse schema (DuckDB). Natural keys are in secanalyst/warehouse/store.py.
CREATE TABLE IF NOT EXISTS dim_company (
    ticker VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    cik VARCHAR NOT NULL,
    fy_end_month INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_filings (
    filing_id VARCHAR PRIMARY KEY,      -- accession number
    ticker VARCHAR NOT NULL,
    form VARCHAR NOT NULL,              -- 10-K / 10-Q
    accession VARCHAR NOT NULL,
    filing_date DATE NOT NULL,
    period_end DATE NOT NULL,           -- dei:DocumentPeriodEndDate
    fiscal_year_label VARCHAR NOT NULL  -- dei:DocumentFiscalYearFocus
);

CREATE TABLE IF NOT EXISTS fact_sections (
    filing_id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    form VARCHAR NOT NULL,
    fiscal_year VARCHAR NOT NULL,
    item VARCHAR NOT NULL,              -- 1, 1A, ... (10-K); P1-2, P2-1A (10-Q)
    title VARCHAR,
    text VARCHAR NOT NULL,
    n_chars INTEGER NOT NULL,
    PRIMARY KEY (filing_id, item)
);

CREATE TABLE IF NOT EXISTS fact_financials (
    ticker VARCHAR NOT NULL,
    fiscal_year_label VARCHAR NOT NULL,
    period_end DATE NOT NULL,
    concept VARCHAR NOT NULL,
    value DOUBLE NOT NULL,              -- USD
    tag VARCHAR NOT NULL,               -- XBRL tag, or sum:/fallback: path for derived values
    accession VARCHAR NOT NULL,         -- source filing(s), comma-separated when derived
    PRIMARY KEY (ticker, fiscal_year_label, concept)
);

CREATE TABLE IF NOT EXISTS fact_ratios (
    ticker VARCHAR NOT NULL,
    fiscal_year_label VARCHAR NOT NULL,
    period_end DATE NOT NULL,
    ratio VARCHAR NOT NULL,
    value DOUBLE,
    status VARCHAR NOT NULL CHECK (status IN ('ok', 'n/a', 'n/m')),
    reason VARCHAR,
    PRIMARY KEY (ticker, fiscal_year_label, ratio)
);

CREATE TABLE IF NOT EXISTS fact_chunks (
    chunk_id VARCHAR PRIMARY KEY,       -- ticker/form/year/item/position
    filing_id VARCHAR NOT NULL,
    ticker VARCHAR NOT NULL,
    form VARCHAR NOT NULL,
    fiscal_year VARCHAR NOT NULL,
    item VARCHAR NOT NULL,
    position INTEGER NOT NULL,
    text VARCHAR NOT NULL,
    n_words INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_ai_answers (
    cache_key VARCHAR PRIMARY KEY,      -- hash(question + retrieved chunk ids + prompt version)
    question_id VARCHAR,
    question VARCHAR NOT NULL,
    answer_json VARCHAR NOT NULL,
    model VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key VARCHAR PRIMARY KEY,
    value VARCHAR
);
