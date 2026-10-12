"""Every object layout seen in real files, from 2010-era releases to version 11."""

import pytest

import crv2svg
from crv2svg.errors import CrvError, UnsupportedError
from crvbuild import (arc, build_cfb, build_crv, build_vectors, build_version, circle, curve, line,
                      point, ramp, square, tabarc)

ERAS = (5, 6, 7, 8, 9, 10)
QUARTER = curve((1, 0), (1, 0.5523), (0.5523, 1), (0, 1))
BAR = [line((-1, 0), (1, 0)), line((1, 0), (1, 2)), line((1, 2), (-1, 2)), line((-1, 2), (-1, 0))]
TEXT = {"kind": "text", "base": [line((10, 5), (16, 5))], "lines": [[(4.0, 2.5, [BAR]), (3.0, 1.0, [BAR])]]}
LAYERS = [
    {"name": "Toolpath Previews", "items": [{"kind": "preview", "paths": [
        square(1, 1, 2), [ramp((0, 0), (1, 1)), tabarc((1, 1), (2, 2), 0.4), point((3, 3))]]}]},
    {"name": "cut", "color": (255, 0, 0), "items": [
        {"kind": "contour", "spans": square(1, 1, 4), "tabs": 2, "params": [("DXF_Z", 0.0)]},
        {"kind": "contour", "spans": circle(10, 6, 2)},
        {"kind": "polyline", "spans": [line((0, 0), (5, 5)), QUARTER]},
        {"kind": "contour", "spans": [point((7, 7))]},
        TEXT,
        {"kind": "contour", "spans": square(20, 1, 1)},
    ]},
]


@pytest.mark.parametrize("base", ERAS)
def test_same_drawing_reads_the_same_in_every_era(base):
    doc = crv2svg.read_bytes(build_crv(LAYERS, base=base))
    assert [l.is_preview for l in doc.layers] == [True, False]
    cut = doc.layers[1].items
    assert [i.kind for i in cut] == ["contour", "contour", "polyline", "contour", "text", "contour"]
    assert cut[0].tabs == 2
    assert [(s.start[:2], s.end[:2]) for s in cut[0].paths[0].spans][0] == ((1, 1), (5, 1))
    assert [s.bulge for s in cut[1].paths[0].spans] == [1.0, 1.0]
    assert cut[2].paths[0].spans[1].control == ((1, 0.5523), (0.5523, 1))
    assert cut[5].paths[0].spans[3].end[:2] == (20, 1)
    assert len(doc.layers[0].items[0].paths[1].spans) == 3
    assert doc.layers[0].items[0].paths[1].spans[1].bulge == 0.4


@pytest.mark.parametrize("base", ERAS)
def test_text_is_placed_only_where_the_layout_is_known(base):
    doc = crv2svg.read_bytes(build_crv(LAYERS, base=base))
    item = doc.layers[1].items[4]
    if base >= 7:
        xs = sorted({round(s.start[0], 6) for p in item.paths for s in p.spans})
        # Frames at 2.5 and 5; ink starts at 1.5 and maps to the base start at x = 10.
        assert xs == [10.0, 12.0, 12.5, 14.5] and not doc.warnings
    else:
        assert item.paths == [] and "before version 9" in doc.warnings[0]


@pytest.mark.parametrize("base", ERAS)
def test_truncation_fails_cleanly_in_every_era(base):
    vectors = build_vectors(LAYERS, base=base)
    for cut in range(0, len(vectors) - 256, 13):
        data = build_cfb({"VectorData/2dDataV2": vectors[:cut], "VersionData/Version": build_version()})
        with pytest.raises(CrvError):
            crv2svg.read_bytes(data)


def test_unknown_span_class_in_old_files_is_named():
    layers = [{"name": "a", "items": [{"kind": "contour", "spans": square(0, 0, 1), "span_type": 9}]}]
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(build_crv(layers, base=5))
    assert "vdMystery" in str(info.value)


def test_unknown_object_version_is_named():
    data = bytearray(build_vectors([{"name": "a", "items": [{"kind": "contour", "spans": square(0, 0, 1)}]}]))
    at = data.find(b"vcCadContour") + len("vcCadContour")
    assert data[at] == 7
    data[at] = 42
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(build_cfb({"VectorData/2dDataV2": bytes(data), "VersionData/Version": build_version()}))
    assert "version 42" in str(info.value)


def test_old_pictures_stop_with_a_plain_message():
    layers = [{"name": "a", "items": [{"kind": "contour", "spans": square(0, 0, 1)}]},
              {"name": "pics", "items": [{"kind": "vcCadModelPreview", "body": b""}]}]
    data = bytearray(build_vectors(layers, base=5))
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(build_cfb({"VectorData/2dDataV2": bytes(data), "VersionData/Version": build_version()}))
    assert info.value.partial is not None and len(info.value.partial.layers) == 1


@pytest.mark.parametrize("base", (5, 6))
def test_old_text_can_be_placed_by_estimate_on_request(base):
    wide = dict(TEXT, base=[line((10, 5), (15.5, 5))])
    data = build_crv([{"name": "t", "items": [wide]}], base=base)
    assert crv2svg.read_bytes(data).layers[0].items[0].paths == []
    doc = crv2svg.read_bytes(data, approximate_text=True)
    xs = sorted({round(s.start[0], 6) for p in doc.layers[0].items[0].paths for s in p.spans})
    # Ink is 4.5 wide on a base line 5.5 long, so it sits half a unit in from each end.
    assert xs == [10.5, 12.5, 13.0, 15.0]
    assert "by estimate" in doc.warnings[0]
