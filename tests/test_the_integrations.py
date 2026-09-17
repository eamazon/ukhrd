"""What the warehouse loaders promise: every column named, the stable links, and the credit carried.

They cannot be run here — nobody has a Fabric or Snowflake account in a test — so what is guarded is the
thing that silently rots: a column added to the Parquet files and never added to the loaders.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("export_parquet", ROOT / "scripts" / "export_parquet.py")
export_parquet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export_parquet)   # also puts src/ on the path
from test_the_store_refuses_a_bad_answer import SOURCE, demo, three_lists  # noqa: E402,F401 — demo is the fixture
from ukhrd import files as files_module, store  # noqa: E402

SQL = (ROOT / "integrations" / "snowflake" / "load_ukhrd.sql").read_text()
NOTEBOOK = (ROOT / "integrations" / "fabric" / "load_ukhrd.ipynb").read_text()
CREDIT = "Contains information from NHS England"
LATEST = "https://github.com/eamazon/ukhrd/releases/latest/download/"


def test_the_snowflake_script_names_every_column_and_builds_a_table_per_list():
    for column in export_parquet.CODES:
        assert column in SQL.split("CREATE OR REPLACE TABLE ukhrd_lists")[0], f"ukhrd_codes is missing {column}"
    for column in export_parquet.LISTS:
        assert column in SQL, f"ukhrd_lists is missing {column}"
    assert "'CREATE OR REPLACE TABLE ukhrd_' || one.list_name" in SQL, "no table per reference list"
    assert "MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE" in SQL, "Parquet columns are lower case"
    assert "USE_LOGICAL_TYPE = TRUE" in SQL, "without it Snowflake reads the timestamps as numbers"


def test_the_fabric_notebook_is_valid_and_builds_a_table_per_list():
    book = json.loads(NOTEBOOK)
    source = "".join("".join(cell["source"]) for cell in book["cells"])

    assert book["nbformat"] == 4 and book["cells"], "Fabric imports nbformat 4 notebooks"
    assert all(cell["cell_type"] in ("code", "markdown") for cell in book["cells"])
    assert 'saveAsTable(PREFIX + name)' in source, "no table per reference list"
    assert 'F.col("is_current")' in source, "the per-list tables hold today's codes only"
    assert "/lakehouse/default/Files/" in source


def test_the_per_list_loop_makes_exactly_one_table_per_code_file(tmp_path):
    """Both loaders run the same query to decide which tables to make. Run it here on real files."""
    duckdb = pytest.importorskip("duckdb")
    store.refresh(SOURCE, read=lambda _url: three_lists())
    export_parquet.export(tmp_path / "out")

    con = duckdb.connect()
    con.execute(f"CREATE TABLE ukhrd_codes AS SELECT * FROM '{tmp_path / 'out' / 'codes.parquet'}'")
    names = [r[0] for r in con.execute(
        "SELECT DISTINCT list_name FROM ukhrd_codes WHERE is_current ORDER BY 1").fetchall()]
    for name in names:
        con.execute(f"CREATE OR REPLACE TABLE ukhrd_{name} AS SELECT code_kind, code, description "
                    f"FROM ukhrd_codes WHERE is_current AND list_name = '{name}'")

    made = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables "
                                      "WHERE table_name LIKE 'ukhrd_%'").fetchall()} - {"ukhrd_codes"}
    files = {p.stem for p in files_module.codes_dir(SOURCE).glob("*.csv")}
    assert made == {"ukhrd_" + f for f in files}, "one table per code file, named after it"
    assert con.execute("SELECT count(*) FROM ukhrd_concept_0").fetchone()[0] == 20


def test_both_loaders_use_the_stable_links_and_carry_the_credit():
    for name, text in (("snowflake", SQL), ("fabric", NOTEBOOK)):
        assert LATEST in text, f"{name} should follow the latest release, not a fixed version"
        assert "codes.parquet" in text and "lists.parquet" in text, f"{name} loads both files"
        assert CREDIT in text, f"{name} dropped NHS England's credit"
        assert "not endorsed by NHS England" in text, f"{name} dropped the not-endorsed line"
