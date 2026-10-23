#!/usr/bin/env python3
"""
Copy audit on the rendered page text.

Renders the dashboard in headless Chromium (Playwright), collects every
piece of reader-facing text (visible text plus alt, title and aria-label
attributes) and checks it against the newsroom's AP-based copy rules:

  - no straight quotes in visible text
  - no "percent," and every % states its base (and a dollar amount)
  - no unabbreviated Jan./Feb./Aug.-Dec. with a specific date, and no
    abbreviated March-July
  - no ordinal suffixes on dates, no "12 p.m." or "12 a.m."
  - no courtesy titles, no Oxford commas, no banned phrases
  - every acronym introduced once, on first use
  - headline and dek share no words

Usage:
    python3 -m http.server 8000           # from the project root, in one shell
    python3 tools/copy_audit.py http://localhost:8000/

Exits 1 when a hard rule fails. Oxford-comma and acronym findings print as
items to review, since the regex cannot always tell a series from an
appositive or a name from an acronym.
"""
import os
import re
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.stderr.write("playwright is required: pip install playwright && playwright install chromium\n")
    sys.exit(2)

BANNED = ["speaks to", "serves as a reminder", "paints a picture", "highlights the importance", "underscores the need",
          "in a broader sense", "at its core", "amid a changing landscape", "as the community grapples with",
          "a testament to", "sparked a conversation", "raised questions about", "only time will tell"]
LONG_MONTHS_ABBREV = r"\b(January|February|August|September|October|November|December) \d{1,2}\b"
SHORT_MONTHS_WRONG = r"\b(Mar|Apr|Jun|Jul|Sep)\.\s*\d{1,2}\b"
ORDINAL_DATE = r"\b(Jan\.|Feb\.|March|April|May|June|July|Aug\.|Sept\.|Oct\.|Nov\.|Dec\.) \d{1,2}(st|nd|rd|th)\b"
ALLOWED_CAPS = {"FEC", "MA-06", "ZIP", "LLC", "URL", "HTTP", "ID", "D", "R", "US"}


def collect(url):
    with sync_playwright() as p:
        # Honor a pre-installed browser (PLAYWRIGHT_CHROMIUM_PATH) when the bundled one is missing.
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#overview-metrics .metric-grid, #overview-metrics .empty-state", timeout=20000)
        # open any collapsible items (the phone version's methodology) and scroll so lazy content renders
        page.evaluate("document.querySelectorAll('#ma06-app details').forEach((d) => { d.open = true; })")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        page.wait_for_timeout(800)
        data = page.evaluate("""() => {
          const out = {segments: [], pct_blocks: [], headline: document.getElementById('headline').textContent, dek: document.getElementById('dek').textContent};
          // On a Ghost page the theme's own header and footer surround the card;
          // only the dashboard's text is ours to audit.
          const root = document.getElementById('ma06-app') || document.body;
          const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
          let n = walker.currentNode;
          while (n) {
            const cs = getComputedStyle(n);
            const hidden = cs.display === 'none' || cs.visibility === 'hidden';
            if (!hidden) {
              for (const attr of ['alt', 'title', 'aria-label', 'placeholder']) {
                const v = n.getAttribute(attr); if (v) out.segments.push('[' + attr + '] ' + v);
              }
              for (const c of n.childNodes) {
                if (c.nodeType === 3 && c.textContent.trim()) {
                  out.segments.push(c.textContent.trim());
                  // A % is judged with the text of its enclosing block (a tile
                  // column, legend item, paragraph or cell), where the base belongs.
                  if (c.textContent.includes('%')) {
                    const block = n.closest('p, li, td, th, h1, h2, h3, h4, .h2h > div, .item, button, .notice-card');
                    out.pct_blocks.push((block || n).innerText.replace(/\\s+/g, ' ').trim());
                  }
                }
              }
            }
            n = walker.nextNode();
          }
          return out;
        }""")
        browser.close()
    return data


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/"
    data = collect(url)
    segs = data["segments"]
    text = "\n".join(segs)
    failures, reviews = [], []

    for s in segs:
        if '"' in s or "'" in s:
            failures.append(f"straight quote: {s[:120]}")
    for m in re.finditer(r"\bpercent\b", text, re.IGNORECASE):
        failures.append(f"the word percent: …{text[max(0, m.start() - 40):m.end() + 40]}…")
    attr_pct = [s for s in segs if s.startswith("[") and "%" in s]
    for s in data["pct_blocks"] + attr_pct:
        if "%" in s:
            if " of " not in s and "base figure was not provided" not in s:
                failures.append(f"% without a stated base: {s[:140]}")
            elif "$" not in s and "base figure was not provided" not in s:
                failures.append(f"% without a dollar amount: {s[:140]}")
    for m in re.finditer(LONG_MONTHS_ABBREV, text):
        failures.append(f"month not abbreviated with a date: {m.group(0)}")
    for m in re.finditer(SHORT_MONTHS_WRONG, text):
        failures.append(f"month wrongly abbreviated: {m.group(0)}")
    for m in re.finditer(ORDINAL_DATE, text):
        failures.append(f"ordinal on a date: {m.group(0)}")
    for m in re.finditer(r"\b12 (a|p)\.m\.", text):
        failures.append(f"12 a.m./p.m. instead of midnight/noon: {m.group(0)}")
    for m in re.finditer(r"\b\d{1,2}(:\d\d)? ?(AM|PM)\b", text):
        failures.append(f"uppercase AM/PM: {m.group(0)}")
    for m in re.finditer(r"\b(Mr|Mrs|Ms|Dr)\.", text):
        failures.append(f"courtesy title: …{text[max(0, m.start() - 30):m.end() + 30]}…")
    for phrase in BANNED:
        if re.search(re.escape(phrase), text, re.IGNORECASE):
            failures.append(f"banned phrase: {phrase}")

    # Oxford comma: a sentence with two or more commas before ", and" / ", or".
    for s in segs:
        for sentence in re.split(r"(?<=[.;:!?])\s+", s):
            for m in re.finditer(r", (and|or) ", sentence):
                if sentence[:m.start()].count(",") >= 1:
                    reviews.append(f"possible Oxford comma: {sentence[:160]}")
                    break

    # Acronyms: each introduced form must be the first occurrence.
    intro = {}
    for m in re.finditer(r"\(([A-Z][A-Z0-9-]{1,})\)", text):
        intro.setdefault(m.group(1), []).append(m.start())
    for acr, positions in intro.items():
        if len(positions) > 1:
            failures.append(f"acronym introduced more than once: {acr}")
        first_use = re.search(r"(?<![A-Za-z-])" + re.escape(acr) + r"(?![A-Za-z-])", text)
        if first_use and first_use.start() < positions[0] - 1:
            failures.append(f"acronym used before it is introduced: {acr} at …{text[max(0, first_use.start() - 40):first_use.end() + 20]}…")
    for tok in sorted(set(re.findall(r"(?<![A-Za-z-])[A-Z]{3,}(?![A-Za-z-])", text))):
        if tok not in intro and tok not in ALLOWED_CAPS:
            reviews.append(f"all-caps token, acronym? {tok}")
    if "FEC" in text and "FEC" not in intro:
        failures.append("FEC is used but never introduced as Federal Election Commission (FEC)")

    hw = set(re.findall(r"[a-z0-9’'-]+", data["headline"].lower()))
    dw = set(re.findall(r"[a-z0-9’'-]+", data["dek"].lower()))
    shared = sorted(w for w in hw & dw if w)
    if shared:
        failures.append(f"headline and dek share words: {', '.join(shared)}")

    print(f"Audited {len(segs)} text segments from {url}")
    print(f"Headline: {data['headline']}\nDek: {data['dek']}\n")
    for f in failures:
        print("FAIL  " + f)
    for r in sorted(set(reviews)):
        print("REVIEW  " + r)
    print(f"\n{len(failures)} failures, {len(set(reviews))} items to review")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
