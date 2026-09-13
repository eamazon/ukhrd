# UKHRD — UK Health Reference Data

**An open store of what the codes in UK health data actually mean.**

NHS files are full of short codes. A file says a patient's admission method was `21`. On its own that
means nothing. The NHS publishes a page saying `21` is "Emergency Admission: Emergency Care Department".
UKHRD fetches those lists, keeps them fresh, and never forgets an old version.

Free, open, and boring on purpose.

```
$ sqlite3 ukhrd.db "SELECT description FROM ref_admission_method WHERE code = '21'"
Emergency Admission: Emergency Care Department or dental casualty department of the Health Care Provider
```

## What it holds today

The **121 code lists used by the NHS Commissioning Data Sets** — 1,273 codes (1,199 national, 74
"not known" defaults). Admission method, admission source, discharge destination, treatment function,
main specialty, ethnic category, and the rest. Pulled from the NHS Data Model and Dictionary.

Adding another dataset is **one row in `data/sources.csv`** plus, if it is a new shape, one small
reader. No change to the engine.

## Where the data comes from

Every code, description and list name here is copied from the
**[NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/)**, published by NHS England.

> Contains information from NHS England, licensed under the current version of the
> [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

- **We do not change what NHS England publishes.** Codes and descriptions are stored exactly as
  printed. The dictionary is an NHS Information Standard, and its
  [terms and conditions](https://www.datadictionary.nhs.uk/notices/terms_and_conditions.html) allow
  copying it but not altering it. The layout, dates and history around the codes are ours.
- **Every list names its page.** `data/lists.csv` and `ref_list_directory` record the exact dictionary
  page each list was copied from, and the release it came from.
- **Other classifications are named, not copied.** A few lists name coding schemes such as SNOMED CT®,
  ICD-10 or OPCS-4 as options. None of those schemes' own codes are held here.
- **Not endorsed.** UKHRD is an independent project. It is not produced, approved or endorsed by NHS
  England.
- **The dictionary is the authority.** Our copy is checked against it every day, and every check is
  recorded in `data/fetches.csv`. For anything that matters, check the page itself.

## The files are the store

Everything lives as plain CSV in **`data/`**, in this repo. Clone it and you have the whole history —
every code, every old meaning, every fetch and who ran it — without fetching anything.

```
data/sources.csv                      what we fetch, and the credit each publisher asks for
data/fetches.csv                      every fetch, whatever happened, and who ran it
data/lists.csv                        every version of every list's details
data/nhs_dd_cds/admission_method.csv  every version of every code in one list      121 of these
```

When the NHS changes something, `git diff data/` shows exactly what. A refresh that finds nothing new
changes one line in `fetches.csv` and nothing else.

**It keeps itself fresh.** A GitHub Action reads the dictionary every morning. A quiet day adds one line
to `fetches.csv`. When NHS England changes something, it opens a pull request showing exactly what
changed; once a person has looked and merged it, a new release with a fresh `ukhrd.db` is published.
A check that looks wrong — too few codes, a list gone missing — changes nothing and is logged as refused.

The database is **one SQLite file, `ukhrd.db`**, built from those files in under a second. Throw it
away whenever you like. Each [release](https://github.com/eamazon/ukhrd/releases) also carries a
ready-built copy.

## Three doors, on purpose

1. **Plain SQL.** One real table per list, named after the list. No ORM, no magic. Open `ukhrd.db` in
   anything that reads SQLite. Recipes: **`docs/QUERIES.md`**.
2. **A command line.** `refresh`, `load`, `status`, `lists`, `show`, `lookup`, `history`, `changes`.
3. **An MCP server** for AI assistants, read-only. See [below](#for-ai-assistants-mcp).

```
sqlite3 ukhrd.db

  ref_admission_method          ← what these codes mean TODAY. 121 lists. START HERE
  ref_treatment_function_code
  ref_discharge_destination     …
  ref_list_directory            every list, its name here, its counts, its page
  ref_code                      every current code, all lists together

  dim_admission_method          ← the TABLE behind it: every version of every code,
  dim_treatment_function_code     effective-dated, with who loaded it and when
  dim_discharge_destination     …

  meta_data_source              what we know how to fetch
  meta_fetch_run                every attempt, whatever happened, and who ran it
  meta_code_list                every version of every list's details
```

**Why two layers.** `ref_admission_source` tells you what code 37 means now. `dim_admission_source`
tells you it meant something else until March, when it changed, and who loaded the change. A reference
store that can only answer the first question is a scraped copy, not a reference store.

No web server and no UI. Those are somebody's fork, not this repo.

## Rules this repo keeps

- **Never delete a version.** Every fetch is kept, and every *meaning* is kept. When the NHS reworks a
  description, the old row is closed off with an end date rather than overwritten; when the NHS drops a
  code, our copy is the only record it ever meant anything — and old data still carries it.
- **Every row says when it landed and who loaded it.** `loaded_at` · `loaded_by` · `updated_at` ·
  `updated_by` · `valid_from` · `valid_to`, plus the fetch that first saw it. Set once, from the fetch,
  and kept in the files — so rebuilding the database next year still tells the truth.
- **The first copy is valid from the beginning.** Codes were in force before we started watching, so a
  2024 NHS file still gets an answer. Changes we saw later carry the date we saw them.
- **One list published twice is one list.** NHS prints some items more than once under different names.
  Where the codes are identical that is one list and gets one table; where they differ they are
  genuinely different lists and keep separate names.
- **A short answer is refused, never applied.** If a source returns 4 rows where it has always returned
  1,483, the fetch is refused and the last good copy stands. The refusal is logged as loudly as a failure.
- **Every row says where it came from.** The page, and the publisher's release name. A row with no
  provenance is a rumour.
- **`national` and `default` codes stay apart.** Default codes are the "not known / not applicable"
  values. Merging them silently corrupts a lookup.
- **Normalising is the caller's job, never ours.** NHS RTT files write `C_100`; the dictionary writes
  `100`. We store what the publisher published. You strip the prefix in your own query.

## Quick start

Needs **Python 3.10 or newer, and nothing else** — no database server, no packages.

```bash
git clone https://github.com/eamazon/ukhrd.git && cd ukhrd
python3 cli.py load                     # build ukhrd.db from data/ — no network, under a second
python3 cli.py lists                    # every list and what to query
python3 cli.py show admission_method
python3 cli.py changes admission_method # every version, with its dates
sqlite3 ukhrd.db "SELECT * FROM ref_admission_method"
```

To bring your clone up to date, `git pull` — the daily check has usually already done the work. To run
a check yourself, `python3 cli.py refresh` (about 9 seconds), then `git diff data/` to see what changed.

Set `UKHRD_DB` to keep the database somewhere other than `ukhrd.db`. Set `UKHRD_ACTOR` to the name that
should be recorded against everything a refresh writes. The tests need `pytest`
(`pip install -r requirements.txt`) and build their own throwaway copy.

**How to query it:** `docs/QUERIES.md` has the layout, the columns and worked recipes.

## For AI assistants (MCP)

`python3 cli.py mcp` serves UKHRD to any assistant that speaks MCP (the Model Context Protocol), over
stdio. It is **read-only**: it opens `ukhrd.db` read-only and never fetches.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-mcp.txt
```

Then add it to your MCP client's configuration, with the full path to your clone:

```json
{
  "mcpServers": {
    "ukhrd": {
      "command": "/full/path/to/ukhrd/.venv/bin/python",
      "args": ["/full/path/to/ukhrd/cli.py", "mcp"]
    }
  }
}
```

| tool | answers |
|---|---|
| `search_lists` | which lists exist, found by words in their name |
| `lookup_code` | what a code means today |
| `show_list` | every code in one list |
| `code_meaning_on` | what a code meant on a given day — for labelling old records |
| `code_history` | every version of a code, with its dates |
| `about` | what is held, which release, how fresh |

Every answer carries NHS England's credit line and the page it came from, and the server asks the
assistant to pass both on.

## Contributing a dataset

Open an issue saying what it is and where it is published. If it is public, free, and UK health data,
it belongs here. If its shape matches something we already read, it is a one-row change.

## Licence

**The code is MIT** — the full text is in `LICENSE`.

**The data is not ours.** It belongs to NHS England, is licensed under the Open Government Licence, and
carries the credit in [Where the data comes from](#where-the-data-comes-from). The same credit travels
with the files in `data/README.md`, so it goes wherever the data goes.
