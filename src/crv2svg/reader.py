"""Turn the bytes of a CRV project into a Document. Layout notes: docs/FORMAT.md."""

import struct

from . import cfb, text
from .archive import Archive
from .errors import CrvError, UnsupportedError
from .model import Document, Item, Layer, Path, Span

VECTOR_STREAM = "VectorData/2dDataV2"
PREVIEW_LAYER = "Toolpath Previews"
# Tab spans are the stretches of a toolpath preview that lift over a holding tab.
SPAN_LINE, SPAN_ARC, SPAN_BEZIER, SPAN_TAB_LINE, SPAN_TAB_ARC = 0, 1, 2, 3, 4
SPAN_POINT = -1
# NaN fails both comparisons, so these also reject it.
COORD_LIMIT = 1e9
# Parameter value types: a double, a 32-bit integer, a one-byte flag.
PARAM_SIZE = {0: 8, 1: 4, 2: 1}
PARAM_STRING = 3
BULGE_LIMIT = 1e6


def read_file(path):
    with open(path, "rb") as handle:
        return read_bytes(handle.read())


def read_bytes(data):
    streams = cfb.read_streams(data)
    doc = Document()
    doc.product, doc.version = _version(streams.get("VersionData/Version", b""))
    doc.preview_gif = streams.get("PreviewData/Preview2D_GIF", b"")
    doc.units = _units(streams.get("VectorData/MaterialSize", b""))
    if VECTOR_STREAM not in streams:
        names = ", ".join(sorted(streams)) or "none"
        raise UnsupportedError(
            "no %s stream in this file (found: %s). It may come from a Vectric "
            "release this reader has not seen." % (VECTOR_STREAM, names))
    ar = Archive(streams[VECTOR_STREAM])
    doc.warnings = ar.warnings
    try:
        _read_vectors(ar, doc)
    except UnsupportedError as exc:
        exc.partial = doc
        raise
    except CrvError as exc:
        raise UnsupportedError(str(exc), partial=doc) from exc
    return doc


def _version(raw):
    """The version stream is a run of UTF-16 strings: product, version, build date, owner."""
    parts, pos = [], 4
    while pos + 4 <= len(raw) and len(parts) < 2:
        if raw[pos:pos + 3] != b"\xff\xfe\xff":
            break
        n = raw[pos + 3]
        pos += 4
        if n == 0xFF:
            n, = struct.unpack_from("<H", raw, pos)
            pos += 2
        parts.append(raw[pos:pos + 2 * n].decode("utf-16-le", "replace").strip())
        pos += 2 * n
    parts += ["", ""]
    return parts[0], parts[1]


def _units(raw):
    """Byte 4 of the material stream is 0 for inches and 1 for millimetres."""
    if len(raw) < 6 or struct.unpack_from("<I", raw, 0)[0] not in (5, 7, 8):
        return None
    return {0: "in", 1: "mm"}.get(raw[4])


def _read_vectors(ar, doc):
    ar.u32()
    ar.u32()
    for _ in range(ar.count("layer", each=2)):
        name = ar.object_header()
        if name != "vcCadLayer":
            raise UnsupportedError("expected a layer, found %r (offset %d)" % (name, ar.pos))
        doc.layers.append(_layer(ar, doc))
    if len(ar.data) - ar.pos >= 36:
        ar.u32()
        doc.material = (ar.f64(), ar.f64(), ar.f64(), ar.f64())


def _layer(ar, doc):
    ar.expect_u32((4,), "layer")
    ar.raw(16)
    layer = Layer(name=ar.string())
    rgb = ar.u32()
    layer.color = (rgb & 0xFF, (rgb >> 8) & 0xFF, (rgb >> 16) & 0xFF)
    ar.raw(6)
    for _ in range(ar.count("object", each=2)):
        layer.items.append(_item(ar))
    ar.raw(3)
    layer.is_preview = bool(layer.items) and all(i.kind == "preview" for i in layer.items)
    if not layer.items and layer.name == PREVIEW_LAYER:
        layer.is_preview = True
    return layer


def _item(ar):
    name = ar.object_header()
    if name == "vcCadContour":
        _item_base(ar)
        ar.expect_u32((2,), "contour object")
        item = Item("contour", [_contour_object(ar)])
        item.tabs = _tabs(ar)
        return item
    if name == "vcCadPolyline":
        _item_base(ar)
        ar.expect_u32((2,), "polyline object")
        item = Item("polyline", [_contour_object(ar)])
        item.tabs = _tabs(ar)
        ar.u32()
        return item
    if name == "vcCadToolpathPreview":
        _item_base(ar)
        ar.expect_u32((4,), "toolpath preview")
        ar.raw(16)
        if ar.object_header() != "vdContourGroup":
            raise UnsupportedError("toolpath preview without a contour group (offset %d)" % ar.pos)
        ar.expect_u32((3,), "contour group")
        paths = [_contour_object(ar) for _ in range(ar.count("contour", each=2))]
        ar.raw(32)
        return Item("preview", paths)
    if name == "vcCadObjectGroup":
        _item_base(ar)
        ar.expect_u32((1,), "object group")
        group = Item("group")
        for _ in range(ar.count("grouped object", each=2)):
            group.paths.extend(_item(ar).paths)
        return group
    if name == "txtBlock":
        return _text_block(ar)
    if name == "vcCadLinearDimensioningObject":
        _item_base(ar)
        ar.expect_u32((1,), "dimension")
        ar.raw(5)
        dimension = Item("dimension")
        for _ in range(ar.count("dimension part", each=2)):
            part = _item(ar)
            dimension.paths.extend(part.paths)
            dimension.parts.append(part)
        # Fonts, sizes, the dimension layer name, then five anchor points.
        ar.expect_u32((2,), "dimension style")
        ar.raw(4 + 1)
        ar.string()
        ar.string()
        ar.raw(1 + 8 + 8 + 4 + 8 + 1)
        ar.string()
        ar.string()
        ar.raw(1 + 4 + 10 * 8)
        return dimension
    if name in ("vcCadBitmap", "vcCadModelPreview", "vcActiveComponentPreview"):
        _item_base(ar)
        # Older releases pack the image with LZMA and follow it with tables of unknown length.
        if name != "vcCadBitmap" or ar.u32() != 6:
            raise UnsupportedError(
                "this file embeds a picture or 3D model preview in a layout this reader "
                "cannot step over yet (offset %d)" % ar.pos)
        ar.raw(11 * 8)
        _item(ar)
        ar.raw(4)
        ar.string()
        ar.raw(2 + 4)
        ar.raw(ar.count("image data"))
        return Item("picture")
    raise UnsupportedError(
        "this file has a %r object, which this reader cannot decode yet (offset %d)"
        % (name, ar.pos))


def _text_block(ar):
    """Text keeps its glyph outlines per character, in each glyph's own frame."""
    _item_base(ar)
    block_version = ar.expect_u32((4, 6), "text block")
    lines = []
    for _ in range(ar.count("text line", each=2)):
        if ar.object_header() != "txtLine":
            raise UnsupportedError("text block holds an unknown record (offset %d)" % ar.pos)
        ar.expect_u32((1, 2), "text line")
        glyphs = []
        for _ in range(ar.count("word", each=2)):
            if ar.object_header() != "txtWord":
                raise UnsupportedError("text line holds an unknown record (offset %d)" % ar.pos)
            ar.expect_u32((1,), "word")
            for _ in range(ar.count("character", each=2)):
                if ar.object_header() != "txtChar":
                    raise UnsupportedError("word holds an unknown record (offset %d)" % ar.pos)
                char_version = ar.expect_u32((3, 4), "character")
                ar.u32()
                ar.string()
                advance = ar.f64()
                if ar.object_header() != "vdContourGroup":
                    raise UnsupportedError("character without outlines (offset %d)" % ar.pos)
                ar.expect_u32((3,), "contour group")
                outlines = [_contour_object(ar) for _ in range(ar.count("contour", each=2))]
                ar.raw(4 + 13)
                metrics = [ar.f64() for _ in range(8 if char_version >= 4 else 7)]
                glyphs.append((advance, outlines, metrics))
        ar.raw(8)
        ar.string()
        ar.raw((5 if block_version >= 6 else 4) * 8)
        lines.append(glyphs)
    ar.raw(2 * 8 + 4)
    base = None
    name = ar.object_header()
    if name == "txtBaseCurve":
        ar.expect_u32((1,), "text base curve")
        base = _contour_object(ar)
    elif name is not None:
        raise UnsupportedError("text block carries a %r record (offset %d)" % (name, ar.pos))
    ar.raw(9)
    # The block's own transform, then its inverse.
    matrix = [ar.f64() for _ in range(9)]
    ar.raw(9 * 8 + (16 if block_version >= 6 else 8))
    item = Item("text")
    if block_version >= 6:
        item.paths, problem = text.layout(matrix, lines, base)
    else:
        # Older releases relate the base line to the glyphs differently; not worked out yet.
        problem = "text saved by a release before version 9"
    if problem:
        ar.warnings.append("left out %s, which this reader cannot place yet" % problem)
    return item


def _item_base(ar):
    version = ar.expect_u32((5, 6, 7, 8, 9, 10), "drawing object")
    ar.raw(16 + 16 + 20)
    if ar.i32() != -1:
        raise UnsupportedError("drawing object header is not the known layout (offset %d)" % ar.pos)
    name = ar.object_header()
    if name == "utParameterList":
        ar.expect_u32((1,), "parameter list")
        for _ in range(ar.count("parameter", each=2)):
            if ar.object_header() != "utParameter":
                raise UnsupportedError("parameter list holds an unknown record (offset %d)" % ar.pos)
            ar.expect_u32((2,), "parameter")
            ar.string()
            kind = ar.u32()
            if kind == PARAM_STRING:
                ar.string()
            elif kind in PARAM_SIZE:
                ar.raw(PARAM_SIZE[kind])
            else:
                raise UnsupportedError("parameter of type %d (offset %d)" % (kind, ar.pos))
    elif name is not None:
        raise UnsupportedError("drawing object carries a %r record (offset %d)" % (name, ar.pos))
    if version == 5:
        ar.raw(4)
        return None
    ar.raw((4 if version >= 10 else 8) + 8 + 8)
    if version <= 7:
        ar.raw(4 if version == 7 else 0)
        return None
    _tagged_version(ar, (1,))
    ar.raw(ar.count("id text"))
    if version == 8:
        return None
    has_transform = ar.u32()
    matrix = None
    if has_transform == 1:
        # Original bounding box, then the 3x3 transform already applied to the stored spans.
        ar.raw(4 * 8)
        matrix = [ar.f64() for _ in range(9)]
    elif has_transform != 0:
        raise UnsupportedError("drawing object transform flag %d (offset %d)" % (has_transform, ar.pos))
    if version >= 10:
        _tagged_version(ar, (1,))
        ar.raw(ar.count("sheet id text"))
    return matrix


def _tagged_version(ar, allowed):
    """Newer records label their version: a length-prefixed "Vectric__Version", then the number."""
    label = ar.raw(ar.count("version label"))
    if label != b"Vectric__Version":
        raise UnsupportedError("expected a version label, found %r (offset %d)" % (label[:24], ar.pos))
    return ar.expect_u32(allowed, "labelled record")


def _tabs(ar):
    n = ar.count("tab", each=2)
    for _ in range(n):
        if ar.object_header() != "vcToolpathTab":
            raise UnsupportedError("unknown record after a contour (offset %d)" % ar.pos)
        ar.expect_u32((1,), "tab")
        ar.raw(16)
    return n


SPAN_CLASSES = {"vdLineSpan": SPAN_LINE, "vdArcSpan": SPAN_ARC, "vdBezierSpan": SPAN_BEZIER,
                "vdTabLineSpan": SPAN_TAB_LINE, "vdTabArcSpan": SPAN_TAB_ARC,
                "vdSpan": SPAN_POINT}


def _contour_object(ar):
    name = ar.object_header()
    if name != "vdContour":
        raise UnsupportedError("expected contour geometry, found %r (offset %d)" % (name, ar.pos))
    version = ar.expect_u32((3, 4, 6, 7), "contour")
    ar.raw(4 + 8 + 1 + 8 + 1)
    path = Path()
    for _ in range(ar.count("span", each=50)):
        if version >= 6:
            kind = ar.u8()
            if kind not in (SPAN_LINE, SPAN_ARC, SPAN_BEZIER, SPAN_TAB_LINE, SPAN_TAB_ARC):
                raise UnsupportedError("span type %d is not decoded yet (offset %d)" % (kind, ar.pos))
        else:
            # Older files write every span as its own object.
            name = ar.object_header()
            if name not in SPAN_CLASSES:
                raise UnsupportedError("%r spans are not decoded yet (offset %d)" % (name, ar.pos))
            kind = SPAN_CLASSES[name]
        path.spans.append(_span(ar, kind))
    ar.raw(16 + 4)
    if version >= 4:
        ar.raw(16 * ar.u16())
    return path


def _span(ar, kind):
    ar.expect_u32((2,), "span")
    ar.u32()
    start = (ar.f64(), ar.f64(), ar.f64())
    end = (ar.f64(), ar.f64(), ar.f64())
    if not all(abs(v) < COORD_LIMIT for v in start[:2] + end[:2]):
        raise CrvError("span has a coordinate that is not a usable number (offset %d)" % ar.pos)
    bulge, control = 0.0, None
    if kind == SPAN_POINT:
        return Span(start, end)
    if kind == SPAN_LINE:
        # A lone point is stored as a line with no trailing block.
        if ar.data[ar.pos:ar.pos + 4] == b"\x01\x00\x00\x00":
            ar.raw(4)
        return Span(start, end)
    ar.expect_u32((1,), "span detail")
    if kind in (SPAN_ARC, SPAN_TAB_ARC):
        bulge = ar.f64()
        if not abs(bulge) < BULGE_LIMIT:
            raise CrvError("arc has a bulge that is not a usable number (offset %d)" % ar.pos)
    elif kind == SPAN_BEZIER:
        control = ((ar.f64(), ar.f64()), (ar.f64(), ar.f64()))
        if not all(abs(v) < COORD_LIMIT for v in control[0] + control[1]):
            raise CrvError("curve has a control point that is not a usable number (offset %d)" % ar.pos)
    if kind in (SPAN_TAB_LINE, SPAN_TAB_ARC):
        ar.expect_u32((1, 2), "tab detail")
        ar.raw(24)
    return Span(start, end, bulge, control)
