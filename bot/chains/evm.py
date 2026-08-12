"""
EVM chain checker for BSC and Ethereum.

Fixes vs original:
- _parse_log_value moved to module level (out of the for-loop).
- Block estimate buffer tightened from 2.5x to 1.3x to cut RPC calls.
- eth_getLogs range capped at 2000 blocks max to avoid RPC range errors.
- Explicit status-code check on RPC responses before .json().
- Price unavailability raises for volatile tokens; stablecoins keep $1 default.
"""

import requests

from ..prices import get_token_prices

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

BSC_RPCS = [
    "https://bsc.publicnode.com",
    "https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3",
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.binance.org",
    "https://rpc-bsc.48.club",
]

ETH_RPCS = [
    "https://cloudflare-eth.com",
    "https://eth.llamarpc.com",
    "https://ethereum.publicnode.com",
    "https://rpc.ankr.com/eth",
]

# Average block times (seconds) and max look-back block caps per chain
_CHAIN_PARAMS = {
    "bsc": {"avg_block": 3,  "max_blocks": 2000},
    "eth": {"avg_block": 12, "max_blocks": 2000},
}

# Supported tokens per chain
TOKENS = {
    "bsc": [
        {"name": "USDT", "address": "0x55d398326f99059fF775485246999027B3197955", "decimals": 18},
        {"name": "USDC", "address": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "decimals": 18},
        {"name": "DAI",  "address": "0x1AF3F329e8BE154074D8769D1FFa4eE058B1Dbc3", "decimals": 18},
        {"name": "ETH",  "address": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8", "decimals": 18},
    ],
    "eth": [
        {"name": "USDT", "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
        {"name": "USDC", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
        {"name": "DAI",  "address": "0x6B175474E89094C44Da98b954EedeAC495271d0F", "decimals": 18},
        {"name": "WBTC", "address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "decimals": 8},
    ],
}

_STABLECOINS = {"USDT", "USDC", "DAI"}


# ---------------------------------------------------------------------------
# Module-level log parser (was incorrectly defined inside a loop before)
# ---------------------------------------------------------------------------

def _parse_log_value(lg: dict) -> int:
    """Parse raw hex Transfer event data into an integer token amount."""
    raw = lg.get("data", "0x0") or "0x0"
    # Some RPCs return bare "0x" with no digits — treat as 0
    return int(raw, 16) if len(raw) > 2 else 0


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

def _call_rpc(rpcs: list, method: str, params: list):
    """Try each RPC in order; raise RuntimeError if all fail."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    for rpc in rpcs:
        try:
            resp = requests.post(rpc, json=payload, timeout=15)
            if resp.status_code != 200:
                last = f"HTTP {resp.status_code}"
                continue
            data = resp.json()
            if data.get("error"):
                last = data["error"]
                continue
            return data.get("result")
        except Exception as exc:
            last = exc
            continue
    raise RuntimeError(f"RPC error on {method}: {last}")


def _current_block_info(rpcs: list) -> tuple:
    """Return (block_number, block_timestamp) for the latest block."""
    num = int(_call_rpc(rpcs, "eth_blockNumber", []), 16)
    info = _call_rpc(rpcs, "eth_getBlockByNumber", [hex(num), False])
    ts = int(info["timestamp"], 16)
    return num, ts


def _find_block(rpcs: list, low: int, high: int, target_ts: int) -> int:
    """Binary-search for the first block whose timestamp >= target_ts."""
    while low <= high:
        mid = (low + high) // 2
        info = _call_rpc(rpcs, "eth_getBlockByNumber", [hex(mid), False])
        ts = int(info["timestamp"], 16)
        if ts >= target_ts:
            high = mid - 1
        else:
            low = mid + 1
    return max(low, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_evm(chain: str, address: str, minutes: int = 15) -> dict:
    """Check *address* on *chain* for incoming token transfers in the last *minutes*."""
    rpcs = BSC_RPCS if chain == "bsc" else ETH_RPCS
    params = _CHAIN_PARAMS[chain]

    num, ts = _current_block_info(rpcs)
    target_ts = ts - minutes * 60

    # Estimate look-back window with a 30% buffer (was 250% — massively over-shooting).
    estimated_blocks = int((minutes * 60 / params["avg_block"]) * 1.3) + 30
    # Hard-cap to avoid eth_getLogs range rejection by public RPCs
    estimated_blocks = min(estimated_blocks, params["max_blocks"])
    low = max(1, num - estimated_blocks)

    # Binary search to find the precise starting block
    from_block = _find_block(rpcs, low, num, target_ts)

    addr = address.lower()
    pad = "0x" + "0" * 24 + addr[2:]

    received: dict = {}

    for tok in TOKENS[chain]:
        logs = _call_rpc(
            rpcs,
            "eth_getLogs",
            [{
                "fromBlock": hex(from_block),
                "toBlock":   hex(num),
                "address":   tok["address"],
                "topics":    [TRANSFER_TOPIC, None, pad],
            }],
        )
        if not logs:
            continue

        raw = sum(_parse_log_value(lg) for lg in logs)
        if raw:
            received[tok["name"]] = received.get(tok["name"], 0) + raw / 10 ** tok["decimals"]

    token_names = [t["name"] for t in TOKENS[chain]]
    prices = get_token_prices(token_names)

    receipts = []
    total = 0.0
    for name, amount in received.items():
        price = prices.get(name)
        if price is None:
            if name in _STABLECOINS:
                price = 1.0
            else:
                raise RuntimeError(f"{name} price unavailable (CoinGecko down and no cache)")
        usd = amount * price
        total += usd
        receipts.append({"token": name, "amount": amount, "usd": usd, "price": price})

    return {"chain": chain, "address": addr, "total_usd": total, "receipts": receipts}
