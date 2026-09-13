# Querying it directly

Data from the [NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/). Contains information
from NHS England, licensed under the current version of the Open Government Licence. Codes and
descriptions are exactly as published; the dictionary is the authority. UKHRD is not endorsed by NHS
England.

The database is **one SQLite file, `ukhrd.db`**. Open it with anything that reads SQLite — the
`sqlite3` command, DBeaver, DuckDB, Python, R, Excel through ODBC.

```bash
sqlite3 ukhrd.db
```

No file yet? `python cli.py load` builds it from the files in `data/` in under a second, or download
`ukhrd.db` from the repo's latest GitHub release. Or skip the database entirely: every table below is a
plain CSV file in `data/`.

## The short version

**One real table per list, `dim_<list>`. A view of today's codes over each, `ref_<list>`.**

```sql
SELECT * FROM ref_admission_method;          -- what these codes mean TODAY
SELECT * FROM dim_admission_method;          -- every version, with the dates each was true
```

`ref_<list>` has three columns: `code_kind`, `code`, `description`. That is all most people need.
When you want to know what a code meant on a date, or when it changed, go to `dim_<list>`.

To see what lists exist:

```sql
SELECT DISTINCT list_name, concept, national_codes FROM ref_list_directory ORDER BY national_codes DESC;
```

## The three prefixes

| prefix | what lives there |
|---|---|
| `ref_` | **query this.** One view per list — today's codes — plus `ref_list_directory` and `ref_code` |
| `dim_` | one real table per list. Every version of every code, effective-dated. 121 of them |
| `meta_` | what we fetch, every fetch, and every version of every list's details |

```
meta_data_source        what we know how to fetch, and the credit it needs    data/sources.csv
meta_fetch_run          every attempt, whatever happened                       data/fetches.csv
meta_code_list          every version of every list's details                  data/lists.csv
meta_current_fetch      view: the newest good fetch per dataset
dim_<list_name>         TABLE: every version of every code                     data/<source>/<list_name>.csv
ref_<list_name>         view: the current rows of dim_<list_name>
ref_list_directory      view: every list today, one row per published item, with its page
ref_code                view: every current code, all lists together
```

⚠ **The file is replaced whole on every refresh.** Keep your own tables in a database of your own and
attach this one beside it — anything you add inside `ukhrd.db` is thrown away next time:

```sql
ATTACH 'ukhrd.db' AS ukhrd;
SELECT * FROM ukhrd.ref_admission_method;
```

## Every row says when and who

This is the part that makes it a reference store rather than a scraped copy.

| column | on | what it answers |
|---|---|---|
| `valid_from` / `valid_to` | dim tables, `meta_code_list` | the window this meaning was in force |
| `is_current` | dim tables, `meta_code_list` | is this the meaning today — `1` yes, `0` no |
| `loaded_at` / `loaded_by` | dim tables, `meta_code_list` | when we first saw this version, and who ran that fetch |
| `updated_at` / `updated_by` | dim tables, `meta_code_list` | when this version was closed off, and by whose fetch |
| `first_fetch_run_id` | dim tables, `meta_code_list` | the fetch that first saw this version |
| `<list_name>_key` | dim tables | the surrogate key. Stable across rebuilds — pin a fact table to it |

Timestamps are ISO 8601 text in UTC, like `2026-09-13T13:38:02.114233+00:00`. They sort and compare
correctly as text. **Compare a day against the first ten characters**, as the recipes below do —
`'2026-09-13T13:38' <= '2026-09-13'` is false as text, and that trips people up.

⚠ **`valid_from` is `1900-01-01` for every code in our first copy.** Those codes were already in force
before we started watching, and a 2024 NHS file needs an answer. When we actually first saw it is
`loaded_at`. Changes we saw later carry the date of the fetch that saw them — the true change happened
at or before that moment, never after.

"Last confirmed" is not a column: every current row was confirmed by the latest successful fetch.

```sql
SELECT f.started_at, f.loaded_by FROM meta_current_fetch c JOIN meta_fetch_run f USING (fetch_run_id);
```

`loaded_by` is `UKHRD_ACTOR` when it was set, otherwise the person logged in:

```bash
UKHRD_ACTOR="the nightly refresh" python cli.py refresh
```

## ⚠ `code_kind` — read this before joining

Every list carries two kinds of code side by side.

| `code_kind` | what it is |
|---|---|
| `national` | a real code. `21` = came in through A&E |
| `default` | the publisher's "not known / not applicable" values, usually `98` and `99` |

Both are there on purpose. Real NHS files carry `99`, and a lookup that quietly dropped it would fail
on exactly the rows that most need explaining. Filter if you want to, but filter knowingly:

```sql
SELECT * FROM ref_admission_method WHERE code_kind = 'national';
```

## Recipes

**What does one code mean**

```sql
SELECT description FROM ref_admission_method WHERE code = '21';
```

**What did it mean on a given day**

The whole reason the dimension tables exist.

```sql
SELECT code, description FROM dim_admission_source
 WHERE substr(valid_from, 1, 10) <= '2024-03-31'
   AND (valid_to IS NULL OR substr(valid_to, 1, 10) > '2024-03-31');
```

**Label a historic file with the meaning that applied at the time**

`admission_date` here is text like `2024-03-31`.

```sql
SELECT f.*, m.description
  FROM my_admissions f
  LEFT JOIN ukhrd.dim_admission_method m
         ON m.code = f.admission_method
        AND substr(m.valid_from, 1, 10) <= f.admission_date
        AND (m.valid_to IS NULL OR substr(m.valid_to, 1, 10) > f.admission_date);
```

**What has changed, and when**

```sql
SELECT code, description, valid_from, valid_to, updated_by
  FROM dim_admission_source WHERE is_current = 0 ORDER BY valid_to DESC;
```

**Join it to your own data**

Your file probably writes the code differently from the publisher. NHS RTT files write `C_100` where
the dictionary writes `100`. **We store what was published; you strip the prefix.** A store that
"helpfully" corrects its sources cannot be trusted as a reference.

```sql
SELECT f.trust_code, f.treatment_function_code, t.description
  FROM my_rtt_file f
  LEFT JOIN ukhrd.ref_treatment_function_code t
         ON t.code = replace(f.treatment_function_code, 'C_', '')
        AND t.code_kind = 'national';
```

**Where did this list come from**

Provenance is in the directory, not in the per-list views. One list can be printed by NHS more than
once under different item names, so a page column on the view would return a row per printing.

```sql
SELECT item_name, source_page, release_label, superseded_by, first_seen_at
  FROM ref_list_directory WHERE list_name = 'treatment_function_code';
```

**Lists the publisher is renaming**

Both names stay live, because older NHS data carries the old one.

```sql
SELECT DISTINCT concept, superseded_by FROM ref_list_directory
 WHERE superseded_by IS NOT NULL ORDER BY 1;
```

**Lists the publisher has stopped printing**

The table and its history stay; only the `ref_` view goes, so it cannot answer as if it were current.

```sql
SELECT list_name, max(valid_to) AS retired_at FROM meta_code_list
 GROUP BY list_name HAVING max(is_current) = 0;
```

**Is it fresh, and what changed**

```sql
SELECT started_at, outcome, loaded_by, release_label, value_count, is_changed, detail
  FROM meta_fetch_run ORDER BY fetch_run_id DESC LIMIT 10;
```

`outcome` is one of three, enforced by a constraint:

| | |
|---|---|
| `success` | it landed |
| `refused` | the answer was too thin to believe. Nothing changed, the old copy still answers |
| `failed` | could not read it, or could not save it. Again, nothing changed |

A refused or failed fetch can never become current, so a bad day at the publisher cannot corrupt you.

**Without a database at all**

The same history is in git. What the publisher changed between two commits:

```bash
git diff --stat HEAD~1 -- data/
git log -p -- data/nhs_dd_cds/admission_method.csv
```
