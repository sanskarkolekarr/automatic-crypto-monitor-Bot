# Crypto Payment Monitor Bot

A Telegram bot that verifies crypto payments for market makers. A market maker registers their
wallet address; when someone announces a payment (e.g. **"sent $300"**, **"send 400"**,
**"paid 300 usd"**, **"300$"**), the bot checks the blockchain to confirm that the wallet
actually received that amount in USDT or USDC within the last 15 minutes. Only **USDT** and
**USDC** count toward the payment (valued at $1 each); no other tokens are accepted.

## Supported chains & tokens

| Chain | Accepted tokens | Method |
|-------|-----------------|--------|
| BSC   | USDT, USDC (BEP-20) | public RPC (no keys) |
| ETH   | USDT, USDC (ERC-20) | public RPC (no keys) |
| TRON  | USDT, USDC (TRC-20, official contracts only) | TronGrid (keyless) |

**Everything runs on free RPCs — no API keys needed.**

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Install Python 3.10+.
3. Run:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt   (Windows)
   source .venv/bin/pip install -r requirements.txt (macOS/Linux)
   ```
4. Copy `.env.example` to `.env` and fill in:
   - `TELEGRAM_BOT_TOKEN` — your bot token from BotFather
   - `OWNER_TELEGRAM_ID` — your numeric Telegram user ID (get it from @userinfobot)
   - `ALLOWED_USER_IDS` — comma-separated Telegram IDs of the market makers you give access to
5. Start the bot:
   ```
   .venv\Scripts\python run.py   (Windows)
   .venv/bin/python run.py       (macOS/Linux)
   ```

## How to use

**Market maker registers their wallet:**
```
/register  →  pick BSC / ETH / TRON  →  send wallet address
```

**Anyone with access verifies a payment — 3 ways:**

1. Reply to the MM's message with the amount: `sent $300` or `300 usd`
2. Mention the MM: `@mmsusername 400`
3. Command: `/verify 300` (optionally replying to / mentioning the MM)

If you send an amount without mentioning or replying to a market maker, the bot will ask you to
resend it in this format: `sent 400 @mmusername`.

The bot replies with a breakdown of everything received in USDT/USDC in the last 15 minutes and a
**PAYMENT CONFIRMED** / **NO MATCHING PAYMENT FOUND** verdict.

## Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/start` `/help` | Allowed users | Show instructions |
| `/register` | Allowed users | Guided wallet registration |
| `/mywallet` | Allowed users | Show your wallets |
| `/remove [chain]` | Allowed users | Remove your wallet(s) |
| `/verify <amount>` | Allowed users | Check a payment |
| `/add @username bsc 0x...` | Owner | Register a wallet for an MM |
| `/grant` *(reply to a user)* | Owner | Give someone bot access |
| `/revoke` *(reply to a user)* | Owner | Remove someone's access |
| `/list` | Owner | Show all registered wallets |

## How the verification works

1. The amount is parsed from the message (`$300`, `300 usd`, `sent 400`, ...).
2. The target MM is found from the reply, the `@mention`, or the sender.
3. For each of the MM's wallets, the bot queries the chain for **incoming USDT/USDC transfers in
   the last 15 minutes** (all via free public RPCs, no API keys):
   - BSC/ETH: `eth_getLogs` on the official USDT and USDC token contracts.
   - TRON: TronGrid `/v1/accounts/{address}/transactions/trc20`, filtered to the official
     USDT and USDC contracts.
4. Each received amount is valued at $1 (USDT/USDC are stablecoins).
5. If the total received ≥ the announced amount, the payment is confirmed.

## Notes

- `VERIFY_WINDOW_MINUTES` in `.env` changes how far back the bot scans (default 15).
- The `eth_getLogs` scan window is small (~300 blocks on BSC), so checks are fast and cheap.
- Other tokens received (BNB, ETH, BTC, meme coins...) are ignored and never count toward a payment.
