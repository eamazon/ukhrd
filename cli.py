"""UKHRD on the command line. The other doors are plain SQL (docs/QUERIES.md) and the MCP server.

    python cli.py refresh [dataset]      fetch it, fold it into data/, rebuild the database
    python cli.py load                   rebuild the database from data/ alone — no fetching
    python cli.py status                 what we hold and how fresh it is
    python cli.py lists [dataset]        every list, biggest first, with its ref_<name>
    python cli.py show <list>            one list in full
    python cli.py lookup <list> <code>   what does this code mean?
    python cli.py history <dataset>      every fetch, newest first
    python cli.py changes <list>         every version of every code in one list, with its dates
    python cli.py mcp                    serve it to an AI assistant over MCP (needs requirements-mcp.txt)
"""
from __future__ import annotations

import logging
import pathlib
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "src"))

from ukhrd import ask, files, load, store  # noqa: E402

MARK = {"success": "✓", "refused": "⛔", "failed": "✗"}


def _wrap(text: str, indent: int = 5, width: int = 92) -> str:
    return textwrap.fill(text, width=width, subsequent_indent=" " * indent)


def _when(stamp: str) -> str:
    return stamp[:16].replace("T", " ")


def cmd_refresh(args: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="   %(message)s")
    entries = store.refresh_all(args or None)
    print()
    for e in entries:
        print(f"{MARK.get(e['outcome'], '?')}  {e['source_key']}  {e['detail']}")
        if e["database"] != "rebuilt":
            print(f"   ⚠ saved to {files.data()}, but the database was {e['database']}")
            print("     to try again, run:  python cli.py load")
    return 0 if all(e["outcome"] == "success" for e in entries) else 1


def cmd_load(_args: list[str]) -> int:
    built = load.load()
    print(f"✓  database rebuilt from {files.data()}: {built['tables']} list tables, "
          f"{built['current_lists']} in force today")
    return 0


def cmd_status(_args: list[str]) -> int:
    rows = ask.status()
    if not rows:
        print("nothing registered yet")
        return 0
    for r in rows:
        head = f"{r['source_key']}   {r['label']}"
        print(f"\n{head}\n{'-' * len(head)}")
        print(f"     from      {r['publisher']} · {r['licence']}")
        print(f"     credit    {_wrap(r['attribution'], indent=15)}")
        if not r["outcome"]:
            print("     never fetched.  run:  python cli.py refresh " + r["source_key"])
            continue
        print(f"     holding   {r['codes_held']:,} codes · {r['lists_held']} lists "
              f"(from {r['items_held']} published items)")
        print(f"     edition   {r['release_label'] or 'unknown'}")
        print(f"     last try  {_when(r['started_at'])}   {r['outcome']}")
        print(f"     {_wrap(r['detail'])}")
        print(f"     refresh   {r['cadence']}" + ("" if r["is_enabled"] else "   (switched off)"))
    return 0


def cmd_lists(args: list[str]) -> int:
    rows = ask.lists(args[0] if args else None)
    if not rows:
        print("nothing held yet — run:  python cli.py refresh")
        return 1
    print(f"\n{'codes':>6}  {'query this':<56}  what it is")
    print("-" * 110)
    for r in rows:
        merged = f"   ({r['feeding_items']} printings)" if r["feeding_items"] > 1 else ""
        print(f"{r['national_codes']:>6}  {'ref_' + r['list_name']:<56}  {r['concept'][:36]}{merged}")
    print(f"\n{len(rows)} lists")
    return 0


def cmd_show(args: list[str]) -> int:
    if not args:
        print("usage: python cli.py show <list>")
        return 1
    found = ask.show(args[0])
    if found is None:
        print(f"\nno list called {args[0]!r} in force. try:  python cli.py lists")
        return 1
    about, codes = found["about"], found["codes"]
    print(f"\nref_{found['list_name']}   {about[0]['concept']}")
    print("-" * 100)
    for c in codes:
        tag = "" if c["code_kind"] == "national" else " ·default"
        print(f"  {c['code']:<8}{tag:<9} {_wrap(c['description'], indent=19)}")
    print(f"\n  {len(codes)} codes · {about[0]['release_label']}")
    for m in about:
        print(f"  from  {m['item_name']}")
        print(f"        {m['source_page']}")
    if about[0]["superseded_by"]:
        print(f"  ⚠ the publisher says this is being replaced by {about[0]['superseded_by']}")
    return 0


def cmd_lookup(args: list[str]) -> int:
    if not args:
        print("usage: python cli.py lookup <list> <code>   or   lookup <code>")
        return 1
    list_name, code = (args[0], args[1]) if len(args) > 1 else (None, args[0])
    hits = ask.lookup(code, list_name=list_name)
    if not hits:
        print(f"\nno code {code!r}" + (f" in {list_name}" if list_name else "")
              + ". try:  python cli.py lists")
        return 1
    for h in hits:
        tag = "" if h["code_kind"] == "national" else "   [a default code: not known / not applicable]"
        print(f"\n{h['code']}   {_wrap(h['description'])}{tag}")
        print(f"\n     list      ref_{h['list_name']}   ({h['concept']})")
        print(f"     edition   {h['release_label']}")
        print(f"     page      {h['source_page']}")
    return 0


def cmd_history(args: list[str]) -> int:
    if not args:
        print("usage: python cli.py history <dataset>")
        return 1
    rows = ask.history(args[0])
    if not rows:
        print(f"no fetches recorded for {args[0]!r}")
        return 1
    for r in rows:
        print(f"{MARK.get(r['outcome'], '?')}  {_when(r['started_at'])}  "
              f"{r['loaded_by']:<16}  {_wrap(r['detail'], indent=42)}")
    return 0


def cmd_changes(args: list[str]) -> int:
    """The point of keeping history: what a code used to mean, and when it stopped meaning it."""
    if not args:
        print("usage: python cli.py changes <list>")
        return 1
    found = ask.changes(args[0])
    if found is None:
        print(f"\nno list called {args[0]!r}. try:  python cli.py lists")
        return 1
    rows = found["rows"]
    live = [r for r in rows if r["is_current"]]
    print(f"\ndim_{found['list_name']}   {found['concept']}")
    print(f"     {len(live)} codes in force, {len(rows) - len(live)} superseded · "
          f"first seen {found['first_seen'][:10]} by {found['first_by']}"
          + ("" if found["live"] else "   ⚠ RETIRED by the publisher"))
    print("-" * 110)
    for r in rows:
        since = "the start " if r["valid_from"].startswith("1900") else r["valid_from"][:10]
        when = f"{since} → " + ("now       " if r["is_current"] else r["valid_to"][:10])
        mark = "  " if r["is_current"] else " ·"
        print(f"{mark}{r['code']:<8} {when}  {_wrap(r['description'], indent=36)}")
    if len(live) == len(rows):
        print("\n  nothing has changed since we first fetched this list")
    return 0


def cmd_mcp(_args: list[str]) -> int:
    from ukhrd import mcp_server
    mcp_server.main()
    return 0


COMMANDS = {"refresh": cmd_refresh, "load": cmd_load, "status": cmd_status, "lists": cmd_lists,
            "show": cmd_show, "lookup": cmd_lookup, "history": cmd_history, "changes": cmd_changes,
            "mcp": cmd_mcp}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
