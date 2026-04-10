#!/usr/bin/env python3
"""FRONTIER-100 builder.

Selects up to 100 early-stage / mid-sized US government contractors in
defense, space, and AI-adjacent NAICS codes, scores them with the
SUPPLY-1000 engine, and writes frontier_cache.json in the same schema
as scores_cache.json so the existing Streamlit UI can render it.
"""
import json
import os
import socket
import sys
import threading
import time
from datetime import date

import requests

socket.setdefaulttimeout(15)

from data_logic import (
    BASE_URL,
    _deduplicate_recipients,
    _normalize_company_name,
    _guess_domain,
    _ttm_window,
    score_company,
    apply_vital_pulse_modifier,
    apply_environment_adjustment,
    search_prime_awards,
    ANALYSIS_YEARS,
)
from vital_pulse import run_vital_pulse
from environment_scores import calculate_environment_adjustment

CACHE_FILE = os.path.join(os.path.dirname(__file__), "frontier_cache.json")
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "frontier_history.json")

# NAICS codes aimed at Erebor Bank's stated focus: defense, AI, space.
FRONTIER_NAICS = {
    "336414": "Guided Missile & Space Vehicle Manufacturing",
    "336415": "Space/Missile Propulsion",
    "336419": "Other Guided Missile & Space Vehicle Parts",
    "334511": "Search, Detection, Navigation, Guidance",
    "334220": "Radio/TV/Wireless Equipment",
    "541330": "Engineering Services",
    "541511": "Custom Computer Programming (AI/Software)",
    "541512": "Computer Systems Design (AI/Software)",
    "541715": "R&D in Physical, Engineering, Life Sciences",
    "541713": "R&D in Nanotechnology",
}

# Company size window: $1M to $100M TTM contract value.
# Below: one-off vendors with nothing to evaluate.
# Above: established mega-primes D&B already covers well.
MIN_VALUE = 1_000_000
MAX_VALUE = 100_000_000
TARGET_COUNT = 100


def _run_with_deadline(fn, timeout, *args, **kwargs):
    """Run fn in a daemon thread and abandon it if it does not return in time."""
    result = [None]
    error = [None]

    def target():
        try:
            result[0] = fn(*args, **kwargs)
        except Exception as exc:
            error[0] = repr(exc)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, "timeout"
    return result[0], error[0]


def fetch_naics_recipients(naics_code, start, end, max_pages=5):
    """Fetch top recipients for a NAICS code, paginating through max_pages."""
    all_results = []
    for page in range(1, max_pages + 1):
        payload = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],
                "time_period": [{"start_date": start, "end_date": end}],
                "naics_codes": {"require": [naics_code]},
            },
            "category": "recipient",
            "limit": 100,
            "page": page,
        }
        try:
            r = requests.post(
                f"{BASE_URL}/search/spending_by_category/recipient/",
                json=payload,
                timeout=30,
            )
            if r.status_code != 200:
                break
            results = r.json().get("results", [])
            if not results:
                break
            all_results.extend(results)
            if len(results) < 100:
                break
        except Exception as e:
            print(f"    fetch error for {naics_code} page {page}: {e}", flush=True)
            break
    return all_results


def build_candidate_pool(start, end):
    """Query every NAICS, merge, dedupe, filter by size, return candidates."""
    all_entries = []
    for naics, label in FRONTIER_NAICS.items():
        print(f"  NAICS {naics} {label}...", flush=True)
        entries = fetch_naics_recipients(naics, start, end, max_pages=5)
        # Tag each entry with its source NAICS so we can inspect later
        for e in entries:
            e["_naics"] = naics
            e["_naics_label"] = label
        all_entries.extend(entries)
        time.sleep(0.3)
    print(f"  Raw candidates across NAICS: {len(all_entries)}", flush=True)

    # Dedupe: same parent company may appear in multiple NAICS
    deduped = _deduplicate_recipients(all_entries)
    print(f"  After dedup: {len(deduped)}", flush=True)

    # Filter by size window
    filtered = [
        e for e in deduped
        if MIN_VALUE <= float(e.get("amount") or 0) <= MAX_VALUE
    ]
    print(f"  After size filter (${MIN_VALUE/1e6:.0f}M-${MAX_VALUE/1e6:.0f}M): {len(filtered)}", flush=True)

    # Sort by amount desc
    filtered.sort(key=lambda e: float(e.get("amount") or 0), reverse=True)
    return filtered[:TARGET_COUNT]


def build_profile(entry, start, end):
    """Build a profile dict matching get_top_company_profiles output."""
    name = entry.get("name")
    amount = float(entry.get("amount") or 0)
    if not name or name.upper() == "REDACTED DUE TO PII":
        return None

    today = date.today()
    current_year = today.year
    history_years = list(range(current_year - 4, current_year))
    ttm_label = current_year

    profile = {
        "name": name,
        "total_prime_value": amount,
        "total_sub_value": 0,
        "agencies": [],
        "prime_contractors": [],
        "sub_contractors": [],
        "yearly_values": {ttm_label: amount},
        "contract_count": 0,
        "sub_count": 0,
        "years_active": [ttm_label],
        "state_code": None,
        "naics_code": entry.get("_naics"),
    }

    # Prime award lookup (TTM window)
    primes = search_prime_awards(recipient_name=name, year=None, limit=200)
    agencies_set = set()
    count = 0
    for award in primes:
        rname = (award.get("Recipient Name") or "").upper()
        if name.upper()[:15] in rname:
            count += 1
            agency = award.get("Awarding Agency")
            if agency:
                agencies_set.add(agency)
    profile["agencies"] = list(agencies_set)
    profile["contract_count"] = count

    # Historical lookback for continuity: query prime awards per historical
    # year for this specific recipient so even early-stage companies that are
    # not in the overall top-N can still populate years_active.
    for hy in history_years:
        hy_primes = search_prime_awards(recipient_name=name, year=hy, limit=100)
        hy_value = 0.0
        for award in hy_primes:
            rname = (award.get("Recipient Name") or "").upper()
            if name.upper()[:15] in rname:
                hy_value += float(award.get("Award Amount") or 0)
        if hy_value > 0:
            profile["yearly_values"][hy] = hy_value
            if hy not in profile["years_active"]:
                profile["years_active"].append(hy)

    return profile


def main():
    today_str = date.today().isoformat()
    print(f"[FRONTIER-100] Building for {today_str}", flush=True)

    start, end = _ttm_window()
    print(f"  TTM window: {start} to {end}", flush=True)

    print("[FRONTIER-100] Step 1: Build candidate pool", flush=True)
    candidates = build_candidate_pool(start, end)
    if len(candidates) < 10:
        print(f"ERROR: only {len(candidates)} candidates, aborting", flush=True)
        sys.exit(1)
    print(f"[FRONTIER-100] Got {len(candidates)} candidates", flush=True)

    print("[FRONTIER-100] Step 2: Build profiles", flush=True)
    profiles = []
    for i, entry in enumerate(candidates):
        p = build_profile(entry, start, end)
        if p and p["contract_count"] > 0:
            profiles.append(p)
            print(f"  {i+1}/{len(candidates)} {p['name'][:40]:<40} ${p['total_prime_value']/1e6:>6.1f}M agencies={len(p['agencies'])} contracts={p['contract_count']}", flush=True)
        time.sleep(0.2)

    if len(profiles) < 10:
        print(f"ERROR: only {len(profiles)} valid profiles", flush=True)
        sys.exit(1)

    print(f"[FRONTIER-100] Step 3: Score all {len(profiles)} companies", flush=True)
    scored = []
    for p in profiles:
        p["_run_cyber_scan"] = True
        result = score_company(p, profiles)
        scored.append(result)

    print(f"[FRONTIER-100] Step 4: VP-1000 vital pulse checks", flush=True)
    PER_COMPANY_DEADLINE = 45
    for i, s in enumerate(scored):
        domain = s.get("domain") or _guess_domain(s["name"])
        if domain:
            vital, err = _run_with_deadline(run_vital_pulse, PER_COMPANY_DEADLINE, domain)
            if vital is not None:
                s = apply_vital_pulse_modifier(s, vital)
                print(f"  {i+1}/{len(scored)} VP {s['name'][:40]:<40} vs={vital['vital_score']}", flush=True)
            elif err == "timeout":
                print(f"  {i+1}/{len(scored)} VP TIMEOUT {s['name'][:40]}", flush=True)
            else:
                print(f"  {i+1}/{len(scored)} VP FAIL {s['name'][:40]}: {err}", flush=True)
        env = calculate_environment_adjustment(s.get("state_code"), s.get("naics_code"), None)
        s = apply_environment_adjustment(s, env)
        scored[i] = s
        time.sleep(0.2)

    scored.sort(key=lambda x: x["total"], reverse=True)

    day_scores = {s["name"]: s["total"] for s in scored}

    # Save history
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    else:
        history = {}
    history[today_str] = day_scores
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, separators=(",", ":"))

    # Save cache in same schema as scores_cache.json
    cache_data = {"date": today_str, "companies": []}
    for s in scored:
        vp_full = s.get("vital_pulse") or {}
        vital_pulse_min = {
            "vital_score": vp_full.get("vital_score", 0),
            "signals": vp_full.get("signals", []),
            "domain": vp_full.get("domain"),
            "alive": vp_full.get("alive") or {"alive": False, "response_time_ms": 0},
            "careers": vp_full.get("careers") or {"has_careers": False, "careers_url": None},
            "freshness": vp_full.get("freshness") or {},
            "ssl": vp_full.get("ssl") or {},
            "robots": vp_full.get("robots") or {},
        }
        cache_data["companies"].append({
            "name": s["name"],
            "total": s["total"],
            "axes": s["axes"],
            "total_value": s.get("total_value", 0),
            "total_prime_value": s.get("total_prime_value", 0),
            "total_sub_value": s.get("total_sub_value", 0),
            "agency_count": s.get("agency_count", 0),
            "sub_contractor_count": s.get("sub_contractor_count", 0),
            "prime_contractor_count": s.get("prime_contractor_count", 0),
            "contract_count": s.get("contract_count", 0),
            "years_active": s.get("years_active", 0),
            "yearly_values": s.get("yearly_values", {}),
            "yoy_change": s.get("yoy_change", 0),
            "domain": s.get("domain"),
            "state_code": s.get("state_code"),
            "naics_code": s.get("naics_code"),
            "prime_contractors": s.get("prime_contractors", []),
            "env_adjustment": s.get("env_adjustment", 0),
            "vp_adjustment": s.get("vp_adjustment", 0),
            "vital_modifier": s.get("vital_modifier", 1.0),
            "vital_pulse": vital_pulse_min,
            "digital_score_detail": s.get("digital_score_detail"),
        })

    with open(CACHE_FILE, "w") as f:
        json.dump(cache_data, f, separators=(",", ":"))

    print(f"[FRONTIER-100] Saved {len(scored)} companies to {CACHE_FILE}", flush=True)


if __name__ == "__main__":
    main()
