import re

# Matches amounts marked with $ or a usd/dollar word:  "$300", "300$", "300 usd", "$ 400.50"
_MARKED = re.compile(
    r"\$\s*([0-9][0-9,]{0,10}(?:\.\d+)?)"
    r"|\b([0-9][0-9,]{0,10}(?:\.\d+)?)\s*(?:(?:usd|dollars?)\b|\$)",
    re.IGNORECASE,
)

# Words that signal a payment action, used to pick up plain numbers like "sent 400"
_ACTION = re.compile(
    r"\b(?:sends?|sent|paid|transfer(?:red|ed)?|deposited?|credited|received)\b",
    re.IGNORECASE,
)

_NUM = re.compile(r"\$?\s*([0-9][0-9,]{0,10}(?:\.\d+)?)")


def _to_float(raw):
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_amount(text):
    """Extract the payment amount (USD) mentioned in a message, or None."""
    if not text:
        return None

    # Prefer amounts that are explicitly marked as dollars
    for m in _MARKED.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw:
            return _to_float(raw)

    # Otherwise look for a number right after an action word: "sent 400", "paid 300"
    for m in _ACTION.finditer(text):
        window = text[m.end(): m.end() + 60]
        m2 = _NUM.search(window)
        if m2:
            val = _to_float(m2.group(1))
            if val is not None:
                return val

    return None
