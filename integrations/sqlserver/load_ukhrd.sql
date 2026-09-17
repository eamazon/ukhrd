/*  UKHRD → SQL Server.  One table per reference list, plus the full history.
 *
 *  Contains information from NHS England, licensed under the current version of the Open Government
 *  Licence. Codes and descriptions are copied exactly as published in the NHS Data Model and Dictionary
 *  (https://www.datadictionary.nhs.uk/). UKHRD is independent and not endorsed by NHS England; the
 *  dictionary is the authority. Keep this credit with the data.
 *
 *  SQL Server cannot read a file over https, and reading Parquet needs an external data source in Azure
 *  or S3 — so this uses the two CSV files from the release:
 *      https://github.com/eamazon/ukhrd/releases/latest/download/codes.csv
 *      https://github.com/eamazon/ukhrd/releases/latest/download/lists.csv
 *  Download them to a folder the SQL Server service account can read (a local path on the server, or a
 *  UNC share), and set @folder below.
 *
 *  Needs SQL Server 2017 or newer for FORMAT = 'CSV' with FIELDQUOTE. For Azure SQL Database, see the
 *  note at the end.
 *
 *  Part 1  land the two files as text
 *  Part 2  type them: ukhrd.codes and ukhrd.lists
 *  Part 3  one table per reference list
 *  Part 4  check what landed
 *
 *  Written from Microsoft's documentation and not yet run against a live SQL Server — tell us what breaks.
 */

SET NOCOUNT ON;
GO

IF SCHEMA_ID('ukhrd') IS NULL EXEC ('CREATE SCHEMA ukhrd');
GO

-- ── Part 1 · land the files as text ──────────────────────────────────────────────────────────────
-- Every column arrives as text; Part 2 does the converting, so a stray value never fails the load.

DROP TABLE IF EXISTS ukhrd.codes_raw;
CREATE TABLE ukhrd.codes_raw (
    source_key NVARCHAR(200), list_name NVARCHAR(200), concept NVARCHAR(400), code_key NVARCHAR(50),
    code_kind NVARCHAR(50), code NVARCHAR(100), description NVARCHAR(MAX), valid_from NVARCHAR(50),
    valid_to NVARCHAR(50), is_current NVARCHAR(10), first_fetch_run_id NVARCHAR(50),
    loaded_at NVARCHAR(50), loaded_by NVARCHAR(200), updated_at NVARCHAR(50), updated_by NVARCHAR(200)
);

DROP TABLE IF EXISTS ukhrd.lists_raw;
CREATE TABLE ukhrd.lists_raw (
    source_key NVARCHAR(200), list_name NVARCHAR(200), list_key NVARCHAR(400), item_name NVARCHAR(400),
    concept_name NVARCHAR(400), superseded_by NVARCHAR(400), source_page NVARCHAR(1000),
    data_sets NVARCHAR(MAX), valid_from NVARCHAR(50), valid_to NVARCHAR(50), is_current NVARCHAR(10),
    first_fetch_run_id NVARCHAR(50), loaded_at NVARCHAR(50), loaded_by NVARCHAR(200),
    updated_at NVARCHAR(50), updated_by NVARCHAR(200)
);

-- ⚠ Set this to the folder holding codes.csv and lists.csv. The files are UTF-8 and end lines with \n.
DECLARE @folder NVARCHAR(400) = N'C:\ukhrd\';
DECLARE @sql NVARCHAR(MAX);

SET @sql = N'
BULK INSERT ukhrd.codes_raw FROM ''' + @folder + N'codes.csv''
WITH (FORMAT = ''CSV'', FIRSTROW = 2, FIELDQUOTE = ''"'', FIELDTERMINATOR = '','',
      ROWTERMINATOR = ''0x0a'', CODEPAGE = ''65001'', TABLOCK);
BULK INSERT ukhrd.lists_raw FROM ''' + @folder + N'lists.csv''
WITH (FORMAT = ''CSV'', FIRSTROW = 2, FIELDQUOTE = ''"'', FIELDTERMINATOR = '','',
      ROWTERMINATOR = ''0x0a'', CODEPAGE = ''65001'', TABLOCK);';
EXEC sp_executesql @sql;
GO


-- ── Part 2 · type them ───────────────────────────────────────────────────────────────────────────
-- valid_from of 1900-01-01 means "in force before UKHRD started watching"; valid_to NULL means current.

DROP TABLE IF EXISTS ukhrd.codes;
SELECT
    source_key          = CAST(source_key AS NVARCHAR(200)),
    list_name           = CAST(list_name AS NVARCHAR(200)),
    concept             = CAST(concept AS NVARCHAR(400)),
    code_key            = TRY_CAST(code_key AS BIGINT),
    code_kind           = CAST(code_kind AS NVARCHAR(50)),
    code                = CAST(code AS NVARCHAR(100)),
    description         = description,
    valid_from          = TRY_CAST(valid_from AS DATETIMEOFFSET(6)),
    valid_to            = TRY_CAST(valid_to AS DATETIMEOFFSET(6)),
    is_current          = CAST(CASE is_current WHEN 'true' THEN 1 ELSE 0 END AS BIT),
    first_fetch_run_id  = TRY_CAST(first_fetch_run_id AS BIGINT),
    loaded_at           = TRY_CAST(loaded_at AS DATETIMEOFFSET(6)),
    loaded_by           = CAST(loaded_by AS NVARCHAR(200)),
    updated_at          = TRY_CAST(updated_at AS DATETIMEOFFSET(6)),
    updated_by          = CAST(updated_by AS NVARCHAR(200))
INTO ukhrd.codes
FROM ukhrd.codes_raw;

CREATE INDEX ix_ukhrd_codes_lookup ON ukhrd.codes (list_name, code_kind, code) INCLUDE (description);

DROP TABLE IF EXISTS ukhrd.lists;
SELECT
    source_key          = CAST(source_key AS NVARCHAR(200)),
    list_name           = CAST(list_name AS NVARCHAR(200)),
    list_key            = CAST(list_key AS NVARCHAR(400)),
    item_name           = CAST(item_name AS NVARCHAR(400)),
    concept_name        = CAST(concept_name AS NVARCHAR(400)),
    superseded_by       = CAST(superseded_by AS NVARCHAR(400)),
    source_page         = CAST(source_page AS NVARCHAR(1000)),
    data_sets           = data_sets,
    valid_from          = TRY_CAST(valid_from AS DATETIMEOFFSET(6)),
    valid_to            = TRY_CAST(valid_to AS DATETIMEOFFSET(6)),
    is_current          = CAST(CASE is_current WHEN 'true' THEN 1 ELSE 0 END AS BIT),
    first_fetch_run_id  = TRY_CAST(first_fetch_run_id AS BIGINT),
    loaded_at           = TRY_CAST(loaded_at AS DATETIMEOFFSET(6)),
    loaded_by           = CAST(loaded_by AS NVARCHAR(200)),
    updated_at          = TRY_CAST(updated_at AS DATETIMEOFFSET(6)),
    updated_by          = CAST(updated_by AS NVARCHAR(200))
INTO ukhrd.lists
FROM ukhrd.lists_raw;

DROP TABLE ukhrd.codes_raw;
DROP TABLE ukhrd.lists_raw;
GO


-- ── Part 3 · one table per reference list ────────────────────────────────────────────────────────
-- ukhrd.admission_method, ukhrd.treatment_function_code, and 119 more: today's codes only.
-- List names are lower-case letters, digits and underscores, at most 59 characters.

DECLARE @list SYSNAME, @sql NVARCHAR(MAX), @made INT = 0;
DECLARE lists CURSOR LOCAL FAST_FORWARD FOR
    SELECT DISTINCT list_name FROM ukhrd.codes WHERE is_current = 1 ORDER BY list_name;

OPEN lists;
FETCH NEXT FROM lists INTO @list;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'DROP TABLE IF EXISTS ukhrd.' + QUOTENAME(@list) + N';
                 SELECT code_kind, code, description INTO ukhrd.' + QUOTENAME(@list) + N'
                   FROM ukhrd.codes WHERE is_current = 1 AND list_name = @name;';
    EXEC sp_executesql @sql, N'@name SYSNAME', @name = @list;
    SET @made = @made + 1;
    FETCH NEXT FROM lists INTO @list;
END
CLOSE lists;
DEALLOCATE lists;
PRINT CAST(@made AS NVARCHAR(10)) + N' reference tables built';
GO


-- ── Part 4 · check what landed ───────────────────────────────────────────────────────────────────
SELECT code_versions = COUNT(*),
       in_force_today = SUM(CASE WHEN is_current = 1 THEN 1 ELSE 0 END),
       lists = COUNT(DISTINCT list_name)
  FROM ukhrd.codes;                                    -- expect 1273 / 1273 / 121 today

SELECT * FROM ukhrd.admission_method ORDER BY code_kind DESC, code;   -- 20 national + 2 default today

SELECT item_name, source_page, data_sets FROM ukhrd.lists
 WHERE list_name = 'admission_method' AND is_current = 1;

-- what a code meant on the date of a record — the reason the history is kept
SELECT s.spell_id, s.admission_date, c.description
  FROM dbo.my_spells s
  LEFT JOIN ukhrd.codes c
         ON c.list_name = 'admission_method' AND c.code_kind = 'national'
        AND c.code = s.admission_method_code
        AND s.admission_date >= c.valid_from
        AND (c.valid_to IS NULL OR s.admission_date < c.valid_to);

-- let other people read it
-- GRANT SELECT ON SCHEMA::ukhrd TO [your_reader_role];


/*  Azure SQL Database has no BULK INSERT from a local path. Put the two CSV files in Azure Blob Storage
 *  and read them from there instead of Part 1:
 *
 *    CREATE DATABASE SCOPED CREDENTIAL ukhrd_cred
 *        WITH IDENTITY = 'SHARED ACCESS SIGNATURE', SECRET = '<sas-token-without-leading-?>';
 *    CREATE EXTERNAL DATA SOURCE ukhrd_files
 *        WITH (TYPE = BLOB_STORAGE, LOCATION = 'https://<account>.blob.core.windows.net/<container>',
 *              CREDENTIAL = ukhrd_cred);
 *    BULK INSERT ukhrd.codes_raw FROM 'codes.csv'
 *        WITH (DATA_SOURCE = 'ukhrd_files', FORMAT = 'CSV', FIRSTROW = 2, FIELDQUOTE = '"',
 *              FIELDTERMINATOR = ',', ROWTERMINATOR = '0x0a', CODEPAGE = '65001');
 *
 *  Parts 2 to 4 are unchanged.
 */
