#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_digest.py
===============
Daily digest of the Tahiti property market.

  Sales (up to a price ceiling set in the configuration):
    - new listings, each reported once
    - number of new listings over 24 hours, 7 days and 30 days,
      with average price and price per m²
  Rentals:
    - the same figures, with average monthly rent and rent per m²

Runs as a scheduled job without AI: the digest is printed to standard output
and the scheduler posts it to the Telegram group. Market figures are printed
on every run, even when there are no new listings.

State: a JSON file of the listings already reported, so each one appears once.
"""
# ---------------------------------------------------------------------------
# Public excerpt of a production script (full version in a private repository).
# Site-specific code (API access, listing fields, message formatting) has been
# removed and is marked [omitted]. The remaining code is unchanged.
# ---------------------------------------------------------------------------

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
SITE = os.environ.get("LISTINGS_SITE", "https://listings.example")  # source website withheld in this public version
MAX_PRICE_XPF = int(os.environ.get("MAX_PRICE_XPF", "0"))  # sale price ceiling, set in the bot's configuration
CAP_MF = f"{MAX_PRICE_XPF / 1e6:g} MF"                      # the ceiling as shown in messages (millions of XPF)
XPF_PER_EUR = 119.3317              # pegged: 1000 XPF = 8.38 EUR
DISPLAY_TZ = os.environ.get("DISPLAY_TZ", "UTC")  # time zone of the readers (set in the bot's configuration)

# Categories to EXCLUDE from all reports (buyer profile: residential only).
EXCLUDED_CATEGORIES = {
    "Droit au bail", "Immobilier d'entreprise", "Fonds de commerce",
    "Terrain", "Parking/Garage",
}
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "digest_state.json")
# ✅ /keep and ✖ /no taps, saved by the contact-draft add-on: listing number -> {"state": "kept" | "no", ...}
LISTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "plugins", "contact-draft", "listings.json")
# The scheduler's record of the jobs (read only): did the last digest reach Telegram?
JOBS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cron", "jobs.json")
CATCHUP_MAX_DAYS = 4  # after a long outage the digest goes back 4 days at most
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) immobot/1.0"

WINDOWS = [
    ("24h", 1),
    ("7j", 7),
    ("30j", 30),
]

CURR = lambda a: {"currency": {"id": 1, "name": "Franc pacifique", "symbol": "CFP", "internationalCode": "XPF"}, "amount": a}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def http_get_json(url, attempts=4):
    """GET a JSON URL with retry-on-truncation/network-error backoff.
    Returns parsed JSON, or None if all attempts fail."""
    ...  # [omitted] HTTP request with retries


def fetch_bids(typeid, tahiti=True, price_max=None, typeids=None):
    """All bids for a type, optionally scoped to Tahiti and a price cap.
    typeids: pass [1,4] for the sale scope (Vente + Promotion). For rentals
    omit it, else the filter cross-contaminates with other categories.
    Retries transient network errors (IncompleteRead etc.) per page.
    Returns (items, ok_flag); ok=False means a page ultimately failed."""
    ...  # [omitted] API request, pagination and filters


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def slugify(s):
    ...  # [omitted] text normalisation


def category_excluded(bid):
    """True if the bid's realty category is excluded from reports."""
    cat = (bid.get("realty") or {}).get("category") or {}
    return (cat.get("label") or "") in EXCLUDED_CATEGORIES


def keep_only_relevant(bids):
    return [b for b in bids if not category_excluded(b)]


CAT_EMOJI = {
    "appartement": "🏢", "maison": "🏠", "terrain": "🌄", "immeuble": "🏬",
    "parking-garage": "🅿️", "fonds-de-commerce": "🏪", "droit-au-bail": "⚖️",
    "immobilier-d-entreprise": "🏢", "propriete": "🏠", "modele-de-maison": "🏗️",
}


def _realty(bid):
    ...  # [omitted] listing field access


def surface_m2(bid):
    ...  # [omitted] listing field access


def category_label(bid):
    ...  # [omitted] listing field access


def locality_label(bid):
    ...  # [omitted] listing field access


def agency_label(bid):
    ...  # [omitted] listing field access


def bid_link(bid):
    ...  # [omitted] listing URL


def decisions():
    """Listing number -> "kept" or "no", as tapped in the group (empty when nothing was tapped yet)."""
    try:
        with open(LISTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): v.get("state") for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def state_time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def last_digest_failed():
    """True when this digest's last run did not reach Telegram (the scheduler's job status)."""
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        jobs = jobs.get("jobs", jobs) if isinstance(jobs, dict) else jobs
        mine = [j for j in jobs if isinstance(j, dict) and j.get("script") == os.path.basename(__file__)]
        return bool(mine) and str(mine[0].get("last_status") or "") in ("delivery_failed", "error")
    except (OSError, ValueError, AttributeError):
        return False


def local_time(naive_utc):
    try:
        from zoneinfo import ZoneInfo
        return f"{naive_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(DISPLAY_TZ)):%d/%m à %H:%M}"
    except Exception:
        return f"{naive_utc:%d/%m à %H:%M} UTC"


def today_string(dt):
    return dt.strftime("%Y-%m-%d")


def price_amount(bid):
    ...  # [omitted] listing field access


def parse_iso(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:  # the site gives Tahiti local time (UTC-10, no summer time)
            dt = dt.replace(tzinfo=timezone(timedelta(hours=-10)))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def fmt_mf(amount, eur=False):
    ...  # [omitted] number formatting


def fmt_eur_m2(v):
    ...  # [omitted] number formatting


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def window_stats(bids, now):
    """For each window (24h/7d/30d): new count, avg price, avg €/m²."""
    out = {}
    for label, days in WINDOWS:
        cutoff = now - timedelta(days=days)
        in_win = [b for b in bids if (parse_iso(b.get("risingDate") or b.get("createdDate")) or now) >= cutoff]
        prices = [price_amount(b) for b in in_win if price_amount(b) is not None]
        per_m2 = []
        for b in in_win:
            amt, m2 = price_amount(b), surface_m2(b)
            if amt is not None and m2:
                per_m2.append(amt / XPF_PER_EUR / m2)
        out[label] = {
            "count": len(in_win),
            "avg_price": sum(prices) / len(prices) if prices else None,
            "avg_eur_m2": sum(per_m2) / len(per_m2) if per_m2 else None,
        }
    return out


def fmt_stats_block(title, emoji, stats, price_is_rent=False):
    ...  # [omitted] message formatting


# --------------------------------------------------------------------------
# Formatting a single new listing
# --------------------------------------------------------------------------
def format_bid(bid):
    ...  # [omitted] message formatting for one listing (keep, drop and contact commands)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    force_report = "--report" in sys.argv
    catchup = None
    if "--catchup" in sys.argv:
        try:
            catchup = int(sys.argv[sys.argv.index("--catchup") + 1])
        except (ValueError, IndexError):
            catchup = 5
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except (ValueError, IndexError):
            limit = 10
    if force_report and limit is None:
        limit = 10

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC

    # --- Fetch scopes (excluded categories removed) ---------------------
    sale_bids, sale_ok = fetch_bids(1, tahiti=True, price_max=MAX_PRICE_XPF, typeids=[1, 4])
    rent_bids, rent_ok = fetch_bids(2, tahiti=True)
    sale_bids = keep_only_relevant(sale_bids)
    rent_bids = keep_only_relevant(rent_bids)

    if not sale_ok or not rent_ok:
        print("⚠️  Échec de récupération partiel : les données peuvent être incomplètes.")

    if not sale_bids and not rent_bids:
        print("⚠️  Aucune annonce récupérée (problème API persisté). Aucun digest généré.")
        return

    # --- New-sale diff: show listings published in the daily window ---------
    # The state is a *same-day dedupe* guard (avoid re-sending the same ids on
    # manual re-runs), NOT a permanent seen-set. The links section must match
    # the "nouvelles publiées 24h" stat exactly, so we base it purely on
    # risingDate within the window.
    seen_now = {b["id"]: b for b in sale_bids}
    DAILY_WINDOW = timedelta(days=catchup if catchup else 1)

    # --- same-day dedupe state (JSON: {"date", "sent", "from", "until"}) ----
    state = {}
    if not force_report and not catchup and os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # tolerate the old plain-list format (migrate -> object)
            if isinstance(raw, list):
                state = {"date": None, "sent": []}
            elif isinstance(raw, dict):
                state = raw
        except Exception:
            state = {}
    today = today_string(now)
    same_day = (state.get("date") == today)

    # --- the window: the last 24 hours, with no gap after the last digest that reached the group ----------
    since = now - DAILY_WINDOW
    if not force_report and not catchup:
        oldest = now - timedelta(days=CATCHUP_MAX_DAYS)
        last_from, last_until = state_time(state.get("from")), state_time(state.get("until"))
        if last_until and last_until < since:  # a morning was missed: start where the last digest stopped
            since = max(last_until, oldest)
        if last_from and last_digest_failed():  # the last digest never reached the group: its listings again
            since = max(min(since, last_from), oldest)
            same_day = False

    # candidate ids = published within the window AND still in scope
    cand = []
    for i, b in seen_now.items():
        dt = parse_iso(b.get("risingDate") or b.get("createdDate"))
        if dt is not None and dt >= since:
            cand.append(i)
    cand.sort(key=lambda i: seen_now[i].get("risingDate") or "", reverse=True)

    if force_report or catchup or not same_day:
        to_show = cand                      # fresh window / new day: show all
    else:
        seen_ids = set(state.get("sent", []))
        to_show = [i for i in cand if i not in seen_ids]  # same day: skip already sent

    # persist the sent list (real runs only)
    if not force_report:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": today, "sent": cand, "from": since.isoformat(timespec="seconds"),
                       "until": now.isoformat(timespec="seconds")}, f)

    # --- Trend stats -----------------------------------------------------
    sale_stats = window_stats(sale_bids, now)
    rent_stats = window_stats(rent_bids, now)

    today = now.strftime("%d/%m/%Y")
    _cap_eur = f"{MAX_PRICE_XPF*0.008380:,.0f} €".replace(",", " ")
    if catchup:
        header = (f"🏡 RATTRAPAGE — Tahiti · {today}\n"
                  f"🎯 Vente ≤ {CAP_MF} ({_cap_eur}) · nouvelles annonces des {catchup} derniers jours "
                  f"(rattrapage des jours manqués)")
    else:
        header = (f"🏡 Digest — Tahiti · {today}\n"
                  f"🎯 Vente ≤ {CAP_MF} ({_cap_eur}) · tracking {len(sale_bids)} annonces")

    blocks = [
        fmt_stats_block(f"VENTE ≤ {CAP_MF}", "🏷️", sale_stats),
        fmt_stats_block("LOCATION", "🔑", rent_stats, price_is_rent=True),
    ]

    # --- New sale listings to show ----------------------------------------
    if force_report:  # preview mode: show newest N of the tracked scope (override)
        to_show = sorted(seen_now.keys(), key=lambda i: seen_now[i].get("risingDate") or "", reverse=True)
    picked = decisions()  # kept or dropped in the group: not shown again
    hidden = [i for i in to_show if picked.get(str(i)) in ("kept", "no")]
    to_show = [i for i in to_show if picked.get(str(i)) not in ("kept", "no")]
    if limit:
        to_show = to_show[:limit]

    msg_parts = [header]
    msg_parts.extend(blocks)

    if to_show:
        noun = "Nouvelle annonce" if len(to_show) == 1 else "Nouvelles annonces"
        longer = since < now - timedelta(days=1, minutes=10) and not catchup and not force_report
        msg_parts.append(f"✨ {noun} (vente ≤ {CAP_MF}) — {len(to_show)}" + (f" · depuis le {local_time(since)}" if longer else ""))
        msg_parts.append("\n\n".join(format_bid(seen_now[i]) for i in to_show))

    n_kept = sum(1 for state in picked.values() if state == "kept")
    if hidden or n_kept:
        foot = []
        if hidden:
            k = sum(1 for i in hidden if picked.get(str(i)) == "kept")
            r = len(hidden) - k
            parts = ([f"{k} gardée" + ("s" if k > 1 else "")] if k else []) + \
                    ([f"{r} retirée" + ("s" if r > 1 else "")] if r else [])
            foot.append("🙈 Masquées : " + ", ".join(parts))
        if n_kept:
            foot.append(f"📌 Gardées : {n_kept} · /keep")
        msg_parts.append("\n".join(foot))

    # On the very first run or when nothing new in scope: still report stats
    print("\n\n".join(msg_parts))


if __name__ == "__main__":
    main()
