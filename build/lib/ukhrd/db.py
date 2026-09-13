"""The one place a connection is made. The database is a single SQLite file, built from data/.

UKHRD_DB points at a different file; the default is ukhrd.db in the repo root. Read on every call so a
test can point it somewhere else.
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parents[2]


def path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("UKHRD_DB", ROOT / "ukhrd.db"))


def connect(target: pathlib.Path | None = None, *, read_only: bool = False) -> sqlite3.Connection:
    """⚠ Foreign keys are OFF in SQLite unless every connection turns them on. This one does."""
    target = pathlib.Path(target or path())
    if read_only:
        conn = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextlib.contextmanager
def cursor(*, read_only: bool = False):
    """A cursor that commits on success and rolls back on anything raised."""
    conn = connect(read_only=read_only)
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
