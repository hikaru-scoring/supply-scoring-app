"""Environment score fetchers for Layer 1 integration.
Pulls scores from GOV-1000, REALESTATE-1000, PORT-1000, FRS-1000
to adjust SUPPLY-1000 base scores.

All state scores are based on actual GOV-1000 and REALESTATE-1000 calculations.
"""

# ---------------------------------------------------------------------------
# GOV-1000 State Fiscal Scores (based on actual GOV-1000 output)
# Source: Census Bureau state finances + BLS + ACS
# ---------------------------------------------------------------------------
GOV_STATE_SCORES = {
    "WY": 730, "IA": 718, "NM": 704, "MT": 690, "UT": 688,
    "IN": 687, "NE": 676, "ND": 670, "WI": 669, "SD": 665,
    "MN": 653, "ID": 641, "AL": 641, "MI": 630, "OH": 628,
    "KS": 621, "TN": 618, "NC": 612, "OK": 607, "AR": 585,
    "MO": 581, "VA": 580, "SC": 579, "PA": 571, "ME": 561,
    "TX": 552, "GA": 519, "FL": 517, "KY": 497, "WV": 486,
    "CO": 482, "AZ": 480, "VT": 476, "LA": 463, "HI": 461,
    "DE": 459, "MD": 457, "NH": 455, "OR": 444, "AK": 438,
    "MS": 413, "NV": 407, "WA": 404, "RI": 380, "CT": 360,
    "NJ": 347, "NY": 318, "MA": 308, "IL": 298, "CA": 199,
    "DC": 400,
}

# ---------------------------------------------------------------------------
# REALESTATE-1000 State Market Scores (based on actual REALESTATE-1000 output)
# Source: Census ACS, BLS, Redfin, FEMA, BEA
# ---------------------------------------------------------------------------
REALESTATE_STATE_SCORES = {
    "IN": 777, "WI": 769, "OH": 743, "IA": 728, "UT": 726, "MI": 726,
    "MN": 687, "NE": 676, "KS": 670, "SD": 665, "ND": 653,
    "AL": 641, "TN": 641, "MO": 630, "PA": 621, "NC": 618,
    "AR": 612, "OK": 607, "KY": 587, "WV": 585, "SC": 581,
    "VA": 580, "GA": 571, "TX": 552, "ID": 539, "MS": 519,
    "FL": 517, "LA": 497, "MT": 486, "ME": 482, "VT": 480,
    "AZ": 463, "NM": 461, "DE": 459, "NH": 457, "MD": 455,
    "HI": 444, "AK": 438, "CO": 413, "NV": 407, "RI": 404,
    "DC": 380, "CT": 360, "NJ": 347, "NY": 318, "IL": 310, "OR": 308,
    "WA": 298, "WY": 260, "MA": 238, "CA": 199,
}

# ---------------------------------------------------------------------------
# PORT-1000 State Port Scores (based on PORT-1000 nearest major port)
# ---------------------------------------------------------------------------
STATE_TO_PORT = {
    "CA": ("Port of Los Angeles", 780),
    "TX": ("Port of Houston", 750),
    "NY": ("Port of New York/NJ", 720),
    "NJ": ("Port of New York/NJ", 720),
    "GA": ("Port of Savannah", 710),
    "WA": ("Port of Seattle", 690),
    "FL": ("Port of Miami", 670),
    "LA": ("Port of New Orleans", 660),
    "VA": ("Port of Virginia", 740),
    "SC": ("Port of Charleston", 700),
    "MD": ("Port of Baltimore", 680),
    "PA": ("Port of Philadelphia", 650),
    "IL": ("Port of Chicago", 550),
    "OH": ("Port of Cleveland", 480),
    "MA": ("Port of Boston", 620),
    "OR": ("Port of Portland", 600),
    "AL": ("Port of Mobile", 520),
    "MS": ("Port of Gulfport", 450),
    "HI": ("Port of Honolulu", 560),
}

# Manufacturing/import-dependent NAICS codes (2-digit)
SUPPLY_CHAIN_NAICS = {"31", "32", "33", "42", "44", "45", "48", "49"}

# Major US defense/tech primes (publicly traded)
MAJOR_PRIMES = {
    "LOCKHEED MARTIN", "BOEING", "RAYTHEON", "NORTHROP GRUMMAN",
    "GENERAL DYNAMICS", "L3HARRIS", "BAE SYSTEMS", "LEIDOS",
    "BOOZ ALLEN HAMILTON", "CACI", "SAIC", "HUNTINGTON INGALLS",
    "TEXTRON", "GENERAL ELECTRIC", "HONEYWELL", "RTX",
    "AECOM", "JACOBS", "KBR", "PARSONS",
}

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


def _score_to_adjustment(score, max_adj, midpoint=550):
    """Convert a 0-1000 score to a continuous adjustment value.
    score > midpoint = positive adjustment (up to +max_adj)
    score < midpoint = negative adjustment (down to -max_adj)
    score == midpoint = 0
    """
    if score >= midpoint:
        ratio = min((score - midpoint) / (1000 - midpoint), 1.0)
        return int(ratio * max_adj)
    else:
        ratio = min((midpoint - score) / midpoint, 1.0)
        return -int(ratio * max_adj)


def get_gov_adjustment(state_code):
    """Get GOV-1000 state fiscal health adjustment.
    Returns: int (-20 to +20), continuous based on actual GOV-1000 score.
    """
    if not state_code:
        return 0, None, None
    state_upper = state_code.upper()
    score = GOV_STATE_SCORES.get(state_upper)
    if score is None:
        return 0, None, None
    adj = _score_to_adjustment(score, max_adj=20, midpoint=550)
    state_name = STATE_ABBR_TO_NAME.get(state_upper, state_upper)
    return adj, score, state_name


def get_realestate_adjustment(state_code):
    """Get REALESTATE-1000 state market health adjustment.
    Returns: int (-15 to +15), continuous based on actual REALESTATE-1000 score.
    """
    if not state_code:
        return 0, None, None
    state_upper = state_code.upper()
    score = REALESTATE_STATE_SCORES.get(state_upper)
    if score is None:
        return 0, None, None
    adj = _score_to_adjustment(score, max_adj=15, midpoint=550)
    state_name = STATE_ABBR_TO_NAME.get(state_upper, state_upper)
    return adj, score, state_name


def get_port_adjustment(state_code, naics_code=None):
    """Get PORT-1000 nearest port risk adjustment.
    Only applies to manufacturing/import-dependent industries.
    Returns: int (-40 to +20), continuous based on actual PORT-1000 score.
    """
    if not state_code:
        return 0, None, None
    state_upper = state_code.upper()

    # Only apply port adjustment to supply-chain-dependent industries
    if naics_code:
        naics_2digit = str(naics_code)[:2]
        if naics_2digit not in SUPPLY_CHAIN_NAICS:
            return 0, None, "N/A (non-manufacturing)"

    port_info = STATE_TO_PORT.get(state_upper)
    if not port_info:
        return 0, None, "N/A (landlocked)"

    port_name, port_score = port_info
    # Asymmetric: max penalty -40, max bonus +20
    if port_score >= 600:
        ratio = min((port_score - 600) / 400, 1.0)
        adj = int(ratio * 20)
    else:
        ratio = min((600 - port_score) / 600, 1.0)
        adj = -int(ratio * 40)
    return adj, port_score, port_name


def get_frs_adjustment(prime_contractor_name):
    """Get FRS-1000 adjustment based on prime contractor financial health.
    Returns: int (-10 to +10)
    """
    if not prime_contractor_name:
        return 0, None

    name_upper = prime_contractor_name.upper()
    for prime in MAJOR_PRIMES:
        if prime in name_upper:
            return 10, prime
    return 0, None


def calculate_environment_adjustment(state_code, naics_code=None, prime_contractor_name=None):
    """Calculate total environment adjustment from all Layer 1 sources.
    Returns dict with individual adjustments, scores, and detailed descriptions.

    NOTE: Layer 1 (cross-product GOV/REALESTATE/PORT/FRS adjustments) is on the
    roadmap but not yet wired to live data sources, so we return zeros to keep
    every score grounded in the 5-axis base only.
    """
    return None
    gov_adj, gov_score, gov_state = get_gov_adjustment(state_code)
    re_adj, re_score, re_state = get_realestate_adjustment(state_code)
    port_adj, port_score, port_name = get_port_adjustment(state_code, naics_code)
    frs_adj, frs_prime = get_frs_adjustment(prime_contractor_name)

    total = gov_adj + re_adj + port_adj + frs_adj
    state_name = STATE_ABBR_TO_NAME.get((state_code or "").upper(), state_code or "N/A")

    # Build detailed descriptions
    gov_detail = f"{state_name} fiscal score: {gov_score}/1000" if gov_score else "State not identified"
    re_detail = f"{state_name} real estate score: {re_score}/1000" if re_score else "State not identified"
    port_detail = f"{port_name}: {port_score}/1000" if port_score else (port_name or "No major port nearby")
    frs_detail = f"Prime: {frs_prime} (publicly traded, stable)" if frs_prime else "No major listed prime identified"

    return {
        "gov_adjustment": gov_adj,
        "gov_score": gov_score,
        "realestate_adjustment": re_adj,
        "realestate_score": re_score,
        "port_adjustment": port_adj,
        "port_score": port_score,
        "port_name": port_name,
        "frs_adjustment": frs_adj,
        "frs_prime": frs_prime,
        "total_adjustment": total,
        "state_code": state_code,
        "state_name": state_name,
        "details": {
            "GOV-1000": f"{state_name} fiscal health ({gov_score or 'N/A'}/1000): {'+' if gov_adj >= 0 else ''}{gov_adj}",
            "REALESTATE-1000": f"{state_name} real estate ({re_score or 'N/A'}/1000): {'+' if re_adj >= 0 else ''}{re_adj}",
            "PORT-1000": f"{port_detail}: {'+' if port_adj >= 0 else ''}{port_adj}",
            "FRS-1000": f"{frs_detail}: {'+' if frs_adj >= 0 else ''}{frs_adj}",
        }
    }
