"""DuckDB connection, schema creation and whitelisted upserts."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from secanalyst.config import REPO_ROOT

_SCHEMA = Path(__file__).parent / "schema.sql"
DB_PATH = REPO_ROOT / "data" / "warehouse.duckdb"

NATURAL_KEYS: dict[str, list[str]] = {
    "dim_company": ["ticker"],
    "fact_filings": ["filing_id"],
    "fact_sections": ["filing_id", "item"],
    "fact_financials": ["ticker", "fiscal_year_label", "concept"],
    "fact_ratios": ["ticker", "fiscal_year_label", "ratio"],
    "fact_chunks": ["chunk_id"],
    "fact_ai_answers": ["cache_key"],
    "meta": ["key"],
}
TABLES = list(NATURAL_KEYS)


def connect(path: Path | str = DB_PATH) -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(_SCHEMA.read_text())
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Delete rows matching the incoming natural keys, then insert ``df`` (columns in table
    order). Only whitelisted table names are accepted. Returns rows written."""
    if table not in NATURAL_KEYS:
        raise ValueError(f"Unknown table '{table}'")
    if df.empty:
        return 0
    keys = NATURAL_KEYS[table]
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    missing = set(cols) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for {table}: {sorted(missing)}")
    data = df[cols]
    con.register("_incoming", data)
    try:
        con.execute("BEGIN")
        cond = " AND ".join(f"t.{k} = i.{k}" for k in keys)
        con.execute(
            f"DELETE FROM {table} AS t WHERE EXISTS "
            f"(SELECT 1 FROM (SELECT DISTINCT {', '.join(keys)} FROM _incoming) i WHERE {cond})"
        )
        con.execute(f"INSERT INTO {table} SELECT * FROM _incoming")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_incoming")
    return len(data)
