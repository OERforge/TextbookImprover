#!/usr/bin/env python3
"""Write remediated copies of Word files: the pipeline's decisions about
each file's tables, images, and links written back into the file, the rest
of it left as it was (lib/docxremediate.py).

    table-headers.py *.docx --sidecar table-headers.csv --new new.csv \\
        --report report.csv --resolved resolved.json
    remediate-docx.py *.docx --resolved resolved.json \\
        --alt image-alt.csv --links bare-links.csv --out remediated

convert.py does the same for a target with format: source. Tables get
only what the sidecar declares, unless --include-guesses.

Copyright 2026 Robert Szarka
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import docxremediate  # noqa: E402

DECORATIVE = "[decorative]"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("docx", nargs="+")
    ap.add_argument("--resolved", help="table-headers.py's --resolved file")
    ap.add_argument("--alt", help="the image-alt sidecar")
    ap.add_argument("--links", help="the bare-links sidecar")
    ap.add_argument("--compat", action="store_true",
                    help="set compatibility mode 15, which Word's Accessibility "
                         "Checker needs according to guides for Word")
    ap.add_argument("--include-guesses", action="store_true",
                    help="write the census's guess for a table with no sidecar row too; "
                         "it then reads back as the file's own declaration")
    ap.add_argument("--out", required=True, help="folder for the copies")
    args = ap.parse_args(argv)
    resolved = {}
    if args.resolved:
        with open(args.resolved, encoding="utf-8") as fh:
            resolved = json.load(fh)
    alts, titles = docxremediate.alt_rows(args.alt), docxremediate.link_titles(args.links)
    os.makedirs(args.out, exist_ok=True)
    totals = {}
    for path in args.docx:
        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(args.out, os.path.basename(path))
        if os.path.abspath(out) == os.path.abspath(path):
            print(f"remediate-docx: {path} would be overwritten; choose another --out", file=sys.stderr)
            return 2
        counts = docxremediate.remediate(path, out, resolved.get(stem, []), alts.get(stem, {}),
                                         titles, args.compat, args.include_guesses)
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
    print("remediate-docx: %d file(s): %d table(s) with header rows, %d with a header column, "
          "%d skipped as not the table the pre-pass saw, %d left to their guess; %d image(s) "
          "described, %d marked decorative; %d link title(s); compatibility mode set in %d."
          % (len(args.docx), totals.get("header_rows", 0), totals.get("header_columns", 0),
             totals.get("skipped", 0), totals.get("undecided", 0), totals.get("described", 0),
             totals.get("decorative", 0),
             totals.get("links", 0), totals.get("compat", 0)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
