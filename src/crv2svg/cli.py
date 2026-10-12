import argparse
import os
import sys

from . import __version__
from .dxf import to_dxf
from .errors import CrvError, UnsupportedError
from .reader import read_file
from .svg import to_svg


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="crv2svg",
        description="Convert the 2D vectors in a Vectric .crv project to SVG or DXF.")
    parser.add_argument("files", nargs="+", metavar="FILE.crv")
    parser.add_argument("-o", "--output", help="output file (one input only); - for stdout")
    parser.add_argument("-f", "--format", choices=("svg", "dxf"),
                        help="output format (default: from -o, else svg)")
    parser.add_argument("--units", choices=("in", "mm"),
                        help="override the units read from the project (SVG page size)")
    parser.add_argument("--layer", action="append", metavar="NAME",
                        help="export only this layer (repeatable)")
    parser.add_argument("--sheet", type=int, metavar="N",
                        help="export only sheet N of a job with several sheets (first is 1); "
                             "without it each sheet gets its own file")
    parser.add_argument("--include-previews", action="store_true",
                        help="also export toolpath preview geometry")
    parser.add_argument("--approximate-text", action="store_true",
                        help="also place text from releases before 9; its position along "
                             "the line is an estimate, good to about 5%% of the text's width")
    parser.add_argument("--info", action="store_true", help="list layers and exit")
    parser.add_argument("--extract-preview", metavar="FILE.gif",
                        help="save the thumbnail stored in the project (one input only)")
    parser.add_argument("--partial", action="store_true",
                        help="when a file has a record this tool cannot decode, "
                             "write what was read before it")
    parser.add_argument("--version", action="version", version="crv2svg " + __version__)
    args = parser.parse_args(argv)

    if (args.output or args.extract_preview) and len(args.files) > 1:
        parser.error("-o and --extract-preview take a single input file")

    worst, written = 0, {}
    for path in args.files:
        try:
            code = _one(path, args, written)
        except OSError as exc:
            print("crv2svg: %s: %s" % (path, exc.strerror or exc), file=sys.stderr)
            code = 1
        # 1 (a file failed) outranks 2 (a partial result), whatever order they came in.
        worst = 1 if 1 in (worst, code) else max(worst, code)
    return worst


def _one(path, args, written):
    partial = False
    try:
        doc = read_file(path, args.approximate_text)
    except UnsupportedError as exc:
        print("crv2svg: %s: %s" % (path, _plain(str(exc))), file=sys.stderr)
        doc = exc.partial
        if args.extract_preview and doc is not None:
            return _save_preview(path, doc, args.extract_preview)
        if not (args.partial and doc is not None and doc.layers):
            if doc is not None and doc.layers:
                print("crv2svg: rerun with --partial to keep the %d layer(s) read before that"
                      % len(doc.layers), file=sys.stderr)
            return 1
        partial = True
    except CrvError as exc:
        print("crv2svg: %s: %s" % (path, _plain(str(exc))), file=sys.stderr)
        return 1

    for note in sorted(set(doc.warnings)):
        print("crv2svg: %s: %s (x%d)" % (path, note, doc.warnings.count(note)), file=sys.stderr)
    if args.info:
        _info(path, doc)
        return 2 if partial else 0
    if args.extract_preview:
        return _save_preview(path, doc, args.extract_preview)

    known = {l.name for l in doc.drawing_layers(args.include_previews)}
    for name in args.layer or ():
        if name not in known:
            print("crv2svg: %s: no layer named %s (have: %s)"
                  % (path, _plain(repr(name)), _plain(", ".join(sorted(known))) or "none"),
                  file=sys.stderr)
            return 1
    wanted = set(args.layer) if args.layer else None

    fmt = args.format
    if not fmt and args.output and args.output.lower().endswith(".dxf"):
        fmt = "dxf"
    fmt = fmt or "svg"

    sheets = doc.sheets
    if args.sheet is not None:
        if not 1 <= args.sheet <= len(sheets):
            print("crv2svg: %s: no sheet %d, this job has %d" % (path, args.sheet, len(sheets)),
                  file=sys.stderr)
            return 1
        jobs = [(sheets[args.sheet - 1], "")]
    elif len(sheets) == 1:
        jobs = [(None, "")]
    elif args.output:
        print("crv2svg: %s: this job has %d sheets, pick one with --sheet or leave out -o to "
              "get a file for each" % (path, len(sheets)), file=sys.stderr)
        return 1
    else:
        jobs = [(key, "-sheet%d" % (n + 1)) for n, key in enumerate(sheets)]

    for sheet, suffix in jobs:
        try:
            if fmt == "svg":
                text = to_svg(doc, units=args.units, include_previews=args.include_previews,
                              layers=wanted, sheet=sheet)
            else:
                text = to_dxf(doc, include_previews=args.include_previews, layers=wanted,
                              sheet=sheet)
        except CrvError as exc:
            print("crv2svg: %s: %s" % (path, exc), file=sys.stderr)
            return 1
        if args.output == "-":
            sys.stdout.flush()
            sys.stdout.buffer.write(text.encode("utf-8"))
            sys.stdout.buffer.flush()
            continue
        target = args.output or os.path.splitext(path)[0] + suffix + "." + fmt
        key = os.path.normcase(os.path.abspath(target))
        if key == os.path.normcase(os.path.abspath(path)):
            print("crv2svg: %s: the output would overwrite the input, name one with -o" % path,
                  file=sys.stderr)
            return 1
        if key in written:
            print("crv2svg: %s: %s was already written from %s in this run, convert it on its "
                  "own with -o" % (path, target, written[key]), file=sys.stderr)
            return 1
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written[key] = path
        print("%s -> %s%s" % (path, target, " (partial)" if partial else ""))
    return 2 if partial else 0


def _save_preview(path, doc, target):
    if not doc.preview_gif:
        print("crv2svg: %s: no thumbnail stored in this project" % path, file=sys.stderr)
        return 1
    with open(target, "wb") as handle:
        handle.write(doc.preview_gif)
    return 0


def _plain(text):
    """Names come from the file, so keep terminal control codes out of messages."""
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _info(path, doc):
    print(path)
    print("  written by: %s %s" % (doc.product or "unknown", doc.version))
    if doc.material:
        print("  material:   %g x %g %s, origin at (%g, %g)"
              % (doc.material[2], doc.material[3], doc.units or "(units unknown)",
                 doc.material[0], doc.material[1]))
    if len(doc.sheets) > 1:
        print("  sheets:     %d, each written to its own file" % len(doc.sheets))
    for layer in doc.layers:
        spans = sum(len(p.spans) for p in layer.paths())
        note = "  [toolpath preview, skipped by default]" if layer.is_preview else ""
        print("  layer %-32s %4d objects %6d segments%s"
              % (_plain(repr(layer.name)), len(layer.items), spans, note))
