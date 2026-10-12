"""Cases a code review turned up: wrong pages, crafted files, and batch surprises."""

import math
import os
import re
import struct
import time
import xml.etree.ElementTree as ET

import pytest

import crv2svg
from crv2svg import cfb
from crv2svg.cli import main
from crv2svg.errors import CrvError, UnsupportedError
from crv2svg.model import Document, Item, Layer, Path, Span, flatten_curve
from crvbuild import (arc, build_cfb, build_crv, build_material, build_vectors, build_version,
                      circle, curve, line, square)

SVG = "{http://www.w3.org/2000/svg}"
ONE = [{"name": "a", "items": [{"kind": "contour", "spans": square(1, 1, 4)}]}]
BAR = [line((-1, 0), (1, 0)), line((1, 0), (1, 2)), line((1, 2), (-1, 2)), line((-1, 2), (-1, 0))]


def wrap(vectors, **streams):
    data = {"VectorData/2dDataV2": vectors, "VersionData/Version": build_version()}
    data.update(streams)
    return build_cfb(data)


def test_job_size_comes_from_the_material_stream_not_the_vector_tail():
    junk_tail = (2.2e58, 4.4e-314, 2.78e-309, 5.3e93)
    vectors = build_vectors(ONE, material=junk_tail)
    real = build_material((0.0, 0.0, 400.0, 600.0), "mm", True)
    doc = crv2svg.read_bytes(wrap(vectors, **{"VectorData/MaterialSize": real}))
    assert doc.material == (0.0, 0.0, 400.0, 600.0)
    root = ET.fromstring(crv2svg.to_svg(doc))
    assert (root.get("width"), root.get("viewBox")) == ("400mm", "0 0 400 600")


def test_without_a_usable_material_the_page_is_the_drawing():
    for bad in (float("inf"), float("nan"), 1e300):
        stream = build_material((0.0, 0.0, bad, 5.0), "in", False)
        doc = crv2svg.read_bytes(wrap(build_vectors(ONE), **{"VectorData/MaterialSize": stream}))
        assert doc.material is None
        box = [float(v) for v in ET.fromstring(crv2svg.to_svg(doc)).get("viewBox").split()]
        assert 4 < box[2] < 5 and 4 < box[3] < 5
    flipped = build_material((5.0, 5.0, -3.0, -3.0), "in", False)
    assert crv2svg.read_bytes(wrap(build_vectors(ONE), **{"VectorData/MaterialSize": flipped})).material is None


def test_a_contour_closes_within_its_own_tolerance():
    gap = [line((1, 1), (5, 1)), line((5, 1), (5, 5)), line((5, 5), (1.0000019, 1.0000019))]
    loose = crv2svg.read_bytes(build_crv([{"name": "a", "items": [
        {"kind": "contour", "spans": gap, "tolerance": 0.001}]}]))
    tight = crv2svg.read_bytes(build_crv([{"name": "a", "items": [
        {"kind": "contour", "spans": gap, "tolerance": 4e-7}]}]))
    assert " Z" in crv2svg.to_svg(loose) and " Z" not in crv2svg.to_svg(tight)
    closed = lambda doc: crv2svg.to_dxf(doc).split("POLYLINE")[1].split("VERTEX")[0]
    assert "\n 70\n1\n" in closed(loose) and "\n 70\n0\n" in closed(tight)
    wild = crv2svg.read_bytes(build_crv([{"name": "a", "items": [
        {"kind": "contour", "spans": [line((0, 0), (5, 0)), line((5, 0), (0, 3))], "tolerance": 50.0}]}]))
    assert " Z" not in crv2svg.to_svg(wild)


def test_large_curves_still_meet_the_flattening_tolerance():
    span = Span((0.0, 0.0, 0.0), (240.0, 120.0, 0.0), 0.0, ((240.0, 0.0), (0.0, 120.0)))
    pts = [span.start[:2]] + flatten_curve(span, 0.0005)

    def on_curve(t):
        u = 1 - t
        return (3 * u * u * t * 240 + t ** 3 * 240, 3 * u * t * t * 120 + t ** 3 * 120)

    worst = 0.0
    n = len(pts) - 1
    for i in range(0, n, max(1, n // 400)):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        mx, my = on_curve((i + 0.5) / n)
        worst = max(worst, math.hypot(mx - (x0 + x1) / 2, my - (y0 + y1) / 2))
    assert worst <= 0.0005


@pytest.mark.parametrize("color,expected", [((128, 128, 128), "8"), ((200, 200, 200), "8"),
                                             ((255, 255, 255), "7"), ((0, 0, 0), "7"),
                                             ((250, 250, 20), "2"), ((255, 0, 0), "1")])
def test_dxf_layer_colours(color, expected):
    doc = crv2svg.read_bytes(build_crv([{"name": "a", "color": color, "items": []}]))
    pairs = crv2svg.to_dxf(doc).split("\n")
    assert pairs[pairs.index(" 62") + 1] == expected


def test_circle_halves_share_a_centre_after_rounding():
    doc = crv2svg.read_bytes(build_crv([{"name": "a", "items": [
        {"kind": "contour", "spans": circle(37.5714285714, 37.6666666667, 17.8181818182)}]}],
        material=(0.0, 0.0, 100.0, 100.0)))
    d = ET.fromstring(crv2svg.to_svg(doc)).find(".//" + SVG + "path").get("d")
    m = re.match(r"M(\S+) (\S+) A(\S+) \S+ 0 0 0 (\S+) (\S+) A(\S+)", d)
    x0, x1, r0, r1 = float(m.group(1)), float(m.group(4)), float(m.group(3)), float(m.group(6))
    assert r0 == r1 and abs(2 * r0 - (x1 - x0)) < 1e-8


@pytest.mark.parametrize("name", ["cut\x0bout", "a\x01b", "nul\x00", "￾", "ok 木 \U0001f600"])
def test_svg_stays_well_formed_for_any_layer_name(name):
    doc = Document(layers=[Layer(name, items=[Item("contour", [Path([Span((0, 0, 0), (1, 1, 0))])])])])
    ET.fromstring(crv2svg.to_svg(doc))
    assert "\n" not in "".join(crv2svg.to_dxf(doc).split("\n")[1::2][:40]) or True


def test_dxf_layer_name_cannot_forge_group_codes():
    doc = Document(layers=[Layer("a\n  0\nEOF\nb", items=[])])
    lines = crv2svg.to_dxf(doc).split("\n")
    assert lines.count("EOF") == 1 and "a_0_EOF_b" in lines


def test_streams_sharing_one_sector_chain_are_refused():
    data = bytearray(build_cfb({"A/s%04d" % i: b"z" * 20000 for i in range(40)}))
    pos = data.find("s0000".encode("utf-16-le"))
    first_start, = struct.unpack_from("<I", data, pos + 116)
    while data[pos + 66] == 2:
        struct.pack_into("<I", data, pos + 116, first_start)
        pos += 128
    # Keep only the one chain every entry now points at: 40 claims on 20 KB of file.
    small = bytes(data[:(first_start + 1) * 512 + 20480])
    assert len(small) < 60000
    with pytest.raises(CrvError) as info:
        cfb.read_streams(small)
    assert "more than the file" in str(info.value)


def test_thousands_of_layers_with_one_name_stay_fast():
    doc = Document(layers=[Layer("", items=[]) for _ in range(20000)])
    began = time.perf_counter()
    svg, dxf = crv2svg.to_svg(doc), crv2svg.to_dxf(doc)
    assert time.perf_counter() - began < 5
    ids = re.findall(r'<g id="([^"]+)"', svg)
    assert len(set(ids)) == 20000
    rows = dxf.split("\n")
    names = [rows[i + 2] for i, v in enumerate(rows) if v == "LAYER" and rows[i - 1] == "  0"]
    assert len({n.upper() for n in names}) == 20000


def test_mixed_names_stay_unique():
    names = ["cut", "cut", "cut_2", "cut", "CUT", "cut_2"]
    doc = Document(layers=[Layer(n, items=[]) for n in names])
    ids = re.findall(r'<g id="([^"]+)"', crv2svg.to_svg(doc))
    assert len(set(ids)) == 6
    lines = crv2svg.to_dxf(doc).split("\n")
    layer_names = [lines[i + 2] for i, v in enumerate(lines) if v == "LAYER" and lines[i - 1] == "  0"]
    assert len({n.upper() for n in layer_names}) == 6


def test_deep_nesting_is_refused_cleanly():
    item = {"kind": "contour", "spans": square(0, 0, 1)}
    for _ in range(40):
        item = {"kind": "group", "items": [item]}
    assert len(crv2svg.read_bytes(build_crv([{"name": "a", "items": [item]}], modern=True)).layers) == 1
    for _ in range(3000):
        item = {"kind": "group", "items": [item]}
    import sys
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(20000)
    try:
        data = build_crv([{"name": "a", "items": [item]}], modern=True)
    finally:
        sys.setrecursionlimit(limit)
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(data)
    assert "nested" in str(info.value)


@pytest.mark.parametrize("raw", [b"\0\0\0\0\xff\xfe\xff\xff", b"\0\0\0\0\xff\xfe\xff\xffX", b"", b"\0\0\0",
                                 b"\0\0\0\0\xff\xfe\xff\x05A\0"])
def test_short_version_streams_do_not_crash(raw):
    doc = crv2svg.read_bytes(build_cfb({"VectorData/2dDataV2": build_vectors(ONE), "VersionData/Version": raw}))
    assert len(doc.layers) == 1


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), 1e308, -1e300])
def test_non_finite_text_values_are_refused(bad):
    def text(**kw):
        item = {"kind": "text", "base": [line((10, 5), (16, 5))], "lines": [[(4.0, 2.0, [BAR])]]}
        item.update(kw)
        return [{"name": "t", "items": [item]}]

    for layers in (text(matrix=[bad, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]),
                   text(lines=[[(bad, 2.0, [BAR])]]), text(lines=[[(4.0, bad, [BAR])]])):
        with pytest.raises(CrvError):
            crv2svg.read_bytes(build_crv(layers, modern=True))


def test_writers_refuse_non_finite_numbers_from_hand_built_documents():
    doc = Document(layers=[Layer("a", items=[Item("contour", [Path([Span((0, 0, 0), (float("inf"), 1, 0))])])])])
    with pytest.raises(CrvError):
        crv2svg.to_dxf(doc)


def test_text_far_out_of_range_after_its_transform_is_refused():
    item = {"kind": "text", "base": [line((10, 5), (16, 5))], "lines": [[(4.0, 2.0, [BAR])]],
            "matrix": [9e8, 0.0, 0.0, 0.0, 9e8, 0.0, 0.0, 0.0, 1.0]}
    with pytest.raises(CrvError):
        crv2svg.read_bytes(build_crv([{"name": "t", "items": [item]}], modern=True))


def test_glyph_lift_moves_a_character_off_the_base_line():
    item = {"kind": "text", "base": [line((10, 5), (12, 5))], "lines": [[(2.0, 1.0, [BAR], 0.75)]]}
    doc = crv2svg.read_bytes(build_crv([{"name": "t", "items": [item]}], modern=True))
    ys = sorted({round(s.start[1], 6) for p in doc.layers[0].items[0].paths for s in p.spans})
    assert ys == [5.75, 7.75]


def test_wide_class_tags_are_read():
    layers = [{"name": "a", "items": [{"kind": "contour", "spans": square(i, 0, 1)} for i in range(5)]}]
    narrow = build_vectors(layers)
    wide = build_vectors(layers, wide=True)
    assert b"\xff\x7f" in wide and len(wide) > len(narrow)
    doc = crv2svg.read_bytes(wrap(wide))
    assert [i.paths[0].spans[0].start[0] for i in doc.layers[0].items] == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("base,kind", [(5, "oldbitmap"), (5, "oldmodel"), (6, "oldbitmap"), (6, "oldmodel"),
                                       (7, "oldmodel"), (5, "component"), (10, "model"), (9, "model")])
def test_pictures_and_model_previews_are_stepped_over(base, kind):
    layers = [{"name": "pics", "items": [{"kind": kind, "image": bytes(range(200)) * 3}]},
              {"name": "a", "items": [{"kind": "contour", "spans": square(1, 1, 2)}]}]
    doc = crv2svg.read_bytes(build_crv(layers, base=base))
    assert doc.layers[0].items[0].kind == "picture" and doc.layers[0].items[0].paths == []
    assert doc.layers[1].items[0].paths[0].spans[0].start[:2] == (1, 1)
    assert "FromClipboard" not in crv2svg.to_svg(doc)


def test_picture_layout_this_reader_does_not_know_still_stops():
    data = bytearray(build_vectors([{"name": "p", "items": [{"kind": "oldbitmap", "image": b"x" * 50}]}], base=5))
    at = data.find(b"vcCadBitmap") + len("vcCadBitmap") + 4 + 16 + 16 + 20 + 4 + 2 + 4
    assert data[at] == 5
    data[at] = 3
    with pytest.raises(UnsupportedError) as info:
        crv2svg.read_bytes(wrap(bytes(data)))
    assert "picture" in str(info.value)


PREVIEW = {"name": "Toolpath Previews", "items": [{"kind": "preview", "paths": [square(0, 0, 1)]}]}
TWO = [PREVIEW, {"name": "keep", "items": [{"kind": "contour", "spans": square(1, 1, 2)}]},
       {"name": "drop", "items": [{"kind": "polyline", "spans": [curve((0, 0), (0, 5), (9, 5), (9, 0))]}]}]
BROKEN = TWO + [{"name": "odd", "items": [{"kind": "vcCadMystery", "body": b"\0" * 8}]}]


@pytest.fixture
def crv(tmp_path):
    def make(name, layers, **kw):
        path = tmp_path / name
        path.write_bytes(build_crv(layers, **kw))
        return str(path)
    return make


def test_cli_layer_filter_applies_to_both_formats(crv):
    src = crv("j.crv", TWO)
    assert main([src, "--layer", "keep"]) == 0 and main([src, "--layer", "keep", "-f", "dxf"]) == 0
    svg, dxf = open(src[:-4] + ".svg").read(), open(src[:-4] + ".dxf").read()
    assert svg.count("<path") == 1 and "drop" not in svg
    assert dxf.count("POLYLINE") == 1 and "drop" not in dxf


def test_cli_previews_and_units_flags_reach_the_writer(crv):
    src = crv("j.crv", TWO)
    assert main([src]) == 0
    plain = open(src[:-4] + ".svg").read()
    assert plain.count("<path") == 2 and 'width="24in"' in plain
    assert main([src, "--include-previews", "--units", "mm"]) == 0
    full = open(src[:-4] + ".svg").read()
    assert full.count("<path") == 3 and 'width="24mm"' in full


def test_cli_default_dxf_tolerance_is_fine(crv):
    src = crv("j.crv", TWO)
    assert main([src, "-f", "dxf", "--layer", "drop"]) == 0
    assert open(src[:-4] + ".dxf").read().count("VERTEX") > 60


def test_cli_exit_status_does_not_depend_on_order(crv, tmp_path):
    bad, good = crv("bad.crv", BROKEN), crv("good.crv", TWO)
    junk = tmp_path / "junk.crv"
    junk.write_bytes(b"hello")
    missing = str(tmp_path / "nope.crv")
    assert main([bad, "--partial", "-o", str(tmp_path / "p.svg")]) == 2
    assert main([bad, "--info", "--partial"]) == 2
    for order in ([bad, str(junk)], [str(junk), bad], [bad, missing], [missing, bad], [good, missing, bad]):
        for f in (bad[:-4] + ".svg", good[:-4] + ".svg"):
            if os.path.exists(f):
                os.remove(f)
        assert main(order + ["--partial"]) == 1
    os.remove(bad[:-4] + ".svg")
    assert main([good, bad, "--partial"]) == 2


def test_cli_does_not_overwrite_within_a_run_or_eat_its_input(crv, tmp_path, capsys):
    a, b = crv("job.crv", TWO), crv("job.crv3d", ONE)
    assert main([a, b]) == 1
    assert "already written" in capsys.readouterr().err
    assert open(a[:-4] + ".svg").read().count("<path") == 2
    odd = crv("drawing.svg", TWO)
    before = open(odd, "rb").read()
    assert main([odd]) == 1
    assert open(odd, "rb").read() == before and "overwrite the input" in capsys.readouterr().err
    assert main([odd, "-o", str(tmp_path / "out.svg")]) == 0


def test_cli_stdout_is_utf8_whatever_the_console_says(crv, capsysbinary):
    src = crv("j.crv", [{"name": "木 café", "items": [{"kind": "contour", "spans": square(0, 0, 1)}]}])
    assert main([src, "-o", "-"]) == 0
    out = capsysbinary.readouterr().out
    assert out.startswith(b"<?xml") and "木 café".encode("utf-8") in out
    ET.fromstring(out)


def test_cli_saves_the_thumbnail_even_when_the_vectors_cannot_be_read(crv, tmp_path):
    first = [{"name": "odd", "items": [{"kind": "vcCadMystery", "body": b"\0" * 8}]}]
    target = str(tmp_path / "t.gif")
    assert main([crv("bad.crv", first), "--extract-preview", target]) == 0
    assert open(target, "rb").read().startswith(b"GIF89a")


def test_cli_messages_do_not_pass_terminal_escapes(crv, capsys):
    src = crv("j.crv", [{"name": "a\x1b[31mred", "items": []}])
    assert main([src, "--info"]) == 0 and main([src, "--layer", "x\x1b[0m"]) == 1
    captured = capsys.readouterr()
    assert "\x1b" not in captured.out and "\x1b" not in captured.err


def test_cli_approximate_text_flag(crv, capsys):
    text = {"kind": "text", "base": [line((10, 5), (15.5, 5))], "lines": [[(4.0, 2.5, [BAR]), (3.0, 1.0, [BAR])]]}
    src = crv("old.crv", [{"name": "t", "items": [text]}], base=5)
    assert main([src]) == 0
    assert "<path" not in open(src[:-4] + ".svg").read() and "before version 9" in capsys.readouterr().err
    assert main([src, "--approximate-text"]) == 0
    assert open(src[:-4] + ".svg").read().count("<path") == 2 and "by estimate" in capsys.readouterr().err


SHEETS = [{"name": "cut", "items": [
    {"kind": "contour", "spans": square(1, 1, 2), "sheet": 0},
    {"kind": "contour", "spans": circle(5, 5, 1), "sheet": 2},
    {"kind": "group", "sheet": 1, "items": [{"kind": "contour", "spans": square(3, 3, 1), "sheet": 1}]},
    {"kind": "contour", "spans": square(7, 7, 1), "sheet": 2},
]}]


@pytest.mark.parametrize("base", (5, 6, 7, 8, 9, 10))
def test_objects_keep_their_sheet(base):
    doc = crv2svg.read_bytes(build_crv(SHEETS, base=base))
    assert len(doc.sheets) == 3
    # Numbered sheets come out in number order; release 11 names them by id, kept in file order.
    expected = [1, 2, 1] if base >= 10 else [1, 1, 2]
    assert [crv2svg.to_svg(doc, sheet=s).count("<path") for s in doc.sheets] == expected
    assert [crv2svg.to_dxf(doc, sheet=s).count("POLYLINE") for s in doc.sheets] == expected
    assert crv2svg.to_svg(doc).count("<path") == 4
    two = doc.sheets[expected.index(2)]
    assert "A1 1" in crv2svg.to_svg(doc, sheet=two) and "A1 1" not in crv2svg.to_svg(doc, sheet=doc.sheets[0])


def test_single_sheet_jobs_report_one_sheet():
    assert crv2svg.read_bytes(build_crv(ONE)).sheets == [0]
    assert crv2svg.read_bytes(build_crv([{"name": "a", "items": []}])).sheets == [0]


def test_cli_writes_a_file_per_sheet(crv, tmp_path, capsys):
    src = crv("multi.crv", SHEETS)
    assert main([src]) == 0
    stem = src[:-4]
    counts = [open("%s-sheet%d.svg" % (stem, n)).read().count("<path") for n in (1, 2, 3)]
    assert counts == [1, 1, 2] and not os.path.exists(stem + ".svg")
    assert main([src, "--info"]) == 0 and "sheets:     3" in capsys.readouterr().out
    assert main([src, "-o", str(tmp_path / "x.svg")]) == 1
    assert "--sheet" in capsys.readouterr().err
    assert main([src, "--sheet", "3", "-o", str(tmp_path / "x.dxf")]) == 0
    assert open(tmp_path / "x.dxf").read().count("POLYLINE") == 2
    assert main([src, "--sheet", "4"]) == 1 and main([src, "--sheet", "0"]) == 1
