"""What the Parquet files promise: every version, real types, and the credit inside the file."""
from __future__ import annotations

import csv
import importlib.util
import pathlib

import pytest

from test_the_store_refuses_a_bad_answer import SOURCE, demo, three_lists  # noqa: F401 — demo is the fixture
from ukhrd import store

duckdb = pytest.importorskip("duckdb")
_spec = importlib.util.spec_from_file_location(
    "export_parquet", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "export_parquet.py")
export_parquet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_parquet)


def test_the_parquet_holds_every_version_with_real_types_and_the_credit_inside(tmp_path):
    store.refresh(SOURCE, read=lambda _url: three_lists(word="old"))
    store.refresh(SOURCE, read=lambda _url: three_lists(word="new"))

    made = export_parquet.export(tmp_path / "out")

    codes, lists = tmp_path / "out" / "codes.parquet", tmp_path / "out" / "lists.parquet"
    con = duckdb.connect()
    assert made == {"codes": 120, "lists": 3}, "every version of every code, not just today's"
    assert con.sql(f"SELECT count(*) FROM '{codes}' WHERE is_current").fetchone()[0] == 60
    assert con.sql(f"SELECT description, valid_to IS NULL FROM '{codes}' WHERE list_name = 'concept_0' "
                   "AND code = '0' ORDER BY valid_from").fetchall() == [("old 0", False), ("new 0", True)]

    types = {r[0]: r[1] for r in con.sql(f"DESCRIBE SELECT * FROM '{codes}'").fetchall()}
    assert types["valid_from"] == "TIMESTAMP WITH TIME ZONE" and types["is_current"] == "BOOLEAN"
    for path in (codes, lists):
        meta = dict(con.sql(f"SELECT decode(key), decode(value) FROM parquet_kv_metadata('{path}')").fetchall())
        assert meta["attribution"] == "Contains nothing from Nobody.", f"{path.name} lost the credit"


def test_the_release_also_carries_plain_csv_for_tools_that_cannot_read_parquet(tmp_path):
    """SQL Server, Excel and R cannot read Parquet. The CSV must be the same tables, same columns."""
    store.refresh(SOURCE, read=lambda _url: three_lists())

    export_parquet.export(tmp_path / "out")

    rows = list(csv.DictReader((tmp_path / "out" / "codes.csv").open(newline="", encoding="utf-8")))
    assert tuple(rows[0]) == export_parquet.CODES, "codes.csv must match the Parquet, column for column"
    assert len(rows) == 60 and {r["is_current"] for r in rows} == {"true"}, "booleans as in data/"
    assert [r["description"] for r in rows if r["list_name"] == "concept_0" and r["code"] == "0"] == ["meaning 0"]

    lists = list(csv.DictReader((tmp_path / "out" / "lists.csv").open(newline="", encoding="utf-8")))
    assert tuple(lists[0]) == export_parquet.LISTS and len(lists) == 3
