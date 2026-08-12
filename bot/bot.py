import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import MessageEntityType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from . import db
from .config import (
    ALLOWED_USER_IDS,
    OWNER_TELEGRAM_ID,
    TELEGRAM_BOT_TOKEN,
    VERIFY_WINDOW_MINUTES,
)
from .parser import parse_amount
from .verifier import verify_wallets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHAINS = ("bsc", "eth", "tron")
REGISTER_CHAIN, REGISTER_ADDRESS = 1, 2

HELP_TEXT = (
    "Crypto Payment Monitor Bot\n\n"
    "This bot verifies that a registered wallet actually received a payment.\n\n"
    "Commands:\n"
    "/register - register your wallet (BSC / ETH / TRON)\n"
    "/mywallet - show your registered wallets\n"
    "/remove [chain] - remove one or all of your wallets\n"
    "/verify 300 - check a $300 payment was received\n\n"
    "How to verify a payment:\n"
    "• Reply to the market maker's message with the amount, e.g. \"sent $300\"\n"
    "• Or @mention them: \"@mm 300 usd\"\n"
    "• Or send /verify 300 while replying to them\n\n"
    "Owner commands:\n"
    "/add @username chain ADDRESS - register a wallet for a market maker\n"
    "/grant (reply to a user) - give someone bot access\n"
    "/revoke (reply to a user) - remove their access\n"
    "/list - show all registered wallets"
)


def is_allowed(user_id):
    return user_id in ALLOWED_USER_IDS or db.user_allowed(user_id)


def validate_address(chain, address):
    address = address.strip()
    if chain in ("bsc", "eth"):
        return (
            len(address) == 42
            and address.startswith("0x")
            and all(c in "0123456789abcdefABCDEF" for c in address[2:])
        )
    if chain == "tron":
        return len(address) == 34 and address.startswith("T")
    return False


def resolve_wallets(update):
    msg = update.message

    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user
        wallets = db.get_wallets_by_user(user.id)
        if not wallets and user.username:
            wallets = db.get_wallets_by_username(user.username)
        return wallets or None

    for entity in (msg.entities or []):
        if entity.type == MessageEntityType.MENTION:
            username = msg.parse_entity(entity).lstrip("@").lower()
            return db.get_wallets_by_username(username) or None

    return None


def describe_target(update):
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user
        return user.full_name or user.username or f"user {user.id}"
    for entity in (msg.entities or []):
        if entity.type == MessageEntityType.MENTION:
            return msg.parse_entity(entity)
    return "you"


# ------------------------------ commands ------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("You don't have access to this bot.")
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("You don't have access to this bot.")
        return ConversationHandler.END
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton(c.upper()) for c in CHAINS]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "Which chain is your wallet on?\n\nSend /cancel to abort.", reply_markup=kb
    )
    return REGISTER_CHAIN


async def register_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chain = update.message.text.strip().lower()
    if chain not in CHAINS:
        await update.message.reply_text("Invalid chain. Pick one: BSC / ETH / TRON.")
        return REGISTER_CHAIN
    context.user_data["reg_chain"] = chain
    await update.message.reply_text("Great. Now send your wallet address:")
    return REGISTER_ADDRESS


async def register_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    chain = context.user_data.get("reg_chain")
    if not validate_address(chain, address):
        await update.message.reply_text(
            "Invalid address for that chain. Please re-send it or /cancel."
        )
        return REGISTER_ADDRESS

    user = update.effective_user
    db.add_wallet(user.id, user.username, user.full_name, chain, address)
    await update.message.reply_text(
        f"Wallet registered:\nChain: {chain.upper()}\nAddress: {address}"
    )
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("You don't have access to this bot.")
        return
    rows = db.get_wallets_by_user(update.effective_user.id)
    if not rows:
        await update.message.reply_text("No wallets registered. Use /register")
        return
    lines = ["Your wallets:"]
    lines += [f"  • {r['chain'].upper()} · {r['address']}" for r in rows]
    await update.message.reply_text("\n".join(lines))


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("You don't have access to this bot.")
        return
    user = update.effective_user
    if context.args:
        chain = context.args[0].lower()
        if db.remove_wallet(user.id, chain):
            await update.message.reply_text(f"Removed your {chain.upper()} wallet.")
        else:
            await update.message.reply_text("No such wallet found.")
    else:
        db.remove_all_wallets(user.id)
        await update.message.reply_text("Removed all your wallets.")


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("Only the owner can use this.")
        return
    parts = update.message.text.split()
    if len(parts) != 4:
        await update.message.reply_text("Usage: /add @username bsc 0x1234...")
        return
    _, username, chain, address = parts
    chain = chain.lower()
    username = username.lstrip("@").lower()
    if chain not in CHAINS or not validate_address(chain, address):
        await update.message.reply_text("Invalid chain or address.")
        return
    db.add_wallet(0, username, username, chain, address)
    await update.message.reply_text(f"Registered {username} → {chain.upper()} {address}")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("Only the owner can use this.")
        return
    rows = db.get_all_wallets()
    if not rows:
        await update.message.reply_text("No registered wallets.")
        return
    by_user = {}
    for r in rows:
        key = r["username"] or f"user {r['user_id']}"
        by_user.setdefault(key, []).append(f"{r['chain'].upper()} · {r['address']}")
    lines = []
    for name, wallets in by_user.items():
        lines.append(f"👤 {name}")
        lines += [f"  • {w}" for w in wallets]
    await update.message.reply_text("\n".join(lines))


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("Only the owner can use this.")
        return
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Reply to a user's message with /grant to give them access.")
        return
    user = msg.reply_to_message.from_user
    db.add_allowed_user(user.id, user.username)
    await msg.reply_text(f"Granted access to {user.full_name or user.username or user.id}.")


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_TELEGRAM_ID:
        await update.message.reply_text("Only the owner can use this.")
        return
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Reply to a user's message with /revoke to remove their access.")
        return
    user = msg.reply_to_message.from_user
    db.remove_allowed_user(user.id)
    await msg.reply_text(f"Removed access from {user.full_name or user.username or user.id}.")


# ------------------------------ verification ------------------------------


async def run_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, amount):
    if amount is None or amount <= 0:
        await update.message.reply_text(
            'Usage: send a message like "sent $300" or reply "300 usd", or /verify 300'
        )
        return

    wallets = resolve_wallets(update)
    if not wallets:
        await update.message.reply_text(
            f"Please send the payment like this:\nsent ${amount:,.2f} @mmusername"
        )
        return

    target = describe_target(update)
    await update.message.reply_text(
        f"Checking {target}'s wallet(s) for a ${amount:,.2f} payment "
        f"in the last {VERIFY_WINDOW_MINUTES} min..."
    )

    total, results, confirmed = verify_wallets(wallets, amount, VERIFY_WINDOW_MINUTES)

    lines = []
    for r in results:
        if "error" in r:
            lines.append(f"❌ {r['chain'].upper()}: {r['error']}")
            continue
        short = f"{r['address'][:6]}...{r['address'][-4:]}"
        if r["receipts"]:
            lines.append(f"{r['chain'].upper()} ({short}):")
            for rc in r["receipts"]:
                price_str = f" @ ${rc['price']:,.2f}" if rc.get("price") and rc["price"] != 1.0 else ""
                lines.append(f"  • {rc['amount']:,.4f} {rc['token']}{price_str} ≈ ${rc['usd']:,.2f}")
        else:
            lines.append(f"{r['chain'].upper()} ({short}): no incoming transfers found")

    verdict = "PAYMENT CONFIRMED" if confirmed else "NO MATCHING PAYMENT FOUND"
    body = "\n".join(lines) or "No data returned."
    
    footer = f"💰 Total received: ${total:,.2f} (Target: ${amount:,.2f})"
    if not confirmed:
        footer += "\n\n⚠️ If you sent the funds and think we had a technical error, please send proof (screen recording) and tag the middleman!"

    await update.message.reply_text(
        f"{'✅' if confirmed else '❌'} {verdict}\n\n"
        f"{body}\n\n"
        f"{footer}"
    )



async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("You don't have access to this bot.")
        return
    amount = None
    for arg in context.args or []:
        try:
            amount = float(arg.replace(",", "").replace("$", ""))
            break
        except ValueError:
            continue
    if amount is None:
        amount = parse_amount(update.message.text)
    await run_verification(update, context, amount)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    text = update.message.text or ""
    if not text.strip():
        return
    amount = parse_amount(text)
    if amount is None:
        return
    await run_verification(update, context, amount)


# ------------------------------ main ------------------------------


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    req = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(req).get_updates_request(req).build()

    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", cmd_register)],
        states={
            REGISTER_CHAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_chain)],
            REGISTER_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_address)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("mywallet", cmd_wallet))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("verify", cmd_verify))
    # BUG FIX: register_conv MUST be added before the catch-all MessageHandler;
    # otherwise the conversation's text states (REGISTER_CHAIN / REGISTER_ADDRESS)
    # are intercepted by on_message and the conversation never advances.
    app.add_handler(register_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    logger.info("Bot started. Press Ctrl+C to stop.")
    app.run_polling(bootstrap_retries=-1)

