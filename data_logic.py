# data_logic.py
"""USASpending.gov API data fetching and SUPPLY-1000 scoring logic."""
import time

try:
    import streamlit as st
except ImportError:
    import types as _types
    st = _types.ModuleType("streamlit")
    st.cache_data = lambda **kwargs: (lambda fn: fn)
    st.secrets = {}

import requests

AXES_LABELS = [
    "Contract Volume",
    "Diversification",
    "Contract Continuity",
    "Network Position",
    "Growth Momentum",
]

BASE_URL = "https://api.usaspending.gov/api/v2"

# Years to analyze for continuity and growth
ANALYSIS_YEARS = list(range(2020, 2026))
CURRENT_YEAR = 2025
PREV_YEAR = 2024


def _clamp(value: float, lo: float = 0, hi: float = 200) -> int:
    return int(min(max(value, lo), hi))


def _safe_post(url: str, payload: dict, retries: int = 2, delay: float = 1.0):
    """POST with retries and error handling."""
    for attempt in range(retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(delay * (attempt + 1))
                continue
        except requests.RequestException:
            if attempt < retries:
                time.sleep(delay)
                continue
    return None


# ---------------------------------------------------------------------------
# API: Prime awards search
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def search_prime_awards(agency_name=None, recipient_name=None, year=2024, limit=100):
    """Search prime contract awards from USAspending.gov."""
    filters = {
        "award_type_codes": ["A", "B", "C", "D"],
        "time_period": [
            {"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
        ],
    }
    if agency_name:
        filters["agencies"] = [
            {"type": "awarding", "tier": "toptier", "name": agency_name}
        ]
    if recipient_name:
        filters["recipient_search_text"] = [recipient_name]

    payload = {
        "filters": filters,
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Awarding Agency", "Start Date", "End Date", "Description",
        ],
        "limit": limit,
        "page": 1,
        "subawards": False,
        "order": "desc",
        "sort": "Award Amount",
    }
    data = _safe_post(f"{BASE_URL}/search/spending_by_award/", payload)
    if data:
        return data.get("results", [])
    return []


# ---------------------------------------------------------------------------
# API: Sub-awards search
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def search_sub_awards(agency_name=None, prime_recipient=None, year=2024, limit=100):
    """Search sub-contract awards from USAspending.gov."""
    filters = {
        "award_type_codes": ["A", "B", "C", "D"],
        "time_period": [
            {"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
        ],
    }
    if agency_name:
        filters["agencies"] = [
            {"type": "awarding", "tier": "toptier", "name": agency_name}
        ]
    if prime_recipient:
        filters["recipient_search_text"] = [prime_recipient]

    payload = {
        "filters": filters,
        "fields": [
            "Sub-Award ID", "Sub-Awardee Name", "Sub-Award Amount",
            "Prime Award ID", "Prime Recipient Name",
        ],
        "limit": limit,
        "page": 1,
        "subawards": True,
        "order": "desc",
        "sort": "Sub-Award Amount",
    }
    data = _safe_post(f"{BASE_URL}/search/spending_by_award/", payload)
    if data:
        return data.get("results", [])
    return []


# ---------------------------------------------------------------------------
# API: Top recipients by category
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_top_recipients(year=2024, limit=50):
    """Get top recipients by contract spending."""
    payload = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [
                {"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
            ],
        },
        "category": "recipient",
        "limit": limit,
        "page": 1,
    }
    data = _safe_post(f"{BASE_URL}/search/spending_by_category/recipient/", payload)
    if data:
        return data.get("results", [])
    return []


# ---------------------------------------------------------------------------
# API: Recipient autocomplete
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def autocomplete_recipient(search_text: str, limit: int = 10):
    """Autocomplete recipient names."""
    payload = {"search_text": search_text, "limit": limit}
    data = _safe_post(f"{BASE_URL}/autocomplete/recipient/", payload)
    if data:
        return data.get("results", [])
    return []


# ---------------------------------------------------------------------------
# Build company profile
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_company_profile(company_name: str) -> dict:
    """Build a company profile from USAspending data across multiple years.

    Returns dict with:
      - name, total_prime_value, total_sub_value
      - agencies (set of awarding agency names)
      - prime_contractors (set: who gives this company sub-contracts)
      - sub_contractors (set: who this company gives sub-contracts to)
      - yearly_values: {year: total_value}
      - contract_count, sub_count
    """
    profile = {
        "name": company_name,
        "total_prime_value": 0,
        "total_sub_value": 0,
        "agencies": set(),
        "prime_contractors": set(),
        "sub_contractors": set(),
        "yearly_values": {},
        "contract_count": 0,
        "sub_count": 0,
        "years_active": set(),
    }

    # Fetch prime awards for each year
    for year in ANALYSIS_YEARS:
        primes = search_prime_awards(recipient_name=company_name, year=year, limit=50)
        year_value = 0
        for award in primes:
            rname = (award.get("Recipient Name") or "").upper()
            if company_name.upper() in rname or rname in company_name.upper():
                amount = award.get("Award Amount") or 0
                if isinstance(amount, str):
                    try:
                        amount = float(amount.replace(",", ""))
                    except ValueError:
                        amount = 0
                amount = float(amount)
                profile["total_prime_value"] += amount
                year_value += amount
                profile["contract_count"] += 1
                agency = award.get("Awarding Agency")
                if agency:
                    profile["agencies"].add(agency)
                profile["years_active"].add(year)

        # Fetch sub-awards where this company is the prime
        subs = search_sub_awards(prime_recipient=company_name, year=year, limit=50)
        for sub in subs:
            prime_name = (sub.get("Prime Recipient Name") or "").upper()
            if company_name.upper() in prime_name or prime_name in company_name.upper():
                sub_name = sub.get("Sub-Awardee Name")
                if sub_name:
                    profile["sub_contractors"].add(sub_name)
                profile["years_active"].add(year)

        # Fetch sub-awards where this company is the sub
        # Search broadly and filter
        subs_as_sub = search_sub_awards(year=year, limit=100)
        for sub in subs_as_sub:
            sub_name = (sub.get("Sub-Awardee Name") or "").upper()
            if company_name.upper() in sub_name or sub_name in company_name.upper():
                amount = sub.get("Sub-Award Amount") or 0
                if isinstance(amount, str):
                    try:
                        amount = float(amount.replace(",", ""))
                    except ValueError:
                        amount = 0
                amount = float(amount)
                profile["total_sub_value"] += amount
                profile["sub_count"] += 1
                prime_name = sub.get("Prime Recipient Name")
                if prime_name:
                    profile["prime_contractors"].add(prime_name)
                profile["years_active"].add(year)

        if year_value > 0:
            profile["yearly_values"][year] = year_value

        time.sleep(0.3)  # rate limiting

    # Convert sets to lists for JSON serialization
    profile["agencies"] = list(profile["agencies"])
    profile["prime_contractors"] = list(profile["prime_contractors"])
    profile["sub_contractors"] = list(profile["sub_contractors"])
    profile["years_active"] = sorted(list(profile["years_active"]))

    return profile


# ---------------------------------------------------------------------------
# Build profiles for top recipients (batch)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_top_company_profiles(year=2024, limit=50) -> list[dict]:
    """Get profiles for the top recipients by contract value.

    This is the main entry point for Dashboard / Rankings.
    Returns a list of scored company dicts.
    """
    top = get_top_recipients(year=year, limit=limit)
    if not top:
        return []

    profiles = []
    for entry in top:
        name = entry.get("name")
        amount = entry.get("amount") or 0
        if not name or name.upper() == "REDACTED DUE TO PII":
            continue
        # Build a lightweight profile from the top-recipients data
        # plus a targeted sub-award lookup
        profile = {
            "name": name,
            "total_prime_value": float(amount),
            "total_sub_value": 0,
            "agencies": [],
            "prime_contractors": [],
            "sub_contractors": [],
            "yearly_values": {year: float(amount)},
            "contract_count": 0,
            "sub_count": 0,
            "years_active": [year],
        }

        # Quick prime award lookup for agency info and contract count
        primes = search_prime_awards(recipient_name=name, year=year, limit=20)
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
        profile["contract_count"] = max(count, 1)

        # Quick sub-award lookup
        subs = search_sub_awards(prime_recipient=name, year=year, limit=20)
        sub_names = set()
        for sub in subs:
            sub_name = sub.get("Sub-Awardee Name")
            if sub_name:
                sub_names.add(sub_name)
        profile["sub_contractors"] = list(sub_names)

        # Previous year for growth
        prev_top = get_top_recipients(year=year - 1, limit=limit)
        for pt in (prev_top or []):
            if pt.get("name") == name:
                prev_amount = pt.get("amount") or 0
                profile["yearly_values"][year - 1] = float(prev_amount)
                if year - 1 not in profile["years_active"]:
                    profile["years_active"].append(year - 1)
                break

        profiles.append(profile)
        time.sleep(0.2)

    return profiles


# ---------------------------------------------------------------------------
# Supply chain network for a company
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def get_supply_chain_network(company_name: str, year=2024) -> dict:
    """Get the supply chain network for a company.

    Returns dict with:
      - prime_contracts: list of {agency, amount, description}
      - sub_contracts_given: list of {sub_name, amount}
      - sub_contracts_received: list of {prime_name, amount}
      - connections: list of {from, to, amount, type}
    """
    network = {
        "prime_contracts": [],
        "sub_contracts_given": [],
        "sub_contracts_received": [],
        "connections": [],
    }

    # Prime contracts this company holds
    primes = search_prime_awards(recipient_name=company_name, year=year, limit=50)
    for award in primes:
        rname = (award.get("Recipient Name") or "").upper()
        if company_name.upper()[:15] in rname:
            agency = award.get("Awarding Agency") or "Unknown Agency"
            amount = float(award.get("Award Amount") or 0)
            desc = award.get("Description") or ""
            network["prime_contracts"].append({
                "agency": agency, "amount": amount, "description": desc,
            })
            network["connections"].append({
                "from": agency, "to": company_name,
                "amount": amount, "type": "prime",
            })

    # Sub-contracts this company gives out (as prime)
    subs_given = search_sub_awards(prime_recipient=company_name, year=year, limit=50)
    for sub in subs_given:
        sub_name = sub.get("Sub-Awardee Name") or "Unknown"
        amount = float(sub.get("Sub-Award Amount") or 0)
        network["sub_contracts_given"].append({
            "sub_name": sub_name, "amount": amount,
        })
        network["connections"].append({
            "from": company_name, "to": sub_name,
            "amount": amount, "type": "sub",
        })

    # Sub-contracts received (company is sub-awardee)
    subs_received = search_sub_awards(year=year, limit=100)
    for sub in subs_received:
        sub_name = (sub.get("Sub-Awardee Name") or "").upper()
        if company_name.upper()[:15] in sub_name:
            prime_name = sub.get("Prime Recipient Name") or "Unknown"
            amount = float(sub.get("Sub-Award Amount") or 0)
            network["sub_contracts_received"].append({
                "prime_name": prime_name, "amount": amount,
            })
            network["connections"].append({
                "from": prime_name, "to": company_name,
                "amount": amount, "type": "sub_received",
            })

    return network


# ---------------------------------------------------------------------------
# Scoring: percentile helper
# ---------------------------------------------------------------------------

def _percentile_rank(value: float, all_values: list[float]) -> float:
    """Return percentile rank (0.0 to 1.0) of value in all_values."""
    if not all_values:
        return 0.5
    below = sum(1 for v in all_values if v < value)
    equal = sum(1 for v in all_values if v == value)
    return (below + 0.5 * equal) / len(all_values)


# ---------------------------------------------------------------------------
# Score a single company
# ---------------------------------------------------------------------------

def score_company(profile: dict, all_profiles: list[dict]) -> dict:
    """Score a single company on 5 axes (each 0-200, total 0-1000).

    Uses percentile ranking among all_profiles for relative scoring.
    """
    name = profile["name"]

    # Collect comparison values from all profiles
    all_total_values = [
        p["total_prime_value"] + p["total_sub_value"] for p in all_profiles
    ]
    all_contract_counts = [p["contract_count"] for p in all_profiles]
    all_agency_counts = [len(p["agencies"]) for p in all_profiles]
    all_sub_counts = [len(p["sub_contractors"]) for p in all_profiles]
    all_years_active = [len(p["years_active"]) for p in all_profiles]

    this_total_value = profile["total_prime_value"] + profile["total_sub_value"]

    # -------------------------------------------------------------------
    # Axis 1: Contract Volume (0-200)
    # Total contract value + number of contracts, percentile ranked
    # -------------------------------------------------------------------
    value_pct = _percentile_rank(this_total_value, all_total_values)
    count_pct = _percentile_rank(profile["contract_count"], all_contract_counts)
    contract_volume = _clamp(value_pct * 140 + count_pct * 60)

    # -------------------------------------------------------------------
    # Axis 2: Diversification (0-200)
    # Number of agencies + number of prime contractors (if sub)
    # Over-reliance on one client = lower score
    # -------------------------------------------------------------------
    agency_count = len(profile["agencies"])
    agency_pct = _percentile_rank(agency_count, all_agency_counts)

    prime_contractor_count = len(profile["prime_contractors"])
    all_prime_counts = [len(p["prime_contractors"]) for p in all_profiles]
    prime_pct = _percentile_rank(prime_contractor_count, all_prime_counts)

    # Concentration penalty: if >80% of value from one source
    concentration_penalty = 0
    if agency_count == 1 and this_total_value > 0:
        concentration_penalty = 30

    diversification = _clamp(agency_pct * 120 + prime_pct * 80 - concentration_penalty)

    # -------------------------------------------------------------------
    # Axis 3: Contract Continuity (0-200)
    # Years active + recurring contracts
    # -------------------------------------------------------------------
    years_active = len(profile["years_active"])
    years_pct = _percentile_rank(years_active, all_years_active)

    # Recurring bonus: contracts in consecutive years
    active_years_sorted = sorted(profile["years_active"])
    consecutive = 0
    for i in range(1, len(active_years_sorted)):
        if active_years_sorted[i] == active_years_sorted[i - 1] + 1:
            consecutive += 1
    max_possible = max(len(ANALYSIS_YEARS) - 1, 1)
    continuity_ratio = consecutive / max_possible

    contract_continuity = _clamp(years_pct * 120 + continuity_ratio * 80)

    # -------------------------------------------------------------------
    # Axis 4: Network Position (0-200)
    # Prime vs sub, number of sub-contractors, hub importance
    # -------------------------------------------------------------------
    is_prime = profile["total_prime_value"] > 0
    has_subs = len(profile["sub_contractors"]) > 0

    # Base: being a prime is worth more
    position_base = 80 if is_prime else 40

    # Sub-contractor network size
    sub_count = len(profile["sub_contractors"])
    sub_pct = _percentile_rank(sub_count, all_sub_counts)
    sub_score = sub_pct * 80

    # Hub bonus: both prime and has many subs
    hub_bonus = 0
    if is_prime and has_subs:
        hub_bonus = min(sub_count * 5, 40)

    network_position = _clamp(position_base + sub_score + hub_bonus)

    # -------------------------------------------------------------------
    # Axis 5: Growth Momentum (0-200)
    # YoY change in contract value + new contracts
    # -------------------------------------------------------------------
    yearly = profile["yearly_values"]
    if len(yearly) >= 2:
        sorted_years = sorted(yearly.keys())
        latest_year = sorted_years[-1]
        prev_year = sorted_years[-2]
        latest_val = yearly[latest_year]
        prev_val = yearly[prev_year]

        if prev_val > 0:
            yoy_change = (latest_val - prev_val) / prev_val
        elif latest_val > 0:
            yoy_change = 1.0  # new entrant with value
        else:
            yoy_change = 0
    else:
        yoy_change = 0

    # Map growth to score: -50% or worse = 0, +100% or better = 160
    all_growths = []
    for p in all_profiles:
        yv = p["yearly_values"]
        if len(yv) >= 2:
            sy = sorted(yv.keys())
            pv = yv[sy[-2]]
            if pv > 0:
                all_growths.append((yv[sy[-1]] - pv) / pv)
    if all_growths:
        growth_pct = _percentile_rank(yoy_change, all_growths)
    else:
        growth_pct = 0.5

    # New contract bonus
    new_contract_bonus = min(profile["contract_count"] * 3, 40)

    growth_momentum = _clamp(growth_pct * 160 + new_contract_bonus)

    # -------------------------------------------------------------------
    # Assemble result
    # -------------------------------------------------------------------
    axes = {
        "Contract Volume": contract_volume,
        "Diversification": diversification,
        "Contract Continuity": contract_continuity,
        "Network Position": network_position,
        "Growth Momentum": growth_momentum,
    }
    total = sum(axes.values())

    return {
        "name": name,
        "axes": axes,
        "total": total,
        "total_prime_value": profile["total_prime_value"],
        "total_sub_value": profile["total_sub_value"],
        "total_value": this_total_value,
        "agency_count": agency_count,
        "sub_contractor_count": len(profile["sub_contractors"]),
        "prime_contractor_count": len(profile["prime_contractors"]),
        "contract_count": profile["contract_count"],
        "years_active": years_active,
        "yearly_values": yearly,
        "yoy_change": yoy_change,
    }


# ---------------------------------------------------------------------------
# Score all top companies (main entry for dashboard)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def score_all_top_companies(year=2024, limit=50) -> list[dict]:
    """Fetch top recipients, build profiles, score them all.

    Returns sorted list of scored company dicts (highest first).
    """
    profiles = get_top_company_profiles(year=year, limit=limit)
    if not profiles:
        return []

    scored = []
    for p in profiles:
        result = score_company(p, profiles)
        scored.append(result)

    scored.sort(key=lambda x: x["total"], reverse=True)
    return scored
