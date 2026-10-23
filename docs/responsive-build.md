# Desktop and mobile versions: build record

Record of the responsive build of the MA-06 general election money dashboard: the two
presentations, where they live in the code, what changed section by section, every
visible-text change, and what could not be verified here.

## File map

| Layer | Where | Notes |
|---|---|---|
| Shared data layer | `app.js`: `fetchJson`, `state`, formatters (`money`, `moneyProse`, `pct`, `pctOf`, `fmtDate`), `cands()`, every `render*` function's data preparation (`snapshotRows`, `late48Rows`, `renderTownTable` row building, timeline `max`) | Untouched calculations. Both versions read `state.data` and `state.copy` once; the map paths load once into `state.usMap`. |
| Version switch | `app.js`: `MOBILE_MQ = matchMedia("(max-width: 768px)")`, `state.mobile`, `applyVersionAttr`, `onVersionChange` | Sets `data-version` on `#ma06-app` and re-renders the components whose markup differs. No reload, no refetch (verified: zero network requests on a resize across 768 px). |
| Desktop presentation | `styles.css` part 2, `@media (min-width: 769px)` and the 1025 and 1280 px steps; `app.js` desktop branches: `renderCandidateCards` (cards), `renderUsMap` tooltip and inset, `renderTimeline` with four ticks, `renderMethodology` `<dl>` | 1,200 px content width, 32 px side padding, 24 px from 769 to 1,024 px. |
| Mobile presentation | `styles.css` part 3, `@media (max-width: 768px)`; `app.js` mobile branches: `renderSnapshotTable`, `renderTable` patterns (`cards`, `expand`, `scroll`), `tileValue` compact fallback, map small-state buttons, week-column tap, `renderMethodology` `<details>` items, `thinTimelineLabels` | 16 px gutters, 16 px inputs, 44 px targets, `env(safe-area-inset-*)`. |
| Markup | `index.html` | `srcset` on the nameplate and both headshots; map readout, inset and button hosts; methodology container; scroll cue; the jump menu that already existed. |
| Images | `assets/images/koh-480.jpg`, `jones-480.jpg`, `nameplate-horizontal-800.png` | Phone-size variants served through `srcset`/`sizes`. |
| Tools | `tools/copy_audit.py` | Opens any `<details>` before auditing instead of the removed methodology toggle. |

The Ghost embed route still works: `tools/make_embed.py` rewrites every `assets/` image
to `data-ma06-src` and sets `MA06_ASSET_BASE` for the script-rendered photos.

## What was built, by section

### Header, nameplate and status line
- Desktop: nameplate at full size; status line on one row where it fits; photos side by side at 860 px, caption beneath.
- Mobile: nameplate scaled to the gutters through `srcset` (800 px file); status line stacks one item per line with each label kept with its value (`.meta-label` is non-breaking); photos side by side, equal height, cropped to a square anchored to the top so faces stay in frame (`object-position: top`); caption beneath both.
- The landscape banner is removed.

### Section navigation
- Desktop: sticky bar with all 10 links and "MHD Indy Home"; the current section highlights on scroll. The bar wraps rather than clipping on narrower desktops: one row at 1,280 px and wider, two rows from 1,025 to 1,279 px, three at 769 to 1,024 px. `--nav-h` is set per range so every anchor clears it.
- Mobile: "MHD Indy Home" plus the full-width "Jump to a section" select, 44 px tall; the link bar is not rendered. Sticky height is 8 percent of a 667 px viewport.
- Both: `scroll-margin-top` on every section and methodology item. Verified: all 11 anchors land below the nav at 375, 769, 1,024, 1,280 and 1,440 px, and the skip link lands exactly at the nav's lower edge.
- Short viewports (under 520 px tall, a phone held sideways): the nav stops being sticky.

### Overview: "Where the two campaigns stand"
- Desktop: four tiles per row at 1,280 px and wider (the fifth and sixth tiles widen to two columns each so the second row has no empty cells), three from 1,025 to 1,279 px, two from 769 to 1,024 px.
- Mobile: one tile per row, Koh and Jones in two equal columns, labeled by name.
- Dollar format: exact figures as before ("$5,383,421"). The compact fallback ("$5.4M", full figure in `title` and `aria-label`) exists in `tileValue` and fires only on phones when the exact figure runs past 10 characters. No current figure does.
- The "Loading FEC data…" state has a minimum height so it fits the layout.

### Candidate snapshots
- Desktop: the two cards, side by side, with the receipts share bar in each.
- Mobile: one real `<table>` (measure | Koh | Jones), one measure per row, photos and names in the column headers, and a full-width row beneath "Total receipts" holding both share bars labeled by name. The raw-filing note appears once.

### Primary dollars vs. general dollars
- Desktop: paired, side by side.
- Mobile: stacked, Koh above Jones. Segment values were already outside the bar, in the legend; the bar is 44 px tall so each segment is a tap target.

### Outside spending
- Desktop: filters in one row; both tables in full, sticky header row, sortable headers, row highlight on hover and focus.
- Mobile: filters full width and stacked. "By group" uses priority columns with expand: Group and Total show; a "Show four more figures" button in each row reveals the support and oppose figures (`aria-expanded`). "Every independent expenditure" uses card rows; the FEC filing link in each card is a 44 px target.

### Late money
- Desktop: search and candidate filter in one row; 24-hour reports newest first.
- Mobile: search and filter full width and stacked; both tables as card rows; 24-hour reports newest first.

### Donor crossover
- Desktop: both search boxes in one row. Mobile: stacked, full width; card rows.

### Geography
- Location breakdown: side by side on desktop, stacked on mobile.
- Map, desktop: full content width with a fixed readout panel and a "New England and mid-Atlantic" inset beside it (`viewBox 778 98 184 194`, about three times the main scale). Hover shows a tooltip that follows the pointer; click, keyboard Tab and Enter or Space select a state, outline it on both maps and write its name and exact amount to the readout.
- Map, mobile: full gutter width; no tooltip; tap or focus writes the readout directly below the map; the inset sits below the readout; a row of nine 44 px buttons (VT, NH, MA, RI, CT, NJ, DE, MD, DC, each with its full name as `aria-label`) selects each small state by touch. A selection survives a version switch.
- Both: Tab selection, lazy loading and the ranked lists kept.
- Top cities and towns, Top states: side by side on desktop; stacked on mobile with the label and amount on one line and the bar beneath, labels wrapping.
- District towns: desktop full table, sticky header, sortable. Mobile: horizontal scroll with a sticky town column and the cue "Scroll sideways for donor counts."; column order on phones is Town, Koh dollars, Jones dollars, then the donor counts, so both candidates' dollars show at 375 px without scrolling.

### Party money
- Side by side on desktop, stacked on mobile; the empty states are unchanged prose.

### Timeline
- Both: one shared scale (`max` across both candidates); a y-axis with dollar ticks and dotted gridlines was added (four ticks on desktop, three on mobile). Bars are buttons: hover, focus and click write the exact value to a readout under each chart. Hatched raw bars, dashed deadline lines and the shaded window kept.
- Desktop: side by side at 1,280 px and wider, stacked below that; legend above.
- Mobile: stacked, receipts above disbursements within each week; short labels ("Sept. 2"); x-axis labels are thinned by measurement (every other label hidden when each would have under 54 px, every third under 27 px) and re-measured on a debounced resize or rotation; legend wraps; hatching widened to a 4 px stripe on a 9 px period; tapping anywhere in a week's column selects the week and reads out both figures.
- Timeline and spending render when their sections near the viewport, like the map.

### Spending
- Side by side on desktop; stacked on mobile with category labels wrapping and amounts visible on the label line.

### Methodology and footer
- Desktop: fully expanded `<dl>`; each subsection has an id (`#method-source` … `#method-limits`).
- Mobile: each subsection is a `<details>` item, collapsed by default, 44 px summary. A link to a subsection opens it: the geography note's "How the estimate works" now points to `#method-district`, and `hashchange` opens whichever item the hash names.
- Footer wraps (`overflow-wrap: anywhere`) and respects the bottom safe-area inset.

## Table patterns on phones

| Table | Pattern | Columns visible without a tap |
|---|---|---|
| Every independent expenditure | Card rows | All: Date, Group, Position ("Supports Koh" etc.), Election, Amount, Purpose, Payee, Form, Filing |
| By group | Priority columns with expand | Group, Total; the button reveals Supports Koh, Opposes Koh, Supports Jones, Opposes Jones |
| 48-hour notices | Card rows | All: Date received, Candidate, Contributor, City, Employer, Amount, Notice |
| 24-hour reports | Card rows | All |
| Likely matches | Card rows | All: Donor, City, Primary candidate (gift), Later gave to, Later gifts, Of that after Sept. 1, Most recent gift |
| District towns | Horizontal scroll, sticky town column | Town, Koh dollars, Jones dollars; donor counts by scroll |
| Top cities and towns, Top states | Single-column list | Place, amount |

Column names in the specification that do not exist in the code, and what was used: the
independent-expenditure tables have no "candidate" column; the Position column carries the
candidate ("Supports Koh", "Opposes Jones"). "Likely matches" has no "amount" column; "Later
gifts" is the amount. The 48-hour table's date is "Date received".

## Visible-text changes

Interface wording only; no headline, section intro, caption or methodology prose changed.

1. "Click a column header to sort." became "Select a column header to sort." (district towns note).
2. Removed: "↻ On a phone, turn it sideways; this dashboard is easier to read in landscape." (the landscape banner).
3. Removed: the methodology toggle "Show the full methodology ▾" / "Hide the full methodology ▴". The desktop methodology is fully expanded; the phone items show a plus or minus sign.
4. New: map readout default "No state selected. The amount appears here when a state is selected."; inset label "New England and mid-Atlantic"; button group "Small Northeastern states" (accessible name) with buttons VT, NH, MA, RI, CT, NJ, DE, MD and DC, each named in full for assistive technology.
5. New: timeline readout default "Select a bar for the week’s exact figures."; the readouts themselves ("Week of Sept. 30: $109,276 in itemized receipts, $39,157 in itemized disbursements (includes raw filings)."); y-axis dollar labels.
6. New: "Scroll sideways for donor counts." above the district towns table on phones.
7. New: "Show four more figures" / "Show fewer figures" buttons in the by-group table on phones.
8. New, phone snapshot table: bar labels "Koh, share of the larger figure" and "Jones, share of the larger figure"; the raw-filing note reads "Both nominees’ receipts, disbursements, cash and debt come from a Raw filing the FEC has posted but not yet processed." once instead of once per card; screen-reader-only header "Measure" and "More details".
9. Timeline bars no longer carry a hover-only `title`; the same text is the bar's `aria-label` and the readout.

## Dependencies

None added. The build keeps the existing stack: plain HTML, CSS and JavaScript, no framework, no chart or map library, no build step.

## Checks run

- No horizontal page scroll at 320, 360, 375, 390, 414, 768, 769, 1,024, 1,280 and 1,440 px, and at 667 by 375, 812 by 375 and 844 by 390 (landscape).
- Version switches at 768/769 px with zero network requests; a map selection and the timeline survive the switch.
- Every input and select is 16 px on phones; the sticky nav is 8.2 percent of a 667 px viewport.
- Anchors: all 10 sections plus `#method-district` land below the nav at every width, from the link bar, the jump menu and the hash; the skip link works.
- Interactions: desktop hover tooltip, click, inset click and keyboard selection on the map; phone buttons; timeline readouts by keyboard and tap; sort by keyboard with `aria-sort`; the expand button; the methodology hash.
- Copy audit: 0 failures. Key scan: clean. Console: no errors.
- Lighthouse, mobile, simulated throttling, headless Chromium in the build container, two runs each: performance before 67 and 74, after 79 and 79; accessibility before 97, after 100; LCP 4.5 s to 3.8 s; total blocking time 150 to 180 ms before, 70 to 80 ms after; CLS 0.19 to 0.29 before, 0.199 after.

## Known limitations and open items

- Browser verification was done in Chromium (Playwright emulation) only. iOS Safari, Android Chrome, Firefox, Safari and Edge were not available in the build environment; everything in the checks above is emulator-only.
- Timeline bars on phones are about 15 px wide (eight weeks share the width), under the 44 px target. Mitigation: the whole week column (30 by 141 px at 375 px) is the tap target and reads out both figures; every bar is still a focusable button for keyboard users.
- Stacked-bar segments narrower than 44 px (small shares) remain narrow targets; the legend states each segment's value and every segment is keyboard-focusable.
- The compact dollar format never triggers with the current figures; the mechanism is in place for a figure past 10 characters.
- Tile values keep the exact-dollar presentation the page already used rather than switching to prose dollars ("$5.4 million"); AP style uses figures for dollar amounts and the prose form appears in each tile's sub-line.
- Desktop link bar wraps to two or three rows between 769 and 1,279 px; all 10 links stay visible.
- A phone held sideways at 769 px or wider receives the desktop version by the width rule the specification sets; the nav un-sticks under 520 px of height so it does not take a third of the screen.
- D.C. is small even in the inset; on phones the DC button selects it, on desktop its inset shape is clickable at about 12 by 15 px.
- CLS of about 0.2 comes from the headline and tiles filling in after the data loads, which the data flow (JSON fetched after first paint) makes unavoidable without reserving heights for text of unknown length.
- Pre-existing data-presentation inconsistency, flagged and not changed: the "Primary dollars vs. general dollars" section says "across 2,770 donor records" (Koh) and "460" (Jones), the sum of per-election counts in `election_split.contributors`, in which a donor who gave for both elections counts twice; the snapshot's "Contributor records" uses `election_split.contributors_total` (2,472 and 392), the distinct count. The build script's `build_candidate` writes both.
- Pre-existing CSS bug fixed because it is presentation, not data: the reduced-motion override for smooth scrolling sat above the smooth rule and lost the cascade, so smooth scrolling ran for readers who had asked for reduced motion.
