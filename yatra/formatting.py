"""Display helpers (Indian number formatting: 2,00,000 not 200,000)."""
from datetime import date


def format_inr(amount: float | int) -> str:
    n = int(round(amount))
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    return f"{sign}₹{digits}"


def format_day(d: date) -> str:
    return d.strftime("%a %d %b %Y")
