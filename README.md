# UKHRD — UK Health Reference Data

**Reference data for the NHS Commissioning Data Sets: the National Codes and Default Codes of every data
element used by CDS v6-2 and v6-3, as effective-dated lookup tables.**

CDS submissions, and the extracts derived from them, carry coded values — `ADMISSION METHOD CODE
(HOSPITAL PROVIDER SPELL) = 21`, `TREATMENT FUNCTION CODE = 100`. What each code means is published by
NHS England in the [NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/), one web page per
data element, as HTML tables. UKHRD copies those tables — unchanged — into lookup tables you can join to,
keeps every earlier version with the dates it was in force, and records the exact page and publication
release each row came from.

```
$ sqlite3 ukhrd.db "SELECT description FROM ref_admission_method WHERE code = '21'"
Emergency Admission: Emergency Care Department or dental casualty department of the Health Care Provider
```

## The source, in NHS England's own terms

| | |
|---|---|
| **NHS Data Model and Dictionary** | "gives a reference point for assured information standards, to support health care activities in the NHS in England" |
| **Data Sets** | groups of data elements "required to support business analysis" |
| **Data Elements** | a data set's use of an attribute; a data element page carries the permitted codes, including **Default Codes** "to handle circumstances where data are not available" |
| **Commissioning Data Sets (CDS)** | "form the basis of data on ACTIVITY carried out by ORGANISATIONS reported centrally for monitoring and payment purposes"; they support Healthcare Resource Group derivation and payment |

A data element page — for example [ADMISSION METHOD CODE (HOSPITAL PROVIDER
SPELL)](https://www.datadictionary.nhs.uk/data_elements/admission_method_code_hospital_provider_spell.html)
— carries a format and length (`an2`), a description, a **National Codes** table, a **Default Codes**
table, and sometimes a note that the element will be replaced by another. **Those two code tables are
what UKHRD turns into rows.** Everything else stays on the page, which every row here names.

## What is held today

| | |
|---|---|
| Publication | NHS Data Model and Dictionary — Commissioning Data Sets, versions 6-2 and 6-3 |
| Release | July 2026 |
| Code lists | **121** |
| Published data elements behind them | 126 (a few are printed under more than one name) |
| Codes | **1,273** — 1,199 National, 74 Default |
| CDS record types that use them | 42 (for example Type 130 Admitted Patient Care, Type 020 Outpatient) |
| Effective-dated versions of list details | 140 |
| Fetch record | every attempt since 12 September 2026, with its outcome |
| Refresh | daily, automatically |

The largest lists:

| list | National Codes | Default Codes | data element |
|---|---:|---:|---|
| `treatment_function_code` | 184 | 2 | TREATMENT FUNCTION CODE |
| `main_specialty_code` | 95 | 2 | MAIN SPECIALTY CODE |
| `critical_care_activity_code` | 68 | 0 | CRITICAL CARE ACTIVITY CODE |
| `activity_location_type_code` | 46 | 0 | ACTIVITY LOCATION TYPE CODE |
| `mental_health_act_legal_status_classification_code` | 27 | 2 | MENTAL HEALTH ACT LEGAL STATUS CLASSIFICATION CODE |
| `admission_method` | 20 | 2 | ADMISSION METHOD CODE (HOSPITAL PROVIDER SPELL) |

`python cli.py lists` prints all 121.

## What a row looks like

One row per code **per version**. `dim_admission_method` for code `21`, if the description were reworded:

| `admission_method_key` | `code_kind` | `code` | `description` | `valid_from` | `valid_to` | `is_current` | `first_fetch_run_id` | `loaded_at` |
|---|---|---|---|---|---|---|---|---|
| 412 | national | 21 | Emergency Admission: A&E… | 1900-01-01 | 2027-02-04 | 0 | 2 | 2026-09-12 |
| 998 | national | 21 | Emergency Admission: Emergency Care Department… | 2027-02-04 | *null* | 1 | 41 | 2027-02-04 |

- **`valid_from` is `1900-01-01` for the first copy of every code.** Those codes were already in force
  before UKHRD began watching, so a 2024 record still gets an answer. When we first saw it is `loaded_at`.
- **Nothing is deleted.** A reworded description closes the old row and opens a new one; a withdrawn code
  is closed and stays queryable, because historic data still carries it.
- **`code_kind` keeps National and Default codes apart.** Default codes (usually `98`, `99`) are the
  publisher's "not known / not applicable" values: kept, labelled, never merged into the real codes.

## How it is laid out

The database is a single SQLite file. SQLite has no schemas, so names are prefixed.

| object | what it is | today |
|---|---|---|
| `ref_<list>` | **start here** — today's codes for one list: `code_kind`, `code`, `description` | 121 views |
| `ref_code` | today's codes, all lists in one table | 1,273 rows |
| `ref_list_directory` | one row per published data element: its list, counts, NHS page, release, first seen | 126 rows |
| `dim_<list>` | the table behind each list: every version of every code, effective-dated, with who loaded it | 121 tables |
| `meta_code_list` | every version of every list's details: name, page, data sets, supersession | 140 rows |
| `meta_fetch_run` | every fetch attempt: outcome, release, code count, content hash, who ran it | one per check |
| `meta_data_source` | what is fetched, its licence, and the attribution its terms require | 1 row |

Query recipes — including "what did this code mean on this date" and joining to your own extracts —
are in **[`docs/QUERIES.md`](docs/QUERIES.md)**.

## Where the data comes from

Every code, description and list name here is copied from the
**[NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/)**, published by NHS England.

> Contains information from NHS England, licensed under the current version of the
> [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

- **Nothing published is altered.** Codes and descriptions are stored exactly as printed. The dictionary
  is an NHS Information Standard, and its
  [terms and conditions](https://www.datadictionary.nhs.uk/notices/terms_and_conditions.html) permit
  copying but not alteration. The dates, keys and structure around the codes are UKHRD's.
- **Every list names its page.** `data/lists.csv` and `ref_list_directory` record the exact dictionary
  page each list was copied from, and the release it came from.
- **Other classifications are named, not copied.** A few lists refer to coding schemes such as SNOMED
  CT®, ICD-10 or OPCS-4. None of those schemes' own codes are held here.
- **Not endorsed.** UKHRD is an independent project, not produced, approved or endorsed by NHS England.
- **The dictionary is the authority.** This copy is checked against it daily, and every check is recorded
  in `data/fetches.csv`. For anything that matters, check the page itself.

## The files are the store; the database is a copy

Everything is plain CSV in **`data/`**, in this repository. Clone it and you have the whole history —
every code, every superseded meaning, every fetch and who ran it — without fetching anything.

```
data/sources.csv                      what is fetched, and the attribution the publisher requires
data/fetches.csv                      every fetch attempt, its outcome, and who ran it
data/lists.csv                        every version of every list's details
data/nhs_dd_cds/admission_method.csv  every version of every code in one list      121 of these
```

`git diff data/` shows exactly what NHS England changed. A check that finds nothing new changes one line
of `fetches.csv` and nothing else.

**It refreshes itself.** A scheduled job reads the dictionary every morning — NHS England's terms ask
that a cached copy be refreshed every 24 hours. A change arrives as a pull request showing precisely what
moved; once a person has reviewed and merged it, a release is published. An implausible answer — too few
codes, or a whole list missing — is refused, changes nothing, and is recorded as loudly as a failure.

Each release carries ready-built copies. These links always point at the newest:

| file | what it is |
|---|---|
| [`ukhrd.db`](https://github.com/eamazon/ukhrd/releases/latest/download/ukhrd.db) | the SQLite database: every table and view above |
| [`codes.parquet`](https://github.com/eamazon/ukhrd/releases/latest/download/codes.parquet) | every version of every code, all lists in one typed table |
| [`lists.parquet`](https://github.com/eamazon/ukhrd/releases/latest/download/lists.parquet) | every version of every list's details, with its NHS page |
| [`ukhrd.mcpb`](https://github.com/eamazon/ukhrd/releases/latest/download/ukhrd.mcpb) | the MCP server as a one-click bundle |

## Three ways in

1. **SQL.** One real table per list. No ORM, no service to run. Open `ukhrd.db` with anything that reads
   SQLite, or load the Parquet files into your own warehouse — ready-to-run loaders for **Microsoft Fabric
   and Snowflake** are in [`integrations/`](integrations/), and DuckDB, Postgres and Power BI recipes are
   in [`docs/QUERIES.md`](docs/QUERIES.md). Each loader builds one table per reference list.
2. **Command line.** `refresh`, `load`, `status`, `lists`, `show`, `lookup`, `history`, `changes`.
3. **MCP server**, read-only, for AI assistants. See [below](#for-ai-assistants-mcp).

There is no web server and no user interface. Those are somebody's fork, not this repository.

## Quick start

Requires **Python 3.10 or newer, and nothing else** — no database server, no packages.

```bash
git clone https://github.com/eamazon/ukhrd.git && cd ukhrd
python3 cli.py load                     # build ukhrd.db from data/ — no network, under a second
python3 cli.py lists                    # every list, largest first
python3 cli.py show admission_method    # one list in full, with its NHS page
python3 cli.py changes admission_method # every version, with the dates each was in force
sqlite3 ukhrd.db "SELECT * FROM ref_admission_method"
```

`git pull` brings a clone up to date; the daily check has usually done the work already. To run a check
yourself: `python3 cli.py refresh` (about 9 seconds), then `git diff data/` to see what changed.

`UKHRD_DB` puts the database elsewhere. `UKHRD_ACTOR` names who a refresh is recorded against. The tests
need `pytest` (`pip install -r requirements.txt`) and build their own throwaway copy.

## For AI assistants (MCP)

UKHRD is also an MCP server (Model Context Protocol), so an assistant can resolve codes for you and carry
the NHS page and the attribution into every answer. It runs locally and is **read-only**.

**One click.** Download
[`ukhrd.mcpb`](https://github.com/eamazon/ukhrd/releases/latest/download/ukhrd.mcpb) and open it with a
desktop AI app that supports MCP Bundles. The app installs everything the server needs.

**Nothing to clone.** With [uv](https://docs.astral.sh/uv/) installed, add this to your MCP client's
configuration:

```json
{
  "mcpServers": {
    "ukhrd": {
      "command": "uvx",
      "args": ["--from", "ukhrd[mcp] @ git+https://github.com/eamazon/ukhrd", "ukhrd-mcp"]
    }
  }
}
```

It installs the server from this repository, downloads `ukhrd.db` from the latest release, keeps it in
`~/.cache/ukhrd`, and fetches a newer copy once that one is a day old.

**From a clone instead:** `pip install -r requirements-mcp.txt`, then
`"command": "/full/path/to/ukhrd/.venv/bin/python", "args": ["/full/path/to/ukhrd/cli.py", "mcp"]`.

| tool | answers |
|---|---|
| `search_lists` | which lists exist, found by words in their name |
| `lookup_code` | what a code means today |
| `show_list` | every code in one list |
| `code_meaning_on` | what a code meant on a given date — for labelling historic records |
| `code_history` | every version of a code, with its dates |
| `about` | what is held, which release, how fresh |

## Principles

- **Nothing is deleted or overwritten.** A changed meaning closes the old row and opens a new one. The
  dictionary publishes only current codes, so for a withdrawn code this is the only record it ever meant
  anything — and historic data still carries it.
- **Every row carries its lineage.** `loaded_at` · `loaded_by` · `updated_at` · `updated_by` ·
  `valid_from` · `valid_to` · `is_current`, plus the fetch that first saw it. Set once, from the fetch,
  and carried in the files, so a rebuild next year still tells the truth.
- **Surrogate keys survive rebuilds.** `<list>_key` comes from the files, not from the database, so a
  fact table pinned to one stays pinned.
- **An implausible answer is refused, never applied.** Two floors: a collapsed total, and any single list
  falling to zero. The last good copy stands, and the refusal is recorded.
- **One data element printed twice is one list.** Where two published items carry identical National
  Codes they share a table; where the codes differ they remain separate lists.
- **Codes are stored as published.** NHS RTT files write `C_100` where the dictionary writes `100`.
  Normalising is the caller's job — a store that corrects its sources cannot be trusted as a reference.

## Contributing a dataset

Open an issue saying what it is and where it is published. If it is public, free and UK health data, it
belongs here. If its shape matches something already read, adding it is one row in `data/sources.csv`.

## Licence

**The code is MIT** — full text in `LICENSE`.

**The data is not ours.** It belongs to NHS England, is licensed under the Open Government Licence, and
carries the attribution in [Where the data comes from](#where-the-data-comes-from). The same attribution
travels with the files in `data/README.md` and inside the Parquet files' metadata.
