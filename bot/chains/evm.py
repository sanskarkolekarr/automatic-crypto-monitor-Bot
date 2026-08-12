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

# Supported tokens per chain
TOKENS = {
    "bsc": [
        {"name": "USDT", "address": "0x55d398326f99059fF775485246999027B3197955", "decimals": 18},
        {"name": "USDC", "address": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", "decimals": 18},
        {"name": "DAI", "address": "0x1AF3F329e8BE154074D8769D1FFa4eE058B1Dbc3", "decimals": 18},
        {"name": "ETH", "address": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8", "decimals": 18},
    ],
    "eth": [
        {"name": "USDT", "address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
        {"name": "USDC", "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
        {"name": "DAI", "address": "0x6B175474E89094C44Da98b954EedeAC495271d0F", "decimals": 18},
        {"name": "WBTC", "address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "decimals": 8},
    ],
}


def _call_rpc(rpcs, method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = None
    for rpc in rpcs:
        try:
            resp = requests.post(rpc, json=payload, timeout=15)
            data = resp.json()
            if data.get("error"):
                last = data["error"]
                continue
            return data.get("result")
        except Exception as exc:
            last = exc
            continue
    raise RuntimeError(f"RPC error on {method}: {last}")


def _current_block_info(rpcs):
    num = int(_call_rpc(rpcs, "eth_blockNumber", []), 16)
    info = _call_rpc(rpcs, "eth_getBlockByNumber", [hex(num), False])
    ts = int(info["timestamp"], 16)
    return num, ts


def _find_block(rpcs, low, high, target_ts):
    while low <= high:
        mid = (low + high) // 2
        info = _call_rpc(rpcs, "eth_getBlockByNumber", [hex(mid), False])
        ts = int(info["timestamp"], 16)
        if ts >= target_ts:
            high = mid - 1
        else:
            low = mid + 1
    return max(low, 1)


def check_evm(chain, address, minutes=15):
    rpcs = BSC_RPCS if chain == "bsc" else ETH_RPCS
    num, ts = _current_block_info(rpcs)
    target_ts = ts - minutes * 60
    # Estimate lower bound based on average block times (~3s for BSC, ~12s for ETH)
    avg_block_time = 3 if chain == "bsc" else 12
    estimated_blocks_back = int((minutes * 60 / avg_block_time) * 2.5) + 100
    low = max(1, num - estimated_blocks_back)
    from_block = _find_block(rpcs, low, num, target_ts)

    addr = address.lower()
    pad = "0x" + "0" * 24 + addr[2:]

    received = {}

    for tok in TOKENS[chain]:
        logs = _call_rpc(
            rpcs,
            "eth_getLogs",
            [{
                "fromBlock": hex(from_block),
                "toBlock": hex(num),
                "address": tok["address"],
                "topics": [TRANSFER_TOPIC, None, pad],
            }],
        )
        if not logs:
            continue
        raw = sum(int(lg.get("data", "0x0"), 16) for lg in logs)
        if raw:
            received[tok["name"]] = received.get(tok["name"], 0) + raw / 10 ** tok["decimals"]

    token_names = [t["name"] for t in TOKENS[chain]]
    prices = get_token_prices(token_names)

    receipts = []
    total = 0.0
    for name, amount in received.items():
        price = prices.get(name, 1.0)
        usd = amount * price
        total += usd
        receipts.append({"token": name, "amount": amount, "usd": usd, "price": price})

    return {"chain": chain, "address": addr, "total_usd": total, "receipts": receipts}

