"""Write a Document as an R12 ASCII DXF. Arcs stay arcs: they go out as polyline bulges."""

import re

from .model import flatten_curve, run_is_closed
from .numfmt import fmt, unique_name

ACI = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255),
       5: (0, 0, 255), 6: (255, 0, 255), 7: (0, 0, 0)}


def to_dxf(doc, include_previews=False, layers=None, curve_tolerance=None, sheet=None):
    """curve_tolerance is how far a flattened Bezier may stray, in drawing units."""
    if curve_tolerance is None:
        curve_tolerance = 0.01 if doc.units == "mm" else 0.0005
    chosen = [l for l in doc.drawing_layers(include_previews)
              if layers is None or l.name in layers]
    names, used = {}, {}
    for index, layer in enumerate(chosen):
        names[index] = _layer_name(layer.name, used)
    out = []

    def emit(code, value):
        out.append("%3d" % code)
        out.append(str(value))

    emit(0, "SECTION"); emit(2, "HEADER")
    emit(9, "$ACADVER"); emit(1, "AC1009")
    if doc.units:
        emit(9, "$MEASUREMENT"); emit(70, 1 if doc.units == "mm" else 0)
    emit(0, "ENDSEC")
    emit(0, "SECTION"); emit(2, "TABLES")
    emit(0, "TABLE"); emit(2, "LAYER"); emit(70, len(chosen))
    for index, layer in enumerate(chosen):
        emit(0, "LAYER"); emit(2, names[index]); emit(70, 0)
        emit(62, _aci(layer.color)); emit(6, "CONTINUOUS")
    emit(0, "ENDTAB"); emit(0, "ENDSEC")
    emit(0, "SECTION"); emit(2, "ENTITIES")
    for index, layer in enumerate(chosen):
        for path in layer.paths(sheet):
            for run in path.runs():
                closed = run_is_closed(run, path.tolerance)
                emit(0, "POLYLINE"); emit(8, names[index]); emit(66, 1)
                emit(10, "0.0"); emit(20, "0.0"); emit(30, "0.0")
                emit(70, 1 if closed else 0)
                for span in run:
                    _vertex(emit, names[index], span.start, span.bulge if span.is_arc else 0.0)
                    if span.is_curve:
                        for pt in flatten_curve(span, curve_tolerance)[:-1]:
                            _vertex(emit, names[index], pt, 0.0)
                if not closed:
                    _vertex(emit, names[index], run[-1].end, 0.0)
                emit(0, "SEQEND"); emit(8, names[index])
    emit(0, "ENDSEC")
    emit(0, "EOF")
    return "\n".join(out) + "\n"


def _vertex(emit, layer, point, bulge):
    emit(0, "VERTEX"); emit(8, layer)
    emit(10, _num(point[0])); emit(20, _num(point[1])); emit(30, "0.0")
    if bulge:
        emit(42, _num(bulge))


def _num(value):
    text = fmt(value, 9)
    return text if "." in text else text + ".0"


def _aci(color):
    # Neutral colours are nearer to yellow than to black in RGB, so they are picked by hand.
    if max(color) - min(color) < 40:
        return 8 if 70 <= max(color) <= 200 else 7
    return min(ACI, key=lambda k: sum((a - b) ** 2 for a, b in zip(ACI[k], color)))


def _layer_name(name, used):
    base = re.sub(r"[^A-Za-z0-9_$-]+", "_", name).strip("_")[:28] or "LAYER"
    return unique_name(base, used, str.upper)
