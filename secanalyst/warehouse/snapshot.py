"""Committed parquet snapshot of the warehouse: the app reads it without network or a
warehouse file. Budget (design §9.1): all committed processed data <= 60 MB."""

from __future__ import annotations

from pathlib import Path

import duckdb

from secanalyst.config import REPO_ROOT
from secanalyst.warehouse.store import NATURAL_KEYS, TABLES, connect

SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshot"
MAX_BYTES = 60 * 1024 * 1024


def _sql_path(p: Path) -> str:
    return p.as_posix().replace("'", "''")


def export_snapshot(con: duckdb.DuckDBPyConnection, out_dir: Path | str = SNAPSHOT_DIR) -> int:
    """One ZSTD parquet file per table, rows ordered by the natural key (stable diffs).
    Returns the total size in bytes."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        order = ", ".join(NATURAL_KEYS[table])
        con.execute(
            f"COPY (SELECT * FROM {table} ORDER BY {order}) "
            f"TO '{_sql_path(out_dir / f'{table}.parquet')}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    return sum((out_dir / f"{t}.parquet").stat().st_size for t in TABLES)


def load_snapshot(snapshot_dir: Path | str = SNAPSHOT_DIR) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with every warehouse table loaded from the parquet snapshot."""
    con = connect(":memory:")
    for table in TABLES:
        path = _sql_path(Path(snapshot_dir) / f"{table}.parquet")
        con.execute(f"INSERT INTO {table} SELECT * FROM read_parquet('{path}')")
    return con
