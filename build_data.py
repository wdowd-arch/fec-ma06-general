#!/usr/bin/env python3
"""
MA-06 general-election campaign finance dashboard: data build.

Pulls Dan Koh (D) and Micah Jones (R) from the OpenFEC API and writes the
pre-built JSON the page reads:

    data/dashboard.json     everything the page renders
    data/build_log.json     endpoints hit, record counts, amendments excluded,
                            reconciliation results, run time

The page never talks to the API. Only this script does, and it reads the key
from the FEC_API_KEY environment variable and nowhere else. The key is sent
in the X-Api-Key header, never in a URL, and is never written to any output
file; the last step of every run scans every output for the key and aborts
if it finds it.

Usage:
    export FEC_API_KEY=...            # never commit it
    python3 build_data.py             # normal daily run
    python3 build_data.py --refresh   # ignore the response cache
    python3 build_data.py --offline   # rebuild from cache only, no network

See README.md for the schedule (daily through Nov. 3, then once after the
Dec. 3 post-general filing) and the methodology notes the page shows.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write("requests is required: pip install -r requirements.txt\n")
    raise

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(ROOT, "cache")
API_BASE = os.environ.get("FEC_API_BASE", "https://api.open.fec.gov/v1")
DOCQUERY_FEC = "https://docquery.fec.gov/dcdev/posted/{file_number}.fec"
DOCQUERY_FORM_PAGE = "https://docquery.fec.gov/cgi-bin/forms/{committee_id}/{file_number}/"
LIMITS_URL = "https://www.fec.gov/help-candidates-and-committees/candidate-taking-receipts/contribution-limits/"
SCHEMA_VERSION = "3.0.0"
EASTERN = ZoneInfo("America/New_York")

CYCLE = 2026
ELECTION_DATE = "2026-11-03"
PRIMARY_DATE = "2026-09-01"
TIMELINE_START = "2026-09-02"          # day after the primary
LATE_WINDOW_START = "2026-10-15"       # 48-hour notice period opens 20 days out
LATE_WINDOW_END = "2026-11-01"         # notices stop 48 hours before Election Day

# The two general-election candidates. Display names are fixed here so the
# page never shows two spellings of the same person.
CANDIDATES = [
    {"key": "koh", "name": "Dan Koh", "last_name": "Koh", "party": "Democratic", "party_abbr": "D",
     "candidate_id": "H8MA03072", "committee_id": "C00654509"},
    {"key": "jones", "name": "Micah Jones", "last_name": "Jones", "party": "Republican", "party_abbr": "R",
     "candidate_id": "H6MA06202", "committee_id": "C00937755"},
]

# The six primary candidates whose donors the crossover section tracks.
PRIMARY_COMMITTEES = [
    {"key": "andres_beck", "name": "Beth Andres-Beck", "committee_id": "C00909770"},
    {"key": "beccia", "name": "John Beccia", "committee_id": "C00923912"},
    {"key": "belsito", "name": "Jamie Belsito", "committee_id": "C00923805"},
    {"key": "jakious", "name": "Rick Jakious", "committee_id": "C00924712"},
    {"key": "lancaster", "name": "Mariah Lancaster", "committee_id": "C00932830"},
    {"key": "nguyen", "name": "Tram Nguyen", "committee_id": "C00924241"},
]

FILING_DEADLINES = [
    {"date": "2026-10-15", "label": "October quarterly report due", "covers": "July 1 through Sept. 30"},
    {"date": "2026-10-22", "label": "Pre-general report due", "covers": "Oct. 1 through Oct. 14"},
    {"date": LATE_WINDOW_START, "end": LATE_WINDOW_END, "label": "48-hour notice window",
     "covers": "Contributions of $1,000 or more must be reported within 48 hours"},
    {"date": ELECTION_DATE, "label": "Election Day", "covers": ""},
    {"date": "2026-12-03", "label": "Post-general report due", "covers": "Oct. 15 through Nov. 23"},
]

# ---------------------------------------------------------------------------
# Geography: the primary edition's ZIP/town rule, reused unchanged. A donor
# with a Massachusetts address is "estimated in the district" when the first
# five digits of the ZIP code are in MA06_ZIPS or the city, uppercased, is in
# MA06_TOWNS. Everything else in Massachusetts is "elsewhere in
# Massachusetts." No state on file means "unknown," never "out of state."
# ZIP codes do not follow district lines exactly and some towns are split, so
# this is an estimate, not a legal determination.
# ---------------------------------------------------------------------------
MA06_ZIPS = sorted({
    "01945", "01970", "01907", "01908", "01901", "01902", "01903", "01904",
    "01905", "01906",
    "01915", "01923", "01960", "01961", "01949", "01983",
    "01930", "01931", "01966", "01929", "01944", "01936", "01982", "01984", "01938",
    "01810", "01845",
    "01830", "01832", "01835", "01860", "01913", "01950", "01951", "01952",
    "01833", "01834", "01921", "01969", "01985",
})
MA06_TOWNS = sorted({
    "MARBLEHEAD", "SALEM", "SWAMPSCOTT", "NAHANT", "LYNN", "SAUGUS", "BEVERLY",
    "DANVERS", "PEABODY", "MIDDLETON", "TOPSFIELD", "GLOUCESTER", "ROCKPORT",
    "ESSEX", "MANCHESTER", "MANCHESTER-BY-THE-SEA", "HAMILTON", "WENHAM",
    "IPSWICH", "ANDOVER", "NORTH ANDOVER", "HAVERHILL", "AMESBURY",
    "NEWBURYPORT", "NEWBURY", "SALISBURY", "MERRIMAC", "GEORGETOWN",
    "GROVELAND", "BOXFORD", "ROWLEY", "WEST NEWBURY",
})


def town_canon(city):
    """Canonical town key for matching: uppercase, letters only, so
    'Manchester-by-the-Sea', 'MANCHESTER BY THE SEA' and 'Manchester'
    all land on the same district town."""
    key = re.sub(r"[^A-Z]", "", (city or "").upper())
    return "MANCHESTERBYTHESEA" if key == "MANCHESTER" else key


MA06_TOWN_KEYS = {town_canon(t) for t in MA06_TOWNS}
TOWN_DISPLAY = {"MANCHESTERBYTHESEA": "Manchester-by-the-Sea"}
# Towns shown in the district table even when a candidate has no donors there.
# Marblehead is always listed; the rest are the rule's own town list with the
# two Manchester spellings merged for display.
DISTRICT_TABLE_TOWNS = sorted({town_canon(t) for t in MA06_TOWNS})

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}

# ---------------------------------------------------------------------------
# Spending categories: the primary edition's keyword rules, unchanged. A
# keyword match against the committee's own free-text purpose field on
# itemized Schedule B rows. First matching rule wins.
# ---------------------------------------------------------------------------
CATEGORY_RULES = [
    ("Refunds", [r"\bREFUND"]),
    ("Payroll", [r"\bPAYROLL\b", r"\bSALAR", r"\bWAGE"]),
    ("Advertising and media", [r"\bMEDIA\b", r"TV AD", r"RADIO", r"BROADCAST",
                               r"\bADVERTISING\b(?! CONSULT)", r"PRINT AD"]),
    ("Digital", [r"DIGITAL", r"\bONLINE\b", r"\bTEXT MESSAGING\b",
                 r"\bSOFTWARE\b", r"\bSUBSCRIPTION", r"\bDIALER\b", r"WEBSITE",
                 r"\bSMS\b", r"\bEMAIL\b"]),
    ("Fundraising", [r"FUNDRAIS", r"\bACTBLUE\b", r"\bWINRED\b",
                     r"MERCHANT FEE", r"CREDIT CARD (PROCESSING|FEE)",
                     r"PAYMENT PROCESS"]),
    ("Consultants", [r"CONSULT", r"STRATEG", r"POLLING", r"RESEARCH"]),
    ("Mail", [r"\bMAIL\b", r"\bMAILING\b", r"\bPOSTAGE\b", r"\bPRINTING\b"]),
    ("Events", [r"\bEVENT", r"CATERING", r"VENUE", r"\bGIFT"]),
    ("Travel", [r"TRAVEL", r"\bLODGING\b", r"\bHOTEL\b", r"\bAIRFARE\b",
                r"\bMILEAGE\b", r"\bPARKING\b", r"\bAUTO\b"]),
    ("Legal, compliance and accounting", [r"COMPLIANCE", r"\bLEGAL\b",
                                          r"ACCOUNT", r"\bTREASURER\b",
                                          r"\bFILING FEE\b", r"\bBANK FEE"]),
    ("Office and operations", [r"OFFICE", r"RENT", r"UTILIT", r"INSURANCE",
                               r"EQUIPMENT", r"SUPPLIES"]),
]
SPEND_ORDER = [label for label, _ in CATEGORY_RULES] + ["Other", "Uncategorized"]

RECONCILIATION_TOLERANCE = 0.01
PER_PAGE = 100


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def to_float(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def iso_date(v):
    """'2026-10-14T00:00:00' / '20261014' / '2026-10-14' -> '2026-10-14'."""
    if not v:
        return None
    s = str(v)
    if "T" in s:
        s = s.split("T", 1)[0]
    if re.fullmatch(r"\d{8}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def first(d, *keys, default=None):
    """First present, non-None key. OpenFEC field names drift between
    endpoints (period vs. ytd, with and without suffixes), so every summary
    read goes through here and the build log records what was missing."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def clean(s):
    return " ".join((s or "").split()).strip(" ,;")


def person_display(row):
    """'First Last' when the filing gives the parts; otherwise the filed
    name with a 'LAST, FIRST' form turned around."""
    first_name = clean(row.get("contributor_first_name"))
    last = clean(row.get("contributor_last_name"))
    if first_name and last:
        return title_display(f"{first_name} {last}")
    name = clean(row.get("contributor_name"))
    if "," in name:
        a, b = [x.strip() for x in name.split(",", 1)]
        if b:
            return title_display(f"{b} {a}")
    return title_display(name)


KEEP_UPPER = {"PAC", "LLC", "LLP", "INC", "USA", "US", "NRCC", "DCCC", "DNC", "RNC", "GOP", "AFL-CIO", "SEIU",
              "UAW", "IBEW", "AFSCME", "NEA", "AFT", "UFCW", "II", "III", "IV", "MA", "NH", "NY", "CT", "DC", "IT", "AI"}


UPPER_TOKENS = KEEP_UPPER | {"SMS", "MMS", "TV", "GOTV", "P2P", "CTV", "OTT", "ID", "ZIP", "FEC"}
TOKEN_FIXES = {"INC": "Inc.", "INC.": "Inc.", "LLC.": "LLC"}


def sentence_display(raw):
    """Filer text that arrives in ALL CAPS (report names, expenditure
    purposes) becomes sentence case: 'October quarterly', 'Digital media
    buy'. Mixed-case text is left alone; initialisms stay uppercase."""
    s = clean(raw)
    if not s:
        return s
    letters = [c for c in s if c.isalpha()]
    if not letters or s != s.upper():
        return s
    words = []
    for i, w in enumerate(s.split(" ")):
        core = w.strip(".,;:()/")
        if core in TOKEN_FIXES:
            words.append(w.replace(core, TOKEN_FIXES[core]))
        elif core in UPPER_TOKENS:
            words.append(w)
        else:
            words.append(w.lower() if i else w.capitalize())
    return " ".join(words)


def title_display(raw):
    """Retitles a value filed in ALL CAPS or all lowercase; leaves mixed case
    alone. Common initialisms stay uppercase so a committee name does not
    come out as 'Something Pac'."""
    s = clean(raw)
    if not s:
        return s
    letters = [c for c in s if c.isalpha()]
    if letters and (s == s.upper() or s == s.lower()):
        words = []
        for w in s.title().split(" "):
            core = w.strip(".,;:()").upper()
            if core in TOKEN_FIXES:
                words.append(TOKEN_FIXES[core])
            else:
                words.append(w.upper() if core in UPPER_TOKENS else w)
        return " ".join(words)
    return s


def zip5(z):
    z = re.sub(r"\D", "", z or "")
    return z[:5] if len(z) >= 5 else ""


def geo_bucket(state, zip_code, city):
    state = (state or "").strip().upper()
    if not state:
        return "unknown"
    if state != "MA":
        return "out_of_state"
    if zip5(zip_code) in MA06_ZIPS or town_canon(city) in MA06_TOWN_KEYS:
        return "in_district"
    return "ma_other"


def categorize_purpose(purpose):
    p = (purpose or "").upper()
    if not p.strip():
        return "Uncategorized"
    for label, patterns in CATEGORY_RULES:
        for pat in patterns:
            if re.search(pat, p):
                return label
    return "Other"


SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "PHD", "ESQ", "DDS", "JD"}


def name_key(last, first_name, full):
    """Normalized name for the crossover rule: last name and first name,
    uppercased, punctuation and spaces removed, generational and
    professional suffixes dropped. Falls back to splitting 'LAST, FIRST'."""
    last = clean(last).upper()
    first_name = clean(first_name).upper()
    if not last and full:
        parts = [p.strip() for p in clean(full).upper().split(",")]
        last = parts[0]
        if len(parts) > 1:
            first_name = parts[1]
    first_word = first_name.split(" ")[0] if first_name else ""
    last_words = [w.strip(".") for w in last.split(" ") if w.strip(".") and w.strip(".") not in SUFFIXES]
    last = "".join(last_words)
    key = re.sub(r"[^A-Z]", "", last + "|" + first_word)
    return key if last and first_word else ""


def ap_month(d: dt.date):
    months = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]
    return months[d.month - 1]


def ap_datetime(ts: dt.datetime):
    """AP style in Eastern time: 'Oct. 22, 2026, 3:14 p.m.'; noon and midnight by name."""
    ts = ts.astimezone(EASTERN)
    h, m = ts.hour, ts.minute
    if h == 0 and m == 0:
        t = "midnight"
    elif h == 12 and m == 0:
        t = "noon"
    else:
        h12 = h % 12 or 12
        t = f"{h12}:{m:02d} {'a.m.' if h < 12 else 'p.m.'}"
    return f"{ap_month(ts.date())} {ts.day}, {ts.year}, {t}"


# ---------------------------------------------------------------------------
# API client: cached, paced, backs off, never logs the key
# ---------------------------------------------------------------------------

class RateLimitPause(Exception):
    pass


class FecClient:
    def __init__(self, api_key, cache_dir, ttl_hours=20.0, refresh=False, offline=False,
                 rate_limit=60, window_seconds=60, log=None):
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.ttl = dt.timedelta(hours=ttl_hours)
        self.refresh = refresh
        self.offline = offline
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self.min_interval = window_seconds / max(rate_limit, 1)
        self.log = log if log is not None else {}
        self.log.setdefault("endpoints", Counter())
        self.log.setdefault("requests", 0)
        self.log.setdefault("cache_hits", 0)
        self.log.setdefault("rate_limit_pauses", 0)
        self.log.setdefault("backoffs", 0)
        self.log.setdefault("warnings", [])
        self._last_call = 0.0
        self._window_started = None
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "ma06-general-dashboard/1.0 (Marblehead Independent)",
        })
        if api_key:
            self.session.headers["X-Api-Key"] = api_key
        os.makedirs(cache_dir, exist_ok=True)

    # -- cache --------------------------------------------------------------
    def _cache_path(self, url, params):
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        return os.path.join(self.cache_dir, hashlib.sha256(key.encode()).hexdigest() + ".json")

    def _read_cache(self, path, ttl=None):
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                entry = json.load(f)
        except (OSError, ValueError):
            return None
        if self.offline:
            return entry
        fetched = dt.datetime.fromisoformat(entry.get("fetched_at", "1970-01-01T00:00:00+00:00"))
        if dt.datetime.now(dt.timezone.utc) - fetched > (ttl or self.ttl):
            return None
        return entry

    def _write_cache(self, path, url, params, status, body, text=None):
        entry = {
            "url": url, "params": params, "status": status,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "body": body, "text": text,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        os.replace(tmp, path)

    # -- pacing -------------------------------------------------------------
    def _pace(self):
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _after_response(self, resp, path):
        remaining = resp.headers.get("X-RateLimit-Remaining")
        limit = resp.headers.get("X-RateLimit-Limit")
        if limit and limit.isdigit() and int(limit) != self.rate_limit:
            self.rate_limit = int(limit)
            self.min_interval = self.window_seconds / max(self.rate_limit, 1)
        if remaining is not None and remaining.isdigit():
            r = int(remaining)
            if self._window_started is None or r >= self.rate_limit - 1:
                self._window_started = time.time()
            if r <= 2:
                # Pause before the counter reaches zero, then start a fresh window.
                elapsed = time.time() - (self._window_started or time.time())
                sleep_for = max(5.0, self.window_seconds - elapsed + 2.0)
                self.log["rate_limit_pauses"] += 1
                sys.stderr.write(f"  rate limit nearly spent ({r} left) after {path}; pausing {sleep_for:.0f}s\n")
                time.sleep(sleep_for)
                self._window_started = None

    # -- requests -----------------------------------------------------------
    def get(self, path, params=None, raw_text=False, base=None, ttl=None):
        """GET an endpoint (or any URL when base is given) with caching."""
        params = dict(params or {})
        url = (base.rstrip("/") + path) if base else (API_BASE.rstrip("/") + path)
        cpath = self._cache_path(url, params)
        if not self.refresh or ttl:
            entry = self._read_cache(cpath, ttl=ttl)
            if entry is not None:
                self.log["cache_hits"] += 1
                self.log["endpoints"][path if not base else url] += 1
                return entry["text"] if raw_text else entry["body"]
        if self.offline:
            raise RuntimeError(f"offline build: no cached response for {path} {params}")

        last_err = None
        for attempt in range(7):
            self._pace()
            try:
                resp = self.session.get(url, params=params, timeout=60)
            except requests.RequestException as exc:
                last_err = exc
                sleep = min(300, 2 ** attempt * 5)
                self.log["backoffs"] += 1
                sys.stderr.write(f"  network error on {path}: {exc.__class__.__name__}; retry in {sleep}s\n")
                time.sleep(sleep)
                continue
            self._last_call = time.time()
            self.log["requests"] += 1
            self.log["endpoints"][path if not base else url] += 1
            if resp.status_code == 200:
                self._after_response(resp, path)
                if raw_text:
                    self._write_cache(cpath, url, params, 200, None, resp.text)
                    return resp.text
                body = resp.json()
                self._write_cache(cpath, url, params, 200, body)
                return body
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep = int(retry_after) if retry_after and retry_after.isdigit() else min(900, 2 ** attempt * 15)
                self.log["backoffs"] += 1
                sys.stderr.write(f"  429 on {path}; backing off {sleep}s\n")
                time.sleep(sleep)
                self._window_started = None
                continue
            if resp.status_code in (500, 502, 503, 504):
                sleep = min(300, 2 ** attempt * 5)
                self.log["backoffs"] += 1
                sys.stderr.write(f"  HTTP {resp.status_code} on {path}; retry in {sleep}s\n")
                time.sleep(sleep)
                continue
            if resp.status_code == 404 and raw_text:
                return None
            raise RuntimeError(f"HTTP {resp.status_code} on {path}: {resp.text[:300]}")
        raise RuntimeError(f"gave up on {path} after retries: {last_err}")

    def paginate(self, path, params, mode="last_indexes", ttl=None):
        """Collects every result page. 'last_indexes' uses OpenFEC's keyset
        pagination (schedule_a/b/e); 'page' uses page numbers."""
        params = dict(params)
        params.setdefault("per_page", PER_PAGE)
        results = []
        if mode == "page":
            page = 1
            while True:
                params["page"] = page
                body = self.get(path, params, ttl=ttl)
                results.extend(body.get("results", []))
                pages = (body.get("pagination") or {}).get("pages", 1) or 1
                if page >= pages:
                    break
                page += 1
            return results
        last = None
        seen_pages = 0
        while True:
            p = dict(params)
            if last:
                p.update(last)
            body = self.get(path, p, ttl=ttl)
            batch = body.get("results", [])
            results.extend(batch)
            seen_pages += 1
            li = (body.get("pagination") or {}).get("last_indexes") or {}
            if not batch or not li or len(batch) < params["per_page"]:
                break
            last = {k: v for k, v in li.items() if v is not None}
            if seen_pages > 2000:
                self.log["warnings"].append(f"stopped paginating {path} after 2000 pages")
                break
        return results


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------

def pull_candidate(client, cand, log):
    cid = cand["committee_id"]
    out = {}
    out["totals"] = client.get(f"/committee/{cid}/totals/", {"cycle": CYCLE}).get("results", [])
    out["reports"] = client.paginate(f"/committee/{cid}/reports/", {"cycle": CYCLE, "sort": "-coverage_end_date"}, mode="page")
    out["efile_reports"] = client.paginate("/efile/reports/house-senate/", {"committee_id": cid, "sort": "-receipt_date"}, mode="page")
    out["schedule_a"] = client.paginate("/schedules/schedule_a/", {
        "committee_id": cid, "two_year_transaction_period": CYCLE, "sort": "-contribution_receipt_date",
        "sort_null_only": "false",
    })
    out["schedule_b"] = client.paginate("/schedules/schedule_b/", {
        "committee_id": cid, "two_year_transaction_period": CYCLE, "sort": "-disbursement_date",
    })
    out["schedule_e"] = client.paginate("/schedules/schedule_e/", {
        "candidate_id": cand["candidate_id"], "min_date": f"{CYCLE - 1}-01-01", "sort": "-expenditure_date",
    })
    out["schedule_e_efile"] = client.paginate("/schedules/schedule_e/efile/", {
        "candidate_id": cand["candidate_id"], "min_date": f"{CYCLE - 1}-01-01", "sort": "-expenditure_date",
    }, mode="page")
    out["schedule_f"] = client.paginate("/schedules/schedule_f/", {
        "candidate_id": cand["candidate_id"], "sort": "-expenditure_date",
    }, mode="page")
    out["filings_f6"] = client.paginate("/filings/", {
        "committee_id": cid, "form_type": "F6", "sort": "-receipt_date",
    }, mode="page")
    out["efile_filings_f6"] = client.paginate("/efile/filings/", {
        "committee_id": cid, "form_type": "F6", "sort": "-receipt_date",
    }, mode="page")
    return out


def pull_raw_after(client, cand, pulled):
    """Raw e-filed Schedule A/B rows from filings the FEC has not yet
    processed. Pulled from the timeline start; any row whose filing already
    appears in the processed itemized data is dropped, so a report whose
    summary is processed but whose line items still lag is not lost."""
    cid = cand["committee_id"]
    processed_files_a = {r.get("file_number") for r in pulled["schedule_a"] if r.get("file_number")}
    processed_files_b = {r.get("file_number") for r in pulled["schedule_b"] if r.get("file_number")}
    # Latest coverage end among reports whose line items the FEC has processed.
    covered = [iso_date(r.get("coverage_end_date")) for r in pulled["reports"]
               if first(r, "file_number", "fec_file_id") in (processed_files_a | processed_files_b) and r.get("coverage_end_date")]
    start = (dt.date.fromisoformat(max(covered)) + dt.timedelta(days=1)).isoformat() if covered else f"{CYCLE - 1}-01-01"
    pulled["itemized_processed_through"] = max(covered) if covered else None
    sched_a = client.paginate("/schedules/schedule_a/efile/", {"committee_id": cid, "min_date": start, "sort": "-contribution_receipt_date"}, mode="page")
    sched_b = client.paginate("/schedules/schedule_b/efile/", {"committee_id": cid, "min_date": start, "sort": "-disbursement_date"}, mode="page")
    sched_a = [r for r in sched_a if r.get("file_number") not in processed_files_a]
    sched_b = [r for r in sched_b if r.get("file_number") not in processed_files_b]
    return sched_a, sched_b


def pull_primary_committee(client, pc, ttl=None):
    return client.paginate("/schedules/schedule_a/", {
        "committee_id": pc["committee_id"], "two_year_transaction_period": CYCLE,
        "sort": "-contribution_receipt_date", "sort_null_only": "false",
    }, ttl=ttl)


def pull_contribution_limit(client, log):
    """Reads the 2025-26 per-election individual limit from FEC.gov rather
    than hardcoding it. Returns status 'not_retrieved' (and the page says so)
    if the page cannot be read or parsed."""
    result = {"individual_per_election": None, "source_url": LIMITS_URL, "retrieved_at": None,
              "status": "not_retrieved", "cycle_label": "2025-26"}
    try:
        html = client.get("", {}, raw_text=True, base=LIMITS_URL)
    except Exception as exc:  # noqa: BLE001
        log["warnings"].append(f"contribution limit page not retrieved: {exc.__class__.__name__}")
        return result
    if not html:
        return result
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # The limits table lists donors by row; the first "per election" figure in
    # the table is the individual-to-candidate-committee limit.
    m = re.search(r"\$\s?([\d,]{4,7})\s*\*?\s*per election", text, re.IGNORECASE)
    if m:
        result["individual_per_election"] = int(m.group(1).replace(",", ""))
        result["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        result["status"] = "retrieved"
        y = re.search(r"(20\d\d)\s*[-–]\s*(20\d\d|\d\d)", text)
        if y:
            result["cycle_label"] = f"{y.group(1)}-{y.group(2)[-2:]}"
    else:
        log["warnings"].append("contribution limit page retrieved but the per-election figure was not found")
    return result


# ---------------------------------------------------------------------------
# F6 (48-hour notice) parsing
# ---------------------------------------------------------------------------

# Version 8.x Form 6 line layout (verified against live filings): the
# contributor's FEC ID sits between ZIP and date; employer and occupation
# follow the amount. The parser locates the eight-digit date rather than
# trusting the position, so a shifted column is caught, not misread.
F65_FIELDS = ["form_type", "filer_committee_id", "transaction_id", "entity_type", "contributor_organization_name",
              "contributor_last_name", "contributor_first_name", "contributor_middle_name", "contributor_prefix",
              "contributor_suffix", "contributor_street_1", "contributor_street_2", "contributor_city",
              "contributor_state", "contributor_zip", "contributor_fec_id", "contribution_date", "contribution_amount",
              "contributor_employer", "contributor_occupation"]


def parse_f6(text, log):
    """Parses the F65 lines of a raw Form 6 filing. Uses the fecfile library
    when installed; otherwise a positional fallback for the version 8.x
    layout, which the build log notes."""
    rows = []
    try:
        import fecfile  # type: ignore
        parsed = fecfile.loads(text)
        for item in parsed.get("itemizations", {}).get("F65", []):
            rows.append({
                "entity_type": item.get("entity_type"),
                "contributor_organization_name": item.get("contributor_organization_name"),
                "contributor_last_name": item.get("contributor_last_name"),
                "contributor_first_name": item.get("contributor_first_name"),
                "contributor_city": item.get("contributor_city"),
                "contributor_state": item.get("contributor_state"),
                "contributor_zip": item.get("contributor_zip"),
                "contributor_employer": item.get("contributor_employer"),
                "contributor_occupation": item.get("contributor_occupation"),
                "contribution_date": iso_date(item.get("contribution_date")),
                "contribution_amount": to_float(item.get("contribution_amount"), None),
                "transaction_id": item.get("transaction_id"),
            })
        return rows
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        log["warnings"].append(f"fecfile could not parse an F6: {exc.__class__.__name__}; using positional fallback")
    delim = "\x1c" if "\x1c" in text else ","
    # str.splitlines() would split on the \x1c field separator, so split on newlines only.
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    header = lines[0] if lines else ""
    if "8." not in header:
        log["warnings"].append("F6 header is not version 8.x; positional F65 parse may be wrong")
    for line in lines:
        if not line.startswith("F65"):
            continue
        parts = [v.strip().strip('"') for v in line.split(delim)]
        if len(parts) < 18:
            log["warnings"].append(f"F65 line with only {len(parts)} fields skipped")
            continue
        rec = dict(zip(F65_FIELDS, parts))
        # Locate the date column (eight digits) after the address block.
        date_idx = next((i for i in range(14, len(parts)) if re.fullmatch(r"\d{8}", parts[i])), None)
        if date_idx is None:
            log["warnings"].append("F65 line with no eight-digit date; amount left blank")
            rec["contribution_amount"] = None
            rec["contribution_date"] = None
        else:
            if date_idx != 16:
                log["warnings"].append(f"F65 date found at column {date_idx + 1}, not 17; employer and occupation read relative to it")
            rec["contribution_date"] = iso_date(parts[date_idx])
            rec["contribution_amount"] = to_float(parts[date_idx + 1] if date_idx + 1 < len(parts) else None, None)
            rec["contributor_employer"] = parts[date_idx + 2] if date_idx + 2 < len(parts) else ""
            rec["contributor_occupation"] = parts[date_idx + 3] if date_idx + 3 < len(parts) else ""
        rows.append(rec)
    return rows


def build_late_notices(client, cand, pulled, log):
    """Every 48-hour notice (Form 6) filed in the late window, newest first,
    with each reported contribution."""
    filings = {}
    for src, rows in (("processed", pulled["filings_f6"]), ("raw", pulled["efile_filings_f6"])):
        for f in rows:
            fn = first(f, "file_number", "fec_file_id")
            if fn is None:
                continue
            fn = int(fn)
            rec = filings.get(fn, {"file_number": fn, "sources": set()})
            rec["sources"].add(src)
            rec["receipt_date"] = iso_date(first(f, "receipt_date", "filed_date", "load_timestamp")) or rec.get("receipt_date")
            rec["amendment_indicator"] = first(f, "amendment_indicator", default=rec.get("amendment_indicator"))
            prev = first(f, "previous_file_number", "amends_file", default=None)
            if prev is not None and int(prev) != fn:
                rec["previous_file_number"] = int(prev)
            if f.get("most_recent") is False or f.get("amended_by"):
                rec["most_recent"] = False
            rec.setdefault("most_recent", True)
            rec["fec_url"] = first(f, "fec_url", default=rec.get("fec_url")) or DOCQUERY_FEC.format(file_number=fn)
            rec["pdf_url"] = first(f, "pdf_url", default=rec.get("pdf_url"))
            filings[fn] = rec
    # An amended notice supersedes the one it amends.
    superseded = {int(r["previous_file_number"]) for r in filings.values() if r.get("previous_file_number")}
    amendments_excluded = 0
    notices = []
    for fn, rec in sorted(filings.items(), key=lambda kv: (kv[1].get("receipt_date") or "", kv[0]), reverse=True):
        if fn in superseded or rec.get("most_recent") is False:
            amendments_excluded += 1
            continue
        rd = rec.get("receipt_date")
        if rd and rd < LATE_WINDOW_START:
            continue
        contributions = []
        total = 0.0
        text = None
        try:
            text = client.get(f"/dcdev/posted/{fn}.fec", {}, raw_text=True, base="https://docquery.fec.gov")
        except Exception as exc:  # noqa: BLE001
            log["warnings"].append(f"could not download F6 {fn}: {exc.__class__.__name__}")
        if text:
            for r in parse_f6(text, log):
                name = clean(r.get("contributor_organization_name")) or clean(
                    f"{r.get('contributor_first_name') or ''} {r.get('contributor_last_name') or ''}")
                amt = r.get("contribution_amount")
                contributions.append({
                    "contributor": title_display(name),
                    "city": title_display(r.get("contributor_city")),
                    "state": (r.get("contributor_state") or "").upper(),
                    "employer": title_display(r.get("contributor_employer")),
                    "occupation": title_display(r.get("contributor_occupation")),
                    "date": r.get("contribution_date"),
                    "amount": amt,
                    "entity_type": r.get("entity_type"),
                })
                total += amt or 0.0
        notices.append({
            "candidate_key": cand["key"], "candidate": cand["name"], "file_number": fn,
            "filed": rd, "amended": (rec.get("amendment_indicator") or "N") not in ("N", "", None),
            "source": "raw filing, not yet processed by the Federal Election Commission" if rec["sources"] == {"raw"} else "processed",
            "filing_page": DOCQUERY_FORM_PAGE.format(committee_id=cand["committee_id"], file_number=fn),
            "fec_url": rec["fec_url"], "pdf_url": rec.get("pdf_url"),
            "contributions": contributions, "total": round(total, 2), "count": len(contributions),
            "before_window": bool(contributions) and all((x["date"] or "") < LATE_WINDOW_START for x in contributions),
        })
    log.setdefault("amendments_excluded", {})[f"{cand['key']}_f6"] = amendments_excluded
    return notices


# ---------------------------------------------------------------------------
# Classification of itemized rows
# ---------------------------------------------------------------------------

def is_memo(row):
    return (row.get("memo_code") or "").strip().upper() == "X" or (row.get("memo_entry") or "").strip().upper() == "Y"


def line_of(row):
    return (row.get("line_number") or "").strip().upper().replace("SA", "")


def election_bucket(row):
    e = (first(row, "election_type", "pgo", default="") or "").strip().upper()
    if not e:
        e = (row.get("fec_election_type_desc") or "").strip().upper()
    if not e:
        return "undesignated"
    if e.startswith("P"):
        return "primary"
    if e.startswith("G"):
        return "general"
    return "other"


def individual_rows(sched_a):
    """Positive, non-memo, individual-contribution-line rows from individual
    people: the universe for geography, the election split and crossover."""
    out = []
    for r in sched_a:
        if is_memo(r):
            continue
        amt = to_float(r.get("contribution_receipt_amount"))
        if amt <= 0:
            continue
        if line_of(r) not in ("11AI", "11A"):
            continue
        if (r.get("entity_type") or "IND").strip().upper() != "IND":
            continue
        out.append(r)
    return out


def row_date(r):
    return iso_date(first(r, "contribution_receipt_date", "disbursement_date", "expenditure_date", "dissemination_date"))


# ---------------------------------------------------------------------------
# Per-candidate build
# ---------------------------------------------------------------------------

def pick_latest_report(reports, efile_reports, log, cand):
    """Most recent report. Processed reports carry a most_recent flag (the
    newest version of an amended report); raw e-filed reports are used when
    they cover a later period than anything processed."""
    processed = [r for r in reports if r.get("most_recent") in (True, None)]
    superseded = [r for r in reports if r.get("most_recent") is False]
    log.setdefault("amendments_excluded", {})[f"{cand['key']}_reports"] = len(superseded)
    processed.sort(key=lambda r: (iso_date(r.get("coverage_end_date")) or "", iso_date(r.get("receipt_date")) or ""), reverse=True)
    latest_processed = processed[0] if processed else None
    raw_latest = None
    if efile_reports:
        er = sorted(efile_reports, key=lambda r: (iso_date(r.get("coverage_end_date")) or "", iso_date(r.get("receipt_date")) or ""), reverse=True)
        raw_latest = er[0]
    use_raw = False
    if raw_latest and (not latest_processed or (iso_date(raw_latest.get("coverage_end_date")) or "") > (iso_date(latest_processed.get("coverage_end_date")) or "")):
        use_raw = True
    chosen = raw_latest if use_raw else latest_processed
    if not chosen:
        return None, processed, False
    fn = first(chosen, "file_number", "fec_file_id")
    rep = {
        "report_type": first(chosen, "report_type"),
        "report_type_full": sentence_display(first(chosen, "report_type_full", "report_type")),
        "coverage_start": iso_date(first(chosen, "coverage_start_date")),
        "coverage_end": iso_date(first(chosen, "coverage_end_date")),
        "filed": iso_date(first(chosen, "receipt_date")),
        "file_number": fn,
        "filing_page": DOCQUERY_FORM_PAGE.format(committee_id=cand["committee_id"], file_number=fn) if fn else None,
        "fec_url": first(chosen, "fec_url", "html_url"),
        "pdf_url": first(chosen, "pdf_url"),
        "source": "raw filing, not yet processed by the Federal Election Commission" if use_raw else "processed",
        "cash_on_hand": to_float(first(chosen, "cash_on_hand_end_period", default=None), None),
        "debts": to_float(first(chosen, "debts_owed_by_committee", "debts_owed_by_cmte", default=None), None),
        "receipts_cycle": to_float(first(chosen, "total_receipts_ytd", "total_receipts_cycle", default=None), None),
        "disbursements_cycle": to_float(first(chosen, "total_disbursements_ytd", "total_disbursements_cycle", default=None), None),
        "receipts_period": to_float(first(chosen, "total_receipts_period", "total_receipts", default=None), None),
        "disbursements_period": to_float(first(chosen, "total_disbursements_period", "total_disbursements", default=None), None),
    }
    return rep, processed, use_raw


def category_totals_from(totals_row):
    t = totals_row or {}
    return {
        "individuals": to_float(first(t, "individual_contributions", default=0)),
        "party_committees": to_float(first(t, "political_party_committee_contributions", default=0)),
        "pacs_committees": to_float(first(t, "other_political_committee_contributions", default=0)),
        "candidate_contributions": to_float(first(t, "candidate_contribution", default=0)),
        "candidate_loans": to_float(first(t, "loans_made_by_candidate", default=0)),
        "other_loans": to_float(first(t, "all_other_loans", default=0)),
        "transfers": to_float(first(t, "transfers_from_other_authorized_committee", default=0)),
        "offsets": to_float(first(t, "offsets_to_operating_expenditures", default=0)),
        "other": to_float(first(t, "other_receipts", default=0)),
    }


def week_buckets(start_iso, end_iso):
    start = dt.date.fromisoformat(start_iso)
    end = dt.date.fromisoformat(end_iso)
    weeks = []
    cur = start
    while cur <= end:
        weeks.append((cur, cur + dt.timedelta(days=6)))
        cur += dt.timedelta(days=7)
    return weeks


def build_candidate(cand, pulled, raw_a, raw_b, limit, log):
    totals_rows = pulled["totals"]
    totals = totals_rows[0] if totals_rows else {}
    latest, processed_reports, latest_is_raw = pick_latest_report(pulled["reports"], pulled["efile_reports"], log, cand)

    # ---- headline totals (processed cumulative, or the raw latest report when newer)
    receipts = to_float(first(totals, "receipts", default=None), None)
    disbursements = to_float(first(totals, "disbursements", default=None), None)
    cash = to_float(first(totals, "last_cash_on_hand_end_period", "cash_on_hand_end_period", default=None), None)
    debts = to_float(first(totals, "last_debts_owed_by_committee", "debts_owed_by_committee", default=None), None)
    processed_through = iso_date(first(totals, "coverage_end_date", default=None))
    totals_source = "processed"
    if latest_is_raw and latest:
        if latest["receipts_cycle"] is not None:
            receipts = latest["receipts_cycle"]
        if latest["disbursements_cycle"] is not None:
            disbursements = latest["disbursements_cycle"]
        if latest["cash_on_hand"] is not None:
            cash = latest["cash_on_hand"]
        if latest["debts"] is not None:
            debts = latest["debts"]
        totals_source = latest["source"]
    if not totals:
        log["warnings"].append(f"{cand['name']}: no processed committee totals for cycle {CYCLE}")

    # The filer's own cycle-to-date column on the latest processed report,
    # for disclosure when it differs from the FEC's processed total.
    filed = {}
    if processed_reports:
        lp = processed_reports[0]
        filed = {"receipts": to_float(first(lp, "total_receipts_ytd", default=None), None),
                 "disbursements": to_float(first(lp, "total_disbursements_ytd", default=None), None),
                 "report": sentence_display(first(lp, "report_type_full", "report_type"))}
    categories = category_totals_from(totals)
    calculated = sum(categories.values())
    reported = to_float(first(totals, "receipts", default=0))
    diff = round(reported - calculated, 2)
    recon_status = "reconciled" if abs(diff) <= RECONCILIATION_TOLERANCE else "unreconciled"
    if recon_status == "unreconciled":
        categories["unreconciled"] = diff
    reconciliation = {"reported_total_receipts": reported, "calculated_category_total": round(calculated, 2),
                      "difference": diff, "status": recon_status, "tolerance": RECONCILIATION_TOLERANCE,
                      "basis": "processed committee totals"}

    # ---- itemized receipts: processed plus raw rows newer than processed coverage
    sched_a = [dict(r, _raw=False) for r in pulled["schedule_a"]]
    sched_a_raw = [dict(r, _raw=True) for r in raw_a]
    ind = individual_rows(sched_a)
    ind_raw = individual_rows(sched_a_raw)

    # election designation split (processed itemized individual rows)
    split = Counter()
    split_counts = defaultdict(set)
    all_keys = set()
    per_donor_general = Counter()
    per_donor_primary = Counter()
    raw_split = Counter()
    for r in ind + ind_raw:
        b = election_bucket(r)
        amt = to_float(r.get("contribution_receipt_amount"))
        split[b] += amt
        if r.get("_raw"):
            raw_split[b] += amt
        key = name_key(r.get("contributor_last_name"), r.get("contributor_first_name"), r.get("contributor_name")) + "|" + zip5(r.get("contributor_zip"))
        split_counts[b].add(key)
        all_keys.add(key)
        if b == "general":
            per_donor_general[key] += amt
        elif b == "primary":
            per_donor_primary[key] += amt
    itemized_ind_total = sum(split.values())
    at_limit_general = at_limit_primary = None
    if limit:
        at_limit_general = sum(1 for v in per_donor_general.values() if v >= limit - 0.005)
        at_limit_primary = sum(1 for v in per_donor_primary.values() if v >= limit - 0.005)
    election_split = {
        "primary": round(split["primary"], 2), "general": round(split["general"], 2),
        "other": round(split["other"], 2), "undesignated": round(split["undesignated"], 2),
        "itemized_individual_total": round(itemized_ind_total, 2),
        "contributors": {k: len(v) for k, v in split_counts.items()},
        "contributors_total": len(all_keys),
        "at_limit_general": at_limit_general, "at_limit_primary": at_limit_primary,
        "raw_general": round(raw_split["general"], 2), "raw_primary": round(raw_split["primary"], 2),
        "raw_undesignated": round(raw_split["undesignated"] + raw_split["other"], 2),
        "raw_total": round(sum(raw_split.values()), 2),
    }

    # geography (processed itemized individual rows)
    geo = Counter()
    towns = Counter()
    town_donors = defaultdict(set)
    states = Counter()
    district_towns = Counter()
    district_donors = defaultdict(set)
    town_display = {}
    raw_geo_total = 0.0
    for r in ind + ind_raw:
        amt = to_float(r.get("contribution_receipt_amount"))
        if r.get("_raw"):
            raw_geo_total += amt
        st = (r.get("contributor_state") or "").strip().upper()
        city = clean(r.get("contributor_city")).upper()
        bucket = geo_bucket(st, r.get("contributor_zip"), city)
        geo[bucket] += amt
        key = name_key(r.get("contributor_last_name"), r.get("contributor_first_name"), r.get("contributor_name")) + "|" + zip5(r.get("contributor_zip"))
        if city and st:
            label = f"{title_display(city)}, {st}"
            towns[label] += amt
            town_donors[label].add(key)
        if st:
            states[STATE_NAMES.get(st, st)] += amt
        if bucket == "in_district":
            t = town_canon(city)
            if t not in MA06_TOWN_KEYS:
                # ZIP matched but the town is not on the list; keep the filer's spelling
                t = city or "UNLISTED TOWN"
                town_display[t] = title_display(city) or "Unlisted town"
            else:
                town_display.setdefault(t, TOWN_DISPLAY.get(t) or title_display(next(x for x in MA06_TOWNS if town_canon(x) == t)))
            district_towns[t] += amt
            district_donors[t].add(key)
    geo_total = geo["in_district"] + geo["ma_other"] + geo["out_of_state"]
    for t in DISTRICT_TABLE_TOWNS:
        town_display.setdefault(t, TOWN_DISPLAY.get(t) or title_display(next(x for x in MA06_TOWNS if town_canon(x) == t)))
    district_table = []
    for t in sorted(set(DISTRICT_TABLE_TOWNS) | set(district_towns)):
        district_table.append({"town": town_display[t], "amount": round(district_towns[t], 2), "donors": len(district_donors[t])})
    district_table.sort(key=lambda x: (-x["amount"], x["town"]))
    geography = {
        "in_district": round(geo["in_district"], 2), "ma_other": round(geo["ma_other"], 2),
        "out_of_state": round(geo["out_of_state"], 2), "unknown": round(geo["unknown"], 2),
        "located_total": round(geo_total, 2), "raw_total": round(raw_geo_total, 2),
        "top_towns": [[k, round(v, 2), len(town_donors[k])] for k, v in towns.most_common(15)],
        "by_state": [[k, round(v, 2)] for k, v in states.most_common()],
        "district_towns": district_table,
    }

    # spending categories (processed, non-memo Schedule B)
    sched_b = [r for r in pulled["schedule_b"] if not is_memo(r)]
    raw_b_rows = [r for r in raw_b if not is_memo(r)]
    spend = Counter()
    raw_spend_total = 0.0
    for r in sched_b + raw_b_rows:
        amt = to_float(r.get("disbursement_amount"))
        spend[categorize_purpose(first(r, "disbursement_description", "disbursement_purpose_category", default=""))] += amt
        if r in raw_b_rows:
            raw_spend_total += amt
    spending = {
        "by_category": {k: round(spend[k], 2) for k in SPEND_ORDER if spend[k]},
        "itemized_total": round(sum(spend.values()), 2),
        "raw_total": round(raw_spend_total, 2),
        "reported_total_disbursements": disbursements,
        "rows": len(sched_b) + len(raw_b_rows),
        "raw_rows": len(raw_b_rows),
    }

    # weekly timeline since Sept. 2: processed plus raw rows after processed coverage
    all_a = [r for r in sched_a if not is_memo(r)] + [r for r in sched_a_raw if not is_memo(r)]
    all_b = [dict(r, _raw=False) for r in sched_b] + [dict(r, _raw=True) for r in raw_b if not is_memo(r)]
    last_date = TIMELINE_START
    for r in all_a + all_b:
        d = row_date(r)
        if d and d > last_date:
            last_date = d
    # Run through today (or the last dated row, if later) so quiet weeks show as empty.
    today = dt.date.today().isoformat()
    end = max(last_date, today, TIMELINE_START)
    weeks = []
    for ws, we in week_buckets(TIMELINE_START, end):
        wsi, wei = ws.isoformat(), we.isoformat()
        rec = {"week_start": wsi, "week_end": wei, "receipts": 0.0, "disbursements": 0.0, "raw_receipts": 0.0, "raw_disbursements": 0.0}
        for r in all_a:
            d = row_date(r)
            if d and wsi <= d <= wei:
                rec["raw_receipts" if r.get("_raw") else "receipts"] += to_float(r.get("contribution_receipt_amount"))
        for r in all_b:
            d = row_date(r)
            if d and wsi <= d <= wei:
                rec["raw_disbursements" if r.get("_raw") else "disbursements"] += to_float(r.get("disbursement_amount"))
        weeks.append({k: (round(v, 2) if isinstance(v, float) else v) for k, v in rec.items()})

    # party money: party-committee contributions (line 11B or party entity) and Schedule F
    party_rows = []
    for r in sched_a + sched_a_raw:
        if is_memo(r):
            continue
        if line_of(r) == "11B" or (r.get("entity_type") or "").strip().upper() == "PTY":
            fn = r.get("file_number")
            party_rows.append({
                "committee": title_display(r.get("contributor_name")), "amount": to_float(r.get("contribution_receipt_amount")),
                "date": row_date(r), "election": election_bucket(r), "raw": bool(r.get("_raw")),
                "filing_page": DOCQUERY_FORM_PAGE.format(committee_id=cand["committee_id"], file_number=fn) if fn else None,
            })
    coordinated = []
    for r in pulled["schedule_f"]:
        if is_memo(r):
            continue
        fn = r.get("file_number")
        pcid = first(r, "committee_id")
        coordinated.append({
            "committee": title_display(first(r, "committee_name", default=(r.get("committee") or {}).get("name") if isinstance(r.get("committee"), dict) else None)),
            "committee_id": pcid,
            "amount": to_float(r.get("expenditure_amount")), "date": row_date(r),
            "purpose": sentence_display(first(r, "expenditure_purpose_full", "expenditure_description", default="")),
            "payee": title_display(r.get("payee_name")),
            "filing_page": DOCQUERY_FORM_PAGE.format(committee_id=pcid, file_number=fn) if fn and pcid else None,
            "pdf_url": r.get("pdf_url"),
        })
    party_money = {
        "contributions": sorted(party_rows, key=lambda x: x["date"] or "", reverse=True),
        "contributions_total": round(sum(x["amount"] for x in party_rows), 2),
        "contributions_reported_total": categories.get("party_committees", 0.0),
        "coordinated": sorted(coordinated, key=lambda x: x["date"] or "", reverse=True),
        "coordinated_total": round(sum(x["amount"] for x in coordinated), 2),
    }

    spending_rate = (disbursements / receipts) if receipts else None

    return {
        "key": cand["key"], "name": cand["name"], "last_name": cand["last_name"],
        "party": cand["party"], "party_abbr": cand["party_abbr"],
        "candidate_id": cand["candidate_id"], "committee_id": cand["committee_id"],
        "committee_name": title_display(first(totals, "committee_name", default=None) or (pulled["reports"][0].get("committee_name") if pulled["reports"] else None) or cand["committee_id"]),
        "fec_candidate_url": f"https://www.fec.gov/data/candidate/{cand['candidate_id']}/?cycle={CYCLE}&election_full=true",
        "fec_committee_url": f"https://www.fec.gov/data/committee/{cand['committee_id']}/?cycle={CYCLE}",
        "totals": {
            "receipts": receipts, "disbursements": disbursements, "cash_on_hand": cash, "debts": debts,
            "spending_rate": spending_rate, "source": totals_source,
            "processed_through": processed_through,
            "itemized_processed_through": pulled.get("itemized_processed_through"),
            "filed_cycle": filed,
            "raw_through": max([row_date(r) for r in sched_a_raw if row_date(r)] + [row_date(r) for r in raw_b if row_date(r)], default=None),
            "individual_itemized": to_float(first(totals, "individual_itemized_contributions", default=None), None),
            "individual_unitemized": to_float(first(totals, "individual_unitemized_contributions", default=None), None),
            "refunds": to_float(first(totals, "contribution_refunds", default=None), None),
            "categories": {k: round(v, 2) for k, v in categories.items()},
        },
        "latest_report": latest,
        "reports_on_file": [
            {"report_type_full": sentence_display(first(r, "report_type_full", "report_type")), "coverage_start": iso_date(r.get("coverage_start_date")),
             "coverage_end": iso_date(r.get("coverage_end_date")), "filed": iso_date(r.get("receipt_date")),
             "receipts_period": to_float(first(r, "total_receipts_period", default=None), None),
             "disbursements_period": to_float(first(r, "total_disbursements_period", default=None), None),
             "cash_on_hand": to_float(first(r, "cash_on_hand_end_period", default=None), None),
             "amended": bool(r.get("is_amended")) or (r.get("amendment_indicator") or "N") != "N",
             "filing_page": DOCQUERY_FORM_PAGE.format(committee_id=cand["committee_id"], file_number=first(r, "file_number", "fec_file_id")) if first(r, "file_number", "fec_file_id") else None}
            for r in processed_reports
        ],
        "reconciliation": reconciliation,
        "election_split": election_split,
        "geography": geography,
        "spending": spending,
        "timeline_weekly": weeks,
        "party_money": party_money,
        "counts": {
            "schedule_a_rows": len(sched_a), "schedule_a_memo_rows": sum(1 for r in sched_a if is_memo(r)),
            "individual_rows": len(ind), "schedule_b_rows": len(pulled["schedule_b"]),
            "schedule_b_memo_rows": sum(1 for r in pulled["schedule_b"] if is_memo(r)),
            "raw_schedule_a_rows": len(raw_a), "raw_schedule_b_rows": len(raw_b),
        },
        "_individual_rows": ind + ind_raw,  # stripped before writing
        "_individual_rows_raw": ind_raw,  # stripped before writing
    }


# ---------------------------------------------------------------------------
# Outside spending (independent expenditures)
# ---------------------------------------------------------------------------

def build_outside_spending(cands, pulled_by_key, log):
    """Independent expenditures naming either candidate.

    The same expenditure can reach the FEC up to four ways: on a 24- or
    48-hour notice (Form 24) and later on the group's regular report (Form
    3X or 5), each of which exists first as a raw e-filing and then as
    processed data, and raw amounts arrive without cents. Rows are grouped
    by spender, side, whole-dollar amount, payee and date, and one row is
    kept per group in this order: processed report, processed notice, raw
    report, raw notice. Every notice row is kept separately for the
    24-hour list in the late-money section."""
    rows = []
    notices = []
    amendments_excluded = 0
    duplicates_dropped = 0

    def sig(r):
        return (first(r, "committee_id"), (r.get("support_oppose_indicator") or "").upper(),
                int(to_float(r.get("expenditure_amount"))), re.sub(r"[^A-Z0-9]", "", clean(r.get("payee_name")).upper()),
                iso_date(first(r, "dissemination_date", "expenditure_date")))

    def make_row(cand, src, r):
        is_notice = bool(r.get("is_notice")) or (r.get("filing_form") or "").upper() in ("F24", "F5N") or (r.get("report_type") or "").upper() in ("24", "48", "F24N", "F24A")
        fn = first(r, "file_number")
        cm = r.get("committee") if isinstance(r.get("committee"), dict) else {}
        group = title_display(first(r, "committee_name", "filer_name", default=None) or cm.get("name") or first(r, "committee_id"))
        spender_id = first(r, "committee_id") or cm.get("committee_id")
        raw = src == "raw"
        return {
            "candidate_key": cand["key"], "candidate": cand["name"],
            "group": group, "group_id": spender_id,
            "group_fec_url": f"https://www.fec.gov/data/committee/{spender_id}/" if spender_id else None,
            "side": "support" if (r.get("support_oppose_indicator") or "").upper() == "S" else "oppose",
            "election": election_bucket(r) if not raw else ("general" if election_bucket(r) == "general" else "primary" if election_bucket(r) == "primary" else "not_stated"),
            "amount": round(to_float(r.get("expenditure_amount")), 2),
            "purpose": sentence_display(first(r, "expenditure_description", "category_code_full", default="")),
            "payee": title_display(r.get("payee_name")),
            "date": iso_date(first(r, "dissemination_date", "expenditure_date")),
            "expenditure_date": iso_date(r.get("expenditure_date")),
            "form": (r.get("filing_form") or "").upper() or None,
            "is_notice": is_notice,
            "source": "raw filing, not yet processed by the Federal Election Commission" if raw else "processed",
            "file_number": fn,
            "filing_page": DOCQUERY_FORM_PAGE.format(committee_id=spender_id, file_number=fn) if fn and spender_id else None,
            "pdf_url": r.get("pdf_url"),
            "_rank": (0 if not raw else 2) + (1 if is_notice else 0),
        }

    for cand in cands:
        p = pulled_by_key[cand["key"]]
        groups = {}
        for src, lst in (("processed", p["schedule_e"]), ("raw", p["schedule_e_efile"])):
            for r in lst:
                if is_memo(r):
                    continue
                if r.get("most_recent") is False:
                    amendments_excluded += 1
                    continue
                row = make_row(cand, src, r)
                groups.setdefault(sig(r), []).append(row)
        kept = []
        for key, cand_rows in groups.items():
            cand_rows.sort(key=lambda x: x["_rank"])
            kept.append(cand_rows[0])
            duplicates_dropped += len(cand_rows) - 1
            notice_rows = [x for x in cand_rows if x["is_notice"]]
            if notice_rows:
                notices.append(notice_rows[0])
        # A notice often carries an estimate that the regular report later
        # states exactly, so a kept notice is dropped from the totals when
        # the same group reports the same payee, same side, within seven days.
        def payee_key(x):
            return re.sub(r"[^A-Z0-9]", "", (x["payee"] or "").upper())
        report_rows = [x for x in kept if not x["is_notice"]]
        for x in kept:
            if x["is_notice"]:
                twin = next((y for y in report_rows if y["group_id"] == x["group_id"] and y["side"] == x["side"]
                             and payee_key(y) == payee_key(x) and x["date"] and y["date"]
                             and abs((dt.date.fromisoformat(y["date"]) - dt.date.fromisoformat(x["date"])).days) <= 7), None)
                if twin:
                    duplicates_dropped += 1
                    continue
            rows.append(x)
    for r in rows + notices:
        r.pop("_rank", None)
    rows.sort(key=lambda x: (x["date"] or "", x["amount"]), reverse=True)
    notices.sort(key=lambda x: (x["date"] or "", x["amount"]), reverse=True)
    by_group = Counter()
    by_group_side = defaultdict(lambda: Counter())
    by_side = {c["key"]: {"support": 0.0, "oppose": 0.0, "support_general": 0.0, "oppose_general": 0.0, "count": 0} for c in cands}
    for r in rows:
        by_group[r["group"]] += r["amount"]
        by_group_side[r["group"]][f"{r['candidate_key']}_{r['side']}"] += r["amount"]
        by_side[r["candidate_key"]][r["side"]] += r["amount"]
        if r["election"] == "general":
            by_side[r["candidate_key"]][r["side"] + "_general"] += r["amount"]
        by_side[r["candidate_key"]]["count"] += 1
    log.setdefault("amendments_excluded", {})["independent_expenditures"] = amendments_excluded
    log["ie_duplicate_rows_dropped"] = duplicates_dropped
    return {
        "rows": rows,
        "notices": notices,
        "by_group": [{"group": g, "total": round(t, 2),
                      **{f"{c['key']}_{side}": round(by_group_side[g][f"{c['key']}_{side}"], 2) for c in cands for side in ("support", "oppose")}}
                     for g, t in by_group.most_common()],
        "by_side": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in by_side.items()},
        "total": round(sum(r["amount"] for r in rows), 2),
    }


def build_ie_24h(outside):
    return outside["notices"]


# ---------------------------------------------------------------------------
# Donor crossover
# ---------------------------------------------------------------------------

CROSSOVER_RULE = (
    "A donor to one of the six primary candidates is counted as a likely match when the normalized name "
    "(last name and first name, uppercased, with punctuation, spaces and suffixes such as Jr. removed) and the "
    "first five digits of the ZIP code on a Koh or Jones receipt equal those on the earlier receipt, and the Koh "
    "or Jones gift is dated after the donor’s first gift to that primary candidate. Only positive, non-memo "
    "contributions from individuals on the individual-contribution line count on either side. Two people who "
    "share a name and a ZIP code would be counted as one; a donor who moved or used a different name form "
    "would be missed."
)


def build_crossover(cands, general_candidates, primary_pulled, log):
    primary_donors = {}  # key -> {primary_key: {first_date, total, name, city, state}}
    for pc in PRIMARY_COMMITTEES:
        for r in individual_rows(primary_pulled[pc["key"]]):
            k = name_key(r.get("contributor_last_name"), r.get("contributor_first_name"), r.get("contributor_name"))
            z = zip5(r.get("contributor_zip"))
            if not k or not z:
                continue
            key = k + "|" + z
            d = row_date(r)
            amt = to_float(r.get("contribution_receipt_amount"))
            rec = primary_donors.setdefault(key, {})
            e = rec.setdefault(pc["key"], {"first_date": d, "total": 0.0, "name": person_display(r),
                                           "city": title_display(r.get("contributor_city")), "state": (r.get("contributor_state") or "").upper()})
            e["total"] += amt
            if d and (e["first_date"] is None or d < e["first_date"]):
                e["first_date"] = d
    rows = []
    summary = {}
    for gc in general_candidates:
        matches = {}
        for r in gc["_individual_rows"]:
            k = name_key(r.get("contributor_last_name"), r.get("contributor_first_name"), r.get("contributor_name"))
            z = zip5(r.get("contributor_zip"))
            key = k + "|" + z
            if not k or not z or key not in primary_donors:
                continue
            d = row_date(r)
            amt = to_float(r.get("contribution_receipt_amount"))
            earlier = {pk: e for pk, e in primary_donors[key].items() if e["first_date"] and d and d > e["first_date"]}
            if not earlier:
                continue
            m = matches.setdefault(key, {"name": person_display(r), "city": title_display(r.get("contributor_city")),
                                         "state": (r.get("contributor_state") or "").upper(), "general_total": 0.0,
                                         "general_after_primary": 0.0, "first_general_date": d, "last_general_date": d,
                                         "primary": {}, "raw": False})
            m["general_total"] += amt
            if r.get("_raw"):
                m["raw"] = True
            if d and d > PRIMARY_DATE:
                m["general_after_primary"] += amt
            if d and d < m["first_general_date"]:
                m["first_general_date"] = d
            if d and d > m["last_general_date"]:
                m["last_general_date"] = d
            for pk, e in earlier.items():
                m["primary"][pk] = {"candidate": next(p["name"] for p in PRIMARY_COMMITTEES if p["key"] == pk),
                                    "total": round(e["total"], 2), "first_date": e["first_date"]}
        by_primary = Counter()
        by_primary_dollars = Counter()
        for key, m in matches.items():
            for pk in m["primary"]:
                by_primary[pk] += 1
                by_primary_dollars[pk] += m["general_total"]
            rows.append({
                "general_key": gc["key"], "general_candidate": gc["name"], "donor": m["name"],
                "city": m["city"], "state": m["state"],
                "primary_candidates": sorted(m["primary"].values(), key=lambda x: x["first_date"] or ""),
                "primary_total": round(sum(x["total"] for x in m["primary"].values()), 2),
                "general_total": round(m["general_total"], 2),
                "general_after_primary": round(m["general_after_primary"], 2),
                "first_general_date": m["first_general_date"], "last_general_date": m["last_general_date"],
                "raw": m["raw"],
            })
        summary[gc["key"]] = {
            "matches": len(matches), "dollars": round(sum(m["general_total"] for m in matches.values()), 2),
            "dollars_after_primary": round(sum(m["general_after_primary"] for m in matches.values()), 2),
            "matches_after_primary": sum(1 for m in matches.values() if m["general_after_primary"] > 0),
            "by_primary_candidate": [{"key": p["key"], "candidate": p["name"], "matches": by_primary[p["key"]],
                                      "dollars": round(by_primary_dollars[p["key"]], 2)} for p in PRIMARY_COMMITTEES],
        }
    rows.sort(key=lambda r: (-r["general_total"], r["donor"]))
    return {
        "rule": CROSSOVER_RULE,
        "primary_candidates": [{"key": p["key"], "name": p["name"], "committee_id": p["committee_id"],
                                "donor_keys": sum(1 for k, v in primary_donors.items() if p["key"] in v)} for p in PRIMARY_COMMITTEES],
        "primary_donor_keys": len(primary_donors),
        "summary": summary,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scan_for_key(paths, api_key):
    if not api_key:
        return []
    hits = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, "rb") as f:
            if api_key.encode() in f.read():
                hits.append(p)
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="ignore cached API responses")
    ap.add_argument("--offline", action="store_true", help="use cached responses only; no network")
    ap.add_argument("--cache-ttl-hours", type=float, default=float(os.environ.get("FEC_CACHE_TTL_HOURS", "20")))
    ap.add_argument("--cache-dir", default=os.environ.get("FEC_CACHE_DIR", CACHE_DIR))
    ap.add_argument("--out-dir", default=DATA_DIR)
    ap.add_argument("--rate-limit", type=int, default=int(os.environ.get("FEC_RATE_LIMIT", "60")))
    ap.add_argument("--rate-window-seconds", type=int, default=int(os.environ.get("FEC_RATE_WINDOW_SECONDS", "60")))
    ap.add_argument("--primary-cache-ttl-hours", type=float, default=float(os.environ.get("FEC_PRIMARY_CACHE_TTL_HOURS", str(24 * 14))),
                    help="cache life for the six primary committees, whose campaigns are over")
    args = ap.parse_args()

    started = time.time()
    started_at = dt.datetime.now(dt.timezone.utc)
    api_key = os.environ.get("FEC_API_KEY", "").strip()
    if not api_key and not args.offline:
        sys.stderr.write("FEC_API_KEY is not set. Export it in the shell that runs this build; it is read from "
                         "the environment only and never written to any file.\n")
        sys.exit(2)

    log = {"started_at": started_at.isoformat(), "mode": "offline-cache" if args.offline else "live",
           "api_base": API_BASE, "cycle": CYCLE, "endpoints": Counter(), "warnings": []}
    client = FecClient(api_key, args.cache_dir, ttl_hours=args.cache_ttl_hours, refresh=args.refresh,
                       offline=args.offline, rate_limit=args.rate_limit, window_seconds=args.rate_window_seconds, log=log)

    print("Pulling contribution limit from FEC.gov ...")
    limit = pull_contribution_limit(client, log)

    pulled = {}
    raw_after = {}
    for cand in CANDIDATES:
        print(f"Pulling {cand['name']} ({cand['committee_id']}) ...")
        pulled[cand["key"]] = pull_candidate(client, cand, log)
        raw_after[cand["key"]] = pull_raw_after(client, cand, pulled[cand["key"]])

    primary_pulled = {}
    for pc in PRIMARY_COMMITTEES:
        print(f"Pulling primary-season donors for {pc['name']} ({pc['committee_id']}) ...")
        primary_pulled[pc["key"]] = pull_primary_committee(client, pc, ttl=dt.timedelta(hours=args.primary_cache_ttl_hours))

    print("Building ...")
    candidates = []
    for cand in CANDIDATES:
        raw_a, raw_b = raw_after[cand["key"]]
        candidates.append(build_candidate(cand, pulled[cand["key"]], raw_a, raw_b, limit.get("individual_per_election"), log))

    outside = build_outside_spending(CANDIDATES, pulled, log)
    for c in candidates:
        c["outside"] = outside["by_side"][c["key"]]

    notices = []
    for cand in CANDIDATES:
        notices.extend(build_late_notices(client, cand, pulled[cand["key"]], log))
    notices.sort(key=lambda n: (n["filed"] or "", n["file_number"]), reverse=True)
    for c in candidates:
        mine = [n for n in notices if n["candidate_key"] == c["key"]]
        c["late_money"] = {"notices_48h_count": len(mine), "notices_48h_total": round(sum(n["total"] for n in mine), 2),
                           "contributions_48h": sum(n["count"] for n in mine)}

    crossover = build_crossover(CANDIDATES, candidates, primary_pulled, log)
    for c in candidates:
        c["crossover"] = crossover["summary"][c["key"]]
        del c["_individual_rows"]
        del c["_individual_rows_raw"]

    now = dt.datetime.now(dt.timezone.utc)
    data_through = {c["key"]: (c["latest_report"] or {}).get("coverage_end") for c in candidates}
    dashboard = {
        "meta": {
            "schema_version": SCHEMA_VERSION, "edition": "general",
            "district": "Massachusetts' 6th Congressional District", "district_abbr": "MA-06",
            "election_date": ELECTION_DATE, "primary_date": PRIMARY_DATE, "cycle": CYCLE,
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "generated_at_display": ap_datetime(now),
            "last_checked_display": ap_datetime(now),
            "data_through": data_through,
            "build_mode": log["mode"],
            "source": {"name": "Federal Election Commission", "api": API_BASE},
        },
        "candidates": candidates,
        "limits": limit,
        "outside_spending": outside,
        "late_money": {
            "window_start": LATE_WINDOW_START, "window_end": LATE_WINDOW_END,
            "notices_48h": notices, "ie_24h": build_ie_24h(outside),
            "last_checked": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "last_checked_display": ap_datetime(now),
        },
        "crossover": crossover,
        "timeline": {"start": TIMELINE_START, "deadlines": FILING_DEADLINES},
        "methodology": {
            "zips": MA06_ZIPS, "towns": [title_display(t) for t in MA06_TOWNS],
            "category_rules": [{"category": label, "patterns": pats} for label, pats in CATEGORY_RULES],
            "crossover_rule": CROSSOVER_RULE,
            "reconciliation_tolerance": RECONCILIATION_TOLERANCE,
            "amendments_excluded": log.get("amendments_excluded", {}),
            "ie_duplicate_rows_dropped": log.get("ie_duplicate_rows_dropped", 0),
        },
    }

    os.makedirs(args.out_dir, exist_ok=True)
    dash_path = os.path.join(args.out_dir, "dashboard.json")
    with open(dash_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, separators=(",", ":"), ensure_ascii=False)

    log["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    log["run_seconds"] = round(time.time() - started, 1)
    log["endpoints"] = dict(sorted(log["endpoints"].items()))
    log["record_counts"] = {
        **{c["key"]: c["counts"] for c in candidates},
        "independent_expenditures": len(outside["rows"]),
        "notices_48h": len(notices),
        "crossover_rows": len(crossover["rows"]),
        "primary_schedule_a_rows": {k: len(v) for k, v in primary_pulled.items()},
    }
    log["reconciliation"] = {c["key"]: c["reconciliation"] for c in candidates}
    log["contribution_limit"] = limit
    log["spot_check"] = {
        c["key"]: {
            "compare_at": c["fec_candidate_url"],
            "figures": {
                "total_receipts": c["totals"]["receipts"], "total_disbursements": c["totals"]["disbursements"],
                "cash_on_hand": c["totals"]["cash_on_hand"], "debts": c["totals"]["debts"],
                "individual_itemized": c["totals"]["individual_itemized"],
            },
            "note": "Compare each figure to the FEC.gov candidate page for the 2026 cycle (election_full=true) and record the result in README.md before publishing.",
        } for c in candidates
    }
    log_path = os.path.join(args.out_dir, "build_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=1, ensure_ascii=False)

    hits = scan_for_key([dash_path, log_path], api_key)
    if hits:
        for p in hits:
            os.remove(p)
        sys.stderr.write("ABORT: the API key appeared in an output file; outputs removed.\n")
        sys.exit(3)

    print(f"Wrote {dash_path} and {log_path} in {log['run_seconds']}s "
          f"({log['requests']} requests, {log['cache_hits']} cache hits, {log['rate_limit_pauses']} rate-limit pauses).")
    for c in candidates:
        r = c["reconciliation"]
        print(f"  {c['name']}: receipts {c['totals']['receipts']}, reconciliation {r['status']} (difference {r['difference']})")
    if log["warnings"]:
        print("Warnings:")
        for w in log["warnings"]:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
