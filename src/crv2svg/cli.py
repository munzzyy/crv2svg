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
    parser.add_argument("--include-previews", action="store_true",
                        help="also export toolpath preview geometry")
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

    status = 0
    for path in args.files:
        try:
            status |= _one(path, args)
        except OSError as exc:
            print("crv2svg: %s: %s" % (path, exc.strerror or exc), file=sys.stderr)
            status = 1
    return status


def _one(path, args):
    partial = False
    try:
        doc = read_file(path)
    except UnsupportedError as exc:
        print("crv2svg: %s: %s" % (path, exc), file=sys.stderr)
        if not (args.partial and exc.partial is not None and exc.partial.layers):
            if exc.partial is not None and exc.partial.layers:
                print("crv2svg: rerun with --partial to keep the %d layer(s) read before that"
                      % len(exc.partial.layers), file=sys.stderr)
            return 1
        doc, partial = exc.partial, True
    except CrvError as exc:
        print("crv2svg: %s: %s" % (path, exc), file=sys.stderr)
        return 1

    for note in sorted(set(doc.warnings)):
        print("crv2svg: %s: %s (x%d)" % (path, note, doc.warnings.count(note)), file=sys.stderr)
    if args.info:
        _info(path, doc)
        return 2 if partial else 0
    if args.extract_preview:
        if not doc.preview_gif:
            print("crv2svg: %s: no thumbnail stored in this project" % path, file=sys.stderr)
            return 1
        with open(args.extract_preview, "wb") as handle:
            handle.write(doc.preview_gif)
        return 0

    known = {l.name for l in doc.drawing_layers(args.include_previews)}
    for name in args.layer or ():
        if name not in known:
            print("crv2svg: %s: no layer named %r (have: %s)"
                  % (path, name, ", ".join(sorted(known)) or "none"), file=sys.stderr)
            return 1
    wanted = set(args.layer) if args.layer else None

    fmt = args.format
    if not fmt and args.output and args.output.lower().endswith(".dxf"):
        fmt = "dxf"
    fmt = fmt or "svg"
    if fmt == "svg":
        text = to_svg(doc, units=args.units, include_previews=args.include_previews, layers=wanted)
    else:
        text = to_dxf(doc, include_previews=args.include_previews, layers=wanted)

    if args.output == "-":
        sys.stdout.write(text)
    else:
        target = args.output or os.path.splitext(path)[0] + "." + fmt
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        print("%s -> %s%s" % (path, target, " (partial)" if partial else ""))
    return 2 if partial else 0


def _info(path, doc):
    print(path)
    print("  written by: %s %s" % (doc.product or "unknown", doc.version))
    if doc.material:
        print("  material:   %g x %g %s, origin at (%g, %g)"
              % (doc.material[2], doc.material[3], doc.units or "(units unknown)",
                 doc.material[0], doc.material[1]))
    for layer in doc.layers:
        spans = sum(len(p.spans) for p in layer.paths())
        note = "  [toolpath preview, skipped by default]" if layer.is_preview else ""
        print("  layer %-32r %4d objects %6d segments%s"
              % (layer.name, len(layer.items), spans, note))
