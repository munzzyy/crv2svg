import math
from dataclasses import dataclass, field

JOIN_TOLERANCE = 1e-6
# Only a guard against runaway input: 16384 chords hold 0.0005 across a curve 180000 wide.
MAX_CURVE_STEPS = 16384
MIN_BULGE = 1e-9


@dataclass
class Span:
    """One segment: a line, an arc when bulge is set, or a cubic Bezier when control is set.

    bulge is tan(sweep / 4), positive counter-clockwise. control is the two inner points.
    """
    start: tuple
    end: tuple
    bulge: float = 0.0
    control: tuple = None

    @property
    def is_arc(self):
        # A bulge this small is a straight line to more digits than either format keeps.
        return (self.control is None and abs(self.bulge) > MIN_BULGE
                and self.start[:2] != self.end[:2])

    @property
    def is_curve(self):
        return self.control is not None

    @property
    def radius(self):
        chord = math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])
        return chord * (1 + self.bulge * self.bulge) / (4 * abs(self.bulge))


@dataclass
class Path:
    spans: list = field(default_factory=list)
    tolerance: float = JOIN_TOLERANCE

    def runs(self):
        """Split into continuous runs; a run is a list of spans joined end to start."""
        out, run = [], []
        for span in self.spans:
            if run and not _same(run[-1].end, span.start, self.tolerance):
                out.append(run)
                run = []
            run.append(span)
        if run:
            out.append(run)
        return out


def run_is_closed(run, tolerance=JOIN_TOLERANCE):
    return (len(run) > 0 and _same(run[-1].end, run[0].start, tolerance)
            and (len(run) > 1 or run[0].is_arc or run[0].is_curve))


def _same(a, b, tolerance=JOIN_TOLERANCE):
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


@dataclass
class Item:
    kind: str
    paths: list = field(default_factory=list)
    tabs: int = 0
    sheet: object = 0
    parts: list = field(default_factory=list)


@dataclass
class Layer:
    name: str
    color: tuple = (0, 0, 0)
    items: list = field(default_factory=list)
    is_preview: bool = False

    def paths(self, sheet=None):
        for item in self.items:
            if sheet is None or item.sheet == sheet:
                yield from item.paths


@dataclass
class Document:
    layers: list = field(default_factory=list)
    product: str = ""
    version: str = ""
    material: tuple = None
    units: str = None
    preview_gif: bytes = b""
    warnings: list = field(default_factory=list)

    def drawing_layers(self, include_previews=False):
        return [l for l in self.layers if include_previews or not l.is_preview]

    @property
    def sheets(self):
        """The sheets that hold drawn objects, in order. A plain job has one."""
        seen = []
        for layer in self.drawing_layers():
            for item in layer.items:
                if item.paths and item.sheet not in seen:
                    seen.append(item.sheet)
        numbered = sorted(s for s in seen if isinstance(s, int))
        return numbered + [s for s in seen if not isinstance(s, int)] or [0]

    def bounds(self, include_previews=False, sheet=None):
        """(min_x, min_y, max_x, max_y) of the geometry, or None when there is none."""
        box = None
        for layer in self.drawing_layers(include_previews):
            for path in layer.paths(sheet):
                for span in path.spans:
                    for x, y in _span_extent(span):
                        if not (math.isfinite(x) and math.isfinite(y)):
                            continue
                        if box is None:
                            box = [x, y, x, y]
                        else:
                            box[0], box[1] = min(box[0], x), min(box[1], y)
                            box[2], box[3] = max(box[2], x), max(box[3], y)
        return tuple(box) if box else None

    def page(self, include_previews=False, sheet=None):
        """Rectangle to draw on: the material when the geometry fits in it, else the geometry."""
        box = self.bounds(include_previews, sheet)
        mat = self.material
        if mat and all(math.isfinite(v) for v in mat) and mat[2] > 0 and mat[3] > 0:
            rect = (mat[0], mat[1], mat[0] + mat[2], mat[1] + mat[3])
            slack = 1e-6 * max(mat[2], mat[3])
            if box is None or (box[0] >= rect[0] - slack and box[1] >= rect[1] - slack
                               and box[2] <= rect[2] + slack and box[3] <= rect[3] + slack):
                return rect
        if box is None:
            return (0.0, 0.0, 1.0, 1.0)
        pad = 0.02 * max(box[2] - box[0], box[3] - box[1]) or 1.0
        return (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)


def _span_extent(span):
    """End points, plus the axis extremes an arc reaches between them."""
    x1, y1 = span.start[0], span.start[1]
    x2, y2 = span.end[0], span.end[1]
    pts = [(x1, y1), (x2, y2)]
    if span.is_curve:
        # The control points bound the curve, which is close enough for a page size.
        return pts + [tuple(span.control[0]), tuple(span.control[1])]
    if not span.is_arc or not math.isfinite(span.bulge):
        return pts
    b = span.bulge
    chord = math.hypot(x2 - x1, y2 - y1)
    r = span.radius
    # Centre sits on the chord's left normal for a counter-clockwise arc.
    h = chord * (1 - b * b) / (4 * b)
    cx = (x1 + x2) / 2 - h * (y2 - y1) / chord
    cy = (y1 + y2) / 2 + h * (x2 - x1) / chord
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = 4 * math.atan(b)
    for k in range(4):
        angle = k * math.pi / 2
        delta = (angle - a1) % (2 * math.pi) if sweep > 0 else (a1 - angle) % (2 * math.pi)
        if delta < abs(sweep):
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def flatten_curve(span, tolerance):
    """Points along a Bezier span after its start, close enough that no chord strays past tolerance."""
    p0, (c1, c2), p3 = span.start[:2], span.control, span.end[:2]
    # Deviation from the chord is bounded by the second differences of the control polygon.
    dd = max(math.hypot(p0[0] - 2 * c1[0] + c2[0], p0[1] - 2 * c1[1] + c2[1]),
             math.hypot(c1[0] - 2 * c2[0] + p3[0], c1[1] - 2 * c2[1] + p3[1]))
    steps = 1
    if tolerance > 0 and dd > 0:
        steps = max(1, min(MAX_CURVE_STEPS, math.ceil(math.sqrt(0.75 * dd / tolerance))))
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        out.append((a * p0[0] + b * c1[0] + c * c2[0] + d * p3[0],
                    a * p0[1] + b * c1[1] + c * c2[1] + d * p3[1]))
    out[-1] = (p3[0], p3[1])
    return out
