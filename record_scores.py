#!/usr/bin/env python3
"""Daily score recorder for SUPPLY-1000 (standalone, no Streamlit dependency)."""
import json
import os
import sys
import time
from datetime import date

import requests

# Import scoring logic from data_logic to ensure consistency
from data_logic import score_all_top_companies, BASE_URL

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "scores_history.json")


def main():
    today_str = date.today().isoformat()
    print(f"[SUPPLY-1000] Recording scores for {today_str}")

    # Load history
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    else:
        history = {}

    # Skip if already recorded today
    if today_str in history:
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
                        {"start_date": "2024-01-01", "end_date": "2024-12-31"}
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
        sys.exit(0)

    # Score top companies
    print("  Scoring top companies...")
    scored = score_all_top_companies(year=2024, limit=50)

    if not scored or len(scored) < 5:
        print(f"ERROR: Only {len(scored) if scored else 0} companies scored, skipping save")
        sys.exit(1)

    day_scores = {}
    for s in scored:
        day_scores[s["name"]] = s["total"]
        print(f"    {s['name']}: {s['total']}")

    history[today_str] = day_scores

    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, separators=(",", ":"))

    print(f"[SUPPLY-1000] Saved {len(day_scores)} scores for {today_str}")


if __name__ == "__main__":
    main()
