"""Build small synthetic CRV projects for the tests. Mirrors the layout in docs/FORMAT.md."""

import struct

SECTOR, MINI, CUTOFF = 512, 64, 4096
END, FREE, FATSECT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD


def build_cfb(streams):
    """streams: {"Storage/Stream": bytes}. Returns the bytes of a compound file."""
    storages = {}
    for path, data in streams.items():
        storage, name = path.split("/")
        storages.setdefault(storage, []).append((name, data))

    entries = [dict(name="Root Entry", kind=5, child=FREE, right=FREE, start=END, size=0)]
    mini_blob, minifat, big = b"", [], []
    prev_storage = None
    for storage in sorted(storages, key=lambda n: (len(n), n.upper())):
        s_idx = len(entries)
        entries.append(dict(name=storage, kind=1, child=FREE, right=FREE, start=0, size=0))
        if prev_storage is None:
            entries[0]["child"] = s_idx
        else:
            entries[prev_storage]["right"] = s_idx
        prev_storage = s_idx
        prev_stream = None
        for name, data in sorted(storages[storage], key=lambda t: (len(t[0]), t[0].upper())):
            idx = len(entries)
            entry = dict(name=name, kind=2, child=FREE, right=FREE, start=END, size=len(data))
            if data and len(data) < CUTOFF:
                first = len(minifat)
                count = (len(data) + MINI - 1) // MINI
                minifat += [first + i + 1 for i in range(count - 1)] + [END]
                mini_blob += data.ljust(count * MINI, b"\0")
                entry["start"] = first
            elif data:
                big.append((idx, data))
            entries.append(entry)
            if prev_stream is None:
                entries[s_idx]["child"] = idx
            else:
                entries[prev_stream]["right"] = idx
            prev_stream = idx

    def sectors_for(n):
        return (n + SECTOR - 1) // SECTOR

    n_dir = sectors_for(len(entries) * 128)
    n_minifat = sectors_for(len(minifat) * 4)
    n_mini = sectors_for(len(mini_blob))
    n_big = sum(sectors_for(len(d)) for _, d in big)
    n_data = n_dir + n_minifat + n_mini + n_big
    n_fat = 1
    while n_fat * (SECTOR // 4) < n_data + n_fat:
        n_fat += 1
    assert n_fat <= 109

    fat = [FATSECT] * n_fat
    cursor = n_fat

    def alloc(count):
        nonlocal cursor
        start = cursor
        for i in range(count):
            fat.append(cursor + 1 if i < count - 1 else END)
            cursor += 1
        return start if count else END

    dir_start = alloc(n_dir)
    minifat_start = alloc(n_minifat)
    entries[0]["start"] = alloc(n_mini)
    entries[0]["size"] = len(mini_blob)
    body = []
    for idx, data in big:
        entries[idx]["start"] = alloc(sectors_for(len(data)))
        body.append(data.ljust(sectors_for(len(data)) * SECTOR, b"\0"))

    dir_blob = b""
    for e in entries:
        name = e["name"].encode("utf-16-le") + b"\0\0"
        rec = name.ljust(64, b"\0") + struct.pack("<HBB", len(name), e["kind"], 1)
        rec += struct.pack("<III", FREE, e["right"], e["child"])
        rec += b"\0" * 36
        rec += struct.pack("<IQ", e["start"], e["size"])
        dir_blob += rec
    dir_blob = dir_blob.ljust(n_dir * SECTOR, b"\xff" * 0 + b"\0")
    minifat_blob = struct.pack("<%dI" % len(minifat), *minifat).ljust(n_minifat * SECTOR, b"\xff")
    fat += [FREE] * (n_fat * (SECTOR // 4) - len(fat))
    fat_blob = struct.pack("<%dI" % len(fat), *fat)

    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16
    header += struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
    header += struct.pack("<III", 0, n_fat, dir_start) + struct.pack("<I", 0)
    header += struct.pack("<III", CUTOFF, minifat_start, n_minifat)
    header += struct.pack("<II", END, 0)
    header += struct.pack("<109I", *(list(range(n_fat)) + [FREE] * (109 - n_fat)))
    assert len(header) == 512
    return (header + fat_blob + dir_blob + minifat_blob
            + mini_blob.ljust(n_mini * SECTOR, b"\0") + b"".join(body))


class Writer:
    def __init__(self):
        self.out = bytearray()
        self.classes = {}
        self.slots = 1
        self.modern = False
        self.base = 7

    def u8(self, v):
        self.out += struct.pack("<B", v)

    def u16(self, v):
        self.out += struct.pack("<H", v)

    def u32(self, v):
        self.out += struct.pack("<I", v)

    def i32(self, v):
        self.out += struct.pack("<i", v)

    def f64(self, v):
        self.out += struct.pack("<d", v)

    def raw(self, b):
        self.out += b

    def string(self, text):
        self.out += b"\xff\xfe\xff"
        if len(text) < 255:
            self.u8(len(text))
        else:
            self.u8(0xFF)
            self.u16(len(text))
        self.out += text.encode("utf-16-le")

    def obj(self, name):
        if name not in self.classes:
            self.u16(0xFFFF)
            self.u16(1)
            self.u16(len(name))
            self.out += name.encode("ascii")
            self.classes[name] = self.slots
            self.slots += 1
        else:
            index = self.classes[name]
            if index < 0x7FFF:
                self.u16(0x8000 | index)
            else:
                self.u16(0x7FFF)
                self.u32(0x80000000 | index)
        self.slots += 1

    def null(self):
        self.u16(0)


def line(a, b):
    return ("line", a, b, 0.0)


def arc(a, b, bulge):
    return ("arc", a, b, bulge)


def point(a):
    return ("point", a, a, 0.0)


def ramp(a, b):
    return ("ramp", a, b, 0.0)


def tabarc(a, b, bulge):
    return ("tabarc", a, b, bulge)


def curve(a, c1, c2, b):
    return ("curve", a, b, (c1, c2))


IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def _xyz(w, p):
    w.f64(p[0])
    w.f64(p[1])
    w.f64(p[2] if len(p) > 2 else 0.0)


def _contour(w, spans, span_type_override=None):
    w.obj("vdContour")
    contour_version = {5: 3, 6: 4}.get(w.base, 7 if w.base >= 8 else 6)
    w.u32(contour_version)
    w.i32(-1)
    w.f64(4e-5)
    w.u8(0)
    w.f64(0.0)
    w.u8(0)
    w.u32(len(spans))
    for kind, a, b, bulge in spans:
        code = {"line": 0, "point": 0, "arc": 1, "curve": 2, "ramp": 3, "tabarc": 4}[kind]
        if contour_version >= 6:
            w.u8(span_type_override if span_type_override is not None else code)
        else:
            w.obj({"line": "vdLineSpan", "point": "vdSpan", "arc": "vdArcSpan",
                   "curve": "vdBezierSpan", "ramp": "vdTabLineSpan",
                   "tabarc": "vdTabArcSpan"}[kind] if span_type_override is None else "vdMystery")
        w.u32(2)
        w.u32({"line": 1, "point": 5, "arc": 0, "curve": 6, "ramp": 7, "tabarc": 17}[kind])
        _xyz(w, a)
        _xyz(w, b)
        if kind == "point":
            continue
        w.u32(1)
        if kind in ("arc", "tabarc"):
            w.f64(bulge)
            if kind == "tabarc":
                w.u32(1)
                w.f64(0.25)
                w.f64(1.0)
                w.f64(1.0)
        elif kind == "curve":
            for cx, cy in bulge:
                w.f64(cx)
                w.f64(cy)
        elif kind == "ramp":
            w.u32(2)
            w.f64(0.11)
            w.f64(1.0)
            w.f64(1.0)
    w.raw(b"\0" * 16)
    w.i32(-1)
    if contour_version >= 4:
        w.u16(0)


def _base(w, params, matrix=None):
    w.u32(w.base)
    w.raw(b"\x11" * 16)
    w.raw(b"\x22" * 16)
    w.u32(0)
    w.u32(0)
    w.u32(0x82)
    w.u32(0x2A)
    w.u32(0)
    w.i32(-1)
    if params:
        w.obj("utParameterList")
        w.u32(1)
        w.u32(len(params))
        for name, value in params:
            w.obj("utParameter")
            w.u32(2)
            w.string(name)
            if isinstance(value, bool):
                w.u32(2)
                w.u8(int(value))
            elif isinstance(value, int):
                w.u32(1)
                w.u32(value)
            elif isinstance(value, str):
                w.u32(3)
                w.string(value)
            else:
                w.u32(0)
                w.f64(value)
    else:
        w.null()
    if w.base == 5:
        w.u32(0)
        return
    if w.base < 10:
        w.u32(0)
    w.u32(1)
    w.f64(1.7976931348623157e308)
    w.f64(1.7976931348623157e308)
    if w.base == 6:
        return
    if w.base == 7:
        w.u32(0)
        return
    uuid = b"00000000-0000-0000-0000-000000000000"
    _label(w, 1)
    w.u32(len(uuid))
    w.raw(uuid)
    if w.base == 8:
        return
    w.u32(1)
    for v in (0.0, 0.0, 1.0, 1.0):
        w.f64(v)
    for v in matrix or IDENTITY:
        w.f64(v)
    if w.base >= 10:
        _label(w, 1)
        w.u32(len(uuid))
        w.raw(uuid)


def _label(w, version):
    w.u32(16)
    w.raw(b"Vectric__Version")
    w.u32(version)


def _group_tail(w, metrics):
    w.u32(1)
    w.raw(b"\0" * 13)
    for v in metrics:
        w.f64(v)


def _text(w, item):
    w.obj("txtBlock")
    _base(w, [("_txtAL_Version", 1), ("_txtAL_InMM", True), ("_txtAL_font_name", "Test Sans"),
              ("_txtAL_width", 12.0)], item.get("matrix"))
    old = w.base < 7
    w.u32(4 if old else 6)
    lines = item["lines"]
    w.u32(len(lines))
    for glyphs in lines:
        w.obj("txtLine")
        w.u32(1 if old else 2)
        w.u32(1)
        w.obj("txtWord")
        w.u32(1)
        w.u32(len(glyphs))
        for advance, offset, outlines in glyphs:
            w.obj("txtChar")
            w.u32(3 if old else 4)
            w.u32(65)
            w.string("3,0Test Sans,,1.0000")
            w.f64(advance)
            w.obj("vdContourGroup")
            w.u32(3)
            w.u32(len(outlines))
            for spans in outlines:
                _contour(w, spans)
            _group_tail(w, [offset, 0.0, 7.0, 7.0, 7.0, advance, 1.0] + ([] if old else [0.0]))
        w.f64(0.0)
        w.string("3,0Test Sans,,1.0000")
        for v in (7.0, 7.0, 7.0, 7.0) + (() if old else (1.0,)):
            w.f64(v)
    for v in (0.0, 0.0):
        w.f64(v)
    w.i32(-1)
    if item.get("base"):
        w.obj("txtBaseCurve")
        w.u32(1)
        _contour(w, item["base"])
    else:
        w.null()
    w.raw(b"\x02\0\0\0\0\0\0\0\x01")
    for v in (item.get("matrix") or IDENTITY) + IDENTITY:
        w.f64(v)
    w.raw(b"\0" * (8 if old else 16))


def _item(w, item):
    kind = item["kind"]
    if kind == "text":
        _text(w, item)
    elif kind == "group":
        w.obj("vcCadObjectGroup")
        _base(w, None)
        w.u32(1)
        w.u32(len(item["items"]))
        for child in item["items"]:
            _item(w, child)
    elif kind == "bitmap":
        w.obj("vcCadBitmap")
        _base(w, [("fvfUseColours", False), ("fvfNumColours", 16), ("fvfTolerance", 0.2)])
        w.u32(6)
        for v in IDENTITY + [0.0, 0.0]:
            w.f64(v)
        _item(w, {"kind": "contour", "spans": square(0, 0, 3)})
        w.u32(120)
        w.string("C:\\Users\\someone\\Pictures\\photo.png")
        w.raw(b"\x00\x01")
        w.u32(13)
        w.u32(len(item["image"]))
        w.raw(item["image"])
    elif kind == "dimension":
        w.obj("vcCadLinearDimensioningObject")
        _base(w, None)
        w.u32(1)
        w.raw(b"\x01\0\0\0\x01")
        w.u32(len(item["parts"]))
        for child in item["parts"]:
            _item(w, child)
        w.u32(2)
        w.raw(b"\x02\0\0\0\x01")
        w.string("Times New Roman")
        w.string("Century")
        w.u8(0)
        w.f64(1.0)
        w.f64(5.0)
        w.u32(3)
        w.f64(2.5)
        w.u8(0)
        w.string("")
        w.string("Dimensions")
        w.u8(1)
        w.u32(2)
        for _ in range(10):
            w.f64(0.5)
    elif kind == "contour":
        w.obj("vcCadContour")
        _base(w, item.get("params"))
        w.u32(2)
        _contour(w, item["spans"], item.get("span_type"))
        w.u32(item.get("tabs", 0))
        for _ in range(item.get("tabs", 0)):
            w.obj("vcToolpathTab")
            w.u32(1)
            w.raw(b"\0" * 12 + b"\x01\0\0\0")
    elif kind == "polyline":
        w.obj("vcCadPolyline")
        _base(w, item.get("params"))
        w.u32(2)
        _contour(w, item["spans"])
        w.u32(0)
        w.u32(1)
    elif kind == "preview":
        w.obj("vcCadToolpathPreview")
        _base(w, None)
        w.u32(4)
        w.raw(b"\x33" * 16)
        w.obj("vdContourGroup")
        w.u32(3)
        w.u32(len(item["paths"]))
        for spans in item["paths"]:
            _contour(w, spans)
        _group_tail(w, [0.25])
        w.raw(b"\x00\x01\x00\x02\x00\x00\x00")
    else:
        w.obj(kind)
        w.raw(item.get("body", b""))


def build_vectors(layers, material=(0.0, 0.0, 24.0, 12.0), modern=False, base=None):
    w = Writer()
    w.base = base or (9 if modern else 7)
    w.modern = w.base >= 9
    w.u32(1)
    w.u32(4 if w.modern else 3)
    w.u32(len(layers))
    for layer in layers:
        w.obj("vcCadLayer")
        w.u32(4)
        w.raw(b"\x44" * 16)
        w.string(layer["name"])
        r, g, b = layer.get("color", (0, 0, 0))
        w.u32(r | (g << 8) | (b << 16))
        w.u32(0)
        w.raw(b"\x00\x01")
        w.u32(len(layer["items"]))
        for item in layer["items"]:
            _item(w, item)
        w.raw(b"\x01\x00\x00")
    if material:
        w.u32(1)
        for v in material:
            w.f64(v)
        w.raw(b"\0" * 220)
    return bytes(w.out)


def build_version(product="VCarve Pro", version="8.505"):
    w = Writer()
    w.u16(1)
    w.u16(0)
    for text in (product, version + "  ", "Jun 22 2016", "", "Test Owner"):
        w.string(text)
    return bytes(w.out)


def build_material(material, units, modern):
    x, y, width, height = material
    out = struct.pack("<IBB", 8 if modern else 5, {"in": 0, "mm": 1}[units], 1)
    out += struct.pack("<6d", x, y, -0.75, x + width, y + height, 0.0)
    return out + b"\0" * 8


def build_crv(layers, material=(0.0, 0.0, 24.0, 12.0), preview=b"GIF89a-not-a-real-image",
              product="VCarve Pro", version="8.505", extra_streams=None, modern=False,
              units="in", base=None):
    streams = {
        "VectorData/2dDataV2": build_vectors(layers, material, modern, base),
        "VersionData/Version": build_version(product, version),
        "PreviewData/Preview2D_GIF": preview,
    }
    if material and units:
        streams["VectorData/MaterialSize"] = build_material(material, units, modern)
    streams.update(extra_streams or {})
    return build_cfb(streams)


def square(x, y, size):
    a, b, c, d = (x, y), (x + size, y), (x + size, y + size), (x, y + size)
    return [line(a, b), line(b, c), line(c, d), line(d, a)]


def circle(cx, cy, r):
    left, right = (cx - r, cy), (cx + r, cy)
    return [arc(left, right, 1.0), arc(right, left, 1.0)]
