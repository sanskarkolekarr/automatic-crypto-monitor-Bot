from concurrent.futures import ThreadPoolExecutor

from .chains import evm, tron
from .config import TOLERANCE_USD


def is_amount_matched(received_total, target_amount, tolerance=TOLERANCE_USD):
    """Check if received amount matches target amount within ±tolerance ($3-$4 up/down)."""
    if received_total <= 0 or target_amount <= 0:
        return False
    return abs(received_total - target_amount) <= tolerance


def verify_wallets(wallets, amount_usd, minutes=15):
    """Check all of a user's wallets for incoming payments within the window.

    Returns (total_usd_received, list_of_per_chain_results, is_confirmed).
    """

    def _check(rec):
        chain = rec["chain"].lower()
        address = rec["address"]
        try:
            if chain in ("bsc", "eth"):
                return evm.check_evm(chain, address, minutes)
            if chain == "tron":
                return tron.check_tron(address, minutes)
            return {"chain": chain, "error": "unsupported chain"}
        except Exception as exc:
            return {"chain": chain, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_check, wallets))

    total = sum(r.get("total_usd", 0) for r in results)
    confirmed = is_amount_matched(total, amount_usd)
    return total, results, confirmed

