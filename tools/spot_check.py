#!/usr/bin/env python3
"""
Spot-check five figures per candidate against two independent sources:

  1. The candidate totals endpoint (/candidate/{id}/totals/, election_full),
     which is what the FEC.gov candidate page displays.
  2. The summary line (F3) of the committee's own most recent raw filing on
     docquery.fec.gov: cycle-to-date receipts and disbursements, cash on hand
     and debts, read straight from the filer's submission.

Compares each with data/dashboard.json and prints a table. Exits 1 on any
mismatch larger than a cent.

    export FEC_API_KEY=...
    python3 tools/spot_check.py
"""
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.open.fec.gov/v1"


def main():
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key:
        sys.exit("FEC_API_KEY is not set")
    s = requests.Session()
    s.headers["X-Api-Key"] = key
    with open(os.path.join(ROOT, "data", "dashboard.json"), encoding="utf-8") as f:
        d = json.load(f)
    bad = 0
    rows = []
    for c in d["candidates"]:
        t = c["totals"]
        r = s.get(f"{API}/candidate/{c['candidate_id']}/totals/", params={"cycle": d["meta"]["cycle"], "election_full": "true"}, timeout=60)
        r.raise_for_status()
        ct = (r.json().get("results") or [{}])[0]
        fec_page = {
            "total_receipts": ct.get("receipts"), "total_disbursements": ct.get("disbursements"),
            "cash_on_hand": ct.get("last_cash_on_hand_end_period"), "debts": ct.get("last_debts_owed_by_committee"),
            "individual_itemized": ct.get("individual_itemized_contributions"),
        }
        ours = {"total_receipts": t["receipts"], "total_disbursements": t["disbursements"], "cash_on_hand": t["cash_on_hand"],
                "debts": t["debts"], "individual_itemized": t["individual_itemized"]}
        # raw filing summary line
        raw = {}
        fn = (c.get("latest_report") or {}).get("file_number")
        if fn:
            rr = requests.get(f"https://docquery.fec.gov/dcdev/posted/{fn}.fec", timeout=60)
            if rr.ok:
                lines = rr.text.split("\n")
                f3 = next((ln for ln in lines if ln.startswith("F3")), "")
                parts = f3.split("\x1c")
                # Version 8.x F3 summary: column B (cycle to date) totals sit after the
                # period columns; locate by the period figures we already know.
                nums = [p for p in parts if re.fullmatch(r"-?\d+\.\d\d", p)]
                raw = {"numbers_on_f3_line": len(nums),
                       "cycle_receipts_present": f"{t['receipts']:.2f}" in nums,
                       "cycle_disbursements_present": f"{t['disbursements']:.2f}" in nums,
                       "cash_on_hand_present": f"{t['cash_on_hand']:.2f}" in nums,
                       "debts_present": f"{t['debts']:.2f}" in nums,
                       "individual_itemized_cycle_present": f"{t['individual_itemized']:.2f}" in nums}
        for k in ours:
            match = fec_page.get(k) is not None and abs(float(fec_page[k]) - float(ours[k])) <= 0.01
            bad += 0 if match else 1
            rows.append((c["name"], k, ours[k], fec_page.get(k), "match" if match else "MISMATCH"))
        for k, v in raw.items():
            if k != "numbers_on_f3_line" and not v:
                bad += 1
            rows.append((c["name"], "raw filing " + str(fn) + " " + k, "", v, "" if k == "numbers_on_f3_line" else ("match" if v else "MISMATCH")))
        # Independent-expenditure totals as the FEC computes them per group and side.
        r = s.get(f"{API}/schedules/schedule_e/by_candidate/", params={"candidate_id": c["candidate_id"], "cycle": d["meta"]["cycle"], "election_full": "true", "per_page": 100}, timeout=60)
        r.raise_for_status()
        fec_ie = {((x.get("committee_name") or "").upper(), x.get("support_oppose_indicator")): x.get("total") for x in r.json().get("results", [])}
        for g in d["outside_spending"]["by_group"]:
            for side, code in (("support", "S"), ("oppose", "O")):
                ours_v = g.get(f"{c['key']}_{side}", 0)
                if not ours_v:
                    continue
                fv = fec_ie.get((g["group"].upper(), code))
                if fv is None:
                    rows.append((c["name"], f"IE {side} by {g['group']}", ours_v, "not in FEC per-candidate totals (notice or raw only)", "note"))
                    continue
                match = abs(float(fv) - float(ours_v)) <= 0.01
                bad += 0 if match else 1
                rows.append((c["name"], f"IE {side} by {g['group']}", ours_v, fv, "match" if match else "MISMATCH"))
        print(f"{c['name']}: compare at {c['fec_candidate_url']}")
    w = max(len(str(r[1])) for r in rows)
    for r in rows:
        print(f"  {r[0]:<12} {str(r[1]):<{w}}  dashboard={r[2]!s:<14} source={r[3]!s:<14} {r[4]}")
    print("\n" + ("All figures match." if bad == 0 else f"{bad} mismatches."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
