"""
Live USD price fetcher with 60-second in-process cache.

Fixes vs original:
- Stablecoins (USDT, USDC, DAI) are seeded with price=1.0 and
  expiry=infinity so they never re-fetch from CoinGecko.
- Volatile tokens (LTC, SOL, ETH, WBTC…) use a last-known-good cache:
  if CoinGecko is unavailable, the last cached value is returned rather
  than silently falling back to $1.
- get_token_prices() returns None for a symbol that has *never* been
  fetched successfully and is not a stablecoin — callers must handle None.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

COINGECKO_MAP = {
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI":  "dai",
    "WBTC": "wrapped-bitcoin",
    "ETH":  "ethereum",
    "BNB":  "binancecoin",
    "TRX":  "tron",
    "LTC":  "litecoin",
    "SOL":  "solana",
}

_STABLECOINS = {"USDT", "USDC", "DAI"}

# Cache: symbol -> (price, fetched_at_unix)
# Stablecoins seeded with inf expiry so they never expire.
_PRICE_CACHE: dict = {
    "USDT": (1.0, float("inf")),
    "USDC": (1.0, float("inf")),
    "DAI":  (1.0, float("inf")),
}

CACHE_TTL = 60  # seconds


def get_token_prices(symbols: list | None = None) -> dict:
    """Return {symbol: price_usd} for the requested symbols.

    For symbols that have *never* been fetched and are not stablecoins,
    the returned dict will not contain that key (i.e. value is None when
    accessed via .get()).  Callers must handle None for volatile tokens.
    """
    now = time.time()
    targets = [s.upper() for s in (symbols or COINGECKO_MAP.keys())]

    to_fetch = []
    for sym in targets:
        if sym not in COINGECKO_MAP:
            continue
        cached_price, cached_time = _PRICE_CACHE.get(sym, (None, 0))
        if cached_time == float("inf"):
            continue  # stablecoin — never re-fetch
        if (now - cached_time) > CACHE_TTL:
            to_fetch.append(sym)

    if to_fetch:
        cg_ids = list({COINGECKO_MAP[s] for s in to_fetch if s in COINGECKO_MAP})
        try:
            url = (
                "https://api.coingecko.com/api/v3/simple/price"
                f"?ids={','.join(cg_ids)}&vs_currencies=usd"
            )
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                for sym in to_fetch:
                    cid = COINGECKO_MAP.get(sym)
                    if cid and cid in data and "usd" in data[cid]:
                        _PRICE_CACHE[sym] = (float(data[cid]["usd"]), now)
            else:
                logger.warning("CoinGecko returned HTTP %s; using cached prices", resp.status_code)
        except Exception as exc:
            logger.warning("CoinGecko lookup failed (%s); using last-known-good prices", exc)
            # Do NOT wipe the cache — last-known-good is better than $1 fallback

    res = {}
    for sym in targets:
        cached = _PRICE_CACHE.get(sym)
        if cached is not None:
            price, _ = cached
            res[sym] = price
        # If never cached and not a stablecoin → omit from result (caller sees None via .get())
    return res


def get_price(symbol: str) -> float | None:
    """Return the USD price for a single symbol, or None if unavailable."""
    prices = get_token_prices([symbol])
    return prices.get(symbol.upper())
