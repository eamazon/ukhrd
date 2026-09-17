# UKHRD in SQL Server

Build **one table per NHS reference list** — `ukhrd.admission_method`, `ukhrd.treatment_function_code`,
and 119 more — from two CSV files.

**You need:** SQL Server 2017 or newer, a login that can create a schema and tables, and a folder the SQL
Server service account can read. **Time:** about ten minutes.

**Why CSV and not Parquet:** SQL Server cannot download a file from a web address, and reading Parquet
needs an external data source in Azure or S3. The CSV files on each release load with plain `BULK INSERT`,
which works on every edition, including Express and LocalDB.

The script is [`load_ukhrd.sql`](load_ukhrd.sql).

## Steps

1. **Download the two files** from the latest release, to a folder on the SQL Server machine (or a UNC
   share it can reach):
   - [`codes.csv`](https://github.com/eamazon/ukhrd/releases/latest/download/codes.csv) — every version of
     every code, all lists
   - [`lists.csv`](https://github.com/eamazon/ukhrd/releases/latest/download/lists.csv) — every version of
     every list's details, with its NHS page
2. **Open `load_ukhrd.sql`** in SQL Server Management Studio or Azure Data Studio, against the database
   that will hold the reference data.
3. **Set the folder.** In Part 1, change `DECLARE @folder NVARCHAR(400) = N'C:\ukhrd\';` to your folder.
   Keep the trailing backslash.
4. **Run Part 1.** It creates the `ukhrd` schema and lands both files as text. If it complains about
   access, the SQL Server *service account* cannot see the folder — not your own login.
5. **Run Part 2.** It converts the text into typed tables: `ukhrd.codes` (1,273 rows today) and
   `ukhrd.lists` (140 rows), with real `DATETIMEOFFSET` dates and a `BIT` for `is_current`, then drops the
   text tables and indexes the lookup.
6. **Run Part 3.** The cursor builds one table per list and prints `121 reference tables built`.
7. **Run Part 4** to check: expect `1273 / 1273 / 121`, and `ukhrd.admission_method` with 20 national and
   2 default codes.
8. **Grant it** to whoever reads it: `GRANT SELECT ON SCHEMA::ukhrd TO [your_reader_role];`
9. **Keep it fresh.** UKHRD publishes a release only when NHS England changes something. Either repeat
   steps 1 and 4–7 then, or schedule it: a SQL Agent job step that runs PowerShell to download both files,
   followed by a T-SQL step running Parts 1–3. Re-running always replaces the tables, so it is safe.

```powershell
# the download step, if you schedule it
$base = "https://github.com/eamazon/ukhrd/releases/latest/download/"
foreach ($f in "codes.csv", "lists.csv") { Invoke-WebRequest "$base$f" -OutFile "C:\ukhrd\$f" }
```

## Using it

```sql
SELECT s.*, a.description AS admission_method_name
FROM   dbo.my_spells s
LEFT JOIN ukhrd.admission_method a
       ON a.code = s.admission_method_code
      AND a.code_kind = 'national';
```

| you want | use |
|---|---|
| what a code means today | `ukhrd.<list>` — the small join tables |
| what it meant on the date of a record | `ukhrd.codes`, with `valid_from` / `valid_to` |
| the NHS page a list came from, and which CDS types use it | `ukhrd.lists` |

`code_kind` is `national` for a real code and `default` for the publisher's "not known / not applicable"
values (usually `98`, `99`). Real NHS files carry them, so drop them knowingly or not at all.

## If something goes wrong

| what you see | what to do |
|---|---|
| `Cannot bulk load because the file could not be opened` | The SQL Server service account cannot read the folder. Use a local path on the server, or grant that account read access to the share. |
| `Bulk load data conversion error` | Check `ROWTERMINATOR = '0x0a'` and `CODEPAGE = '65001'` — the files are UTF-8 with Unix line endings. |
| Descriptions arrive split across columns | `FIELDQUOTE = '"'` is missing, or the server is older than SQL Server 2017. On 2016 and earlier, load with a format file or use PowerShell `Import-Csv`. |
| Dates are `NULL` after Part 2 | `TRY_CAST` failed. Look at `ukhrd.codes_raw` before dropping it: the values should look like `2026-09-13T13:38:02.114233+00:00`. |
| Part 3 errors on a table name | A list name is not a plain identifier. `QUOTENAME` handles it, but tell us — list names are meant to be lower-case letters, digits and underscores. |
| Azure SQL Database: `BULK INSERT` refuses a local path | Use the blob-storage version at the end of the script. |

## Where the data comes from

Contains information from NHS England, licensed under the current version of the
[Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Codes and descriptions are copied exactly as published in the
[NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/). UKHRD is independent and not
endorsed by NHS England; the dictionary is the authority. Keep this credit with the data — including in
anything you publish from it.

⚠ **Not yet run against a live SQL Server.** The script follows Microsoft's documentation and its per-list
logic is tested in this repository. If a statement fails, please open an issue with the message.
