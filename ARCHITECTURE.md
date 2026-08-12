# Architecture

One Telegram bot serves **all** market makers. MMs are identified by their Telegram username;
each payment message must mention or reply to the target MM so the bot checks **only that MM's
registered wallets**.

```
                        ┌─────────────────────────────────────────────────────────┐
   Telegram            │                     BOT PROCESS (run.py)                  │
                        │                                                         │
┌──────────┐  update   │  ┌──────────────────┐     ┌──────────────────────────┐   │
│  Payer / │ ─────────►│  │ Message Router    │────►│ Verification Pipeline    │   │
│  MM       │  /reply  │  │ (PTB handlers)    │     │ verifier.py              │   │
└──────────┘           │  └────────┬─────────┘     │  ThreadPool (4 workers)   │   │
     │                 │           │               └───────┬──────────────────┘   │
     │  reply/verify  │           │ parses $amount         │ dispatch by chain    │
     ▼                 │           ▼                       ▼                       │
┌──────────┐          │  ┌─────────────┐   ┌─────────────────────────────────┐    │
│ Telegram │◄─────────│  │ MM Resolver  │   │  ┌──────────┐  ┌──────────────┐ │    │
│  reply   │  result  │  │ resolve_wallets│  │  │ evm.py   │  │  tron.py    │ │    │
└──────────┘          │  └──────┬──────┘   │  │ BSC + ETH │  │ TRON        │ │    │
     ▲                 │         │ wallet   │  │ (USDT/USDC)│ (USDT/USDC)  │ │    │
     │                 │         ▼          │  └─────┬────┘  └─────┬────────┘ │    │
     │                 │  ┌─────────────┐   │        │ RPCs/Grid   │          │    │
     │                 │  │   SQLite    │   │        ▼             ▼          │    │
     │                 │  │ wallets.db  │   │  ┌──────────┐  ┌─────────────┐  │    │
     │                 │  └─────────────┘   │  │ Public   │  │  TronGrid   │  │    │
     │                 │                    │  │ EVM RPCs │  │  (keyless)  │  │    │
     │                 │                    │  └────┬─────┘  └──────┬──────┘  │    │
     │                 │                    │       │  eth_getLogs   │  trc20 │    │
     │                 │                    │       └──────┬─────────┘        │    │
     │                 │                    │              ▼                   │    │
     │                 │                    │     USDT/USDC ≈ $1 each          │    │
     └─────────────────┼────────────────────┼──────────────────────────────────┘
                       │  ✅/❌ + $ breakdown │
                       └─────────────────────┘
```

## Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Bot entry | `run.py` | Starts the application (polling) |
| Message router | `bot/bot.py` | Telegram handlers, access control, reply formatting |
| MM resolver | `bot/bot.py` (`resolve_wallets`) | Picks the target MM: reply → @mention → prompt |
| Amount parser | `bot/parser.py` | Extracts USD amount from free text |
| Verifier | `bot/verifier.py` | Runs chain checks in parallel, sums USD totals |
| Chain checkers | `bot/chains/evm.py`, `bot/chains/tron.py` | Fetch incoming USDT/USDC transfers per chain (RPC-only) |
| Storage | `bot/db.py` | SQLite `data/wallets.db` |
| Config | `bot/config.py` | Env vars from `.env` |

## Message flow

```
Payer:  "sent 400$ @mm1"

  1. on_message   → parse_amount("sent 400$ @mm1")        → 400.0
  2. resolve_wallets → @mention "mm1" → SELECT * FROM wallets WHERE username='mm1'
  3. verify_wallets([{chain:bsc, address:0x...}, {chain:tron, T...}], 400, 15)
  4. BSC worker   → eth_getLogs(USDT+USDC, 0x... , last ~300 blocks) → $ value
     TRON worker  → TronGrid /transactions/trc20 (official USDT/USDC) → $ value
  5. total ≥ $400  →  ✅ PAYMENT CONFIRMED  (with per-token USD breakdown)
                    /  ❌ NO MATCHING PAYMENT FOUND
```

No mention / reply  →  bot replies `Please send the payment like this: sent $400.00 @mmusername`

## Data model (SQLite)

```
wallets (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER,        -- Telegram ID (0 if added via /add by username)
  username   TEXT,           -- Telegram @username (used for @mention lookup)
  name       TEXT,
  chain      TEXT,           -- bsc | eth | tron
  address    TEXT,
  created_at TEXT
  UNIQUE(user_id, chain, address)
)

allowed_users (
  user_id    INTEGER PRIMARY KEY,   -- granted via /grant (owner)
  username   TEXT,
  created_at TEXT
)
```

## External dependencies

| Service | Use | Key required |
|---------|-----|--------------|
| Telegram Bot API | messaging | token only |
| BSC public RPCs | `eth_getLogs` on USDT/USDC contracts | no |
| ETH public RPCs | `eth_getLogs` on USDT/USDC contracts | no |
| TronGrid | official USDT/USDC TRC-20 history | no |

## Design decisions

- **One bot, many MMs** — DB stores MM → wallet mapping; @mention selects the target.
- **Event-driven checks** — no background scanner; blockchain is queried only when a payment
  is announced, within a small window (~300 blocks) so it is fast and free-tier friendly.
- **Chain isolation** — a failure on one chain (RPC down, rate limit) does not block others
  (parallel workers + per-chain try/except).
- **RPC-only** — no paid APIs; everything runs on free public RPCs and keyless TronGrid.
- **USDT/USDC only** — only the official USDT and USDC contracts count (valued at $1 each);
  BNB, ETH, BUSD, BTC, meme coins and fake tokens are all ignored.
