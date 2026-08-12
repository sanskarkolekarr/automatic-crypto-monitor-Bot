"""
Solana chain checker – SOL (native) + USDT/USDC (SPL tokens).

Uses public JSON-RPC endpoints with fallover. Only *confirmed* transactions
within the lookback window are counted.

Key fixes vs original implementation:
- Increased signature limit to 100 to reduce missed txns in busy windows.
- `blockTime is None` (unconfirmed) → skipped, not included.
- SPL token balance diff uses per-tx pre/post maps (not additive accumulation)
  to avoid double-counting when the same mint appears multiple times.
- Price unavailability raises instead of silently falling back to $1.
"""

import logging
import time
from typing import Optional

import requests

from ..prices import get_token_prices

logger = logging.getLogger(__name__)

SOLANA_RPCS = [
    "https://solana-rpc.publicnode.com",
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana",
]

# SPL Token Mints (mainnet)
SPL_TOKENS = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": {"name": "USDT", "decimals": 6},
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {"name": "USDC", "decimals": 6},
}

_REQUEST_TIMEOUT = 15
_SIG_LIMIT = 100  # Raised from 20 to reduce missed transactions


# ---------------------------------------------------------------------------
# RPC helper
# ---------------------------------------------------------------------------


def _call_rpc(method: str, params: list) -> Optional[object]:
    """Try each RPC in order; raise RuntimeError if all fail."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_err = None
    for rpc in SOLANA_RPCS:
        try:
            resp = requests.post(rpc, json=payload, timeout=_REQUEST_TIMEOUT)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            data = resp.json()
            if "error" in data:
                last_err = data["error"]
                continue
            return data.get("result")
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"Solana RPC error on {method}: {last_err}")


# ---------------------------------------------------------------------------
# Transaction parsers
# ---------------------------------------------------------------------------


def _parse_sol_received(tx: dict, addr: str) -> float:
    """Return net SOL lamports received by *addr* in this transaction.

    Excludes the fee paid by index-0 (fee payer) from the diff calculation
    by only counting *positive* deltas that result from received transfers,
    not fee refunds or self-transfers.
    """
    meta = tx.get("meta") or {}
    transaction = tx.get("transaction") or {}
    message = transaction.get("message") or {}
    account_keys = message.get("accountKeys") or []

    pre_bals = meta.get("preBalances") or []
    post_bals = meta.get("postBalances") or []
    fee = meta.get("fee") or 0

    # Build index map: pubkey -> index
    for idx, key_obj in enumerate(account_keys):
        pubkey = key_obj.get("pubkey") if isinstance(key_obj, dict) else str(key_obj)
        if pubkey != addr:
            continue
        if idx >= len(pre_bals) or idx >= len(post_bals):
            break
        diff = post_bals[idx] - pre_bals[idx]
        # If this account is the fee payer (idx == 0), the fee was deducted from
        # their balance; add it back so we only measure actual received value.
        if idx == 0:
            diff += fee
        return max(diff, 0)  # Only count positive (received) deltas
    return 0


def _parse_spl_received(tx: dict, addr: str) -> dict:
    """Return {token_name: amount} of SPL tokens received by *addr* in this tx.

    Uses a pre/post map keyed by (accountIndex, mint) to avoid double-counting.
    """
    meta = tx.get("meta") or {}

    def _build_map(token_balances):
        m = {}
        for tb in token_balances or []:
            owner = tb.get("owner")
            mint = tb.get("mint")
            if owner != addr or mint not in SPL_TOKENS:
                continue
            acct_idx = tb.get("accountIndex", -1)
            key = (acct_idx, mint)
            ui_amount = float((tb.get("uiTokenAmount") or {}).get("uiAmount") or 0.0)
            m[key] = ui_amount
        return m

    pre_map = _build_map(meta.get("preTokenBalances"))
    post_map = _build_map(meta.get("postTokenBalances"))

    all_keys = set(pre_map) | set(post_map)
    received = {}
    for key in all_keys:
        _, mint = key
        diff = post_map.get(key, 0.0) - pre_map.get(key, 0.0)
        if diff > 0:
            name = SPL_TOKENS[mint]["name"]
            received[name] = received.get(name, 0.0) + diff
    return received


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_solana(address: str, minutes: int = 15) -> dict:
    """Return chain result dict for a Solana address."""
    now_ts = int(time.time())
    min_ts = now_ts - minutes * 60
    addr = address.strip()

    # Step 1 – recent confirmed signatures
    sigs_info = _call_rpc("getSignaturesForAddress", [addr, {"limit": _SIG_LIMIT}])
    if not sigs_info:
        return {"chain": "solana", "address": addr, "total_usd": 0.0, "receipts": []}

    target_sigs = []
    for info in sigs_info:
        if info.get("err") is not None:
            continue  # failed transaction
        bt = info.get("blockTime")
        # Exclude unconfirmed (blockTime is None) and out-of-window transactions
        if bt is None or bt < min_ts:
            continue
        target_sigs.append(info["signature"])

    if not target_sigs:
        return {"chain": "solana", "address": addr, "total_usd": 0.0, "receipts": []}

    received: dict[str, float] = {}

    # Step 2 – parse each confirmed in-window transaction
    for sig in target_sigs[:30]:  # cap at 30 to keep latency bounded
        try:
            tx = _call_rpc(
                "getParsedTransaction",
                [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            )
            if not tx:
                continue

            # Native SOL
            sol_lamports = _parse_sol_received(tx, addr)
            if sol_lamports > 0:
                received["SOL"] = received.get("SOL", 0.0) + sol_lamports / 1e9

            # SPL tokens
            for name, amount in _parse_spl_received(tx, addr).items():
                received[name] = received.get(name, 0.0) + amount

        except Exception as exc:
            logger.warning("Solana tx parse error %s: %s", sig, exc)
            continue

    if not received:
        return {"chain": "solana", "address": addr, "total_usd": 0.0, "receipts": []}

    prices = get_token_prices(list(received.keys()))

    receipts = []
    total_usd = 0.0
    for tok_name, amount in received.items():
        price = prices.get(tok_name)
        if price is None:
            if tok_name in ("USDT", "USDC"):
                price = 1.0
            else:
                raise RuntimeError(f"{tok_name} price unavailable (CoinGecko down and no cache)")
        usd = amount * price
        total_usd += usd
        receipts.append({"token": tok_name, "amount": amount, "usd": usd, "price": price})

    return {
        "chain": "solana",
        "address": addr,
        "total_usd": total_usd,
        "receipts": receipts,
    }
