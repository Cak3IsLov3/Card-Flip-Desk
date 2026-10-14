"""Reading amounts written in German or English notation.

Exports and pasted text from eBay.de use a decimal comma ("12,50", "1.234,56");
English sites use a decimal point ("12.50", "1,234.56"). Both are accepted.
"""

import re
from decimal import Decimal, InvalidOperation

from .calculator import CENT

_AMOUNT = re.compile(r"^\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?$|^\d+(?:[.,]\d{1,2})?$")
_EURO_MARKS = re.compile(r"(?i)eur|€|\s")
FOREIGN_CURRENCY = re.compile(r"(?i)\$|£|usd|gbp|chf|pln|sek|dkk|czk")


def parse_amount(text) -> Decimal | None:
    """12,50 · 12.50 · 1.234,56 · 1,234.56 · 15 · "EUR 12,50" · "12,50 €" → Decimal; otherwise None.

    A separator followed by exactly one or two digits is the decimal point;
    any other separator groups thousands. Negative amounts are not accepted.
    """
    token = _EURO_MARKS.sub("", str(text or ""))
    if not _AMOUNT.match(token):
        return None
    last = max(token.rfind(","), token.rfind("."))
    if last != -1 and len(token) - last - 1 in (1, 2):
        whole, cents = token[:last], token[last + 1:]
    else:
        whole, cents = token, ""
    whole = whole.replace(",", "").replace(".", "")
    try:
        return Decimal(f"{whole}.{cents or '0'}").quantize(CENT)
    except InvalidOperation:
        return None
