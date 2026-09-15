from __future__ import annotations

from pathlib import Path

from cfb_canes_analytics.storage import append_parquet, read_or_none, upsert_parquet


def sparse_rows(n: int = 150) -> list[dict]:
    """A column that is null for longer than polars' 100-row inference window.

    This is the real ESPN shape: only a handful of games per week carry an odds
    provider, and they are never the first ones.
    """
    rows = [{"id": str(i), "provider": None} for i in range(n)]
    rows[-1]["provider"] = "DraftKings"
    return rows


def test_upsert_handles_late_appearing_values(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    assert upsert_parquet(path, sparse_rows(), ["id"]) == 150
    df = read_or_none(path)
    assert df is not None
    assert df.get_column("provider").drop_nulls().to_list() == ["DraftKings"]


def test_upsert_keeps_last_row_per_key(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    upsert_parquet(path, [{"id": "a", "v": 1}], ["id"])
    upsert_parquet(path, [{"id": "a", "v": 2}, {"id": "b", "v": 3}], ["id"])
    df = read_or_none(path)
    assert df is not None and df.height == 2
    assert df.filter(df["id"] == "a")["v"].to_list() == [2]


def test_append_accumulates_and_empty_is_a_noop(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    append_parquet(path, [{"id": "a"}])
    append_parquet(path, [{"id": "a"}])
    assert append_parquet(path, []) == 2


def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    assert read_or_none(tmp_path / "nope.parquet") is None
