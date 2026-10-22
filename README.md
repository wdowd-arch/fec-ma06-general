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
tools/spot_check.py    compares the build with the FEC's own totals
tools/make_embed.py    writes ghost/embed.html from index.html and ghost/manifest.json
tools/publish_ghost.py one-command daily refresh: build, spot-check, upload, update the page
ghost/embed.html       the Ghost HTML card (generated)
ghost/manifest.json    URLs Ghost assigned to the uploaded files (written by publish_ghost.py)
ghost/UPLOAD.md        publishing steps for marbleheadindependent.com/ma-06-general/
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
3. Raw e-filed Schedule A and B rows from filings whose line items the FEC has not yet
   processed (it processes a report's summary weeks before its line items), labeled
   "raw filing, not yet processed by the Federal Election Commission" and folded into the
   election split, geography, crossover, party, spending and timeline sections with the raw
   share stated.
4. Schedule A for the six primary committees (Andres-Beck, Beccia, Belsito, Jakious,
   Lancaster, Nguyen) for the donor crossover match.
5. Builds every section, reconciles each candidate's categories to reported total receipts,
   writes `data/dashboard.json` and `data/build_log.json`, then scans both for the key.

Amended reports: only the newest version is used (`most_recent`); superseded versions are
counted in `build_log.json` under `amendments_excluded`. Memo and conduit entries
(`memo_code = X`) are excluded from every total. Independent expenditures reach the FEC up to
four times (24-hour notice and regular report, each raw and then processed, raw amounts
without cents), so rows are matched on spender, side, whole-dollar amount, payee and date and
one is kept per match, preferring the processed report; a notice is also dropped from the
totals when the same group reports the same payee within seven days. The 24-hour list in the
late-money section keeps every notice.

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
The file records which build the current headline was written from; rewrite it when a new
filing changes the story (the pre-general report due Oct. 22 and the post-general report due
Dec. 3 are the likely occasions).

## Quality checks before publishing

```bash
# 1. Reconciliation: each candidate's categories vs. reported total receipts
python3 -c "import json;d=json.load(open('data/build_log.json'));print(json.dumps(d['reconciliation'],indent=1))"

# 2. Spot-check five figures per candidate against FEC.gov
python3 tools/spot_check.py
#    Compares total receipts, total disbursements, cash on hand, debts and itemized individual
#    contributions with the candidate-totals endpoint that the FEC.gov candidate page displays,
#    checks that each figure appears on the summary line of the committee's own raw filing, and
#    compares every group's independent-expenditure total with the FEC's per-candidate totals.

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

### Spot-check record, build of Oct. 22, 2026, 7:45 p.m.

Both pre-general reports (Form 3, 12G, covering Oct. 1 through Oct. 14) were filed Oct. 22
and the page uses their raw summary lines: Koh receipts $5,383,420.65, disbursements
$4,302,794.83, cash on hand $1,081,990.54, debts $234,000; Jones receipts $619,903.76,
disbursements $450,121.61, cash on hand $169,782.15, debts $0. The FEC's processed
candidate-totals endpoint still stops at Sept. 30, so `tools/spot_check.py` reports those
six figures as mismatches against it (the Sept. 30 figures below) while confirming that
each one appears on the summary line of the committee's own raw filing (file numbers 2038378
and 2038923). Debts and itemized individual contributions (processed, through Sept. 30)
matched. Both processed independent-expenditure totals still matched (New Leadership PAC
$1,055,318.67 and Think Big $705,312.66, both supporting Koh); two groups opposing Koh
(Guardrails Alliance $30,910, United Future PAC $20,000) appear only in 24-hour notices or
raw filings and have no FEC per-candidate total yet. Both candidates reconciled to the cent
against processed totals.

### Spot-check record, build of Oct. 22, 2026, 4:50 p.m.

All 10 candidate figures (five each) matched the FEC candidate-totals endpoint to the cent:
Koh receipts $5,251,469.39, disbursements $4,253,534.06, cash on hand $999,275.05, debts
$234,000, itemized individual contributions $4,531,906.27; Jones receipts $586,090.76,
disbursements $370,619.67, cash on hand $215,471.09, debts $0, itemized individual
contributions $530,826.67. Nine of 10 raw-filing checks matched; the exception is Koh's own
October quarterly, which lists cycle-to-date disbursements of $4,253,559.06, $25 more than the
FEC's processed total. The page uses the processed figure and states the difference. Both
groups with processed independent expenditures matched the FEC's per-candidate totals
(New Leadership PAC $1,055,318.67 supporting Koh; Think Big $705,312.66 supporting Koh).

## Run it locally

Browsers block `fetch()` from `file://` pages, so serve the folder:

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

## Publish on marbleheadindependent.com/ma-06-general/

The page is a Ghost page containing one HTML card, `ghost/embed.html`: a script holding the
uploaded files' URLs, the `<div id="ma06-app">` block from `index.html`, and the loader for
`app.js`. `tools/publish_ghost.py` does the whole refresh in one command, reading every
credential from the environment:

```bash
export FEC_API_KEY=... GHOST_ADMIN_API_KEY=id:secret GHOST_ADMIN_URL=https://www.marbleheadindependent.com
python3 tools/publish_ghost.py --setup   # once: upload every file, create the page as a draft
python3 tools/publish_ghost.py           # daily: build, spot-check, upload the data, update the card
```

The daily run stops if the build or the spot-check fails, uploads only `data/dashboard.json`
and `data/build_log.json` (plus `data/copy.json` when the headline changed), records the
URLs Ghost assigned in `ghost/manifest.json`, regenerates `ghost/embed.html` with
`tools/make_embed.py` and rewrites the page's card without changing its draft or published
status. Step-by-step instructions, the manual alternative and what to publish are in
**[ghost/UPLOAD.md](ghost/UPLOAD.md)**.

Every style rule is scoped under `#ma06-app`, so the theme's own styles are untouched, and the
card sets no Open Graph tags because Ghost generates them from the page's meta settings.

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
