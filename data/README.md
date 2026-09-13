# The data

These files are the store behind UKHRD (UK Health Reference Data): every version of every code, every
list and every fetch.

**Source:** the [NHS Data Model and Dictionary](https://www.datadictionary.nhs.uk/), published by NHS
England.

> Contains information from NHS England, licensed under the current version of the
> [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

- Codes and descriptions are **exactly as NHS England publishes them**. The columns around them —
  dates, keys, who ran the fetch — are added by UKHRD.
- The MIT licence in this repo covers the **code**, not these files. These files carry NHS England's
  terms: [terms and conditions](https://www.datadictionary.nhs.uk/notices/terms_and_conditions.html).
- UKHRD is independent and **not endorsed by NHS England**.
- The dictionary is the authority. Before relying on a code, check the page named in `source_page` in
  `lists.csv`.

## What is here

| file | one row per |
|---|---|
| `sources.csv` | publication we fetch |
| `fetches.csv` | fetch attempt, whatever happened, and who ran it |
| `lists.csv` | version of a published list's details — its name, its page, its data sets |
| `<source>/<list>.csv` | version of one code: its meaning, `valid_from` / `valid_to`, and when we first saw it |

`valid_from` of `1900-01-01` means "already in force when we started watching". Nothing in these files is
ever deleted: a changed meaning closes the old row and opens a new one.
