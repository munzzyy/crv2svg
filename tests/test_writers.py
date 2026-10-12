import math
import xml.etree.ElementTree as ET

import pytest

import crv2svg
from crv2svg.model import Document, Item, Layer, Path, Span
from crvbuild import arc, build_crv, circle, line, square

SVG = "{http://www.w3.org/2000/svg}"


def doc_of(layers, **kw):
    return crv2svg.read_bytes(build_crv(layers, **kw))


def paths(svg_text):
    root = ET.fromstring(svg_text)
    return [p.get("d") for p in root.iter(SVG + "path")]


def test_svg_flips_y_and_closes_shapes():
    doc = doc_of([{"name": "a", "items": [{"kind": "contour", "spans": square(1, 1, 4)}]}])
    assert paths(crv2svg.to_svg(doc)) == ["M1 11 L5 11 L5 7 L1 7 Z"]


def test_svg_open_path_is_not_closed():
    doc = doc_of([{"name": "a", "items": [{"kind": "polyline", "spans": [line((0, 0), (5, 5))]}]}])
    assert paths(crv2svg.to_svg(doc)) == ["M0 12 L5 7"]


def test_svg_arc_direction_and_size():
    spans = [arc((0, 6), (2, 6), 0.5), arc((2, 6), (4, 6), -0.5), arc((4, 6), (6, 6), 2.0)]
    doc = doc_of([{"name": "a", "items": [{"kind": "polyline", "spans": spans}]}])
    d = paths(crv2svg.to_svg(doc))[0]
    # Counter-clockwise in the drawing is sweep 0 once y is flipped; a bulge over 1 is the large arc.
    assert d == "M0 6 A1.25 1.25 0 0 0 2 6 A1.25 1.25 0 0 1 4 6 A1.25 1.25 0 1 0 6 6"


def test_svg_circle_from_two_half_arcs():
    doc = doc_of([{"name": "a", "items": [{"kind": "contour", "spans": circle(10, 6, 2)}]}])
    assert paths(crv2svg.to_svg(doc)) == ["M8 6 A2 2 0 0 0 12 6 A2 2 0 0 0 8 6 Z"]


def test_svg_size_units_and_viewbox():
    doc = doc_of([{"name": "a", "items": []}], material=(0.0, 0.0, 96.0, 48.0))
    root = ET.fromstring(crv2svg.to_svg(doc, units="in"))
    assert (root.get("width"), root.get("height"), root.get("viewBox")) == ("96in", "48in", "0 0 96 48")
    unknown = doc_of([{"name": "a", "items": []}], material=(0.0, 0.0, 96.0, 48.0), units=None)
    assert unknown.units is None
    assert ET.fromstring(crv2svg.to_svg(unknown)).get("width") == "96"


def test_svg_escapes_hostile_layer_names():
    name = 'a"><script>alert(1)</script>&'
    doc = doc_of([{"name": name, "items": [{"kind": "contour", "spans": square(0, 0, 1)}]}])
    text = crv2svg.to_svg(doc)
    assert "<script>" not in text
    root = ET.fromstring(text)
    group = root.find(SVG + "g")
    assert group.get("{http://www.inkscape.org/namespaces/inkscape}label") == name
    assert group.find(SVG + "title").text == name


def test_svg_layer_ids_are_unique():
    layers = [{"name": n, "items": []} for n in ("cut 1", "cut_1", "cut-1", "1", "")]
    root = ET.fromstring(crv2svg.to_svg(doc_of(layers)))
    ids = [g.get("id") for g in root.iter(SVG + "g")]
    assert len(set(ids)) == 5 and all(i[0].isalpha() for i in ids)


def test_previews_are_left_out_unless_asked_for():
    layers = [
        {"name": "Toolpath Previews", "items": [{"kind": "preview", "paths": [square(0, 0, 1)]}]},
        {"name": "a", "items": [{"kind": "contour", "spans": square(2, 2, 1)}]},
    ]
    doc = doc_of(layers)
    assert len(paths(crv2svg.to_svg(doc))) == 1
    assert len(paths(crv2svg.to_svg(doc, include_previews=True))) == 2
    assert crv2svg.to_dxf(doc).count("POLYLINE") == 1


def test_layer_filter():
    layers = [{"name": n, "items": [{"kind": "contour", "spans": square(0, 0, 1)}]} for n in "ab"]
    doc = doc_of(layers)
    root = ET.fromstring(crv2svg.to_svg(doc, layers={"b"}))
    assert [g.find(SVG + "title").text for g in root.iter(SVG + "g")] == ["b"]


def test_page_grows_when_geometry_leaves_the_material():
    doc = doc_of([{"name": "a", "items": [{"kind": "contour", "spans": square(30, 0, 10)}]}])
    x0, y0, x1, y1 = doc.page()
    assert x0 < 30 and x1 > 40 and y1 > 10


def test_bounds_include_the_bulge_of_an_arc():
    doc = Document(layers=[Layer("a", items=[Item("contour", [Path([Span((0, 0, 0), (2, 0, 0), -1.0)])])])])
    box = doc.bounds()
    assert box[3] == pytest.approx(1.0) and box[1] == pytest.approx(0.0)
    doc.layers[0].items[0].paths[0].spans[0].bulge = 1.0
    assert doc.bounds()[1] == pytest.approx(-1.0)


def dxf_pairs(text):
    lines = text.split("\n")
    return [(int(lines[i]), lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def test_dxf_structure_and_bulges():
    spans = [line((0, 0), (2, 0)), arc((2, 0), (2, 2), 0.41421356), line((2, 2), (0, 2)),
             line((0, 2), (0, 0))]
    doc = doc_of([{"name": "cut out 1/4\"", "color": (0, 0, 255),
                   "items": [{"kind": "contour", "spans": spans}]}])
    pairs = dxf_pairs(crv2svg.to_dxf(doc))
    assert pairs[0] == (0, "SECTION") and pairs[-1] == (0, "EOF")
    assert (2, "cut_out_1_4") in pairs and (62, "5") in pairs
    poly = pairs.index((0, "POLYLINE"))
    assert (70, "1") in pairs[poly:poly + 8]
    verts = [i for i, p in enumerate(pairs) if p == (0, "VERTEX")]
    assert len(verts) == 4
    bulges = [float(v) for c, v in pairs if c == 42]
    assert bulges == [0.41421356]
    second = dict(pairs[verts[1] + 1:verts[1] + 6])
    assert (second[10], second[20]) == ("2.0", "0.0") and 42 in second


def test_dxf_open_path_writes_its_last_point():
    doc = doc_of([{"name": "a", "items": [{"kind": "polyline",
                                           "spans": [line((0, 0), (5, 5)), line((5, 5), (9, 5))]}]}])
    pairs = dxf_pairs(crv2svg.to_dxf(doc))
    poly = pairs.index((0, "POLYLINE"))
    assert (70, "0") in pairs[poly:poly + 8]
    xs = [float(v) for c, v in pairs if c == 10][1:]
    assert xs == [0.0, 5.0, 9.0]


def test_dxf_layer_names_stay_unique_after_cleaning():
    layers = [{"name": n, "items": []} for n in ("cut 1", "cut_1", "CUT-1", "")]
    pairs = dxf_pairs(crv2svg.to_dxf(doc_of(layers)))
    names = [pairs[i + 1][1] for i, p in enumerate(pairs) if p == (0, "LAYER")]
    assert len(names) == 4 and len({n.upper() for n in names}) == 4


def test_disjoint_spans_become_separate_runs():
    spans = [line((0, 0), (1, 0)), line((5, 5), (6, 5))]
    doc = doc_of([{"name": "a", "items": [{"kind": "polyline", "spans": spans}]}])
    assert paths(crv2svg.to_svg(doc)) == ["M0 12 L1 12 M5 7 L6 7"]
    assert crv2svg.to_dxf(doc).count("POLYLINE") == 2


def test_radius_matches_geometry():
    span = Span((0, 0, 0), (2, 0, 0), math.tan(math.pi / 8))
    assert span.radius == pytest.approx(math.sqrt(2))


def test_number_format_rounds_ties_away_from_zero():
    from crv2svg.numfmt import fmt
    assert fmt(0.0078125, 6) == "0.007813"
    assert fmt(-0.0078125, 6) == "-0.007813"
    assert fmt(2.0, 6) == "2" and fmt(-0.0000001, 6) == "0" and fmt(1e-7, 9) == "0.0000001"
    assert fmt(123456789.125, 6) == "123456789.125"


def test_nearly_straight_arc_and_huge_numbers_do_not_break_formatting():
    from crv2svg.numfmt import fmt
    assert fmt(1.5e300, 6).startswith("15000") and fmt(1e-300, 6) == "0"
    spans = [arc((0, 0), (10, 0), 1e-12), arc((10, 0), (20, 0), 1e-7)]
    doc = doc_of([{"name": "a", "items": [{"kind": "polyline", "spans": spans}]}])
    d = paths(crv2svg.to_svg(doc))[0]
    assert d.startswith("M0 12 L10 12 A") and crv2svg.to_dxf(doc).endswith("EOF\n")
