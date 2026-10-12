"""One number format for both writers, defined exactly so the JavaScript port can match it."""

from decimal import ROUND_HALF_UP, Context, Decimal

# Wide enough that no finite double overflows the quantize step.
_CONTEXT = Context(prec=400, rounding=ROUND_HALF_UP)


def fmt(value, digits):
    """Fixed-point with ties rounded away from zero, trailing zeros trimmed."""
    quantum = Decimal(1).scaleb(-digits)
    text = format(Decimal(value).quantize(quantum, context=_CONTEXT), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
