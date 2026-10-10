#!/usr/bin/env python3
"""Write remediated copies of a book's Word files and hand-maintained HTML
pages, or of PowerPoint decks: the decisions made about each in the
sidecars written back into it, the rest of it left as it was
(lib/docxremediate.py, lib/htmlremediate.py, lib/pptxremediate.py).

    table-headers.py *.docx *.html --sidecar table-headers.csv --new new.csv \\
        --report report.csv --resolved resolved.json --resolved-html resolved-html.json
    remediate.py *.docx *.html --resolved resolved.json \\
        --resolved-html resolved-html.json --alt image-alt.csv \\
        --links bare-links.csv --language en --out remediated

    remediate.py *.pptx --alt image-alt.csv --table-headers table-headers.csv \\
        --slide-titles slide-titles.csv --reading-order reading-order.csv \\
        --language en --out remediated

convert.py does the same for a target with format: source. Tables get
only what the sidecar declares, unless --include-guesses (Word only); a
deck's are read from the table-headers sidecar itself, by their keys.
An HTML page is read with the header pre-pass as convert.py reads it, so
--resolved-html comes from a pre-pass run over the pages' intermediates;
convert.py does that itself. Table captions only a run of convert.py
writes, since they depend on which table the filter gave each one to.

Copyright 2026 Robert Szarka
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import docxremediate  # noqa: E402
import htmlremediate  # noqa: E402
import mdremediate  # noqa: E402
import pptxparse  # noqa: E402
import pptxremediate  # noqa: E402

DECORATIVE = "[decorative]"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+",
                    help="Word files, HTML pages, Markdown files, and PowerPoint decks")
    ap.add_argument("--resolved", help="table-headers.py's --resolved file")
    ap.add_argument("--resolved-html", help="table-headers.py's --resolved-html file")
    ap.add_argument("--language", help="the book's language, for an HTML page with no lang, "
                    "or a deck with no default language")
    ap.add_argument("--alt", help="the image-alt sidecar")
    ap.add_argument("--links", help="the bare-links sidecar")
    ap.add_argument("--table-headers", help="the table-headers sidecar, for a deck's tables")
    ap.add_argument("--slide-titles", help="the slide-titles sidecar, for a deck's slides")
    ap.add_argument("--reading-order", help="the reading-order sidecar, for a deck's slides")
    ap.add_argument("--compat", action="store_true",
                    help="set compatibility mode 15, which Word's Accessibility "
                         "Checker needs according to guides for Word")
    ap.add_argument("--include-guesses", action="store_true",
                    help="write the census's guess for a table with no sidecar row too; "
                         "it then reads back as the file's own declaration")
    ap.add_argument("--repair-equations", action="store_true",
                    help="give Word's and PowerPoint's equations the characters they mean, as "
                         "the pipeline's math.repair_equations does")
    ap.add_argument("--out", required=True, help="folder for the copies")
    args = ap.parse_args(argv)
    resolved, resolved_html = {}, {}
    if args.resolved:
        with open(args.resolved, encoding="utf-8") as fh:
            resolved = json.load(fh)
    if args.resolved_html:
        with open(args.resolved_html, encoding="utf-8") as fh:
            resolved_html = json.load(fh)
    alts, titles = docxremediate.alt_rows(args.alt), docxremediate.link_titles(args.links)
    page_alts, links = htmlremediate.alt_rows(args.alt), htmlremediate.link_rows(args.links)
    deck_alts, deck_tables = pptxremediate.alt_rows(args.alt), pptxremediate.header_rows(
        args.table_headers)
    slide_titles = pptxremediate.title_rows(args.slide_titles)
    deck_links = pptxremediate.link_rows(args.links)
    bad = []
    slide_orders = pptxremediate.order_rows(args.reading_order, bad)
    for key, token in bad:
        print(f"remediate: {args.reading_order}: the order for {key} isn't a list of shape ids "
              f"({token!r} isn't one); its slide is left as it is", file=sys.stderr)
    os.makedirs(args.out, exist_ok=True)
    totals, deck_totals = {}, {}     # every file's counts, and the decks' alone
    failed = 0
    for path in args.files:
        stem, ext = os.path.splitext(os.path.basename(path))
        out = os.path.join(args.out, os.path.basename(path))
        if os.path.abspath(out) == os.path.abspath(path):
            print(f"remediate: {path} would be overwritten; choose another --out", file=sys.stderr)
            return 2
        if ext.lower() == ".docx":
            counts = docxremediate.remediate(path, out, resolved.get(stem, []), alts.get(stem, {}),
                                             titles, args.compat, args.include_guesses,
                                             replacements={u: r for u, (r, _) in links.items() if r},
                                             language=args.language,
                                             equations=args.repair_equations)
        elif ext.lower() in (".html", ".htm"):
            counts = htmlremediate.remediate(path, out, resolved_html.get(stem, []), page_alts,
                                             links, args.language)
        elif ext.lower() == ".md":
            counts = mdremediate.remediate(path, out, page_alts, links, [], args.language)
        elif ext.lower() == ".pptx":
            problems = []
            counts = pptxremediate.remediate(path, out, deck_alts, deck_tables, slide_titles,
                                             args.language, orders=slide_orders,
                                             problems=problems, links=deck_links,
                                             equations=args.repair_equations)
            for key, why in problems:
                print(f"remediate: the reading order for {key} isn't written: {why}",
                      file=sys.stderr)
            try:                # read back, as a run reads its copies back
                pptxparse.read(out)
            except Exception as exc:
                print(f"remediate: the copy of {path} can't be read back: {exc}", file=sys.stderr)
                failed += 1
        else:
            print(f"remediate: {path} isn't a Word file, an HTML page, Markdown, or a "
                  "PowerPoint deck; left out", file=sys.stderr)
            continue
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
            if ext.lower() == ".pptx":
                deck_totals[key] = deck_totals.get(key, 0) + n
    print("remediate: %d file(s): %d table(s) with header rows, %d with a header column, "
          "%d skipped as not the table the pre-pass saw, %d left to their guess; %d image(s) "
          "described, %d marked decorative; %d link title(s); compatibility mode set in %d."
          % (len(args.files), totals.get("header_rows", 0), totals.get("header_columns", 0),
             totals.get("skipped", 0), totals.get("undecided", 0), totals.get("described", 0),
             totals.get("decorative", 0),
             totals.get("links", 0), totals.get("compat", 0)), file=sys.stderr)
    if any(p.lower().endswith(".pptx") for p in args.files):
        print("remediate: slides: %d title(s) added above their slides, %d slide(s) put in "
              "the reading order given, %d title(s) given in place of one another slide has, "
              "%d deck(s) given the language as their default, %d given a title in the file's "
              "properties; %d bare link(s) given a replacement; %d equation(s) repaired; %d "
              "thing(s) PowerPoint couldn't read put right."
              % (deck_totals.get("titles", 0), deck_totals.get("orders", 0),
                 deck_totals.get("retitled", 0), deck_totals.get("language", 0),
                 deck_totals.get("core_title", 0), deck_totals.get("replaced", 0),
                 deck_totals.get("equations_repaired", 0), deck_totals.get("repaired", 0)),
              file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
