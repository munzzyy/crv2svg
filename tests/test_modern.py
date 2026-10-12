"""The layout newer releases write: labelled versions, groups, curves, text, bitmaps."""

import xml.etree.ElementTree as ET

import pytest

import crv2svg
from crv2svg.errors import CrvError
from crv2svg.model import Span, flatten_curve
from crv2svg.text import arc_to_curves
from crvbuild import arc, build_crv, circle, curve, line, square

SVG = "{http://www.w3.org/2000/svg}"
QUARTER = curve((1, 0), (1, 0.5523), (0.5523, 1), (0, 1))
BAR = [line((-1, 0), (1, 0)), line((1, 0), (1, 2)), line((1, 2), (-1, 2)), line((-1, 2), (-1, 0))]


def read(layers, **kw):
    return crv2svg.read_bytes(build_crv(layers, modern=True, **kw))


def paths(text):
    return [p.get("d") for p in ET.fromstring(text).iter(SVG + "path")]


def test_modern_contours_and_units():
    doc = read([{"name": "a", "items": [{"kind": "contour", "spans": square(1, 1, 4)},
                                        {"kind": "polyline", "spans": [line((0, 0), (5, 5))]}]}],
               units="mm", material=(-50.0, -25.0, 100.0, 50.0))
    assert doc.units == "mm" and doc.material == (-50.0, -25.0, 100.0, 50.0)
    root = ET.fromstring(crv2svg.to_svg(doc))
    assert (root.get("width"), root.get("viewBox")) == ("100mm", "0 0 100 50")
    assert paths(crv2svg.to_svg(doc))[0] == "M51 24 L55 24 L55 20 L51 20 Z"
    assert "$MEASUREMENT\n 70\n1\n" in crv2svg.to_dxf(doc)


def test_units_default_to_what_the_file_says_but_can_be_overridden():
    doc = read([{"name": "a", "items": []}], units="in")
    assert ET.fromstring(crv2svg.to_svg(doc)).get("width") == "24in"
    assert ET.fromstring(crv2svg.to_svg(doc, units="mm")).get("width") == "24mm"
    assert "$MEASUREMENT\n 70\n0\n" in crv2svg.to_dxf(doc)


def test_curve_spans_reach_svg_as_cubics():
    doc = read([{"name": "a", "items": [{"kind": "polyline", "spans": [QUARTER]}]}])
    span = doc.layers[0].items[0].paths[0].spans[0]
    assert span.is_curve and span.control == ((1, 0.5523), (0.5523, 1))
    assert paths(crv2svg.to_svg(doc)) == ["M1 12 C1 11.4477 0.5523 11 0 11"]


def test_dxf_flattens_curves_within_tolerance():
    doc = read([{"name": "a", "items": [{"kind": "polyline", "spans": [QUARTER]}]}])
    coarse = crv2svg.to_dxf(doc, curve_tolerance=0.05).count("VERTEX")
    fine = crv2svg.to_dxf(doc, curve_tolerance=0.0005).count("VERTEX")
    assert 2 < coarse < fine
    span = doc.layers[0].items[0].paths[0].spans[0]
    pts = [span.start[:2]] + flatten_curve(span, 0.0005)
    assert pts[-1] == (0, 1)
    assert all(abs((x * x + y * y) ** 0.5 - 1) < 0.001 for x, y in pts)


def test_groups_are_flattened_including_nested_ones():
    inner = {"kind": "group", "items": [{"kind": "contour", "spans": circle(8, 6, 1)}]}
    group = {"kind": "group", "items": [{"kind": "contour", "spans": square(1, 1, 2)}, inner]}
    doc = read([{"name": "a", "items": [group, {"kind": "contour", "spans": square(5, 5, 1)}]}])
    assert [i.kind for i in doc.layers[0].items] == ["group", "contour"]
    assert len(paths(crv2svg.to_svg(doc))) == 3


def test_bitmaps_are_skipped_and_their_file_path_never_leaves():
    image = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20
    doc = read([{"name": "pics", "items": [{"kind": "bitmap", "image": image}]},
                {"name": "a", "items": [{"kind": "contour", "spans": square(1, 1, 2)}]}])
    assert doc.layers[0].items[0].kind == "picture" and not doc.layers[0].items[0].paths
    svg, dxf = crv2svg.to_svg(doc), crv2svg.to_dxf(doc)
    assert len(paths(svg)) == 1
    assert "someone" not in svg and "someone" not in dxf


def text_item(**kw):
    item = {"kind": "text", "base": [line((10, 5), (16, 5))],
            "lines": [[(4.0, 2.0, [BAR]), (2.0, 1.0, []), (3.0, 1.5, [BAR])]]}
    item.update(kw)
    return item


def test_text_glyphs_sit_along_the_base_line():
    doc = read([{"name": "t", "items": [text_item()]}])
    item = doc.layers[0].items[0]
    assert item.kind == "text" and not doc.warnings
    xs = sorted({round(s.start[0], 6) for p in item.paths for s in p.spans})
    # Glyph frames land at pen + offset: 2 and 7.5. Ink starts at 1, which maps to the base start.
    assert xs == [10.0, 12.0, 15.5, 17.5]
    ys = sorted({round(s.start[1], 6) for p in item.paths for s in p.spans})
    assert ys == [5.0, 7.0]


def test_text_transform_is_applied_after_layout():
    matrix = [2.0, 0.0, 100.0, 0.0, 2.0, -10.0, 0.0, 0.0, 1.0]
    doc = read([{"name": "t", "items": [text_item(matrix=matrix)]}])
    xs = sorted({round(s.start[0], 6) for p in doc.layers[0].items[0].paths for s in p.spans})
    assert xs == [120.0, 124.0, 131.0, 135.0]


def test_text_follows_a_rotated_base_line():
    doc = read([{"name": "t", "items": [text_item(base=[line((0, 0), (0, 6))])]}])
    pts = {(round(s.start[0], 6), round(s.start[1], 6))
           for p in doc.layers[0].items[0].paths for s in p.spans}
    assert (0.0, 0.0) in pts and (-2.0, 0.0) in pts and (0.0, 2.0) in pts


def test_text_under_uneven_scaling_turns_arcs_into_curves():
    glyph = [arc((-1, 1), (1, 1), -1.0), arc((1, 1), (-1, 1), -1.0)]
    matrix = [3.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    item = text_item(lines=[[(2.0, 1.0, [glyph])]], base=[line((0, 0), (2, 0))], matrix=matrix)
    spans = read([{"name": "t", "items": [item]}]).layers[0].items[0].paths[0].spans
    assert spans and all(s.is_curve for s in spans)
    xs = [s.start[0] for s in spans]
    assert min(xs) == pytest.approx(0.0) and max(xs) == pytest.approx(6.0)


def test_text_this_reader_cannot_place_is_left_out_with_a_warning():
    two_lines = text_item(lines=[[(4.0, 2.0, [BAR])], [(4.0, 2.0, [BAR])]])
    bent = text_item(base=[arc((0, 0), (6, 0), 0.5)])
    doc = read([{"name": "t", "items": [two_lines, bent, {"kind": "contour", "spans": square(0, 0, 1)}]}])
    assert [len(i.paths) for i in doc.layers[0].items] == [0, 0, 1]
    assert len(doc.warnings) == 2 and "2 lines" in doc.warnings[0] and "curve" in doc.warnings[1]


def test_dimension_parts_are_drawn():
    parts = [text_item(), {"kind": "contour", "spans": [line((0, 0), (9, 0))]}]
    doc = read([{"name": "Dimensions", "items": [{"kind": "dimension", "parts": parts}]},
                {"name": "a", "items": [{"kind": "contour", "spans": square(0, 0, 1)}]}])
    assert doc.layers[0].items[0].kind == "dimension"
    assert len(doc.layers[0].items[0].paths) == 3
    assert len(doc.layers[1].items) == 1


def test_arc_to_curves_stays_on_the_circle():
    for bulge in (1.0, -1.0, 0.3, 2.5, -4.0):
        span = Span((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), bulge)
        pieces = arc_to_curves(span)
        assert pieces[0].start[:2] == (0.0, 0.0) and pieces[-1].end[:2] == (2.0, 0.0)
        r = span.radius
        h = 2.0 * (1 - bulge * bulge) / (4 * bulge)
        cx, cy = 1.0, h
        for piece in pieces:
            for x, y in flatten_curve(piece, 1e-4):
                assert ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 == pytest.approx(r, rel=1e-3)


def test_truncated_modern_stream_fails_cleanly():
    from crvbuild import build_cfb, build_vectors, build_version
    layers = [{"name": "t", "items": [text_item(), {"kind": "group", "items": [
        {"kind": "contour", "spans": [QUARTER]}]}, {"kind": "bitmap", "image": b"\x89PNG" * 50}]}]
    vectors = build_vectors(layers, modern=True)
    for cut in range(0, len(vectors) - 256, 11):
        data = build_cfb({"VectorData/2dDataV2": vectors[:cut], "VersionData/Version": build_version()})
        with pytest.raises(CrvError):
            crv2svg.read_bytes(data)


def test_mirrored_text_flips_arc_direction():
    glyph = [arc((-1, 0), (1, 0), 0.5), line((1, 0), (-1, 0))]
    matrix = [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    item = text_item(lines=[[(2.0, 1.0, [glyph])]], base=[line((0, 0), (2, 0))], matrix=matrix)
    spans = read([{"name": "t", "items": [item]}]).layers[0].items[0].paths[0].spans
    assert spans[0].bulge == -0.5 and spans[0].start[0] == pytest.approx(0.0)
    assert spans[0].end[0] == pytest.approx(-2.0)
