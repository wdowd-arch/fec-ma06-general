/* MA-06 general-election campaign finance dashboard: client-side rendering.
   No build step, no framework. Reads the pre-built JSON that build_data.py
   wrote (dashboard.json) plus the editor-owned copy.json from
   window.MA06_DATA_BASE. The U.S. map paths lazy-load when the geography
   section scrolls into view. Every number and date formatter below follows
   the newsroom's AP-based copy rules; see README.md. */

(function () {
  "use strict";

  const BASE = (window.MA06_DATA_BASE || "data/").replace(/\/?$/, "/");
  const KEYS = ["koh", "jones"];

  // ------------------------------------------------------------- formatters
  const fmtUSD0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  const fmtUSD2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtInt = new Intl.NumberFormat("en-US");
  const MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
  const WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];

  function isNum(v) { return typeof v === "number" && !isNaN(v); }
  function trim0(s) { return s.replace(/\.0$/, ""); }

  // Exact dollars for tiles and tables: $1,234 or, when cents matter, $1,234.56.
  function money(v, cents) {
    if (!isNum(v)) return "not reported";
    const neg = v < 0 ? "-" : "";
    const a = Math.abs(v);
    if (cents && Math.round(a * 100) % 100 !== 0) return neg + fmtUSD2.format(a);
    return neg + fmtUSD0.format(Math.round(a));
  }
  // Prose dollars: $4.5 million; about $283,000; $5,250; $5.
  function moneyProse(v) {
    if (!isNum(v)) return "an amount that was not reported";
    const neg = v < 0 ? "-" : "";
    const a = Math.abs(v);
    if (a >= 1e9) return neg + "$" + trim0((a / 1e9).toFixed(1)) + " billion";
    if (a >= 1e6) return neg + "$" + trim0((a / 1e6).toFixed(1)) + " million";
    if (a >= 1e4) {
      const r = Math.round(a / 1000) * 1000;
      return (r === Math.round(a) ? "" : "about ") + neg + fmtUSD0.format(r);
    }
    return neg + fmtUSD0.format(Math.round(a));
  }
  function pct(fraction) { return fraction > 0 && fraction < 0.0005 ? "less than 0.1%" : trim0((fraction * 100).toFixed(1)) + "%"; }
  // Every percentage states its base and, when the base is known, the dollars.
  function pctOf(part, base, baseDesc) {
    if (!isNum(base) || base <= 0 || !isNum(part)) return "the base figure was not provided";
    return pct(part / base) + " of " + moneyProse(base) + " " + baseDesc + ", " + moneyProse(part);
  }
  function numWord(n) {
    if (!isNum(n)) return "an unreported number of";
    return n >= 0 && n <= 9 && Number.isInteger(n) ? WORDS[n] : fmtInt.format(n);
  }
  function numSentenceStart(n) { const w = numWord(n); return w.charAt(0).toUpperCase() + w.slice(1); }
  function plural(n, one, many) { return n === 1 ? one : (many || one + "s"); }
  function parseDate(iso) { return iso ? new Date(iso.slice(0, 10) + "T00:00:00") : null; }
  function fmtDate(iso, withYear) {
    const d = parseDate(iso);
    if (!d || isNaN(d)) return "date not reported";
    return MONTHS[d.getMonth()] + " " + d.getDate() + (withYear === false ? "" : ", " + d.getFullYear());
  }
  function fmtDay(iso) { return fmtDate(iso, false); }

  // ------------------------------------------------------------------ dom
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === "class") e.className = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    }
    (children || []).forEach((c) => { if (c !== null && c !== undefined) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function byId(id) { return document.getElementById(id); }
  function clear(node) { node.innerHTML = ""; return node; }
  function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
  function link(href, text, title) {
    return href ? el("a", { href, target: "_blank", rel: "noopener", title: title || null }, [text]) : el("span", {}, [text]);
  }
  function pill(text, cls) { return el("span", { class: "tag-pill " + (cls || "") }, [text]); }
  function emptyState(text) { return el("div", { class: "empty-state" }, [text]); }
  function rawPill() { return pill("Raw filing", "raw"); }
  const RAW_TEXT = "raw filing, not yet processed by the Federal Election Commission";
  function isRaw(source) { return typeof source === "string" && source.indexOf("raw") === 0; }

  // One URL, two presentations. The version is chosen by viewport width and
  // nothing else; crossing 768 px re-renders the components whose markup
  // differs, from the data already in memory, never a reload or a refetch.
  const MOBILE_MQ = window.matchMedia("(max-width: 768px)");
  const state = { data: null, copy: null, usMap: null, usMapLoading: false, geoKey: "koh", geoSelected: null, sorts: {},
    mobile: MOBILE_MQ.matches, rendered: { timeline: false, spending: false } };
  function applyVersionAttr() { const app = byId("ma06-app"); if (app) app.dataset.version = state.mobile ? "mobile" : "desktop"; }
  applyVersionAttr();

  // Compact dollars are a phone-only fallback for a tile value that cannot
  // fit at 360 px; the full figure stays in title and aria-label. Tables and
  // the methodology never use it, and the desktop version never does.
  function compactMoney(v) {
    const a = Math.abs(v), neg = v < 0 ? "-" : "";
    if (a >= 1e9) return neg + "$" + trim0((a / 1e9).toFixed(1)) + "B";
    if (a >= 1e6) return neg + "$" + trim0((a / 1e6).toFixed(1)) + "M";
    if (a >= 1e4) return neg + "$" + Math.round(a / 1e3) + "K";
    return money(v);
  }
  function tileValue(v) {
    const full = money(v);
    if (state.mobile && isNum(v) && full.length > 10) return el("div", { class: "value", title: full, "aria-label": full }, [compactMoney(v)]);
    return el("div", { class: "value" }, [full]);
  }

  function cand(key) { return state.data.candidates.find((c) => c.key === key); }
  function cands() { return KEYS.map(cand).filter(Boolean); }
  function possessive(c) { return c.last_name + (c.last_name.endsWith("s") ? "’" : "’s"); }

  // ------------------------------------------------------------- loading
  // Exact per-file URLs win over the folder base: Ghost renames an uploaded
  // file that shares a name with an earlier upload, so the embed can pin each.
  async function fetchJson(name) {
    const files = window.MA06_DATA_FILES || {};
    const r = await fetch(files[name] || BASE + name, { cache: "no-cache" });
    if (!r.ok) throw new Error(name + " " + r.status);
    return r.json();
  }
  function observeLazy(id, fn) {
    const target = byId(id);
    if (!target) return;
    if (!("IntersectionObserver" in window)) { fn(); return; }
    const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { fn(); io.disconnect(); } }), { rootMargin: "200px" });
    io.observe(target);
  }

  // -------------------------------------------------------- sortable table
  // Renders a table with aria-sort headers and data-label cells (for the
  // phone-width card reflow). cols: {key,label,format,num}. rows: objects.
  // opts.mobile picks the phone pattern: "cards" (default; every row becomes
  // a stacked card of label and value), {pattern: "expand", priority: [keys]}
  // (priority columns show, a button in the row reveals the rest) or
  // {pattern: "scroll", cue: id} (horizontal scroll with a sticky first
  // column, only where comparing across columns is the point).
  function renderTable(table, cols, rows, opts) {
    opts = opts || {};
    const id = table.id;
    const mobile = opts.mobile || {};
    const scroller = table.closest(".table-scroll");
    const scrollPattern = state.mobile && mobile.pattern === "scroll";
    const expandPattern = state.mobile && mobile.pattern === "expand";
    table.classList.toggle("scroll-table", scrollPattern);
    table.classList.toggle("card-table", !scrollPattern);
    table.classList.toggle("expand-rows", expandPattern);
    if (scroller) scroller.classList.toggle("scroll-x", scrollPattern);
    if (mobile.cue) { const cue = byId(mobile.cue); if (cue) cue.hidden = !scrollPattern; }
    const priority = new Set(mobile.priority || []);
    const sort = state.sorts[id] || (state.sorts[id] = { key: opts.defaultSort || cols[0].key, dir: opts.defaultDir || -1 });
    const thead = clear(table.querySelector("thead"));
    const trh = el("tr");
    cols.forEach((col) => {
      const sorted = sort.key === col.key;
      const th = el("th", { scope: "col", class: col.num ? "num" : "" });
      if (sorted) th.setAttribute("aria-sort", sort.dir > 0 ? "ascending" : "descending");
      if (opts.sortable === false || col.sortable === false) { th.appendChild(document.createTextNode(col.label)); }
      else {
        const btn = el("button", { type: "button", class: "sort-btn" + (sorted ? " sorted" : ""), "aria-label": "Sort by " + col.label }, [
          col.label, el("span", { class: "arrow", "aria-hidden": "true" }, [sorted ? (sort.dir > 0 ? "▲" : "▼") : "↕"]),
        ]);
        btn.addEventListener("click", () => {
          if (sort.key === col.key) sort.dir *= -1; else { sort.key = col.key; sort.dir = col.num ? -1 : 1; }
          renderTable(table, cols, rows, opts);
        });
        th.appendChild(btn);
      }
      if (expandPattern && !priority.has(col.key)) th.classList.add("secondary");
      trh.appendChild(th);
    });
    if (expandPattern) trh.appendChild(el("th", { scope: "col", class: "row-toggle" }, [el("span", { class: "sr-only" }, ["More details"])]));
    thead.appendChild(trh);
    const col = cols.find((c) => c.key === sort.key) || cols[0];
    const sortedRows = [...rows].sort((a, b) => {
      const av = col.sortValue ? col.sortValue(a) : a[sort.key], bv = col.sortValue ? col.sortValue(b) : b[sort.key];
      if (typeof av === "string" || typeof bv === "string") return String(av || "").localeCompare(String(bv || "")) * sort.dir;
      return ((av || 0) - (bv || 0)) * sort.dir;
    });
    const tbody = clear(table.querySelector("tbody"));
    if (!sortedRows.length) {
      tbody.appendChild(el("tr", {}, [el("td", { colspan: String(cols.length) }, [emptyState(opts.empty || "Nothing on file.")])]));
    } else {
      sortedRows.forEach((r) => {
        const tr = el("tr");
        cols.forEach((c) => {
          const cell = c.render ? c.render(r) : (c.num ? money(r[c.key], c.cents) : (r[c.key] == null ? "—" : String(r[c.key])));
          tr.appendChild(el("td", { class: (c.num ? "num" : "") + (c.wrap ? " wrap-cell" : "") + (expandPattern && !priority.has(c.key) ? " secondary" : ""), "data-label": c.label }, [typeof cell === "string" ? cell : cell]));
        });
        if (expandPattern) {
          const hiddenCount = cols.length - priority.size;
          const btn = el("button", { type: "button", class: "row-more", "aria-expanded": "false" }, ["Show " + numWord(hiddenCount) + " more " + plural(hiddenCount, "figure")]);
          btn.addEventListener("click", () => {
            const open = tr.classList.toggle("expanded");
            btn.setAttribute("aria-expanded", open ? "true" : "false");
            btn.textContent = open ? "Show fewer figures" : "Show " + numWord(hiddenCount) + " more " + plural(hiddenCount, "figure");
          });
          tr.appendChild(el("td", { class: "row-toggle" }, [btn]));
        }
        tbody.appendChild(tr);
      });
    }
    let tfoot = table.querySelector("tfoot");
    if (opts.footer && sortedRows.length) {
      if (!tfoot) { tfoot = el("tfoot"); table.appendChild(tfoot); }
      clear(tfoot).appendChild(opts.footer(sortedRows));
    } else if (tfoot) tfoot.remove();
  }

  // ------------------------------------------------------- shared pieces
  function pairBlock(c, children) {
    return el("div", {}, [el("h3", {}, [el("span", { class: "swatch-dot " + c.key, "aria-hidden": "true" }), c.name + " (" + c.party_abbr + ")"]), ...children]);
  }
  // Stacked bar plus a legend that gives each segment's exact dollars and
  // its share of a stated base. Segments are focusable buttons that write
  // the exact value into a live region.
  function stackWithLegend(segments, base, baseDesc, detailId) {
    const bar = el("div", { class: "stack-bar" });
    const legend = el("div", { class: "stack-legend" });
    const detail = el("p", { class: "seg-detail", id: detailId, "aria-live": "polite" });
    const parts = [];
    segments.forEach((s) => {
      if (!isNum(s.value) || s.value <= 0) return;
      const text = s.label + ": " + money(s.value) + ", " + pctOf(s.value, base, baseDesc);
      parts.push(text);
      const seg = el("button", { type: "button", class: "seg", style: "width:" + ((s.value / base) * 100) + "%;background:" + s.color, "aria-label": text, title: text });
      seg.addEventListener("click", () => { detail.textContent = text; });
      seg.addEventListener("focus", () => { detail.textContent = text; });
      bar.appendChild(seg);
      legend.appendChild(el("span", { class: "item" }, [el("span", { class: "swatch", style: "background:" + s.color }), text]));
    });
    return [bar, legend, detail, el("p", { class: "sr-only" }, [parts.join("; ") || "No dollars in this breakdown."])];
  }
  function hbarList(container, rows, max, cls) {
    clear(container);
    if (!rows.length) { container.appendChild(emptyState("Nothing on file for this selection.")); return; }
    const m = max || Math.max(...rows.map((r) => r[1]), 1);
    rows.forEach((r) => {
      const label = r[0], amt = r[1];
      container.appendChild(el("div", { class: "hbar-row" }, [
        el("span", { class: "lbl", title: label }, [label]),
        el("div", { class: "hbar-track", role: "img", "aria-label": label + ": " + money(amt) }, [el("div", { class: "hbar-fill " + (cls || ""), style: "width:" + ((amt / m) * 100) + "%" })]),
        el("span", { class: "amt" }, [money(amt)]),
      ]));
    });
  }

  // ---------------------------------------------------------------- masthead
  function renderMasthead() {
    const d = state.data, copy = state.copy || {};
    byId("headline").textContent = copy.headline || "MA-06 general election money";
    byId("dek").textContent = copy.dek || "";
    byId("byline").textContent = copy.byline || "";
    const through = cands().map((c) => c.last_name + " " + fmtDate(d.meta.data_through[c.key])).join("; ");
    byId("meta-data-through").textContent = through;
    byId("meta-last-checked").textContent = d.meta.last_checked_display;
    const note = byId("build-note");
    if (d.meta.build_mode !== "live") {
      note.textContent = "This build was assembled from cached responses rather than a live pull from the FEC (" + d.meta.build_mode + "). Run build_data.py against the live FEC service before publishing.";
      note.classList.remove("hidden");
    }
    byId("copyright-year").textContent = String(new Date().getFullYear());
  }

  // ---------------------------------------------------------------- overview
  // Candidate headshots live beside the nameplate; inside a Ghost card the
  // embed sets window.MA06_ASSET_BASE so the same paths resolve.
  const ASSET_BASE = window.MA06_ASSET_BASE ? String(window.MA06_ASSET_BASE).replace(/\/?$/, "/") : "";
  const PHOTOS = { koh: "assets/images/koh.jpg", jones: "assets/images/jones.jpg" };
  // Exact uploaded URLs (by file name) win over the folder base: Ghost
  // stores images flat and renames repeats, so the embed pins each one.
  function assetUrl(rel) {
    const files = window.MA06_ASSET_FILES || {};
    return files[rel.split("/").pop()] || ASSET_BASE + rel;
  }

  // The primary edition's candidate snapshot cards: photo, name, bar, the
  // same seven figures for each nominee.
  function snapshotRows(c) {
    const t = c.totals, g = c.geography || {}, es = c.election_split || {};
    const through = t.raw_through || t.processed_through || (c.latest_report && c.latest_report.coverage_end);
    const inDistrict = isNum(g.in_district) && isNum(g.located_total) && g.located_total > 0 ? pct(g.in_district / g.located_total) + " of " + moneyProse(g.located_total) : "not available";
    return [
      ["Total receipts", money(t.receipts)],
      ["Total disbursements", money(t.disbursements)],
      ["Cash on hand", money(t.cash_on_hand)],
      ["Debt owed", money(t.debts)],
      ["Contributor records", isNum(es.contributors_total) ? fmtInt.format(es.contributors_total) : "not available"],
      ["Estimated in MA-06", inDistrict],
      ["Data through", through ? fmtDay(through) : "not reported"],
    ];
  }
  function rawNote(cls) {
    const note = el("p", { class: cls }, ["Receipts, disbursements, cash and debt come from a "]);
    note.appendChild(rawPill());
    note.appendChild(document.createTextNode(" the FEC has posted but not yet processed."));
    return note;
  }
  // Phone version: one three-column comparison (measure | Koh | Jones), one
  // measure per row, the receipts share bars spanning the width beneath the
  // receipts row. Real table markup keeps the semantics.
  function renderSnapshotTable(host, cs) {
    const max = Math.max(...cs.map((c) => (isNum(c.totals.receipts) ? c.totals.receipts : 0)), 0);
    const head = el("tr", {}, [el("th", { scope: "col" }, [el("span", { class: "sr-only" }, ["Measure"])])]);
    cs.forEach((c) => head.appendChild(el("th", { scope: "col", class: c.key }, [
      PHOTOS[c.key] ? el("img", { class: "candidate-photo", src: assetUrl(PHOTOS[c.key]), alt: "", width: "56", height: "56", loading: "lazy" }) : null,
      el("span", { class: "name" }, [c.name]), el("span", { class: "party" }, ["(" + c.party_abbr + ")"]),
    ])));
    const body = el("tbody");
    const rowsBy = cs.map(snapshotRows);
    rowsBy[0].forEach((row, i) => {
      const tr = el("tr", {}, [el("th", { scope: "row" }, [row[0]])]);
      cs.forEach((c, j) => tr.appendChild(el("td", {}, [rowsBy[j][i][1]])));
      body.appendChild(tr);
      if (i === 0) {
        const td = el("td", { class: "bar-row", colspan: String(cs.length + 1) });
        cs.forEach((c) => {
          const share = max > 0 && isNum(c.totals.receipts) ? (c.totals.receipts / max) * 100 : 0;
          td.appendChild(el("div", { class: "who " + c.key }, [c.last_name + ", share of the larger figure"]));
          td.appendChild(el("div", { class: "mini-bar " + c.key, role: "img", "aria-label": c.name + " total receipts " + money(c.totals.receipts) + (max > 0 ? ", " + pct(share / 100) + " of the larger figure" : "") }, [el("span", { style: "width:" + share + "%" })]));
        });
        body.appendChild(el("tr", {}, [td]));
      }
    });
    const table = el("table", { class: "snapshot-table" }, [el("thead", {}, [head]), body]);
    host.appendChild(table);
    const rawOnes = cs.filter((c) => isRaw(c.totals.source));
    if (rawOnes.length) {
      const note = el("p", { class: "snapshot-note" }, [(rawOnes.length === cs.length ? "Both nominees’ receipts" : possessive(rawOnes[0]) + " receipts") + ", disbursements, cash and debt come from a "]);
      note.appendChild(rawPill()); note.appendChild(document.createTextNode(" the FEC has posted but not yet processed."));
      host.appendChild(note);
    }
  }
  function renderCandidateCards(cs) {
    const host = byId("overview-cards");
    if (!host) return;
    clear(host);
    if (state.mobile) { renderSnapshotTable(host, cs); return; }
    const max = Math.max(...cs.map((c) => (isNum(c.totals.receipts) ? c.totals.receipts : 0)), 0);
    cs.forEach((c) => {
      const t = c.totals;
      const rows = snapshotRows(c);   // every percentage states its base: "7.3% of $4.6 million"
      const dl = el("dl", {});
      rows.forEach(([k, v]) => { dl.appendChild(el("dt", {}, [k])); dl.appendChild(el("dd", {}, [v])); });
      const share = max > 0 && isNum(t.receipts) ? (t.receipts / max) * 100 : 0;
      const card = el("div", { class: "candidate-card" }, [
        PHOTOS[c.key] ? el("img", { class: "candidate-photo", src: assetUrl(PHOTOS[c.key]), alt: c.name, width: "72", height: "72", loading: "lazy" }) : null,
        el("h3", {}, [c.name, el("span", { class: "party" }, ["(" + c.party_abbr + ")"])]),
        el("div", { class: "mini-bar " + c.key, role: "img", "aria-label": c.name + " total receipts " + money(t.receipts) + (max > 0 ? ", " + pct(share / 100) + " of the larger figure" : "") }, [el("span", { style: "width:" + share + "%" })]),
        dl,
      ]);
      if (isRaw(t.source)) card.appendChild(rawNote("card-note"));
      host.appendChild(card);
    });
  }

  // The reader-support card the primary edition shows above the snapshots
  // and again at the foot of the page.
  function supportCardTemplate() {
    return el("aside", { class: "support-card", "aria-label": "Support The Marblehead Independent" }, [
      el("p", { class: "kicker" }, ["Reader-supported"]),
      el("p", {}, ["This coverage is free. Recurring contributors keep local journalism open to everyone in Marblehead and across the North Shore."]),
      el("div", { class: "support-actions" }, [
        el("a", { class: "btn", href: "https://www.marbleheadindependent.com/ways-to-support/" }, ["Support local journalism"]),
        el("a", { class: "btn secondary", href: "https://www.marbleheadindependent.com/the-founders-circle/" }, ["Contribute to our founders’ circle"]),
      ]),
      el("p", { class: "support-newsletter" }, ["Not ready to contribute yet? ", el("a", { href: "https://www.marbleheadindependent.com/#/portal/signup" }, ["Sign up for our weekly newsletter"]), "."]),
    ]);
  }
  function renderSupportCards() {
    ["support-card-top", "support-card-bottom"].forEach((id) => {
      const host = byId(id);
      if (host) { clear(host).appendChild(supportCardTemplate()); }
    });
  }

  function renderOverview() {
    const cs = cands();
    const grid = el("div", { class: "metric-grid" });
    const tiles = [
      { label: "Total receipts", get: (c) => c.totals.receipts, sub: (c) => "Cycle to date" },
      { label: "Total disbursements", get: (c) => c.totals.disbursements, sub: (c) => "Cycle to date" },
      { label: "Cash on hand", get: (c) => c.totals.cash_on_hand, sub: (c) => "At the close of the most recent report" },
      { label: "Debt", get: (c) => c.totals.debts, sub: (c) => "Owed by the committee" },
      { label: "Spending rate", get: (c) => c.totals.spending_rate, kind: "rate",
        sub: (c) => isNum(c.totals.spending_rate) ? "of " + moneyProse(c.totals.receipts) + " in total receipts spent, " + moneyProse(c.totals.disbursements) : "total receipts were not reported" },
      { label: "Most recent report covered", get: (c) => null, kind: "report",
        value: (c) => c.latest_report ? c.latest_report.report_type_full : "No report on file",
        sub: (c) => c.latest_report ? "Covers through " + fmtDate(c.latest_report.coverage_end) + "; filed " + fmtDate(c.latest_report.filed) : "" },
    ];
    tiles.forEach((t) => {
      const tile = el("div", { class: "metric-tile" }, [el("div", { class: "label" }, [t.label])]);
      const h2h = el("div", { class: "h2h" });
      const max = Math.max(...cs.map((c) => (isNum(t.get(c)) ? t.get(c) : 0)), 0);
      cs.forEach((c) => {
        const v = t.get(c);
        const col = el("div", {}, [el("div", { class: "who " + c.key }, [c.name])]);
        if (t.kind === "report") {
          col.appendChild(el("div", { class: "value", style: "font-size:1rem" }, [t.value(c)]));
          const sub = el("div", { class: "sub" }, [t.sub(c)]);
          if (c.latest_report && isRaw(c.latest_report.source)) { sub.appendChild(document.createTextNode(" ")); sub.appendChild(rawPill()); }
          if (c.latest_report && c.latest_report.filing_page) { sub.appendChild(document.createTextNode(" ")); sub.appendChild(link(c.latest_report.filing_page, "View the filing")); }
          col.appendChild(sub);
        } else if (t.kind === "rate") {
          col.appendChild(el("div", { class: "value" }, [isNum(v) ? pct(v) : "not reported"]));
          col.appendChild(el("div", { class: "sub" }, [t.sub(c)]));
          col.appendChild(el("div", { class: "bar " + c.key, role: "img", "aria-label": c.name + " spending rate: " + (isNum(v) ? pct(v) + " " + t.sub(c) : "not reported") }, [el("span", { style: "width:" + (isNum(v) ? Math.min(100, v * 100) : 0) + "%" })]));
        } else {
          col.appendChild(tileValue(v));
          const sub = el("div", { class: "sub" }, [t.sub(c)]);
          if (isRaw(c.totals.source)) { sub.appendChild(document.createTextNode(" ")); sub.appendChild(rawPill()); }
          col.appendChild(sub);
          col.appendChild(el("div", { class: "bar " + c.key, role: "img", "aria-label": c.name + " " + t.label.toLowerCase() + " " + money(v) + (max > 0 && isNum(v) ? ", " + pct(v / max) + " of the larger figure" : "") }, [el("span", { style: "width:" + (max > 0 && isNum(v) ? (v / max) * 100 : 0) + "%" })]));
        }
        h2h.appendChild(col);
      });
      tile.appendChild(h2h);
      grid.appendChild(tile);
    });
    clear(byId("overview-metrics")).appendChild(grid);

    renderSupportCards();
    renderCandidateCards(cs);

    const recon = clear(byId("overview-recon"));
    cs.forEach((c) => {
      const r = c.reconciliation;
      if (r.status === "reconciled") {
        recon.appendChild(el("p", { class: "panel-note" }, [possessive(c) + " receipt categories add up to the reported total receipts of " + money(r.reported_total_receipts) + "."]));
      } else {
        recon.appendChild(el("p", { class: "recon-flag" }, [possessive(c) + " receipt categories total " + money(r.calculated_category_total) + " against reported total receipts of " + money(r.reported_total_receipts) + ". The " + money(r.difference, true) + " difference is shown as unreconciled."]));
      }
    });
    cs.forEach((c) => {
      const f = c.totals.filed_cycle || {};
      [["receipts", "receipts"], ["disbursements", "disbursements"]].forEach(([k, label]) => {
        if (isNum(f[k]) && isNum(c.totals[k]) && Math.abs(f[k] - c.totals[k]) > 0.01) {
          recon.appendChild(el("p", { class: "panel-note" }, [possessive(c) + " own " + f.report + " report lists cycle-to-date " + label + " of " + money(f[k], true) + "; the FEC’s processed total, used here and on FEC.gov, is " + money(c.totals[k], true) + ", a difference of " + money(Math.abs(f[k] - c.totals[k]), true) + "."]));
        }
      });
    });
    const rawTotals = cs.filter((c) => isRaw(c.totals.source));
    if (rawTotals.length) recon.appendChild(el("p", { class: "panel-note" }, ["Figures marked “Raw filing” come from a report the FEC has posted but not yet processed; they can change once processing finishes."]));
  }

  // ---------------------------------------------------------------- elections
  const SPLIT = [
    { key: "primary", label: "Designated for the primary", color: "var(--slate-blue)" },
    { key: "general", label: "Designated for the general election", color: "var(--positive)" },
    { key: "undesignated", label: "No election designated", color: "var(--amber)" },
    { key: "other", label: "Other designation", color: "var(--ink-soft)" },
  ];
  function renderElections() {
    const d = state.data, lim = d.limits || {};
    const note = byId("limit-note");
    if (lim.status === "retrieved" && isNum(lim.individual_per_election)) {
      clear(note).append("The per-election limit for an individual giving to a House candidate in " + lim.cycle_label + " is " + money(lim.individual_per_election) + ", read from ", link(lim.source_url, "FEC.gov"), " on " + fmtDate(lim.retrieved_at) + ".");
    } else {
      clear(note).append("The per-election contribution limit could not be read from ", link(lim.source_url || "https://www.fec.gov/", "FEC.gov"), " on this build, so this page does not count donors at the limit.");
    }
    const list = clear(byId("elections-list"));
    cands().forEach((c) => {
      const s = c.election_split;
      const base = s.itemized_individual_total;
      const kids = [el("p", { class: "panel-note", style: "margin-inline:0;max-width:none;text-align:left" }, [money(base) + " in itemized individual gifts across " + numWord(Object.values(s.contributors || {}).reduce((a, b) => a + b, 0)) + " donor records."])];
      kids.push(...stackWithLegend(SPLIT.map((x) => ({ label: x.label, value: s[x.key], color: x.color })), base, "in itemized individual gifts", "split-detail-" + c.key));
      if (isNum(s.at_limit_general)) {
        kids.push(el("p", { class: "panel-note", style: "margin:.8rem 0 0;max-width:none;text-align:left" }, [
          numSentenceStart(s.at_limit_general) + " donor " + plural(s.at_limit_general, "record", "records") + " (name plus ZIP code) " + plural(s.at_limit_general, "has", "have") + " given " + c.last_name + " the full " + money(lim.individual_per_election) + " for the general election; " + numWord(s.at_limit_primary) + " did so for the primary."]));
      }
      if (s.raw_total > 0) {
        kids.push(el("p", { class: "panel-note", style: "margin:.5rem 0 0;max-width:none;text-align:left" }, ["The figures include " + money(s.raw_total) + " from raw filings not yet processed by the FEC: " + money(s.raw_general) + " designated for the general election, " + money(s.raw_primary) + " for the primary and " + money(s.raw_undesignated) + " with no designation."]));
      }
      list.appendChild(pairBlock(c, kids));
    });
  }

  // ---------------------------------------------------------------- outside
  function sideLabel(r) { return (r.side === "support" ? "Supports " : "Opposes ") + cand(r.candidate_key).last_name; }
  function renderOutside() {
    const d = state.data, os = d.outside_spending;
    const cs = cands();
    const summary = clear(byId("outside-summary"));
    cs.forEach((c) => {
      const side = os.by_side[c.key] || { support: 0, oppose: 0, count: 0 };
      summary.appendChild(pairBlock(c, [
        el("div", { class: "hbar-row" }, [el("span", { class: "lbl" }, ["Supporting " + c.last_name]), el("div", { class: "hbar-track", role: "img", "aria-label": "Supporting " + c.last_name + " " + money(side.support) }, [el("div", { class: "hbar-fill", style: "width:" + (os.total ? (side.support / os.total) * 100 : 0) + "%;background:var(--positive)" })]), el("span", { class: "amt" }, [money(side.support)])]),
        el("div", { class: "hbar-row" }, [el("span", { class: "lbl" }, ["Opposing " + c.last_name]), el("div", { class: "hbar-track", role: "img", "aria-label": "Opposing " + c.last_name + " " + money(side.oppose) }, [el("div", { class: "hbar-fill", style: "width:" + (os.total ? (side.oppose / os.total) * 100 : 0) + "%;background:var(--independent-red)" })]), el("span", { class: "amt" }, [money(side.oppose)])]),
        el("p", { class: "panel-note", style: "margin:.4rem 0 0;max-width:none;text-align:left" }, [numSentenceStart(side.count) + " " + plural(side.count, "expenditure") + " on file naming " + c.last_name + " for the 2026 cycle. Of the dollars, " + money(side.support_general) + " supporting and " + money(side.oppose_general) + " opposing were designated for the general election; the rest were designated for the primary or carried no designation."]),
      ]));
    });

    const groupCols = [{ key: "group", label: "Group", render: (r) => r.group_fec_url ? link(r.group_fec_url, r.group, "Committee record on FEC.gov") : r.group, wrap: true }, { key: "total", label: "Total", num: true }];
    cs.forEach((c) => {
      groupCols.push({ key: c.key + "_support", label: "Supports " + c.last_name, num: true });
      groupCols.push({ key: c.key + "_oppose", label: "Opposes " + c.last_name, num: true });
    });
    renderTable(byId("outside-groups"), groupCols, os.by_group, { defaultSort: "total", mobile: { pattern: "expand", priority: ["group", "total"] }, empty: "No independent expenditures supporting or opposing either candidate are on file for the 2026 cycle." });

    const sel = byId("outside-candidate");
    if (!sel.dataset.filled) {
      cs.forEach((c) => sel.appendChild(el("option", { value: c.key }, [c.name])));
      sel.dataset.filled = "1";
      sel.addEventListener("change", renderOutsideRows);
      byId("outside-side").addEventListener("change", renderOutsideRows);
    }
    renderOutsideRows();
  }
  const IE_COLS = [
    { key: "date", label: "Date", render: (r) => { const s = el("span", {}, [fmtDate(r.date)]); if (isRaw(r.source)) { s.appendChild(document.createTextNode(" ")); s.appendChild(rawPill()); } return s; } },
    { key: "group", label: "Group", render: (r) => r.group_fec_url ? link(r.group_fec_url, r.group) : r.group, wrap: true },
    { key: "side", label: "Position", render: (r) => pill(sideLabel(r), r.side), sortValue: (r) => sideLabel(r) },
    { key: "election", label: "Election", render: (r) => r.election === "general" ? "General" : r.election === "primary" ? "Primary" : r.election === "not_stated" ? "Not stated on the raw filing" : "Not designated" },
    { key: "amount", label: "Amount", num: true, cents: true },
    { key: "purpose", label: "Purpose", wrap: true, render: (r) => r.purpose || "not described" },
    { key: "payee", label: "Payee", wrap: true, render: (r) => r.payee || "not reported" },
    { key: "form", label: "Form", render: (r) => (r.form || "—") + (r.is_notice ? " (24-hour report)" : "") },
    { key: "filing_page", label: "Filing", sortable: false, render: (r) => link(r.filing_page || r.pdf_url, "View on FEC.gov") },
  ];
  function renderOutsideRows() {
    const os = state.data.outside_spending;
    const ck = byId("outside-candidate").value, side = byId("outside-side").value;
    const rows = os.rows.filter((r) => (ck === "__all__" || r.candidate_key === ck) && (side === "__all__" || r.side === side));
    byId("outside-count").textContent = fmtInt.format(rows.length) + " of " + fmtInt.format(os.rows.length) + " independent " + plural(os.rows.length, "expenditure") + " shown, totaling " + money(rows.reduce((a, r) => a + r.amount, 0)) + ".";
    renderTable(byId("outside-table"), IE_COLS, rows, { defaultSort: "date", empty: "No independent expenditures match this selection. Groups must report spending of $1,000 or more within 24 hours in the final 20 days before the election, so check back." });
  }

  // ---------------------------------------------------------------- late
  const LATE48_COLS = [
    { key: "date", label: "Date received", render: (r) => fmtDate(r.date) },
    { key: "candidate", label: "Candidate", render: (r) => pill(r.candidate, r.candidate_key) },
    { key: "contributor", label: "Contributor", wrap: true, render: (r) => r.contributor || "not reported" },
    { key: "city", label: "City, state", render: (r) => (r.city ? r.city + ", " : "") + (r.state || "") },
    { key: "employer", label: "Employer, occupation", wrap: true, render: (r) => [r.employer, r.occupation].filter(Boolean).join(", ") || "not reported" },
    { key: "amount", label: "Amount", num: true, cents: true, render: (r) => isNum(r.amount) ? money(r.amount, true) : "see filing" },
    { key: "filed", label: "Notice", wrap: true, render: (r) => { const s = el("span", {}, ["Filed " + fmtDay(r.filed) + " · ", link(r.filing_page || r.fec_url, "View on FEC.gov")]); if (r.raw) { s.appendChild(document.createTextNode(" ")); s.appendChild(rawPill()); } if (r.amended) { s.appendChild(document.createTextNode(" ")); s.appendChild(pill("Amended")); } return s; }, sortValue: (r) => r.filed },
  ];
  function late48Rows() {
    const rows = [];
    (state.data.late_money.notices_48h || []).forEach((n) => {
      n.contributions.forEach((x) => rows.push(Object.assign({}, x, {
        candidate: n.candidate, candidate_key: n.candidate_key, filed: n.filed, amended: n.amended, raw: isRaw(n.source),
        filing_page: n.filing_page, fec_url: n.fec_url, before_window: n.before_window,
      })));
    });
    return rows;
  }
  function renderLate48Rows() {
    const lm = state.data.late_money, notices = lm.notices_48h || [];
    const ck = byId("late-48-candidate").value, q = byId("late-48-search").value.trim().toLowerCase();
    const all = late48Rows();
    const rows = all.filter((r) => (ck === "__all__" || r.candidate_key === ck) &&
      (!q || [r.contributor, r.city, r.state, r.employer, r.occupation].filter(Boolean).join(" ").toLowerCase().includes(q)));
    const unread = notices.filter((n) => !n.contributions.length);
    const early = notices.filter((n) => n.before_window);
    let text = fmtInt.format(rows.length) + " of " + fmtInt.format(all.length) + " " + plural(all.length, "contribution") + " shown, totaling " + money(rows.reduce((a, r) => a + (isNum(r.amount) ? r.amount : 0), 0)) + ", from " + numWord(notices.length) + " " + plural(notices.length, "notice") + " filed since " + fmtDay(lm.window_start) + ".";
    if (early.length) text += " " + numSentenceStart(early.length) + " " + plural(early.length, "notice lists", "notices list") + " only contributions dated before " + fmtDate(lm.window_start) + "; the committee filed late or for the primary’s own 48-hour window.";
    if (unread.length) text += " The line items of " + numWord(unread.length) + " " + plural(unread.length, "notice") + " could not be read; open the filing for the contributions.";
    byId("late-48-count").textContent = text;
    renderTable(byId("late-48"), LATE48_COLS, rows, { defaultSort: "date", empty: notices.length ? "No contributions match the filter." : "No 48-hour notices have been filed by either committee since " + fmtDate(lm.window_start) + "." });
  }

  function renderLate() {
    const d = state.data, lm = d.late_money;
    clear(byId("late-note")).append(
      "A campaign must report any contribution of $1,000 or more received from " + fmtDay(lm.window_start) + " through " + fmtDay(lm.window_end) + " to the FEC within 48 hours, and a group must report an independent expenditure of $1,000 or more in that period within 24 hours. The amounts here are what the filers reported; they are not yet in the processed totals above. Filings last checked " + lm.last_checked_display + ".");
    const summary = clear(byId("late-summary"));
    cands().forEach((c) => {
      const l = c.late_money;
      summary.appendChild(pairBlock(c, [el("p", { class: "panel-note", style: "margin:0;max-width:none;text-align:left" }, [
        numSentenceStart(l.notices_48h_count) + " 48-hour " + plural(l.notices_48h_count, "notice") + " on file since " + fmtDay(lm.window_start) + ", reporting " + numWord(l.contributions_48h) + " " + plural(l.contributions_48h, "contribution") + " totaling " + money(l.notices_48h_total) + "."])]));
    });
    // Every contribution from every notice in one sortable table, the same
    // pattern as the 24-hour table below it, with the notice linked per row.
    const sel = byId("late-48-candidate");
    if (!sel.dataset.filled) {
      cands().forEach((c) => sel.appendChild(el("option", { value: c.key }, [c.name])));
      sel.dataset.filled = "1";
      sel.addEventListener("change", renderLate48Rows);
      byId("late-48-search").addEventListener("input", debounce(renderLate48Rows, 150));
    }
    renderLate48Rows();
    const ie = lm.ie_24h || [];
    byId("late-24-count").textContent = fmtInt.format(ie.length) + " 24-hour " + plural(ie.length, "report") + " on file, totaling " + money(ie.reduce((a, r) => a + r.amount, 0)) + ".";
    renderTable(byId("late-24"), IE_COLS, ie, { defaultSort: "date", empty: "No 24-hour independent expenditure reports naming either candidate are on file." });
  }

  // ---------------------------------------------------------------- crossover
  function renderCrossover() {
    const d = state.data, x = d.crossover;
    const pcs = x.primary_candidates.map((p) => p.name);
    clear(byId("crossover-note")).append(
      "Individual donors to " + pcs.slice(0, -1).join(", ") + " or " + pcs[pcs.length - 1] + " in the primary who later gave to Dan Koh or Micah Jones. The match uses the donor’s normalized name plus ZIP code, so the results are likely matches, not confirmed identities. The full rule is in the methodology. " + fmtInt.format(x.primary_donor_keys) + " distinct name-and-ZIP records gave to the six primary campaigns.");
    const summary = clear(byId("crossover-summary"));
    cands().forEach((c) => {
      const s = c.crossover;
      const kids = [el("p", { class: "panel-note", style: "margin:0 0 .6rem;max-width:none;text-align:left" }, [
        numSentenceStart(s.matches) + " likely " + plural(s.matches, "match", "matches") + " later gave " + c.last_name + " " + money(s.dollars) + " in itemized gifts. " + numSentenceStart(s.matches_after_primary) + " of them gave after the Sept. 1 primary, " + money(s.dollars_after_primary) + "."])];
      const rows = s.by_primary_candidate.map((p) => [p.candidate + " (" + numWord(p.matches) + ")", p.dollars]);
      const holder = el("div");
      hbarList(holder, rows, Math.max(1, ...rows.map((r) => r[1])), c.key);
      kids.push(holder);
      kids.push(el("p", { class: "sr-only" }, ["Dollars later given to " + c.last_name + " by donors who first gave to each primary candidate: " + rows.map((r) => r[0] + " " + money(r[1])).join("; ")]));
      summary.appendChild(pairBlock(c, kids));
    });
    const sel = byId("crossover-candidate");
    if (!sel.dataset.filled) {
      cands().forEach((c) => sel.appendChild(el("option", { value: c.key }, [c.name])));
      sel.dataset.filled = "1";
      sel.addEventListener("change", renderCrossoverRows);
      byId("crossover-search").addEventListener("input", debounce(renderCrossoverRows, 150));
    }
    renderCrossoverRows();
  }
  const XO_COLS = [
    { key: "donor", label: "Donor", wrap: true },
    { key: "city", label: "City, state", render: (r) => (r.city ? r.city + ", " : "") + (r.state || "") },
    { key: "primary_total", label: "Primary candidate (gift)", wrap: true, render: (r) => r.primary_candidates.map((p) => p.candidate + " (" + money(p.total) + ", first " + fmtDay(p.first_date) + ")").join("; "), sortValue: (r) => r.primary_total },
    { key: "general_candidate", label: "Later gave to", render: (r) => { const s = el("span", {}, [pill(r.general_candidate, r.general_key)]); if (r.raw) { s.appendChild(document.createTextNode(" ")); s.appendChild(rawPill()); } return s; } },
    { key: "general_total", label: "Later gifts", num: true },
    { key: "general_after_primary", label: "Of that, after Sept. 1", num: true },
    { key: "last_general_date", label: "Most recent gift", render: (r) => fmtDate(r.last_general_date) },
  ];
  function renderCrossoverRows() {
    const x = state.data.crossover;
    const q = (byId("crossover-search").value || "").toLowerCase().trim(), ck = byId("crossover-candidate").value;
    const rows = x.rows.filter((r) => (ck === "__all__" || r.general_key === ck) && (!q || (r.donor + " " + r.city + " " + r.primary_candidates.map((p) => p.candidate).join(" ")).toLowerCase().includes(q)));
    byId("crossover-count").textContent = fmtInt.format(rows.length) + " of " + fmtInt.format(x.rows.length) + " likely " + plural(x.rows.length, "match", "matches") + " shown, " + money(rows.reduce((a, r) => a + r.general_total, 0)) + " in later gifts.";
    renderTable(byId("crossover-table"), XO_COLS, rows, { defaultSort: "general_total", empty: "No likely matches for this selection." });
  }

  // ---------------------------------------------------------------- geography
  const GEO = [
    { key: "in_district", label: "Estimated in the district", color: "var(--positive)" },
    { key: "ma_other", label: "Elsewhere in Massachusetts", color: "var(--slate-blue)" },
    { key: "out_of_state", label: "Out of state", color: "var(--amber)" },
  ];
  function renderGeography() {
    const summary = clear(byId("geo-summary"));
    cands().forEach((c) => {
      const g = c.geography;
      const kids = stackWithLegend(GEO.map((x) => ({ label: x.label, value: g[x.key], color: x.color })), g.located_total, "in itemized individual gifts with a state on file", "geo-detail-" + c.key);
      if (g.unknown > 0) kids.push(el("p", { class: "panel-note", style: "margin:.4rem 0 0;max-width:none;text-align:left" }, [money(g.unknown) + " came from donors with no state on file and is left out of the shares above."]));
      if (g.raw_total > 0) kids.push(el("p", { class: "panel-note", style: "margin:.4rem 0 0;max-width:none;text-align:left" }, ["Includes " + money(g.raw_total) + " from raw filings not yet processed by the FEC."]));
      summary.appendChild(pairBlock(c, kids));
    });
    const tabs = byId("geo-tabs");
    if (!tabs.dataset.filled) {
      cands().forEach((c, i) => {
        const b = el("button", { type: "button", "aria-pressed": i === 0 ? "true" : "false", class: i === 0 ? "active" : "" }, [c.name]);
        b.addEventListener("click", () => {
          tabs.querySelectorAll("button").forEach((x) => { x.classList.remove("active"); x.setAttribute("aria-pressed", "false"); });
          b.classList.add("active"); b.setAttribute("aria-pressed", "true");
          state.geoKey = c.key; renderGeoDetail();
        });
        tabs.appendChild(b);
      });
      tabs.dataset.filled = "1";
    }
    renderGeoDetail();
    renderTownTable();
  }
  function renderGeoDetail() {
    const c = cand(state.geoKey);
    if (state.usMap) renderUsMap(c);
    hbarList(byId("geo-top-city"), c.geography.top_towns.map((t) => [t[0], t[1]]), null, c.key);
    hbarList(byId("geo-top-state"), c.geography.by_state.slice(0, 15), null, c.key);
  }
  function lerp(a, b, t) { return Math.round(a + (b - a) * t); }
  function shade(t) { const f = [251, 246, 238], to = [194, 38, 29]; return "rgb(" + lerp(f[0], to[0], t) + "," + lerp(f[1], to[1], t) + "," + lerp(f[2], to[2], t) + ")"; }
  // The Northeast inset: the viewBox region that holds the nine small states
  // (VT, NH, MA, RI, CT, NJ, DE, MD, DC) at about three times the main
  // map's scale. On phones a row of buttons makes each one a 44 px target.
  const INSET_VIEWBOX = "778 98 184 194";
  const SMALL_STATES = ["VT", "NH", "MA", "RI", "CT", "NJ", "DE", "MD", "DC"];
  function stateText(c, info, amt) {
    return info.name + ": " + (amt > 0 ? money(amt) + " in itemized individual gifts to " + c.last_name : "no itemized individual gifts to " + c.last_name + " on file");
  }
  function renderUsMap(c) {
    const wrap = byId("geo-map-wrap");
    if (!wrap || !state.usMap) return;
    const amounts = {};
    c.geography.by_state.forEach((s) => { amounts[s[0].toLowerCase()] = s[1]; });
    const max = Math.max(1, ...c.geography.by_state.map((s) => s[1]));
    const NS = "http://www.w3.org/2000/svg";
    const detail = byId("geo-map-detail");
    const texts = {};
    const paths = { main: {}, inset: {} };
    const buttons = {};
    function select(postal) {
      state.geoSelected = postal;
      Object.values(paths.main).concat(Object.values(paths.inset)).forEach((p) => p.classList.toggle("selected", p.dataset.state === postal));
      Object.entries(buttons).forEach(([k, b]) => { b.classList.toggle("selected", k === postal); b.setAttribute("aria-pressed", k === postal ? "true" : "false"); });
      detail.textContent = texts[postal] + ".";
    }
    function makeSvg(viewBox, label, focusable) {
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", viewBox);
      svg.setAttribute("class", "us-map");
      svg.setAttribute("role", "group");
      svg.setAttribute("aria-label", label);
      const store = focusable ? paths.main : paths.inset;
      Object.entries(state.usMap.states).forEach(([postal, info]) => {
        const amt = amounts[info.name.toLowerCase()] || 0;
        texts[postal] = stateText(c, info, amt);
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", info.d);
        path.setAttribute("fill", shade(amt > 0 ? Math.sqrt(amt / max) : 0));
        path.setAttribute("class", "us-state" + (postal === "MA" ? " us-state-home" : ""));
        path.dataset.state = postal;
        if (focusable) { path.setAttribute("tabindex", "0"); path.setAttribute("role", "button"); path.setAttribute("aria-label", texts[postal]); }
        else { path.setAttribute("aria-hidden", "true"); }
        path.addEventListener("click", () => select(postal));
        if (focusable) {
          path.addEventListener("focus", () => select(postal));
          path.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(postal); } });
        }
        // Desktop hover: a tooltip that follows the pointer. Phones never see it.
        path.addEventListener("mouseenter", () => { if (!state.mobile) showTip(texts[postal]); });
        path.addEventListener("mousemove", (e) => { if (!state.mobile) moveTip(e); });
        path.addEventListener("mouseleave", hideTip);
        store[postal] = path;
        svg.appendChild(path);
      });
      return svg;
    }
    const tip = el("div", { class: "us-map-tip", hidden: "" });
    function showTip(text) { tip.textContent = text; tip.hidden = false; }
    function moveTip(e) { const r = wrap.getBoundingClientRect(); tip.style.left = (e.clientX - r.left) + "px"; tip.style.top = (e.clientY - r.top) + "px"; }
    function hideTip() { tip.hidden = true; }
    const main = makeSvg(state.usMap.viewBox, "Map of the United States shaded by itemized individual dollars given to " + c.name + ", by state. The Top states list below has every figure.", true);
    clear(wrap).appendChild(main);
    wrap.appendChild(tip);
    const insetHost = clear(byId("geo-map-inset"));
    insetHost.appendChild(el("p", { class: "inset-label" }, ["New England and mid-Atlantic"]));
    insetHost.appendChild(makeSvg(INSET_VIEWBOX, "Inset of the Northeast at a larger scale, same shading", false));
    const small = clear(byId("geo-map-small"));
    SMALL_STATES.forEach((postal) => {
      const b = el("button", { type: "button", "aria-pressed": "false", "aria-label": state.usMap.states[postal].name }, [postal]);
      b.addEventListener("click", () => select(postal));
      buttons[postal] = b;
      small.appendChild(b);
    });
    if (state.geoSelected && texts[state.geoSelected]) select(state.geoSelected);
    else detail.textContent = "No state selected. The amount appears here when a state is selected.";
    const legend = clear(byId("geo-map-legend"));
    legend.appendChild(el("span", {}, ["Fewer dollars"]));
    [0, 0.15, 0.4, 0.7, 1].forEach((t) => legend.appendChild(el("span", { class: "us-map-swatch", style: "background:" + shade(t) })));
    legend.appendChild(el("span", {}, ["More dollars, relative to the top state (" + money(max) + ")"]));
  }
  function loadUsMapOnce() {
    if (state.usMap || state.usMapLoading) return;
    state.usMapLoading = true;
    const loading = byId("geo-map-loading");
    if (loading) loading.textContent = "Loading the map…";
    fetchJson("us-states-paths.json").then((m) => { state.usMap = m; state.usMapLoading = false; renderGeoDetail(); })
      .catch((err) => { state.usMapLoading = false; if (loading) loading.textContent = "The map is unavailable right now (" + err.message + "). The Top states list has the same figures."; });
  }
  function renderTownTable() {
    const cs = cands();
    const byTown = {};
    cs.forEach((c) => c.geography.district_towns.forEach((t) => {
      const r = byTown[t.town] || (byTown[t.town] = { town: t.town });
      r[c.key + "_amount"] = t.amount; r[c.key + "_donors"] = t.donors;
    }));
    const rows = Object.values(byTown).map((r) => { cs.forEach((c) => { r[c.key + "_amount"] = r[c.key + "_amount"] || 0; r[c.key + "_donors"] = r[c.key + "_donors"] || 0; }); r.total = cs.reduce((a, c) => a + r[c.key + "_amount"], 0); return r; });
    const cols = [{ key: "town", label: "Town" }];
    const amountCols = cs.map((c) => ({ key: c.key + "_amount", label: c.last_name + " dollars", num: true }));
    const donorCols = cs.map((c) => ({ key: c.key + "_donors", label: c.last_name + " donor records", num: true, render: (r) => fmtInt.format(r[c.key + "_donors"]) }));
    // Phones: both candidates' dollars first, so they show without scrolling; donor counts follow by scroll.
    if (state.mobile) cols.push(...amountCols, ...donorCols);
    else cs.forEach((c, i) => cols.push(amountCols[i], donorCols[i]));
    renderTable(byId("geo-town-table"), cols, rows, { defaultSort: "total", mobile: { pattern: "scroll", cue: "geo-town-cue" }, empty: "No district towns on file.", footer: (sorted) => {
      const tr = el("tr", {}, [el("td", { "data-label": "Town" }, ["All listed towns"])]);
      cols.slice(1).forEach((col) => {
        const total = sorted.reduce((a, r) => a + r[col.key], 0);
        tr.appendChild(el("td", { class: "num", "data-label": col.label }, [col.key.endsWith("_donors") ? fmtInt.format(total) : money(total)]));
      });
      return tr;
    } });
    state.sorts["geo-town-table"].key = state.sorts["geo-town-table"].key || "total";
  }

  // ---------------------------------------------------------------- party
  function renderParty() {
    const list = clear(byId("party-list"));
    cands().forEach((c) => {
      const p = c.party_money;
      const kids = [];
      kids.push(el("h4", {}, ["Party committee contributions"]));
      if (p.contributions.length) {
        const t = el("table", { class: "card-table" }, [
          el("thead", {}, [el("tr", {}, [el("th", { scope: "col" }, ["Committee"]), el("th", { scope: "col" }, ["Date"]), el("th", { scope: "col" }, ["Election"]), el("th", { scope: "col", class: "num" }, ["Amount"]), el("th", { scope: "col" }, ["Filing"])])]),
          el("tbody", {}, p.contributions.map((r) => el("tr", {}, [
            el("td", { "data-label": "Committee", class: "wrap-cell" }, [r.committee, r.raw ? " " : null, r.raw ? rawPill() : null]), el("td", { "data-label": "Date" }, [fmtDate(r.date)]),
            el("td", { "data-label": "Election" }, [r.election === "general" ? "General" : r.election === "primary" ? "Primary" : "Not designated"]),
            el("td", { "data-label": "Amount", class: "num" }, [money(r.amount, true)]), el("td", { "data-label": "Filing" }, [link(r.filing_page, "View on FEC.gov")]),
          ]))),
        ]);
        kids.push(el("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": c.name + " party contributions, scrollable" }, [t]));
        kids.push(el("p", { class: "panel-note", style: "margin:.4rem 0 .8rem;max-width:none;text-align:left" }, ["Itemized party contributions total " + money(p.contributions_total) + "; the committee’s summary page reports " + money(p.contributions_reported_total) + " from party committees."]));
      } else {
        kids.push(el("p", { class: "panel-note", style: "margin:0 0 .8rem;max-width:none;text-align:left" }, ["No party-committee contributions appear in " + possessive(c) + " itemized receipts. The committee’s summary page reports " + money(p.contributions_reported_total) + " from party committees."]));
      }
      kids.push(el("h4", {}, ["Coordinated party expenditures"]));
      if (p.coordinated.length) {
        const t = el("table", { class: "card-table" }, [
          el("thead", {}, [el("tr", {}, [el("th", { scope: "col" }, ["Party committee"]), el("th", { scope: "col" }, ["Date"]), el("th", { scope: "col" }, ["Purpose"]), el("th", { scope: "col" }, ["Payee"]), el("th", { scope: "col", class: "num" }, ["Amount"]), el("th", { scope: "col" }, ["Filing"])])]),
          el("tbody", {}, p.coordinated.map((r) => el("tr", {}, [
            el("td", { "data-label": "Party committee", class: "wrap-cell" }, [r.committee]), el("td", { "data-label": "Date" }, [fmtDate(r.date)]),
            el("td", { "data-label": "Purpose", class: "wrap-cell" }, [r.purpose || "not described"]), el("td", { "data-label": "Payee", class: "wrap-cell" }, [r.payee || "not reported"]),
            el("td", { "data-label": "Amount", class: "num" }, [money(r.amount, true)]), el("td", { "data-label": "Filing" }, [link(r.filing_page || r.pdf_url, "View on FEC.gov")]),
          ]))),
        ]);
        kids.push(el("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": c.name + " coordinated party expenditures, scrollable" }, [t]));
        kids.push(el("p", { class: "panel-note", style: "margin:.4rem 0 0;max-width:none;text-align:left" }, ["Coordinated party expenditures on " + possessive(c) + " behalf total " + money(p.coordinated_total) + "."]));
      } else {
        kids.push(el("p", { class: "panel-note", style: "margin:0;max-width:none;text-align:left" }, ["No coordinated party expenditures on " + possessive(c) + " behalf have been filed on Schedule F."]));
      }
      list.appendChild(pairBlock(c, kids));
    });
  }

  // ---------------------------------------------------------------- timeline
  // Both charts share one scale: max is the largest weekly figure for either
  // candidate. Bars are buttons; hover, focus and tap write the exact value
  // into a readout under the chart that stays on screen.
  function renderTimeline() {
    const d = state.data, tl = d.timeline;
    const cs = cands();
    state.rendered.timeline = true;
    const max = Math.max(1, ...cs.flatMap((c) => c.timeline_weekly.flatMap((w) => [w.receipts + w.raw_receipts, w.disbursements + w.raw_disbursements])));
    const deadlineDays = tl.deadlines.filter((x) => !x.end).map((x) => x.date);
    const win = tl.deadlines.find((x) => x.end);
    const pairHost = clear(byId("timeline-pair"));
    pairHost.classList.add("timeline-pair");
    const ticks = state.mobile ? [0, 0.5, 1] : [0, 1 / 3, 2 / 3, 1];
    cs.forEach((c) => {
      const chart = el("div", { class: "timeline-chart" });
      const labels = el("div", { class: "timeline-labels" });
      const readout = el("p", { class: "seg-detail timeline-readout", id: "timeline-readout-" + c.key, "aria-live": "polite" }, ["Select a bar for the week’s exact figures."]);
      const desc = [];
      const bars = [];
      c.timeline_weekly.forEach((w) => {
        const r = w.receipts + w.raw_receipts, sp = w.disbursements + w.raw_disbursements;
        const hasDeadline = deadlineDays.some((dd) => dd >= w.week_start && dd <= w.week_end);
        const inWindow = win && w.week_end >= win.date && w.week_start <= win.end;
        const label = "Week of " + fmtDay(w.week_start);
        const rTitle = label + ": " + money(r) + " in itemized receipts" + (w.raw_receipts ? " (" + money(w.raw_receipts) + " from raw filings)" : "");
        const sTitle = label + ": " + money(sp) + " in itemized disbursements" + (w.raw_disbursements ? " (" + money(w.raw_disbursements) + " from raw filings)" : "");
        desc.push(label + " " + money(r) + " received, " + money(sp) + " spent");
        const mk = (cls, h, text) => {
          const b = el("button", { type: "button", class: cls, style: "height:" + ((h / max) * 100) + "%", "aria-label": text });
          const act = () => { bars.forEach((x) => x.classList.remove("selected")); b.classList.add("selected"); readout.textContent = text + "."; };
          b.addEventListener("click", act); b.addEventListener("focus", act);
          b.addEventListener("mouseenter", () => { if (!state.mobile) readout.textContent = text + "."; });
          bars.push(b);
          return b;
        };
        const pair = el("div", { class: "bar-pair" + (hasDeadline ? " deadline" : "") + (inWindow ? " window" : "") }, [
          mk("bar receipt" + (w.raw_receipts ? " raw" : ""), r, rTitle),
          mk("bar disb" + (w.raw_disbursements ? " raw" : ""), sp, sTitle),
        ]);
        // Phones: the whole week column is the tap target and reads out both figures.
        pair.addEventListener("click", () => {
          if (!state.mobile) return;
          chart.querySelectorAll(".bar-pair.selected").forEach((x) => x.classList.remove("selected"));
          pair.classList.add("selected");
          readout.textContent = label + ": " + money(r) + " in itemized receipts, " + money(sp) + " in itemized disbursements" + (w.raw_receipts || w.raw_disbursements ? " (includes raw filings)" : "") + ".";
        });
        chart.appendChild(pair);
        labels.appendChild(el("span", {}, [fmtDay(w.week_start)]));
      });
      const axis = el("div", { class: "timeline-axis", "aria-hidden": "true" });
      const grid = el("div", { class: "timeline-grid", "aria-hidden": "true" });
      ticks.forEach((t) => {
        axis.appendChild(el("span", { style: "bottom:" + (t * 100) + "%" }, [money(max * t)]));
        grid.appendChild(el("span", { style: "bottom:" + (t * 100) + "%" }));
      });
      const kids = [];
      if (!c.timeline_weekly.length) kids.push(emptyState("No itemized transactions dated since " + fmtDate(tl.start) + " are on file."));
      else kids.push(el("div", { class: "week-chart" }, [axis, el("div", { class: "timeline-plot" }, [grid, chart, labels]), readout]), el("p", { class: "sr-only" }, [c.name + ", by week: " + desc.join("; ")]));
      const tot = c.timeline_weekly.reduce((a, w) => ({ r: a.r + w.receipts + w.raw_receipts, s: a.s + w.disbursements + w.raw_disbursements }), { r: 0, s: 0 });
      kids.push(el("p", { class: "panel-note", style: "margin:.6rem 0 0;max-width:none;text-align:left" }, ["Since " + fmtDate(tl.start) + ": " + money(tot.r) + " in itemized receipts and " + money(tot.s) + " in itemized disbursements. Unitemized gifts under $200 appear only in the summary totals, not here."]));
      pairHost.appendChild(pairBlock(c, kids));
    });
    const dl = clear(byId("deadline-list"));
    tl.deadlines.forEach((x) => dl.appendChild(el("li", {}, [(x.end ? fmtDay(x.date) + " through " + fmtDay(x.end) : fmtDate(x.date)) + ": " + x.label + (x.covers ? " (" + x.covers + ")" : "")])));
    requestAnimationFrame(thinTimelineLabels);
  }
  // Hide every other x-axis label when they would overlap (measured, so
  // rotation and resizes re-decide); the hidden ones keep their space.
  function thinTimelineLabels() {
    document.querySelectorAll("#ma06-app .timeline-labels").forEach((row) => {
      const spans = [...row.children];
      if (!spans.length) return;
      const each = row.clientWidth / spans.length;
      const step = each >= 54 ? 1 : each >= 27 ? 2 : 3;
      spans.forEach((sp, i) => sp.classList.toggle("thin", i % step !== 0));
    });
  }

  // ---------------------------------------------------------------- spending
  const SPEND_COLORS = {};
  (function () {
    const order = ["Refunds", "Payroll", "Advertising and media", "Digital", "Fundraising", "Consultants", "Mail", "Events", "Travel", "Legal, compliance and accounting", "Office and operations", "Other", "Uncategorized"];
    const palette = ["var(--independent-red)", "var(--harbor-black)", "var(--slate-blue)", "#8fb3e8", "#c98a4b", "#7a5c8f", "#8a6d3b", "#2F6B4F", "#4b8f8c", "#5b5c5f", "#b5a642", "#9a9a9a", "#DDD3C2"];
    order.forEach((k, i) => { SPEND_COLORS[k] = palette[i]; });
  })();
  function renderSpending() {
    const host = clear(byId("spending-pair"));
    cands().forEach((c) => {
      const s = c.spending;
      const entries = Object.entries(s.by_category).sort((a, b) => b[1] - a[1]);
      const kids = [];
      if (!entries.length) kids.push(emptyState("No itemized disbursements on file."));
      else {
        kids.push(...stackWithLegend(entries.map(([k, v]) => ({ label: k, value: v, color: SPEND_COLORS[k] || "#9a9a9a" })), s.itemized_total, "in itemized disbursements", "spend-detail-" + c.key));
        const holder = el("div", { style: "margin-top:.8rem" });
        hbarList(holder, entries, entries[0][1], c.key);
        kids.push(holder);
      }
      kids.push(el("p", { class: "panel-note", style: "margin:.6rem 0 0;max-width:none;text-align:left" }, ["Itemized disbursements total " + money(s.itemized_total) + " across " + fmtInt.format(s.rows) + " rows; the committee’s reported total disbursements are " + money(s.reported_total_disbursements) + ", a figure that also covers unitemized payments." + (s.raw_total > 0 ? " Includes " + money(s.raw_total) + " across " + fmtInt.format(s.raw_rows) + " rows from raw filings not yet processed by the FEC." : "")]));
      host.appendChild(pairBlock(c, kids));
    });
  }

  // ---------------------------------------------------------------- methodology
  function renderMethodology() {
    const d = state.data, m = d.methodology, lim = d.limits || {};
    const dl = clear(byId("methodology-list"));
    const amend = m.amendments_excluded || {};
    const amendTotal = Object.values(amend).reduce((a, b) => a + (b || 0), 0);
    const items = [
      ["Data source", "OpenFEC, the FEC’s public data service, read by a build script that writes the figures this page shows. Totals, reports and itemized receipts and disbursements come from the FEC’s processed data. Where a committee or group has filed something the FEC has not yet processed, the page uses the raw e-filing and labels it “" + RAW_TEXT + ".” The 48-hour notices are read from the raw Form 6 filings themselves. The page never calls the service; it loads only the pre-built files. This build ran " + d.meta.generated_at_display + " Eastern time."],
      ["Which report each figure comes from", "Total receipts, total disbursements, cash on hand and debt are each committee’s own cycle-to-date figures from its most recent report. The weekly timeline, geography, election split, spending, party and crossover sections are built from itemized rows. The FEC processes line items separately from the summary and can lag it by weeks, so wherever a filing’s line items are not yet processed, the raw e-filed rows are used and labeled. " + cands().map((c) => c.last_name + ": line items processed through " + fmtDate(c.totals.itemized_processed_through) + (c.totals.raw_through ? ", raw rows through " + fmtDate(c.totals.raw_through) : "")).join("; ") + "."],
      ["Amendments", "When a report is amended, only the newest version is used, never the original plus the amendment. This build excluded " + numWord(amendTotal) + " superseded " + plural(amendTotal, "filing") + " across reports, 48-hour notices and independent expenditures. It also dropped " + numWord(m.ie_notices_superseded_by_reports || 0) + " 24- or 48-hour independent expenditure " + plural(m.ie_notices_superseded_by_reports || 0, "notice") + " that later appeared on a regular report."],
      ["Memo and conduit entries", "Rows the filer marked as memo entries, such as the ActBlue or WinRed pass-through record that accompanies an earmarked gift, are left out of every total so the same dollars are not counted twice."],
      ["Reconciliation", "For each candidate, the nine receipt categories on the committee’s summary (individuals, party committees, other committees, candidate contributions, candidate loans, other loans, transfers, offsets to operating expenditures and other receipts) are added up and compared with reported total receipts. Any difference larger than a cent is shown as “unreconciled” rather than hidden."].concat([]),
      ["Primary vs. general", "Each itemized gift from an individual carries the election the committee designated it for. Gifts with no designation are shown as such and not assigned. The per-election limit is read from " + (lim.source_url || "FEC.gov") + " on each build" + (lim.status === "retrieved" ? " (" + money(lim.individual_per_election) + " for " + lim.cycle_label + ")" : ", and was not retrieved on this build") + "."],
      ["Outside spending", "Independent expenditures come from Schedule E rows naming either candidate, processed and raw, with memo rows and superseded amendments removed. The same expenditure can reach the FEC on a 24-hour notice and again on the group’s regular report, each first as a raw e-filing and then as processed data. Raw amounts arrive without cents. Rows are therefore matched on spender, side, whole-dollar amount, payee and date and one is kept, preferring the processed report. Federal law bars the groups that make them from coordinating with a campaign. A group’s spending is listed under the candidate it named and the side it reported, support or oppose."],
      ["Late money", "The FEC requires a 48-hour notice for any contribution of $1,000 or more received from " + fmtDay(d.late_money.window_start) + " through " + fmtDay(d.late_money.window_end) + ", and a 24-hour report for independent expenditures of $1,000 or more in the same period. Both lists are rebuilt on every run and stamped with the time of the check."],
      ["Donor crossover rule", m.crossover_rule],
      ["How “estimated in the district” works", "A donor with a Massachusetts address is counted in the district when the first five digits of the ZIP code on the receipt are on the primary edition’s list of " + numWord(m.zips.length) + " district ZIP codes, or the town is on its list of " + numWord(m.towns.length) + " towns: " + m.towns.join(", ") + ". Any other Massachusetts address is “elsewhere in Massachusetts.” A receipt with no state is “unknown,” not “out of state.” ZIP codes do not follow district lines exactly and some towns are split, so this is an estimate. The ZIP list: " + m.zips.join(", ") + "."],
      ["Donor records, not people", "Donor counts are distinct name-and-ZIP-code records within one committee’s itemized receipts. Two spellings of one person count twice; two people who share a name and ZIP code count once."],
      ["Spending categories", "A keyword match against each committee’s own description of the expense, in this order, first match wins: " + m.category_rules.map((r) => r.category + " (" + r.patterns.map((p) => p.replace(/\\b/g, "").replace(/[\\()?!|]/g, "")).join(", ").toLowerCase() + ")").join("; ") + ". Anything else with a description is “Other”; a blank description is “Uncategorized.” These are the primary edition’s rules, unchanged."],
      ["What the filings cannot show", "Unitemized gifts, those from donors whose total giving stays at $200 or less, appear only as a lump sum on the summary page, so they are missing from the geography, election split, crossover and weekly figures. Employer, occupation and address fields are self-reported. Spending descriptions are the filer’s own words, and a payment to a processor or consultant can hide the ultimate vendor. Outside spending that a group has not yet reported, and any spending on communications that are not independent expenditures, do not appear. The crossover match cannot tell two people with the same name and ZIP code apart, and misses a donor who moved or changed how they wrote their name."],
    ];
    const ids = ["source", "report", "amendments", "memo", "reconciliation", "elections", "outside", "late", "crossover", "district", "records", "spending", "limits"];
    const host = clear(byId("methodology-list"));
    if (state.mobile) {
      // Phone version: each subsection is its own collapsible item, collapsed
      // by default; a link to one of them opens it.
      const list = el("div", { class: "method-list" });
      items.forEach(([dt, dd], i) => list.appendChild(el("details", { class: "method-item", id: "method-" + ids[i] }, [el("summary", {}, [dt]), el("p", {}, [dd])])));
      host.appendChild(list);
    } else {
      const list = el("dl", {});
      items.forEach(([dt, dd], i) => { list.appendChild(el("dt", { id: "method-" + ids[i], class: "method-item" }, [dt])); list.appendChild(el("dd", {}, [dd])); });
      host.appendChild(list);
    }
    openMethodFromHash();
  }
  function openMethodFromHash() {
    const h = location.hash;
    if (!h || h.indexOf("#method-") !== 0) return;
    const item = document.querySelector(h);
    if (item && item.tagName === "DETAILS") item.open = true;
  }

  // ---------------------------------------------------------------- nav
  function initSectionNav() {
    const links = [...document.querySelectorAll("#ma06-app .sectionnav-links a")];
    const sections = links.map((l) => document.querySelector(l.getAttribute("href")));
    const setActive = () => {
      let idx = 0;
      const y = window.scrollY + 140;
      sections.forEach((s, i) => { if (s && s.offsetTop <= y) idx = i; });
      links.forEach((l, i) => { l.classList.toggle("active", i === idx); if (i === idx) l.setAttribute("aria-current", "location"); else l.removeAttribute("aria-current"); });
    };
    window.addEventListener("scroll", setActive, { passive: true });
    setActive();
    const jump = byId("jump-to-section");
    if (jump) jump.addEventListener("change", () => { const t = document.querySelector(jump.value); if (t) t.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); });
  }

  async function init() {
    try {
      const [data, copy] = await Promise.all([fetchJson("dashboard.json"), fetchJson("copy.json").catch(() => null)]);
      state.data = data; state.copy = copy;
    } catch (err) {
      byId("headline").textContent = "The dashboard data could not be loaded";
      clear(byId("overview-metrics")).appendChild(emptyState("The pre-built data file could not be loaded (" + err.message + "). If this page was opened directly from a file, serve the folder over HTTP; if it is embedded, check window.MA06_DATA_BASE."));
      return;
    }
    renderMasthead();
    renderOverview();
    renderElections();
    renderOutside();
    renderLate();
    renderCrossover();
    renderGeography();
    renderParty();
    renderMethodology();
    initSectionNav();
    observeLazy("geography", loadUsMapOnce);
    // Below-the-fold charts render when their section nears the viewport.
    observeLazy("timeline", renderTimeline);
    observeLazy("spending", () => { state.rendered.spending = true; renderSpending(); });
    window.addEventListener("hashchange", openMethodFromHash);
    // Rotation and resizes: re-decide which x-axis labels fit, debounced.
    window.addEventListener("resize", debounce(() => { if (state.rendered.timeline) thinTimelineLabels(); }, 150));
  }
  // Crossing 768 px by resize or rotation swaps the presentation of every
  // component whose markup differs, from the data already loaded.
  function onVersionChange(e) {
    state.mobile = e.matches;
    applyVersionAttr();
    if (!state.data) return;
    renderOverview();
    renderOutside();
    renderLate();
    renderCrossover();
    renderGeography();
    renderParty();
    if (state.rendered.timeline) renderTimeline();
    renderMethodology();
  }
  if (MOBILE_MQ.addEventListener) MOBILE_MQ.addEventListener("change", onVersionChange); else MOBILE_MQ.addListener(onVersionChange);
  // Inside a Ghost HTML card the script is injected after the page has
  // parsed, so DOMContentLoaded has already fired; start at once in that case.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
