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

Upload these seven files, keeping the folder layout:

```
content/files/ma06-general/
├── styles.css
├── app.js
├── data/
│   ├── dashboard.json
│   ├── build_log.json
│   ├── copy.json
│   └── us-states-paths.json
└── assets/images/
    └── nameplate-horizontal.png
```

Ghost(Pro) has no file manager that lets you pick a folder, so use whichever of these the
site already has:

- **The theme repo's assets folder.** Put the files under `assets/ma06-general/` in
  `wdowd-arch/marblehead-independent-theme` and let the existing GitHub Actions deploy push
  them; then set `MA06_BASE` to
  `https://www.marbleheadindependent.com/assets/ma06-general/`. This is the cleanest route
  because a push updates the data files in one step.
- **SFTP or the host's file access**, if your Ghost plan allows it, straight into
  `content/files/ma06-general/`.
- **The editor's File card** as a fallback. Ghost stores each upload at
  `/content/files/<year>/<month>/<name>` and will not keep the `data/` and `assets/`
  subfolders, so this route needs every file in one folder and `MA06_BASE` plus the
  `data/` suffix adjusted in the card script (`window.MA06_DATA_BASE = MA06_BASE;`).

After uploading, open `https://www.marbleheadindependent.com/content/files/ma06-general/data/dashboard.json`
in a browser. It must return JSON, not a 404.

## 2. Create the page

1. Ghost Admin, **Pages**, **New page**.
2. Title: `MA-06 general election money` (the H1 inside the card carries the real headline;
   the page title is for the browser tab and the admin list).
3. Click the **+** in the editor, choose **HTML**, and paste the entire contents of
   `ghost/embed.html` into the card. Nothing else goes on the page.
4. Open the page settings (the gear icon, top right).
   - **Page URL**: `ma-06-general`
   - **Excerpt**: leave empty.
   - Untick **Show title and feature image** if the theme offers it, so the nameplate
     and headline inside the card are the first thing on the page.
5. In the same settings panel, open **Meta data**:
   - **Meta title**: `MA-06 general election money — The Marblehead Independent`
   - **Meta description**: `Dan Koh and Micah Jones head to head on receipts, spending,
     outside money, late contributions and donor geography in the Nov. 3, 2026, general
     election for Massachusetts' 6th Congressional District, built from Federal Election
     Commission filings.`
   - **Canonical URL**: `https://www.marbleheadindependent.com/ma-06-general/`
6. Optional, under **X card** and **Facebook card**: the same title and description.
   Ghost generates the Open Graph tags from these, which is why the card itself has none.
7. **Preview**, scroll the whole page on a phone-width preview, then **Publish**.

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

```bash
export FEC_API_KEY=...
python3 build_data.py --refresh
python3 tools/spot_check.py
```

Then re-upload, to the same folder, only:

- `data/dashboard.json`
- `data/build_log.json`
- `data/copy.json`, only when the headline or dek changed.

The page does not need to be edited or republished; browsers fetch the JSON with
`cache: no-cache`, so a reload shows the new figures. Nothing else changes unless
`index.html`, `app.js` or `styles.css` changed, in which case rerun
`python3 tools/make_embed.py`, re-upload the changed file and paste the regenerated
`ghost/embed.html` into the card again.

## Schedule

Daily through Tuesday, Nov. 3, 2026, and once more after the post-general report due
Dec. 3. The pre-general report (covering Oct. 1 through 14) is the next filing that will
change the overview tiles; rewrite the headline in `data/copy.json` when it does.
