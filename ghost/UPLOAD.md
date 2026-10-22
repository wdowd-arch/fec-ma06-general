# Publishing the dashboard at marbleheadindependent.com/ma-06-general/

The page is a Ghost page whose only content is one HTML card. The card loads the
stylesheet, the script and the data from a folder of uploaded files, so a daily build
only replaces two small JSON files and the page itself never changes.

Everything below assumes the files live at

```
https://www.marbleheadindependent.com/content/files/ma06-general/
```

That URL is the one constant at the top of `ghost/embed.html` (`MA06_BASE`). If the files
end up somewhere else, change that one line and paste the card again.

## 1. Upload the files

`tools/publish_ghost.py` does the uploads and the page through the Ghost Admin API. Set the
three credentials in the shell (never in a file in this repository) and run the one-time
setup, which uploads every file and creates the page as a draft:

```bash
export FEC_API_KEY=...               # OpenFEC key
export GHOST_ADMIN_API_KEY=id:secret # Ghost Admin, Settings, Integrations, Custom integration
export GHOST_ADMIN_URL=https://www.marbleheadindependent.com
python3 tools/publish_ghost.py --setup
```

Ghost stores uploads at `/content/files/<year>/<month>/<name>` (images under
`/content/images/`) and renames a repeat upload (`dashboard-2.json`), so the script records
each file's exact URL in `ghost/manifest.json`, regenerates `ghost/embed.html` from it, and
writes the card to the page. The embed's top block holds those URLs; nothing else needs the
folder layout.

If you prefer to upload by hand, the seven files are:

```
styles.css
app.js
data/dashboard.json
data/build_log.json
data/copy.json
data/us-states-paths.json
assets/images/nameplate-horizontal.png
```

Put them anywhere that serves them (one folder is simplest), then either edit
`ghost/manifest.json` with the URLs and run `python3 tools/make_embed.py`, or run
`python3 tools/make_embed.py --base <folder URL>` if every file sits in that one folder
under its original name. Open the dashboard.json URL in a browser afterward; it must return
JSON, not a 404.

## 2. The page

`--setup` creates the page with slug `ma-06-general`, title `MA-06 general election money`,
meta title `MA-06 general election money — The Marblehead Independent`, the meta
description from `index.html`, canonical URL `https://www.marbleheadindependent.com/ma-06-general/`
and one HTML card holding `ghost/embed.html`, left as a draft. The script prints the draft
preview link (`/p/<uuid>/`).

To publish: open the page in Ghost Admin, check the preview on a phone-width window, and
click **Publish**; or run `python3 tools/publish_ghost.py --no-build --publish`. In the page
settings, untick **Show title and feature image** if the theme offers it, so the nameplate
and headline inside the card come first.

To create the page by hand instead: Ghost Admin, **Pages**, **New page**; add an **HTML**
card and paste the whole of `ghost/embed.html`; in the settings panel set **Page URL** to
`ma-06-general`, and under **Meta data** the meta title, meta description and canonical URL
above.

## 3. Check the live page

- The headline from `data/copy.json` shows under the nameplate, and the overview tiles
  fill in. If the tiles say the data could not be loaded, the files are not at
  `MA06_BASE`; check the URL from step 1.
- The section navigation sticks below the theme's header. If the theme header is also
  sticky and the two overlap, add `#ma06-app .sectionnav { top: <header height>px; }` to
  Ghost's **Code injection**, Site header.
- Scroll to the geography section; the U.S. map should draw.
- Run the copy audit against the live page from the repo:
  `python3 tools/copy_audit.py https://www.marbleheadindependent.com/ma-06-general/`.

## 4. After each daily build

One command:

```bash
export FEC_API_KEY=... GHOST_ADMIN_API_KEY=... GHOST_ADMIN_URL=https://www.marbleheadindependent.com
python3 tools/publish_ghost.py
```

It runs `build_data.py --refresh` and `tools/spot_check.py` and stops if either fails;
uploads `data/dashboard.json` and `data/build_log.json` (and `data/copy.json` only when its
content changed since the last upload); records the new URLs in `ghost/manifest.json`;
regenerates `ghost/embed.html`; updates the page's card, keeping it draft or published as it
was; and scans every file it touched for the keys. `--no-build` skips the build (to push an
edited headline), `--dry-run` makes no uploads and no page write.

Commit `ghost/manifest.json`, `ghost/embed.html` and the two data files afterward so the
repository matches the site.

If `index.html`, `app.js` or `styles.css` changed, run `python3 tools/publish_ghost.py --setup`
again; it re-uploads everything and rewrites the card.

## Schedule

Daily through Tuesday, Nov. 3, 2026, and once more after the post-general report due
Dec. 3. The pre-general report (covering Oct. 1 through 14) is the next filing that will
change the overview tiles; rewrite the headline in `data/copy.json` when it does.
