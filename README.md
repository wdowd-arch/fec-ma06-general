# MA-06 general election campaign finance dashboard

The Marblehead Independent's head-to-head money tracker for Dan Koh (D) and Micah Jones (R)
in the Tuesday, Nov. 3, 2026, general election for Massachusetts' 6th Congressional District.
It is the general-election edition of the primary-season dashboard in `wdowd-arch/fec-ma06`
and reuses that edition's brand tokens, component classes, section pattern, accessibility
features and methodology rules (ZIP/town geography estimate, spending keyword rules,
amendment and memo handling, reconciliation).

```
build_data.py          pulls the OpenFEC API and writes data/dashboard.json + data/build_log.json
index.html             the page (standalone, or paste the body into a Ghost HTML card)
styles.css             brand tokens and every component style, scoped under #ma06-app
app.js                 renders the JSON; every number and date formatter follows the copy rules
data/
  copy.json            editor-owned headline, dek and byline (the build never touches it)
  us-states-paths.json U.S. map paths (static, from the primary edition)
  dashboard.json       generated, do not hand-edit
  build_log.json       generated: endpoints hit, record counts, amendments excluded,
                       reconciliation results, run time, spot-check figures
assets/images/         nameplate
tools/copy_audit.py    copy audit on the rendered page
tools/check_no_key.py  fails if the API key appears anywhere in the tree
cache/                 API response cache (gitignored)
```

## Set the key

The build reads the key from the `FEC_API_KEY` environment variable and nowhere else. It is
sent in the `X-Api-Key` header, never in a URL, and never written to any file. Do not put it
in a `.env` file inside this repository and do not paste it into the HTML, JSON or JavaScript.

```bash
export FEC_API_KEY=your_key_here      # macOS / Linux, for this shell only
```

```powershell
$env:FEC_API_KEY = "your_key_here"    # Windows PowerShell, for this session only
```

Get a key at <https://api.open.fec.gov/developers/>. The key's rate limit is read from the
`X-RateLimit-Limit` and `X-RateLimit-Remaining` headers on every response; the client paces
requests to the limit, pauses before the counter reaches zero, backs off on 429 responses and
caches every response in `cache/` so a re-run on the same day costs almost no requests.
Defaults assume 60 requests per 60-second window; override with `FEC_RATE_LIMIT` and
`FEC_RATE_WINDOW_SECONDS` if the key's window is longer.

## Run the build

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # requests; fecfile and playwright are optional
export FEC_API_KEY=...
python3 build_data.py                  # daily run
python3 build_data.py --refresh        # ignore the cache (after a filing deadline)
python3 build_data.py --offline        # rebuild from cache only, no network
```

What it does, in order:

1. Reads the 2025-26 per-election individual contribution limit from the FEC.gov limits page
   (not hardcoded; if the page cannot be read the page says so and skips at-limit counts).
2. For each candidate: committee totals and reports (processed), raw e-filed report summaries,
   processed Schedule A and B for the 2026 cycle, Schedule E (independent expenditures)
   processed and raw, Schedule F (coordinated party expenditures), and Form 6 48-hour notices
   from both the processed and raw filing indexes, downloading each Form 6 from docquery.
3. Raw e-filed Schedule A and B rows dated after the processed coverage end, labeled
   "raw filing, not yet processed by the Federal Election Commission."
4. Schedule A for the six primary committees (Andres-Beck, Beccia, Belsito, Jakious,
   Lancaster, Nguyen) for the donor crossover match.
5. Builds every section, reconciles each candidate's categories to reported total receipts,
   writes `data/dashboard.json` and `data/build_log.json`, then scans both for the key.

Amended reports: only the newest version is used (`most_recent`); superseded versions are
counted in `build_log.json` under `amendments_excluded`. Memo and conduit entries
(`memo_code = X`) are excluded from every total.

## Schedule

Run once a day through Nov. 3, and once more after the Dec. 3 post-general report:

```
# crontab, 7 a.m. Eastern daily through Election Day, then Dec. 4
0 7 * 10,11 *  cd /path/to/fec-ma06-general && . .venv/bin/activate && FEC_API_KEY=... python3 build_data.py --refresh >> logs/build.log 2>&1
0 7 4 12 *     cd /path/to/fec-ma06-general && . .venv/bin/activate && FEC_API_KEY=... python3 build_data.py --refresh >> logs/build.log 2>&1
```

Keep the key in the crontab or the scheduler's secret store, not in the repository.
After each run, upload the new `data/dashboard.json` and `data/build_log.json` (see Ghost
below) and, when the numbers change the story, rewrite `data/copy.json`.

## Headline and dek

`data/copy.json` holds the headline, dek and byline. The build never writes it. Write the
headline and dek only after reviewing a fresh build, on the most newsworthy verified finding,
applying the same standard to both candidates. Sentence-style capitalization; present tense
for immediate action, an infinitive for anything to come; never begin with an article; never
split a verb phrase; the dek must not repeat any word in the headline; curly quotes only.
The shipped file is marked `"status": "placeholder"` for that reason.

## Quality checks before publishing

```bash
# 1. Reconciliation: each candidate's categories vs. reported total receipts
python3 -c "import json;d=json.load(open('data/build_log.json'));print(json.dumps(d['reconciliation'],indent=1))"

# 2. Spot-check five figures per candidate against FEC.gov (URLs and figures are in the log)
python3 -c "import json;d=json.load(open('data/build_log.json'));print(json.dumps(d['spot_check'],indent=1))"
#    Compare total receipts, total disbursements, cash on hand, debts and itemized individual
#    contributions with the candidate page for the 2026 cycle and note any difference here.

# 3. No key anywhere
python3 tools/check_no_key.py

# 4. Copy audit on the rendered page
python3 -m http.server 8000 &      # from the project root
pip install playwright && playwright install chromium
python3 tools/copy_audit.py http://localhost:8000/
```

The copy audit fails on straight quotes, the word "percent," a % without a stated base and
dollar amount, a wrongly abbreviated or unabbreviated month, an ordinal on a date, "12 p.m."
or "12 a.m.," courtesy titles, banned phrases, an acronym used before or without its
introduction, and any word shared by the headline and dek. It prints possible Oxford commas
and unexplained all-caps tokens for review.

Test at phone width: the section nav becomes a jump menu below 821 px and every data table
reflows into labeled cards below 768 px (headers stay in the DOM for assistive technology).

## Run it locally

Browsers block `fetch()` from `file://` pages, so serve the folder:

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

## Upload to Ghost

The page reads its JSON from `window.MA06_DATA_BASE`, so it can live either as a standalone
page (the recommended route from the primary edition's hosting notes: a static host or a
subdomain) or inside a Ghost HTML card.

Ghost HTML card:

1. In Ghost Admin, upload `styles.css`, `app.js`, `data/dashboard.json`, `data/copy.json`,
   `data/us-states-paths.json` and `assets/images/nameplate-horizontal.png` (Settings, Labs,
   or any file host; note the folder URL, for example
   `https://www.marbleheadindependent.com/content/files/ma06-general/`).
2. Create a page, add an HTML card, and paste:

   ```html
   <link rel="stylesheet" href="https://…/ma06-general/styles.css">
   <script>window.MA06_DATA_BASE = "https://…/ma06-general/data/";</script>
   <!-- everything between <div id="ma06-app"> and </div> from index.html,
        with the nameplate src pointed at the uploaded image -->
   <script src="https://…/ma06-general/app.js"></script>
   ```

3. Each daily build only needs `dashboard.json` and `build_log.json` re-uploaded; the HTML
   card does not change. Replace `copy.json` when the headline changes.

Every style rule is scoped under `#ma06-app`, so the theme's own styles are untouched. Open
Graph tags are set once in `index.html`; Ghost sets its own on an embedded page, so do not
paste the `<head>`.

## What changed from the primary edition

- Two candidates, treated identically: the same tiles, order, wording and caveats for each.
- New sections: primary vs. general split with the limit read from FEC.gov, outside spending,
  late money (48-hour notices and 24-hour independent expenditure reports), donor crossover,
  party money, weekly timeline with deadlines marked.
- Fixes: one set of Open Graph tags, one copyright line, bars no longer floor at 2% (the
  fill is the exact share with a 2 px visible minimum and the exact value labeled), one
  display name per candidate.
- Kept: skip link, `aria-sort` on sortable headers, sr-only descriptions of every bar,
  `aria-live` row counts, `data-label` table reflow at phone width.
