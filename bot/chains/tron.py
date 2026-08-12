import time

import requests

from ..prices import get_token_prices

TRONGRID = "https://api.trongrid.io"

# Accepted TRC-20 contracts (lowercase keys)
ALLOWED_TOKENS = {
    "tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t": "USDT",
    "tekxitehnzsmse2xqrbj4w32run966rdz8": "USDC",
}


def check_tron(address, minutes=15):
    now_ms = int(time.time() * 1000)
    min_ms = now_ms - minutes * 60 * 1000

    received = {}

    try:
        resp = requests.get(
            f"{TRONGRID}/v1/accounts/{address}/transactions/trc20",
            params={"only_to": "true", "min_timestamp": min_ms, "limit": 200},
            timeout=20,
        )
        for tx in resp.json().get("data", []):
            if str(tx.get("to", "")).lower() != address.lower():
                continue
            if tx.get("block_timestamp", 0) < min_ms:
                continue
            info = tx.get("token_info") or {}
            contract = str(info.get("address", "")).lower()
            sym = ALLOWED_TOKENS.get(contract)
            if not sym:
                continue
            decimals = int(info.get("decimals", 6))
            value = int(tx.get("value", 0)) / (10 ** decimals)
            received[sym] = received.get(sym, 0) + value
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc

    if not received:
        return {"chain": "tron", "address": address, "total_usd": 0.0, "receipts": []}

    prices = get_token_prices(list(received.keys()))

    receipts = []
    total = 0.0
    for sym, amount in received.items():
        price = prices.get(sym, 1.0)
        usd = amount * price
        total += usd
        receipts.append({"token": sym, "amount": amount, "usd": usd, "price": price})

    return {"chain": "tron", "address": address, "total_usd": total, "receipts": receipts}

