"""Write the Parquet files that go on every release, from ukhrd.db.

    python cli.py load && python scripts/export_parquet.py [folder]       (default: the current folder)

    codes.parquet   every version of every code in every list — the dim_ tables stacked, one row each
    lists.parquet   every version of every list's details: its name here, its NHS page, its data sets

Join them on source_key + list_name. One list_name can have several rows in lists.parquet — the same list
printed on several pages — so pick the rows you want before joining, or codes multiply.

⛔ THE CREDIT TRAVELS INSIDE THE FILE. Each file's Parquet metadata carries the publisher's attribution
word for word, from data/sources.csv, so copying the file copies the credit.

Timestamps are real UTC timestamps and is_current a real boolean, so a warehouse gets types, not text.
Needs DuckDB (requirements-export.txt). The core does not: only the release Action, and people who want
Parquet, install it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import duckdb  # noqa: E402

from ukhrd import db  # noqa: E402

VERSION = ("valid_from", "valid_to", "is_current", "first_fetch_run_id",
           "loaded_at", "loaded_by", "updated_at", "updated_by")
CODES = ("source_key", "list_name", "concept", "code_key", "code_kind", "code", "description") + VERSION
LISTS = ("source_key", "list_name", "list_key", "item_name", "concept_name", "superseded_by",
         "source_page", "data_sets") + VERSION
TIMES = {"valid_from", "valid_to", "loaded_at", "updated_at"}
TYPES = {"code_key": "BIGINT", "first_fetch_run_id": "BIGINT", "is_current": "BOOLEAN"}


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _write(con, name: str, columns: tuple[str, ...], rows: list[tuple], path: pathlib.Path, meta: dict) -> None:
    """Rows go in as text and are cast inside DuckDB, so no timezone package is needed."""
    con.execute(f"CREATE TABLE {name} (" + ", ".join(f"{c} {TYPES.get(c, 'VARCHAR')}" for c in columns) + ")")
    rows = [tuple(bool(v) if c == "is_current" else v for c, v in zip(columns, r)) for r in rows]
    con.executemany(f"INSERT INTO {name} VALUES (" + ", ".join("?" * len(columns)) + ")", rows)
    select = ", ".join(f"CAST({c} AS TIMESTAMPTZ) AS {c}" if c in TIMES else c for c in columns)
    kv = ", ".join(f"{k}: {_quote(v)}" for k, v in meta.items())
    con.execute(f"COPY (SELECT {select} FROM {name}) TO {_quote(str(path))} "
                f"(FORMAT parquet, COMPRESSION zstd, KV_METADATA {{{kv}}})")


def export(folder: pathlib.Path) -> dict:
    """Write codes.parquet and lists.parquet into `folder`. Returns how many rows each holds."""
    folder.mkdir(parents=True, exist_ok=True)
    src = db.connect(read_only=True)
    try:
        sources = src.execute("SELECT publisher, licence, attribution FROM meta_data_source "
                              "ORDER BY source_key").fetchall()
        releases = [r[0] for r in src.execute("SELECT release_label FROM meta_current_fetch ORDER BY source_key")]
        about = {r["list_name"]: r for r in src.execute(
            "SELECT list_name, min(source_key) AS source_key, min(coalesce(concept_name, item_name)) AS concept "
            "FROM meta_code_list GROUP BY list_name")}
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                            "AND name LIKE 'dim^_%' ESCAPE '^' ORDER BY name")]
        codes = []
        for table in tables:
            name = table.removeprefix("dim_")
            for r in src.execute(f'SELECT "{name}_key", code_kind, code, description, {", ".join(VERSION)} '
                                 f'FROM "{table}" ORDER BY code_kind DESC, code, valid_from'):
                codes.append((about[name]["source_key"], name, about[name]["concept"], *r))
        lists = [tuple(r) for r in src.execute(
            f"SELECT {', '.join(LISTS)} FROM meta_code_list ORDER BY source_key, list_name, list_key, valid_from")]
    finally:
        src.close()

    meta = {"attribution": " | ".join(sorted({s["attribution"] for s in sources})),
            "publisher": " | ".join(sorted({s["publisher"] for s in sources})),
            "licence": " | ".join(sorted({s["licence"] for s in sources})),
            "release": " | ".join(releases),
            "note": "UKHRD is independent and not endorsed by the publisher. The publisher's own page is the authority."}
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    _write(con, "codes", CODES, codes, folder / "codes.parquet", meta)
    _write(con, "lists", LISTS, lists, folder / "lists.parquet", meta)
    return {"codes": len(codes), "lists": len(lists)}


def main() -> int:
    folder = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    made = export(folder)
    print(f"✓  {made['codes']} code versions → {folder / 'codes.parquet'}")
    print(f"✓  {made['lists']} list versions → {folder / 'lists.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
