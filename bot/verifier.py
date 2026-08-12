"""
Payment verification orchestrator.

Fixes vs original:
- verify_wallets now counts chains that errored and surfaces a warning
  in the return value so callers can distinguish "nothing received" from
  "all chains failed" — prevents a silent false-negative being shown as
  a clean "NO MATCHING PAYMENT FOUND" to users.
- is_amount_matched logic unchanged (abs-tolerance based).
"""

from concurrent.futures import ThreadPoolExecutor

from .chains import evm, ltc, solana, tron
from .config import TOLERANCE_USD


def is_amount_matched(received_total: float, target_amount: float, tolerance: float = TOLERANCE_USD) -> bool:
    """Return True if |received - target| <= tolerance and received > 0."""
    if received_total <= 0 or target_amount <= 0:
        return False
    return abs(received_total - target_amount) <= tolerance


def verify_wallets(wallets: list, amount_usd: float, minutes: int = 15) -> tuple:
    """Check all wallets for incoming payments within the time window.

    Returns:
        (total_usd_received, list_of_per_chain_results, is_confirmed, all_chains_errored)

    `all_chains_errored` is True when every chain check returned an error dict,
    meaning the result should be treated as a technical failure, not a genuine
    "no payment found".
    """

    def _check(rec: dict) -> dict:
        chain = rec["chain"].lower()
        address = rec["address"]
        try:
            if chain in ("bsc", "eth"):
                return evm.check_evm(chain, address, minutes)
            if chain == "tron":
                return tron.check_tron(address, minutes)
            if chain == "ltc":
                return ltc.check_ltc(address, minutes)
            if chain == "solana":
                return solana.check_solana(address, minutes)
            return {"chain": chain, "error": "unsupported chain"}
        except Exception as exc:
            return {"chain": chain, "address": address, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_check, wallets))

    total = sum(r.get("total_usd", 0.0) for r in results)
    confirmed = is_amount_matched(total, amount_usd)

    # Detect all-error scenario so the bot can warn the user
    error_count = sum(1 for r in results if "error" in r)
    all_chains_errored = len(results) > 0 and error_count == len(results)

    return total, results, confirmed, all_chains_errored
