"""Parquet storage under ``data/`` (gitignored). Small, boring, idempotent."""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import polars as pl


def data_dir() -> Path:
    return Path(os.environ.get("CFB_DATA_DIR", "data"))


def raw_path(name: str, base: Path | None = None) -> Path:
    return (base or data_dir()) / "raw" / name


def read_or_none(path: Path) -> pl.DataFrame | None:
    return pl.read_parquet(path) if path.exists() else None


def _write_atomic(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.write_parquet(tmp)
    os.replace(tmp, path)


def upsert_parquet(path: Path, rows: Iterable[dict[str, Any]], keys: list[str]) -> int:
    """Merge rows into ``path`` keeping the last row per key. Returns total row count."""
    new = pl.DataFrame(list(rows))
    if new.is_empty():
        existing = read_or_none(path)
        return 0 if existing is None else existing.height
    old = read_or_none(path)
    df = new if old is None else pl.concat([old, new], how="diagonal_relaxed")
    df = df.unique(subset=keys, keep="last", maintain_order=True)
    _write_atomic(df, path)
    return df.height


def append_parquet(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    new = pl.DataFrame(list(rows))
    if new.is_empty():
        existing = read_or_none(path)
        return 0 if existing is None else existing.height
    old = read_or_none(path)
    df = new if old is None else pl.concat([old, new], how="diagonal_relaxed")
    _write_atomic(df, path)
    return df.height


def existing_values(path: Path, column: str) -> set[Any]:
    df = read_or_none(path)
    if df is None or column not in df.columns:
        return set()
    return set(df.get_column(column).unique().to_list())
