"""Place the glyph outlines of a text block.

A text record stores each character's outline in the glyph's own frame, plus its advance
and the offset of that frame from the pen. Glyphs run along the block's base line, which
spans the ink of the laid-out line, and the block's transform is applied last.
"""

import math

from .errors import CrvError
from .model import Path, Span, _span_extent

COORD_LIMIT = 1e9


def layout(matrix, lines, base, padded=False):
    """Return (paths, problem). problem is None, or why the text could not be placed.

    padded is for releases before 9, whose base line is a tenth longer than the ink. Which
    end the extra length sits on is not known, so the ink is centred on the line.
    """
    if not any(outlines for line in lines for _, outlines, _ in line):
        return [], None
    if len(lines) != 1:
        return [], "text with %d lines" % len(lines)
    if base is None or len(base.spans) != 1 or base.spans[0].is_arc or base.spans[0].is_curve:
        return [], "text on a curve"
    start, end = base.spans[0].start, base.spans[0].end
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length <= 0:
        return [], "text with an empty base line"
    ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length

    placed, pen, ink_left, ink_right = [], 0.0, None, None
    for advance, outlines, metrics in lines[0]:
        origin = pen + metrics[0]
        for path in outlines:
            for span in path.spans:
                for x, _ in _span_extent(span):
                    if ink_left is None or origin + x < ink_left:
                        ink_left = origin + x
                    if ink_right is None or origin + x > ink_right:
                        ink_right = origin + x
        placed.append((origin, metrics[1], outlines))
        pen += advance
    ink_left = ink_left or 0.0
    if padded:
        ink_left -= (length - ((ink_right or 0.0) - ink_left)) / 2

    a, b, tx, c, d, ty = (matrix or [1, 0, 0, 0, 1, 0, 0, 0, 1])[:6]
    scale = max(abs(a), abs(b), abs(c), abs(d), 1e-300)
    rotation = abs(a - d) <= 1e-9 * scale and abs(b + c) <= 1e-9 * scale
    reflection = abs(a + d) <= 1e-9 * scale and abs(b - c) <= 1e-9 * scale
    # Arcs survive only a transform that keeps circles round.
    similar = rotation or reflection
    mirrored = a * d - b * c < 0

    def point(origin, lift, p):
        along, up = origin - ink_left + p[0], lift + p[1]
        x = start[0] + ux * along - uy * up
        y = start[1] + uy * along + ux * up
        px, py = a * x + b * y + tx, c * x + d * y + ty
        if not (abs(px) < COORD_LIMIT and abs(py) < COORD_LIMIT):
            raise CrvError("text lands at a position that is not a usable number")
        return (px, py, 0.0)

    paths = []
    for origin, lift, outlines in placed:
        for path in outlines:
            out = Path()
            for span in path.spans:
                pieces = [span] if similar or not span.is_arc else arc_to_curves(span)
                for piece in pieces:
                    control = None
                    if piece.is_curve:
                        control = tuple(point(origin, lift, p)[:2] for p in piece.control)
                    bulge = -piece.bulge if mirrored else piece.bulge
                    out.spans.append(Span(point(origin, lift, piece.start),
                                          point(origin, lift, piece.end), bulge, control))
            paths.append(out)
    return paths, None


def arc_to_curves(span):
    """Cubic Beziers that follow an arc span, a quarter turn or less each."""
    x1, y1, x2, y2 = span.start[0], span.start[1], span.end[0], span.end[1]
    sweep = 4 * math.atan(span.bulge)
    chord = math.hypot(x2 - x1, y2 - y1)
    h = chord * (1 - span.bulge * span.bulge) / (4 * span.bulge)
    cx = (x1 + x2) / 2 - h * (y2 - y1) / chord
    cy = (y1 + y2) / 2 + h * (x2 - x1) / chord
    r = span.radius
    a0 = math.atan2(y1 - cy, x1 - cx)
    steps = max(1, math.ceil(abs(sweep) / (math.pi / 2) - 1e-9))
    step = sweep / steps
    k = 4 / 3 * math.tan(step / 4)
    out, p0 = [], (x1, y1, 0.0)
    for i in range(steps):
        t0, t1 = a0 + i * step, a0 + (i + 1) * step
        p3 = (x2, y2, 0.0) if i == steps - 1 else (cx + r * math.cos(t1), cy + r * math.sin(t1), 0.0)
        c1 = (p0[0] - k * r * math.sin(t0), p0[1] + k * r * math.cos(t0))
        c2 = (p3[0] + k * r * math.sin(t1), p3[1] - k * r * math.cos(t1))
        out.append(Span(p0, p3, 0.0, (c1, c2)))
        p0 = p3
    return out
