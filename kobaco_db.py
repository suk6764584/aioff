from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

import duckdb


_TABLE_RE = re.compile(r"^[A-Za-z0-9_]+$")


class KobacoDB:
    """Read-only DuckDB views over the KOBACO Parquet snapshot."""

    def __init__(self, parquet_dir: str | os.PathLike[str] | None = None):
        base_dir = Path(__file__).resolve().parent
        configured = parquet_dir or os.getenv("KOBACO_PARQUET_DIR")
        self.parquet_dir = Path(configured) if configured else base_dir / "raw_data" / "parquet_db"
        self.parquet_dir = self.parquet_dir.resolve()
        self._lock = threading.RLock()
        self.conn = duckdb.connect(database=":memory:")
        self.tables: list[str] = []
        self._register_views()

    def _register_views(self) -> None:
        if not self.parquet_dir.is_dir():
            raise FileNotFoundError(f"KOBACO parquet directory not found: {self.parquet_dir}")

        parquet_files = sorted(self.parquet_dir.glob("*.parquet"))
        if not parquet_files:
            raise FileNotFoundError(f"No parquet files found: {self.parquet_dir}")

        for path in parquet_files:
            table = path.stem
            if not _TABLE_RE.fullmatch(table):
                continue
            escaped_path = str(path).replace("'", "''")
            with self._lock:
                self.conn.execute(
                    f'CREATE OR REPLACE VIEW "{table}" AS '
                    f"SELECT * FROM read_parquet('{escaped_path}')"
                )
            self.tables.append(table)

    def query(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self.conn.execute(sql, params or [])
            columns = [x[0] for x in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def has_tables(self, *names: str) -> bool:
        available = set(self.tables)
        return all(name in available for name in names)

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "parquet_dir": str(self.parquet_dir),
            "table_count": len(self.tables),
            "tables": list(self.tables),
        }


_instance: KobacoDB | None = None
_instance_error: str | None = None
_instance_lock = threading.Lock()


def get_kobaco_db() -> KobacoDB | None:
    global _instance, _instance_error
    if _instance is not None:
        return _instance
    if _instance_error is not None:
        return None
    with _instance_lock:
        if _instance is not None:
            return _instance
        if _instance_error is not None:
            return None
        try:
            _instance = KobacoDB()
        except Exception as exc:
            _instance_error = f"{type(exc).__name__}: {exc}"
            return None
    return _instance


def kobaco_status() -> dict[str, Any]:
    db = get_kobaco_db()
    if db is not None:
        return db.status()
    base_dir = Path(__file__).resolve().parent
    configured = os.getenv("KOBACO_PARQUET_DIR")
    parquet_dir = Path(configured) if configured else base_dir / "raw_data" / "parquet_db"
    return {
        "available": False,
        "parquet_dir": str(parquet_dir.resolve()),
        "table_count": 0,
        "tables": [],
        "error": _instance_error or "KOBACO DB not initialized",
    }
