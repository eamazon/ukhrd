"""UKHRD as an MCP server: what NHS codes mean, for any AI assistant that speaks MCP.

    python cli.py mcp          over stdio. Point an MCP client's config at that command.

⛔ READ-ONLY. It opens ukhrd.db read-only and never fetches. Refreshing is a person's job, on the command
line, where the diff is looked at before it is committed. If there is no database yet it is built from
data/ first, which is the same copy `cli.py load` makes.

⛔ THE CREDIT TRAVELS WITH THE ANSWER. Every result carries the publisher's attribution line word for
word, from data/sources.csv, and the page each list came from. NHS England's terms require the credit
wherever the data goes, and an assistant repeating an answer is the data going somewhere.

The tools are plain functions over ask.py, so they are tested without the MCP library installed.
"""
from __future__ import annotations

from ukhrd import ask, db, load

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


def main() -> None:
    if not db.path().exists():
        load.load()
    build().run(transport="stdio")
