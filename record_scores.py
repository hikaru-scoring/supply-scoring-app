#!/usr/bin/env python3
"""Daily score recorder for SUPPLY-1000 (standalone, no Streamlit dependency)."""
import json
import os
import socket
import sys
import threading
import time
from datetime import date

import requests

# Global hard cap on every blocking socket operation so a single bad domain
# cannot stall the entire daily regen.
socket.setdefaulttimeout(15)


def _run_with_deadline(fn, timeout, *args, **kwargs):
    """Run fn in a daemon thread and abandon it if it does not return in time.
    Daemon threads die with the main process so abandoned ones do not leak.
    Returns (result, error_str_or_None).
    """
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

# Import scoring logic from data_logic to ensure consistency
from data_logic import (
    score_all_top_companies, BASE_URL, _guess_domain,
    apply_vital_pulse_modifier, apply_environment_adjustment,
)
from vital_pulse import run_vital_pulse
from environment_scores import calculate_environment_adjustment

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "scores_history.json")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "scores_cache.json")


def main():
    today_str = date.today().isoformat()
    print(f"[SUPPLY-1000] Recording scores for {today_str}")

    # Load history
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    else:
        history = {}

    # Skip if already recorded today (unless --force is passed)
    force = "--force" in sys.argv
    if today_str in history and not force:
        print(f"[SUPPLY-1000] Scores already recorded for {today_str}, skipping")
        sys.exit(0)

    # Connectivity check
    print("  Checking API connectivity...")
    api_ok = False
    for attempt in range(3):
        try:
            payload = {
                "filters": {
                    "award_type_codes": ["A", "B", "C", "D"],
                    "time_period": [
                        {"start_date": "2025-01-01", "end_date": "2025-12-31"}
                    ],
                },
                "category": "recipient",
                "limit": 1,
                "page": 1,
            }
            r = requests.post(
                f"{BASE_URL}/search/spending_by_category/recipient/",
                json=payload,
                timeout=30,
            )
            if r.status_code == 200:
                api_ok = True
                results = r.json().get("results", [])
                print(f"  API reachable ({len(results)} test results)")
                break
        except Exception:
            pass
        print(f"  Retry {attempt + 1}/3 for API check...")
        time.sleep(10)

    if not api_ok:
        print("WARNING: API unreachable. Using last known scores.")
        if history:
            last_date = sorted(history.keys())[-1]
            history[today_str] = history[last_date]
            with open(HISTORY_FILE, "w") as f:
                json.dump(history, f, separators=(",", ":"))
            print(f"  Copied scores from {last_date}")
            # Also copy cache if it exists
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r") as f:
                    cache = json.load(f)
                cache["date"] = today_str
                with open(CACHE_FILE, "w") as f:
                    json.dump(cache, f, separators=(",", ":"))
        sys.exit(0)

    # Score top companies (base 5-axis scores)
    print("  Scoring top companies (base 5-axis)...")
    scored = score_all_top_companies(year=None, limit=50)

    if not scored or len(scored) < 5:
        print(f"ERROR: Only {len(scored) if scored else 0} companies scored, skipping save")
        sys.exit(1)

    # Apply VP-1000 + environment adjustment to each company.
    # Each company gets a 45s hard deadline via _run_with_deadline so one bad
    # domain (slow SSL handshake, hanging careers page, etc.) cannot stall the
    # whole daily regen. Companies that time out keep their base 5-axis score
    # and a neutral vital_modifier.
    print("  Applying VP-1000 vital pulse checks...", flush=True)
    PER_COMPANY_DEADLINE = 45

    for i, s in enumerate(scored):
        domain = s.get("domain") or _guess_domain(s["name"])
        if domain:
            vital, err = _run_with_deadline(run_vital_pulse, PER_COMPANY_DEADLINE, domain)
            if vital is not None:
                s = apply_vital_pulse_modifier(s, vital)
                print(f"    VP-1000 {s['name']}: vital_score={vital['vital_score']}, modifier={s.get('vital_modifier', 1.0)}", flush=True)
            elif err == "timeout":
                print(f"    VP-1000 TIMEOUT for {s['name']} (keeping base score)", flush=True)
            else:
                print(f"    VP-1000 FAILED for {s['name']}: {err}", flush=True)
        time.sleep(0.3)

        # Apply environment adjustment (no-op until live data wired)
        env = calculate_environment_adjustment(
            s.get("state_code"),
            s.get("naics_code"),
            s.get("prime_contractors", [None])[0] if s.get("prime_contractors") else None,
        )
        s = apply_environment_adjustment(s, env)
        scored[i] = s

    # Re-sort after VP-1000 + environment adjustments
    scored.sort(key=lambda x: x["total"], reverse=True)

    # Save final scores (with VP-1000 + environment) to history
    day_scores = {}
    for s in scored:
        day_scores[s["name"]] = s["total"]
        print(f"    {s['name']}: {s['total']}")

    history[today_str] = day_scores

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, separators=(",", ":"))

    # Save detailed cache for Dashboard/Rankings
    # This includes axes, VP-1000, environment data so the app can display
    # without recalculating
    cache_data = {
        "date": today_str,
        "companies": [],
    }
    for s in scored:
        # Save the full vital_pulse dict so the Detail view and PDF can render
        # signals, response time, and careers info without re-fetching.
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
        company_cache = {
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
        }
        cache_data["companies"].append(company_cache)

    with open(CACHE_FILE, "w") as f:
        json.dump(cache_data, f, separators=(",", ":"))

    print(f"[SUPPLY-1000] Saved {len(day_scores)} scores for {today_str}")
    print(f"[SUPPLY-1000] Cache saved to {CACHE_FILE}")


if __name__ == "__main__":
    main()
