#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rental_market_tracker.py
========================
Weekly tracker of the Tahiti rental market (residential listings only).

Goal: measure which listings enter and leave the rental market each week,
and how long they stayed online, by region, size and rent per m².

Method
------
A daily snapshot records the ids of every rental listing online, and of those
marked unavailable. Most rented listings are deleted from the site rather than
marked as rented, so the weekly figures are derived from the snapshots:
  * entry:     first snapshot in which a listing is online
               (the very first snapshot is the baseline)
  * departure: online in one snapshot, missing from the next,
               and still missing from the latest one
Time on market = date of the snapshot that found the listing gone, minus its
creation date. When that date was never saved, it is estimated from the
listing number, since numbers follow the order of creation. A listing put
back online is counted from its return.
Size comes from the listing's own type (studio, F1 to F5+), never guessed from
the area. Rent per m² is shown only when plausible (5 to 100 €/m²).
A snapshot with a failed page or a sudden drop of more than 20% is flagged and
ignored, so a site failure never looks like listings leaving.

Notes: pages are fetched 25 listings at a time (larger pages were cut short by
the site). Listing ids are stored as integers and must never be compared with
text ids; that mismatch caused the 448-departure bug fixed on 4 Oct 2026.

Usage
-----
  python rental_market_tracker.py --capture           # daily snapshot (no output)
  python rental_market_tracker.py --report            # snapshot + weekly report
  python rental_market_tracker.py --asof 2026-10-03   # report for that day, from saved snapshots only

State: rental_tracking_state.json next to this file.
"""
# ---------------------------------------------------------------------------
# Public excerpt of a production script (full version in a private repository).
# Site-specific code (API access, listing fields, message formatting) has been
# removed and is marked [omitted]. The remaining code is unchanged.
# ---------------------------------------------------------------------------

import bisect
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone

SITE = os.environ.get("LISTINGS_SITE", "https://listings.example")  # source website withheld in this public version
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rental_tracking_state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) immotrack/1.0"

# Same buyer-profile exclusions as every other report.
EXCLUDED_CATEGORIES = {
    "Droit au bail", "Immobilier d'entreprise", "Fonds de commerce",
    "Terrain", "Parking/Garage",
}
TRACK_CATEGORIES = ("Appartement", "Maison")  # residential focus for tracking

WEEK = timedelta(days=7)
EUR_M2_MIN, EUR_M2_MAX = 5, 100   # outside this, the ad's m² is a typo (2 000 m² for a F2...)
MAX_DROP = 0.8                    # fewer than 80% of the last good capture = site problem


def http_get_json(url, attempts=4):
    ...  # [omitted] HTTP request with retries


def fetch_scope(is_available):
    """All rental bids on Tahiti for one availability value -> (items, complete)."""
    ...  # [omitted] API request and pagination, with a completeness check on each page


def to_utc(s):
    ...  # [omitted] date conversion


def category(b):
    ...  # [omitted] listing field access


def region(b):
    ...  # [omitted] mapping of localities to regions


def size_band(m):
    ...  # [omitted] size bands


def price_eur(b):
    ...  # [omitted] listing field access


def surface_m2(b):
    """Living area only (the plot/land area is never a living area)."""
    v = (b.get("realty") or {}).get("area")
    try:
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def locality(b):
    ...  # [omitted] listing field access


def agency(b):
    ...  # [omitted] listing field access


def bid_link(b):
    ...  # [omitted] listing URL


def attrs_of(b):
    ...  # [omitted] listing field access


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"history": {}, "snapshots": {}}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, STATE_FILE)


def today_str(now):
    return now.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Capture (daily, silent)
# --------------------------------------------------------------------------
def capture(state, now):
    avail, ok_avail = fetch_scope(True)
    gone, ok_gone = fetch_scope(False)
    # Residential only: keep exactly the tracked residential categories.
    avail = [b for b in avail if category(b) in TRACK_CATEGORIES]
    gone = [b for b in gone if category(b) in TRACK_CATEGORIES]

    ts = today_str(now)
    avail_ids = {b["id"] for b in avail}
    gone_ids = {b["id"] for b in gone}

    snap = state.setdefault("snapshots", {})
    good = [d for d in good_captures(snap) if d < ts]
    ok = ok_avail and ok_gone
    if ok and good and len(avail_ids) < MAX_DROP * len(snap[good[-1]].get("avail", [])):
        ok = False  # a fifth of the market does not rent overnight: the site answered badly

    by_id = {}
    for b in avail + gone:
        by_id[b["id"]] = b

    history = state.setdefault("history", {})
    was_empty = not history  # True on the very first capture (baseline)
    baseline_ts = (now - WEEK).strftime("%Y-%m-%d")  # treat pre-existing as older than the week
    for bid_id, b in by_id.items():
        rec = history.get(str(bid_id))
        if rec is None:
            first = baseline_ts if was_empty else ts
            rec = {
                "first_seen": first,
                "last_available": ts if bid_id in avail_ids else None,
                "last_gone": ts if bid_id in gone_ids else None,
                "attrs": attrs_of(b),
            }
            history[str(bid_id)] = rec
        else:
            # preserve first_seen; update last_available / last_gone as observed
            if bid_id in avail_ids:
                rec["last_available"] = ts
            if bid_id in gone_ids:
                rec["last_gone"] = ts
            for k, v in attrs_of(b).items():  # attrs stay frozen at first sight;
                rec["attrs"].setdefault(k, v)  # only fields added later (type, created) fill in

    # A bad capture never replaces a good one of the same day.
    old = snap.get(ts)
    if ok or not (old and old.get("ok", True)):
        snap[ts] = {"avail": sorted(avail_ids), "gone": sorted(gone_ids), "ok": ok}
    # Baseline done on first capture -> future reports are real.
    if "baselined" not in state:
        state["baselined"] = ts
    # every capture is kept (the weekly PDF and the data export read the whole history)

    save_state(state)
    return avail_ids, gone_ids


# --------------------------------------------------------------------------
# Reporting (weekly)
# --------------------------------------------------------------------------
def fmt_eur(x):
    ...  # [omitted] number formatting


def eur_m2(pr, m2_):
    """€/m², or None when the m² of the ad cannot be right."""
    if pr is None or not m2_ or m2_ <= 0:
        return None
    v = pr / m2_
    return v if EUR_M2_MIN <= v <= EUR_M2_MAX else None


def fmt_eur_m2(pr, m2_):
    ...  # [omitted] number formatting


def size_label(a):
    """The ad's own type: Studio, F1..F4, F5+ (F5 and >F5); nc when unknown."""
    t = (a.get("type") or "").strip()
    if t in ("F5", ">F5"):
        return "F5+"
    return t or "nc"


def size_or_area(a):
    ...  # [omitted] label formatting


def creation_dates(history):
    """Function id -> creation date. Known dates come from the ads; for an ad gone
    before its date was saved, interpolate between the nearest listing numbers."""
    known = []
    for k, r in history.items():
        c = (r.get("attrs") or {}).get("created")
        if c:
            try:
                known.append((int(k), datetime.strptime(c, "%Y-%m-%d")))
            except ValueError:
                pass
    known.sort()
    ids = [k for k, _ in known]
    exact = dict(known)

    def get(bid):
        i = int(bid)
        if i in exact:
            return exact[i]
        if not known:
            return None
        k = bisect.bisect_left(ids, i)
        if k == 0:
            return known[0][1]
        if k >= len(known):
            return known[-1][1]
        (i1, d1), (i2, d2) = known[k - 1], known[k]
        return d1 + (d2 - d1) * ((i - i1) / (i2 - i1))

    return get


def good_captures(snap, upto=None):
    """Dates of the captures to trust, oldest first: those saved with ok=true, and older
    ones without the flag unless they hold under 80% of the listings of the last trusted
    capture (a fetch that failed half-way, like 02/10/2026: 67 listings instead of ~400)."""
    good = []
    for d in sorted(snap):
        if upto is not None and d > upto:
            break
        s = snap[d]
        if "ok" in s:
            if s["ok"]:
                good.append(d)
        elif not good or len(s.get("avail", [])) >= MAX_DROP * len(snap[good[-1]].get("avail", [])):
            good.append(d)
    return good


def week_moves(state, day):
    """The week ending on `day` (YYYY-MM-DD), from the good captures up to that day:
    {"snaps", "cur", "ws", "entrees": [id], "sortis": [{"id", "out", "days_on_market"}]}."""
    history = state.get("history", {})
    snap = state.get("snapshots") or {}
    snaps = good_captures(snap, day)
    ws = (datetime.strptime(day, "%Y-%m-%d") - WEEK).strftime("%Y-%m-%d")
    res = {"snaps": snaps, "cur": snaps[-1] if snaps else None, "ws": ws, "entrees": [], "sortis": []}
    if len(snaps) <= 1:
        return res

    # Each listing: first and last capture where it was online.
    first_av, last_av = {}, {}
    for d in snaps:
        for i in snap[d].get("avail", []):
            i = str(i)
            first_av.setdefault(i, d)
            last_av[i] = d
    next_capture = dict(zip(snaps, snaps[1:]))
    created = creation_dates(history)

    # --- Entries this week: first online during the week (not in the baseline snapshot)
    res["entrees"] = sorted(i for i, d in first_av.items() if d > snaps[0] and ws < d <= day)

    # --- Departures this week: online, then missing from a snapshot of the week, not back since
    for i, d in last_av.items():
        if d == res["cur"]:
            continue  # still online at the latest capture
        out = next_capture[d]  # first capture that found it gone
        if ws < out <= day:
            start = created(i)
            seen = datetime.strptime(first_av[i], "%Y-%m-%d")
            if first_av[i] > snaps[0] and (start is None or (seen - start).days > 2):
                start = seen  # an old ad put back online: count from its return
            dom = max(0, (datetime.strptime(out, "%Y-%m-%d") - start).days) if start else None
            res["sortis"].append({"id": i, "out": out, "days_on_market": dom})
    res["sortis"].sort(key=lambda r: r["days_on_market"] if r["days_on_market"] is not None else 9999)
    return res


def weekly_report(state, now, asof=None):
    ...  # [omitted] text of the weekly report (counts, fastest departures, segments), built from week_moves()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    state = load_state()

    if "--asof" in args:  # an earlier day's report, from the saved captures only
        k = args.index("--asof")
        asof = args[k + 1] if k + 1 < len(args) else ""
        datetime.strptime(asof, "%Y-%m-%d")  # stops on a malformed date
        print(weekly_report(state, now, asof))
        return

    if "--report" in args:
        capture(state, now)          # refresh before reporting
        print(weekly_report(state, now))
        return

    # --capture, or no option (the scheduler passes none): daily capture, silent
    capture(state, now)


if __name__ == "__main__":
    main()
