"""Keep every version. Pure functions: no files, no database, so the rules can be read and tested alone.

    name_lists()  what each published list is called — the table a person queries
    fold()        slowly-changing Type 2: close what changed or went away, open what is new

⛔ NOTHING IS EVER DELETED AND NOTHING IS EVER OVERWRITTEN. A changed meaning closes the old row
(`valid_to`, `is_current = false`) and opens a new one. The NHS Data Dictionary publishes only CURRENT
codes, so when a code is dropped our copy is the only record it ever meant anything.

⛔ THE FIRST COPY IS VALID FROM THE BEGINNING. Before we started watching, NHS files already carried
these codes. A first row dated the day of our first fetch would make "what did 21 mean on a 2024
admission?" answer NOTHING. So the first version of every code is valid from 1900-01-01, and only
changes we actually saw carry the date we saw them. When we first saw it is `loaded_at`.
"""
from __future__ import annotations

import re

BEGINNING = "1900-01-01T00:00:00.000000+00:00"
NAME_LIMIT = 59  # every list's name is cut here. Changing it would rename tables and files, so it stays


def _slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return re.sub(r"^_|_$", "", text).lower()[:NAME_LIMIT]


def name_lists(lists: list[dict]) -> dict[str, str]:
    """{list_key: list_name}. Three rules, each earned by looking at the real dictionary on 2026-09-12:

    1. Name it after the CONCEPT, not the published item: `admission_method`, never
       `admission_method_code_hospital_provider_spell`.
    2. Several items can share a concept. Identical NATIONAL codes means one list the publisher prints
       more than once, so one name (NHS NUMBER STATUS INDICATOR CODE is printed three times). Different
       national codes are genuinely different lists and each keeps its item-based name.
    3. A name cut at 59 bytes can collide. Two different concepts landing on one name get numbered;
       several printings of ONE concept landing on one name is rule 2 working, not a collision.
    """
    concept = {lst["list_key"]: lst["concept_name"] or lst["item_name"] for lst in lists}
    code_sets: dict[str, set] = {}
    for lst in lists:
        national = tuple(sorted((v["code"], v["description"]) for v in lst["values"]
                                if v["code_kind"] == "national"))
        code_sets.setdefault(concept[lst["list_key"]], set()).add(national or None)

    base = {}
    for lst in lists:
        c = concept[lst["list_key"]]
        one_list = len(code_sets[c] - {None}) == 1
        base[lst["list_key"]] = _slug(c if one_list else lst["list_key"])

    names = {}
    for key, name in base.items():
        rivals = sorted({concept[k] for k, other in base.items() if other == name})
        names[key] = name if len(rivals) == 1 else f"{name[:56]}_{rivals.index(concept[key]) + 1}"
    return names


def fold(rows: list[dict], incoming: dict[tuple, dict], *, key: tuple[str, ...],
         attrs: tuple[str, ...], keycol: str, run_id: str, at: str, actor: str, first: bool,
         next_key: int | None = None) -> tuple[list[dict], set, set]:
    """Fold one fetch into every version held. Returns (every version now held, opened, closed).

    `rows` are the versions already held, as read from their file. `incoming` is what this fetch says,
    keyed by the natural key. Every timestamp is `at` — the time of the FETCH, never the time this
    runs, because on a replay those are far apart and a date that records when code ran records
    nothing. A key missing from `incoming` is closed, never removed.
    """
    rows = [dict(r) for r in rows]
    current = {tuple(r[k] for k in key): r for r in rows if r["is_current"] == "true"}

    closed = set()
    for k, row in current.items():
        if k not in incoming or any(row[a] != incoming[k][a] for a in attrs):
            row.update(valid_to=at, is_current="false", updated_at=at, updated_by=actor)
            closed.add(k)

    if next_key is None:
        next_key = max((int(r[keycol]) for r in rows), default=0) + 1
    opened = set()
    for k in sorted(incoming, key=lambda k: tuple(v or "" for v in k)):
        if k in current and k not in closed:
            continue
        rows.append({keycol: str(next_key), **dict(zip(key, k)),
                     **{a: incoming[k][a] for a in attrs},
                     "valid_from": BEGINNING if first else at, "valid_to": None, "is_current": "true",
                     "first_fetch_run_id": run_id, "loaded_at": at, "loaded_by": actor,
                     "updated_at": None, "updated_by": None})
        opened.add(k)
        next_key += 1
    return rows, opened, closed
