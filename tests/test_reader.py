import random

import pytest

import crv2svg
from crv2svg import cfb
from crv2svg.errors import CrvError, UnsupportedError
from crvbuild import (arc, build_cfb, build_crv, build_vectors, build_version, circle, line,
                      point, ramp, square)

LAYERS = [
    {"name": "Toolpath Previews", "items": [
        {"kind": "preview", "paths": [square(1, 1, 2), [ramp((0, 0), (1, 1)), point((3, 3))]]},
    ]},
    {"name": "cutout", "color": (255, 0, 0), "items": [
        {"kind": "contour", "spans": square(1, 1, 4), "tabs": 2, "params": [("DXF_Z", 0.0)]},
        {"kind": "contour", "spans": circle(10, 6, 2)},
    ]},
    {"name": "grooves", "color": (0, 255, 0), "items": [
        {"kind": "polyline", "spans": [line((0, 0), (5, 5))]},
        {"kind": "contour", "spans": [arc((0, 0), (2, 0), -0.5), line((2, 0), (3, 4))]},
    ]},
]


def test_reads_layers_geometry_and_metadata():
    doc = crv2svg.read_bytes(build_crv(LAYERS, product="Cut2D Desktop", version="9.012"))
    assert (doc.product, doc.version) == ("Cut2D Desktop", "9.012")
    assert doc.material == (0.0, 0.0, 24.0, 12.0)
    assert doc.preview_gif.startswith(b"GIF89a")
    assert [l.name for l in doc.layers] == ["Toolpath Previews", "cutout", "grooves"]
    assert [l.is_preview for l in doc.layers] == [True, False, False]
    assert doc.layers[1].color == (255, 0, 0)
    assert doc.layers[2].color == (0, 255, 0)

    sq = doc.layers[1].items[0]
    assert sq.kind == "contour" and sq.tabs == 2
    assert [(s.start[:2], s.end[:2]) for s in sq.paths[0].spans] == [
        ((1, 1), (5, 1)), ((5, 1), (5, 5)), ((5, 5), (1, 5)), ((1, 5), (1, 1))]
    circ = doc.layers[1].items[1].paths[0].spans
    assert [s.bulge for s in circ] == [1.0, 1.0]
    assert circ[0].radius == pytest.approx(2.0)

    assert doc.layers[2].items[0].kind == "polyline"
    mixed = doc.layers[2].items[1].paths[0].spans
    assert mixed[0].bulge == -0.5 and mixed[0].is_arc
    assert mixed[1].bulge == 0.0 and not mixed[1].is_arc

    preview = doc.layers[0].items[0]
    assert preview.kind == "preview" and len(preview.paths) == 2
    assert len(preview.paths[1].spans) == 2


def test_objects_after_a_point_span_stay_aligned():
    layers = [{"name": "a", "items": [
        {"kind": "contour", "spans": [point((3, 3))]},
        {"kind": "contour", "spans": square(0, 0, 1)},
    ]}]
    doc = crv2svg.read_bytes(build_crv(layers))
    assert len(doc.layers[0].items[1].paths[0].spans) == 4


def test_many_objects_use_wide_class_tags():
    items = [{"kind": "contour", "spans": [line((i, 0), (i, 1))]} for i in range(17000)]
    doc = crv2svg.read_bytes(build_crv([{"name": "big", "items": items}]))
    assert len(doc.layers[0].items) == 17000
    assert doc.layers[0].items[-1].paths[0].spans[0].start[0] == 16999


def test_unknown_object_reports_its_name_and_keeps_earlier_layers():
    layers = LAYERS + [{"name": "text", "items": [{"kind": "vcCadText", "body": b"\0" * 40}]}]
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(build_crv(layers))
    assert "vcCadText" in str(info.value)
    assert [l.name for l in info.value.partial.layers] == ["Toolpath Previews", "cutout", "grooves"]


def test_unknown_span_type_is_unsupported_not_garbage():
    layers = [{"name": "a", "items": [{"kind": "contour", "spans": square(0, 0, 1), "span_type": 9}]}]
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(build_crv(layers))
    assert "span type 9" in str(info.value)


def test_missing_vector_stream_lists_what_is_there():
    data = build_cfb({"VersionData/Version": build_version(), "VectorData/2dDataV9": b"\0" * 10})
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(data)
    assert "2dDataV9" in str(info.value)


def test_every_truncation_of_the_vector_stream_fails_cleanly():
    vectors = build_vectors(LAYERS)
    version = build_version()
    for cut in range(0, len(vectors) - 256, 7):
        data = build_cfb({"VectorData/2dDataV2": vectors[:cut], "VersionData/Version": version})
        with pytest.raises(CrvError):
            crv2svg.read_bytes(data)


def test_corrupted_bytes_never_escape_as_other_exceptions():
    vectors = build_vectors(LAYERS)
    version = build_version()
    rng = random.Random(1234)
    for _ in range(600):
        damaged = bytearray(vectors)
        for _ in range(rng.randint(1, 4)):
            damaged[rng.randrange(len(damaged))] = rng.randrange(256)
        data = build_cfb({"VectorData/2dDataV2": bytes(damaged), "VersionData/Version": version})
        try:
            doc = crv2svg.read_bytes(data)
        except CrvError:
            continue
        crv2svg.to_svg(doc)
        crv2svg.to_dxf(doc)


def test_huge_counts_are_refused_before_allocating():
    vectors = bytearray(build_vectors([{"name": "a", "items": []}]))
    vectors[8:12] = b"\xff\xff\xff\x7f"
    data = build_cfb({"VectorData/2dDataV2": bytes(vectors), "VersionData/Version": build_version()})
    with pytest.raises(CrvError):
        crv2svg.read_bytes(data)


def test_container_reader_is_what_feeds_the_parser():
    streams = cfb.read_streams(build_crv(LAYERS))
    assert streams["VectorData/2dDataV2"] == build_vectors(LAYERS)


def test_non_finite_coordinates_are_refused():
    for bad in (float("nan"), float("inf"), 1e300):
        layers = [{"name": "a", "items": [{"kind": "contour", "spans": [line((0, 0), (bad, 1))]}]}]
        with pytest.raises(CrvError):
            crv2svg.read_bytes(build_crv(layers))
    layers = [{"name": "a", "items": [{"kind": "contour", "spans": [arc((0, 0), (1, 1), float("nan"))]}]}]
    with pytest.raises(CrvError):
        crv2svg.read_bytes(build_crv(layers))
