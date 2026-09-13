"""Reading the database back. The command line and the MCP server both ask through here, so every door
gives the same answer. The database is opened read-only: nothing in this file can change it.

⛔ AN ANSWER CARRIES WHERE IT CAME FROM. A meaning comes with its NHS page and release; status carries
the publisher's credit line word for word. A code with no source is a rumour.

Dates are ISO text. A day asked about is compared by its first ten characters, so on the day a code was
reworded the answer is the NEW meaning, and no day ever has two.
"""
from __future__ import annotations

import re

from ukhrd.db import cursor

DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _rows(cur, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in cur.execute(sql, args).fetchall()]


def _resolve(cur, name: str) -> str | None:
    """A list's name as a person might type it: `admission_method`, `ref_admission_method`, `dim_…`."""
    for candidate in (name, name.removeprefix("ref_").removeprefix("dim_")):
        if cur.execute("SELECT 1 FROM meta_code_list WHERE list_name = ? LIMIT 1", (candidate,)).fetchone():
            return candidate
    return None


def status() -> list[dict]:
    """Per dataset: what it is, whose it is, how much we hold, when we last tried and how it went.

    ⛔ The counts come from what ANSWERS, not the latest attempt. After a refusal the latest attempt
    holds nothing, and saying "holding 0" while 1,273 codes answer queries is a lie.
    """
    with cursor(read_only=True) as cur:
        return _rows(cur, """
            SELECT s.source_key, s.label, s.publisher, s.licence, s.attribution, s.url, s.is_enabled,
                   s.cadence, f.fetch_run_id, f.started_at, f.outcome, f.release_label, f.is_changed, f.detail,
                   (SELECT count(*) FROM ref_code c WHERE c.source_key = s.source_key) AS codes_held,
                   (SELECT count(DISTINCT list_name) FROM ref_list_directory d
                     WHERE d.source_key = s.source_key) AS lists_held,
                   (SELECT count(*) FROM ref_list_directory d WHERE d.source_key = s.source_key) AS items_held
              FROM meta_data_source s
              LEFT JOIN meta_fetch_run f
                     ON f.fetch_run_id = (SELECT max(r.fetch_run_id) FROM meta_fetch_run r
                                           WHERE r.source_key = s.source_key)
             ORDER BY s.source_key""")


def lists(source_key: str | None = None, *, search: str | None = None) -> list[dict]:
    """Every list in force, biggest first. `search` matches words in its name or what it is."""
    where, args = [], []
    if source_key:
        where.append("source_key = ?")
        args.append(source_key)
    if search:
        where.append("(list_name LIKE ? OR concept LIKE ? OR item_name LIKE ?)")
        args += [f"%{search}%"] * 3
    sql = ("SELECT source_key, list_name, min(concept) AS concept, count(*) AS feeding_items, "
           "min(release_label) AS release_label, min(national_codes) AS national_codes, "
           "min(default_codes) AS default_codes FROM ref_list_directory"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " GROUP BY source_key, list_name ORDER BY national_codes DESC, list_name")
    with cursor(read_only=True) as cur:
        return _rows(cur, sql, args)


def lookup(code: str, *, list_name: str | None = None) -> list[dict]:
    """What does this code mean today? One answer per list and kind, with the page it came from."""
    where, args = ["c.code = ?"], [code]
    with cursor(read_only=True) as cur:
        if list_name:
            where.append("(c.list_name = ? OR d.list_key = ?)")
            args += [_resolve(cur, list_name) or list_name, list_name]
        return _rows(cur, f"""
            SELECT source_key, list_name, code_kind, code, description, concept, release_label, source_page
              FROM (SELECT c.*, d.concept, d.release_label, d.source_page,
                           row_number() OVER (PARTITION BY c.source_key, c.list_name, c.code_kind
                                              ORDER BY d.list_key) AS n
                      FROM ref_code c
                      JOIN ref_list_directory d ON d.source_key = c.source_key AND d.list_name = c.list_name
                     WHERE {" AND ".join(where)})
             WHERE n = 1
             ORDER BY source_key, list_name, code_kind""", args)


def show(list_name: str) -> dict | None:
    """One list in force, in full: every printing of it, and every code."""
    with cursor(read_only=True) as cur:
        name = _resolve(cur, list_name)
        about = name and _rows(cur, "SELECT * FROM ref_list_directory WHERE list_name = ? ORDER BY list_key",
                               (name,))
        if not about:
            return None
        codes = _rows(cur, "SELECT code_kind, code, description FROM ref_code WHERE list_name = ? "
                           "ORDER BY code_kind DESC, code", (name,))
    return {"list_name": name, "about": about, "codes": codes}


def history(source_key: str, limit: int = 20) -> list[dict]:
    """Every fetch of one dataset, newest first — refusals and failures included."""
    with cursor(read_only=True) as cur:
        return _rows(cur, "SELECT * FROM meta_fetch_run WHERE source_key = ? ORDER BY fetch_run_id DESC LIMIT ?",
                     (source_key, limit))


def changes(list_name: str, code: str | None = None) -> dict | None:
    """Every version of every code in one list, retired lists included, with the dates each was true."""
    with cursor(read_only=True) as cur:
        name = _resolve(cur, list_name)
        if name is None:
            return None
        about = dict(cur.execute(
            "SELECT min(coalesce(concept_name, item_name)) AS concept, min(loaded_at) AS first_seen, "
            "max(is_current) AS live, (SELECT loaded_by FROM meta_code_list WHERE list_name = :n "
            "ORDER BY loaded_at, code_list_key LIMIT 1) AS first_by, "
            "(SELECT group_concat(DISTINCT source_page) FROM meta_code_list WHERE list_name = :n) AS pages "
            "FROM meta_code_list WHERE list_name = :n", {"n": name}).fetchone())
        rows = _rows(cur, f'SELECT code, code_kind, description, valid_from, valid_to, is_current '
                          f'FROM "dim_{name}" WHERE ? IS NULL OR code = ? '
                          f'ORDER BY code_kind DESC, code, valid_from', (code, code))
    return {"list_name": name, **about, "pages": sorted((about["pages"] or "").split(",")), "rows": rows}


def meaning_on(list_name: str, code: str, day: str) -> dict | None:
    """What did this code mean on this day? Reads every version, so a withdrawn code still answers."""
    if not DAY.fullmatch(day):
        raise ValueError(f"a day looks like 2024-03-31, not {day!r}")
    found = changes(list_name, code)
    if found is None:
        return None
    found["rows"] = [r for r in found["rows"] if r["valid_from"][:10] <= day
                     and (r["valid_to"] is None or r["valid_to"][:10] > day)]
    return found
