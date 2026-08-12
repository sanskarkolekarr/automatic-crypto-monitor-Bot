import logging
import time
import requests

logger = logging.getLogger(__name__)

COINGECKO_MAP = {
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "WBTC": "wrapped-bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "TRX": "tron",
    "LTC": "litecoin",
    "SOL": "solana",
}

# Pre-populate stablecoins
_PRICE_CACHE = {
    "USDT": (1.0, float("inf")),
    "USDC": (1.0, float("inf")),
    "DAI": (1.0, float("inf")),
}

CACHE_TTL = 60  # seconds


def get_token_prices(symbols=None):
    """Fetch live USD prices for token symbols with a 60s memory cache."""
    now = time.time()
    targets = [s.upper() for s in (symbols or COINGECKO_MAP.keys())]

    to_fetch = []
    for sym in targets:
        if sym in COINGECKO_MAP:
            _, cached_time = _PRICE_CACHE.get(sym, (None, 0))
            if (now - cached_time) > CACHE_TTL:
                to_fetch.append(sym)

    if to_fetch:
        cg_ids = list(set(COINGECKO_MAP[sym] for sym in to_fetch if sym in COINGECKO_MAP))
        if cg_ids:
            try:
                url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(cg_ids)}&vs_currencies=usd"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    for sym in to_fetch:
                        cid = COINGECKO_MAP.get(sym)
                        if cid and cid in data and "usd" in data[cid]:
                            _PRICE_CACHE[sym] = (float(data[cid]["usd"]), now)
            except Exception as exc:
                logger.warning("CoinGecko price lookup failed (%s); using cached/fallback prices", exc)

    res = {}
    for sym in targets:
        price, _ = _PRICE_CACHE.get(sym, (1.0 if sym in ("USDT", "USDC", "DAI") else None, 0))
        if price is not None:
            res[sym] = price
    return res


def get_price(symbol):
    prices = get_token_prices([symbol])
    return prices.get(symbol.upper(), 1.0)
