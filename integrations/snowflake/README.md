# UKHRD in Snowflake

Build **one table per NHS reference list** — `ukhrd_admission_method`, `ukhrd_treatment_function_code`,
and 119 more — from two small Parquet files.

**You need:** a role that can create a schema, stage and tables, and a warehouse to run them.
**Time:** about ten minutes. Part 4 (daily refresh inside Snowflake) also needs `ACCOUNTADMIN` once.

The script is [`load_ukhrd.sql`](load_ukhrd.sql). Open it in a Snowsight worksheet and work down it.

## Steps

1. **Download the two files** from the [latest release](https://github.com/eamazon/ukhrd/releases/latest):
   `codes.parquet` and `lists.parquet`.
2. **Run Part 1 down to `CREATE OR REPLACE STAGE`.** That makes the `ukhrd` schema, a Parquet file format
   with `USE_LOGICAL_TYPE = TRUE` (without it Snowflake reads the timestamps as numbers) and a stage.
3. **Put the two files in the stage.** Either:
   - **Snowsight:** *Data → Databases → your database → `UKHRD` → Stages → `UKHRD_STAGE`*, then **+ Files**
     and upload both; or
   - **SnowSQL:**
     ```sql
     PUT file:///path/to/codes.parquet @ukhrd_stage AUTO_COMPRESS = FALSE;
     PUT file:///path/to/lists.parquet @ukhrd_stage AUTO_COMPRESS = FALSE;
     ```
     `AUTO_COMPRESS = FALSE` matters: otherwise the files arrive as `codes.parquet.gz` and the `COPY INTO`
     statements will not find them.
4. **Run the rest of Part 1** — the two `CREATE OR REPLACE TABLE` statements and the two `COPY INTO`
   statements. That fills `ukhrd_codes` (1,273 rows today) and `ukhrd_lists` (140 rows).
5. **Run Part 2**, the `EXECUTE IMMEDIATE $$ … $$` block. It loops over the lists and builds one table
   each. It returns `121 reference tables built`.
6. **Run Part 3** to check. Expect `1273 / 1273 / 121`, and `ukhrd_admission_method` with 20 national
   codes and 2 default codes.
7. **Let other people read it:**
   ```sql
   GRANT USAGE  ON SCHEMA ukhrd TO ROLE <your_reader_role>;
   GRANT SELECT ON ALL TABLES IN SCHEMA ukhrd TO ROLE <your_reader_role>;
   GRANT SELECT ON FUTURE TABLES IN SCHEMA ukhrd TO ROLE <your_reader_role>;
   ```
8. **Keeping it fresh.** Either repeat steps 1, 3 and 4–5 when a new release appears (UKHRD publishes only
   when NHS England changes something), or run **Part 4** once: it creates a network rule, an external
   access integration, a Python procedure that fetches the newest release itself, and a daily task.
   Set your warehouse name in the task, then `ALTER TASK ukhrd_refresh RESUME;` — tasks start suspended.

## Using it

```sql
SELECT s.*, a.description AS admission_method_name
FROM   my_spells s
LEFT JOIN ukhrd.ukhrd_admission_method a
       ON a.code = s.admission_method_code
      AND a.code_kind = 'national';
```

| you want | use |
|---|---|
| what a code means today | `ukhrd_<list>` — the small join tables |
| what it meant on the date of a record | `ukhrd_codes`, with `valid_from` / `valid_to` |
| the NHS page a list came from, and which CDS types use it | `ukhrd_lists` |

`code_kind` is `national` for a real code and `default` for the publisher's "not known / not applicable"
values (usually `98`, `99`). Real NHS files carry them, so drop them knowingly or not at all.

## If something goes wrong

| what you see | what to do |
|---|---|
| `Remote file 'codes.parquet' was not found` | The `PUT` compressed it. Re-upload with `AUTO_COMPRESS = FALSE`, or `LIST @ukhrd_stage;` to see the real names. |
| Timestamps arrive as large numbers | The file format lost `USE_LOGICAL_TYPE = TRUE`. Recreate it and re-run the `COPY INTO`. |
| `column ... does not exist` on `COPY INTO` | Keep `MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE`: the Parquet columns are lower case. |
| The scripting block errors on `DECLARE` | Run the whole `EXECUTE IMMEDIATE $$ … $$;` statement in one go, not line by line. |
| Part 4: `not authorized` on the network rule | Creating network rules and integrations needs `ACCOUNTADMIN`. Skip Part 4 and load by hand. |
| The task never runs | Tasks start suspended: `ALTER TASK ukhrd_refresh RESUME;` and check `SHOW TASKS`. |

## Where the data comes from

Contains information from NHS England, licensed under the current version of the
[Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Codes and descriptions are copied exactly as published in the
[NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/). UKHRD is independent and not
endorsed by NHS England; the dictionary is the authority. Keep this credit with the data — including in
anything you publish from it.

⚠ **Not yet run against a live Snowflake account.** The script follows Snowflake's documentation and its
per-list logic is tested in this repo. If a statement fails, please open an issue with the message.
