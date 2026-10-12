# crv2svg

Convert the 2D vectors in a Vectric project file (`.crv`, `.crv3d`) to SVG or DXF, without
owning the software that wrote it.

VCarve, Aspire and Cut2D save designs in their own format, and the only way to get the
drawing back out has been to open the file in a licensed copy and export it. People on
other CAM software who are handed a `.crv`, or who let a licence lapse, are stuck. crv2svg
reads the file directly.

It is a small Python package with no dependencies. It only reads files. It never runs or
needs any Vectric software.

## Install

```
pip install git+https://github.com/munzzyy/crv2svg
```

Python 3.9 or newer.

## Use

```
crv2svg sign.crv                  # writes sign.svg next to it
crv2svg sign.crv -o sign.dxf      # DXF instead
crv2svg *.crv -f dxf              # a whole folder
crv2svg sign.crv --info           # what is in the file
crv2svg sign.crv --layer "Cut out" --layer Pockets
crv2svg sign.crv --extract-preview thumb.gif
crv2svg parts.crv                 # a job with 3 sheets writes parts-sheet1.svg to parts-sheet3.svg
crv2svg parts.crv --sheet 2 -o second.dxf
```

`--info` prints the release that wrote the file, the job size and units, and each layer:

```
sign.crv
  written by: VCarve Pro 8.505
  material:   96 x 48 in, origin at (0, 0)
  layer 'Toolpath Previews'                 3 objects    442 segments  [toolpath preview, skipped by default]
  layer 'cutout 1/4"'                       5 objects    220 segments
  layer 'drill holes 3/16"'                17 objects     68 segments
```

From Python:

```python
import crv2svg

doc = crv2svg.read_file("sign.crv")
open("sign.svg", "w").write(crv2svg.to_svg(doc))
open("sign.dxf", "w").write(crv2svg.to_dxf(doc))
```

## In the browser

`web/index.html` does the same job in a page, for people who will not install Python. Open
it in a browser, or serve the folder with `python3 -m http.server --directory web`. Drop
one or more `.crv` files on it, pick the layers, and download SVG or DXF. To get one
self-contained file you can hand around, run `python3 web/build.py`, which writes
`dist/crv2svg.html`.

Nothing is uploaded. The conversion runs in the page, and the page's security policy
forbids any network request. `web/crv2svg.js` is the same reader and writers rewritten in
JavaScript with no dependencies. `tests/test_web_parity.py` runs both engines over the same
files and fails unless the SVG, the DXF and the error messages are identical, byte for
byte. It needs Node and skips itself without it.

## What you get

- Lines, arcs and Bezier curves, on their original layers with the layer colours.
- Real size. The SVG page is the job's material in inches or millimetres, whichever the
  project used. `--units` overrides it.
- Arcs stay arcs. In SVG they are arc commands. In DXF they are polyline bulges, so a
  CAM program sees a true radius and not a string of short lines.
- DXF is the plain R12 flavour that nearly everything opens. It has no Bezier entity, so
  curves are flattened there to within 0.0005 in or 0.01 mm.
- A job with several sheets gives one file per sheet. Vectric keeps every sheet in the
  same coordinates, so one file for all of them would be a pile of overlapping parts.
- Shapes that Vectric treats as closed come out closed.
- Grouped objects come out as their parts. Dimension lines come out as drawn.
- Toolpath previews are left out unless you pass `--include-previews`.

## What it reads

Tested on 156 project files that people have published, saved by Aspire, VCarve Pro,
VCarve Desktop, Cut2D and PartWorks releases from 6.0 (2010) to 11.5 (2023). All 156
convert. Checks behind that:

- Vectric stores a thumbnail of the job in each file. For files from four releases, the
  SVG was laid beside that thumbnail and matched it, text included.
- Where a repository holds Vectric's own DXF export beside the project, every point
  crv2svg reads is in that DXF to three decimals. The largest such file has 34,277.

## What it does not do

- Toolpaths, tools, feeds and 3D models. This is the drawing only.
- Text saved by releases before 9 is left out by default. Those releases store letters
  along a line that is a tenth longer than the text, and which end the slack sits on is
  not known. `--approximate-text` puts the text in the middle of that line, which can be
  off by up to a twentieth of the text's width. Check it against the original before
  cutting. Text converted to curves inside Vectric is ordinary vectors and is exact.
- Text with more than one line and text on a curve are left out. crv2svg says so when it
  happens.
- Embedded pictures are not exported.
- Release 12 has not been tested. If a file fails, the message names the record that
  stopped it. Please open an issue with that message, and the file if you can share it.
- It does not write `.crv` files.

A record it has no layout for stops the file with an error that names it, instead of
writing a drawing with pieces missing. `--partial` keeps the layers read before that
point. Exit status is 0 when everything converted, 1 when any file could not be read, and
2 when the worst that happened was a `--partial` result.

## The format

`docs/FORMAT.md` is a write-up of the file layout as far as it has been worked out, for
anyone who wants to build on it. It was worked out by reading files. No Vectric software
was run, opened or taken apart.

## Tests

```
python -m pip install pytest
python -m pytest
```

The tests build small synthetic project files, so no one else's designs are in this
repository. To run the converter over your own collection as well:

```
CRV2SVG_SAMPLES=/path/to/folder python -m pytest tests/test_corpus.py
```

## Licence

GPL-3.0-or-later. Vectric, VCarve, Aspire, Cut2D and PartWorks are trademarks of their
owners. This project is not affiliated with or endorsed by Vectric Ltd.
