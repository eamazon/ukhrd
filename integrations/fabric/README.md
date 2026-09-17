# UKHRD in Microsoft Fabric

Build **one table per NHS reference list** in a Lakehouse — `ukhrd_admission_method`,
`ukhrd_treatment_function_code`, and 119 more — and keep them up to date on a schedule.

**You need:** a Fabric workspace, a Lakehouse, and permission to run and schedule notebooks.
**Time:** about ten minutes, plus a few minutes for the first run.

## Steps

1. **Get the notebook.** Download
   [`load_ukhrd.ipynb`](https://raw.githubusercontent.com/eamazon/ukhrd/main/integrations/fabric/load_ukhrd.ipynb)
   (right-click → Save link as).
2. **Create or open a Lakehouse.** In your workspace: **New item → Lakehouse**. A name like `ukhrd` keeps
   the reference data apart from your own tables.
3. **Import the notebook.** In the workspace: **New item → Import notebook → From this computer**, and
   pick the file you downloaded.
4. **Attach the Lakehouse.** Open the notebook, and in the **Explorer** panel on the left choose
   **Lakehouses → Add**, then select your Lakehouse. It must be the *default* one — the notebook writes to
   `/lakehouse/default/Files/`.
5. **Run all.** The first run downloads two small files, writes `ukhrd_codes` and `ukhrd_lists`, then
   writes one table per list. Expect a few minutes; later runs are quicker.
6. **Check what landed.** In the Lakehouse, refresh **Tables**. You should see `ukhrd_codes`,
   `ukhrd_lists` and 121 `ukhrd_…` tables. The last notebook cell displays `ukhrd_admission_method`
   (20 national codes and 2 default codes today).
7. **Schedule it.** In the notebook: **Run → Schedule → On**, repeat **daily**. Any time after **08:00
   UTC** is good: UKHRD checks the dictionary at 06:17 UTC and publishes only when NHS England changes
   something. Each run replaces the tables, so re-running is always safe.

## Using it

Through the Lakehouse's **SQL analytics endpoint**, a notebook, a Dataflow, or a Power BI semantic model:

```sql
SELECT s.*, a.description AS admission_method_name
FROM   my_spells s
LEFT JOIN ukhrd_admission_method a
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

**Point-in-time labelling**, the reason the history is kept:

```sql
SELECT s.*, c.description
FROM   my_spells s
LEFT JOIN ukhrd_codes c
       ON c.list_name = 'admission_method' AND c.code_kind = 'national'
      AND c.code = s.admission_method_code
      AND s.admission_date >= c.valid_from
      AND (c.valid_to IS NULL OR s.admission_date < c.valid_to);
```

## Other ways in, if a notebook does not fit your layers

The notebook does bronze and silver in one go: it lands the files and builds the tables. If you keep
those apart, any of these work — the files are ordinary Parquet over HTTPS.

| way | good for | what it cannot do |
|---|---|---|
| **Data pipeline → Copy activity**, source **HTTP** (`https://github.com/eamazon/ukhrd/releases/latest/download/codes.parquet`), sink **Lakehouse Files** | a no-code **bronze** landing, dated folders, retries and alerts built in | make the 121 per-list tables — follow it with this notebook, or a stored procedure |
| **Dataflow Gen2**, **Get data → Web**, then `Parquet.Document` | teams who prefer Power Query; lands `ukhrd_codes` / `ukhrd_lists` as Lakehouse tables | one query per list would mean 121 queries by hand |
| **OneLake shortcut** | zero-copy, no refresh job at all | shortcuts point at ADLS, S3, GCS or Dataverse — **not** GitHub. Only an option if you first mirror the files into your own storage |
| **This notebook** | one step from release to 121 tables, scheduled | nothing — but it is code, and it writes bronze and silver together |

**A medallion split that works:** a pipeline copies the two files into `Files/bronze/ukhrd/<date>/` each
morning, then runs this notebook with `DOWNLOAD = False` and `FOLDER` pointing at that bronze folder.
Bronze stays the untouched publisher file; silver is the 121 tables. Click by click:

### Pipeline for bronze, click by click

1. **New item → Data pipeline.** Name it `ukhrd bronze`.
2. **Copy data → Add to canvas.**
3. **Source tab → Connection → More → HTTP.** Base URL `https://github.com`, authentication **Anonymous**.
   Name it `github-ukhrd`.
4. Still on Source: **Relative URL**
   `/eamazon/ukhrd/releases/latest/download/codes.parquet`, **Method** `GET`, **File format** `Binary`
   (binary keeps the file byte for byte).
5. **Destination tab → Workspace → Lakehouse → your Lakehouse → Root folder `Files`.**
   **File path** `bronze/ukhrd/@{formatDateTime(utcNow(),'yyyy-MM-dd')}`, **File name** `codes.parquet`,
   **File format** `Binary`.
6. **Copy the activity and paste it.** In the copy, change both file names to `lists.parquet`.
7. **Run** the pipeline, then look in the Lakehouse under `Files/bronze/ukhrd/<today>/` — two files.
8. **Add the notebook.** Drag **Notebook** onto the canvas, connect it after the two copies (**On success**),
   and choose `load_ukhrd`. Under **Settings → Base parameters** add `DOWNLOAD` = `False` (type Boolean)
   and `FOLDER` = `bronze/ukhrd/<today's expression>` (type String). In the notebook, open the first code
   cell's **⋯ menu → Toggle parameter cell** once, so the pipeline's values replace those lines.
9. **Schedule** the pipeline: **Home → Schedule → On**, daily, any time after **08:00 UTC**.

If you would rather not use parameters, edit the first cell of the notebook by hand: set `DOWNLOAD = False`
and `FOLDER = "bronze/ukhrd/2026-09-17/"`.

## If you want the CSV files instead of Parquet

[`load_ukhrd_from_csv.ipynb`](load_ukhrd_from_csv.ipynb) builds exactly the same tables from the **CSV
store in the repository**: it downloads one zip of the repo, keeps the CSVs in `Files/bronze/ukhrd/<date>/`
untouched, and reads them from there. Import and run it the same way as the other notebook.

| | Parquet route (`load_ukhrd.ipynb`) | CSV route (`load_ukhrd_from_csv.ipynb`) |
|---|---|---|
| Source | two files on the latest release, about 40 KB | 122 CSV files from the repository, about 700 KB zipped |
| Types | real timestamps and booleans, already typed | text; the notebook converts `is_current`, dates stay ISO text |
| Bronze | the release file | the publisher's own CSV, the exact file git tracks |
| Waits for a release | yes — one is cut only when NHS England changes something | no — the CSVs change the moment a change is merged |
| Speed | seconds | a minute or two |

## If something goes wrong

| what you see | what to do |
|---|---|
| The download cell fails or times out | Your Spark session may have no route to the internet. Download `codes.parquet` and `lists.parquet` yourself from the [latest release](https://github.com/eamazon/ukhrd/releases/latest), upload them into the Lakehouse's **Files** as `ukhrd_codes.parquet` and `ukhrd_lists.parquet`, then run every cell except the first code cell. |
| `Path does not exist: Files/ukhrd_codes.parquet` | The notebook is not attached to a *default* Lakehouse. Redo step 4. |
| A table name clashes with one of yours | Change `PREFIX` in the first code cell, for example to `nhs_ref_`. |
| The first run is slow | Normal: 123 small tables are written. Later runs reuse the session. |

## Where the data comes from

Contains information from NHS England, licensed under the current version of the
[Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Codes and descriptions are copied exactly as published in the
[NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/). UKHRD is independent and not
endorsed by NHS England; the dictionary is the authority. Keep this credit with the data — including in
anything you publish from it.

⚠ **Not yet run against a live Fabric account.** The steps follow Microsoft's documentation and the
notebook's own logic is tested in this repo. If a screen differs, please open an issue saying what it said.
