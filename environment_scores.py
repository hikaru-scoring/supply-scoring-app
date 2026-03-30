"""Environment score fetchers for Layer 1 integration.
Pulls scores from GOV-1000, REALESTATE-1000, PORT-1000, FRS-1000
to adjust SUPPLY-1000 base scores.
"""

import requests

# State FIPS to abbreviation mapping (all 50 states + DC)
STATE_ABBR_TO_NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# Major port by state (for PORT-1000 lookup)
STATE_TO_PORT = {
    "CA": "Port of Los Angeles",
    "TX": "Port of Houston",
    "NY": "Port of New York and New Jersey",
    "NJ": "Port of New York and New Jersey",
    "GA": "Port of Savannah",
    "WA": "Port of Seattle",
    "FL": "Port of Miami",
    "LA": "Port of New Orleans",
    "VA": "Port of Virginia",
    "SC": "Port of Charleston",
    "MD": "Port of Baltimore",
    "PA": "Port of Philadelphia",
    "IL": "Port of Chicago",
    "OH": "Port of Cleveland",
    "MA": "Port of Boston",
    "OR": "Port of Portland",
    "AL": "Port of Mobile",
    "MS": "Port of Gulfport",
    "HI": "Port of Honolulu",
}

# Manufacturing/import-dependent NAICS codes (2-digit)
SUPPLY_CHAIN_NAICS = {"31", "32", "33", "42", "44", "45", "48", "49"}


def _clamp(val, lo=0, hi=1000):
    return max(lo, min(hi, int(val)))


def get_gov_adjustment(state_code):
    """Get GOV-1000 state fiscal health adjustment.
    Returns: int (-20 to +20)

    Since we cannot call the GOV-1000 Streamlit app directly,
    we use a tier-based approach from known fiscal health rankings.
    """
    # Tier-based approach using known fiscal health rankings
    # Based on GOV-1000 actual scores (snapshot)
    strong_states = {"WY", "UT", "ID", "NE", "SD", "ND", "IA", "MT", "IN", "WI"}  # 700+
    weak_states = {"IL", "NJ", "CT", "MA", "NY", "CA", "RI", "WV", "MS", "NM"}  # below 500

    if not state_code:
        return 0
    state_upper = state_code.upper()
    if state_upper in strong_states:
        return 20
    elif state_upper in weak_states:
        return -20
    return 0


def get_realestate_adjustment(state_code):
    """Get REALESTATE-1000 state market health adjustment.
    Returns: int (-15 to +15)
    """
    # Based on REALESTATE-1000 actual scores (snapshot)
    strong_states = {"IN", "WI", "OH", "IA", "MI", "MN", "NE", "KS", "SD", "ND"}  # 700+
    weak_states = {"CA", "HI", "WA", "OR", "NV", "CO", "MA", "NY", "NJ", "CT"}  # below 500

    if not state_code:
        return 0
    state_upper = state_code.upper()
    if state_upper in strong_states:
        return 15
    elif state_upper in weak_states:
        return -15
    return 0


def get_port_adjustment(state_code, naics_code=None):
    """Get PORT-1000 nearest port risk adjustment.
    Only applies to manufacturing/import-dependent industries.
    Returns: int (-40 to +20)
    """
    if not state_code:
        return 0

    # Only apply port adjustment to supply-chain-dependent industries
    if naics_code:
        naics_2digit = str(naics_code)[:2]
        if naics_2digit not in SUPPLY_CHAIN_NAICS:
            return 0  # Not supply chain dependent

    state_upper = state_code.upper()
    port_name = STATE_TO_PORT.get(state_upper)
    if not port_name:
        return 0  # Landlocked or no major port

    # Based on PORT-1000 actual scores (snapshot)
    # Singapore-class ports score 900+, major US ports 600-800
    strong_ports = {"CA", "TX", "GA", "WA", "VA", "NY", "NJ"}  # Major hub states
    weak_ports = {"MS", "AL", "OH"}

    if state_upper in strong_ports:
        return 20
    elif state_upper in weak_ports:
        return -20
    return 0


def get_frs_adjustment(prime_contractor_name):
    """Get FRS-1000 adjustment based on prime contractor financial health.
    Only applies if the prime contractor is a publicly traded company.
    Returns: int (-10 to +10)
    """
    if not prime_contractor_name:
        return 0

    # Known SGX/public companies and their approximate FRS-1000 tier
    # This is a simplified lookup. In production, would call FRS-1000 API
    strong_companies = {
        "DBS": True, "OCBC": True, "SINGTEL": True,
    }

    # Major US defense/tech primes (publicly traded, generally strong)
    major_primes = {
        "LOCKHEED MARTIN", "BOEING", "RAYTHEON", "NORTHROP GRUMMAN",
        "GENERAL DYNAMICS", "L3HARRIS", "BAE SYSTEMS", "LEIDOS",
        "BOOZ ALLEN HAMILTON", "CACI", "SAIC", "HUNTINGTON INGALLS",
        "TEXTRON", "GENERAL ELECTRIC", "HONEYWELL",
    }

    name_upper = prime_contractor_name.upper()
    for prime in major_primes:
        if prime in name_upper:
            return 10  # Large, stable prime contractor

    return 0  # Unknown or private company


def calculate_environment_adjustment(state_code, naics_code=None, prime_contractor_name=None):
    """Calculate total environment adjustment from all Layer 1 sources.
    Returns dict with individual adjustments and total.
    """
    gov = get_gov_adjustment(state_code)
    realestate = get_realestate_adjustment(state_code)
    port = get_port_adjustment(state_code, naics_code)
    frs = get_frs_adjustment(prime_contractor_name)

    total = gov + realestate + port + frs

    return {
        "gov_adjustment": gov,
        "realestate_adjustment": realestate,
        "port_adjustment": port,
        "frs_adjustment": frs,
        "total_adjustment": total,
        "state_code": state_code,
        "details": {
            "GOV-1000": f"State fiscal health: {'+' if gov >= 0 else ''}{gov}",
            "REALESTATE-1000": f"Real estate market: {'+' if realestate >= 0 else ''}{realestate}",
            "PORT-1000": f"Port risk: {'+' if port >= 0 else ''}{port}",
            "FRS-1000": f"Prime contractor health: {'+' if frs >= 0 else ''}{frs}",
        }
    }
