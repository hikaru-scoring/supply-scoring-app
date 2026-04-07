"""
SUPPLY-1000 Backtest Engine v2 (Bulk approach)
===============================================
Proves that SUPPLY-1000 scores predict government contractor outcomes.

Key optimization: Instead of querying each company individually,
fetch Top N recipients for each year in bulk (few API calls),
then match companies locally.

Usage:
  python backtest.py --scoring-year 2018 --limit 500
  python backtest.py --scoring-year 2015 --limit 500
"""

import argparse
import json
import os
import re
import sys
import time
import functools
from datetime import datetime

import requests

# Force unbuffered output
print = functools.partial(print, flush=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "https://api.usaspending.gov/api/v2"

LOOKBACK_YEARS = 4  # years before scoring year for continuity
API_DELAY = 0.4
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "backtest_results")

_COMPANY_SUFFIXES = re.compile(
    r'\b(CORPORATION|CORP|INCORPORATED|INC|LLC|LLP|L\.?P\.?|PTE|LTD|CO|'
    r'COMPANY|GROUP|HOLDINGS|SERVICES|TECHNOLOGIES|SOLUTIONS|ENTERPRISES|'
    r'INTERNATIONAL|INTL)\b\.?',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    n = name.upper().strip()
    if n.startswith("THE "):
        n = n[4:]
    n = _COMPANY_SUFFIXES.sub("", n)
    n = re.sub(r'[^A-Z0-9 ]', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _clamp(value: float, lo: float = 0, hi: float = 200) -> int:
    return int(min(max(value, lo), hi))


def _percentile_rank(value: float, all_values: list) -> float:
    if not all_values:
        return 0.5
    below = sum(1 for v in all_values if v < value)
    equal = sum(1 for v in all_values if v == value)
    return (below + 0.5 * equal) / len(all_values)


def _safe_post(url: str, payload: dict, retries: int = 3, delay: float = 2.0):
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=90)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = delay * (2 ** attempt)
                print(f"  Rate limited, waiting {wait:.0f}s...")
                time.sleep(wait)
                continue
            print(f"  API error {r.status_code}")
        except requests.RequestException as e:
            if attempt < retries:
                print(f"  Request error, retrying ({attempt+1}/{retries})...")
                time.sleep(delay)
                continue
            print(f"  Request failed: {e}")
    return None


# ---------------------------------------------------------------------------
# Bulk fetch: Top recipients for a year (paginated)
# ---------------------------------------------------------------------------

def fetch_top_recipients_bulk(year: int, limit: int = 1000) -> dict:
    """Fetch top recipients for a fiscal year. Returns {normalized_name: {name, amount}}.

    Paginates through results to get up to `limit` entries.
    """
    all_results = []
    page = 1
    per_page = 100

    while len(all_results) < limit:
        payload = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],
                "time_period": [
                    {"start_date": f"{year-1}-10-01", "end_date": f"{year}-09-30"}
                ],
            },
            "category": "recipient",
            "limit": per_page,
            "page": page,
        }
        data = _safe_post(f"{BASE_URL}/search/spending_by_category/recipient/", payload)
        if not data:
            break
        results = data.get("results", [])
        if not results:
            break
        all_results.extend(results)
        page += 1
        time.sleep(API_DELAY)

    # Build lookup dict by normalized name
    lookup = {}
    for entry in all_results:
        name = entry.get("name") or ""
        if not name or name.upper() == "REDACTED DUE TO PII":
            continue
        base = _normalize(name)
        if not base:
            continue
        amount = float(entry.get("amount") or 0)
        if base in lookup:
            lookup[base]["amount"] += amount
        else:
            lookup[base] = {"name": name, "amount": amount}

    return lookup


# ---------------------------------------------------------------------------
# Bulk fetch: Prime award details for multiple companies in one year
# ---------------------------------------------------------------------------

def fetch_prime_details_bulk(names: list, year: int) -> dict:
    """For a list of company names, fetch agency and contract count info.

    Returns {normalized_name: {agencies: [...], contract_count: N}}
    Uses individual API calls but with shorter timeout.
    """
    results = {}
    for i, name in enumerate(names):
        if (i + 1) % 50 == 0:
            print(f"    Prime details: {i+1}/{len(names)}")

        payload = {
            "filters": {
                "award_type_codes": ["A", "B", "C", "D"],
                "time_period": [
                    {"start_date": f"{year-1}-10-01", "end_date": f"{year}-09-30"}
                ],
                "recipient_search_text": [name],
            },
            "fields": [
                "Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
            ],
            "limit": 30,
            "page": 1,
            "subawards": False,
            "order": "desc",
            "sort": "Award Amount",
        }
        data = _safe_post(f"{BASE_URL}/search/spending_by_award/", payload)
        agencies = set()
        count = 0
        if data:
            for award in data.get("results", []):
                rname = (award.get("Recipient Name") or "").upper()
                if name.upper()[:15] in rname:
                    count += 1
                    agency = award.get("Awarding Agency")
                    if agency:
                        agencies.add(agency)

        base = _normalize(name)
        results[base] = {"agencies": list(agencies), "contract_count": max(count, 1)}
        time.sleep(API_DELAY)

    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_backtest(scoring_year: int, limit: int = 500, tracking_years: int = 3):
    """Run the full backtest pipeline."""

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    checkpoint_path = os.path.join(OUTPUT_DIR, f"checkpoint_{scoring_year}.json")
    start_time = datetime.now()

    print(f"SUPPLY-1000 Backtest Engine v2")
    print(f"Scoring Year: FY{scoring_year}")
    print(f"Companies: Top {limit}")
    print(f"Tracking: {tracking_years} years")
    print(f"Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # Check for checkpoint
    if os.path.exists(checkpoint_path):
        print(f"\nFound checkpoint, loading...")
        with open(checkpoint_path, "r") as f:
            checkpoint = json.load(f)
        if checkpoint.get("step") == "analysis":
            scored = checkpoint["scored"]
            print(f"  Resuming from analysis step ({len(scored)} companies)")
            analysis = analyze_results(scored, scoring_year)
            save_results(scored, analysis, scoring_year, limit, tracking_years, start_time)
            return

    # =======================================================================
    # PHASE 1: Bulk fetch spending data for all relevant years
    # =======================================================================
    # Years: lookback + scoring year + tracking years
    all_years = list(range(scoring_year - LOOKBACK_YEARS, scoring_year + tracking_years + 1))
    # Cap at 2025
    all_years = [y for y in all_years if y <= 2025]

    print(f"\n[Phase 1] Bulk fetching top recipients for {len(all_years)} years ({all_years[0]}-{all_years[-1]})...")

    # For each year, fetch top recipients (need enough to cover our companies)
    # Fetch more than limit to account for dedup and to find our companies in future years
    fetch_limit = min(limit + 200, 1500)

    yearly_data = {}  # {year: {normalized_name: {name, amount}}}
    for year in all_years:
        print(f"  FY{year}...", end=" ")
        yearly_data[year] = fetch_top_recipients_bulk(year, fetch_limit)
        print(f"{len(yearly_data[year])} recipients")
        time.sleep(API_DELAY)

    # =======================================================================
    # PHASE 2: Build scored company list from scoring year
    # =======================================================================
    print(f"\n[Phase 2] Building company list from FY{scoring_year}...")

    scoring_data = yearly_data[scoring_year]
    # Sort by amount and take top N
    sorted_companies = sorted(scoring_data.items(), key=lambda x: x[1]["amount"], reverse=True)
    sorted_companies = sorted_companies[:limit]

    print(f"  {len(sorted_companies)} companies selected")

    # Build profiles using bulk data
    analysis_years = list(range(scoring_year - LOOKBACK_YEARS, scoring_year + 1))
    analysis_years = [y for y in analysis_years if y in yearly_data]

    profiles = []
    for base_name, info in sorted_companies:
        # Get yearly values from bulk data
        yearly_values = {}
        for y in analysis_years:
            if base_name in yearly_data.get(y, {}):
                yearly_values[y] = yearly_data[y][base_name]["amount"]

        # Ensure scoring year value is included
        if scoring_year not in yearly_values:
            yearly_values[scoring_year] = info["amount"]

        years_active = [y for y, v in yearly_values.items() if v > 0]

        profiles.append({
            "name": info["name"],
            "_normalized": base_name,
            "total_prime_value": info["amount"],
            "total_sub_value": 0,
            "agencies": [],  # Will fill in Phase 2b
            "prime_contractors": [],
            "sub_contractors": [],
            "yearly_values": yearly_values,
            "contract_count": 1,  # Will fill in Phase 2b
            "years_active": years_active,
        })

    # =======================================================================
    # PHASE 2b: Fetch prime award details (agencies, contract count)
    # This is the slow part - one API call per company
    # =======================================================================
    print(f"\n[Phase 2b] Fetching award details for {len(profiles)} companies...")

    names_to_fetch = [p["name"] for p in profiles]
    details = fetch_prime_details_bulk(names_to_fetch, scoring_year)

    for p in profiles:
        base = p["_normalized"]
        if base in details:
            p["agencies"] = details[base]["agencies"]
            p["contract_count"] = details[base]["contract_count"]

    print(f"  Done")

    # =======================================================================
    # PHASE 3: Score all companies (4-axis)
    # =======================================================================
    print(f"\n[Phase 3] Scoring {len(profiles)} companies...")

    scored = score_all(profiles, scoring_year)

    # =======================================================================
    # PHASE 4: Track outcomes using bulk data (no extra API calls!)
    # =======================================================================
    print(f"\n[Phase 4] Tracking outcomes...")

    tracking_end = min(scoring_year + tracking_years, 2025)
    check_years = [y for y in range(scoring_year + 1, tracking_end + 1) if y in yearly_data]

    for company in scored:
        base = company["_normalized"]
        base_value = company["total_value"]

        # Check future spending from bulk data
        future_yearly = {}
        for y in check_years:
            if base in yearly_data.get(y, {}):
                future_yearly[y] = yearly_data[y][base]["amount"]
            else:
                future_yearly[y] = 0

        company["future_yearly"] = future_yearly

        # Outcome A: Disappeared from top recipients in ALL tracking years
        future_values = [future_yearly.get(y, 0) for y in check_years]
        company["disappeared"] = all(v == 0 for v in future_values) if future_values else False

        # Outcome B: Severe decline (>50% drop)
        if base_value > 0 and future_values:
            latest_future = 0
            for y in reversed(check_years):
                if future_yearly.get(y, 0) > 0:
                    latest_future = future_yearly[y]
                    break
            if latest_future == 0:
                company["decline_pct"] = -1.0
            else:
                company["decline_pct"] = (latest_future - base_value) / base_value
        else:
            company["decline_pct"] = 0

        company["severe_decline"] = company["decline_pct"] < -0.5
        company["excluded"] = False  # SAM.gov check skipped for now

    disappeared = sum(1 for c in scored if c["disappeared"])
    declined = sum(1 for c in scored if c["severe_decline"])
    print(f"  Disappeared from top list: {disappeared}")
    print(f"  Severe decline (>50%): {declined}")

    # Save checkpoint before analysis
    with open(checkpoint_path, "w") as f:
        json.dump({"step": "analysis", "scored": scored}, f)

    # =======================================================================
    # PHASE 5: Analysis
    # =======================================================================
    analysis = analyze_results(scored, scoring_year)

    # Save final results
    save_results(scored, analysis, scoring_year, limit, tracking_years, start_time)

    # Cleanup checkpoint
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)


def score_all(profiles: list, scoring_year: int) -> list:
    """Score all companies on 4 axes, scaled to 0-1000."""
    analysis_years = list(range(scoring_year - LOOKBACK_YEARS, scoring_year + 1))

    all_total_values = [p["total_prime_value"] + p["total_sub_value"] for p in profiles]
    all_contract_counts = [p["contract_count"] for p in profiles]
    all_agency_counts = [len(p["agencies"]) for p in profiles]
    all_sub_counts = [len(p["sub_contractors"]) for p in profiles]
    all_years_active = [len(p["years_active"]) for p in profiles]

    scored = []
    for p in profiles:
        total_value = p["total_prime_value"] + p["total_sub_value"]

        # Axis 1: Contract Volume
        value_pct = _percentile_rank(total_value, all_total_values)
        count_pct = _percentile_rank(p["contract_count"], all_contract_counts)
        yearly = p["yearly_values"]
        sorted_year_keys = sorted(k for k in yearly.keys() if isinstance(k, int))
        if len(sorted_year_keys) >= 2:
            latest = yearly[sorted_year_keys[-1]]
            prev = yearly[sorted_year_keys[-2]]
            yoy = (latest - prev) / prev if prev > 0 else (1.0 if latest > 0 else 0)
        else:
            yoy = 0
        growth_bonus = min(max(yoy * 40, -20), 40)
        contract_volume = _clamp(value_pct * 120 + count_pct * 40 + growth_bonus)

        # Axis 2: Diversification
        agency_count = len(p["agencies"])
        agency_pct = _percentile_rank(agency_count, all_agency_counts)
        prime_pct = 0.5
        concentration_penalty = 30 if agency_count == 1 and total_value > 0 else 0
        diversification = _clamp(agency_pct * 120 + prime_pct * 80 - concentration_penalty)

        # Axis 3: Contract Continuity
        years_count = len(p["years_active"])
        years_pct = _percentile_rank(years_count, all_years_active)
        active_sorted = sorted(p["years_active"])
        consecutive = sum(
            1 for i in range(1, len(active_sorted))
            if active_sorted[i] == active_sorted[i-1] + 1
        )
        max_possible = max(len(analysis_years) - 1, 1)
        continuity_ratio = consecutive / max_possible
        contract_continuity = _clamp(years_pct * 120 + continuity_ratio * 80)

        # Axis 4: Network Position
        is_prime = p["total_prime_value"] > 0
        sub_count = len(p["sub_contractors"])
        has_subs = sub_count > 0
        position_base = 80 if is_prime else 40
        sub_pct = _percentile_rank(sub_count, all_sub_counts)
        sub_score = sub_pct * 80
        hub_bonus = min(sub_count * 5, 40) if is_prime and has_subs else 0
        network_position = _clamp(position_base + sub_score + hub_bonus)

        # Total: scale 4-axis to 0-1000
        four_axis = contract_volume + diversification + contract_continuity + network_position
        total_score = min(round(four_axis * 1000 / 800), 1000)

        scored.append({
            "name": p["name"],
            "_normalized": p["_normalized"],
            "score": total_score,
            "axes": {
                "Contract Volume": contract_volume,
                "Diversification": diversification,
                "Contract Continuity": contract_continuity,
                "Network Position": network_position,
            },
            "total_value": total_value,
            "contract_count": p["contract_count"],
            "agency_count": agency_count,
            "sub_count": sub_count,
            "years_active": len(p["years_active"]),
            "yoy_change": yoy,
            "yearly_values": {str(k): v for k, v in p["yearly_values"].items()},
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    print(f"  Top 5: {[(s['name'][:30], s['score']) for s in scored[:5]]}")
    print(f"  Bottom 5: {[(s['name'][:30], s['score']) for s in scored[-5:]]}")
    return scored


def analyze_results(scored: list, scoring_year: int) -> dict:
    """Compute correlation between scores and outcomes."""
    print(f"\n[Phase 5] Analyzing results...")

    total = len(scored)
    if total == 0:
        return {}

    # Split into quartiles
    sorted_by_score = sorted(scored, key=lambda x: x["score"])
    q_size = total // 4
    quartiles = {
        "Q1_lowest": sorted_by_score[:q_size],
        "Q2": sorted_by_score[q_size:2*q_size],
        "Q3": sorted_by_score[2*q_size:3*q_size],
        "Q4_highest": sorted_by_score[3*q_size:],
    }

    analysis = {
        "scoring_year": scoring_year,
        "total_companies": total,
        "overall": {
            "disappeared": sum(1 for c in scored if c.get("disappeared")),
            "severe_decline": sum(1 for c in scored if c.get("severe_decline")),
            "avg_score": round(sum(c["score"] for c in scored) / total, 1),
        },
        "by_quartile": {},
    }

    for q_name, q_companies in quartiles.items():
        n = len(q_companies)
        if n == 0:
            continue
        scores = [c["score"] for c in q_companies]
        disappeared = sum(1 for c in q_companies if c.get("disappeared"))
        declined = sum(1 for c in q_companies if c.get("severe_decline"))
        any_neg = len([c for c in q_companies
                      if c.get("disappeared") or c.get("severe_decline")])

        analysis["by_quartile"][q_name] = {
            "count": n,
            "score_range": f"{min(scores)}-{max(scores)}",
            "avg_score": round(sum(scores) / n, 1),
            "disappeared": disappeared,
            "disappeared_pct": round(disappeared / n * 100, 1),
            "severe_decline": declined,
            "severe_decline_pct": round(declined / n * 100, 1),
            "any_negative": any_neg,
            "any_negative_pct": round(any_neg / n * 100, 1),
        }

    # Threshold analysis
    thresholds = [300, 400, 500, 600]
    analysis["by_threshold"] = {}
    for threshold in thresholds:
        below = [c for c in scored if c["score"] < threshold]
        above = [c for c in scored if c["score"] >= threshold]
        if below and above:
            below_neg = len([c for c in below
                           if c.get("disappeared") or c.get("severe_decline")])
            above_neg = len([c for c in above
                           if c.get("disappeared") or c.get("severe_decline")])
            analysis["by_threshold"][f"below_{threshold}"] = {
                "count": len(below),
                "negative_pct": round(below_neg / len(below) * 100, 1),
            }
            analysis["by_threshold"][f"above_{threshold}"] = {
                "count": len(above),
                "negative_pct": round(above_neg / len(above) * 100, 1),
            }

    # Print summary
    print(f"\n{'='*60}")
    print(f"  SUPPLY-1000 BACKTEST RESULTS - FY{scoring_year}")
    print(f"{'='*60}")
    print(f"  Companies scored: {total}")
    print(f"  Average score: {analysis['overall']['avg_score']}")
    print(f"  Disappeared: {analysis['overall']['disappeared']} ({analysis['overall']['disappeared']/total*100:.1f}%)")
    print(f"  Severe decline: {analysis['overall']['severe_decline']} ({analysis['overall']['severe_decline']/total*100:.1f}%)")
    print()
    print(f"  {'Quartile':<14} {'Score Range':<14} {'Disappeared':>12} {'Decline>50%':>12} {'Any Neg':>10}")
    print(f"  {'-'*62}")
    for q_name, q_data in analysis["by_quartile"].items():
        print(f"  {q_name:<14} {q_data['score_range']:<14} {q_data['disappeared_pct']:>11.1f}% {q_data['severe_decline_pct']:>11.1f}% {q_data['any_negative_pct']:>9.1f}%")
    print(f"{'='*60}")

    if analysis["by_threshold"]:
        print(f"\n  Score Threshold Analysis:")
        for key, val in analysis["by_threshold"].items():
            print(f"    {key}: {val['count']} companies, {val['negative_pct']}% negative outcome")

    return analysis


def save_results(scored, analysis, scoring_year, limit, tracking_years, start_time):
    """Save results to JSON."""
    output_path = os.path.join(OUTPUT_DIR, f"backtest_{scoring_year}.json")
    with open(output_path, "w") as f:
        json.dump({
            "meta": {
                "scoring_year": scoring_year,
                "limit": limit,
                "tracking_years": tracking_years,
                "run_date": datetime.now().isoformat(),
                "duration_minutes": round((datetime.now() - start_time).total_seconds() / 60, 1),
            },
            "analysis": analysis,
            "companies": scored,
        }, f, indent=2)

    print(f"\nResults saved to {output_path}")
    print(f"Duration: {(datetime.now() - start_time).total_seconds() / 60:.1f} minutes")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SUPPLY-1000 Backtest Engine v2")
    parser.add_argument("--scoring-year", type=int, default=2018)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--tracking-years", type=int, default=3)
    args = parser.parse_args()

    run_backtest(args.scoring_year, args.limit, args.tracking_years)


if __name__ == "__main__":
    main()
