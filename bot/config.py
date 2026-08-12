import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_TELEGRAM_ID = int(os.getenv("OWNER_TELEGRAM_ID", "0") or 0)

# Users allowed to use the bot (env list + owner)
ALLOWED_USER_IDS = {OWNER_TELEGRAM_ID} if OWNER_TELEGRAM_ID else set()
for part in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(","):
    if part.isdigit():
        ALLOWED_USER_IDS.add(int(part))

VERIFY_WINDOW_MINUTES = int(os.getenv("VERIFY_WINDOW_MINUTES", "15") or 15)
TOLERANCE_USD = float(os.getenv("TOLERANCE_USD", "4.0") or 4.0)

