# Contributing to crv2svg

I maintain this alone, so replies can take a few days, but I read everything.

## A file that does not convert

This is the most useful thing you can send. Run `crv2svg yourfile.crv --info` and open an
issue with the full message. It names the record that stopped the reader. If the design is
yours to share, attach the file. If it is not, the message and the release that wrote it
(the `written by` line) are still enough to start on.

Files from release 12, two-sided jobs, and text on a curve are the gaps I know about.

## Setup

```
git clone https://github.com/munzzyy/crv2svg
cd crv2svg
python -m pip install -e . pytest
python -m pytest
```

There are no runtime dependencies. The tests build their own small project files with
`tests/crvbuild.py`, so please do not add anyone's real design as a fixture. Vectric saves
the licence owner's name inside every project file.

## The page is a second engine

`src/crv2svg/*.py` is the reference. `web/crv2svg.js` is the same reader and writers
rewritten by hand, and `tests/test_web_parity.py` runs both over the same files and fails
unless every SVG, DXF, warning and error message is identical, byte for byte. A change to
a layout, a limit or a message in one has to land in the other in the same commit. The
parity tests need Node, and the page tests need Chromium. Both skip themselves when the
program is missing, and the page tests also skip on CI, so run them on your own machine
before sending a change to `web/`.

## What a patch needs

- A test that fails without the change.
- If you worked out a new piece of the file layout, a few lines in `docs/FORMAT.md` saying
  what the bytes are and how you know.
- No guessing in the reader. A record it does not understand must stop with an error that
  names it. Nothing in the stream says how long an unknown record is, so skipping one
  silently writes a drawing with pieces missing.

Please do not send anything learned by taking Vectric's software apart. Everything here
came from reading project files that people published.
