"""Environment score fetchers for Layer 1 integration.

The cross-product environment layer (GOV-1000 / REALESTATE-1000 / PORT-1000 /
FRS-1000) is on the roadmap but not yet wired to live data, so this module is
intentionally a no-op. Re-enable it only when each downstream score comes from
a live API rather than a hand-typed table.
"""


def calculate_environment_adjustment(state_code, naics_code=None, prime_contractor_name=None):
    """No-op until the Layer 1 cross-product layer is wired to live data."""
    return None
