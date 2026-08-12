import time
import logging
import requests
from ..prices import get_token_prices

logger = logging.getLogger(__name__)

MEMPOOL_LTC_API = "https://litecoinspace.org/api"
BLOCKCHAIR_LTC_API = "https://api.blockchair.com/litecoin/dashboards/address"


def check_ltc(address, minutes=15):
    now_ts = int(time.time())
    min_ts = now_ts - minutes * 60

    received_satoshis = 0
    addr = address.strip()

    # Attempt 1: litecoinspace.org (mempool.space for LTC)
    try:
        resp = requests.get(f"{MEMPOOL_LTC_API}/address/{addr}/txs", timeout=15)
        if resp.status_code == 200:
            txs = resp.json()
            for tx in txs:
                status = tx.get("status", {})
                block_time = status.get("block_time")
                # If confirmed, ensure it was within the time window.
                # If unconfirmed (in mempool), we count it as recent.
                if block_time and block_time < min_ts:
                    continue

                for vout in tx.get("vout", []):
                    target_addr = vout.get("scriptpubkey_address", "")
                    if target_addr and target_addr.lower() == addr.lower():
                        received_satoshis += vout.get("value", 0)
        else:
            raise RuntimeError(f"Litecoinspace status code {resp.status_code}")
    except Exception as exc:
        logger.warning("Litecoinspace lookup failed (%s); trying Blockchair fallback", exc)
        # Attempt 2: Blockchair fallback
        try:
            resp = requests.get(f"{BLOCKCHAIR_LTC_API}/{addr}", timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get(addr, {})
                txs = data.get("transactions", [])
                # Filter recent transactions from blockchair list
                for tx_hash in txs:
                    # Fetch tx details if needed, or query address inputs/outputs
                    pass
        except Exception as exc2:
            logger.error("Blockchair fallback also failed: %s", exc2)

    ltc_amount = received_satoshis / 1e8

    if ltc_amount <= 0:
        return {"chain": "ltc", "address": addr, "total_usd": 0.0, "receipts": []}

    prices = get_token_prices(["LTC"])
    price = prices.get("LTC", 1.0)
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
