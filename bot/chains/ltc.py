"""
Litecoin (LTC) chain checker.

Primary:  litecoinspace.org  (mempool-style REST, keyless)
Fallback: Blockchair          (keyless, generous free tier)

Only confirmed transactions (block_time set) are counted; mempool
(unconfirmed) transactions are intentionally excluded to prevent spoofing.
"""

import logging
import time

import requests

from ..prices import get_token_prices

logger = logging.getLogger(__name__)

MEMPOOL_LTC_API = "https://litecoinspace.org/api"
BLOCKCHAIR_LTC_API = "https://api.blockchair.com/litecoin/dashboards/address"

_REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_litecoinspace(addr: str, min_ts: int) -> int:
    """Return total satoshis received by *addr* since *min_ts* via litecoinspace.org.

    Raises RuntimeError on any HTTP or parsing problem.
    """
    url = f"{MEMPOOL_LTC_API}/address/{addr}/txs"
    resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"litecoinspace HTTP {resp.status_code}")

    sats = 0
    for tx in resp.json():
        status = tx.get("status") or {}
        # Skip unconfirmed (mempool) transactions – they can be spoofed or double-spent.
        if not status.get("confirmed"):
            continue
        block_time = status.get("block_time") or 0
        if block_time < min_ts:
            continue
        for vout in tx.get("vout") or []:
            if (vout.get("scriptpubkey_address") or "").lower() == addr.lower():
                sats += int(vout.get("value") or 0)
    return sats


def _fetch_blockchair(addr: str, min_ts: int) -> int:
    """Return total satoshis received by *addr* since *min_ts* via Blockchair.

    Raises RuntimeError on any HTTP or parsing problem.
    """
    url = f"{BLOCKCHAIR_LTC_API}/{addr}"
    # Ask for transaction outputs in the response
    params = {"transaction_details": True, "limit": "100,0"}
    resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"Blockchair HTTP {resp.status_code}")

    data = resp.json().get("data") or {}
    addr_data = data.get(addr) or {}
    outputs = addr_data.get("outputs") or []

    sats = 0
    for out in outputs:
        # Blockchair timestamps: "time" field is ISO string; "block_id" > 0 means confirmed
        if not out.get("block_id"):
            continue  # unconfirmed
        # Parse time — Blockchair uses "YYYY-MM-DD HH:MM:SS"
        tx_time_str = out.get("time") or ""
        try:
            import datetime
            tx_ts = int(
                datetime.datetime.strptime(tx_time_str, "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=datetime.timezone.utc)
                .timestamp()
            )
        except (ValueError, TypeError):
            continue
        if tx_ts < min_ts:
            continue
        if (out.get("recipient") or "").lower() == addr.lower():
            sats += int(out.get("value") or 0)
    return sats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_ltc(address: str, minutes: int = 15) -> dict:
    """Return chain result dict for a Litecoin address."""
    now_ts = int(time.time())
    min_ts = now_ts - minutes * 60
    addr = address.strip()

    sats = 0
    error_msg = None

    # Attempt 1 — litecoinspace.org
    try:
        sats = _fetch_litecoinspace(addr, min_ts)
    except Exception as exc:
        logger.warning("LTC litecoinspace failed (%s); trying Blockchair", exc)
        # Attempt 2 — Blockchair
        try:
            sats = _fetch_blockchair(addr, min_ts)
        except Exception as exc2:
            logger.error("LTC Blockchair fallback also failed: %s", exc2)
            error_msg = f"All LTC APIs failed: {exc2}"

    if error_msg:
        return {"chain": "ltc", "address": addr, "error": error_msg}

    ltc_amount = sats / 1e8

    if ltc_amount <= 0:
        return {"chain": "ltc", "address": addr, "total_usd": 0.0, "receipts": []}

    prices = get_token_prices(["LTC"])
    price = prices.get("LTC")
    if price is None:
        # CoinGecko unavailable and no cached value — raise so caller shows error
        raise RuntimeError("LTC price unavailable (CoinGecko down and no cache)")

    usd = ltc_amount * price
    return {
        "chain": "ltc",
        "address": addr,
        "total_usd": usd,
        "receipts": [
            {
                "token": "LTC",
                "amount": ltc_amount,
                "usd": usd,
                "price": price,
            }
        ],
    }
