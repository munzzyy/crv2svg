"""The browser engine (web/crv2svg.js) must produce the same bytes as the Python package."""

import glob
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import sys

import pytest

import crv2svg
from crv2svg.errors import CrvError, UnsupportedError
import crvbuild
from crvbuild import (arc, build_cfb, build_crv, build_vectors, build_version, circle, curve, line,
                      point, ramp, square, tabarc)

NODE = shutil.which("node")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "web", "crv2svg.js")
SAMPLES = os.environ.get("CRV2SVG_SAMPLES")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = r"""
const fs = require("fs");
const crypto = require("crypto");
const crv = require(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const dump = process.argv[4] || undefined;
const approximate = process.argv[5] === "approx";
const VARIANTS = [
  {},
  { includePreviews: true, units: "mm" },
  { curveTolerance: 0.2, firstLayerOnly: true },
];
const sha = (s) => crypto.createHash("sha256").update(s, "utf8").digest("hex");
const bits = (v) => { const d = new DataView(new ArrayBuffer(8)); d.setFloat64(0, v); return d.getBigUint64(0).toString(16); };

function meta(doc) {
  return {
    product: doc.product, version: doc.version, units: doc.units,
    material: doc.material && doc.material.map(bits),
    preview: doc.previewGif.length,
    warnings: crv.warningLines(doc),
    sheets: doc.sheets,
    layers: doc.layers.map((l) => [l.name, l.color, l.isPreview, l.items.length,
      crv.layerPaths(l).reduce((n, p) => n + p.spans.length, 0)]),
  };
}

function outs(doc, wantText) {
  const variants = VARIANTS.map((v) => {
    const o = { includePreviews: !!v.includePreviews, units: v.units, curveTolerance: v.curveTolerance };
    if (v.firstLayerOnly) o.layers = doc.layers.length ? [doc.layers[0].name] : [];
    return o;
  });
  for (const sheet of doc.sheets) variants.push({ sheet });
  return variants.map((o) => {
    try {
      const svg = crv.toSvg(doc, o);
      const dxf = crv.toDxf(doc, o);
      return wantText ? { svg, dxf } : { svg: [sha(svg), Buffer.byteLength(svg)], dxf: [sha(dxf), Buffer.byteLength(dxf)] };
    } catch (e) {
      return { crash: e.name + ": " + e.message };
    }
  });
}

function run(c, wantText) {
  let data;
  try {
    data = new Uint8Array(fs.readFileSync(c.path));
  } catch (e) {
    return { crash: "read: " + e.message };
  }
  try {
    const doc = crv.readBytes(data, approximate);
    return { ok: true, meta: meta(doc), outs: outs(doc, wantText) };
  } catch (e) {
    if (!(e instanceof crv.CrvError)) return { crash: e.name + ": " + e.message };
    const r = { ok: false, cls: e instanceof crv.UnsupportedError ? "UnsupportedError" : "CrvError", msg: e.message };
    r.partial = e.partial ? { meta: meta(e.partial), outs: outs(e.partial, wantText) } : null;
    return r;
  }
}

const result = {};
for (const c of cases) {
  if (dump === undefined) result[c.id] = run(c, false);
  else if (c.id === dump) result[c.id] = run(c, true);
}
process.stdout.write(JSON.stringify(result));
"""


# ------------------------------------------------------------------ python side

def _sha(text):
    data = text.encode("utf-8")
    return [hashlib.sha256(data).hexdigest(), len(data)]


def _bits(v):
    return "%x" % struct.unpack(">Q", struct.pack(">d", v))[0]


def _meta(doc):
    counts = {}
    for w in doc.warnings:
        counts[w] = counts.get(w, 0) + 1
    return {
        "product": doc.product, "version": doc.version, "units": doc.units,
        "material": None if doc.material is None else [_bits(v) for v in doc.material],
        "preview": len(doc.preview_gif),
        "warnings": ["%s (x%d)" % (w, counts[w]) for w in sorted(counts)],
        "sheets": list(doc.sheets),
        "layers": [[l.name, list(l.color), l.is_preview, len(l.items),
                    sum(len(p.spans) for p in l.paths())] for l in doc.layers],
    }


def _outs(doc, want_text=False):
    out = []
    variants = [{}, {"include_previews": True, "units": "mm"},
                {"curve_tolerance": 0.2, "first_layer_only": True}]
    variants += [{"sheet": sheet} for sheet in doc.sheets]
    for v in variants:
        layers = None
        if v.get("first_layer_only"):
            layers = {doc.layers[0].name} if doc.layers else set()
        try:
            svg = crv2svg.to_svg(doc, units=v.get("units"), sheet=v.get("sheet"),
                                 include_previews=v.get("include_previews", False), layers=layers)
            dxf = crv2svg.to_dxf(doc, include_previews=v.get("include_previews", False),
                                 layers=layers, curve_tolerance=v.get("curve_tolerance"),
                                 sheet=v.get("sheet"))
        except Exception as exc:
            out.append({"crash": "%s: %s" % (type(exc).__name__, exc)})
            continue
        out.append({"svg": svg, "dxf": dxf} if want_text else {"svg": _sha(svg), "dxf": _sha(dxf)})
    return out


def python_result(data, want_text=False, approximate=False):
    try:
        doc = crv2svg.read_bytes(data, approximate)
    except UnsupportedError as exc:
        partial = exc.partial
        return {"ok": False, "cls": "UnsupportedError", "msg": str(exc),
                "partial": None if partial is None else
                {"meta": _meta(partial), "outs": _outs(partial, want_text)}}
    except CrvError as exc:
        return {"ok": False, "cls": "CrvError", "msg": str(exc), "partial": None}
    except Exception as exc:
        return {"crash": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": True, "meta": _meta(doc), "outs": _outs(doc, want_text)}


# ------------------------------------------------------------------- the cases

QUARTER = curve((1, 0), (1, 0.5523), (0.5523, 1), (0, 1))
WIDE = curve((0, 0), (40, 90), (60, -90), (100, 0))
BAR = [line((-1, 0), (1, 0)), line((1, 0), (1, 2)), line((1, 2), (-1, 2)), line((-1, 2), (-1, 0))]
BOWL = [arc((-1, 1), (1, 1), -1.0), arc((1, 1), (-1, 1), -1.0)]
SWEEPS = [arc((0, 0), (2, 0), 0.3), arc((2, 0), (4, 1), -2.5), arc((4, 1), (5, 3), 0.77),
          arc((5, 3), (1, 3), 4.0), arc((1, 3), (0, 0.5), -0.05)]
LAYERS = [
    {"name": "Toolpath Previews", "items": [{"kind": "preview", "paths": [
        square(1, 1, 2), [ramp((0, 0), (1, 1)), tabarc((1, 1), (2, 2), 0.4), point((3, 3))]]}]},
    {"name": "cut", "color": (255, 0, 0), "items": [
        {"kind": "contour", "spans": square(1, 1, 4), "tabs": 2, "params": [("DXF_Z", 0.0)]},
        {"kind": "contour", "spans": circle(10, 6, 2)},
        {"kind": "polyline", "spans": [line((0, 0), (5, 5)), QUARTER]},
        {"kind": "contour", "spans": [point((7, 7))]},
        {"kind": "text", "base": [line((10, 5), (16, 5))], "lines": [[(4.0, 2.5, [BAR]), (3.0, 1.0, [BAR])]]},
        {"kind": "contour", "spans": square(20, 1, 1)},
    ]},
]


def text_item(**kw):
    item = {"kind": "text", "base": [line((10, 5), (16, 5))],
            "lines": [[(4.0, 2.0, [BAR]), (2.0, 1.0, []), (3.0, 1.5, [BAR])]]}
    item.update(kw)
    return item


def rot(deg, sx=1.0, sy=1.0, tx=0.0, ty=0.0):
    import math
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [c * sx, -s * sy, tx, s * sx, c * sy, ty, 0.0, 0.0, 1.0]


def lay(name, items, color=(0, 0, 0)):
    return {"name": name, "color": color, "items": items}


def contour(spans, **kw):
    return dict(kind="contour", spans=spans, **kw)


def _string(self, text, narrow={}):
    if text in narrow:
        raw = narrow[text]
        self.u8(len(raw))
        self.out += raw
        return
    raw = text.encode("utf-16-le", "surrogatepass")
    n = len(raw) // 2
    self.out += b"\xff\xfe\xff"
    if n < 255:
        self.u8(n)
    else:
        self.u8(0xFF)
        self.u16(n)
    self.out += raw


NARROW = {"café": "caf\xe9".encode("cp1252"), "€™": b"\x80\x99", "bad\x81": b"bad\x81"}
_string.__defaults__ = (NARROW,)


def _nest(depth):
    item = contour(square(0, 0, 1))
    for _ in range(depth):
        item = {"kind": "group", "items": [item]}
    return item


def synthetic_cases():
    """(id, bytes). Built with the string writer widened to real UTF-16 so odd names work."""
    original, limit = crvbuild.Writer.string, sys.getrecursionlimit()
    crvbuild.Writer.string = _string
    sys.setrecursionlimit(20000)
    try:
        return _synthetic_cases()
    finally:
        crvbuild.Writer.string = original
        sys.setrecursionlimit(limit)


def _synthetic_cases():
    cases = []

    def add(name, data):
        cases.append((name, data))

    for base in (5, 6, 7, 8, 9, 10):
        add("era-%d" % base, build_crv(LAYERS, base=base))
        add("era-%d-mm" % base, build_crv(LAYERS, base=base, units="mm", material=(-10.0, -5.0, 60.0, 30.0)))
    add("modern-inch", build_crv(LAYERS, modern=True))
    add("modern-no-units", build_crv(LAYERS, modern=True, units=None))
    add("no-material", build_crv(LAYERS, material=None))
    add("zero-material", build_crv(LAYERS, material=(0.0, 0.0, 0.0, 0.0)))
    add("product-strings", build_crv(LAYERS, product="Aspire", version="11.5  "))
    add("empty-version-product", build_crv(LAYERS, product="", version=""))

    add("arcs", build_crv([lay("arcs", [contour(SWEEPS), contour(circle(8, 6, 3)),
                                        contour([arc((6, 6), (6.5, 6), 1.0), arc((6.5, 6), (6, 6), 1.0)])])]))
    add("near-straight-arcs", build_crv([lay("n", [contour([
        arc((0, 0), (4, 0), 1e-10), arc((4, 0), (4, 4), 1e-9), arc((4, 4), (0, 4), 1.0000001e-9),
        arc((0, 4), (0, 0), -2e-9), arc((1, 1), (1, 1), 0.7), arc((2, 2), (2.0000001, 2), 0.01)])])]))
    add("arcs-large-and-small", build_crv([lay("a", [contour([
        arc((0, 0), (1e-7, 0), 0.9), arc((1e-7, 0), (100000.0, 3.0), 0.001),
        arc((100000.0, 3.0), (0, 0), -999999.0)])])]))
    add("beziers", build_crv([lay("b", [contour([QUARTER]), contour([WIDE]),
                                        contour([curve((0, 0), (0, 0), (0, 0), (0, 0))]),
                                        contour([curve((0, 0), (1, 0), (2, 0), (3, 0))])])], modern=True))
    add("groups", build_crv([lay("g", [
        {"kind": "group", "items": [contour(square(1, 1, 2)), {"kind": "group", "items": [contour(circle(8, 6, 1))]}]},
        contour(square(5, 5, 1))])]))
    add("tabs-ramps", build_crv([lay("t", [contour([ramp((0, 0), (3, 1)), tabarc((3, 1), (5, 5), -0.3),
                                                    line((5, 5), (0, 0))], tabs=3)])]))

    add("text-plain", build_crv([lay("t", [text_item()])], modern=True))
    add("text-rotated", build_crv([lay("t", [text_item(matrix=rot(33.0, tx=5.0, ty=-1.0))])], modern=True))
    add("text-base-diagonal", build_crv([lay("t", [text_item(base=[line((3, 2), (9, 7))])])], modern=True))
    add("text-mirrored", build_crv([lay("t", [
        text_item(lines=[[(2.0, 1.0, [[arc((-1, 0), (1, 0), 0.5), line((1, 0), (-1, 0))]])]],
                  base=[line((0, 0), (2, 0))], matrix=[-1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0])])], modern=True))
    add("text-mirrored-rotated", build_crv([lay("t", [text_item(
        lines=[[(2.0, 1.0, [BOWL]), (2.0, 0.5, [BAR])]], base=[line((0, 0), (4, 0))],
        matrix=[0.6, 0.8, 3.0, 0.8, -0.6, 4.0, 0, 0, 1.0])])], modern=True))
    for i, matrix in enumerate([
            [3.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            [1.0, 0.0, 2.0, 0.0, 0.37, 1.0, 0.0, 0.0, 1.0],
            rot(21.0, sx=2.3, sy=0.7, tx=1.0),
            [1.0, 0.4, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            [-2.0, 0.0, 9.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            [0.00123, 0.0, 0.0, 0.0, 7.7, 0.0, 0.0, 0.0, 1.0]]):
        glyphs = [[(2.0, 1.0, [BOWL]), (2.5, 0.25, [SWEEPS]), (1.5, 0.0, [circle(0, 1, 1) + BAR])]]
        add("text-uneven-%d" % i, build_crv([lay("t", [text_item(
            lines=glyphs, base=[line((1, 1), (7, 2.5))], matrix=matrix)])], modern=True))
    add("text-unplaceable", build_crv([lay("t", [
        text_item(lines=[[(4.0, 2.0, [BAR])], [(4.0, 2.0, [BAR])]]),
        text_item(base=[arc((0, 0), (6, 0), 0.5)]),
        text_item(base=[line((2, 2), (2, 2))]),
        contour(square(0, 0, 1))])], modern=True))
    add("text-empty-glyphs", build_crv([lay("t", [text_item(lines=[[(1.0, 0.0, [])]])])], modern=True))
    add("text-old-release", build_crv([lay("t", [text_item()])], base=6))
    add("dimension", build_crv([lay("Dimensions", [{"kind": "dimension", "parts": [
        text_item(), contour([line((0, 0), (9, 0))])]}]), lay("a", [contour(square(0, 0, 1))])], modern=True))
    image = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20
    add("picture", build_crv([lay("pics", [{"kind": "bitmap", "image": image}]),
                              lay("a", [contour(square(1, 1, 2))])], modern=True))
    add("old-picture", build_crv([lay("a", [contour(square(0, 0, 1))]),
                                  lay("pics", [{"kind": "vcCadModelPreview", "body": b""}])], base=5))

    add("outside-material", build_crv([lay("o", [contour(square(-3, -2, 40)), contour(circle(30, 30, 5))])]))
    add("outside-material-mm", build_crv([lay("o", [contour(square(100, 100, 17.3))])], units="mm"))
    add("inside-slack", build_crv([lay("o", [contour(square(0, 0, 24.00001))])]))
    add("only-previews", build_crv([LAYERS[0]]))
    add("no-geometry", build_crv([lay("empty", [])]))
    add("no-layers", build_crv([]))

    tie = 0.0078125
    add("tie-coordinates", build_crv([lay("tie", [
        contour([line((tie, tie), (0.0009765625, 3 * tie)), line((0.0009765625, 3 * tie), (123456789.125, 5.5)),
                 line((123456789.125, 5.5), (tie, tie))]),
        contour([line((-tie, -tie), (-0.0009765625, 2.5e-7)), line((1e-7, 5e-10), (0.5, 0.25))]),
        contour([arc((tie, 0), (tie * 3, 0), 0.0078125), curve((tie, 0), (tie, tie), (tie * 2, tie), (5.5, 5.5))])])]))
    add("tie-negative-outside", build_crv([lay("tie", [contour([line((-0.0078125, -0.0078125), (0.5, 0.5))])])],
                                          material=(0.0, 0.0, 0.0078125, 0.0078125)))
    bar = [line((-1, 0), (1, 0)), line((1, 0), (1, 2))]
    for i, matrix in enumerate([[float("inf"), 0, 0, 0, 1.0, 0, 0, 0, 1.0], [1e308, 0, 0, 0, 1e308, 0, 0, 0, 1.0],
                                [float("nan"), 0, 0, 0, 1.0, 0, 0, 0, 1.0]]):
        add("text-odd-matrix-%d" % i, build_crv([lay("t", [text_item(lines=[[(2.0, 1.0, [bar])]],
                                                                       base=[line((0, 0), (2, 0))], matrix=matrix)])],
                                                modern=True))
    for i, material in enumerate([(0.0, 0.0, float("inf"), 5.0), (0.0, 0.0, float("nan"), 5.0),
                                  (1e308, 0.0, 1e308, 5.0), (-0.0, -0.0, 5e-324, 5e-324)]):
        add("odd-material-%d" % i, build_crv([lay("a", [contour(square(0, 0, 1))])], material=material))
    add("deep-nesting", build_crv([lay("g", [_nest(3000)])]))
    add("big-numbers", build_crv([lay("big", [contour([line((9e8, -9e8), (1.5e-300, 5e-324)),
                                                      line((1.5e-300, 5e-324), (123456.7890123, 987654.321))])])],
                                 material=(0.0, 0.0, 1e300, 1e300)))

    names = ['a<b>&c', 'say "hi"', "it's", 'both \' and "', "tab\there\nnew\rline", "", "9lives", "___",
             "Cut", "cut", "CUT", "Cut ", "a-b_c$d", "x" * 40, "y" * 300, "café", "€™",
             "bad\x81", "\U0001f600 emoji", "éè", "\ud800", "x\udc00y", "\ud800𐀀", "\u0000nul",
             "Toolpath Previews", "layer", "layer_2", "layer", "a/b", "../..", "‮RTL"]
    for i, n in enumerate(names):
        add("layer-name-%d" % i, build_crv([lay(n, [contour(square(1, 1, 2))], color=(i * 8 % 256, 255 - i, i * 3 % 256))]))
    add("duplicate-names", build_crv([lay(n, [contour(square(1 + i, 1, 1))]) for i, n in enumerate(
        ["Cut", "cut", "CUT", "cut_2", "Cut 2", "a b", "a  b", "a_b", "", "0", "0"])]))
    add("colors", build_crv([lay("c%d" % i, [contour(square(i, i, 1))], color=c) for i, c in enumerate([
        (255, 255, 255), (231, 231, 231), (230, 255, 255), (255, 0, 0), (128, 128, 128), (127, 127, 127),
        (255, 128, 0), (0, 100, 200), (10, 10, 10), (255, 254, 0), (200, 0, 200), (1, 2, 3)])]))

    add("unknown-class", build_crv([lay("a", [contour(square(0, 0, 1))]),
                                    lay("b", [{"kind": "vcCadText", "body": b"\0" * 8}])]))
    for i, cls in enumerate(["it's", 'say "x"', "both'\"", "back\\slash", "tab\there", "x" * 60]):
        add("unknown-class-name-%d" % i, build_crv([lay("a", [{"kind": cls, "body": b"\0" * 8}])]))
    add("unknown-span-type", build_crv([lay("a", [contour(square(0, 0, 1)), contour(square(1, 1, 1), span_type=9)])],
                                       modern=True))
    add("unknown-span-class", build_crv([lay("a", [contour(square(0, 0, 1), span_type=9)])], base=5))
    add("unknown-span-type-6", build_crv([lay("a", [contour(square(0, 0, 1), span_type=5)])], base=7))

    vec = build_vectors([lay("a", [contour(square(0, 0, 1))])])
    at = vec.find(b"vcCadContour") + len("vcCadContour")
    for v in (0, 1, 42):
        patched = bytearray(vec)
        patched[at] = v
        add("object-version-%d" % v, build_cfb({"VectorData/2dDataV2": bytes(patched),
                                                "VersionData/Version": build_version()}))

    modern_vec = build_vectors([lay("t", [text_item(), {"kind": "group", "items": [contour([QUARTER])]},
                                          {"kind": "bitmap", "image": b"\x89PNG" * 50}])], modern=True)
    for cut in range(0, len(modern_vec) - 200, 97):
        add("truncated-modern-%d" % cut, build_cfb({"VectorData/2dDataV2": modern_vec[:cut],
                                                    "VersionData/Version": build_version()}))
    old_vec = build_vectors(LAYERS, base=5)
    for cut in range(0, len(old_vec) - 200, 131):
        add("truncated-era5-%d" % cut, build_cfb({"VectorData/2dDataV2": old_vec[:cut],
                                                  "VersionData/Version": build_version()}))
    full = build_crv(LAYERS, modern=True)
    for cut in (0, 1, 8, 100, 511, 512, 700, 1024, len(full) // 2, len(full) - 1):
        add("truncated-file-%d" % cut, full[:cut])

    add("not-cfb", b"<svg></svg>" * 100)
    add("empty", b"")
    add("missing-vector-stream", build_cfb({"VersionData/Version": build_version(), "Other/Stream": b"x" * 10}))
    add("missing-vector-stream-names", build_cfb({"bé/z": b"1", "A/z": b"2", "a/é": b"3"}))
    add("only-garbage-vector", build_cfb({"VectorData/2dDataV2": b"\x01" * 40}))
    add("empty-vector", build_cfb({"VectorData/2dDataV2": b""}))
    add("huge-layer-count", build_cfb({"VectorData/2dDataV2": struct.pack("<III", 1, 3, 0xFFFFFFFF) + b"\0" * 30}))
    add("wrong-first-class", build_cfb({"VectorData/2dDataV2": struct.pack("<III", 1, 3, 1)
                                        + b"\xff\xff\x01\x00\x03\x00foo" + b"\0" * 30}))
    add("bad-class-ref", build_cfb({"VectorData/2dDataV2": struct.pack("<IIIH", 1, 3, 1, 0x8005) + b"\0" * 30}))
    add("shared-ref", build_cfb({"VectorData/2dDataV2": struct.pack("<IIIH", 1, 3, 1, 0x0003) + b"\0" * 30}))
    add("big-tag-ref", build_cfb({"VectorData/2dDataV2": struct.pack("<IIIHI", 1, 3, 1, 0x7FFF, 0x80000009) + b"\0" * 30}))
    for i, version_stream in enumerate([
            b"", b"\0" * 4, b"\0\0\0\0\xff\xfe\xff\x03a\0b\0c\0",
            b"\0\0\0\0\xff\xfe\xff\xffX", b"\1\0\0\0\xff\xfe\xff\x02\x00\xd8A\0\xff\xfe\xff\x02\x00\xdc\x00\xdc",
            b"\0\0\0\0\xff\xfe\xff\x05a\0b\0", b"\0\0\0\0\xff\xfe\xfe\x03abc",
            b"\0\0\0\0\xff\xfe\xff\x03\x20\x00\x1f\x00X\0\xff\xfe\xff\x02\xa0\x00Y\0",
            b"\0\0\0\0\xff\xfe\xff\x02\x00\xd8"]):
        add("version-stream-%d" % i, build_cfb({"VectorData/2dDataV2": build_vectors(LAYERS),
                                                "VersionData/Version": version_stream}))
    for i, material in enumerate([b"", b"\x05\0\0\0\x01", b"\x07\0\0\0\x00\x01", b"\x08\0\0\0\x02\x01", b"\x09\0\0\0\x01\x01"]):
        add("material-stream-%d" % i, build_cfb({"VectorData/2dDataV2": build_vectors(LAYERS),
                                                 "VectorData/MaterialSize": material}))
    _material_cases(add)
    _sheet_cases(add)
    _tolerance_cases(add)
    _picture_cases(add)
    _estimate_cases(add)
    _hardening_cases(add)
    _writer_cases(add)
    return cases


def _stream_cfb(vector, material=None, version=None):
    streams = {"VectorData/2dDataV2": vector,
               "VersionData/Version": build_version() if version is None else version}
    if material is not None:
        streams["VectorData/MaterialSize"] = material
    return build_cfb(streams)


def _material_cases(add):
    """The job rectangle comes from VectorData/MaterialSize; whatever trails the vector stream is ignored."""
    vec = build_vectors(LAYERS, material=None)
    junk = struct.pack("<I4d", 1, 3.0, 4.0, 5.0, 6.0) + b"\xff" * 220
    stream = crvbuild.build_material((2.0, 3.0, 40.0, 20.0), "mm", False)
    add("material-tail-only", _stream_cfb(vec + junk))
    add("material-stream-wins", _stream_cfb(vec + junk, stream))
    add("material-stream-no-tail", _stream_cfb(vec, stream))
    nan = float("nan")
    add("material-tail-nan", _stream_cfb(vec + struct.pack("<I4d", 1, nan, nan, nan, nan), stream))
    add("material-tail-random", _stream_cfb(vec + bytes(random.Random(5).randrange(256) for _ in range(300)), stream))
    add("material-flipped", _stream_cfb(vec, crvbuild.build_material((10.0, 10.0, -5.0, -5.0), "in", False)))
    add("material-flipped-y", _stream_cfb(vec, crvbuild.build_material((0.0, 10.0, 5.0, -5.0), "in", False)))
    add("material-zero-width", _stream_cfb(vec, crvbuild.build_material((3.0, 3.0, 0.0, 9.0), "in", False)))
    add("material-limit-edge", _stream_cfb(vec, crvbuild.build_material((0.0, 0.0, 1e9, 10.0), "in", False)))
    add("material-just-inside", _stream_cfb(vec, crvbuild.build_material((0.0, 0.0, 999999999.0, 10.0), "mm", False)))
    add("material-negative-origin", _stream_cfb(vec, crvbuild.build_material((-30.5, -20.25, 60.0, 40.0), "mm", True)))
    for i, corner in enumerate([(nan, 0.0, 5.0, 5.0), (0.0, nan, 5.0, 5.0), (0.0, 0.0, float("inf"), 5.0),
                                (float("-inf"), 0.0, 5.0, 5.0)]):
        add("material-nonfinite-%d" % i, _stream_cfb(vec, crvbuild.build_material(corner, "in", False)))
    whole = crvbuild.build_material((0.0, 0.0, 30.0, 15.0), "in", False)
    for n in (0, 5, 6, 53, 54, 55):
        add("material-length-%d" % n, _stream_cfb(vec, whole[:n]))
    for head in (0, 4, 5, 6, 7, 8, 9):
        patched = struct.pack("<I", head) + whole[4:]
        add("material-head-%d" % head, _stream_cfb(vec, patched))
    for units in (0, 1, 2, 255):
        patched = whole[:4] + bytes([units]) + whole[5:]
        add("material-units-%d" % units, _stream_cfb(vec, patched))
    add("material-small-job-big-parts", build_crv([lay("o", [contour(square(0, 0, 400))])], material=(0.0, 0.0, 5.0, 5.0)))


def _sheet_cases(add):
    def parts(sheet, x):
        return contour(square(x, 1, 2), sheet=sheet)

    layers = [
        lay("Toolpath Previews", [{"kind": "preview", "paths": [square(0, 0, 3)], "sheet": 9}]),
        lay("cut", [parts(2, 1), parts(7, 5), {"kind": "bitmap", "image": b"IMG" * 20, "sheet": 5},
                    {"kind": "group", "sheet": 7, "items": [parts(2, 9), contour(circle(14, 6, 1), sheet=0)]}],
            color=(255, 0, 0)),
        lay("pocket", [parts(0, 12), parts(2, 3), contour(square(100, 100, 5), sheet=7),
                       text_item(sheet=0), {"kind": "dimension", "sheet": 2, "parts": [contour([line((0, 0), (9, 0))])]}],
            color=(0, 0, 255)),
        lay("only-on-seven", [contour(square(2, 8, 1), sheet=7)]),
    ]
    for base in (5, 6, 7, 8, 9, 10):
        add("sheets-era-%d" % base, build_crv(layers, base=base))
    add("sheets-modern-mm", build_crv(layers, modern=True, units="mm"))
    add("sheets-no-material", build_crv(layers, base=9, material=None))
    add("sheets-huge-number", build_crv([lay("a", [contour(square(0, 0, 1), sheet=4000000000),
                                                    contour(square(2, 2, 1), sheet=1)])], base=7))
    add("sheets-one-sheet-not-zero", build_crv([lay("a", [contour(square(0, 0, 1), sheet=3)])], base=9))
    add("sheets-empty-sheet-layer", build_crv([lay("a", [{"kind": "contour", "spans": [], "sheet": 4},
                                                         contour(square(0, 0, 1), sheet=1)])], base=9))
    add("sheets-previews-only", build_crv([layers[0]], base=9))
    add("sheets-wide-tags", build_crv(layers, base=10, wide=True))
    sheet_ids = [4, 3, 3, 1, 4, 0, 2, 6, 5]
    add("sheets-many", build_crv([lay("l%d" % (i % 3), [contour(square(i * 2, i, 1.5), sheet=n)
                                                         for i, n in enumerate(sheet_ids)]) for i in range(3)],
                                 base=10, units="mm"))
    for cut in (300, 900, 1500):
        add("sheets-truncated-%d" % cut, build_cfb({"VectorData/2dDataV2": build_vectors(layers, base=10)[:cut],
                                                     "VersionData/Version": build_version()}))


def _tolerance_cases(add):
    gaps = (0.0, 1e-6, 2e-6, 4e-5, 5e-4, 0.003, 0.005, 0.01, 0.02)
    nan = float("nan")
    for i, tol in enumerate([1e-6, 1.0000001e-6, 4e-5, 0.0099999, 0.01, 0.0100001, 0.02, 0.0, -1.0, nan,
                             float("inf"), 5e-324, 1e-3]):
        items = []
        for j, gap in enumerate(gaps):
            y = j * 3
            items.append(contour([line((0, y), (4, y)), line((4 + gap, y), (4, y + 2)), line((4, y + 2), (0, y + 2)),
                                  line((0, y + 2 + gap), (0, y))], tolerance=tol))
            items.append(contour([arc((6, y), (8, y), 1.0), arc((8 + gap, y), (6, y + gap), 1.0)], tolerance=tol))
        add("join-tolerance-%d" % i, build_crv([lay("j", items)], material=(0.0, 0.0, 30.0, 40.0)))
    ragged = [line((0, 0), (4, 0)), line((4.003, 0), (4, 4)), line((4, 4.0), (0, 4)), line((0, 3.997), (0, 0))]
    add("join-tolerance-wide", build_crv([lay("j", [contour(ragged, tolerance=0.005)])]))
    add("join-tolerance-ignored", build_crv([lay("j", [contour(ragged, tolerance=0.02)])]))
    add("join-tolerance-text-base", build_crv([lay("t", [text_item(base=[line((10, 5), (16, 5))])])], modern=True))
    add("join-tolerance-curves", build_crv([lay("j", [contour(
        [curve((0, 0), (1, 2), (3, 2), (4, 0)), curve((4.004, 0), (5, -2), (7, -2), (8, 0)), line((8, 0), (0, 0.004))],
        tolerance=0.006)])]))


def _picture_cases(add):
    image = bytes(range(256)) * 8
    kinds = {"bitmap": 7, "oldbitmap": 6, "oldmodel": 6, "model": 9, "component": 9}
    for kind, default in kinds.items():
        def one(base, kind=kind):
            return build_crv([lay("pics", [{"kind": kind, "image": image}]), lay("a", [contour(square(1, 1, 2))])],
                             base=base)
        add("picture-%s" % kind, one(default))
        for base in (5, 6, 7, 8, 9, 10):
            add("picture-%s-era-%d" % (kind, base), one(base))
        whole = one(default)
        for cut in (1100, 1700, 2600, 3300):
            add("picture-%s-truncated-%d" % (kind, cut), whole[:cut])
        add("picture-%s-in-group" % kind, build_crv([lay("g", [{"kind": "group", "sheet": 3, "items": [
            {"kind": kind, "image": image}, contour(square(1, 1, 1))]}])], base=default))
        add("picture-%s-between-parts" % kind, build_crv([lay("g", [
            contour(square(0, 0, 1), sheet=1), {"kind": kind, "image": image, "sheet": 2},
            contour(square(3, 3, 1), sheet=2)])], base=default))
        add("picture-%s-empty-image" % kind, build_crv([lay("g", [{"kind": kind, "image": b""}])], base=default))
    add("picture-garbage-version", build_crv([lay("g", [{"kind": "vcCadBitmap", "body": b""}])], base=7))


def _estimate_cases(add):
    glyphs = [[(2.0, 1.0, [BOWL], 0.25), (2.5, 0.25, [SWEEPS]), (1.5, 0.0, [circle(0, 1, 1) + BAR], -0.3)]]
    for base in (5, 6, 7, 8):
        add("approx-text-era-%d" % base, build_crv([lay("t", [text_item()])], base=base))
        add("approx-text-lift-era-%d" % base, build_crv([lay("t", [text_item(lines=glyphs, base=[line((1, 1), (7, 2.5))])])],
                                                       base=base))
        add("approx-text-rotated-era-%d" % base, build_crv([lay("t", [text_item(matrix=rot(33.0, tx=5.0, ty=-1.0))])],
                                                           base=base))
        add("approx-text-mirrored-era-%d" % base, build_crv([lay("t", [text_item(
            lines=[[(2.0, 1.0, [BOWL]), (2.0, 0.5, [BAR])]], base=[line((0, 0), (4, 0))],
            matrix=[0.6, 0.8, 3.0, 0.8, -0.6, 4.0, 0, 0, 1.0])])], base=base))
        add("approx-text-skewed-era-%d" % base, build_crv([lay("t", [text_item(
            lines=glyphs, matrix=[1.0, 0.4, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0])])], base=base))
        add("approx-text-short-line-era-%d" % base, build_crv([lay("t", [text_item(base=[line((0, 0), (1, 0))])])], base=base))
        add("approx-text-long-line-era-%d" % base, build_crv([lay("t", [text_item(base=[line((0, 0), (90, 40))])])], base=base))
        add("approx-text-unplaceable-era-%d" % base, build_crv([lay("t", [
            text_item(lines=[[(4.0, 2.0, [BAR])], [(4.0, 2.0, [BAR])]]),
            text_item(base=[arc((0, 0), (6, 0), 0.5)]), text_item(base=[line((2, 2), (2, 2))]),
            text_item(base=None), text_item(lines=[[(1.0, 0.0, [])]]), contour(square(0, 0, 1))])], base=base))
        add("approx-text-two-blocks-era-%d" % base, build_crv([lay("t", [text_item(), text_item(base=[line((0, 9), (5, 9))])]),
                                                                lay("u", [text_item()])], base=base))
    add("approx-text-dimension-era-6", build_crv([lay("D", [{"kind": "dimension", "parts": [
        text_item(), contour([line((0, 0), (9, 0))])]}])], base=6))
    add("approx-text-lands-out-of-range", build_crv([lay("t", [text_item(matrix=rot(0.0, tx=2e9))])], base=5))
    add("approx-text-near-limit", build_crv([lay("t", [text_item(matrix=rot(0.0, tx=999999990.0))])], base=6))


def _hardening_cases(add):
    for n in (1, 62, 63, 64, 65, 66, 100, 500):
        add("nesting-%d" % n, build_crv([lay("g", [_nest(n)])]))
    for n in (63, 64, 65):
        item = contour(square(0, 0, 1))
        for _ in range(n):
            item = {"kind": "dimension", "parts": [item]}
        add("nesting-dimension-%d" % n, build_crv([lay("g", [item])], modern=True))
    item = contour(square(0, 0, 1))
    for i in range(70):
        item = {"kind": "group", "items": [item]} if i % 2 else {"kind": "dimension", "parts": [item]}
    add("nesting-mixed-70", build_crv([lay("g", [item])], modern=True))
    add("nesting-siblings-not-depth", build_crv([lay("g", [{"kind": "group", "items": [
        contour(square(i, 0, 1)) for i in range(200)]}])]))

    for i, v in enumerate([b"\0\0\0\0\xff\xfe\xff\xff", b"\0\0\0\0\xff\xfe\xff\xff\x01",
                           b"\0\0\0\0\xff\xfe\xff\xff\x01\x00", b"\0\0\0\0\xff\xfe\xff\xff\x01\x00A",
                           b"\0\0\0\0\xff\xfe\xff\xff\x00\x00", b"\0\0\0\0\xff\xfe\xff", b"\0\0\0\0\xff\xfe",
                           b"\0\0\0\0\xff", b"\0\0\0", b"\0\0\0\0\xff\xfe\xff\x00",
                           b"\0\0\0\0\xff\xfe\xff\x01A\0\xff\xfe\xff\xff\x03",
                           b"\0\0\0\0\xff\xfe\xff\x01A\0\xff\xfe\xff\x01B\0\xff\xfe\xff\xff"]):
        add("version-short-%d" % i, build_cfb({"VectorData/2dDataV2": build_vectors(LAYERS), "VersionData/Version": v}))

    inf, nan = float("inf"), float("nan")
    for i, glyph in enumerate([(inf, 1.0, [BAR]), (nan, 1.0, [BAR]), (1e9, 1.0, [BAR]), (-1e9, 1.0, [BAR]),
                               (999999999.5, 1.0, [BAR]), (2.0, inf, [BAR]), (2.0, nan, [BAR]), (2.0, -1e9, [BAR]),
                               (2.0, 1.0, [BAR], nan), (2.0, 1.0, [BAR], 1e12), (2.0, 1.0, [BAR], -inf)]):
        add("text-nonfinite-%d" % i, build_crv([lay("t", [text_item(lines=[[glyph]], base=[line((0, 0), (2, 0))])])],
                                               modern=True))
    add("text-advance-inf", build_crv([lay("t", [text_item(lines=[[(inf, 1.0, [BAR])]])])], modern=True))
    for i in range(9):
        matrix = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        matrix[i] = [nan, inf, 1e9, -1e9, 5e8][i % 5]
        add("text-matrix-element-%d" % i, build_crv([lay("t", [text_item(matrix=matrix)])], modern=True))
    add("text-lands-out-of-range", build_crv([lay("t", [text_item(matrix=rot(0.0, tx=2e9))])], modern=True))
    add("text-lands-just-inside", build_crv([lay("t", [text_item(matrix=rot(0.0, tx=999999900.0))])], modern=True))
    add("text-lands-scaled-out", build_crv([lay("t", [text_item(matrix=rot(0.0, sx=1e9, sy=1e9))])], modern=True))
    add("text-lands-out-in-y", build_crv([lay("t", [text_item(matrix=[1.0, 0.0, 0.0, 0.0, 1.0, -3e9, 0.0, 0.0, 1.0])])],
                                         modern=True))

    names = ["Cut"] * 3000
    for i in range(3000):
        if i % 11 == 3:
            names[i] = "Cut_%d" % (i % 5 + 2)
        elif i % 13 == 5:
            names[i] = "cut"
    add("thousands-of-same-name", build_crv([lay(n, [contour(square(i % 40, i // 40 % 10, 0.5))])
                                             for i, n in enumerate(names)], material=(0.0, 0.0, 40.0, 10.0)))
    add("thousands-of-long-names", build_crv([lay("x" * 40 + str(i), [contour(square(i % 40, 1, 0.5))]) for i in range(800)]))
    add("thousands-of-symbol-names", build_crv([lay("".join(chr(0x4e00 + (i * 7 + k) % 5000) for k in range(3)),
                                                    [contour(square(i % 40, 1, 0.5))]) for i in range(800)]))
    add("thousands-of-numeric-names", build_crv([lay(str(i % 40), [contour(square(i % 40, 1, 0.5))]) for i in range(1200)]))


def _writer_cases(add):
    controls = ["a\x01b", "\x0b", "\x1f", "\x7f", "\x85", "\u2028", "\ufffe", "\uffff", "\ufdd0", "\x08x\x0c",
                "a\tb", "a\nb", "a\rb", "\u00a0nb", "\ud7ff", "\ue000", "\U0010ffff", "\U0001f600", "\x00", "\x00\x01",
                "\ufeff", "\ufffd", "<\x02>", '"\x03"']
    add("layer-controls", build_crv([lay(n, [contour(square(1 + i * 0.5, 1, 1))], color=(i * 10, 0, 255 - i * 10))
                                      for i, n in enumerate(controls)]))
    for i, n in enumerate(controls):
        add("layer-control-%d" % i, build_crv([lay(n, [contour(square(1, 1, 2))])]))
    greys = [(v, v, v) for v in range(0, 256, 5)] + [(v, v, v) for v in (1, 69, 70, 71, 199, 200, 201, 229, 230, 231)]
    greys += [(100, 110, 139), (100, 110, 140), (70, 70, 109), (200, 160, 161), (200, 160, 160), (255, 254, 255),
              (69, 100, 108), (200, 200, 239), (0, 39, 0), (0, 40, 0), (128, 128, 167)]
    add("grey-colours", build_crv([lay("g%d" % i, [contour(square(i % 24, i // 24, 0.8))], color=c)
                                   for i, c in enumerate(greys)]))

    add("circle-radius-case", build_crv([lay("c", [contour(circle(37.5714285714, 37.6666666667, 17.8181818182))])],
                                        material=(0.0, 0.0, 100.0, 100.0), units="mm"))
    rng = random.Random(7)
    circles = [contour(circle(round(rng.uniform(5, 95), 10), round(rng.uniform(5, 95), 10),
                              round(rng.uniform(0.1, 5), 10))) for _ in range(400)]
    add("circle-radius-random", build_crv([lay("c", circles)], material=(0.0, 0.0, 100.0, 100.0), units="mm"))
    arcs = []
    for _ in range(400):
        a = (round(rng.uniform(0, 100), 10), round(rng.uniform(0, 100), 10))
        b = (round(rng.uniform(0, 100), 10), round(rng.uniform(0, 100), 10))
        arcs.append(contour([arc(a, b, rng.choice([-1, 1]) * rng.uniform(0.01, 4)), arc(b, a, rng.uniform(-3, 3) or 0.5)]))
    add("arc-radius-random", build_crv([lay("c", arcs)], material=(0.0, 0.0, 100.0, 100.0), units="mm"))
    add("circle-radius-inches", build_crv([lay("c", [contour(circle(3.14159265358, 2.71828182846, 1.41421356237))])],
                                          material=(0.0, 0.0, 10.0, 10.0)))

    big = [curve((0, 0), (1e8, 1e8), (-1e8, 1e8), (1e8, 0)), curve((0, 0), (300, 900), (600, -900), (900, 0)),
           curve((0, 0), (3e5, 1e5), (-2e5, 4e5), (1e5, 0)), curve((0, 0), (9e8, 9e8), (-9e8, 9e8), (9e8, 0))]
    add("big-curves", build_crv([lay("b", [contour([c]) for c in big])]))
    add("big-curves-mm", build_crv([lay("b", [contour([c]) for c in big])], units="mm", modern=True))
    add("big-curve-cap-edge", build_crv([lay("b", [contour([curve((0, 0), (x, 4 * x), (-x, 4 * x), (x, 0))])
                                                    for x in (4000.0, 50000.0, 90000.0, 120000.0, 200000.0)])]))
    add("wide-tags", build_crv(LAYERS, wide=True))
    for base in (5, 7, 9, 10):
        add("wide-tags-era-%d" % base, build_crv(LAYERS, wide=True, base=base))
    add("no-units-eras", build_crv(LAYERS, base=6, units=None))


def fuzz_cases():
    """Seeded mutations of valid files, both inside the vector stream and across the container."""
    rng = random.Random(20261011)
    bases = [build_vectors(LAYERS, base=b) for b in (5, 7, 9, 10)]
    bases.append(build_vectors([lay("t", [text_item(matrix=rot(12.0, sx=2.0)), {"kind": "dimension", "parts": [
        text_item(), contour(SWEEPS)]}, {"kind": "bitmap", "image": b"IMG" * 30}])], modern=True))
    out = []
    for n in range(240):
        vec = bytearray(rng.choice(bases))
        for _ in range(rng.randint(1, 3)):
            kind = rng.random()
            at = rng.randrange(len(vec))
            if kind < 0.4:
                vec[at] ^= 1 << rng.randrange(8)
            elif kind < 0.7:
                vec[at:at + 4] = rng.choice([b"\xff\xff\xff\xff", b"\0\0\0\0", b"\xff\xff\0\0", b"\x7f\xff\0\0",
                                             b"\0\0\0\x80", b"\x01\0\0\0"])
            elif kind < 0.85:
                vec[at:at + 8] = rng.choice([struct.pack("<d", float("nan")), struct.pack("<d", 1e300),
                                             struct.pack("<d", float("inf")), struct.pack("<d", -0.0),
                                             struct.pack("<d", 5e-324)])
            else:
                del vec[at:]
        out.append(("fuzz-vec-%d" % n, build_cfb({"VectorData/2dDataV2": bytes(vec),
                                                  "VersionData/Version": build_version()})))
    whole = build_crv(LAYERS, modern=True)
    for n in range(120):
        data = bytearray(whole)
        for _ in range(rng.randint(1, 3)):
            at = rng.randrange(0, 1024 if rng.random() < 0.7 else len(data))
            if rng.random() < 0.5:
                data[at] = rng.randrange(256)
            else:
                data[at:at + 4] = rng.choice([b"\xff\xff\xff\xff", b"\0\0\0\0", b"\xfe\xff\xff\xff", b"\x01\0\0\0"])
        out.append(("fuzz-cfb-%d" % n, bytes(data)))
    return out


# ---------------------------------------------------------------------- running

def run_node(tmp_path, entries, dump=None, approximate=False):
    """entries: [(id, path)]. Returns {id: result}."""
    driver = tmp_path / "driver.js"
    driver.write_text(DRIVER)
    manifest = tmp_path / ("manifest-%s.json" % hashlib.sha256(json.dumps(entries).encode()).hexdigest()[:12])
    manifest.write_text(json.dumps([{"id": i, "path": p} for i, p in entries]))
    argv = [NODE, str(driver), ENGINE, str(manifest), dump or "", "approx" if approximate else ""]
    done = subprocess.run(argv, capture_output=True, timeout=1800)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(done.stdout.decode("utf-8"))


def first_difference(a, b):
    a_lines, b_lines = a.split("\n"), b.split("\n")
    for i, (x, y) in enumerate(zip(a_lines, b_lines)):
        if x != y:
            return "line %d\n  python: %r\n  node:   %r" % (i + 1, x[:300], y[:300])
    return "lengths differ: python %d lines, node %d lines" % (len(a_lines), len(b_lines))


def explain(tmp_path, case_id, path, py, js, approximate):
    if not (py.get("ok") or py.get("partial")) or "outs" not in (py if py.get("ok") else py["partial"]):
        return "python %r\nnode   %r" % (py, js)
    detail = run_node(tmp_path, [(case_id, path)], dump=case_id, approximate=approximate)[case_id]
    want = py if py.get("ok") else py["partial"]
    got = detail if detail.get("ok") else detail.get("partial")
    full = python_result(open(path, "rb").read(), want_text=True, approximate=approximate)
    ref = full if full.get("ok") else full["partial"]
    for n, (p, g) in enumerate(zip(ref["outs"], got["outs"])):
        for key in ("svg", "dxf"):
            if p.get(key) != g.get(key):
                return "variant %d %s: %s" % (n, key, first_difference(p.get(key, ""), g.get(key, "")))
    return "metadata or error differs:\npython %r\nnode   %r" % (want.get("meta"), got.get("meta"))


def comparable(py, js):
    """Python crashes (an exception that is not a CrvError) have no exact twin; node must still be clean."""
    if "crash" in py:
        return False
    for result in (py, js):
        for part in [result] + ([result["partial"]] if result.get("partial") else []):
            if any("crash" in o for o in part.get("outs", [])):
                return False
    return True


MODES = (False, True)


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("parity")
    entries, py = [], {m: {} for m in MODES}
    for case_id, data in synthetic_cases() + fuzz_cases():
        path = tmp / (case_id + ".crv")
        path.write_bytes(data)
        entries.append((case_id, str(path)))
        for mode in MODES:
            py[mode][case_id] = python_result(data, approximate=mode)
    return tmp, entries, py, {m: run_node(tmp, entries, approximate=m) for m in MODES}


def results_of(result):
    return [result] + ([result["partial"]] if result.get("partial") else [])


@pytest.mark.parametrize("mode", MODES, ids=["estimate-off", "estimate-on"])
def test_synthetic_files_match_exactly(synthetic, mode):
    tmp, entries, py, js = synthetic
    py, js = py[mode], js[mode]
    paths = dict(entries)
    bad, skipped, matched, compared = [], [], 0, 0
    for case_id, _ in entries:
        if not comparable(py[case_id], js[case_id]):
            skipped.append(case_id)
            assert "crash" not in js[case_id] or "CrvError" in js[case_id]["crash"], (case_id, js[case_id])
            continue
        if py[case_id] == js[case_id]:
            matched += 1
            compared += sum(len(r["outs"]) for r in results_of(py[case_id]) if "outs" in r)
        else:
            bad.append(case_id)
    print("\nweb parity, synthetic, estimate %s: %d matched (%d svg+dxf pairs), %d python-side crashes "
          "skipped, %d differ" % ("on" if mode else "off", matched, compared, len(skipped), len(bad)))
    assert not bad, "\n\n".join("%s: %s" % (c, explain(tmp, c, paths[c], py[c], js[c], mode)) for c in bad[:3])


def test_node_never_leaks_a_raw_exception(synthetic):
    _, entries, _, js = synthetic
    for mode in MODES:
        crashes = {c: js[mode][c]["crash"] for c, _ in entries if "crash" in js[mode][c]}
        assert not crashes
        for case_id, _ in entries:
            for part in results_of(js[mode][case_id]):
                for o in part.get("outs", []):
                    assert o.get("crash", "CrvError").startswith("CrvError"), (case_id, o)


def test_synthetic_set_covers_what_it_claims(synthetic):
    _, entries, py, js = synthetic
    ids = [c for c, _ in entries]
    assert len(ids) > 600
    js = js[False]
    ok = sum(1 for c in ids if js[c].get("ok"))
    unsupported = sum(1 for c in ids if js[c].get("cls") == "UnsupportedError")
    plain = sum(1 for c in ids if js[c].get("cls") == "CrvError")
    assert ok > 150 and unsupported > 60 and plain > 25
    warned = [c for c in ids if js[c].get("ok") and js[c]["meta"]["warnings"]]
    assert warned


def test_arc_conversion_in_text_is_exercised(synthetic):
    _, _, py, js = synthetic
    assert js[False]["text-uneven-0"]["ok"] and py[False]["text-uneven-0"] == js[False]["text-uneven-0"]


def _ok(js, case_id, mode=False):
    result = js[mode][case_id]
    assert result.get("ok"), (case_id, result)
    return result


def test_each_new_behaviour_is_actually_reached(synthetic):
    """Guards against a parity case that matches only because both engines did nothing."""
    _, _, py, js = synthetic
    for mode in (py, js):
        assert _ok(mode, "sheets-era-5")["meta"]["sheets"] == [0, 2, 7]
        assert _ok(mode, "sheets-era-10")["meta"]["sheets"] == [
            "00000002-0000-0000-0000-000000000000", "00000007-0000-0000-0000-000000000000",
            "00000000-0000-0000-0000-000000000000"]
        assert _ok(mode, "sheets-huge-number")["meta"]["sheets"] == [1, 4000000000]
        assert _ok(mode, "material-stream-wins")["meta"]["material"] != _ok(mode, "material-tail-only")["meta"]["material"]
        assert _ok(mode, "material-tail-only")["meta"]["material"] is None
        assert _ok(mode, "material-flipped")["meta"]["material"] is None
        for kind in ("bitmap", "oldbitmap", "oldmodel", "model", "component"):
            assert _ok(mode, "picture-%s" % kind)["meta"]["layers"][0][3] == 1
        assert js[False]["picture-oldbitmap-era-8"]["cls"] == "UnsupportedError"
        assert js[False]["nesting-65"]["cls"] == "UnsupportedError"
        assert "nested more than 64" in js[False]["nesting-65"]["msg"]
        assert js[False]["nesting-64"]["ok"]
        assert js[False]["text-lands-out-of-range"]["cls"] == "UnsupportedError"
        assert js[False]["text-advance-inf"]["cls"] == "UnsupportedError"
    for era in (5, 6):
        off, on = _ok(js, "approx-text-era-%d" % era), _ok(js, "approx-text-era-%d" % era, True)
        assert off["meta"]["warnings"] != on["meta"]["warnings"]
        assert any("by estimate" in w for w in on["meta"]["warnings"])
        assert any("left out" in w for w in off["meta"]["warnings"])
        assert off["outs"][0]["svg"] != on["outs"][0]["svg"]
    multi = _ok(js, "sheets-era-7")
    assert len({o["svg"][0] for o in multi["outs"][3:]}) == 3
    assert multi["outs"][3]["svg"] != multi["outs"][0]["svg"]
    names = _ok(js, "thousands-of-same-name")
    assert names["meta"]["layers"][2999][0] == "Cut"
    near = _ok(js, "join-tolerance-wide")
    assert near["outs"][0]["svg"] != _ok(js, "join-tolerance-ignored")["outs"][0]["svg"]


def test_number_writer_refuses_non_finite_like_python(tmp_path):
    from crv2svg.numfmt import fmt
    values = [float("nan"), float("inf"), float("-inf"), 0.0, -0.0, 1.5, -2.5e-7, 123456789.1234567, 5e-324, 1e300]
    script = tmp_path / "fmt.js"
    script.write_text("const c=require(%s);const out=[];for(const v of [NaN,Infinity,-Infinity,0,-0,1.5,-2.5e-7,"
                      "123456789.1234567,5e-324,1e300]){for(const d of [6,9]){try{out.push(c.numfmt.fmt(v,d))}"
                      "catch(e){out.push(e.name+': '+e.message)}}}console.log(JSON.stringify(out))" % json.dumps(ENGINE))
    got = json.loads(subprocess.run([NODE, str(script)], capture_output=True, check=True).stdout)
    want = []
    for v in values:
        for d in (6, 9):
            try:
                want.append(fmt(v, d))
            except CrvError as exc:
                want.append("CrvError: %s" % exc)
    assert got == want
    assert got[0] == "CrvError: a number in this file is too large to write"


@pytest.mark.skipif(not SAMPLES, reason="set CRV2SVG_SAMPLES to a folder of .crv files")
@pytest.mark.parametrize("mode", MODES, ids=["estimate-off", "estimate-on"])
def test_real_files_match_exactly(tmp_path, mode):
    files = sorted(glob.glob(os.path.join(SAMPLES, "**", "*.crv*"), recursive=True))
    assert files
    entries = [("f%d" % i, f) for i, f in enumerate(files)]
    js = run_node(tmp_path, entries, approximate=mode)
    bad, ok, refused, multi, sheet_pairs, warned = [], 0, 0, 0, 0, 0
    for case_id, path in entries:
        with open(path, "rb") as handle:
            py = python_result(handle.read(), approximate=mode)
        assert "crash" not in js[case_id], (path, js[case_id])
        if py == js[case_id]:
            ok += 1
            refused += 0 if py.get("ok") else 1
            for part in results_of(py):
                if "meta" in part:
                    warned += bool(part["meta"]["warnings"])
                    if len(part["meta"]["sheets"]) > 1:
                        multi += 1
                        sheet_pairs += len(part["meta"]["sheets"])
        else:
            bad.append((case_id, path, py, js[case_id]))
    print("\nweb parity, corpus, estimate %s: %d of %d files identical (%d identical refusals); "
          "%d multi-sheet files, %d per-sheet svg+dxf pairs compared; %d files carry warnings" % (
              "on" if mode else "off", ok, len(files), refused, multi, sheet_pairs, warned))
    assert not bad, "\n\n".join("%s: %s" % (os.path.basename(p), explain(tmp_path, c, p, py, js_, mode))
                                for c, p, py, js_ in bad[:3])


# ------------------------------------------------------------ the page, in a real browser

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
CHECKS = os.path.join(ROOT, "tests", "web_browser_check.mjs")


def _rect_round(x, y, w, h, r):
    k = 0.4142135623
    return [line((x + r, y), (x + w - r, y)), arc((x + w - r, y), (x + w, y + r), k),
            line((x + w, y + r), (x + w, y + h - r)), arc((x + w, y + h - r), (x + w - r, y + h), k),
            line((x + w - r, y + h), (x + r, y + h)), arc((x + r, y + h), (x, y + h - r), k),
            line((x, y + h - r), (x, y + r)), arc((x, y + r), (x + r, y), k)]


def browser_inputs(folder):
    sign = [
        lay("Cut out", [contour(_rect_round(20, 20, 260, 160, 18))], color=(214, 40, 40)),
        lay("Pocket", [contour(circle(150, 100, 30))], color=(40, 90, 200)),
    ]
    mm = dict(material=(0.0, 0.0, 300.0, 200.0), units="mm")
    parts = [contour(_rect_round(10 + 100 * c, 10 + 70 * r, 90, 60, 8), sheet=sh)
             for sh in (0, 1, 2) for r in range(2) for c in range(2)]
    files = {
        "single.crv": build_crv(sign, modern=True, **mm),
        "three-sheets.crv": build_crv([lay("Parts", parts, color=(200, 60, 30))],
                                      material=(0.0, 0.0, 500.0, 305.0), units="mm", base=9),
        "empty-layers.crv": build_crv([lay("Nothing", [])], modern=True, **mm),
        "many-empty.crv": build_crv(
            [lay("Empty %d" % i, []) for i in range(19)]
            + [lay("Cut %d" % i, [contour(square(10 * i, 10, 5))], color=(10 * i, 60, 120)) for i in range(3)],
            modern=True, **mm),
        "heavy.crv": build_crv([lay("Tiny", [contour(square(10, 10, 5))])], modern=True,
                               preview=b"GIF89a" + bytes(1600000), **mm),
        "old-text2.crv": build_crv(
            [lay("Lettering", [text_item(base=[line((20, 30), (90, 30))]),
                               text_item(base=[line((20, 40), (90, 40))]),
                               contour(_rect_round(10, 10, 120, 50, 8))])],
            material=(0.0, 0.0, 150.0, 80.0), units="mm", base=6),
        "unknown.crv": build_crv(
            [lay("a", [contour(_rect_round(10, 10, 100, 60, 8))]),
             lay("b", [{"kind": "vcCadSpline", "body": b"\0" * 8}])], **mm),
        "junk.crv": b"This is just text that somebody renamed. " * 40,
        "zero.crv": b"",
        "bezier-heavy.crv": bezier_heavy(300),
    }
    for name, data in files.items():
        with open(os.path.join(folder, name), "wb") as handle:
            handle.write(data)


def bezier_heavy(count):
    spans = [curve((i, 0.0), (i, 180000.0), (i + 1, -180000.0), (i + 1, 0.0)) for i in range(count)]
    return build_crv([lay("Curves", [contour(spans)])], material=(0.0, 0.0, 400.0, 100.0), units="in")


def test_a_curve_heavy_export_is_refused_cleanly_not_run_out_of_memory(tmp_path):
    path = tmp_path / "heavy.crv"
    path.write_bytes(bezier_heavy(300))
    assert path.stat().st_size < 40000
    script = tmp_path / "heavy.js"
    script.write_text(
        "const c=require(%s);const d=c.readBytes(new Uint8Array(require('fs').readFileSync(%s)),false);"
        "const svg=c.toSvg(d,{});let dxf;try{c.toDxf(d,{});dxf='built'}catch(e){dxf=e.name+': '+e.message}"
        "console.log(JSON.stringify([svg.length<100000,dxf]))" % (json.dumps(ENGINE), json.dumps(str(path))))
    done = subprocess.run([NODE, "--max-old-space-size=512", str(script)], capture_output=True, timeout=300)
    assert done.returncode == 0, done.stderr.decode()[-500:]
    assert json.loads(done.stdout) == [True, "CrvError: this drawing is too large to save"]
    doc = crv2svg.read_bytes(path.read_bytes())
    assert len(crv2svg.to_svg(doc)) < 100000
    with pytest.raises(CrvError, match="^this drawing is too large to save$"):
        crv2svg.to_dxf(doc)


def _run_page(tmp_path, page_url):
    inputs = tmp_path / "in"
    inputs.mkdir()
    browser_inputs(str(inputs))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    done = subprocess.run([NODE, CHECKS, page_url, str(inputs), str(scratch), CHROMIUM],
                          capture_output=True, timeout=600)
    out = done.stdout.decode("utf-8", "replace")
    assert done.returncode == 0 and "FAIL" not in out, out + done.stderr.decode("utf-8", "replace")[-1500:]
    assert out.count("PASS") >= 30


@pytest.mark.skipif(CHROMIUM is None, reason="no chromium to drive")
def test_page_behaves_when_served(tmp_path):
    server = subprocess.Popen([sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1", "--directory",
                               os.path.join(ROOT, "web")], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        port = server.stdout.readline().split("port")[1].split()[0]
        _run_page(tmp_path, "http://127.0.0.1:%s/index.html" % port)
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.mark.skipif(CHROMIUM is None, reason="no chromium to drive")
def test_built_single_file_behaves_from_file(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "web"))
    import build
    build.build()
    _run_page(tmp_path, "file://" + build.OUT.as_posix())


# ------------------------------------------------------------ trigonometry primitives

LIBM_GAPS = [
    ("sin", [-40.46222598149629]), ("sin", [-25.45317874339358]), ("sin", [-6.701513737761446]),
    ("cos", [39.14334289674979]), ("cos", [-0.1812354801642763]), ("cos", [-26.90082661822437]),
    ("tan", [239.87046026234188]), ("tan", [0.5535752173688248]),
    ("atan2", [-0.2816733256830218, 3.6012964080056364]), ("atan2", [0.3185416163176677, 0.9241107567408667]),
    ("atan2", [-286.80109274235366, 45.90472243803569]),
]


def _exact(fn, args):
    """The correctly rounded double, from 70 digit decimal arithmetic."""
    from decimal import Decimal, getcontext
    getcontext().prec = 70
    D = Decimal

    def series_atan(x):
        x = D(x)
        for _ in range(4):
            x = x / (1 + (1 + x * x).sqrt())
        total, term, k = x, x, 0
        while abs(term) > D(10) ** -68:
            k += 1
            term = -term * x * x
            total += term / (2 * k + 1)
        return total * 16

    atan5, atan239 = _machin(D(1) / 5), _machin(D(1) / 239)
    pi = 16 * atan5 - 4 * atan239

    def reduce(x):
        x = D(x)
        n = (x / (2 * pi)).to_integral_value()
        return x - n * 2 * pi

    def sin_c(x):
        r = reduce(x)
        total, term, k = r, r, 0
        while abs(term) > D(10) ** -68:
            k += 1
            term = -term * r * r / ((2 * k) * (2 * k + 1))
            total += term
        return total

    def cos_c(x):
        r = reduce(x)
        total, term, k = D(1), D(1), 0
        while abs(term) > D(10) ** -68:
            k += 1
            term = -term * r * r / ((2 * k - 1) * (2 * k))
            total += term
        return total

    if fn == "sin":
        return float(sin_c(args[0]))
    if fn == "cos":
        return float(cos_c(args[0]))
    if fn == "tan":
        return float(sin_c(args[0]) / cos_c(args[0]))
    y, x = D(args[0]), D(args[1])
    angle = series_atan(abs(y / x))
    if x < 0:
        angle = pi - angle
    return float(-angle if y < 0 else angle)


def _machin(x):
    from decimal import Decimal
    total, term, k = x, x, 0
    while abs(term) > Decimal(10) ** -68:
        k += 1
        term = -term * x * x
        total += term / (2 * k + 1)
    return total


def test_trig_primitives_are_correctly_rounded_where_libm_is_one_ulp_off(tmp_path):
    """The browser engine rounds correctly; Python's math module (the platform libm) sometimes lands one ulp away.

    The pairs below were found by differential fuzzing. They are pinned so a change to the series that
    moves any of them is noticed, and the formatted coordinates must still agree at the writers' precision.
    """
    import math
    script = tmp_path / "trig.js"
    script.write_text(
        "const m=require(%s)._math;const out=[];for(const [f,a] of %s){out.push(m[f](...a))}"
        "console.log(JSON.stringify(out.map((v)=>v.toString())))" % (json.dumps(ENGINE), json.dumps(LIBM_GAPS)))
    got = [float(v) for v in json.loads(subprocess.run([NODE, str(script)], capture_output=True, check=True).stdout)]
    from crv2svg.numfmt import fmt
    for (fn, args), value in zip(LIBM_GAPS, got):
        assert value == _exact(fn, args), (fn, args)
        libm = getattr(math, fn)(*args)
        assert abs(libm - value) <= math.ulp(value), (fn, args, libm, value)
        for digits in (6, 9):
            assert fmt(libm, digits) == fmt(value, digits), (fn, args, digits)
