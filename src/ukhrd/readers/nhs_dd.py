"""Read code lists out of the NHS Data Model and Dictionary.

The dictionary is a flat set of static HTML pages generated from Mauro Data Mapper. No login, no key.
Every coded page carries one table under an anchor whose id ends `_nationalCodes`, two columns,
Code | Description. A second table under `_defaultCodes` holds the "not known / not applicable" values.

⛔ THE USER-AGENT IS NOT COSMETIC. Measured 2026-09-12 against attributes/admission_method.html:
a polite, self-identifying string gets **403**, no user-agent gets **403**, a normal browser string gets 200.
Do not replace it with a self-identifying string — the fetch will start failing silently.

⛔ WE DO NOT NORMALISE. The dictionary writes `100`; an NHS RTT file writes `C_100`. Storing the
publisher's own value is the whole point. The caller strips the prefix in their own query.

What it walks:  sitemap.xml → the CDS type pages of the CURRENT versions → the data items they
reference → each item's code tables. Older CDS versions are deliberately left out.
"""
from __future__ import annotations

import html
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

BASE = "https://www.datadictionary.nhs.uk/"
BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CURRENT_VERSIONS = ("data_sets/cds_v6-2/", "data_sets/cds_v6-3/")
WORKERS = 8
TIMEOUT = 30


def _get(path: str) -> str:
    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": BROWSER})
            return urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 — the sitemap walk tolerates a page, not the start
            if attempt == 2:
                log.warning("nhs_dd: gave up on %s — %s", path, exc)
                return ""
    return ""


def _rows(table_html: str) -> list[list[str]]:
    out = []
    for row in re.findall(r"(?s)<tr.*?</tr>", table_html):
        cells = [html.unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<.*?>", "", c))).strip()
                 for c in re.findall(r"(?s)<t[dh].*?</t[dh]>", row)]
        if cells:
            out.append(cells)
    return out


def _table(page: str, anchor: str) -> list[list[str]]:
    """The table sitting under the element whose id ends with `anchor`."""
    m = re.search(r'(?s)id="[^"]*_' + anchor + r'".*?(<table.*?</table>)', page)
    return _rows(m.group(1)) if m else []


def _text(page: str) -> str:
    body = re.sub(r"(?s)<(script|style).*?</\1>", "", page)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<.*?>", " ", body)))


def _release(index_html: str) -> str:
    """Which publication this is. ⛔ Raises rather than guessing.

    Every row is stamped with this. Landing 1,483 rows marked "unknown release" would quietly rewrite
    history the next time somebody asked what a code meant in 2026 — and the store's whole promise is
    that a row without provenance is a rumour. A raise here becomes outcome `failed`, the last good
    copy stands, and a person goes and looks at the page.
    """
    m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|"
                  r"November|December) \d{4} release)", _text(index_html))
    if not m:
        raise ValueError("could not read which release this is from the dictionary's front page — "
                         "its layout has probably changed. Nothing was stored.")
    return m.group(1)


def _same_thing(a: str, b: str) -> bool:
    """Are these two published names the same item? Whitespace and punctuation vary between sentences."""
    tidy = lambda s: re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()
    return tidy(a) == tidy(b)


def read(url: str) -> dict:
    """Every coded item in the current Commissioning Data Sets.

    Returns ``{"release": "July 2026 release", "lists": [...]}`` where each list carries its own
    metadata and its codes. Touches no database, so a test can hand it saved pages instead.
    """
    sitemap = _get(url.replace(BASE, ""))
    paths = re.findall(r"<loc>(.*?)</loc>", sitemap)
    type_pages = [p for p in paths if p.startswith(CURRENT_VERSIONS)]
    log.info("nhs_dd: %d CDS type pages", len(type_pages))

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        typed = list(ex.map(_get, type_pages))

    used_by: dict[str, set[str]] = {}
    for path, page in zip(type_pages, typed):
        # Some CDS types are published twice, the second as `…_2.html`. Strip only that TRAILING
        # marker — a plain .replace("_2", "") also eats the 2 out of `type_200` and silently renames
        # the data set. Caught by eye-checking the first real fetch, 2026-09-12.
        label = path.split("/")[-1].removesuffix(".html").removesuffix("_2")
        for name in set(re.findall(r'href="[^"]*data_elements/([a-z0-9_\-.]+\.html)"', page)):
            used_by.setdefault("data_elements/" + name, set()).add(label)

    items = sorted(used_by)
    log.info("nhs_dd: %d distinct data items referenced", len(items))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        pages = dict(zip(items, ex.map(_get, items)))

    release = _release(_get("index.html"))
    lists: list[dict] = []
    for path, page in pages.items():
        if not page:
            continue
        national, default = _table(page, "nationalCodes"), _table(page, "defaultCodes")
        if not national:
            continue
        title = html.unescape(re.sub(r"\s+", " ", re.search(r"(?s)<title>(.*?)</title>",
                                                            page).group(1))).strip()
        text = _text(page)
        same = re.search(r"is the same as attribute ([A-Z0-9 ()\-,/]+?) \.", text)
        # ⚠ THE SENTENCE CAN BE ABOUT SOMEBODY ELSE. The page for ADMISSION SOURCE carries
        # "SOURCE OF ADMISSION CODE … will be replaced with ADMISSION SOURCE …" — it is the
        # REPLACEMENT being described, not the replaced. Capturing only the target marked the new
        # list as superseded by itself. So capture the SUBJECT too and keep it only when the subject
        # is this item. Caught by eye-checking a real fetch, 2026-09-12.
        goes = re.search(r"([A-Z][A-Z0-9 ()\-/]{4,70}?) will be replaced (?:by|with) "
                         r"([A-Z][A-Z0-9 ()\-/]{4,60})", text)
        if goes and _same_thing(goes.group(1), title):
            superseded_by = goes.group(2).strip()
        else:
            superseded_by = None
        values = [{"code_kind": kind, "code": c[0], "description": c[1]}
                  for kind, table in (("national", national), ("default", default))
                  for c in table[1:] if len(c) >= 2 and c[0] and c[1]]
        lists.append({
            "list_key": path.split("/")[-1].removesuffix(".html"),
            "item_name": title,
            "concept_name": same.group(1).strip() if same else None,
            "superseded_by": superseded_by,
            "source_page": BASE + path,
            "data_sets": sorted(used_by[path]),
            "values": values,
        })
    log.info("nhs_dd: %d code rows across %d lists, %s",
             sum(len(l["values"]) for l in lists), len(lists), release)
    return {"release": release, "lists": lists}
