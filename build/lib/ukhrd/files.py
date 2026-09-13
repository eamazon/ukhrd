"""The CSV files in data/ ARE the store. The SQLite database is built from them and can be thrown away.

    data/sources.csv                  what we know how to fetch — one row per dataset
    data/fetches.csv                  every fetch attempt, whatever happened, and who ran it
    data/lists.csv                    every version of every published list's details
    data/<source_key>/<list>.csv      every version of every code in one list

⛔ NOTHING IS EVER DELETED. A file is rewritten whole — every version it held, plus the new ones.
Every file in a batch is written under a temporary name first and only then swapped in, so a failure
while writing leaves the old files standing, not half of a new one.

Plain CSV, one row per line, in the same order every time, so `git diff` shows exactly what the
publisher changed and nothing else. Values are text; an empty cell is "no value".
"""
from __future__ import annotations

import csv
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

SOURCE = ("source_key", "label", "publisher", "licence", "attribution", "reader", "url",
          "floor_value_count", "cadence", "is_enabled", "notes", "created_at")
FETCH = ("fetch_run_id", "source_key", "started_at", "finished_at", "outcome", "release_label",
         "value_count", "content_hash", "is_changed", "detail", "loaded_by", "host")
VERSION = ("valid_from", "valid_to", "is_current", "first_fetch_run_id",
           "loaded_at", "loaded_by", "updated_at", "updated_by")
LIST = ("code_list_key", "source_key", "list_key", "list_name", "item_name", "concept_name",
        "superseded_by", "source_page", "data_sets") + VERSION


def code_columns(list_name: str) -> tuple[str, ...]:
    return (f"{list_name}_key", "code_kind", "code", "description") + VERSION


def data() -> pathlib.Path:
    """UKHRD_DATA, or the data/ folder in this repo. Read on every call so a test can point it away."""
    return pathlib.Path(os.environ.get("UKHRD_DATA", ROOT / "data"))


def sources_path() -> pathlib.Path:
    return data() / "sources.csv"


def fetches_path() -> pathlib.Path:
    return data() / "fetches.csv"


def lists_path() -> pathlib.Path:
    return data() / "lists.csv"


def codes_dir(source_key: str) -> pathlib.Path:
    return data() / source_key


def codes_path(source_key: str, list_name: str) -> pathlib.Path:
    return codes_dir(source_key) / f"{list_name}.csv"


def read(path: pathlib.Path) -> list[dict]:
    """Every row. An empty cell reads as None. A file that does not exist yet holds nothing."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]


def write_all(batch: dict[pathlib.Path, tuple[tuple[str, ...], list[dict]]]) -> None:
    """{path: (columns, rows)}. Every file is written aside first; only then is each swapped in."""
    staged = []
    try:
        for path, (columns, rows) in batch.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            staged.append((tmp, path))
            with tmp.open("w", newline="", encoding="utf-8") as f:
                out = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
                out.writeheader()
                out.writerows(rows)
    except BaseException:
        for tmp, _ in staged:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, path in staged:
        os.replace(tmp, path)
