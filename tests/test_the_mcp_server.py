"""What the MCP server promises: it only reads, and the credit travels with every answer."""
from __future__ import annotations

import asyncio

import pytest

from test_the_store_refuses_a_bad_answer import SOURCE, demo, three_lists  # noqa: F401 — demo is the fixture
from ukhrd import mcp_server, store

TOOL_NAMES = {"search_lists", "lookup_code", "show_list", "code_meaning_on", "code_history", "about"}


def test_every_answer_carries_the_publishers_credit_and_where_it_came_from():
    store.refresh(SOURCE, read=lambda _url: three_lists())

    for answer in (mcp_server.lookup_code("0", "concept_0"), mcp_server.show_list("concept_0"),
                   mcp_server.code_meaning_on("concept_0", "0", "2024-03-31"),
                   mcp_server.search_lists("concept"), mcp_server.about(),
                   mcp_server.show_list("no_such_list")):
        assert answer["credit"] == ["Contains nothing from Nobody."]
        assert "not endorsed" in answer["note"]
    assert mcp_server.lookup_code("0", "concept_0")["matches"][0]["source_page"] == "https://example.invalid/list_0"
    assert mcp_server.code_meaning_on("concept_0", "0", "2024-03-31")["pages"] == ["https://example.invalid/list_0"]
    assert "2024-03-31" in mcp_server.code_meaning_on("concept_0", "0", "last March")["error"], \
        "a badly written day gets told what a day looks like, not a bare error"


def test_the_server_offers_only_read_only_tools_and_tells_the_assistant_to_credit():
    pytest.importorskip("mcp")
    server = mcp_server.build()

    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == TOOL_NAMES
    assert all(t.annotations.read_only_hint is True and t.annotations.destructive_hint is False for t in tools)
    assert "Contains nothing from Nobody." in server.instructions


def test_a_copy_from_github_is_fetched_once_a_day_and_a_bad_download_keeps_the_one_held(tmp_path):
    import os
    import time

    cache, calls = tmp_path / "cache" / "ukhrd.db", []

    def fetch(body):
        def answer(url):
            calls.append(url)
            if isinstance(body, Exception):
                raise body
            return body
        return answer

    with pytest.raises(OSError):
        mcp_server.latest_copy(cache, fetch=fetch(OSError("offline")))   # nothing held, nothing to fall back on

    mcp_server.latest_copy(cache, fetch=fetch(mcp_server.SQLITE + b"first"))
    mcp_server.latest_copy(cache, fetch=fetch(mcp_server.SQLITE + b"second"))
    assert cache.read_bytes().endswith(b"first") and len(calls) == 2, "a copy under a day old is not fetched again"

    two_days_ago = time.time() - 2 * 24 * 3600
    for bad in (b"<html>Not Found</html>", OSError("offline")):
        os.utime(cache, (two_days_ago, two_days_ago))
        mcp_server.latest_copy(cache, fetch=fetch(bad))
        assert cache.read_bytes().endswith(b"first"), "a failed or garbled download keeps the copy held"

    mcp_server.latest_copy(cache, fetch=fetch(mcp_server.SQLITE + b"newer"))
    assert cache.read_bytes().endswith(b"newer"), "a day-old copy is replaced"
    assert not list(cache.parent.glob("*.tmp"))
