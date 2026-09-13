"""UKHRD as an MCP server: what NHS codes mean, for any AI assistant that speaks MCP.

    python cli.py mcp          from a clone, over stdio
    ukhrd-mcp                  installed straight from GitHub — see "For AI assistants" in README.md

⛔ READ-ONLY. It opens ukhrd.db read-only and never fetches from the NHS. Refreshing is the daily check's
job, where a change is looked at before it is published.

Where the database comes from:
  from a clone      the repo's own ukhrd.db, built from data/ first if it is not there yet
  installed         the newest GitHub release's ukhrd.db, kept in ~/.cache/ukhrd and fetched again once
                    it is a day old — NHS England's terms say a cached copy "should" be refreshed every
                    24 hours. A failed or garbled download keeps the copy already held.

⛔ THE CREDIT TRAVELS WITH THE ANSWER. Every result carries the publisher's attribution line word for
word, from data/sources.csv, and the page each list came from. NHS England's terms require the credit
wherever the data goes, and an assistant repeating an answer is the data going somewhere.

The tools are plain functions over ask.py, so they are tested without the MCP library installed.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
import urllib.request

from ukhrd import ask, db, files, load

RELEASE = os.environ.get("UKHRD_RELEASE", "https://github.com/eamazon/ukhrd/releases/latest/download/ukhrd.db")
FRESH_FOR = 24 * 3600
SQLITE = b"SQLite format 3\x00"

NOT_ENDORSED = ("UKHRD is independent and not endorsed by the publisher. The publisher's own page is the "
                "authority: check source_page before relying on a code.")

INSTRUCTIONS = """UKHRD answers what the short codes in UK health data mean: the code lists of the NHS
Commissioning Data Sets, copied exactly as published, with every past meaning kept and dated.
Find a list with search_lists, then use lookup_code or show_list. To label an old record, use
code_meaning_on with the record's date. `default` codes are the publisher's "not known / not applicable"
values. Never tidy or normalise a code: a file writing C_100 means the published code 100.
When you repeat an answer, give its source_page and this credit: """


def _answer(**result) -> dict:
    return {**result, "credit": sorted({s["attribution"] for s in ask.status()}), "note": NOT_ENDORSED}


def search_lists(words: str | None = None) -> dict:
    """Find code lists by words in their name, e.g. "admission" or "ethnic". No words: every list in force."""
    return _answer(lists=ask.lists(search=words))


def lookup_code(code: str, list_name: str | None = None) -> dict:
    """What a code means today. Give list_name (e.g. admission_method) when you know it; without it, every
    list holding that code answers."""
    return _answer(matches=ask.lookup(code, list_name=list_name))


def show_list(list_name: str) -> dict:
    """Every code in one list today, with the page or pages it was copied from and the release."""
    found = ask.show(list_name)
    return _answer(**found) if found else _answer(error=f"no list called {list_name!r} in force; try search_lists")


def code_meaning_on(list_name: str, code: str, day: str) -> dict:
    """What a code meant on a given day, written YYYY-MM-DD. Use it to label historic records. Codes held
    since before UKHRD started watching are valid from 1900-01-01."""
    try:
        found = ask.meaning_on(list_name, code, day)
    except ValueError as exc:
        return _answer(error=str(exc))
    return _answer(**found) if found else _answer(error=f"no list called {list_name!r}; try search_lists")


def code_history(list_name: str, code: str | None = None) -> dict:
    """Every version of every code in a list, or of one code, with the dates each meaning was in force.
    Lists the publisher has stopped printing still answer here."""
    found = ask.changes(list_name, code)
    return _answer(**found) if found else _answer(error=f"no list called {list_name!r}; try search_lists")


def about() -> dict:
    """What UKHRD holds, from which release, when it was last refreshed, and the credit the publisher asks for."""
    return _answer(datasets=ask.status())


TOOLS = (search_lists, lookup_code, show_list, code_meaning_on, code_history, about)


def build():
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    credit = " ".join(sorted({s["attribution"] for s in ask.status()}))
    server = MCPServer(name="ukhrd", instructions=INSTRUCTIONS + credit)
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                                openWorldHint=False)
    for tool in TOOLS:
        server.tool(annotations=read_only)(tool)
    return server


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def latest_copy(cache: pathlib.Path, *, fetch=None, now: float | None = None) -> pathlib.Path:
    """The newest released ukhrd.db, kept at `cache`, fetched again once it is a day old."""
    now = time.time() if now is None else now
    if cache.exists() and now - cache.stat().st_mtime < FRESH_FOR:
        return cache
    try:
        body = (fetch or _download)(RELEASE)
        if not body.startswith(SQLITE):
            raise ValueError(f"{RELEASE} did not hand back a SQLite database")
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(cache.name + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, cache)
    except Exception as exc:  # noqa: BLE001 — an old copy answers better than none
        if not cache.exists():
            raise
        print(f"ukhrd: could not fetch a newer copy, using the one from "
              f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(cache.stat().st_mtime))} UTC — {exc}", file=sys.stderr)
    return cache


def main() -> None:
    """⚠ stdout is the MCP conversation. Anything said to a person goes to stderr."""
    if "UKHRD_DB" not in os.environ and not files.sources_path().exists():
        home = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or pathlib.Path.home() / ".cache")
        os.environ["UKHRD_DB"] = str(latest_copy(home / "ukhrd" / "ukhrd.db"))
    elif not db.path().exists():
        load.load()
    build().run(transport="stdio")
