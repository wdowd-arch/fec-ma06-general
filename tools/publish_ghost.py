#!/usr/bin/env python3
"""
Daily refresh of the MA-06 dashboard on marbleheadindependent.com in one
command. Reads every credential from the environment and never writes one
anywhere:

    FEC_API_KEY          OpenFEC key, used by build_data.py
    GHOST_ADMIN_API_KEY  Ghost Admin API key, "id:secret"
    GHOST_ADMIN_URL      https://www.marbleheadindependent.com

What it does, in order:

  1. python3 build_data.py --refresh, then python3 tools/spot_check.py;
     stops if either fails.
  2. Uploads data/dashboard.json and data/build_log.json through the Ghost
     Admin API (and data/copy.json when its content changed since the last
     upload). Ghost renames a repeat upload, so the new URLs are recorded in
     ghost/manifest.json. styles.css and app.js travel inside the card.
  3. Regenerates ghost/embed.html from the manifest and updates the HTML
     card on the page with slug ma-06-general, keeping its draft or
     published status.
  4. Scans every file it touched for the keys.

First-time setup uploads every file and creates the page as a draft:

    python3 tools/publish_ghost.py --setup

Options: --no-build (skip step 1), --card-only (no build, no uploads; just
rewrite the card after a page-code change), --dry-run (no uploads, no page
write), --publish (set the page live; by default a draft stays a draft).
"""
import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import subprocess
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "ghost", "manifest.json")
EMBED = os.path.join(ROOT, "ghost", "embed.html")
SLUG = "ma-06-general"
PAGE_TITLE = "MA-06 general election money"
META_TITLE = "MA-06 general election money — The Marblehead Independent"
META_DESCRIPTION = ("Dan Koh and Micah Jones head to head on receipts, spending, outside money, late contributions and "
                    "donor geography in the Nov. 3, 2026, general election for Massachusetts' 6th Congressional District, "
                    "built from Federal Election Commission filings.")
# styles.css and app.js are carried inside the card: Ghost's storage serves
# uploaded .css and .js as text/plain, which browsers refuse for a
# cross-origin stylesheet. The manifest marks them "inline".
INLINE_FILES = {"styles": "styles.css", "script": "app.js"}
ALL_FILES = {
    "dashboard.json": "data/dashboard.json",
    "build_log.json": "data/build_log.json", "copy.json": "data/copy.json",
    "us-states-paths.json": "data/us-states-paths.json",
    # Images are keyed by file name so the embed can resolve src and srcset entries.
    "nameplate-horizontal.png": "assets/images/nameplate-horizontal.png",
    "nameplate-horizontal-800.png": "assets/images/nameplate-horizontal-800.png",
    "koh.jpg": "assets/images/koh.jpg", "koh-480.jpg": "assets/images/koh-480.jpg",
    "jones.jpg": "assets/images/jones.jpg", "jones-480.jpg": "assets/images/jones-480.jpg",
}
INLINE_IF_REFUSED = set()
DAILY_FILES = ["dashboard.json", "build_log.json"]


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Ghost:
    def __init__(self, site, key):
        self.site = site.rstrip("/")
        self.kid, self.secret = key.split(":", 1)
        self.s = requests.Session()
        self.admin = self.site
        # Ghost(Pro) answers the Admin API on the site's ghost.io host and
        # redirects there from the custom domain; a redirect across hosts
        # drops the Authorization header, so resolve the host once.
        try:
            r = self.s.get(f"{self.site}/ghost/api/admin/site/", allow_redirects=False, timeout=30)
            if r.is_redirect and r.headers.get("Location", "").startswith("http"):
                loc = r.headers["Location"]
                self.admin = loc.split("/ghost/")[0]
        except requests.RequestException:
            pass

    def token(self):
        now = int(time.time())
        header = b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": self.kid}).encode())
        payload = b64url(json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode())
        sig = b64url(hmac.new(bytes.fromhex(self.secret), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        return f"{header}.{payload}.{sig}"

    def headers(self):
        return {"Authorization": "Ghost " + self.token(), "Accept-Version": "v5.0"}

    def api(self, method, path, **kw):
        r = self.s.request(method, f"{self.admin}/ghost/api/admin{path}", headers=self.headers(), timeout=120, **kw)
        if not r.ok:
            raise RuntimeError(f"Ghost {method} {path}: HTTP {r.status_code} {r.text[:400]}")
        return r.json() if r.text else {}

    def upload(self, local_path, dry_run=False):
        """Images go to /images/upload/, everything else to /files/upload/.
        Returns the public URL Ghost assigned."""
        name = os.path.basename(local_path)
        is_image = name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"))
        endpoint = "/images/upload/" if is_image else "/files/upload/"
        if dry_run:
            return f"{self.site}/content/{'images' if is_image else 'files'}/dry-run/{name}"
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(local_path, "rb") as f:
            files = {"file": (name, f, ctype)}
            data = {"ref": name} if not is_image else {}
            body = self.api("POST", endpoint, files=files, data=data)
        key = "images" if is_image else "files"
        return body[key][0]["url"]

    def get_page(self):
        try:
            return self.api("GET", f"/pages/slug/{SLUG}/")["pages"][0]
        except RuntimeError as exc:
            if "404" in str(exc):
                return None
            raise

    def write_page(self, html, existing=None, publish=False, dry_run=False):
        card = "<!--kg-card-begin: html-->\n" + html + "\n<!--kg-card-end: html-->"
        page = {
            "title": PAGE_TITLE, "slug": SLUG, "html": card,
            "meta_title": META_TITLE, "meta_description": META_DESCRIPTION,
            "canonical_url": f"{self.site}/{SLUG}/",
            "status": "published" if publish else (existing or {}).get("status", "draft"),
        }
        if dry_run:
            return existing or {"uuid": "dry-run", "status": page["status"]}
        if existing:
            page["updated_at"] = existing["updated_at"]
            body = self.api("PUT", f"/pages/{existing['id']}/?source=html", json={"pages": [page]})
        else:
            body = self.api("POST", "/pages/?source=html", json={"pages": [page]})
        return body["pages"][0]


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(cmd):
    print("$ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def scan_for_keys(paths, keys):
    hits = []
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, "rb") as f:
            data = f.read()
        for k in keys:
            if k and k.encode() in data:
                hits.append(p)
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true", help="upload every file and create the page as a draft")
    ap.add_argument("--no-build", action="store_true", help="skip build_data.py and spot_check.py")
    ap.add_argument("--dry-run", action="store_true", help="no uploads, no page write")
    ap.add_argument("--publish", action="store_true", help="set the page status to published")
    ap.add_argument("--card-only", action="store_true", help="no build, no uploads: regenerate the card from the manifest and update the page")
    args = ap.parse_args()

    if args.card_only:
        args.no_build = True
    fec_key = os.environ.get("FEC_API_KEY", "").strip()
    ghost_key = os.environ.get("GHOST_ADMIN_API_KEY", "").strip()
    site = os.environ.get("GHOST_ADMIN_URL", "").strip()
    if not args.dry_run and (not ghost_key or not site):
        sys.exit("GHOST_ADMIN_API_KEY and GHOST_ADMIN_URL must be set in the environment")
    if not args.no_build and not fec_key:
        sys.exit("FEC_API_KEY must be set in the environment (or pass --no-build)")

    # 1. fresh build and spot-check
    if not args.no_build:
        if run([sys.executable, "build_data.py", "--refresh"]) != 0:
            sys.exit("build_data.py failed; nothing uploaded")
        if run([sys.executable, os.path.join("tools", "spot_check.py")]) != 0:
            sys.exit("spot_check.py reported a mismatch; nothing uploaded")

    manifest = {"base": site + "/content/files/", "files": {}}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    ghost = Ghost(site or "https://example.invalid", ghost_key or "0:00")

    # 2. uploads
    todo = list(ALL_FILES) if args.setup else list(DAILY_FILES)
    if args.card_only:
        todo = []
    copy_path = os.path.join(ROOT, ALL_FILES["copy.json"])
    if not args.setup and not args.card_only and manifest["files"].get("copy.json", {}).get("sha256") != sha(copy_path):
        todo.append("copy.json")
    for key, rel in INLINE_FILES.items():
        manifest["files"][key] = {"inline": True, "sha256": sha(os.path.join(ROOT, rel))}
    for key in todo:
        local = os.path.join(ROOT, ALL_FILES[key])
        try:
            url = ghost.upload(local, dry_run=args.dry_run)
        except RuntimeError as exc:
            if key in INLINE_IF_REFUSED:
                print(f"Ghost refused {ALL_FILES[key]} ({str(exc)[:80]}); it will be carried inside the card instead")
                manifest["files"][key] = {"inline": True, "sha256": sha(local)}
                continue
            raise
        manifest["files"][key] = {"url": url, "sha256": sha(local), "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        print(f"uploaded {ALL_FILES[key]} -> {url}")
    missing = [k for k in ALL_FILES if k not in manifest["files"] or not manifest["files"][k].get("url")]
    if missing:
        sys.exit(f"manifest has no URL for {', '.join(missing)}; run with --setup once")
    if manifest["files"].get("dashboard.json", {}).get("url"):
        manifest["base"] = manifest["files"]["dashboard.json"]["url"].rsplit("/", 1)[0] + "/"
    if not args.dry_run:
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)

    # 3. embed and page
    if run([sys.executable, os.path.join("tools", "make_embed.py"), "--manifest", MANIFEST] + ([] if not args.dry_run else [])) != 0:
        sys.exit("make_embed.py failed")
    with open(EMBED, encoding="utf-8") as f:
        html = f.read()
    existing = None if args.dry_run and not site else ghost.get_page() if not args.dry_run else None
    page = ghost.write_page(html, existing=existing, publish=args.publish, dry_run=args.dry_run)
    status = page.get("status")
    if status == "published":
        print(f"page live: {site}/{SLUG}/")
    else:
        print(f"page saved as {status}; preview: {site}/p/{page.get('uuid')}/")

    # 4. key scan
    hits = scan_for_keys([MANIFEST, EMBED, os.path.join(ROOT, "data", "dashboard.json"), os.path.join(ROOT, "data", "build_log.json")] if not args.dry_run else [EMBED],
                         [fec_key, ghost_key, ghost_key.split(":")[-1] if ghost_key else ""])
    if hits:
        for h in hits:
            os.remove(h)
        sys.exit("ABORT: a key appeared in an output file; the file was removed")
    print("done; no keys in any output")


if __name__ == "__main__":
    main()
