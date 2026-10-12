"""Runs against real project files when CRV2SVG_SAMPLES points at a folder of them."""

import glob
import os
import xml.etree.ElementTree as ET

import pytest

import crv2svg

ROOT = os.environ.get("CRV2SVG_SAMPLES")
FILES = sorted(glob.glob(os.path.join(ROOT, "**", "*.crv*"), recursive=True)) if ROOT else []

pytestmark = pytest.mark.skipif(not FILES, reason="set CRV2SVG_SAMPLES to a folder of .crv files")


@pytest.mark.parametrize("path", FILES)
def test_real_file_converts(path):
    try:
        doc = crv2svg.read_file(path)
    except crv2svg.UnsupportedError as exc:
        pytest.skip(str(exc))
    assert doc.layers
    ET.fromstring(crv2svg.to_svg(doc))
    assert crv2svg.to_dxf(doc).endswith("EOF\n")
