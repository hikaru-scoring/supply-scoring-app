# entity_resolver.py
"""Simple entity resolution for company names from USAspending data.
No LLM needed -- use fuzzy string matching (difflib).
"""

import re
from difflib import SequenceMatcher


# Common corporate suffixes to strip for matching
_SUFFIXES = [
    r"\bCORPORATION\b",
    r"\bCORP\.?\b",
    r"\bINCORPORATED\b",
    r"\bINC\.?\b",
    r"\bLIMITED\b",
    r"\bLTD\.?\b",
    r"\bCOMPANY\b",
    r"\bCO\.?\b",
    r"\bLLC\b",
    r"\bLLP\b",
    r"\bLP\b",
    r"\bL\.?L\.?C\.?\b",
    r"\bL\.?L\.?P\.?\b",
    r"\bP\.?C\.?\b",
    r"\bPLC\b",
    r"\bGROUP\b",
    r"\bHOLDINGS\b",
    r"\bENTERPRISES\b",
    r"\bSERVICES\b",
    r"\bSOLUTIONS\b",
    r"\bINTERNATIONAL\b",
    r"\bINTL\b",
    r"\bTECHNOLOGIES\b",
    r"\bTECH\b",
]

_SUFFIX_PATTERN = re.compile("|".join(_SUFFIXES), re.IGNORECASE)


def normalize_company_name(name: str) -> str:
    """Normalize company name for matching.

    - Uppercase
    - Remove common suffixes: LLC, INC, CORP, CORPORATION, LTD, CO, COMPANY, LP, LLP
    - Remove punctuation
    - Strip extra whitespace
    """
    if not name:
        return ""
    text = name.upper()
    # Remove suffixes
    text = _SUFFIX_PATTERN.sub("", text)
    # Remove punctuation
    text = re.sub(r"[^A-Z0-9\s]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def are_same_entity(name1: str, name2: str, threshold: float = 0.85) -> bool:
    """Check if two company names refer to the same entity."""
    if not name1 or not name2:
        return False
    n1 = normalize_company_name(name1)
    n2 = normalize_company_name(name2)
    if not n1 or not n2:
        return False
    # Exact match after normalization
    if n1 == n2:
        return True
    # One is a substring of the other
    if n1 in n2 or n2 in n1:
        return True
    # Fuzzy match
    ratio = SequenceMatcher(None, n1, n2).ratio()
    return ratio >= threshold


def resolve_entities(company_names: list) -> dict:
    """Given a list of company names, group them into unique entities.

    Returns dict: {canonical_name: [list of variant names]}
    Uses normalized names + fuzzy matching.
    """
    if not company_names:
        return {}

    # Map normalized -> list of original names
    groups = {}  # canonical -> [variants]
    canonical_map = {}  # normalized -> canonical original name

    for name in company_names:
        if not name:
            continue
        norm = normalize_company_name(name)
        if not norm:
            continue

        matched_canonical = None
        for existing_norm, existing_canonical in canonical_map.items():
            if existing_norm == norm:
                matched_canonical = existing_canonical
                break
            if existing_norm in norm or norm in existing_norm:
                matched_canonical = existing_canonical
                break
            ratio = SequenceMatcher(None, norm, existing_norm).ratio()
            if ratio >= 0.85:
                matched_canonical = existing_canonical
                break

        if matched_canonical:
            if name not in groups[matched_canonical]:
                groups[matched_canonical].append(name)
        else:
            # New entity: use the original name as canonical
            canonical_map[norm] = name
            groups[name] = [name]

    return groups


def assign_company_ids(records: list) -> list:
    """Assign unique Company_ID to each record based on entity resolution.

    Returns records with added 'company_id' and 'canonical_name' fields.
    """
    if not records:
        return records

    # Collect all company names (both prime and sub)
    all_names = set()
    for rec in records:
        prime = rec.get("Prime Recipient Name", "")
        sub = rec.get("Sub-Awardee Name", "")
        if prime:
            all_names.add(prime)
        if sub:
            all_names.add(sub)

    all_names = list(all_names)
    entity_groups = resolve_entities(all_names)

    # Build reverse map: variant -> (canonical, id)
    variant_to_canonical = {}
    for idx, (canonical, variants) in enumerate(entity_groups.items()):
        cid = f"CMP-{idx + 1:05d}"
        for v in variants:
            variant_to_canonical[v] = (canonical, cid)

    # Annotate each record
    enriched = []
    for rec in records:
        r = dict(rec)
        prime = rec.get("Prime Recipient Name", "")
        sub = rec.get("Sub-Awardee Name", "")

        if prime in variant_to_canonical:
            r["prime_canonical"] = variant_to_canonical[prime][0]
            r["prime_company_id"] = variant_to_canonical[prime][1]
        else:
            r["prime_canonical"] = prime
            r["prime_company_id"] = "CMP-UNKNOWN"

        if sub in variant_to_canonical:
            r["sub_canonical"] = variant_to_canonical[sub][0]
            r["sub_company_id"] = variant_to_canonical[sub][1]
        else:
            r["sub_canonical"] = sub
            r["sub_company_id"] = "CMP-UNKNOWN"

        enriched.append(r)

    return enriched
