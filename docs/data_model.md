# Data model

The warehouse is a DuckDB file (`data/warehouse.duckdb`, not committed) rebuilt from the raw
EDGAR files; the committed copy of the data is `data/snapshot/*.parquet`. DDL: `secanalyst/warehouse/schema.sql`.
Column definitions: [data_dictionary.md](data_dictionary.md).

```mermaid
erDiagram
    dim_company ||--o{ fact_filings : files
    dim_company ||--o{ fact_financials : reports
    dim_company ||--o{ fact_ratios : "computed for"
    fact_filings ||--o{ fact_sections : "split into"
    fact_filings ||--o{ fact_chunks : "chunked into"
    fact_chunks ||--o{ fact_ai_answers : "cited by"
    fact_financials ||--o{ fact_ratios : "inputs of"

    dim_company {
        varchar ticker PK
        varchar name
        varchar cik
        int fy_end_month
    }
    fact_filings {
        varchar filing_id PK
        varchar ticker FK
        varchar form
        date filing_date
        date period_end
        varchar fiscal_year_label
    }
    fact_sections {
        varchar filing_id PK
        varchar item PK
        varchar text
    }
    fact_chunks {
        varchar chunk_id PK
        varchar filing_id FK
        int position
        varchar text
    }
    fact_financials {
        varchar ticker PK
        varchar fiscal_year_label PK
        varchar concept PK
        double value
        varchar tag
    }
    fact_ratios {
        varchar ticker PK
        varchar fiscal_year_label PK
        varchar ratio PK
        double value
        varchar status
    }
    fact_ai_answers {
        varchar cache_key PK
        varchar question
        varchar answer_json
    }
    meta {
        varchar key PK
        varchar value
    }
```

Notes

- Relations are logical: DuckDB enforces the primary keys and the `status` check on `fact_ratios`,
  the quality checks enforce the rest (for example a section without a filing is an error).
- The snapshot adds three derived files that are not warehouse tables: `chunks.parquet` with
  `vectors.npy` (the search index), `risk_diff.parquet` and `radar.parquet` (due diligence).
- A ratio row exists for every (company, fiscal year, ratio), with `status` `ok`, `n/a` or `n/m`.
- `fact_chunks` is declared in the schema but stays empty: the 4,376 chunks live in
  `chunks.parquet` (same columns plus `period_end`), which the search reads. `fact_ai_answers` is
  empty until a drafted answer is committed (none yet); the live cache is `data/ai_cache/`.
