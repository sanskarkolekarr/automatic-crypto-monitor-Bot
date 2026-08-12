"""
Amount parser — extracts a USD value from free-form payment messages.

Fixes vs original:
- Removed "received" from _ACTION words. "I received $300" describes the
  recipient's perspective, not the payer's, so matching it was semantically
  incorrect and caused wallet lookup confusion.
- Added "send" (present tense) alongside "sent".
"""

import re

# Matches amounts explicitly marked as dollars:
#   "$300", "300$", "300 usd", "$ 400.50", "300 dollars"
_MARKED = re.compile(
    r"\$\s*([0-9][0-9,]{0,10}(?:\.\d+)?)"
    r"|\b([0-9][0-9,]{0,10}(?:\.\d+)?)\s*(?:(?:usd|dollars?)(?:\b)|(?=\$)|\$)",
    re.IGNORECASE,
)

# Action verbs that signal a payment; "received" intentionally excluded
# because it describes the recipient's viewpoint, not the payer's.
_ACTION = re.compile(
    r"\b(?:sends?|sent|paid|transfer(?:red|ed)?|deposited?|credited)\b",
    re.IGNORECASE,
)

_NUM = re.compile(r"\$?\s*([0-9][0-9,]{0,10}(?:\.\d+)?)")


def _to_float(raw: str | None) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError, AttributeError):
        return None


def parse_amount(text: str | None) -> float | None:
    """Extract the payment amount (USD) from a message, or None."""
    if not text:
        return None

    # Prefer amounts that are explicitly marked as dollars
    for m in _MARKED.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw:
            val = _to_float(raw)
            if val and val > 0:
                return val

    # Fall back to number right after an action verb: "sent 400", "paid 300"
    for m in _ACTION.finditer(text):
        window = text[m.end(): m.end() + 60]
        m2 = _NUM.search(window)
        if m2:
            val = _to_float(m2.group(1))
            if val and val > 0:
                return val

    return None
