#!/usr/bin/env python3
"""
table-samples.py -- collect one real example of each table shape into a
single Word document.

    python3 util/table-samples.py book/*.docx -o samples.docx
    python3 util/table-samples.py --list-cases
    python3 util/table-samples.py book/*.docx --random -o other.docx
    python3 util/table-samples.py book/*.docx --case payoff-matrix -o one.docx

Every table in the output is copied from a source file rather than rebuilt,
including its style, its table-look flags, its merges, its repeated-header
rows, and whatever direct formatting the cells carry. Images and hyperlinks
come with it. The point is to be able to open one document, see every shape
the corpus contains, and judge what a conversion would do to each -- so a
copy that quietly tidied anything up would be worse than useless.

What does not come across: numbering definitions (a numbered list inside a
cell renders as plain paragraphs), and any style whose id collides with a
style already taken from an earlier source, since styles are merged by id
with the first definition winning. Both are noted in the generated document.

Run against a book nobody here has seen and it answers "what is in this
thing, and which parts of it are going to be a problem" before anyone
commits to converting it.

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
import random
import re
import sys
import zipfile
import zlib
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import tablecensus as tc  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKGREL = "http://schemas.openxmlformats.org/package/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
V = "urn:schemas-microsoft-com:vml"

PREFIXES = {
    "w": W,
    "r": R,
    "a": A,
    "v": V,
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "o": "urn:schemas-microsoft-com:office:office",
    "w10": "urn:schemas-microsoft-com:office:word",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "wp14": "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "wne": "http://schemas.microsoft.com/office/word/2006/wordml",
}
for prefix, uri in PREFIXES.items():
    ET.register_namespace(prefix, uri)

MEDIA_TYPES = {
    ".png": "image/png", ".jpeg": "image/jpeg", ".jpg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".tiff": "image/tiff",
    ".emf": "image/x-emf", ".wmf": "image/x-wmf", ".svg": "image/svg+xml",
}


def w(tag):
    return "{%s}%s" % (W, tag)


# --------------------------------------------------------------------------
# What we know how to recognize
# --------------------------------------------------------------------------
#
# A case is a shape someone has to make a decision about. Each one names
# what it is and what is at stake, because the document these end up in is
# read by whoever has to make that decision.

CASES = []


def case(ident, title, note, test):
    CASES.append({"id": ident, "title": title, "note": note, "test": test})


def evidence(info, text):
    return text in "; ".join(info["ev"])


def blank(cell):
    return not cell.text and not cell.image


def corner_depth(grid):
    """How many leading rows and columns of the top-left block are blank."""
    rows = 0
    while rows < len(grid) and blank(grid[rows][0]):
        rows += 1
    cols = 0
    if grid:
        while cols < len(grid[0]) and blank(grid[0][cols]):
            cols += 1
    return rows, cols


def is_full_width(row):
    """One merged cell across the whole row: a title, not a spanning header."""
    return len(row) > 1 and len({id(c) for c in row}) == 1


def sort_key(text):
    return text.strip().lower().lstrip("@_!(&|").strip()


def reads_down_the_columns(rows):
    """A list snaked into columns rather than a table of rows.

    A glossary laid out three columns wide runs alphabetically *down*
    column one, then down column two. Read across the rows, as HTML and a
    screen reader will, the order is scrambled: Class, JavaDoc, private.
    There are no headers to declare and `none` is the right value, but the
    value does not say the thing that matters about it.

    Recognized loosely, and it stays a thing to look at rather than
    something to act on: two data tables in the other books have sorted
    columns by coincidence. Pairing it with a `none` guess is what keeps
    it precise.
    """
    if len(rows) < 3 or max(len(r) for r in rows) < 2:
        return False
    cells = [[c.text for c in r] for r in rows]
    if any(len(t) > 40 for r in cells for t in r):
        return False
    if any(tc.NUMERIC.match(t.strip()) for r in cells for t in r if t.strip()):
        return False
    columns = [[sort_key(r[j]) for r in cells if j < len(r) and r[j].strip()]
               for j in range(max(len(r) for r in cells))]
    sorted_columns = sum(1 for c in columns if len(c) > 2 and c == sorted(c))
    across = [sort_key(t) for r in cells for t in r if t.strip()]
    return sorted_columns >= 2 and across != sorted(across)


def unordered_numbers(cells):
    """Numeric, all distinct, and in no order.

    The census rule turns on the ordering, so a case meant to show an
    unordered column has to test for disorder rather than infer it from
    the value the guess landed on. A first column can be ordered and still
    come out first-row for an unrelated reason -- a body of expressions
    rather than values, say -- and picking one of those as the example
    illustrates the wrong thing.
    """
    values = [tc.parse_number(c.text) for c in cells]
    if len(values) < 3 or any(v is None for v in values):
        return False
    if len(set(values)) != len(values):
        return False
    rising = all(b > a for a, b in zip(values, values[1:]))
    falling = all(b < a for a, b in zip(values, values[1:]))
    return not (rising or falling)


def spans_in(tbl, row_index):
    rows = tbl.findall(w("tr"))
    if row_index >= len(rows):
        return 0
    return len(rows[row_index].findall(".//" + w("gridSpan")))


case("header-row-marked", "Header row, marked in Word",
     "The ordinary case. Row 1 carries w:tblHeader, so it repeats across "
     "pages, Pandoc reads it as a header, and the conversion needs "
     "nothing from a sidecar.",
     lambda i: i["guess"] == "first-row" and evidence(i, "tblHeader row 1"))

case("header-row-unmarked", "Header row, not marked in Word",
     "Every cell in row 1 has text and they are uniformly bold or "
     "uniformly shaded (a blank corner cell is allowed and ignored), but "
     "the row carries no w:tblHeader, so nothing in the file says it is a "
     "header. The signal is formatting, not what the words say. A sidecar "
     "value fixes this without anyone opening Word, because the header "
     "text is already there.",
     lambda i: i["guess"] == "first-row"
     and not evidence(i, "tblHeader")
     and evidence(i, "header-looking row 1"))

case("header-row-missing", "No header text anywhere",
     "No w:tblHeader, no uniformly bold or shaded band in row 1 or "
     "column 1, and no first column that keys its rows over a body of "
     "values. A sidecar cannot help if the words genuinely are not there: "
     "nothing can invent them. Either it is a data grid or someone has to "
     "author headers in Word. Read the table before deciding which.",
     lambda i: i["guess"] == "none" and i["ncols"] > 1
     and not evidence(i, "merged cells"))

case("row-headers-unformatted", "Row headers with nothing marking them",
     "A contingency table: the first column labels its rows and Word was "
     "never told, so it is neither bold nor shaded. Recognized from "
     "content instead -- every cell filled, no value repeated, and the "
     "rest of the table numeric -- which is the shape the whole guess "
     "exists for and the one no reading of the formatting can settle.",
     lambda i: i["guess"] == "both"
     and not evidence(i, "first column bold/shaded"))

case("row-headers-formatted", "Row headers Word does mark",
     "The same shape with bold or shading on the first column, which is "
     "the only version a formatting-based rule can find. Rare: 19 tables "
     "in 1,716.",
     lambda i: i["guess"] in ("both", "first-column")
     and evidence(i, "first column bold/shaded"))

case("row-headers-only", "Row headers, no header row",
     "The first column labels its rows and there is no header row at all. "
     "Reading row 1 as headers here would promote a data row.",
     lambda i: i["guess"] == "first-column")

case("numeric-key-ordered", "Ordered numeric first column",
     "Year, price, or a frequency table's data column: numeric, unique, "
     "and sorted, which is what makes it a lookup axis rather than the "
     "first of several data series.",
     lambda i: i["guess"] == "both" and i["nrows"] > 3
     and tc.mostly_numeric([r[0] for r in i["grid"][1:]]))

case("numeric-first-column-unordered", "Unordered numeric first column",
     "Columns of measurements where row 1 names the groups. The first "
     "column is numeric and every value distinct, which is exactly what a "
     "lookup axis looks like; only its disorder distinguishes it.",
     lambda i: i["guess"] == "first-row" and i["nrows"] > 3
     and unordered_numbers([r[0] for r in i["grid"][1:]]))

case("bin-column", "A column of bins",
     "Values like 1, 2, 3-4, 5+ that mostly do not parse as numbers. They "
     "label their rows and do not have to be sorted to prove it.",
     lambda i: len(i["grid"]) > 3
     and not tc.mostly_numeric([r[0] for r in i["grid"][1:]])
     and any(re.match(r"^\d+\s*[-\u2013+]", r[0].text) for r in i["grid"][1:]))

case("title-row", "Merged title row above the headers",
     "Row 1 is one merged cell spanning the table. It is a caption that "
     "Word had nowhere better to put, and reading it as a header row "
     "makes an ordinary table look headerless.",
     lambda i: evidence(i, "row 1 is one merged cell"))

case("empty-first-row", "Empty row above the headers",
     "A spacer row with no content at all, above the real header row. "
     "Same failure as the title row and a different cause.",
     lambda i: i["grid"] and i["ncols"] > 1
     and all(blank(c) for c in i["grid"][0]))

case("single-column", "One column",
     "Every row spans the full width trivially, so any rule that reads "
     "past full-width rows will consume the whole table unless it is "
     "guarded. Layout tables are excluded here: they are nearly all "
     "one cell holding one image, and they have their own case below.",
     lambda i: i["ncols"] == 1 and not i["kind"].startswith("layout")
     and i["nrows"] > 2)

case("grouping-bands", "Grouping bands partway down",
     "Merged full-width rows that label the rows beneath them. Twelve "
     "tables in five books. The plan is to split these into one table per "
     "band, with the band text composed into each part's caption.",
     lambda i: evidence(i, "full-width band at row"))

case("payoff-matrix", "Two-level headers on both axes",
     "A blank corner block, column headers spanning groups, row headers "
     "merged down the side. Structurally correct and beyond anything a "
     "four-value declaration can express: a manual case.",
     lambda i: corner_depth(i["grid"])[0] >= 2 and corner_depth(i["grid"])[1] >= 2
     and spans_in(i["tbl"], 0) > 0)

case("stacked-column-headers", "Column headers spanning groups",
     "A header row with merged cells over a second row of headers. HTML "
     "can express this with headers/id; PDF cannot yet, because a cell "
     "Headers array is still open in latex-lab-table.",
     lambda i: spans_in(i["tbl"], 0) > 0 and i["nrows"] > 2
     and i["ncols"] > 2
     and not is_full_width(i["grid"][0])
     and corner_depth(i["grid"])[1] < 2)

case("headers-not-in-row-1", "Headers below row 1",
     "The header band sits in row 2 or lower with something other than a "
     "title or a blank row above it. The four values have nowhere to say "
     "this.",
     lambda i: i["kind"].startswith("headers-not-in-row-1"))

case("merged-body-cells", "Merges in the body",
     "Merged cells below the header rows, which survive conversion as "
     "spans but carry no indication of what heads what.",
     lambda i: evidence(i, "merged cells")
     and not evidence(i, "row 1 is one merged cell")
     and spans_in(i["tbl"], 0) == 0)

case("multi-paragraph-cell", "Cells holding several paragraphs or breaks",
     "Line structure inside a cell. It matters twice: the text extractor "
     "runs the paragraphs together unless it separates them, and cell "
     "text is what a sidecar key is computed from.",
     lambda i: any(len(c.findall(w("p"))) > 1 or c.findall(".//" + w("br"))
                   for c in i["tbl"].findall(".//" + w("tc"))))

case("image-in-cell", "Images inside a data table",
     "A picture in a cell of a table that is otherwise carrying data, so "
     "the layout-table rule must not fire on it.",
     lambda i: not i["kind"].startswith("layout")
     and any(c.image for r in i["grid"] for c in r))

case("layout-table", "Layout table",
     "A table used to position images or blocks rather than to relate "
     "data. It wants role=\"presentation\" and no headers at all, and it "
     "is 60% of the tables in the OpenStax corpus.",
     lambda i: i["kind"].startswith("layout"))

case("column-major-list", "A list snaked into columns",
     "Alphabetical down column one, then down column two. Converted "
     "faithfully it is read across the rows instead, which scrambles the "
     "order. There are no headers to declare, so none is the right value "
     "and it does not describe the problem: the honest fix is authoring "
     "the content as a list.",
     lambda i: i["guess"] == "none" and reads_down_the_columns(
         [r for r in i["grid"] if r and not tc.is_full_width_band(r)]))

case("nested-table", "A table inside a table",
     "The example is the container, so the nesting is visible: an inner "
     "table copied on its own would just look like a small table. Rare "
     "and worth seeing, because every rule that talks about \"row 1\" has "
     "to decide which table it means.",
     lambda i: i["depth"] == 0 and i["tbl"].findall(".//" + w("tbl")))


# --------------------------------------------------------------------------
# Reading the sources
# --------------------------------------------------------------------------

class Source:
    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self.raw = self.zip.read("word/document.xml")
        self.root = ET.fromstring(self.raw)
        self.rels = {}
        try:
            rels = ET.fromstring(self.zip.read("word/_rels/document.xml.rels"))
        except KeyError:
            return
        for rel in rels:
            self.rels[rel.get("Id")] = (rel.get("Type"), rel.get("Target"),
                                        rel.get("TargetMode"))
        self.types = {}
        self.defaults = {}
        try:
            types = ET.fromstring(self.zip.read("[Content_Types].xml"))
        except KeyError:
            return
        for el in types:
            if el.tag.endswith("Override"):
                self.types[el.get("PartName")] = el.get("ContentType")
            elif el.tag.endswith("Default"):
                self.defaults["." + el.get("Extension").lower()] = \
                    el.get("ContentType")

    def content_type(self, target):
        part = "/word/" + target.lstrip("/")
        if part in self.types:
            return self.types[part]
        ext = os.path.splitext(target)[1].lower()
        if ext in self.defaults:
            return self.defaults[ext]
        return MEDIA_TYPES.get(ext, "application/octet-stream")

    def compatibility_mode(self):
        """What the source says about Word's layout rules, or None.

        Word shows "Compatibility Mode" and refuses to run its Accessibility
        Checker until the file is converted whenever this is below 15 or
        missing. All 1,011 files in the four OpenStax books declare 12.
        """
        try:
            settings = self.zip.read("word/settings.xml").decode("utf8", "ignore")
        except KeyError:
            return None
        found = re.search(r'w:name="compatibilityMode"[^>]*?w:val="(\d+)"',
                          settings)
        return found.group(1) if found else None

    def namespaces(self):
        head = self.raw[:4000].decode("utf8", "ignore")
        return dict(re.findall(r'xmlns:([A-Za-z0-9]+)="([^"]+)"', head))

    def styles(self):
        try:
            return ET.fromstring(self.zip.read("word/styles.xml"))
        except KeyError:
            return None


def label_for(body, tbl, depth, parents):
    if depth == 0:
        return tc.nearby_label(body, tbl)
    outer = parents.get(id(tbl))
    if outer is None:
        return ""
    label = tc.nearby_label(body, outer)
    return ("inside %s" % label) if label else ""


def collect(paths, verbose=False, modes=None):
    """Every table in every source, with its classification."""
    found = []
    for path in paths:
        try:
            src = Source(path)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            print("  skipped %s: %s" % (path, exc), file=sys.stderr)
            continue
        if modes is not None:
            modes[src.compatibility_mode() or "not declared"] = \
                modes.get(src.compatibility_mode() or "not declared", 0) + 1
        body = src.root.find(w("body"))
        if body is None:
            continue
        # A nested table has no label of its own, and reporting it with a
        # bare index says nothing about where it lives. Borrow the
        # enclosing table's label instead.
        parents = {}
        for outer, depth in tc.all_tables(body):
            if depth == 0:
                for inner in outer.findall(".//" + w("tbl")):
                    parents[id(inner)] = outer
        for index, (tbl, depth) in enumerate(tc.all_tables(body)):
            kind, ev, nrows, ncols = tc.classify(tbl)
            grid = tc.build_grid(tbl)
            if not grid:
                continue
            value, why = tc.explain(tbl, kind, ev)
            found.append({
                "source": src, "path": path, "index": index, "tbl": tbl,
                "depth": depth, "kind": kind, "ev": ev, "grid": grid,
                "nrows": nrows, "ncols": ncols,
                "guess": value or "",
                "why": why,
                "label": label_for(body, tbl, depth, parents),
            })
    if verbose:
        print("  read %d tables from %d files" % (found and len(found) or 0,
                                                  len(paths)), file=sys.stderr)
    return found


def choose(found, wanted, per_case, seed=None):
    """One example per case, preferring tables not already used.

    Deterministic by default: the same corpus gives the same tables every
    time, so regenerating after a change to the rules shows what the change
    did rather than a fresh shuffle. Pass a seed to sample instead, which
    is how you look at a second or third example of a shape without
    generating every match.
    """
    picked = []
    used = set()
    shuffler = random.Random(seed) if seed is not None else None
    for spec_ in CASES:
        if wanted and spec_["id"] not in wanted:
            continue
        matches = []
        for info in found:
            try:
                if spec_["test"](info):
                    matches.append(info)
            except (IndexError, AttributeError, TypeError):
                continue
        if not matches:
            continue
        fresh = [m for m in matches
                 if (m["path"], m["index"]) not in used] or matches
        if shuffler is None:
            # Smallest first, then skip the first third: the very smallest
            # match of a shape is usually a degenerate example of it.
            fresh.sort(key=lambda m: (m["nrows"] * m["ncols"], m["nrows"]))
            fresh = fresh[len(fresh) // 3:] or fresh
        else:
            fresh = sorted(fresh, key=lambda m: (m["path"], m["index"]))
            shuffler.shuffle(fresh)
        for info in fresh[:per_case]:
            used.add((info["path"], info["index"]))
            picked.append((spec_, info, len(matches)))
    return picked


# --------------------------------------------------------------------------
# Writing the document
# --------------------------------------------------------------------------

SETTINGS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:settings xmlns:w="%s"><w:compat><w:compatSetting '
            'w:name="compatibilityMode" '
            'w:uri="http://schemas.microsoft.com/office/word" w:val="%%s"/>'
            '</w:compat></w:settings>' % W)


class Builder:
    def __init__(self, compat="15"):
        self.compat = compat
        self.body = ET.Element(w("body"))
        self.parts = {}
        self.rels = []
        self.styles = {}
        self.style_sources = {}
        self.namespaces = dict(PREFIXES)
        self.collisions = []
        self.overrides = {}

    def rel_id(self, target, rtype, mode=None):
        ident = "rId%d" % (len(self.rels) + 100)
        self.rels.append((ident, rtype, target, mode))
        return ident

    def take_styles(self, src):
        root = src.styles()
        if root is None:
            return
        for style in root.findall(w("style")):
            ident = style.get(w("styleId"))
            if ident is None:
                continue
            if ident in self.styles:
                if (self.style_sources[ident] != src.path
                        and ET.tostring(self.styles[ident]) != ET.tostring(style)):
                    self.collisions.append((ident, self.style_sources[ident],
                                            src.path))
                continue
            self.styles[ident] = style
            self.style_sources[ident] = src.path
        for key, value in src.namespaces().items():
            if key not in self.namespaces:
                self.namespaces[key] = value
                ET.register_namespace(key, value)

    def take_media(self, src, tbl):
        """Copy every image the table references, and repoint it."""
        attr_embed = "{%s}embed" % R
        attr_link = "{%s}link" % R
        attr_id = "{%s}id" % R
        for el in tbl.iter():
            tag = el.tag
            attrs = []
            if tag == "{%s}blip" % A:
                attrs = [attr_embed, attr_link]
            elif tag == "{%s}imagedata" % V:
                attrs = [attr_id]
            elif tag == w("hyperlink"):
                old = el.get(attr_id)
                if old and old in src.rels:
                    rtype, target, mode = src.rels[old]
                    el.set(attr_id, self.rel_id(target, rtype, mode or "External"))
                elif old:
                    del el.attrib[attr_id]
                continue
            for attr in attrs:
                old = el.get(attr)
                if not old or old not in src.rels:
                    continue
                rtype, target, _ = src.rels[old]
                name = target.split("/")[-1]
                # zlib.crc32 rather than hash(): Python randomizes string
                # hashing per process, so hash() here made two runs over the
                # same corpus produce different media part names and a
                # different file. Everything else about the run is already
                # deterministic and this was the one thing that was not.
                part = "media/%s-%s" % (zlib.crc32(src.path.encode()) % 100000,
                                        name)
                try:
                    data = src.zip.read("word/" + target.lstrip("/"))
                except KeyError:
                    del el.attrib[attr]
                    continue
                self.parts["word/" + part] = data
                # Carry the source's own declaration rather than deriving one
                # from the extension. OpenStax stores its images as .so named
                # application/octet-stream, which is what Word itself writes
                # for media it cannot type, and seeing that is part of the
                # point of this document.
                self.overrides["/word/" + part] = src.content_type(target)
                el.set(attr, self.rel_id(part, rtype))

    def para(self, text="", style=None, italic=False):
        p = ET.SubElement(self.body, w("p"))
        if style:
            ppr = ET.SubElement(p, w("pPr"))
            ET.SubElement(ppr, w("pStyle")).set(w("val"), style)
        if text:
            run = ET.SubElement(p, w("r"))
            if italic:
                rpr = ET.SubElement(run, w("rPr"))
                ET.SubElement(rpr, w("i"))
            node = ET.SubElement(run, w("t"))
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            node.text = text
        return p

    def table(self, tbl):
        self.body.append(tbl)

    def finish(self, path):
        ET.SubElement(self.body, w("sectPr"))
        doc = ET.Element(w("document"))
        doc.append(self.body)
        xml = ET.tostring(doc, encoding="unicode")
        xml = self.declare(xml)

        styles = ET.Element(w("styles"))
        for ident in ("Normal", "Heading1", "Heading2"):
            if ident not in self.styles:
                self.styles[ident] = self.default_style(ident)
        for style in self.styles.values():
            styles.append(style)
        styles_xml = self.declare(ET.tostring(styles, encoding="unicode"))

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
            out.writestr("[Content_Types].xml", self.content_types())
            out.writestr("_rels/.rels", PACKAGE_RELS)
            out.writestr("word/document.xml", '<?xml version="1.0" '
                         'encoding="UTF-8" standalone="yes"?>' + xml)
            out.writestr("word/styles.xml", '<?xml version="1.0" '
                         'encoding="UTF-8" standalone="yes"?>' + styles_xml)
            if self.compat:
                out.writestr("word/settings.xml", SETTINGS % self.compat)
            out.writestr("word/_rels/document.xml.rels", self.document_rels())
            for name, data in self.parts.items():
                out.writestr(name, data)

    def declare(self, xml):
        """Add our namespace declarations to the root, keeping ElementTree's.

        ElementTree declares the prefixes it used itself, including the
        ns0-style ones it invents for namespaces nobody registered. Removing
        those and substituting our own list leaves any prefix we did not
        know about unbound, which is a file Word will not open.
        """
        match = re.match(r'<([A-Za-z0-9]+:[A-Za-z0-9]+)((?:\s+[^\s=]+="[^"]*")*)',
                         xml)
        if not match:
            return xml
        present = set(re.findall(r'xmlns:([^=\s]+)=', match.group(2)))
        extra = "".join(' xmlns:%s="%s"' % kv
                        for kv in sorted(self.namespaces.items())
                        if kv[0] not in present)
        head = "<" + match.group(1) + extra + match.group(2)
        return head + xml[match.end():]

    def default_style(self, ident):
        style = ET.Element(w("style"))
        style.set(w("type"), "paragraph")
        style.set(w("styleId"), ident)
        name = ET.SubElement(style, w("name"))
        name.set(w("val"), {"Normal": "Normal", "Heading1": "heading 1",
                            "Heading2": "heading 2"}[ident])
        if ident.startswith("Heading"):
            ppr = ET.SubElement(style, w("pPr"))
            ET.SubElement(ppr, w("outlineLvl")).set(
                w("val"), str(int(ident[-1]) - 1))
            rpr = ET.SubElement(style, w("rPr"))
            ET.SubElement(rpr, w("b"))
            ET.SubElement(rpr, w("sz")).set(w("val"),
                                            "32" if ident == "Heading1" else "26")
        return style

    def content_types(self):
        defaults = ['<Default Extension="rels" ContentType="application/'
                    'vnd.openxmlformats-package.relationships+xml"/>',
                    '<Default Extension="xml" ContentType="application/xml"/>']
        for part, ctype in sorted(self.overrides.items()):
            defaults.append('<Override PartName="%s" ContentType="%s"/>'
                            % (part, ctype))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/'
                '2006/content-types">' + "".join(defaults) +
                '<Override PartName="/word/document.xml" ContentType='
                '"application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.document.main+xml"/>'
                '<Override PartName="/word/styles.xml" ContentType='
                '"application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.styles+xml"/>'
                + ('<Override PartName="/word/settings.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.'
                   'wordprocessingml.settings+xml"/>' if self.compat else "")
                + '</Types>')

    def document_rels(self):
        items = ['<Relationship Id="rIdStyles" Type="http://schemas.'
                 'openxmlformats.org/officeDocument/2006/relationships/styles"'
                 ' Target="styles.xml"/>']
        if self.compat:
            items.append('<Relationship Id="rIdSettings" Type="http://schemas.'
                         'openxmlformats.org/officeDocument/2006/relationships/'
                         'settings" Target="settings.xml"/>')
        for ident, rtype, target, mode in self.rels:
            extra = ' TargetMode="%s"' % mode if mode else ""
            items.append('<Relationship Id="%s" Type="%s" Target="%s"%s/>'
                         % (ident, rtype, target, extra))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="%s">%s</Relationships>'
                % (PKGREL, "".join(items)))


PACKAGE_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="%s"><Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/officeDocument" Target="word/document.xml"/>'
                '</Relationships>' % PKGREL)


def build(picked, path, sources, compat="15", modes=None):
    doc = Builder(compat)
    doc.para("Table shapes found in this corpus", style="Heading1")
    doc.para("Generated by util/table-samples.py from %d file(s). Each table "
             "below is copied from its source exactly as it was stored, "
             "including style, table-look flags, merges, repeat-header rows, "
             "direct formatting, images, and links."
             % len(sources))
    if modes:
        doc.para("Compatibility mode declared by the sources: %s. Word shows "
                 "\u201cCompatibility Mode\u201d and will not run its "
                 "Accessibility Checker until the file is converted whenever "
                 "that is below 15 or missing."
                 % ", ".join("%s (%d file(s))" % (k, v)
                             for k, v in sorted(modes.items())),
                 italic=True)
    if compat:
        doc.para("This document declares compatibilityMode %s, so Word treats "
                 "it as a current file and the Accessibility Checker will run "
                 "against it. The sources it was built from declare no "
                 "compatibility mode at all, which is why Word calls them an "
                 "older format, so table layout here may differ slightly from "
                 "the originals. Regenerate with --compat none to match the "
                 "sources instead." % compat, italic=True)
    doc.para("Two things do not survive the copy. Numbering definitions are "
             "not carried over, so a numbered list inside a cell appears as "
             "plain paragraphs. And styles are merged by id across sources "
             "with the first definition winning, so a table may render with "
             "another book's version of a style of the same name.",
             italic=True)

    for spec_, info, total in picked:
        doc.para("%s: %s" % (spec_["id"], spec_["title"]), style="Heading1")
        doc.para(spec_["note"])
        doc.para("Source: %s, table %d%s. %d x %d. %d table(s) in this "
                 "corpus match this case."
                 % (os.path.basename(info["path"]), info["index"],
                    (", labeled %s" % info["label"]) if info["label"] else "",
                    info["nrows"], info["ncols"], total),
                 italic=True)
        doc.para("Census kind: %s" % info["kind"], italic=True)
        doc.para("Guess: %s" % (info["guess"] or "(none)"), italic=True)
        doc.para("Evidence read from the file: %s"
                 % ("; ".join(info["ev"]) or "none"), italic=True)
        doc.para("Why that value: %s." % info["why"], italic=True)
        doc.take_styles(info["source"])
        doc.take_media(info["source"], info["tbl"])
        doc.table(info["tbl"])
        doc.para()

    if doc.collisions:
        doc.para("Style id collisions", style="Heading1")
        doc.para("These style ids were defined differently in more than one "
                 "source. The first definition won.", italic=True)
        for ident, first, other in doc.collisions[:20]:
            doc.para("%s: kept from %s, also defined in %s"
                     % (ident, os.path.basename(first), os.path.basename(other)))

    doc.finish(path)


def main():
    ap = argparse.ArgumentParser(
        description="Collect one real example of each table shape into a "
                    "single Word document.")
    ap.add_argument("files", nargs="*", help="source .docx files")
    ap.add_argument("-o", "--output", default="table-samples.docx")
    ap.add_argument("--case", action="append", default=[],
                    help="only this case (repeatable)")
    ap.add_argument("--per-case", type=int, default=1,
                    help="examples per case (default 1)")
    ap.add_argument("--random", action="store_true",
                    help="pick a different example of each shape, and print "
                         "the seed used so the same set can be had again")
    ap.add_argument("--seed", type=int,
                    help="sample with this seed (implies --random)")
    ap.add_argument("--compat", default="15",
                    help="compatibilityMode to declare, or none to omit "
                         "settings.xml entirely (default 15)")
    ap.add_argument("--list-cases", action="store_true",
                    help="print the cases this knows about and exit")
    args = ap.parse_args()

    if args.list_cases:
        for spec_ in CASES:
            print("%-30s %s" % (spec_["id"], spec_["title"]))
        return 0
    if not args.files:
        ap.error("no input files")

    seed = args.seed
    if seed is None and args.random:
        seed = random.randrange(10 ** 6)
    modes = {}
    found = collect(args.files, modes=modes)
    if not found:
        print("no tables found", file=sys.stderr)
        return 1
    picked = choose(found, set(args.case), args.per_case, seed)
    if not picked:
        print("no case matched", file=sys.stderr)
        return 1
    build(picked, args.output, args.files,
          "" if args.compat.lower() == "none" else args.compat, modes)

    print("%d tables read from %d files" % (len(found), len(args.files)),
          file=sys.stderr)
    for mode, count in sorted(modes.items()):
        print("  compatibilityMode %s: %d file(s)%s" % (
            mode, count,
            "  (Word will ask to convert before checking accessibility)"
            if mode != "15" else ""), file=sys.stderr)
    seen = {spec_["id"] for spec_, _, _ in picked}
    for spec_ in CASES:
        mark = "  " if spec_["id"] in seen else "--"
        print("%s %-30s %s" % (mark, spec_["id"],
                               "not found in this corpus"
                               if spec_["id"] not in seen else ""),
              file=sys.stderr)
    if seed is not None:
        print("sampled with --seed %d" % seed, file=sys.stderr)
    print("wrote %s" % args.output, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
