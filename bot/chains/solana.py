import logging
import time
import requests
from ..prices import get_token_prices

logger = logging.getLogger(__name__)

SOLANA_RPCS = [
    "https://solana-rpc.publicnode.com",
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana",
]

# SPL Token Mints
SPL_TOKENS = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": {"name": "USDT", "decimals": 6},
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {"name": "USDC", "decimals": 6},
}


def _call_rpc(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_err = None
    for rpc in SOLANA_RPCS:
        try:
            resp = requests.post(rpc, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    last_err = data["error"]
                    continue
                return data.get("result")
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Solana RPC error on {method}: {last_err}")


def check_solana(address, minutes=15):
    now_ts = int(time.time())
    min_ts = now_ts - minutes * 60

    addr = address.strip()

    # Step 1: Get recent signatures
    signatures_info = _call_rpc("getSignaturesForAddress", [addr, {"limit": 20}])
    if not signatures_info:
        return {"chain": "solana", "address": addr, "total_usd": 0.0, "receipts": []}

    target_sigs = []
    for info in signatures_info:
        if info.get("err") is not None:
            continue
        bt = info.get("blockTime")
        if bt and bt < min_ts:
            continue
        target_sigs.append(info.get("signature"))

    received = {}  # token_name -> float amount

    # Step 2: Parse each transaction
    for sig in target_sigs[:10]:  # Limit to max 10 transactions to keep response fast
        try:
            tx = _call_rpc(
                "getParsedTransaction",
                [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            )
            if not tx:
                continue

            meta = tx.get("meta") or {}
            transaction = tx.get("transaction") or {}
            message = transaction.get("message") or {}
            account_keys = message.get("accountKeys") or []

            # Find index of target address in account keys
            addr_idx = None
            for idx, key_obj in enumerate(account_keys):
                pubkey = key_obj.get("pubkey") if isinstance(key_obj, dict) else str(key_obj)
                if pubkey == addr:
                    addr_idx = idx
                    break

            # 2a. Check native SOL balance change
            if addr_idx is not None:
                pre_bals = meta.get("preBalances") or []
                post_bals = meta.get("postBalances") or []
                if addr_idx < len(pre_bals) and addr_idx < len(post_bals):
                    diff_lamports = post_bals[addr_idx] - pre_bals[addr_idx]
                    if diff_lamports > 0:
                        sol_amount = diff_lamports / 1e9
                        received["SOL"] = received.get("SOL", 0.0) + sol_amount

            # 2b. Check SPL Token balance changes
            pre_token = meta.get("preTokenBalances") or []
            post_token = meta.get("postTokenBalances") or []

            token_diffs = {}  # mint -> diff float amount

            for tb in post_token:
                owner = tb.get("owner")
                mint = tb.get("mint")
                if owner == addr and mint in SPL_TOKENS:
                    ui_amount = float(
                        tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0
                    )
                    token_diffs[mint] = token_diffs.get(mint, 0.0) + ui_amount

            for tb in pre_token:
                owner = tb.get("owner")
                mint = tb.get("mint")
                if owner == addr and mint in SPL_TOKENS:
                    ui_amount = float(
                        tb.get("uiTokenAmount", {}).get("uiAmount") or 0.0
                    )
                    token_diffs[mint] = token_diffs.get(mint, 0.0) - ui_amount

            for mint, diff in token_diffs.items():
                if diff > 0:
                    tname = SPL_TOKENS[mint]["name"]
                    received[tname] = received.get(tname, 0.0) + diff

        except Exception as exc:
            logger.warning("Error parsing Solana transaction %s: %s", sig, exc)
            continue

    if not received:
        return {"chain": "solana", "address": addr, "total_usd": 0.0, "receipts": []}

    prices = get_token_prices(list(received.keys()))

    receipts = []
    total_usd = 0.0
    for tok_name, amount in received.items():
        price = prices.get(tok_name, 1.0)
        usd = amount * price
        total_usd += usd
        receipts.append({"token": tok_name, "amount": amount, "usd": usd, "price": price})

    return {
        "chain": "solana",
        "address": addr,
        "total_usd": total_usd,
        "receipts": receipts,
    }
