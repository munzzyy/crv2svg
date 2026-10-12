"""Write a Document as SVG. CRV has y pointing up, SVG down, so y is flipped on the page."""

import re
from xml.sax.saxutils import escape, quoteattr

from .model import run_is_closed
from .numfmt import fmt

UNIT_SUFFIX = {"in": "in", "mm": "mm"}


def to_svg(doc, units=None, include_previews=False, layers=None):
    units = units or doc.units
    x0, y0, x1, y1 = doc.page(include_previews)
    width, height = x1 - x0, y1 - y0
    suffix = UNIT_SUFFIX.get(units, "")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'width="%s%s" height="%s%s" viewBox="0 0 %s %s">'
        % (_num(width), suffix, _num(height), suffix, _num(width), _num(height)),
    ]
    used = set()
    for layer in doc.drawing_layers(include_previews):
        if layers is not None and layer.name not in layers:
            continue
        out.append(
            '<g id=%s inkscape:groupmode="layer" inkscape:label=%s fill="none" '
            'stroke="%s" stroke-width="1" vector-effect="non-scaling-stroke">'
            % (quoteattr(_unique_id(layer.name, used)), quoteattr(layer.name), _stroke(layer.color)))
        out.append("<title>%s</title>" % escape(layer.name))
        for path in layer.paths():
            d = _path_data(path, x0, y1)
            if d:
                out.append('<path vector-effect="non-scaling-stroke" d="%s"/>' % d)
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _path_data(path, x0, y_top):
    parts = []
    for run in path.runs():
        sx, sy = run[0].start[0] - x0, y_top - run[0].start[1]
        parts.append("M%s %s" % (_num(sx), _num(sy)))
        closed = run_is_closed(run)
        for i, span in enumerate(run):
            ex, ey = span.end[0] - x0, y_top - span.end[1]
            last = i == len(run) - 1
            if span.is_curve:
                (ax, ay), (bx, by) = span.control
                parts.append("C%s %s %s %s %s %s" % (
                    _num(ax - x0), _num(y_top - ay), _num(bx - x0), _num(y_top - by),
                    _num(ex), _num(ey)))
            elif span.is_arc:
                r = _num(span.radius)
                parts.append("A%s %s 0 %d %d %s %s" % (
                    r, r, 1 if abs(span.bulge) > 1 else 0, 0 if span.bulge > 0 else 1,
                    _num(ex), _num(ey)))
            elif not (closed and last):
                parts.append("L%s %s" % (_num(ex), _num(ey)))
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
    candidate, n = base, 2
    while candidate in used:
        candidate = "%s_%d" % (base, n)
        n += 1
    used.add(candidate)
    return candidate
