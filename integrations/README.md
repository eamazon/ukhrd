# Loading UKHRD into a warehouse

Ready-to-run loaders. Each one builds **one table per reference list** — `ukhrd_admission_method`,
`ukhrd_treatment_function_code`, and 119 more — so a join names a table, never a filter on a list name.

| step-by-step guide | from the release's Parquet | from the repository's CSV |
|---|---|---|
| **[Microsoft Fabric](fabric/README.md)** | [`fabric/load_ukhrd.ipynb`](fabric/load_ukhrd.ipynb) | [`fabric/load_ukhrd_from_csv.ipynb`](fabric/load_ukhrd_from_csv.ipynb) |
| **[Snowflake](snowflake/README.md)** | [`snowflake/load_ukhrd.sql`](snowflake/load_ukhrd.sql) | [`snowflake/load_ukhrd_from_csv.sql`](snowflake/load_ukhrd_from_csv.sql) |

Both routes end with the same tables. **Parquet** is two small typed files from the latest release —
quickest, and what most people want. **CSV** is the publisher's own files, exactly as git tracks them, and
does not wait for a release to be cut. The Fabric guide also covers landing the files with a pipeline
(no code) and keeping bronze and silver apart.

Both read the same two files, and these links always point at the newest release:

```
https://github.com/eamazon/ukhrd/releases/latest/download/codes.parquet
https://github.com/eamazon/ukhrd/releases/latest/download/lists.parquet
```

## What you end up with

| table | rows | what it is |
|---|---|---|
| `ukhrd_<list>` × 121 | 2–186 | **the join tables.** Today's codes for one list: `code_kind`, `code`, `description` |
| `ukhrd_codes` | 1,273 | every version of every code, all lists, effective-dated — for "what did it mean then" |
| `ukhrd_lists` | 140 | every version of every list's details, with the NHS page it was copied from |

```sql
SELECT s.*, a.description AS admission_method_name
FROM   my_spells s
LEFT JOIN ukhrd_admission_method a
       ON a.code = s.admission_method_code
      AND a.code_kind = 'national';
```

`code_kind` is `national` for a real code and `default` for the publisher's "not known / not applicable"
values (usually `98`, `99`). Keep or drop them knowingly — real NHS files carry them.

For point-in-time labelling of historic records, and for the rest of the query recipes, see
[`../docs/QUERIES.md`](../docs/QUERIES.md).

## Where the data comes from

Contains information from NHS England, licensed under the current version of the
[Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Codes and descriptions are copied exactly as published in the
[NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/). UKHRD is independent and not
endorsed by NHS England; the dictionary is the authority. **Keep this credit with the data** — it travels
inside each Parquet file's metadata, and both loaders put it in a comment and in `ukhrd_lists`.

**Tried by us:** DuckDB, and DuckDB loading into Postgres. The Fabric and Snowflake scripts follow
Microsoft's and Snowflake's own documentation but have not been run against a live account. If a step
differs on your screen, open an issue saying what it said.
