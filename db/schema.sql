-- The fixed shape of the database. Run by `python cli.py load`, never by hand.
--
-- ⭐ THE DATABASE IS A COPY. The truth is the CSV files in data/. `load` builds a fresh SQLite file from
-- them and swaps it in over the old one, so it can be thrown away and rebuilt at any time, and anyone
-- reading sees the old copy or the new one, never half of each. To change the shape, edit this file and
-- run `load`. There are no migrations, because there is nothing here to migrate.
--
-- SQLite has no schemas, so a name's prefix says what it is for:
--   meta_   what we fetch, every fetch, every version of every list's details
--   dim_    one TABLE per code list, slowly-changing Type 2 — made by load.py, because which lists
--           exist is decided by the publisher, not written in advance
--   ref_    what people query: a view of today's codes per list, plus ref_list_directory and ref_code
--
-- House style: snake_case singular names · constraints pk_ fk_ uq_ ck_, indexes ix_ · STRICT tables ·
-- timestamps are ISO 8601 UTC text, which sorts and compares correctly as text · booleans are 0 / 1 ·
-- a controlled vocabulary is a CHECK · a comment on anything that is not self-evident.
-- ⚠ Keys come from the files, never from AUTOINCREMENT, so every rebuild gives every row the same key
-- and a fact table pinned to one stays pinned.


-- ── what we know how to fetch ────────────────────────────────────────────────────────────────────
-- One row per PUBLICATION, not per list. From data/sources.csv. Adding a dataset whose shape we
-- already read is one row in that file and no code at all.

CREATE TABLE meta_data_source (
    source_key        TEXT    NOT NULL,
    label             TEXT    NOT NULL,
    publisher         TEXT    NOT NULL,
    licence           TEXT    NOT NULL,
    attribution       TEXT    NOT NULL,  -- the credit line the publisher's terms require, word for word
    reader            TEXT    NOT NULL,  -- which reader handles this SHAPE of publication
    url               TEXT    NOT NULL,
    floor_value_count INTEGER NOT NULL,  -- fewer codes than this and a fetch is REFUSED, not applied
    cadence           TEXT    NOT NULL,
    is_enabled        INTEGER NOT NULL,
    notes             TEXT,
    created_at        TEXT    NOT NULL,

    CONSTRAINT pk_data_source         PRIMARY KEY (source_key),
    CONSTRAINT ck_data_source_key     CHECK (source_key GLOB '[a-z]*' AND source_key NOT GLOB '*[^a-z0-9_]*'),
    CONSTRAINT ck_data_source_floor   CHECK (floor_value_count > 0),
    CONSTRAINT ck_data_source_cadence CHECK (cadence IN ('manual', 'daily', 'weekly')),
    CONSTRAINT ck_data_source_enabled CHECK (is_enabled IN (0, 1)),
    CONSTRAINT ck_data_source_url     CHECK (url LIKE 'http://%' OR url LIKE 'https://%'),
    CONSTRAINT ck_data_source_credit  CHECK (length(attribution) > 0)
) STRICT;


-- ── what happened, every time ────────────────────────────────────────────────────────────────────
-- From data/fetches.csv. A refusal and a failure get a row too: "we did not apply it" is the fact
-- somebody needs, and silence reads as success.

CREATE TABLE meta_fetch_run (
    fetch_run_id  INTEGER NOT NULL,
    source_key    TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,
    finished_at   TEXT    NOT NULL,
    outcome       TEXT    NOT NULL,  -- success · refused (too thin to believe) · failed (could not read or save)
    release_label TEXT,              -- the publisher's own name for the edition, e.g. "July 2026 release"
    value_count   INTEGER,
    content_hash  TEXT,
    is_changed    INTEGER,           -- did this fetch open or close any version of any code or list
    detail        TEXT    NOT NULL,  -- a sentence a person can read
    loaded_by     TEXT    NOT NULL,  -- UKHRD_ACTOR when set, otherwise the person logged in
    host          TEXT    NOT NULL,

    CONSTRAINT pk_fetch_run         PRIMARY KEY (fetch_run_id),
    CONSTRAINT fk_fetch_run_source  FOREIGN KEY (source_key) REFERENCES meta_data_source (source_key),
    CONSTRAINT ck_fetch_run_outcome CHECK (outcome IN ('success', 'refused', 'failed')),
    CONSTRAINT ck_fetch_run_counts  CHECK (value_count IS NULL OR value_count >= 0),
    CONSTRAINT ck_fetch_run_order   CHECK (finished_at >= started_at),
    CONSTRAINT ck_fetch_run_detail  CHECK (length(detail) > 0),
    CONSTRAINT ck_fetch_run_changed CHECK (is_changed IS NULL OR is_changed IN (0, 1)),
    CONSTRAINT ck_fetch_run_hash    CHECK (content_hash IS NULL
                                           OR (length(content_hash) = 64 AND content_hash NOT GLOB '*[^0-9a-f]*')),
    -- a success must say what it holds and what it is; half a record is worse than none
    CONSTRAINT ck_fetch_run_success_is_complete
        CHECK (outcome <> 'success'
               OR (value_count IS NOT NULL AND content_hash IS NOT NULL
                   AND is_changed IS NOT NULL AND release_label IS NOT NULL))
) STRICT;

CREATE INDEX ix_fetch_run_source_recent ON meta_fetch_run (source_key, fetch_run_id DESC);


-- ── every version of every published list's details ──────────────────────────────────────────────
-- From data/lists.csv. Its codes are in dim_<list_name>; for today's lists read ref_list_directory.
-- valid_from of 1900-01-01 means "already in force when we started watching"; when we first saw a
-- version is loaded_at.

CREATE TABLE meta_code_list (
    code_list_key      INTEGER NOT NULL,
    source_key         TEXT    NOT NULL,
    list_key           TEXT    NOT NULL,  -- the publisher's own identifier for the item
    list_name          TEXT    NOT NULL,  -- the table its codes live in; several printings share one
    item_name          TEXT    NOT NULL,
    concept_name       TEXT,              -- the underlying thing, e.g. "ADMISSION METHOD"
    superseded_by      TEXT,              -- where the page says "will be replaced with X"; both stay live
    source_page        TEXT    NOT NULL,
    data_sets          TEXT,              -- which collections use it, separated by ";"
    valid_from         TEXT    NOT NULL,
    valid_to           TEXT,
    is_current         INTEGER NOT NULL,
    first_fetch_run_id INTEGER NOT NULL,
    loaded_at          TEXT    NOT NULL,
    loaded_by          TEXT    NOT NULL,
    updated_at         TEXT,
    updated_by         TEXT,

    CONSTRAINT pk_code_list             PRIMARY KEY (code_list_key),
    CONSTRAINT fk_code_list_source      FOREIGN KEY (source_key) REFERENCES meta_data_source (source_key),
    CONSTRAINT fk_code_list_first_fetch FOREIGN KEY (first_fetch_run_id) REFERENCES meta_fetch_run (fetch_run_id),
    CONSTRAINT ck_code_list_page        CHECK (source_page LIKE 'http://%' OR source_page LIKE 'https://%'),
    CONSTRAINT ck_code_list_is_current  CHECK (is_current IN (0, 1)),
    CONSTRAINT ck_code_list_valid_span  CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_code_list_open_means_current CHECK (is_current = (valid_to IS NULL)),
    CONSTRAINT ck_code_list_closed_says_who
        CHECK (is_current = 1 OR (updated_at IS NOT NULL AND updated_by IS NOT NULL))
) STRICT;

CREATE UNIQUE INDEX ix_code_list_current ON meta_code_list (source_key, list_key) WHERE is_current = 1;
CREATE INDEX ix_code_list_name ON meta_code_list (list_name);
