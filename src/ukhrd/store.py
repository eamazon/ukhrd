"""Fetch a dataset, check it, fold it into the files, rebuild the database. The engine.

    NHS page ──reader──► lists ──floors──► history.fold() ──► data/*.csv ──load──► ukhrd.db

⭐ IT KNOWS NOTHING ABOUT WHICH DATASETS EXIST. data/sources.csv names them; READERS knows the shapes.
Adding a dataset of a shape we already read is one row in that file and no Python at all.

⭐ THE FILES ARE THE STORE. A refresh writes data/ first and rebuilds the database from it second. If
the rebuild fails, nothing is lost: the fetch is saved, and `python cli.py load` catches it up.

⛔ A THIN ANSWER IS REFUSED, NEVER APPLIED. Two floors, guarding different things.
`floor_value_count` catches a collapsed total. The vanished-list check catches ONE list dropping to
zero, which a total cannot see. Either way the last good copy stands and the refusal is written down
as loudly as a failure — silence reads as success.

⛔ EVERY ROW SAYS WHEN AND WHO, and both come from the FETCH: `started_at` and UKHRD_ACTOR (or the
person logged in). They are set once, here, and carried in the files — so rebuilding the database next
year still says when the fetch really happened.
"""
from __future__ import annotations

import getpass
import hashlib
import logging
import os
import socket
from datetime import datetime, timezone

from ukhrd import files, history, load
from ukhrd.readers import READERS

log = logging.getLogger(__name__)

LIST_ATTRS = ("list_name", "item_name", "concept_name", "superseded_by", "source_page", "data_sets")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def actor() -> str:
    """Who is doing this: UKHRD_ACTOR when set, otherwise the person logged in."""
    return os.environ.get("UKHRD_ACTOR") or getpass.getuser()


def sources(*, enabled_only: bool = True) -> list[dict]:
    return [s for s in files.read(files.sources_path())
            if not enabled_only or s["is_enabled"] == "true"]


def _source(source_key: str) -> dict:
    for s in sources(enabled_only=False):
        if s["source_key"] == source_key:
            return s
    raise KeyError(f"no dataset called {source_key!r} — add a row to data/sources.csv")


def _next_id() -> str:
    return str(max((int(r["fetch_run_id"]) for r in files.read(files.fetches_path())), default=0) + 1)


def _digest(lists: list[dict]) -> str:
    h = hashlib.sha256()
    for lst in sorted(lists, key=lambda x: x["list_key"]):
        h.update((lst["list_key"] + "\x1e").encode())
        for v in sorted(lst["values"], key=lambda v: (v["code_kind"], v["code"])):
            h.update(("\x1f".join((v["code_kind"], v["code"], v["description"])) + "\x1e").encode())
    return h.hexdigest()


def _describe(lists: list[dict], moved: dict, lists_moved: set, *, first: bool) -> str:
    """What changed, as a sentence a person can read, not a boolean."""
    codes = sum(len(lst["values"]) for lst in lists)
    if first:
        return f"first copy: {codes} codes across {len(lists)} lists"
    bits = []
    for label, pick in (("added", lambda o, c: o - c), ("removed", lambda o, c: c - o),
                        ("reworded", lambda o, c: o & c)):
        hits = {name: pick(o, c) for name, (o, c) in moved.items() if pick(o, c)}
        if hits:
            names = sorted(hits)
            bits.append(f"{sum(map(len, hits.values()))} {label} (" + ", ".join(names[:3]) +
                        ("…" if len(names) > 3 else "") + ")")
    if lists_moved:
        bits.append(f"details changed on {len(lists_moved)} list(s)")
    if not bits:
        return f"{codes} codes, no code or meaning changed"
    return f"{codes} codes · " + " · ".join(bits)


# ── saving ────────────────────────────────────────────────────────────────────────────────────────

def save(source_key: str, lists: list[dict], run: dict) -> dict:
    """Fold one good fetch into the files, with its log row, as ONE batch. Returns the log row.

    `run` is the log row. A refresh leaves `detail` and `is_changed` empty and they are worked out
    here; a replay of an old fetch passes them exactly as they were recorded at the time.
    """
    all_lists = files.read(files.lists_path())
    mine = [r for r in all_lists if r["source_key"] == source_key]
    stamp = {"run_id": run["fetch_run_id"], "at": run["started_at"], "actor": run["loaded_by"],
             "first": not mine}
    names = history.name_lists(lists)

    incoming = {(source_key, lst["list_key"]): {
        "list_name": names[lst["list_key"]], "item_name": lst["item_name"],
        "concept_name": lst["concept_name"], "superseded_by": lst["superseded_by"],
        "source_page": lst["source_page"], "data_sets": ";".join(lst["data_sets"]) or None}
        for lst in lists}
    list_rows, opened, closed = history.fold(
        mine, incoming, key=("source_key", "list_key"), attrs=LIST_ATTRS, keycol="code_list_key",
        next_key=max((int(r["code_list_key"]) for r in all_lists), default=0) + 1, **stamp)

    batch = {}
    if opened or closed:
        others = [r for r in all_lists if r["source_key"] != source_key]
        batch[files.lists_path()] = (files.LIST, sorted(
            others + list_rows, key=lambda r: (r["source_key"], r["list_key"], int(r["code_list_key"]))))

    codes: dict[str, dict] = {}
    for lst in lists:
        name, bucket = names[lst["list_key"]], codes.setdefault(names[lst["list_key"]], {})
        for v in lst["values"]:
            k = (v["code_kind"], v["code"])
            if k in bucket and bucket[k]["description"] != v["description"]:
                raise ValueError(f"{name}: code {v['code']} is printed with two different meanings")
            bucket[k] = {"description": v["description"]}

    moved = {}
    held = {p.stem for p in files.codes_dir(source_key).glob("*.csv")}
    for name in sorted(held | set(codes)):
        path, keycol = files.codes_path(source_key, name), f"{name}_key"
        rows, o, c = history.fold(files.read(path), codes.get(name, {}), key=("code_kind", "code"),
                                  attrs=("description",), keycol=keycol, **stamp)
        if o or c:
            batch[path] = (files.code_columns(name), sorted(
                rows, key=lambda r: (r["code_kind"] != "national", r["code"], int(r[keycol]))))
            moved[name] = (o, c)

    if run["detail"] is None:
        run["detail"] = _describe(lists, moved, opened | closed, first=stamp["first"])
    if run["is_changed"] is None:
        run["is_changed"] = "true" if batch else "false"
    run["finished_at"] = run["finished_at"] or now()
    batch[files.fetches_path()] = (files.FETCH, files.read(files.fetches_path()) + [run])
    files.write_all(batch)
    return run


def _give_up(run: dict, outcome: str, detail: str, value_count: int | None = None) -> dict:
    """A refusal or a failure. It gets a log row of its own and nothing else is touched."""
    log.warning("store: %s", detail)
    run = {**run, "fetch_run_id": _next_id(), "outcome": outcome, "detail": detail,
           "value_count": None if value_count is None else str(value_count), "release_label": None,
           "content_hash": None, "is_changed": None, "finished_at": now()}
    files.write_all({files.fetches_path(): (files.FETCH, files.read(files.fetches_path()) + [run])})
    return _rebuild(run)


def _rebuild(run: dict) -> dict:
    try:
        load.load()
        run["database"] = "rebuilt"
    except Exception as exc:  # noqa: BLE001 — the files are saved; the database can catch up later
        log.warning("store: saved to data/, but the database was not rebuilt — %s", exc)
        run["database"] = f"not rebuilt: {exc}"
    return run


# ── the one call ──────────────────────────────────────────────────────────────────────────────────

def refresh(source_key: str, *, read=None) -> dict:
    """Fetch one dataset and keep it, unless the answer is too thin to believe.

    Returns the log row. Never raises for an outage — the outcome says so, because one dataset being
    unreachable must not take the whole store down. `read` is the seam: a test hands over lists
    without touching the network.
    """
    src = _source(source_key)
    run = dict.fromkeys(files.FETCH)
    run.update(source_key=source_key, started_at=now(), loaded_by=actor(), host=socket.gethostname())
    reader = read or READERS.get(src["reader"])
    if reader is None:
        return _give_up(run, "failed", f"no reader called {src['reader']!r}")

    try:
        result = reader(src["url"])
        lists, release = result["lists"], result["release"]
    except Exception as exc:  # noqa: BLE001 — recorded, never raised: see the docstring
        return _give_up(run, "failed", f"could not read it: {exc}")

    codes = sum(len(lst["values"]) for lst in lists)

    # ⛔ FLOOR ONE — the total collapsed.
    if codes < int(src["floor_value_count"]):
        return _give_up(run, "refused", f"refused: got {codes} codes and we expect at least "
                        f"{src['floor_value_count']}. The previous copy is untouched.", codes)

    # ⛔ FLOOR TWO — a list vanished, which a total cannot see.
    held = {r["list_key"] for r in files.read(files.lists_path())
            if r["source_key"] == source_key and r["is_current"] == "true"}
    missing = held - {lst["list_key"] for lst in lists}
    if missing:
        return _give_up(run, "refused", f"refused: {len(missing)} list(s) we hold have disappeared, "
                        "e.g. " + ", ".join(sorted(missing)[:3]) + ". The previous copy is untouched.",
                        codes)

    run.update(fetch_run_id=_next_id(), outcome="success", release_label=release,
               value_count=str(codes), content_hash=_digest(lists))
    try:
        save(source_key, lists, run)
    except Exception as exc:  # noqa: BLE001 — a save that did not happen is a failure, not a success
        return _give_up(run, "failed", f"could not save it: {exc}", codes)
    log.info("store: %s -> %s", source_key, run["detail"])
    return _rebuild(run)


def refresh_all(keys: list[str] | None = None) -> list[dict]:
    """Every dataset, or the ones named. One failing does not stop the rest."""
    return [refresh(k) for k in (keys or [s["source_key"] for s in sources()])]
