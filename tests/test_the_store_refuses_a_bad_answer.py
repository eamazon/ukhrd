"""What the store promises. Each test breaks the thing it guards and watches it hold.

The files and the database go to a temporary folder. They never touch data/ or ukhrd.db. Every
refresh ends by rebuilding the test database from the files.
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ukhrd import ask, db, files, load, store  # noqa: E402
from ukhrd.db import cursor  # noqa: E402

SOURCE = "demo"


def a_list(key: str, concept: str, codes: int, *, word: str = "meaning", defaults: int = 0) -> dict:
    return {
        "list_key": key, "item_name": concept.upper() + " (SOMEWHERE)", "concept_name": concept.upper(),
        "superseded_by": None, "source_page": f"https://example.invalid/{key}",
        "data_sets": ["cds_v6-3"],
        "values": [{"code_kind": "national", "code": str(i), "description": f"{word} {i}"}
                   for i in range(codes)]
                  + [{"code_kind": "default", "code": "99", "description": "Not known"}] * defaults,
    }


def fetched(lists: list[dict], release: str = "July 2026 release") -> dict:
    return {"release": release, "lists": lists}


def three_lists(codes_each: int = 20, *, word: str = "meaning") -> dict:
    return fetched([a_list(f"list_{i}", f"concept {i}", codes_each, word=word) for i in range(3)])


@pytest.fixture(autouse=True)
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("UKHRD_DATA", str(tmp_path))
    monkeypatch.setenv("UKHRD_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("UKHRD_ACTOR", raising=False)
    files.write_all({files.sources_path(): (files.SOURCE, [{
        "source_key": SOURCE, "label": "Demo", "publisher": "Nobody", "licence": "OGL v3.0",
        "attribution": "Contains nothing from Nobody.",
        "reader": "none", "url": "https://example.invalid/", "floor_value_count": "50",
        "cadence": "manual", "is_enabled": "true", "notes": None, "created_at": store.now()}])})
    load.load()
    return tmp_path


def held() -> list[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM ref_code WHERE source_key = ? ORDER BY list_name, code", (SOURCE,))
        return [dict(r) for r in cur.fetchall()]


def one(query: str, *args):
    with cursor() as cur:
        cur.execute(query, args)
        return cur.fetchone()


def write(query: str, *args) -> None:
    with cursor() as cur:
        cur.execute(query, args)


def csv_bytes() -> dict:
    return {p.name: p.read_bytes() for p in files.data().rglob("*.csv") if p.name != "fetches.csv"}


# ── landing ───────────────────────────────────────────────────────────────────────────────────────

def test_a_first_fetch_lands_in_the_files_and_the_database():
    entry = store.refresh(SOURCE, read=lambda _url: three_lists())

    assert entry["outcome"] == "success" and entry["database"] == "rebuilt"
    assert entry["release_label"] == "July 2026 release"
    assert len(held()) == 60
    assert len(files.read(files.codes_path(SOURCE, "concept_0"))) == 20


def test_the_release_is_a_fact_about_the_fetch_not_about_every_row():
    store.refresh(SOURCE, read=lambda _url: three_lists())

    row = one("SELECT count(*) AS n FROM sqlite_master t, pragma_table_info(t.name) c "
              "WHERE t.type = 'table' AND c.name LIKE 'release%' "
              "AND (t.name LIKE 'dim^_%' ESCAPE '^' OR t.name = 'meta_code_list')")
    assert row["n"] == 0, "release lives on the fetch, never repeated on every row"


# ── the floors ────────────────────────────────────────────────────────────────────────────────────

def test_a_short_answer_is_refused_and_the_old_copy_stands():
    store.refresh(SOURCE, read=lambda _url: three_lists())
    before = csv_bytes()

    entry = store.refresh(SOURCE, read=lambda _url: three_lists(1))    # a bad day at the publisher

    assert entry["outcome"] == "refused"
    assert "3" in entry["detail"] and "50" in entry["detail"]
    assert len(held()) == 60, "the previous copy must still answer"
    assert csv_bytes() == before, "and no file but the log may change"


def test_a_vanished_list_is_refused_even_when_the_total_looks_fine():
    """The floor a TOTAL cannot see: 60 codes in, 60 back, but one whole list is gone."""
    store.refresh(SOURCE, read=lambda _url: three_lists(20))

    entry = store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list("list_0", "concept 0", 30), a_list("list_1", "concept 1", 30)]))

    assert entry["outcome"] == "refused"
    assert "list_2" in entry["detail"]
    assert {r["list_name"] for r in held()} == {"concept_0", "concept_1", "concept_2"}


def test_an_outage_is_recorded_not_raised():
    def boom(_url):
        raise ConnectionError("nhs is down")

    entry = store.refresh(SOURCE, read=boom)

    assert entry["outcome"] == "failed"
    assert "nhs is down" in entry["detail"]
    assert one("SELECT outcome FROM meta_fetch_run")["outcome"] == "failed", "and it is in the log"


def test_a_failure_while_saving_leaves_no_success_and_no_changed_file(monkeypatch):
    store.refresh(SOURCE, read=lambda _url: three_lists())
    before = csv_bytes()
    real, calls = files.write_all, []

    def disk_full_once(batch):
        if not calls:
            calls.append(1)
            raise OSError("disk full")
        return real(batch)

    monkeypatch.setattr(files, "write_all", disk_full_once)
    entry = store.refresh(SOURCE, read=lambda _url: three_lists(30))

    assert entry["outcome"] == "failed" and "disk full" in entry["detail"]
    assert csv_bytes() == before, "a save that did not happen must not have changed a file"
    assert len(held()) == 60, "the previous copy must still answer"
    assert one("SELECT count(*) AS n FROM meta_fetch_run WHERE outcome = 'success'")["n"] == 1


def test_a_batch_that_fails_part_way_swaps_nothing_in(tmp_path):
    """The files are the store, so half a write is the thing that must never happen."""
    good, blocked = tmp_path / "good.csv", tmp_path / "not_a_folder"
    files.write_all({good: (("a",), [{"a": "old"}])})
    blocked.write_text("a file, so nothing can be written inside it")

    with pytest.raises(OSError):
        files.write_all({good: (("a",), [{"a": "new"}]), blocked / "x.csv": (("a",), [{"a": "x"}])})

    assert files.read(good) == [{"a": "old"}]
    assert not list(tmp_path.glob("*.tmp")), "and no half-written file is left behind"


def test_the_database_refuses_an_unknown_outcome():
    """The controlled vocabulary is a constraint, not a convention."""
    with pytest.raises(sqlite3.IntegrityError, match="ck_fetch_run_outcome"):
        write("INSERT INTO meta_fetch_run (fetch_run_id, source_key, started_at, finished_at, outcome, "
              "detail, loaded_by, host) VALUES (99, ?, '2026', '2026', 'probably fine', 'x', 'x', 'x')", SOURCE)


def test_the_database_refuses_a_success_that_says_nothing():
    """A success must carry its release, its count, its hash. Half a record is worse than none."""
    with pytest.raises(sqlite3.IntegrityError, match="ck_fetch_run_success_is_complete"):
        write("INSERT INTO meta_fetch_run (fetch_run_id, source_key, started_at, finished_at, outcome, "
              "detail, loaded_by, host) VALUES (99, ?, '2026', '2026', 'success', 'landed', 'x', 'x')", SOURCE)


# ── the database is a copy ────────────────────────────────────────────────────────────────────────

def test_the_database_can_be_thrown_away_and_rebuilt_from_the_files_alone():
    store.refresh(SOURCE, read=lambda _url: three_lists(word="old"))
    store.refresh(SOURCE, read=lambda _url: three_lists(word="new"))
    snapshot = "SELECT * FROM dim_concept_0 ORDER BY concept_0_key"
    with cursor() as cur:
        cur.execute(snapshot)
        before = [tuple(r) for r in cur.fetchall()]
    db.path().unlink()

    load.load()

    with cursor() as cur:
        cur.execute(snapshot)
        assert [tuple(r) for r in cur.fetchall()] == before, "every version, every key and date must come back"


def test_a_file_whose_columns_have_drifted_is_refused_and_the_old_database_still_answers():
    """A rebuild is built aside and swapped in whole, so a bad file can never leave half a database."""
    store.refresh(SOURCE, read=lambda _url: three_lists())
    path = files.codes_path(SOURCE, "concept_0")
    path.write_text(path.read_text().replace("description", "meaning", 1))

    with pytest.raises(ValueError, match="does not have the columns"):
        load.load()

    assert len(held()) == 60, "the old database must still answer"
    assert not list(db.path().parent.glob("*.db.tmp")), "and no half-built database is left behind"


def test_the_database_is_opened_read_only_for_every_question():
    """The MCP server hands questions from an AI to this code. Nothing it asks may change the copy."""
    store.refresh(SOURCE, read=lambda _url: three_lists())
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with cursor(read_only=True) as cur:
            cur.execute("DELETE FROM meta_code_list")


def test_a_code_answers_for_the_day_asked_about_even_after_it_was_withdrawn():
    store.refresh(SOURCE, read=lambda _url: three_lists(20, word="old"))
    later = store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list(f"list_{i}", f"concept {i}", 19, word="new") for i in range(3)]))   # 19 withdrawn
    today = later["started_at"][:10]

    assert [r["description"] for r in ask.meaning_on("ref_concept_0", "19", "2024-03-31")["rows"]] == ["old 19"]
    assert ask.meaning_on("concept_0", "19", today)["rows"] == [], "gone from the day it was withdrawn"
    assert [r["description"] for r in ask.meaning_on("concept_0", "0", today)["rows"]] == ["new 0"]
    assert ask.meaning_on("concept_0", "0", today)["pages"] == ["https://example.invalid/list_0"]
    with pytest.raises(ValueError):
        ask.meaning_on("concept_0", "0", "last March")


def test_a_rebuild_keeps_the_date_of_the_fetch_not_the_date_of_the_rebuild():
    """⛔ An audit date must be the date of the event, not of the code run. Caught twice already."""
    entry = store.refresh(SOURCE, read=lambda _url: three_lists())
    load.load()

    for table in ("dim_concept_0", "meta_code_list"):
        row = one(f"SELECT min(loaded_at = ?) AS same FROM {table}", entry["started_at"])
        assert row["same"] == 1, f"{table} says it was loaded when the database was rebuilt"


# ── history ───────────────────────────────────────────────────────────────────────────────────────

def test_a_reworded_code_keeps_BOTH_meanings_with_the_dates_each_was_true():
    """What a code meant last March. The whole reason a dimension table exists."""
    store.refresh(SOURCE, read=lambda _url: three_lists(word="old"))
    store.refresh(SOURCE, read=lambda _url: three_lists(word="new"))

    with cursor() as cur:
        cur.execute("SELECT description, valid_from, valid_to, is_current FROM dim_concept_0 "
                    "WHERE code = '0' ORDER BY valid_from")
        was, now = [dict(r) for r in cur.fetchall()]

    assert was["description"] == "old 0" and not was["is_current"] and was["valid_to"] is not None
    assert now["description"] == "new 0" and now["is_current"] and now["valid_to"] is None
    assert was["valid_to"] == now["valid_from"], "no gap and no overlap between the two"
    assert len(held()) == 60 and all(r["description"].startswith("new") for r in held())


def test_a_first_copy_answers_for_dates_before_we_started_watching():
    """NHS files from 2024 carry these codes. A first row dated today would answer them with nothing."""
    store.refresh(SOURCE, read=lambda _url: three_lists(word="old"))
    store.refresh(SOURCE, read=lambda _url: three_lists(word="new"))

    row = one("SELECT description FROM dim_concept_0 WHERE code = '0' "
              "AND valid_from <= '2024-03-31' AND (valid_to IS NULL OR valid_to > '2024-03-31')")
    assert row["description"] == "old 0"


def test_the_change_is_described_in_words():
    store.refresh(SOURCE, read=lambda _url: three_lists())
    changed = three_lists()
    changed["lists"][0]["values"][0]["description"] = "reworded entirely"

    entry = store.refresh(SOURCE, read=lambda _url: changed)

    assert "1 reworded" in entry["detail"] and "concept_0" in entry["detail"], entry["detail"]


def test_an_identical_refetch_says_so_and_changes_no_file_but_the_log():
    """So `git diff` on data/ shows what the PUBLISHER changed, and nothing else."""
    store.refresh(SOURCE, read=lambda _url: three_lists())
    before = csv_bytes()

    entry = store.refresh(SOURCE, read=lambda _url: three_lists())

    assert entry["is_changed"] == "false"
    assert "no code or meaning changed" in entry["detail"]
    assert csv_bytes() == before


def test_a_change_to_one_code_leaves_every_other_row_in_its_file_exactly_as_it_was():
    """A changed list rewrites its whole file. The 19 codes that did not move must come back byte for
    byte — not restamped with the new fetch's date, not renumbered, not reordered."""
    store.refresh(SOURCE, read=lambda _url: three_lists())
    before = [r for r in files.read(files.codes_path(SOURCE, "concept_0")) if r["code"] != "0"]
    changed = three_lists()
    changed["lists"][0]["values"][0]["description"] = "reworded entirely"

    store.refresh(SOURCE, read=lambda _url: changed)

    after = [r for r in files.read(files.codes_path(SOURCE, "concept_0")) if r["code"] != "0"]
    assert after == before


def test_a_code_that_stops_being_published_is_closed_not_deleted():
    """The dictionary only ever shows CURRENT codes, so our closed row is the only record it existed."""
    store.refresh(SOURCE, read=lambda _url: three_lists(20))
    store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list(f"list_{i}", f"concept {i}", 19) for i in range(3)]))   # code '19' withdrawn

    row = one("SELECT is_current, valid_to, updated_by FROM dim_concept_0 WHERE code = '19'")
    assert row is not None, "a withdrawn code must still be findable"
    assert row["is_current"] == 0 and row["valid_to"] is not None and row["updated_by"]
    assert one("SELECT count(*) AS n FROM ref_concept_0 WHERE code = '19'")["n"] == 0


def test_an_unchanged_code_stays_one_row_and_remembers_the_fetch_that_first_saw_it():
    first = store.refresh(SOURCE, read=lambda _url: three_lists())
    store.refresh(SOURCE, read=lambda _url: three_lists())

    assert one("SELECT count(*) AS n FROM dim_concept_0")["n"] == 20
    row = one("SELECT first_fetch_run_id FROM dim_concept_0 WHERE code = '0'")
    assert str(row["first_fetch_run_id"]) == first["fetch_run_id"]


def test_the_dimension_refuses_a_row_that_ends_before_it_begins():
    store.refresh(SOURCE, read=lambda _url: three_lists())
    with pytest.raises(sqlite3.IntegrityError, match="ck_valid_span"):
        write("UPDATE dim_concept_0 SET valid_to = '1800-01-01', is_current = 0, "
              "updated_at = '2026', updated_by = 'x' WHERE code = '0'")


def test_a_row_still_in_force_cannot_carry_an_end_date():
    """is_current and valid_to are two ways of saying one thing. They are not allowed to disagree."""
    store.refresh(SOURCE, read=lambda _url: three_lists())
    with pytest.raises(sqlite3.IntegrityError, match="ck_open_means_current"):
        write("UPDATE dim_concept_0 SET valid_to = '2999-01-01' WHERE code = '0'")


def test_a_fetch_cannot_be_deleted_while_a_row_still_cites_it():
    """Lineage that a tidy-up can quietly erase is not lineage."""
    run = store.refresh(SOURCE, read=lambda _url: three_lists())
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        write("DELETE FROM meta_fetch_run WHERE fetch_run_id = ?", int(run["fetch_run_id"]))


# ── the reference layer ───────────────────────────────────────────────────────────────────────────

def test_every_list_gets_a_REAL_TABLE_named_after_it_and_a_view_of_today():
    store.refresh(SOURCE, read=lambda _url: three_lists())

    assert one("SELECT count(*) AS n FROM ref_concept_0")["n"] == 20
    assert one("SELECT type FROM sqlite_master WHERE name = 'dim_concept_0'")["type"] == "table"
    assert one("SELECT count(*) AS n FROM sqlite_master WHERE type = 'table' "
               "AND name LIKE 'dim^_%' ESCAPE '^'")["n"] == 3


def test_one_list_published_three_times_becomes_ONE_list():
    """Identical codes under one concept are one list printed three times, not _1 _2 _3."""
    store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list(f"printing_{i}", "one true concept", 20) for i in range(3)]))

    row = one("SELECT count(DISTINCT list_name) AS names, count(*) AS items FROM ref_list_directory")
    assert (row["names"], row["items"]) == (1, 3), "three printings, one list, all three pages kept"
    assert one("SELECT count(*) AS n FROM ref_one_true_concept")["n"] == 20, "not each code three times"


def test_two_lists_sharing_a_name_but_not_their_codes_stay_apart():
    store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list("item_a", "shared concept", 20), a_list("item_b", "shared concept", 30)]))

    assert one("SELECT count(DISTINCT list_name) AS n FROM ref_list_directory")["n"] == 2


def test_two_concepts_cut_to_the_same_name_are_numbered_not_merged():
    """A name is cut at 59 characters. Different lists must not quietly share one table."""
    long = "a remarkably long concept name that keeps going well past the limit "
    store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list("item_a", long + "one", 30), a_list("item_b", long + "two", 30)]))

    with cursor() as cur:
        cur.execute("SELECT DISTINCT list_name FROM ref_list_directory ORDER BY 1")
        names = [r["list_name"] for r in cur.fetchall()]
    assert len(names) == 2 and names[0].endswith("_1") and names[1].endswith("_2")
    assert all(len(n) <= 59 for n in names), "every name is cut at the same place"


def test_default_codes_are_exposed_and_labelled_not_dropped():
    """Real NHS files carry 99. A lookup that omits it fails on the rows that most need a label."""
    store.refresh(SOURCE, read=lambda _url: fetched(
        [a_list(f"list_{i}", f"concept {i}", 20, defaults=1) for i in range(3)]))

    row = one("SELECT code_kind, description FROM ref_concept_0 WHERE code = '99'")
    assert (row["code_kind"], row["description"]) == ("default", "Not known")


def test_a_view_carries_no_page_column_so_a_merge_cannot_multiply_rows():
    store.refresh(SOURCE, read=lambda _url: three_lists())

    with cursor() as cur:
        cur.execute("SELECT name FROM pragma_table_info('ref_concept_0')")
        assert {r["name"] for r in cur.fetchall()} == {"code_kind", "code", "description"}


# ── status and the audit trail ────────────────────────────────────────────────────────────────────

def test_status_reports_what_we_still_hold_after_a_refusal():
    store.refresh(SOURCE, read=lambda _url: three_lists())
    store.refresh(SOURCE, read=lambda _url: three_lists(1))          # refused

    row = [s for s in ask.status() if s["source_key"] == SOURCE][0]
    assert row["outcome"] == "refused"
    assert row["codes_held"] == 60, "saying 'holding 0' while 60 codes answer is a lie"
    assert row["lists_held"] == 3


def test_a_dataset_never_fetched_says_so_instead_of_vanishing():
    row = [s for s in ask.status() if s["source_key"] == SOURCE][0]
    assert row["outcome"] is None and row["codes_held"] == 0


def test_every_row_says_when_it_landed_and_who_loaded_it():
    store.refresh(SOURCE, read=lambda _url: three_lists())

    for table in ("meta_fetch_run", "meta_code_list", "dim_concept_0"):
        assert one(f"SELECT count(*) AS n FROM {table} WHERE loaded_by IS NULL")["n"] == 0
    for table in ("meta_code_list", "dim_concept_0"):
        assert one(f"SELECT count(*) AS n FROM {table} WHERE loaded_at IS NULL")["n"] == 0


def test_the_loader_can_be_named_and_every_row_carries_the_name(monkeypatch):
    """On a shared box "who" must mean a person or a job, not whichever login happened to connect."""
    monkeypatch.setenv("UKHRD_ACTOR", "the nightly refresh")
    store.refresh(SOURCE, read=lambda _url: three_lists())

    for table in ("meta_fetch_run", "meta_code_list", "dim_concept_0"):
        row = one(f"SELECT group_concat(DISTINCT loaded_by) AS who FROM {table}")
        assert row["who"] == "the nightly refresh", table


def test_an_unreadable_release_stops_everything():
    """A row that cannot say which edition it came from is a rumour."""
    from ukhrd.readers import nhs_dd

    assert nhs_dd._release("<p>July 2026 release</p>") == "July 2026 release"
    with pytest.raises(ValueError, match="could not read which release"):
        nhs_dd._release("<p>the front page has been redesigned</p>")
