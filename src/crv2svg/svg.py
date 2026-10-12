"""Write a Document as SVG. CRV has y pointing up, SVG down, so y is flipped on the page."""

import math
import re
from xml.sax.saxutils import escape, quoteattr

from .errors import CrvError
from .model import MAX_OUTPUT, run_is_closed
from .numfmt import fmt, unique_name

UNIT_SUFFIX = {"in": "in", "mm": "mm"}


def to_svg(doc, units=None, include_previews=False, layers=None, sheet=None):
    """sheet is one entry of doc.sheets, or None to draw every sheet on one page."""
    units = units or doc.units
    x0, y0, x1, y1 = doc.page(include_previews, sheet)
    width, height = x1 - x0, y1 - y0
    suffix = UNIT_SUFFIX.get(units, "")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'width="%s%s" height="%s%s" viewBox="0 0 %s %s">'
        % (_num(width), suffix, _num(height), suffix, _num(width), _num(height)),
    ]
    used = {}
    size = 0
    for layer in doc.drawing_layers(include_previews):
        if layers is not None and layer.name not in layers:
            continue
        out.append(
            '<g id=%s inkscape:groupmode="layer" inkscape:label=%s fill="none" '
            'stroke="%s" stroke-width="1" vector-effect="non-scaling-stroke">'
            % (quoteattr(_unique_id(layer.name, used)), quoteattr(_clean(layer.name)),
               _stroke(layer.color)))
        out.append("<title>%s</title>" % escape(_clean(layer.name)))
        for path in layer.paths(sheet):
            d = _path_data(path, x0, y1)
            size += len(d)
            if size > MAX_OUTPUT:
                raise CrvError("this drawing is too large to save")
            if d:
                out.append('<path vector-effect="non-scaling-stroke" d="%s"/>' % d)
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _path_data(path, x0, y_top):
    parts = []
    for run in path.runs():
        sx, sy = _num(run[0].start[0] - x0), _num(y_top - run[0].start[1])
        parts.append("M%s %s" % (sx, sy))
        closed = run_is_closed(run, path.tolerance)
        for i, span in enumerate(run):
            ex, ey = _num(span.end[0] - x0), _num(y_top - span.end[1])
            last = i == len(run) - 1
            if span.is_curve:
                (ax, ay), (bx, by) = span.control
                parts.append("C%s %s %s %s %s %s" % (
                    _num(ax - x0), _num(y_top - ay), _num(bx - x0), _num(y_top - by), ex, ey))
            elif span.is_arc:
                # Radius from the rounded end points, so the two halves of a circle still meet.
                chord = math.hypot(float(ex) - float(sx), float(ey) - float(sy))
                b2 = span.bulge * span.bulge
                r = fmt(chord * (1 + b2) / (4 * abs(span.bulge)), 9) if chord else _num(span.radius)
                parts.append("A%s %s 0 %d %d %s %s" % (
                    r, r, 1 if abs(span.bulge) > 1 else 0, 0 if span.bulge > 0 else 1, ex, ey))
            elif not (closed and last):
                parts.append("L%s %s" % (ex, ey))
            sx, sy = ex, ey
        if closed:
            parts.append("Z")
    return " ".join(parts)


def _num(value):
    return fmt(value, 6)


def _stroke(color):
    r, g, b = color
    if min(r, g, b) > 230:
        return "#000000"
    return "#%02x%02x%02x" % (r, g, b)


def _unique_id(name, used):
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "layer"
    if not base[0].isalpha():
        base = "layer_" + base
    return unique_name(base, used, lambda text: text)


def _clean(text):
    """XML 1.0 has no way to write most control characters, so they become U+FFFD."""
    return _NOT_XML.sub("\ufffd", text)


_NOT_XML = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
