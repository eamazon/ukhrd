/*  UKHRD → Snowflake, from the CSV store.  One table per reference list, plus the full history.
 *
 *  Same end result as load_ukhrd.sql — ukhrd_codes, ukhrd_lists and one table per list — but the source is
 *  the CSV files in the repository rather than the Parquet files on a release. Use this when bronze has to
 *  be the publisher's own text files, or when you want the whole change history behind them in git.
 *
 *  Contains information from NHS England, licensed under the current version of the Open Government
 *  Licence. Codes and descriptions are copied exactly as published in the NHS Data Model and Dictionary
 *  (https://www.datadictionary.nhs.uk/). UKHRD is independent and not endorsed by NHS England; the
 *  dictionary is the authority. Keep this credit with the data.
 *
 *  Part 1  put the CSV files in a stage
 *  Part 2  load lists.csv, and every code file, into one table per reference list
 *  Part 3  check what landed
 */

-- ── Part 1 · stage the files ─────────────────────────────────────────────────────────────────────
-- Download and unzip https://github.com/eamazon/ukhrd/archive/refs/heads/main.zip
-- The files you need are in ukhrd-main/data/ : lists.csv, and nhs_dd_cds/<list>.csv × 121.

CREATE SCHEMA IF NOT EXISTS ukhrd;
USE SCHEMA ukhrd;

CREATE OR REPLACE FILE FORMAT ukhrd_csv
    TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    EMPTY_FIELD_AS_NULL = TRUE TRIM_SPACE = FALSE;

CREATE OR REPLACE STAGE ukhrd_csv_stage
    FILE_FORMAT = ukhrd_csv
    DIRECTORY = (ENABLE = TRUE);       -- so Part 2 can list the files it has to load

-- Upload with SnowSQL (wildcards are allowed, AUTO_COMPRESS = FALSE keeps the names):
--   PUT file:///path/to/ukhrd-main/data/lists.csv              @ukhrd_csv_stage           AUTO_COMPRESS = FALSE;
--   PUT file:///path/to/ukhrd-main/data/nhs_dd_cds/*.csv       @ukhrd_csv_stage/codes/    AUTO_COMPRESS = FALSE;
-- or drag the files into the stage in Snowsight (Data » Databases » UKHRD » Stages » UKHRD_CSV_STAGE).

ALTER STAGE ukhrd_csv_stage REFRESH;   -- the directory table only sees files after a refresh
SELECT relative_path, size FROM DIRECTORY(@ukhrd_csv_stage) ORDER BY relative_path;   -- expect 122 files


-- ── Part 2 · load ────────────────────────────────────────────────────────────────────────────────
-- ⚠ Column ORDER matters here, not column names: every code file has the same twelve columns, and the
-- first one is named after its own list (admission_method_key, …), so the load is positional.

CREATE OR REPLACE TABLE ukhrd_lists (
    code_list_key       NUMBER,
    source_key          STRING,
    list_key            STRING,
    list_name           STRING,
    item_name           STRING,
    concept_name        STRING,
    superseded_by       STRING,
    source_page         STRING,
    data_sets           STRING,
    valid_from          TIMESTAMP_TZ,
    valid_to            TIMESTAMP_TZ,
    is_current          BOOLEAN,
    first_fetch_run_id  NUMBER,
    loaded_at           TIMESTAMP_TZ,
    loaded_by           STRING,
    updated_at          TIMESTAMP_TZ,
    updated_by          STRING
);

COPY INTO ukhrd_lists FROM (
    SELECT $1::NUMBER, $2::STRING, $3::STRING, $4::STRING, $5::STRING, $6::STRING, $7::STRING, $8::STRING,
           $9::STRING, $10::TIMESTAMP_TZ, $11::TIMESTAMP_TZ, $12::BOOLEAN, $13::NUMBER,
           $14::TIMESTAMP_TZ, $15::STRING, $16::TIMESTAMP_TZ, $17::STRING
      FROM @ukhrd_csv_stage/lists.csv
) FILE_FORMAT = (FORMAT_NAME = 'ukhrd_csv') ON_ERROR = ABORT_STATEMENT;

CREATE OR REPLACE TABLE ukhrd_codes (
    source_key          STRING,
    list_name           STRING,
    code_key            NUMBER,
    code_kind           STRING,
    code                STRING,
    description         STRING,
    valid_from          TIMESTAMP_TZ,
    valid_to            TIMESTAMP_TZ,
    is_current          BOOLEAN,
    first_fetch_run_id  NUMBER,
    loaded_at           TIMESTAMP_TZ,
    loaded_by           STRING,
    updated_at          TIMESTAMP_TZ,
    updated_by          STRING
);

-- One pass over the staged code files: stack them into ukhrd_codes, then cut one table per list.
EXECUTE IMMEDIATE $$
DECLARE
    files CURSOR FOR
        SELECT relative_path FROM DIRECTORY(@ukhrd_csv_stage)
         WHERE relative_path LIKE 'codes/%.csv' ORDER BY relative_path;
    made INTEGER DEFAULT 0;
BEGIN
    FOR one IN files DO
        LET path  STRING := one.relative_path;
        LET list_name STRING := REGEXP_REPLACE(path, '^codes/|\\.csv$', '');
        EXECUTE IMMEDIATE
            'INSERT INTO ukhrd_codes SELECT ''nhs_dd_cds'', ''' || list_name || ''', ' ||
            '$1::NUMBER, $2::STRING, $3::STRING, $4::STRING, $5::TIMESTAMP_TZ, $6::TIMESTAMP_TZ, ' ||
            '$7::BOOLEAN, $8::NUMBER, $9::TIMESTAMP_TZ, $10::STRING, $11::TIMESTAMP_TZ, $12::STRING ' ||
            'FROM @ukhrd_csv_stage/' || path || ' (FILE_FORMAT => ''ukhrd_csv'')';
        EXECUTE IMMEDIATE
            'CREATE OR REPLACE TABLE ukhrd_' || list_name || ' AS ' ||
            'SELECT code_kind, code, description FROM ukhrd_codes ' ||
            'WHERE is_current AND list_name = ''' || list_name || '''';
        made := made + 1;
    END FOR;
    RETURN made || ' reference tables built from CSV';
END;
$$;


-- ── Part 3 · check what landed ───────────────────────────────────────────────────────────────────
SELECT count(*) AS code_versions, count_if(is_current) AS in_force_today,
       count(DISTINCT list_name) AS lists FROM ukhrd_codes;          -- expect 1273 / 1273 / 121 today

SELECT * FROM ukhrd_admission_method ORDER BY code_kind DESC, code;  -- 20 national + 2 default today

SELECT item_name, source_page, data_sets FROM ukhrd_lists
 WHERE list_name = 'admission_method' AND is_current;

-- Grant it to whoever reads it
-- GRANT USAGE  ON SCHEMA ukhrd TO ROLE <your_reader_role>;
-- GRANT SELECT ON ALL TABLES IN SCHEMA ukhrd TO ROLE <your_reader_role>;
-- GRANT SELECT ON FUTURE TABLES IN SCHEMA ukhrd TO ROLE <your_reader_role>;
