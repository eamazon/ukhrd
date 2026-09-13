"""Build the database from the files in data/. The database is one SQLite file you can throw away.

    python cli.py load

Builds a fresh file beside the old one and swaps it in, so anyone reading sees the old copy or the new
one, never half of each. About a second, no network, nothing to install.

The fixed tables are plain SQL in db/schema.sql and the views over them in db/views.sql. Python writes
only what cannot be written in advance: one dim_ table and one ref_ view per list, because which lists
exist is decided by the publisher, not by us.

⛔ A LIST THE PUBLISHER STOPPED PRINTING KEEPS ITS TABLE. Its rows are closed in its file; here it gets
its dim_ table and history as ever, but no ref_ view, so it cannot answer as though it were current.

⚠ ref_code is one UNION ALL over every current list. SQLite allows 500 arms in one compound SELECT.
"""
from __future__ import annotations

import csv
import os
import pathlib
import re

from ukhrd import db, files

SQL = files.ROOT / "db"
SAFE = re.compile(r"[a-z0-9_]+")
BOOLEAN = {"is_enabled", "is_changed", "is_current"}

DIM_TABLE = """
CREATE TABLE "dim_{name}" (
    /* {about} */
    "{name}_key"       INTEGER NOT NULL,
    code_kind          TEXT    NOT NULL,
    code               TEXT    NOT NULL,
    description        TEXT    NOT NULL,
    valid_from         TEXT    NOT NULL,
    valid_to           TEXT,
    is_current         INTEGER NOT NULL,
    first_fetch_run_id INTEGER NOT NULL,
    loaded_at          TEXT    NOT NULL,
    loaded_by          TEXT    NOT NULL,
    updated_at         TEXT,
    updated_by         TEXT,
    CONSTRAINT pk_{name} PRIMARY KEY ("{name}_key"),
    CONSTRAINT fk_first_fetch FOREIGN KEY (first_fetch_run_id) REFERENCES meta_fetch_run (fetch_run_id),
    CONSTRAINT ck_code_kind CHECK (code_kind IN ('national', 'default')),
    CONSTRAINT ck_is_current CHECK (is_current IN (0, 1)),
    CONSTRAINT ck_valid_span CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_open_means_current CHECK (is_current = (valid_to IS NULL)),
    CONSTRAINT ck_closed_says_who CHECK (is_current = 1 OR (updated_at IS NOT NULL AND updated_by IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX "ix_{name}" ON "dim_{name}" (code_kind, code) WHERE is_current = 1;
"""


def _insert(conn, table: str, columns: tuple[str, ...], path: pathlib.Path) -> None:
    """One file in. A file whose columns have drifted is refused before a single row goes in."""
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as f:
        rows = csv.reader(f)
        if next(rows, None) != list(columns):
            raise ValueError(f"{path} does not have the columns {list(columns)} — nothing was loaded")
        flags = [c in BOOLEAN for c in columns]
        data = []
        for n, row in enumerate(rows, start=2):
            if len(row) != len(columns):
                raise ValueError(f"{path} line {n} has {len(row)} values, expected {len(columns)}")
            data.append(tuple(None if v == "" else ({"true": 1, "false": 0}[v] if flag else v)
                              for v, flag in zip(row, flags)))
    names = ", ".join(f'"{c}"' for c in columns)
    conn.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({", ".join("?" * len(columns))})', data)


def _build(conn) -> dict:
    conn.executescript((SQL / "schema.sql").read_text())
    _insert(conn, "meta_data_source", files.SOURCE, files.sources_path())
    _insert(conn, "meta_fetch_run", files.FETCH, files.fetches_path())
    _insert(conn, "meta_code_list", files.LIST, files.lists_path())

    about = {(r["source_key"], r["list_name"]): r for r in conn.execute(
        "SELECT source_key, list_name, min(coalesce(concept_name, item_name)) AS concept, "
        "max(is_current) AS live FROM meta_code_list GROUP BY source_key, list_name")}
    current = []
    tables = 0
    for (source,) in conn.execute("SELECT source_key FROM meta_data_source ORDER BY source_key").fetchall():
        for path in sorted(files.codes_dir(source).glob("*.csv")):
            name, row = path.stem, about.get((source, path.stem))
            if row is None or not SAFE.fullmatch(name):
                raise ValueError(f"{path} has codes but data/lists.csv names no list called {name!r} — "
                                 "the files disagree, so nothing was loaded")
            conn.executescript(DIM_TABLE.format(name=name, about=f"{row['concept']} — every version of "
                                                f"every code. From {source}/{path.name}".replace("*/", "")))
            _insert(conn, f"dim_{name}", files.code_columns(name), path)
            tables += 1
            if row["live"]:
                conn.execute(f'CREATE VIEW "ref_{name}" AS SELECT code_kind, code, description '
                             f'FROM "dim_{name}" WHERE is_current = 1')
                current.append((source, name))

    arms = [f"SELECT '{s}' AS source_key, '{n}' AS list_name, code_kind, code, description "
            f'FROM "dim_{n}" WHERE is_current = 1' for s, n in current]
    conn.execute("CREATE VIEW ref_code AS " + (" UNION ALL ".join(arms) or
                 "SELECT NULL AS source_key, NULL AS list_name, NULL AS code_kind, NULL AS code, "
                 "NULL AS description WHERE 0"))
    conn.executescript((SQL / "views.sql").read_text())
    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise ValueError(f"{len(broken)} row(s) point at something that does not exist — nothing was loaded")
    conn.commit()
    return {"tables": tables, "current_lists": len(current)}


def load(target: pathlib.Path | None = None) -> dict:
    """Throw the database away and rebuild it from data/. Returns how many tables and live lists."""
    target = pathlib.Path(target or db.path())
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    conn = db.connect(tmp)
    try:
        built = _build(conn)
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(tmp, target)
    return built
