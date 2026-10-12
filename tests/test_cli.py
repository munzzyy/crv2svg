import os

import pytest

from crv2svg.cli import main
from crvbuild import build_crv, square

GOOD = [{"name": "cutout", "items": [{"kind": "contour", "spans": square(1, 1, 4)}]}]
BAD = GOOD + [{"name": "text", "items": [{"kind": "vcCadText", "body": b"\0" * 8}]}]


@pytest.fixture
def crv(tmp_path):
    def make(name, layers):
        path = tmp_path / name
        path.write_bytes(build_crv(layers))
        return str(path)
    return make


def test_default_output_sits_next_to_the_input(crv, capsys):
    src = crv("part.crv", GOOD)
    assert main([src]) == 0
    out = src[:-4] + ".svg"
    assert "<path" in open(out).read()
    assert out in capsys.readouterr().out


def test_dxf_by_extension_and_by_flag(crv, tmp_path):
    src = crv("part.crv", GOOD)
    target = str(tmp_path / "x.dxf")
    assert main([src, "-o", target]) == 0
    assert open(target).read().endswith("EOF\n")
    assert main([src, "-f", "dxf"]) == 0
    assert os.path.exists(src[:-4] + ".dxf")


def test_stdout(crv, capsys):
    assert main([crv("part.crv", GOOD), "-o", "-"]) == 0
    assert capsys.readouterr().out.startswith("<?xml")


def test_info(crv, capsys):
    assert main([crv("part.crv", GOOD), "--info"]) == 0
    out = capsys.readouterr().out
    assert "VCarve Pro 8.505" in out and "'cutout'" in out and "24 x 12" in out


def test_unsupported_file_fails_then_partial_saves_what_it_can(crv, capsys):
    src = crv("part.crv", BAD)
    assert main([src]) == 1
    err = capsys.readouterr().err
    assert "vcCadText" in err and "--partial" in err
    assert not os.path.exists(src[:-4] + ".svg")
    assert main([src, "--partial"]) == 2
    assert "<path" in open(src[:-4] + ".svg").read()


def test_not_a_crv_and_missing_file(tmp_path, capsys):
    junk = tmp_path / "junk.crv"
    junk.write_bytes(b"hello")
    assert main([str(junk)]) == 1
    assert main([str(tmp_path / "nope.crv")]) == 1
    err = capsys.readouterr().err
    assert "not a compound file" in err and "nope.crv" in err


def test_one_bad_file_does_not_stop_the_batch(crv, tmp_path):
    good = crv("good.crv", GOOD)
    junk = tmp_path / "junk.crv"
    junk.write_bytes(b"hello")
    assert main([str(junk), good]) == 1
    assert os.path.exists(good[:-4] + ".svg")


def test_unknown_layer_name(crv, capsys):
    assert main([crv("part.crv", GOOD), "--layer", "nope"]) == 1
    assert "cutout" in capsys.readouterr().err


def test_extract_preview(crv, tmp_path):
    target = str(tmp_path / "thumb.gif")
    assert main([crv("part.crv", GOOD), "--extract-preview", target]) == 0
    assert open(target, "rb").read().startswith(b"GIF89a")
