"""
pdfretag.py -- repairs to a tagged PDF's structure that LaTeX's tagging
code doesn't make yet, applied after the PDF target builds the file.

A table's caption. Pandoc writes every table as a longtable, with its
caption in the table's first rows, and latex-lab-table, by its own
documentation, formats a longtable caption as a multicolumn row rather
than tagging it as a Caption: the structure has a first TR holding one TH
that spans the table. NVDA, in Acrobat Reader, reads that caption as row 1
and counts a row too many. The caption's TH becomes the Table's first
child, a Caption; the TR it sat in goes.

The repeated head. For a captioned longtable, latex-lab marks the head
repeated on later pages as an artifact, but in PDF 2.0 leaves that
Artifact element inside the Table, with TH and TD under it (latex3/
tagging-project#1583); NVDA counted its cells as three more columns. An
Artifact element in a Table that holds no content is taken out. One that
holds content, a head actually repeated on a later page, is left and
counted, since its content needs a structure parent.

What is retagged is decided by the book, not by the PDF's look: a caption
only in a table the book gave one, matched in order, and only when the PDF
has as many tables as the book; only the table's first row, and only when
that row is a single header cell while some other row has more than one
cell. A table whose own first header row is one cell spanning the table is
left alone unless the book captioned it, in which case the caption comes
first and is the one taken. Each table's content stays with the same
structure elements, so the parent tree that maps content to structure
needs no change.

Needs pikepdf; without it, the caller says so and the file is left as
LaTeX made it.

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

try:
    import pikepdf
except ImportError:
    pikepdf = None


def _kids(element):
    k = element.get("/K")
    if k is None:
        return []
    return list(k) if isinstance(k, pikepdf.Array) else [k]


def _kind(element):
    return str(element.get("/S")) if isinstance(element, pikepdf.Dictionary) else ""


def _cells(row):
    return [c for c in _kids(row) if _kind(c) in ("/TH", "/TD")]


def _has_content(element):
    """Whether anything under element is marked content or an object."""
    if isinstance(element, int):
        return True
    if isinstance(element, pikepdf.Object) and element._type_code == pikepdf.ObjectType.integer:
        return True
    if isinstance(element, pikepdf.Dictionary):
        if str(element.get("/Type")) in ("/MCR", "/OBJR"):
            return True
        return any(_has_content(c) for c in _kids(element))
    return False


def tables(root):
    """Every Table structure element, in document order."""
    found = []

    def walk(element):
        if not isinstance(element, pikepdf.Dictionary):
            return
        if _kind(element) == "/Table":
            found.append(element)
        for kid in _kids(element):
            walk(kid)
    walk(root)
    return found


def retag(path, captioned):
    """Repair the PDF at path in place. captioned: for each table of the
    book, in order, whether the book gave it a caption. Returns counts:
    captions retagged, empty artifacts taken out, artifacts left (with
    content), and whether the tables could be matched at all."""
    counts = {"captions": 0, "artifacts": 0, "artifacts_left": 0, "matched": False}
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        found = tables(pdf.Root.StructTreeRoot)
        counts["matched"] = len(found) == len(captioned)
        for table, has_caption in zip(found, captioned if counts["matched"] else []):
            kids = _kids(table)
            rows = [k for k in kids if _kind(k) == "/TR"]
            first = kids[0] if kids else None
            if (has_caption and _kind(first) == "/TR" and len(_cells(first)) == 1
                    and _kind(_cells(first)[0]) == "/TH"
                    and any(len(_cells(r)) > 1 for r in rows)):
                cell = _cells(first)[0]
                cell.S = pikepdf.Name("/Caption")
                for key in ("/C", "/A"):
                    if key in cell:
                        del cell[key]
                cell.P = table
                kids[0] = cell
                counts["captions"] += 1
            kept = []
            for kid in kids:
                if _kind(kid) == "/Artifact":
                    if _has_content(kid):
                        counts["artifacts_left"] += 1
                    else:
                        counts["artifacts"] += 1
                        continue
                kept.append(kid)
            table.K = pikepdf.Array(kept)
        pdf.save(path)
    return counts
