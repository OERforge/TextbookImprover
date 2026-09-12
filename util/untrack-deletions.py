#!/usr/bin/env python3
"""
untrack-deletions.py -- turn Word tracked deletions into ordinary
strikethrough text.

    python3 untrack-deletions.py BC-14.docx -o BC-14-fixed.docx

Some authors use Word's "track changes" deletion mark as *content*: a
before-and-after table showing which words to cut from a sentence. That is
revision history being used to carry meaning, and anything that resolves
revisions destroys it -- Word's own "Accept All Changes", most converters,
and Pandoc, which accepts changes by default and silently drops the very
words the example is about.

This rewrites each <w:del> element as normal runs whose text is struck
through, so the appearance is preserved and the meaning no longer depends
on a revision being left unresolved.

Only word/document.xml is touched. Every other part of the package is
copied through byte for byte, with its original compression.

Copyright 2026 Robert Szarka

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import argparse
import os
import re
import sys
import zipfile

DEL_RE = re.compile(r"<w:del(?: [^>]*)?>(.*?)</w:del>", re.S)
RUN_RE = re.compile(r"<w:r(?: [^>]*)?>.*?</w:r>", re.S)
RPR_RE = re.compile(r"<w:rPr(?: [^>]*)?>", re.S)


def strike_run(run):
    """Add <w:strike/> to a run and turn its delText back into ordinary text."""
    # <w:delText> is the deleted-text element; only valid inside <w:del>.
    run = run.replace("<w:delText", "<w:t").replace("</w:delText>", "</w:t>")

    if "<w:strike/>" in run or "<w:strike " in run:
        return run

    m = RPR_RE.search(run)
    if m:
        # w:strike belongs in the run properties, where order is loose
        # enough that appending directly after the opening tag is safe.
        return run[:m.end()] + "<w:strike/>" + run[m.end():]

    # No properties yet. They must be the first child of <w:r>.
    open_tag = re.match(r"<w:r(?: [^>]*)?>", run)
    return (run[:open_tag.end()] + "<w:rPr><w:strike/></w:rPr>"
            + run[open_tag.end():])


def convert(xml):
    counts = {"deletions": 0, "runs": 0, "words": 0}

    def replace(match):
        inner = match.group(1)
        if "<w:delText" not in inner:
            # A deleted paragraph mark or similar: no text to preserve, so
            # accepting it is the right outcome and it is left alone.
            return match.group(0)

        counts["deletions"] += 1
        for text in re.findall(r"<w:delText[^>]*>(.*?)</w:delText>", inner, re.S):
            counts["words"] += len(text.split())

        def fix(run_match):
            counts["runs"] += 1
            return strike_run(run_match.group(0))

        return RUN_RE.sub(fix, inner)

    return DEL_RE.sub(replace, xml), counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("docx")
    # Not required with --check: naming an output file that will never be
    # written just gets in the way of scanning a whole directory.
    parser.add_argument("-o", "--output")
    parser.add_argument("--check", action="store_true",
                        help="report what would change; write nothing")
    args = parser.parse_args()

    if not args.check and not args.output:
        parser.error("-o/--output is required unless --check is given")

    name = os.path.basename(args.docx)

    # Word writes an owner file beside any document it has open: the same
    # name prefixed with "~$", the same extension, and not a zip. A glob of
    # *.docx picks it up, so skip it rather than failing on it.
    if name.startswith("~$"):
        print(f"{args.docx}: Word lock file, skipped.")
        return 0

    if os.path.getsize(args.docx) == 0:
        print(f"{args.docx}: empty file, skipped.", file=sys.stderr)
        print("  On a cloud-synced drive this is usually a placeholder that "
              "has not been downloaded yet.", file=sys.stderr)
        return 0

    try:
        with zipfile.ZipFile(args.docx) as archive:
            names = archive.namelist()
            if "word/document.xml" not in names:
                print(f"{args.docx}: no word/document.xml, skipped.",
                      file=sys.stderr)
                print("  A .doc renamed to .docx would look like this.",
                      file=sys.stderr)
                return 0
            original = archive.read("word/document.xml").decode("utf-8")

            # Tracked changes can also live in headers, footers and footnotes.
            elsewhere = [n for n in names
                         if n != "word/document.xml" and n.endswith(".xml")
                         and b"<w:del " in archive.read(n)]
    except zipfile.BadZipFile:
        print(f"{args.docx}: not a valid .docx, skipped.", file=sys.stderr)
        print("  A .docx is a zip archive; this file is not one. Common "
              "causes: an older .doc renamed, or a cloud-storage "
              "placeholder that has not been downloaded.", file=sys.stderr)
        return 0

    updated, counts = convert(original)

    print(f"{args.docx}: {counts['deletions']} tracked deletion(s), "
          f"{counts['runs']} run(s), about {counts['words']} word(s).")
    if elsewhere:
        print("WARNING: tracked deletions also appear in parts this script "
              "does not touch:", file=sys.stderr)
        for name in elsewhere:
            print(f"  {name}", file=sys.stderr)

    if counts["deletions"] == 0:
        return 0
    if args.check:
        return 0

    # Copy every other part through untouched, preserving compression.
    with zipfile.ZipFile(args.docx) as source:
        with zipfile.ZipFile(args.output, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    data = updated.encode("utf-8")
                target.writestr(item, data,
                                compress_type=item.compress_type)

    print(f"Wrote {args.output}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
