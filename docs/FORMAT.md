# The CRV file layout, as far as crv2svg reads it

These are working notes from reading project files, not a spec from Vectric. They come
from the bytes of 156 public project files saved by releases 6 through 11 of Aspire,
VCarve, Cut2D and PartWorks. Where a field is skipped without being understood, it says
so. Corrections are welcome.

All integers are little-endian. `f64` is an IEEE double. A GUID is 16 raw bytes.

## Container

A `.crv` or `.crv3d` file is a compound file (the OLE2 container Microsoft documents as
MS-CFB). The streams seen:

| Stream | Contents |
| --- | --- |
| `VersionData/Version` | Product name, version, build date and licence owner as strings |
| `VectorData/2dDataV2` | Layers and their 2D vectors. This is the stream crv2svg reads |
| `VectorData/MaterialSize` | Job size, thickness and units |
| `VectorData/DocumentData` | Guides and snap grid |
| `PreviewData/Preview2D_GIF` | A 512 x 256 GIF thumbnail of the job |
| `PreviewData/Preview3D_PNG` | Thumbnail of the 3D view, in files with a model |
| `Toolpaths/*`, `ModelObjects/*`, `SideData/*`, `Settings` | Not read |

`MaterialSize` starts with a `u32` version (5, 7 or 8), then a `u8` that is 0 for inches and
1 for millimetres, one more `u8`, and six `f64`: the minimum corner x, y, z and the
maximum corner x, y, z.

## Object stream

`2dDataV2` is written with MFC's `CArchive`, so objects carry class tags:

- `u16 0x0000`: a null object.
- `u16 0xFFFF`, `u16 schema`, `u16 length`, class name in ASCII: first use of a class. The
  object's fields follow.
- `u16 0x8000 | n`: an object of the class that took slot `n`.
- `u16 0x7FFF`, `u32 0x80000000 | n`: the same, once slots pass 32766.

Classes and objects share one counter that starts at 1. Each new class takes a slot and so
does each object, which is how `n` is resolved.

Strings are `FF FE FF`, a length byte (`FF` then a `u16` when 255 or more), then that many
UTF-16 code units. A lone `00` byte is an empty string.

From release 9 on, some records label their version instead of using a bare number: a
`u32` length, the ASCII text `Vectric__Version`, then the `u32` version. Below this is
written `label(n)`. An id written as text is a `u32` length and a 36-character UUID.

## Stream header and layers

```
u32   1, or 2 from release 11
u32   2, 3, 4 or 5 (grows with the release)
u32   layer count
layer objects (class vcCadLayer)
u32   1
f64   material x, y, width, height
...   a vcCadSheet object and more, not read
```

### vcCadLayer

```
u32   4            version
GUID  layer id
str   name
u32   colour, 0x00BBGGRR
u8[6] not understood (zero, then 00 01)
u32   object count
objects
u8[3] not understood
```

Toolpath previews live in their own layer, made only of `vcCadToolpathPreview` objects.
Its name is translated ("Toolpath Previews", "Previsualiza Camino Herramienta"), so it is
recognised by what it holds.

## Drawing objects

Every drawing object starts with the same header. Its version tells the release apart:

| Header version | Contour version | Written by release |
| --- | --- | --- |
| 5 | 3 | 6.0, 6.5, 7.0 |
| 6 | 4 | 7.5 |
| 7 | 4 | 8.0 |
| 7 | 6 | 8.5 |
| 8 | 6 | 8.9 beta |
| 8 | 7 | 9.5 |
| 9 | 7 | 10.5 |
| 10 | 7 | 11.0, 11.5 |

```
u32   header version
GUID  object id
GUID  id of the layer it sits on
u8[20] colour and flags, not understood
i32   -1
object utParameterList, or null
```

What follows depends on the version:

- 5: `u32 0`.
- 6: `u32 0`, `u32 1`, `f64 x`, `f64 y`.
- 7: the same, then `u32 0`.
- 8: `u32 0`, `u32 1`, `f64 x`, `f64 y`, `label(1)`, id as text.
- 9: as 8, then `u32 1`, four `f64` (the object's box before it was transformed) and nine
  `f64` (a 3 x 3 transform, row by row, translation in the third column).
- 10: as 9 without the leading `u32 0`, and with a second `label(1)` and id at the end.

The spans of a contour are stored after the transform has been applied. The box and
matrix describe how the object got there, so a reader does not apply them again.

`utParameterList` is `u32 1`, a `u32` count, then `utParameter` objects. Each parameter is
`u32 2`, a name string, a `u32` type and a value: type 0 is an `f64`, 1 a `u32`, 2 a `u8`
flag, 3 a string.

### vcCadContour and vcCadPolyline

```
u32   2            version
object vdContour
u32   tab count
vcToolpathTab objects, each u32 1 then 16 bytes not understood
u32   (vcCadPolyline only) not understood, seen as 1
```

### vcCadObjectGroup

```
u32   1            version
u32   object count
drawing objects, which may be groups themselves
```

### vcCadToolpathPreview

```
u32   4            version
u8[16] not understood
object vdContourGroup: u32 3, u32 count, vdContour objects
u8[32] not understood, holds a tool diameter
```

### vcCadBitmap

Release 9 and later (version 6):

```
u32   6            version
f64[11] a transform and a point
object vcCadContour, the picture's outline
u32   not understood
str   the path the picture was imported from
u8[6] not understood
u32   byte count
bytes the image file, usually a PNG
```

Earlier releases (version 5), and `vcCadModelPreview` and `vcActiveComponentPreview`,
pack the image with LZMA and follow it with colour tables whose length is not known.
crv2svg cannot step over those yet and stops.

### vcCadLinearDimensioningObject

```
u32   1            version
u8[5] not understood
u32   part count
drawing objects: a text block, then the arrows and extension lines
u32   2            style version
...   two font names, sizes, the dimension layer name and five anchor points
```

## vdContour

```
u32   version: 3, 4, 6 or 7 (see the table above)
i32   not understood (-1 on drawn vectors)
f64   tolerance
u8    flag
f64   z
u8    flag
u32   span count
spans
GUID  zero on drawn vectors
i32   not understood
u16   count, then that many GUIDs (version 4 and later)
```

### Spans

Versions 3 and 4 write each span as an object of class `vdLineSpan`, `vdArcSpan`,
`vdBezierSpan`, `vdTabLineSpan` or `vdSpan`. Versions 6 and 7 write a `u8` type instead:
0 line, 1 arc, 2 Bezier, 3 tab line, 4 tab arc. Either way the fields are the same:

```
u32   2            version
u32   flags: 1 line, 0 arc, 6 Bezier, 7 tab line, 17 tab arc, 5 a lone point
f64   start x, y, z
f64   end x, y, z
```

Then, depending on the kind:

- Line: `u32 1`.
- Lone point (`vdSpan`, or a line with flags 5): nothing.
- Arc: `u32 1`, `f64 bulge`.
- Bezier: `u32 1`, then the two inner control points as `f64` x, y, x, y.
- Tab line: `u32 1`, `u32 2`, three `f64`.
- Tab arc: `u32 1`, `f64 bulge`, `u32 1`, three `f64`.

The bulge is the same one DXF uses: the tangent of a quarter of the arc's included angle,
positive when the arc runs counter-clockwise from start to end. A bulge of 1 is a half
circle, and a full circle is stored as two of them. Tab spans only turn up in toolpath
previews, where the cutter lifts over a holding tab.

A contour is closed when its last span ends where its first one starts.

## Text

A `txtBlock` keeps the outline of each character, not finished vectors.

```
drawing object header
u32   block version: 4 (before release 9) or 6
u32   line count
per line, a txtLine object:
    u32   1 or 2       version
    u32   word count
    per word, a txtWord object:
        u32   1            version
        u32   character count
        per character, a txtChar object:
            u32   3 or 4       version
            u32   character code
            str   font description
            f64   advance
            object vdContourGroup: u32 3, u32 count, vdContour outlines
            u8[17] not understood
            f64[7] metrics, eight of them in version 4
    f64   not understood
    str   font description
    f64[4] sizes, five of them in block version 6
f64[2] not understood
i32   -1
object txtBaseCurve (u32 1, then a vdContour), or null
u8[9] not understood
f64[9] the block's transform
f64[9] its inverse
u8[8] not understood, sixteen bytes in block version 6
```

Outlines are in each glyph's own frame: y is 0 on the base line and x is measured from a
point inside the glyph. The first metric is how far that point sits from the pen, and the
pen moves on by the advance after each character.

In block version 6 the base curve is a straight line that runs from the left edge of the
first glyph's ink to the right edge of the last one's. That fixes where the line of text
sits: lay the glyphs out from the pen, shift them so the leftmost ink lands on the base
line's start, then apply the block's transform. This was checked on real files, where the
laid-out ink width matches the base line length to four decimals.

In block version 4 the base line is about a tenth longer than the ink and that rule does
not hold. crv2svg reads those blocks but leaves their text out. It also leaves out text
with more than one line and text on a curve, because the line spacing and the curve
mapping have not been worked out.

## What has not been seen

Two-sided jobs, multiple sheets, arc and angular dimensions, and anything written by
release 12. crv2svg stops with a named error when it meets a class or version it has no
layout for, because nothing in the stream says how long an unknown record is, so it
cannot be skipped safely.
