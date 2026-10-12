"""One number format for both writers, defined exactly so the JavaScript port can match it."""

import math
from decimal import ROUND_HALF_UP, Context, Decimal

from .errors import CrvError

# Wide enough that no finite double overflows the quantize step.
_CONTEXT = Context(prec=400, rounding=ROUND_HALF_UP)


def fmt(value, digits):
    """Fixed-point with ties rounded away from zero, trailing zeros trimmed."""
    if not math.isfinite(value):
        raise CrvError("a number in this file is too large to write")
    quantum = Decimal(1).scaleb(-digits)
    text = format(Decimal(value).quantize(quantum, context=_CONTEXT), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def unique_name(base, used, key):
    """base, or base_2, base_3 and so on. used maps each taken key to the next suffix to try."""
    candidate, n = base, used.get(key(base), 1)
    while key(candidate) in used:
        n += 1
        candidate = "%s_%d" % (base, n)
    used[key(base)] = n
    used[key(candidate)] = 1
    return candidate
