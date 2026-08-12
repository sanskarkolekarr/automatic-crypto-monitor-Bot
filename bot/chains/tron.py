"""
TRON chain checker – USDT/USDC (TRC-20 official contracts only).

Fixes vs original:
- Checks resp.status_code and raises a meaningful error before .json().
- Surfaces rate-limit (429) distinctly.
- Handles missing/malformed 'value' field safely.
"""

import time

import requests

from ..prices import get_token_prices

TRONGRID = "https://api.trongrid.io"

# Accepted TRC-20 contracts (lowercase keys → token name)
ALLOWED_TOKENS = {
    "tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t": "USDT",
    "tekxitehnzsmse2xqrbj4w32run966rdz8": "USDC",
}

_REQUEST_TIMEOUT = 20


def check_tron(address: str, minutes: int = 15) -> dict:
    """Return chain result dict for a TRON address."""
    now_ms = int(time.time() * 1000)
    min_ms = now_ms - minutes * 60 * 1000

    received: dict = {}

    try:
        resp = requests.get(
            f"{TRONGRID}/v1/accounts/{address}/transactions/trc20",
            params={"only_to": "true", "min_timestamp": min_ms, "limit": 200},
            timeout=_REQUEST_TIMEOUT,
        )
        # Raise descriptive error before trying to parse the body
        if resp.status_code == 429:
            raise RuntimeError("TronGrid rate-limited (429); try again shortly")
        if resp.status_code != 200:
            raise RuntimeError(f"TronGrid HTTP {resp.status_code}")

        for tx in resp.json().get("data", []):
            # Double-check recipient address (API filter can be approximate)
            if str(tx.get("to", "")).lower() != address.lower():
                continue
            # Double-check timestamp (min_timestamp param respected by API but verify)
            if tx.get("block_timestamp", 0) < min_ms:
                continue

            info = tx.get("token_info") or {}
            contract = str(info.get("address", "")).lower()
            sym = ALLOWED_TOKENS.get(contract)
            if not sym:
                continue

            decimals = int(info.get("decimals", 6))
            raw_value = tx.get("value", "0")
            try:
                value = int(raw_value) / (10 ** decimals)
            except (ValueError, TypeError):
                continue  # malformed value — skip silently

            received[sym] = received.get(sym, 0) + value

    except RuntimeError:
        raise  # re-raise our own descriptive errors
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    if not received:
        return {"chain": "tron", "address": address, "total_usd": 0.0, "receipts": []}

    prices = get_token_prices(list(received.keys()))

    receipts = []
    total = 0.0
    for sym, amount in received.items():
        price = prices.get(sym, 1.0)  # USDT/USDC → always $1
        usd = amount * price
        total += usd
        receipts.append({"token": sym, "amount": amount, "usd": usd, "price": price})

    return {"chain": "tron", "address": address, "total_usd": total, "receipts": receipts}
