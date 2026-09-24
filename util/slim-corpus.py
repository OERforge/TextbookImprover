#!/usr/bin/env python3
"""Make a slim copy of a corpus of Word books for the table census.

The census reads nothing but word/document.xml, so each .docx is copied
with that part alone, which leaves out the images that are most of a
book's size: nine books, 1,782 files, came to 10.5 MB. A book is a folder
of .docx files, or a .zip archive of them as OpenStax's DOCX downloads
come; each keeps its own folder in the output, so table-census.py reports
the slim copy book by book with the same totals as the originals.

It's for moving a corpus somewhere to be measured -- another machine, a
colleague, a chat -- when the question is what shapes its tables take. A
slim copy is no good for converting a book or for table-samples.py, which
copy a table's styles and images; keep the originals for those.

Usage:
    python3 slim-corpus.py CORPUS-FOLDER [OUTPUT.zip]

The output defaults to corpus-slim.zip in the current folder.
"""
import io
import os
import sys
import zipfile
from collections import Counter


def slim(data):
    """The .docx in data with word/document.xml alone, or None."""
    try:
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return None
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml)
    return out.getvalue()


def main():
    if len(sys.argv) not in (2, 3) or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    source = sys.argv[1]
    target = os.path.abspath(sys.argv[2] if len(sys.argv) == 3
                             else "corpus-slim.zip")
    if not os.path.isdir(source):
        print(f"{source}: no such folder (looked for {os.path.abspath(source)})")
        return 1

    books, unreadable, seen = Counter(), [], Counter()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        def add(rel, data):
            copy = slim(data)
            if copy is None:
                unreadable.append(rel)
                return
            parts = rel.replace("\\", "/").split("/")
            out.writestr("/".join(parts), copy)
            books[parts[0] if len(parts) > 1 else "(loose files)"] += 1

        for here, dirs, files in os.walk(source):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(here, name)
                if os.path.abspath(path) == target or name.startswith("~$"):
                    continue
                rel = os.path.relpath(path, source)
                seen[os.path.splitext(name)[1].lower() or "(none)"] += 1
                if name.lower().endswith(".docx"):
                    with open(path, "rb") as fh:
                        add(rel, fh.read())
                elif name.lower().endswith(".zip"):
                    try:
                        archive = zipfile.ZipFile(path)
                    except zipfile.BadZipFile:
                        unreadable.append(rel)
                        continue
                    book = os.path.splitext(rel)[0]
                    for inner in sorted(archive.namelist()):
                        base = inner.rsplit("/", 1)[-1]
                        if base.lower().endswith(".docx") and not base.startswith("~$"):
                            add(book + "/" + inner, archive.read(inner))

    total = sum(books.values())
    if total == 0:
        os.remove(target)
        found = ", ".join(f"{n} {ext}" for ext, n in seen.most_common()) or "nothing"
        print(f"No .docx files under {os.path.abspath(source)}, loose or in a "
              f".zip. Found: {found}. No zip written.")
        return 1
    for book, n in sorted(books.items()):
        print(f"  {n:5d}  {book}")
    for rel in unreadable:
        print(f"  skipped, not a readable Word file: {rel}")
    size = os.path.getsize(target) / 1e6
    print(f"{total} files in {len(books)} book(s), {size:.1f} MB: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
