/*  UKHRD → Snowflake.  One table per reference list, plus the full history.
 *
 *  Contains information from NHS England, licensed under the current version of the Open Government
 *  Licence. Codes and descriptions are copied exactly as published in the NHS Data Model and Dictionary
 *  (https://www.datadictionary.nhs.uk/). UKHRD is independent and not endorsed by NHS England; the
 *  dictionary is the authority. Keep this credit with the data.
 *
 *  Part 1  load the two Parquet files      (by hand, or by the daily task in Part 4)
 *  Part 2  build one table per list        ukhrd_admission_method, ukhrd_treatment_function_code, …
 *  Part 3  check what landed
 *  Part 4  optional: let Snowflake fetch the newest release itself, every morning
 *
 *  Written from Snowflake's documentation and not yet run against a live account — tell us what breaks.
 */

-- ── Part 1 · load ────────────────────────────────────────────────────────────────────────────────
-- Download both files first:
--   https://github.com/eamazon/ukhrd/releases/latest/download/codes.parquet
--   https://github.com/eamazon/ukhrd/releases/latest/download/lists.parquet

CREATE SCHEMA IF NOT EXISTS ukhrd;
USE SCHEMA ukhrd;

CREATE OR REPLACE FILE FORMAT ukhrd_parquet TYPE = PARQUET USE_LOGICAL_TYPE = TRUE;
CREATE OR REPLACE STAGE ukhrd_stage FILE_FORMAT = ukhrd_parquet;

-- Put the two files in the stage: in Snowsight use Data » Add data » Load files into a stage, or run
-- this from SnowSQL (AUTO_COMPRESS = FALSE keeps the file names exactly as they are):
--   PUT file:///path/to/codes.parquet @ukhrd_stage AUTO_COMPRESS = FALSE;
--   PUT file:///path/to/lists.parquet @ukhrd_stage AUTO_COMPRESS = FALSE;

CREATE OR REPLACE TABLE ukhrd_codes (
    source_key          STRING,        -- which publication it came from
    list_name           STRING,        -- the reference list, and the table name below
    concept             STRING,        -- the NHS data element or attribute it describes
    code_key            NUMBER,        -- surrogate key, stable across rebuilds
    code_kind           STRING,        -- national | default
    code                STRING,
    description         STRING,
    valid_from          TIMESTAMP_TZ,  -- 1900-01-01 means "in force before UKHRD started watching"
    valid_to            TIMESTAMP_TZ,  -- NULL while current
    is_current          BOOLEAN,
    first_fetch_run_id  NUMBER,
    loaded_at           TIMESTAMP_TZ,
    loaded_by           STRING,
    updated_at          TIMESTAMP_TZ,
    updated_by          STRING
);

CREATE OR REPLACE TABLE ukhrd_lists (
    source_key          STRING,
    list_name           STRING,
    list_key            STRING,        -- the publisher's own identifier for the item
    item_name           STRING,
    concept_name        STRING,
    superseded_by       STRING,        -- where the page says it will be replaced; both stay live
    source_page         STRING,        -- the exact NHS page this list was copied from
    data_sets           STRING,        -- CDS record types that use it, separated by ";"
    valid_from          TIMESTAMP_TZ,
    valid_to            TIMESTAMP_TZ,
    is_current          BOOLEAN,
    first_fetch_run_id  NUMBER,
    loaded_at           TIMESTAMP_TZ,
    loaded_by           STRING,
    updated_at          TIMESTAMP_TZ,
    updated_by          STRING
);

COPY INTO ukhrd_codes FROM @ukhrd_stage FILES = ('codes.parquet')
     FILE_FORMAT = (FORMAT_NAME = 'ukhrd_parquet') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

COPY INTO ukhrd_lists FROM @ukhrd_stage FILES = ('lists.parquet')
     FILE_FORMAT = (FORMAT_NAME = 'ukhrd_parquet') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;


-- ── Part 2 · one table per reference list ────────────────────────────────────────────────────────
-- 121 tables of today's codes: ukhrd_admission_method, ukhrd_treatment_function_code, and the rest.
-- List names are lower-case letters, digits and underscores only, at most 59 characters.

EXECUTE IMMEDIATE $$
DECLARE
    lists CURSOR FOR SELECT DISTINCT list_name FROM ukhrd_codes WHERE is_current ORDER BY list_name;
    made  INTEGER DEFAULT 0;
BEGIN
    FOR one IN lists DO
        EXECUTE IMMEDIATE
            'CREATE OR REPLACE TABLE ukhrd_' || one.list_name || ' AS ' ||
            'SELECT code_kind, code, description FROM ukhrd_codes ' ||
            'WHERE is_current AND list_name = ''' || one.list_name || '''';
        made := made + 1;
    END FOR;
    RETURN made || ' reference tables built';
END;
$$;


-- ── Part 3 · check what landed ───────────────────────────────────────────────────────────────────
SELECT count(*) AS code_versions, count_if(is_current) AS in_force_today,
       count(DISTINCT list_name) AS lists FROM ukhrd_codes;               -- expect 1273 / 1273 / 121 today

SELECT * FROM ukhrd_admission_method ORDER BY code_kind DESC, code;

-- the NHS page behind a list, and the release it came from
SELECT item_name, source_page, data_sets FROM ukhrd_lists
 WHERE list_name = 'admission_method' AND is_current;

-- what a code meant on the date of a record (the reason the history is kept)
SELECT s.spell_id, s.admission_date, c.description
  FROM my_spells s
  LEFT JOIN ukhrd_codes c
         ON c.list_name = 'admission_method' AND c.code_kind = 'national'
        AND c.code = s.admission_method_code
        AND s.admission_date >= c.valid_from
        AND (c.valid_to IS NULL OR s.admission_date < c.valid_to);


-- ── Part 4 · optional: refresh it every morning, inside Snowflake ────────────────────────────────
-- Needs ACCOUNTADMIN to create the network rule and the integration. Without this, repeat Part 1 by
-- hand when a new release appears. UKHRD publishes a release only when NHS England changes something.

CREATE OR REPLACE NETWORK RULE ukhrd_github
    MODE = EGRESS TYPE = HOST_PORT
    VALUE_LIST = ('github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com');

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION ukhrd_github_access
    ALLOWED_NETWORK_RULES = (ukhrd_github) ENABLED = TRUE;

CREATE OR REPLACE PROCEDURE ukhrd_fetch()
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (ukhrd_github_access)
AS $$
import io
import requests

BASE = "https://github.com/eamazon/ukhrd/releases/latest/download/"

def run(session):
    got = []
    for name in ("codes.parquet", "lists.parquet"):
        body = requests.get(BASE + name, timeout=120).content
        session.file.put_stream(io.BytesIO(body), "@ukhrd_stage/" + name,
                                auto_compress=False, overwrite=True)
        got.append(f"{name} {len(body)} bytes")
    return "; ".join(got)
$$;

CREATE OR REPLACE TASK ukhrd_refresh
    WAREHOUSE = <your_warehouse>
    SCHEDULE = 'USING CRON 30 7 * * * UTC'      -- after UKHRD's own morning check
AS
BEGIN
    CALL ukhrd_fetch();
    TRUNCATE TABLE ukhrd_codes;
    TRUNCATE TABLE ukhrd_lists;
    COPY INTO ukhrd_codes FROM @ukhrd_stage FILES = ('codes.parquet')
         FILE_FORMAT = (FORMAT_NAME = 'ukhrd_parquet') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE FORCE = TRUE;
    COPY INTO ukhrd_lists FROM @ukhrd_stage FILES = ('lists.parquet')
         FILE_FORMAT = (FORMAT_NAME = 'ukhrd_parquet') MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE FORCE = TRUE;
END;

-- ALTER TASK ukhrd_refresh RESUME;   -- tasks start suspended
