"""
pptxparse.py -- what a PowerPoint deck holds, read from its XML.

A deck is read with the standard library's zip and XML modules, as the
Word code reads a document, for the checks (pptxcheck.py) and for writing
a person's decisions back into the deck (pptxremediate.py). Nothing here
changes a file. What's kept is what accessibility and conversion ask
about: the slides in the presentation's order, hidden ones marked; each
slide's shapes in the shape tree's order, which is PowerPoint's reading
order and its z-order alike, with where each sits on the slide (group
transforms applied, a placeholder's position taken from its layout or
master when the slide doesn't give one); titles; pictures, keyed by the
SHA-256 of their image's bytes; tables with their header flags and
merged cells; charts, SmartArt, embedded objects, and media; links;
speaker notes; sections; languages; and the core properties' title.

A shape inside mc:AlternateContent is read from the first mc:Choice,
which is what PowerPoint shows; PowerPoint keeps a copy in mc:Fallback
for older readers, with the same shape ids, which the remediation edits
too.

Two things Pandoc's PowerPoint writer leaves in a deck are read past and
recorded in Deck.malformed, since PowerPoint can't read them as written:
a prefix used without its namespace declared (a14, for a formula in a
table cell), which PowerPoint repairs by removing content, and a shape
with no properties at all (an empty p:sp, for a date its layout has no
placeholder for), which stops PowerPoint opening the deck.

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

import collections
import hashlib
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "a14": "http://schemas.microsoft.com/office/drawing/2010/main",
    "adec": "http://schemas.microsoft.com/office/drawing/2017/decorative",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
}
# The prefixes a part may use without declaring them, which Pandoc's
# writer does for a formula in a table cell (a14); declared on the root
# when a part won't parse otherwise.
TOLERATED = ("a14", "p14", "mc", "m")

DECORATIVE_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
SECTIONS_URI = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"
GRAPHIC_KINDS = {
    "http://schemas.openxmlformats.org/drawingml/2006/table": "table",
    "http://schemas.openxmlformats.org/drawingml/2006/chart": "chart",
    "http://schemas.microsoft.com/office/drawing/2014/chartex": "chart",
    "http://schemas.openxmlformats.org/drawingml/2006/diagram": "smartart",
    "http://schemas.openxmlformats.org/presentationml/2006/ole": "ole",
}
TITLE_TYPES = ("title", "ctrTitle")
# Placeholders a screen reader isn't meant to read as the slide's content.
FURNITURE = ("dt", "ftr", "sldNum", "hdr")
EMU_PER_INCH = 914400


def q(tag):
    prefix, name = tag.split(":")
    return "{%s}%s" % (NS[prefix], name)


# The root's name: the first "<" followed by a name, which an XML
# declaration ("<?"), a comment, or a doctype ("<!") isn't.
ROOT_NAME = re.compile(r"<[A-Za-z_][\w.-]*(?::[\w.-]+)?")
# A start tag, its attributes' quoted values allowed to hold ">".
START_TAG = re.compile(r"<([\w.-]+(?::[\w.-]+)?)((?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)"
                       r"\s*/?>")


def declare_unbound(text):
    """text with each tolerated prefix it uses where it isn't declared
    declared on its root, first among the root's attributes: (text, the
    prefixes), or (None, the prefixes) if it still won't parse. A prefix
    declared on one element and used undeclared on another, as Pandoc
    declares a14 around a text box's formula and not a table's, is found
    by where the parse fails."""
    declared = []
    for _ in range(len(TOLERATED) + 1):
        try:
            ET.fromstring(text)
            return text, declared
        except ET.ParseError as exc:
            if "unbound prefix" not in str(exc):
                return None, declared
            line, column = exc.position
        offset = sum(len(row) + 1 for row in text.split("\n")[:line - 1]) + column
        tag, root = START_TAG.match(text, offset), ROOT_NAME.search(text)
        if tag is None or root is None:
            return None, declared
        names = [tag.group(1)] + re.findall(r"\s([\w.-]+:[\w.-]+)\s*=", tag.group(2))
        new = [p for p in dict.fromkeys(n.split(":")[0] for n in names if ":" in n)
               if p in TOLERATED and p not in declared]
        if not new:
            return None, declared
        text = (text[:root.end()] + "".join(' xmlns:%s="%s"' % (p, NS[p]) for p in new)
                + text[root.end():])
        declared += new
    return None, declared


def parse_xml(data, problems=None):
    """An element tree from a part's bytes, declaring a tolerated prefix
    on the root when the part uses it undeclared. problems, a list, is
    told which prefixes were."""
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        if "unbound prefix" not in str(exc):
            raise
        first = exc
    text, declared = declare_unbound(data.decode("utf-8"))
    if text is None:
        raise first
    if problems is not None:
        problems.append("the prefix%s %s used without a namespace declaration"
                        % ("es" if len(declared) > 1 else "", ", ".join(declared)))
    return ET.fromstring(text)


def relationships(zf, part):
    """{id: (type, target, external)} for a part, the target a package
    path unless external."""
    folder, name = posixpath.split(part)
    rels_part = posixpath.join(folder, "_rels", name + ".rels")
    if rels_part not in zf.namelist():
        return {}
    out = {}
    for rel in parse_xml(zf.read(rels_part)):
        target = rel.get("Target") or ""
        external = rel.get("TargetMode") == "External"
        if not external:
            target = posixpath.normpath(posixpath.join(folder, target)) \
                if not target.startswith("/") else target.lstrip("/")
        out[rel.get("Id")] = ((rel.get("Type") or "").rsplit("/", 1)[-1], target, external)
    return out


def rel_target(rels, kind):
    """The first internal target of a relationship type."""
    for typ, target, external in rels.values():
        if typ == kind and not external:
            return target
    return None


class Box:
    """Where a shape sits, in EMU from the slide's top left."""

    __slots__ = ("x", "y", "cx", "cy")

    def __init__(self, x, y, cx, cy):
        self.x, self.y, self.cx, self.cy = x, y, cx, cy

    def overlaps(self, other):
        return (self.x < other.x + other.cx and other.x < self.x + self.cx
                and self.y < other.y + other.cy and other.y < self.y + self.cy)

    def on_slide(self, width, height):
        return self.x + self.cx > 0 and self.y + self.cy > 0 and self.x < width and self.y < height

    def __repr__(self):
        return "Box(%d, %d, %d, %d)" % (self.x, self.y, self.cx, self.cy)


class Link:
    __slots__ = ("text", "target", "tooltip", "external")

    def __init__(self, text, target, tooltip, external):
        self.text, self.target, self.tooltip, self.external = text, target, tooltip, external


class Table:
    """A table's cells as text, its header flags, and whether any cell
    is merged."""

    __slots__ = ("rows", "first_row", "first_col", "merged", "grid")

    def __init__(self, rows, first_row, first_col, merged, grid=None):
        self.rows, self.first_row, self.first_col, self.merged = rows, first_row, first_col, merged
        # (text, bold, column span, vertical merge) per cell, the cells a
        # merge covers left out of a row, as the table census reads a grid
        self.grid = grid or []

    def key(self):
        """The table's content hash, as tablecensus keys a table: each
        cell's text in row order, a unit separator after each cell, a
        record separator after each row, then the shape."""
        h = hashlib.sha256()
        for row in self.rows:
            for cell in row:
                h.update(cell.strip().encode("utf-8") + b"\x1f")
            h.update(b"\x1e")
        widths = ",".join(str(len(r)) for r in self.rows)
        ncols = max((len(r) for r in self.rows), default=0)
        h.update(("%d;%d;%s" % (len(self.rows), ncols, widths)).encode("ascii"))
        return h.hexdigest()


class Shape:
    """One shape, picture, frame, group, or connector in a shape tree."""

    __slots__ = ("kind", "frame", "id", "name", "descr", "title", "hidden", "decorative",
                 "ph_type", "ph_idx", "text", "paragraphs", "box", "children", "image",
                 "links", "table", "prog_id", "media", "depth", "alternate", "math",
                 "malformed")

    def __init__(self, kind):
        self.kind = kind            # sp, pic, graphicFrame, grpSp, cxnSp, contentPart
        self.frame = None           # table, chart, smartart, ole, other (graphicFrame)
        self.id = self.name = None
        self.descr = self.title = None
        self.hidden = self.decorative = False
        self.ph_type = self.ph_idx = None
        self.text = ""
        self.paragraphs = []
        self.box = None
        self.children = []
        self.image = None           # (part, sha256, extension) for a picture or a picture fill
        self.links = []
        self.table = None
        self.prog_id = None
        self.media = None           # video or audio
        self.depth = 0
        self.alternate = False      # read from mc:AlternateContent's Choice
        self.math = 0               # Office math formulas in the shape's text
        self.malformed = False      # no non-visual properties: no id, name, or alt text

    @property
    def placeholder(self):
        return self.ph_type is not None

    @property
    def is_title(self):
        return self.ph_type in TITLE_TYPES

    @property
    def furniture(self):
        return self.ph_type in FURNITURE

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def __repr__(self):
        return "<%s %s %r>" % (self.kind, self.id, self.name)


class Slide:
    __slots__ = ("number", "part", "slide_id", "hidden", "layout", "layout_part", "shapes",
                 "notes", "section")

    def __init__(self, number, part, slide_id):
        self.number, self.part, self.slide_id = number, part, slide_id
        self.hidden = False
        self.layout = self.layout_part = None
        self.shapes = []
        self.notes = ""
        self.section = None

    def all_shapes(self):
        for shape in self.shapes:
            yield from shape.walk()

    @property
    def title_shape(self):
        for shape in self.all_shapes():
            if shape.is_title and shape.text.strip():
                return shape
        return None

    @property
    def title(self):
        shape = self.title_shape
        return " ".join(shape.text.split()) if shape else None


class Deck:
    __slots__ = ("path", "slides", "width", "height", "sections", "core_title", "creator",
                 "application", "languages", "default_language", "masters", "images",
                 "parts", "presentation_part", "master_languages", "malformed")

    def __init__(self, path):
        self.path = path
        self.slides = []
        self.width = self.height = 0
        self.sections = []          # (name, [slide ids])
        self.core_title = self.creator = self.application = None
        self.languages = collections.Counter()
        self.default_language = None
        self.masters = []           # (part, [Shape]) for each layout and master
        self.images = {}            # sha256: (extension, bytes size, first part)
        self.parts = []
        self.presentation_part = "ppt/presentation.xml"
        self.master_languages = collections.Counter()  # in the masters' text styles
        self.malformed = []         # (part, what PowerPoint can't read there as written)

    @property
    def language(self):
        """The language most of the deck's text says it's in, else the
        presentation's default, else its masters' text styles'."""
        if self.languages:
            return self.languages.most_common(1)[0][0]
        if self.default_language:
            return self.default_language
        if self.master_languages:
            return self.master_languages.most_common(1)[0][0]
        return None

    def pictures(self):
        """(slide or None, shape) for every shape that shows an image,
        slides first, then layouts and masters."""
        for slide in self.slides:
            for shape in slide.all_shapes():
                if shape.image:
                    yield slide, shape
        for _, shapes in self.masters:
            for top in shapes:
                for shape in top.walk():
                    if shape.image:
                        yield None, shape


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def _offset(xfrm):
    if xfrm is None:
        return None
    off, ext = xfrm.find(q("a:off")), xfrm.find(q("a:ext"))
    if off is None or ext is None:
        return None
    try:
        return Box(int(off.get("x", 0)), int(off.get("y", 0)),
                   int(ext.get("cx", 0)), int(ext.get("cy", 0)))
    except ValueError:
        return None


def _group_map(xfrm):
    """A function mapping a child's box into its group's parent space."""
    box = _offset(xfrm)
    if box is None:
        return None
    ch_off, ch_ext = xfrm.find(q("a:chOff")), xfrm.find(q("a:chExt"))
    try:
        cx0 = int(ch_off.get("x", 0)) if ch_off is not None else box.x
        cy0 = int(ch_off.get("y", 0)) if ch_off is not None else box.y
        cw = int(ch_ext.get("cx", 0)) if ch_ext is not None else box.cx
        chh = int(ch_ext.get("cy", 0)) if ch_ext is not None else box.cy
    except ValueError:
        return None
    sx = box.cx / cw if cw else 1.0
    sy = box.cy / chh if chh else 1.0

    def mapped(child):
        return Box(int(box.x + (child.x - cx0) * sx), int(box.y + (child.y - cy0) * sy),
                   int(child.cx * sx), int(child.cy * sy))
    return mapped


def _paragraph_text(p):
    """A paragraph's text: runs and fields as written, a line break as a
    newline, a formula as its characters."""
    out = []
    for el in p.iter():
        if el.tag in (q("a:t"), q("m:t")) and el.text:
            out.append(el.text)
        elif el.tag == q("a:br"):
            out.append("\n")
    return "".join(out)


def _text_body(shape_el):
    body = shape_el.find(q("p:txBody"))
    if body is None:
        body = shape_el.find(".//" + q("a:txBody"))
    if body is None:
        return []
    return [_paragraph_text(p) for p in body.findall(q("a:p"))]


def _links(shape_el, rels, cnvpr):
    found = []

    def add(el, text):
        rid = el.get(q("r:id"))
        action = el.get("action") or ""
        target, external = None, False
        if rid and rid in rels:
            _, target, external = rels[rid]
        elif action.startswith("ppaction://"):
            target = action
        if target:
            found.append(Link(text, target, el.get("tooltip"), external))

    if cnvpr is not None:
        click = cnvpr.find(q("a:hlinkClick"))
        if click is not None:
            add(click, "")
    for run in shape_el.iter(q("a:r")):
        rpr = run.find(q("a:rPr"))
        click = rpr.find(q("a:hlinkClick")) if rpr is not None else None
        if click is not None:
            t = run.find(q("a:t"))
            add(click, t.text if t is not None and t.text else "")
    # Adjacent runs of one link are one link to a reader.
    merged = []
    for link in found:
        if merged and link.text and merged[-1].text and merged[-1].target == link.target \
                and merged[-1].tooltip == link.tooltip:
            merged[-1].text += link.text
        else:
            merged.append(link)
    return merged


def _cell_text(tc):
    """A cell's text as tablecensus.keyed_text() reads a Word cell:
    paragraphs and line breaks separated by a newline."""
    parts = []

    def walk(node):
        for child in node:
            if child.tag in (q("a:t"), q("m:t")):
                parts.append(child.text or "")
            elif child.tag == q("a:br"):
                parts.append("\n")
            elif child.tag == q("a:p") and parts and parts[-1] != "\n":
                parts.append("\n")
            walk(child)

    walk(tc)
    return "".join(parts).strip()


def _table(frame_el):
    tbl = frame_el.find(".//" + q("a:tbl"))
    if tbl is None:
        return None
    pr = tbl.find(q("a:tblPr"))
    first_row = pr is not None and pr.get("firstRow") in ("1", "true")
    first_col = pr is not None and pr.get("firstCol") in ("1", "true")
    rows, merged, grid = [], False, []
    for tr in tbl.findall(q("a:tr")):
        cells, line = [], []
        for tc in tr.findall(q("a:tc")):
            h_merge = tc.get("hMerge") in ("1", "true")
            v_merge = tc.get("vMerge") in ("1", "true")
            if any(tc.get(k) not in (None, "0", "1", "false") for k in ("gridSpan", "rowSpan")) \
                    or h_merge or v_merge:
                merged = True
            text = _cell_text(tc)
            cells.append(text)
            if h_merge:
                continue
            runs = [r for r in tc.iter(q("a:r")) if (r.findtext(q("a:t")) or "").strip()]
            bold = bool(runs) and all(
                (r.find(q("a:rPr")) is not None and r.find(q("a:rPr")).get("b") in ("1", "true"))
                for r in runs)
            try:
                span = max(1, int(tc.get("gridSpan") or 1))
            except ValueError:
                span = 1
            vertical = "continue" if v_merge else (
                "restart" if (tc.get("rowSpan") or "1") not in ("0", "1") else None)
            line.append((text, bold, span, vertical))
        rows.append(cells)
        grid.append(line)
    return Table(rows, first_row, first_col, merged, grid)


def _decorative(cnvpr):
    """Whether a shape carries PowerPoint's decorative mark, in its own
    extension list: one inside its link's list isn't the shape's."""
    if cnvpr is None:
        return False
    for ext_list in cnvpr.findall(q("a:extLst")):
        for ext in ext_list.findall(q("a:ext")):
            if ext.get("uri") == DECORATIVE_URI:
                mark = ext.find(q("adec:decorative"))
                return mark is not None and mark.get("val") in ("1", "true")
    return False


class _Reader:
    """Reads one slide's, layout's, or master's shape tree."""

    def __init__(self, zf, deck, part, rels, inherited=None):
        self.zf, self.deck, self.part, self.rels = zf, deck, part, rels
        self.inherited = inherited or {}

    def image(self, blip):
        if blip is None:
            return None
        rid = blip.get(q("r:embed"))
        if rid and rid in self.rels and not self.rels[rid][2]:
            target = self.rels[rid][1]
            try:
                data = self.zf.read(target)
            except KeyError:
                return None
            digest = hashlib.sha256(data).hexdigest()
            ext = posixpath.splitext(target)[1].lower()
            self.deck.images.setdefault(digest, (ext, len(data), target))
            return (target, digest, ext)
        rid = blip.get(q("r:link"))
        if rid and rid in self.rels:
            target = self.rels[rid][1]
            return (target, None, posixpath.splitext(target)[1].lower())
        return None

    def shapes(self, parent, depth=0, mapper=None, alternate=False):
        out = []
        for el in parent:
            tag = el.tag
            if tag == q("mc:AlternateContent"):
                choice = el.find(q("mc:Choice"))
                if choice is None:
                    choice = el.find(q("mc:Fallback"))
                if choice is not None:
                    out.extend(self.shapes(choice, depth, mapper, True))
                continue
            for kind in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp", "contentPart"):
                if tag == q("p:" + kind):
                    malformed = kind != "contentPart" and not any(
                        c.tag.startswith("{%s}nv" % NS["p"]) for c in el)
                    if malformed:
                        self.deck.malformed.append((self.part, (
                            "an empty <p:%s/>" if len(el) == 0 else
                            "a <p:%s> with no non-visual properties") % kind))
                    # An empty one has nothing to read; one with content
                    # is read, its text and its children with it, but has
                    # no id, name, or alt text of its own.
                    if not malformed or len(el):
                        shape = self.shape(el, kind, depth, mapper, alternate)
                        shape.malformed = malformed
                        out.append(shape)
                    break
        return out

    def shape(self, el, kind, depth, mapper, alternate):
        shape = Shape(kind)
        shape.depth, shape.alternate = depth, alternate
        nv = next((c for c in el if c.tag.startswith("{%s}nv" % NS["p"])), None)
        cnvpr = nv.find(q("p:cNvPr")) if nv is not None else None
        if cnvpr is not None:
            shape.id, shape.name = cnvpr.get("id"), cnvpr.get("name")
            shape.descr, shape.title = cnvpr.get("descr"), cnvpr.get("title")
            shape.hidden = cnvpr.get("hidden") in ("1", "true")
            shape.decorative = _decorative(cnvpr)
        nvpr = nv.find(q("p:nvPr")) if nv is not None else None
        ph = nvpr.find(q("p:ph")) if nvpr is not None else None
        if ph is not None:
            shape.ph_type = ph.get("type") or "obj"
            shape.ph_idx = ph.get("idx") or "0"
        if nvpr is not None:
            if nvpr.find(q("a:videoFile")) is not None:
                shape.media = "video"
            elif nvpr.find(q("a:audioFile")) is not None:
                shape.media = "audio"
            else:
                for ext in nvpr.iter(q("a:ext")):
                    if ext.find(q("p14:media")) is not None:
                        shape.media = "media"
        # Position: the shape's own, or its placeholder's on the layout
        # or master; a group's children are placed through the group.
        if kind == "graphicFrame":
            xfrm = el.find(q("p:xfrm"))
        elif kind == "grpSp":
            gpr = el.find(q("p:grpSpPr"))
            xfrm = gpr.find(q("a:xfrm")) if gpr is not None else None
        else:
            spr = el.find(q("p:spPr"))
            xfrm = spr.find(q("a:xfrm")) if spr is not None else None
        box = _offset(xfrm)
        if box is None and shape.placeholder:
            box = self.inherited.get(("idx", shape.ph_idx)) or self.inherited.get(
                ("type", _base_type(shape.ph_type)))
        if box is not None and mapper is not None:
            box = mapper(box)
        shape.box = box
        if kind == "pic":
            fill = el.find(q("p:blipFill"))
            shape.image = self.image(fill.find(q("a:blip")) if fill is not None else None)
        elif kind == "sp":
            spr = el.find(q("p:spPr"))
            fill = spr.find(q("a:blipFill")) if spr is not None else None
            if fill is not None:
                shape.image = self.image(fill.find(q("a:blip")))
        if kind in ("sp", "cxnSp"):
            shape.paragraphs = _text_body(el)
            shape.text = "\n".join(shape.paragraphs).strip()
            shape.math = len(el.findall(".//" + q("m:oMath")))
        if kind == "graphicFrame":
            data = el.find(".//" + q("a:graphicData"))
            uri = data.get("uri") if data is not None else ""
            shape.frame = GRAPHIC_KINDS.get(uri, "other")
            if shape.frame == "table":
                shape.table = _table(el)
                shape.text = "\n".join("\t".join(r) for r in shape.table.rows) if shape.table else ""
                shape.math = len(el.findall(".//" + q("m:oMath")))
            elif shape.frame == "ole":
                ole = el.find(".//" + q("p:oleObj"))
                shape.prog_id = ole.get("progId") if ole is not None else None
                pic = el.find(".//" + q("p:pic"))
                if pic is not None:
                    fill = pic.find(q("p:blipFill"))
                    shape.image = self.image(fill.find(q("a:blip")) if fill is not None else None)
        if kind == "grpSp":
            gpr = el.find(q("p:grpSpPr"))
            child_map = _group_map(gpr.find(q("a:xfrm"))) if gpr is not None else None
            if child_map is not None and mapper is not None:
                outer = mapper
                child_map = (lambda inner: (lambda b: outer(inner(b))))(child_map)
            shape.children = self.shapes(el, depth + 1, child_map or mapper, alternate)
        shape.links = _links(el, self.rels, cnvpr)
        if depth == 0 and self.part.startswith("ppt/slides/"):
            for rpr in el.iter():
                if rpr.tag in (q("a:rPr"), q("a:endParaRPr")) and rpr.get("lang"):
                    self.deck.languages[rpr.get("lang")] += 1
        return shape


def _base_type(ph_type):
    """The master placeholder a slide's placeholder takes its place from."""
    if ph_type in TITLE_TYPES:
        return "title"
    if ph_type in ("body", "obj", "subTitle", "tbl", "chart", "dgm", "media", "clipArt", "pic"):
        return "body"
    return ph_type


def _placeholder_boxes(zf, part, parent=None):
    """{("idx", n) or ("type", t): Box} for a layout's or master's
    placeholders, falling back to the parent's."""
    found = dict(parent or {})
    root = parse_xml(zf.read(part))
    tree = root.find(".//" + q("p:spTree"))
    if tree is None:
        return found
    for el in tree.iter():
        if el.tag not in (q("p:sp"), q("p:pic"), q("p:graphicFrame")):
            continue
        ph = el.find(".//" + q("p:nvPr") + "/" + q("p:ph"))
        if ph is None:
            continue
        xfrm = el.find(q("p:xfrm")) if el.tag == q("p:graphicFrame") else \
            (el.find(q("p:spPr")).find(q("a:xfrm")) if el.find(q("p:spPr")) is not None else None)
        box = _offset(xfrm)
        if box is None:
            continue
        found[("idx", ph.get("idx") or "0")] = box
        found[("type", _base_type(ph.get("type") or "obj"))] = box
    return found


def read(path):
    """A Deck from a .pptx file."""
    deck = Deck(path)
    with zipfile.ZipFile(path) as zf:

        def part_xml(part):
            problems = []
            root = parse_xml(zf.read(part), problems)
            deck.malformed.extend((part, problem) for problem in problems)
            return root

        deck.parts = zf.namelist()
        pres_part = "ppt/presentation.xml"
        root_rels = relationships(zf, "")
        main = rel_target(root_rels, "officeDocument")
        if main:
            pres_part = main
        deck.presentation_part = pres_part
        pres = part_xml(pres_part)
        pres_rels = relationships(zf, pres_part)
        size = pres.find(q("p:sldSz"))
        if size is not None:
            deck.width, deck.height = int(size.get("cx", 0)), int(size.get("cy", 0))
        default = pres.find(".//" + q("p:defaultTextStyle") + "//" + q("a:defRPr"))
        if default is not None and default.get("lang"):
            deck.default_language = default.get("lang")
        for ext in pres.iter(q("p:ext")):
            if ext.get("uri") == SECTIONS_URI:
                for section in ext.iter(q("p14:section")):
                    ids = [s.get("id") for s in section.iter(q("p14:sldId"))]
                    deck.sections.append((section.get("name") or "", ids))
        section_of = {sid: name for name, ids in deck.sections for sid in ids}
        id_list = pres.find(q("p:sldIdLst"))
        entries = list(id_list) if id_list is not None else []
        boxes_cache = {}
        for number, entry in enumerate(entries, 1):
            rid = entry.get(q("r:id"))
            if rid not in pres_rels:
                continue
            part = pres_rels[rid][1]
            slide = Slide(number, part, entry.get("id"))
            slide.section = section_of.get(slide.slide_id)
            root = part_xml(part)
            slide.hidden = root.get("show") in ("0", "false")
            rels = relationships(zf, part)
            layout = rel_target(rels, "slideLayout")
            inherited = {}
            if layout:
                slide.layout_part = layout
                try:
                    layout_root = parse_xml(zf.read(layout))
                    csld = layout_root.find(q("p:cSld"))
                    slide.layout = csld.get("name") if csld is not None else None
                    if layout not in boxes_cache:
                        master = rel_target(relationships(zf, layout), "slideMaster")
                        if master and master not in boxes_cache:
                            boxes_cache[master] = _placeholder_boxes(zf, master)
                        boxes_cache[layout] = _placeholder_boxes(
                            zf, layout, boxes_cache.get(master))
                    inherited = boxes_cache[layout]
                except KeyError:
                    pass
            tree = root.find(".//" + q("p:spTree"))
            reader = _Reader(zf, deck, part, rels, inherited)
            slide.shapes = reader.shapes(tree) if tree is not None else []
            notes = rel_target(rels, "notesSlide")
            if notes:
                try:
                    nroot = part_xml(notes)
                    texts = []
                    for sp in nroot.iter(q("p:sp")):
                        ph = sp.find(".//" + q("p:ph"))
                        if ph is not None and ph.get("type") == "body":
                            texts.extend(_text_body(sp))
                    slide.notes = "\n".join(texts).strip()
                except KeyError:
                    pass
            deck.slides.append(slide)
        for part in sorted(boxes_cache):
            try:
                root = part_xml(part)
            except KeyError:
                continue
            tree = root.find(".//" + q("p:spTree"))
            if tree is not None:
                reader = _Reader(zf, deck, part, relationships(zf, part))
                deck.masters.append((part, reader.shapes(tree)))
            styles = root.find(q("p:txStyles"))
            for default in (styles.iter(q("a:defRPr")) if styles is not None else ()):
                if default.get("lang"):
                    deck.master_languages[default.get("lang")] += 1
        core = rel_target(root_rels, "core-properties") or "docProps/core.xml"
        if core in deck.parts:
            croot = parse_xml(zf.read(core))
            title = croot.find(q("dc:title"))
            deck.core_title = title.text.strip() if title is not None and title.text else None
            creator = croot.find(q("dc:creator"))
            deck.creator = creator.text if creator is not None else None
        app = rel_target(root_rels, "extended-properties") or "docProps/app.xml"
        if app in deck.parts:
            match = re.search(rb"<Application>([^<]*)</Application>", zf.read(app))
            deck.application = match.group(1).decode("utf-8", "replace") if match else None
    return deck


def short_hash(digest):
    """The part of an image's SHA-256 its sidecar key uses."""
    return digest[:16]
