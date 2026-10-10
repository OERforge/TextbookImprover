#!/usr/bin/env python3
"""
run-slides-tests.py -- PowerPoint decks: reading one, checking it, writing
a person's decisions into a copy, and a run of convert.py over a folder
of them.

    python3 tests/run-slides-tests.py

Builds small decks as PresentationML with the standard library, so every
shape a check or a decision is about is there on purpose, and reads back
what the code wrote. The parts that run convert.py need Pandoc 3.9 or
later, which convert.py requires of every run, and are skipped without
it; the rest needs nothing but the standard library.

WHY THESE EXIST

A deck is remediated by editing its XML as text, so that nothing a
person or PowerPoint wrote is lost to a parser's idea of the file. Every
edit is therefore a pattern that has to find exactly its element and
nothing else, in Choice and Fallback alike, and leave every other byte
where it was; and every decision is found again by a key a person copied
from a report into a sidecar. Each of those is pinned here, with the
checks that say what a deck still needs, since a check that never fires
and an edit that quietly lands nowhere look the same from outside.

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

import csv
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
import zlib
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import deckrun  # noqa: E402
import pptxcheck  # noqa: E402
import pptxorder  # noqa: E402
import pptxparse  # noqa: E402
import pptxremediate as rem  # noqa: E402

NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
MC = ('xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
      'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"')
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
EMU = 914400


# ---------------------------------------------------------------------------
# Building decks
# ---------------------------------------------------------------------------

def png(red, green, blue):
    """A one-pixel PNG of a color, so each color is an image of its own."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes([0, red, green, blue])))
            + chunk(b"IEND", b""))


RED, GREEN, BLUE = png(200, 0, 0), png(0, 200, 0), png(0, 0, 200)


def esc(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def nv(tag, shape_id, name, descr=None, decorative=False, ph=None, extra=""):
    """A shape's non-visual properties: its id, name, description, and
    decorative mark, and its placeholder."""
    attrs = ' descr="%s"' % esc(descr) if descr is not None else ""
    inner = ""
    if decorative:
        inner = ('<a:extLst><a:ext uri="{C183D7F6-B498-43B3-948B-1728B52AA6E4}">'
                 '<adec:decorative xmlns:adec="http://schemas.microsoft.com/office/drawing/'
                 '2017/decorative" val="1"/></a:ext></a:extLst>')
    cnvpr = ('<p:cNvPr id="%s" name="%s"%s>%s</p:cNvPr>' % (shape_id, esc(name), attrs, inner)
             if inner else '<p:cNvPr id="%s" name="%s"%s/>' % (shape_id, esc(name), attrs))
    kind = {"sp": "p:cNvSpPr", "pic": "p:cNvPicPr", "graphicFrame": "p:cNvGraphicFramePr",
            "grpSp": "p:cNvGrpSpPr", "cxnSp": "p:cNvCxnSpPr"}[tag]
    nvpr = "<p:nvPr>%s%s</p:nvPr>" % (ph or "", extra)
    return "<p:nv%sPr>%s<%s/>%s</p:nv%sPr>" % (tag[0].upper() + tag[1:], cnvpr, kind, nvpr,
                                               tag[0].upper() + tag[1:])


def xfrm(x, y, cx, cy, tag="a:xfrm"):
    return '<%s><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/></%s>' % (tag, x, y, cx, cy, tag)


def body(paragraphs, lang=None, link=None):
    """A text body: each paragraph a run, the first linked when link is a
    relationship id."""
    out = []
    lang_attr = ' lang="%s"' % lang if lang else ""
    for i, text in enumerate(paragraphs):
        if link and i == 0:
            rpr = '<a:rPr%s><a:hlinkClick r:id="%s"/></a:rPr>' % (lang_attr, link)
        else:
            rpr = "<a:rPr%s/>" % lang_attr if lang else ""
        out.append("<a:p><a:r>%s<a:t>%s</a:t></a:r></a:p>" % (rpr, esc(text)))
    return "<p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody>" % ("".join(out) or "<a:p/>")


def title(shape_id, text, ph_type="title", box=None, lang=None):
    """A title placeholder, placed by the layout unless box says."""
    sppr = "<p:spPr>%s</p:spPr>" % xfrm(*box) if box else "<p:spPr/>"
    return ("<p:sp>%s%s%s</p:sp>"
            % (nv("sp", shape_id, "Title %s" % shape_id, ph='<p:ph type="%s"/>' % ph_type),
               sppr, body([text] if text else [], lang)))


def content(shape_id, paragraphs, box=None, lang=None):
    """The layout's content placeholder (idx 1)."""
    sppr = "<p:spPr>%s</p:spPr>" % xfrm(*box) if box else "<p:spPr/>"
    return ("<p:sp>%s%s%s</p:sp>"
            % (nv("sp", shape_id, "Content Placeholder %s" % shape_id, ph='<p:ph idx="1"/>'),
               sppr, body(paragraphs, lang)))


def textbox(shape_id, name, paragraphs, box, link=None, lang=None):
    return ("<p:sp>%s<p:spPr>%s<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></p:spPr>%s</p:sp>"
            % (nv("sp", shape_id, name), xfrm(*box), body(paragraphs, lang, link)))


def rect(shape_id, name, box, descr=None, decorative=False):
    """A shape with no text."""
    return ("<p:sp>%s<p:spPr>%s<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></p:spPr></p:sp>"
            % (nv("sp", shape_id, name, descr, decorative), xfrm(*box)))


def line(shape_id, box):
    return ("<p:cxnSp>%s<p:spPr>%s<a:prstGeom prst=\"line\"><a:avLst/></a:prstGeom></p:spPr>"
            "</p:cxnSp>" % (nv("cxnSp", shape_id, "Straight Connector %s" % shape_id), xfrm(*box)))


def pic(shape_id, rid, box, descr=None, decorative=False, name=None, extra=""):
    return ("<p:pic>%s<p:blipFill><a:blip r:embed=\"%s\"/><a:stretch><a:fillRect/></a:stretch>"
            "</p:blipFill><p:spPr>%s<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></p:spPr>"
            "</p:pic>" % (nv("pic", shape_id, name or "Picture %s" % shape_id, descr, decorative,
                             extra=extra), rid, xfrm(*box)))


def video(shape_id, rid, box):
    return ("<p:pic>%s<p:blipFill><a:blip r:embed=\"%s\"/></p:blipFill><p:spPr>%s</p:spPr>"
            "</p:pic>" % (nv("pic", shape_id, "Video %s" % shape_id, "A talk",
                             extra='<a:videoFile r:link="%s"/>' % rid), rid, xfrm(*box)))


def group(shape_id, children, box, descr=None, decorative=False):
    x, y, cx, cy = box
    return ('<p:grpSp>%s<p:grpSpPr><a:xfrm><a:off x="%d" y="%d"/><a:ext cx="%d" cy="%d"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="%d" cy="%d"/></a:xfrm></p:grpSpPr>%s</p:grpSp>'
            % (nv("grpSp", shape_id, "Group %s" % shape_id, descr, decorative), x, y, cx, cy,
               cx * 2, cy * 2, "".join(children)))


def cell(text, bold=False, attrs=""):
    rpr = '<a:rPr b="1"/>' if bold else ""
    return ("<a:tc%s><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r>%s<a:t>%s</a:t></a:r></a:p>"
            "</a:txBody><a:tcPr/></a:tc>" % (attrs, rpr, esc(text)) if text is not None else
            "<a:tc%s><a:txBody><a:bodyPr/><a:lstStyle/><a:p/></a:txBody><a:tcPr/></a:tc>" % attrs)


def table(shape_id, rows, box, first_row=False, first_col=False, cells=None):
    """A table; cells, if given, are a row's <a:tc> elements as written."""
    flags = "".join([' firstRow="1"' if first_row else "", ' firstCol="1"' if first_col else ""])
    width = max(len(r) for r in rows)
    grid = "".join('<a:gridCol w="%d"/>' % (box[2] // width) for _ in range(width))
    body_rows = "".join('<a:tr h="370840">%s</a:tr>' % ("".join(cells[i]) if cells and i in cells
                                                        else "".join(cell(t) for t in row))
                        for i, row in enumerate(rows))
    return ('<p:graphicFrame>%s%s<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
            'drawingml/2006/table"><a:tbl><a:tblPr%s/><a:tblGrid>%s</a:tblGrid>%s</a:tbl>'
            '</a:graphicData></a:graphic></p:graphicFrame>'
            % (nv("graphicFrame", shape_id, "Table %s" % shape_id), xfrm(*box, tag="p:xfrm"),
               flags, grid, body_rows))


def chart(shape_id, rid, box, descr=None):
    return ('<p:graphicFrame>%s%s<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/'
            'drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/'
            '2006/chart" r:id="%s"/></a:graphicData></a:graphic></p:graphicFrame>'
            % (nv("graphicFrame", shape_id, "Chart %s" % shape_id, descr),
               xfrm(*box, tag="p:xfrm"), rid))


def alternate(choice, fallback):
    return ('<mc:AlternateContent %s><mc:Choice Requires="p14">%s</mc:Choice>'
            '<mc:Fallback>%s</mc:Fallback></mc:AlternateContent>' % (MC, choice, fallback))


def slide_xml(shapes, hidden=False):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sld %s%s><p:cSld>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>%s</p:spTree>'
            '</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
            % (NS, ' show="0"' if hidden else "", "".join(shapes)))


def rels(entries):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
            % "".join('<Relationship Id="%s" Type="%s%s" Target="%s"%s/>'
                      % (rid, REL, kind, esc(target), ' TargetMode="External"' if external else "")
                      for rid, kind, target, external in entries))


TITLE_BOX = (457200, 274320, 8229600, 1143000)
BODY_BOX = (457200, 1600200, 8229600, 4525963)


def layout_xml():
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldLayout %s type="obj">'
            '<p:cSld name="Title and Content"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
            '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>%s%s</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
            % (NS, title(2, "", box=TITLE_BOX), content(3, [], box=BODY_BOX)))


def master_xml(logo=False, styles_lang=None):
    lang = ' lang="%s"' % styles_lang if styles_lang else ""
    level = '<a:lvl1pPr><a:defRPr sz="2800"%s/></a:lvl1pPr>' % lang
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldMaster %s><p:cSld>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/>%s%s</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" '
            'bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
            'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
            'folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/>'
            '</p:sldLayoutIdLst><p:txStyles><p:titleStyle>%s</p:titleStyle><p:bodyStyle>%s'
            '</p:bodyStyle><p:otherStyle><a:defPPr><a:defRPr%s/></a:defPPr>%s</p:otherStyle>'
            '</p:txStyles></p:sldMaster>'
            % (NS, title(2, "", box=TITLE_BOX),
               pic(7, "rId2", (8229600, 6172200, 457200, 457200), name="Logo") if logo else "",
               level, level, lang, level))


def presentation_xml(count, default_lang="en-US", sections=None, style=True):
    ids = "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, 2 + i) for i in range(count))
    lang = ' lang="%s"' % default_lang if default_lang else ""
    styles = ('<p:defaultTextStyle><a:defPPr><a:defRPr%s/></a:defPPr><a:lvl1pPr>'
              '<a:defRPr sz="1800"/></a:lvl1pPr></p:defaultTextStyle>' % lang) if style else ""
    ext = ""
    if sections:
        ext = ('<p:extLst><p:ext uri="{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"><p14:sectionLst %s>'
               % MC + "".join('<p14:section name="%s" id="{00000000-0000-0000-0000-00000000000%d}">'
                              '<p14:sldIdLst>%s</p14:sldIdLst></p14:section>'
                              % (esc(name), n, "".join('<p14:sldId id="%d"/>' % (256 + i)
                                                       for i in members))
                              for n, (name, members) in enumerate(sections))
               + '</p14:sectionLst></p:ext></p:extLst>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:presentation %s>'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            '<p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/>'
            '<p:notesSz cx="6858000" cy="9144000"/>%s%s</p:presentation>'
            % (NS, ids, styles, ext))


def core_xml(core_title):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">%s<dc:creator>Test</dc:creator>'
            '</cp:coreProperties>' % ("<dc:title>%s</dc:title>" % esc(core_title)
                                      if core_title else "<dc:title></dc:title>"))


def notes_xml(text):
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:notes %s><p:cSld>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/><p:sp>%s<p:spPr/>%s</p:sp></p:spTree></p:cSld></p:notes>'
            % (NS, nv("sp", 3, "Notes Placeholder 2", ph='<p:ph type="body" idx="1"/>'),
               body([text])))


def deck(path, slides, default_lang="en-US", core_title="A Deck", sections=None, logo=False,
         style=True, styles_lang=None):
    """A deck: each slide a dict of shapes, and its images, links, charts,
    notes, and whether it's hidden, by relationship id."""
    types = ['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/>', '<Default Extension="xml" ContentType="application/xml"/>',
             '<Default Extension="png" ContentType="image/png"/>',
             '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.'
             'openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
             '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/'
             'vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
             '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/'
             'vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
             '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-'
             'package.core-properties+xml"/>']
    parts = [("_rels/.rels", rels([("rId1", "officeDocument", "ppt/presentation.xml", False),
                                   ("rId2", "metadata/core-properties", "docProps/core.xml",
                                    False)]).replace(REL + "metadata/core-properties",
                                                     "http://schemas.openxmlformats.org/package/"
                                                     "2006/relationships/metadata/"
                                                     "core-properties")),
             ("docProps/core.xml", core_xml(core_title)),
             ("ppt/presentation.xml", presentation_xml(len(slides), default_lang, sections,
                                                       style)),
             ("ppt/_rels/presentation.xml.rels",
              rels([("rId1", "slideMaster", "slideMasters/slideMaster1.xml", False)]
                   + [("rId%d" % (2 + i), "slide", "slides/slide%d.xml" % (i + 1), False)
                      for i in range(len(slides))])),
             ("ppt/slideMasters/slideMaster1.xml", master_xml(logo, styles_lang)),
             ("ppt/slideMasters/_rels/slideMaster1.xml.rels",
              rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False)]
                   + ([("rId2", "image", "../media/logo.png", False)] if logo else []))),
             ("ppt/slideLayouts/slideLayout1.xml", layout_xml()),
             ("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
              rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml", False)]))]
    if logo:
        parts.append(("ppt/media/logo.png", BLUE))
    for number, spec in enumerate(slides, 1):
        entries = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False)]
        for rid, data in sorted(spec.get("images", {}).items()):
            name = "ppt/media/s%d-%s.png" % (number, rid)
            parts.append((name, data))
            entries.append((rid, "image", "../media/" + os.path.basename(name), False))
        for rid, url in sorted(spec.get("links", {}).items()):
            entries.append((rid, "hyperlink", url, True))
        for rid in sorted(spec.get("charts", ())):
            name = "ppt/charts/chart%d%s.xml" % (number, rid)
            parts.append((name, '<?xml version="1.0"?><c:chartSpace xmlns:c="http://schemas.'
                                'openxmlformats.org/drawingml/2006/chart"/>'))
            entries.append((rid, "chart", "../charts/" + os.path.basename(name), False))
        for rid in sorted(spec.get("videos", ())):
            entries.append((rid, "video", "https://example.org/talk.mp4", True))
        if spec.get("notes"):
            parts.append(("ppt/notesSlides/notesSlide%d.xml" % number, notes_xml(spec["notes"])))
            entries.append(("rId99", "notesSlide", "../notesSlides/notesSlide%d.xml" % number,
                            False))
            types.append('<Override PartName="/ppt/notesSlides/notesSlide%d.xml" ContentType="'
                         'application/vnd.openxmlformats-officedocument.presentationml.'
                         'notesSlide+xml"/>' % number)
        parts.append(("ppt/slides/slide%d.xml" % number,
                      slide_xml(spec.get("shapes", []), spec.get("hidden", False))))
        parts.append(("ppt/slides/_rels/slide%d.xml.rels" % number, rels(entries)))
        types.append('<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.'
                     'openxmlformats-officedocument.presentationml.slide+xml"/>' % number)
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns='
                     '"http://schemas.openxmlformats.org/package/2006/content-types">%s</Types>'
                     % "".join(types))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        for name, data in parts:
            z.writestr(name, data)
    return path


def read_part(path, part):
    with zipfile.ZipFile(path) as z:
        return z.read(part).decode("utf-8")


def read_part_bytes(path, part):
    with zipfile.ZipFile(path) as z:
        return z.read(part)


def checks_of(found):
    return sorted({f.check for f in found})


def utf16(path, part):
    """A deck with one part rewritten in UTF-16, its byte-order mark first,
    as OPC allows."""
    with zipfile.ZipFile(path) as z:
        members = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            if info.filename == part:
                data = data.decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
                data = data.encode("utf-16-le")
                data = b"\xff\xfe" + data
            z.writestr(info, data)
    return path


# ---------------------------------------------------------------------------
# The decks the checks are about
# ---------------------------------------------------------------------------

def clean_deck(path):
    """A deck with nothing to report: titles, described pictures, a table
    with its header row, a language, and a title in its properties."""
    return deck(path, [
        {"shapes": [title(2, "The Course", "ctrTitle", box=TITLE_BOX),
                    content(3, ["Week one"])]},
        {"shapes": [title(2, "Supply"), content(3, ["Prices rise", "Quantities fall"]),
                    pic(4, "rId2", (7000000, 2000000, 2000000, 2000000), "A supply curve")],
         "images": {"rId2": RED}},
        {"shapes": [title(2, "Prices"),
                    table(4, [["Good", "Price"], ["Bread", "2"]], (457200, 1600200, 6000000, 800000),
                          first_row=True)]},
    ], sections=[("Introduction", [0]), ("Markets", [1, 2])])


def messy_deck(path):
    """A deck with one of each problem, each on a slide of its own."""
    loose = [rect(10 + i, "Rectangle %d" % i, (300000 * i, 3000000, 200000, 200000))
             for i in range(5)] + [line(20 + i, (300000 * i, 3500000, 200000, 0)) for i in range(3)]
    return deck(path, [
        # 1: no title at all, a picture with no alt text
        {"shapes": [pic(4, "rId2", (457200, 1600200, 2000000, 2000000))], "images": {"rId2": RED}},
        # 2: an empty title placeholder; a chart with no alt text
        {"shapes": [title(2, ""), chart(5, "rId3", (457200, 1600200, 4000000, 3000000))],
         "charts": ["rId3"]},
        # 3: a table without its header row, with merged cells
        {"shapes": [title(2, "Costs"), table(4, [["Cost", "Amount", ""], ["Fixed", "10", "x"]],
                                             (457200, 1600200, 6000000, 800000),
                                             cells={0: [cell("Cost"), cell("Amount", attrs=' gridSpan="2"'),
                                                        cell(None, attrs=' hMerge="1"')]})]},
        # 4: the title read last, below the text it heads
        {"shapes": [textbox(4, "TextBox 3", ["Read first"], (457200, 1600200, 4000000, 600000)),
                    title(2, "Costs")]},
        # 5: a video, a group with no alt text holding a picture with none
        {"shapes": [title(2, "Media"), video(4, "rId5", (457200, 1600200, 3000000, 2000000)),
                    group(6, [rect(7, "Rectangle 6", (0, 0, 100000, 100000)),
                              pic(8, "rId2", (200000, 0, 100000, 100000))],
                          (5000000, 1600200, 2000000, 2000000))],
         "images": {"rId2": GREEN}, "videos": ["rId5"]},
        # 6: alt text that says nothing, in five ways, and some too long
        {"shapes": [title(2, "Words"),
                    pic(4, "rId2", (0, 1600200, 900000, 900000), "IMG_2041.JPG"),
                    pic(5, "rId3", (1000000, 1600200, 900000, 900000), "..."),
                    pic(6, "rId4", (2000000, 1600200, 900000, 900000), "Image"),
                    pic(7, "rId5", (3000000, 1600200, 900000, 900000), "j0309720"),
                    pic(8, "rId6", (4000000, 1600200, 900000, 900000),
                        "A close up of a logo\n\nDescription automatically generated"),
                    pic(9, "rId7", (5000000, 1600200, 900000, 900000), "x" * 130),
                    pic(10, "rId8", (6000000, 1600200, 900000, 900000), "Picture 9")],
         "images": {"rId2": png(1, 1, 1), "rId3": png(2, 2, 2), "rId4": png(3, 3, 3),
                    "rId5": png(4, 4, 4), "rId6": png(5, 5, 5), "rId7": png(6, 6, 6),
                    "rId8": png(7, 7, 7)}},
        # 7: decorative with a description; a hidden slide; a bare link;
        # columns laid out with tabs
        {"shapes": [title(2, "Words"),
                    pic(4, "rId2", (0, 1600200, 900000, 900000), "A flourish", decorative=True),
                    textbox(5, "TextBox 4", ["https://example.org/"], (0, 3000000, 4000000, 400000),
                            link="rId3"),
                    textbox(6, "TextBox 5", ["Good\tPrice\tTax", "Bread\t2\t0"],
                            (5000000, 3000000, 4000000, 800000))],
         "images": {"rId2": png(9, 9, 9)}, "links": {"rId3": "https://example.org"},
         "hidden": True},
        # 8: a diagram drawn with loose shapes
        {"shapes": [title(2, "A diagram")] + loose},
    ], default_lang=None, core_title=None, sections=[("Default Section", [0, 1, 2]),
                                                    ("Part", [3, 4]), ("part", [5, 6, 7])],
        logo=True)


def case_parse(work):
    path = clean_deck(os.path.join(work, "clean.pptx"))
    d = pptxparse.read(path)
    yield "a centered title is a title, and each slide's is read", \
        [s.title for s in d.slides] == ["The Course", "Supply", "Prices"], [s.title for s in d.slides]
    placed = d.slides[1].shapes[0].box
    yield "a placeholder with no position of its own takes its layout's", \
        placed is not None and (placed.x, placed.y) == TITLE_BOX[:2], placed
    yield "the slide size, sections, default language, and core title are read", \
        (d.width, d.height) == (12192000, 6858000) and d.default_language == "en-US" \
        and d.core_title == "A Deck" and [n for n, _ in d.sections] == ["Introduction", "Markets"], \
        (d.width, d.default_language, d.core_title, d.sections)
    tbl = d.slides[2].shapes[1].table
    yield "a table's cells and its header row are read", \
        tbl is not None and tbl.rows == [["Good", "Price"], ["Bread", "2"]] and tbl.first_row \
        and not tbl.first_col and not tbl.merged, tbl and tbl.rows
    # The same picture twice, in a group whose children are placed through
    # it, and in mc:AlternateContent, read from the Choice.
    other = deck(os.path.join(work, "other.pptx"), [
        {"shapes": [title(2, "One"), group(4, [pic(5, "rId2", (1000, 2000, 400, 400))],
                                           (100000, 200000, 1000, 1000))],
         "images": {"rId2": RED}},
        {"shapes": [title(2, "Two"), alternate(pic(4, "rId2", (0, 0, 10, 10), "Choice"),
                                               pic(4, "rId2", (0, 0, 10, 10), "Fallback"))],
         "images": {"rId2": RED}, "notes": "Say this aloud.", "hidden": True},
    ])
    d = pptxparse.read(other)
    child = d.slides[0].shapes[1].children[0]
    yield "a group's child is placed through the group's transform", \
        child.box is not None and (child.box.x, child.box.y, child.box.cx) == (100500, 201000, 200), \
        child.box
    pictures = [s for _slide, s in d.pictures()]
    yield "one image in two parts is one picture by its content, read once from AlternateContent", \
        len(pictures) == 2 and len({p.image[1] for p in pictures}) == 1 \
        and pictures[1].alternate and pictures[1].descr == "Choice" and len(d.images) == 1, \
        [(p.image, p.descr) for p in pictures]
    yield "speaker notes and a hidden slide are read", \
        d.slides[1].notes == "Say this aloud." and d.slides[1].hidden and not d.slides[0].hidden, \
        (d.slides[1].notes, d.slides[1].hidden)


def case_check(work):
    found = pptxcheck.check(pptxparse.read(clean_deck(os.path.join(work, "clean.pptx"))))
    yield "a clean deck has nothing to report", not found, [(f.check, f.where) for f in found]
    found = pptxcheck.check(pptxparse.read(messy_deck(os.path.join(work, "messy.pptx"))))
    by = {}
    for f in found:
        by.setdefault(f.check, []).append(f)
    expected = {
        "pptx-slide-no-title": 2, "pptx-object-no-alt": 3, "pptx-table-no-header": 1,
        "pptx-merged-cells": 1, "pptx-reading-order": 1, "pptx-media-no-captions": 1,
        "pptx-shape-no-alt": 1, "pptx-alt-is-file-name": 1, "pptx-alt-placeholder": 4,
        "pptx-alt-auto-generated": 1, "pptx-alt-too-long": 1, "pptx-decorative-with-alt": 1,
        "pptx-hidden-slide": 1, "pptx-link-bare-url": 1, "pptx-tab-table": 1,
        "pptx-drawn-diagram": 1, "pptx-duplicate-title": 2, "pptx-section-default-name": 1,
        "pptx-duplicate-section": 1, "pptx-no-language": 1, "pptx-no-core-title": 1,
        "pptx-master-image-no-alt": 1,
    }
    counts = {k: len(v) for k, v in by.items()}
    for check, n in sorted(expected.items()):
        yield "%s: found %d time(s) in the messy deck" % (check, n), counts.get(check) == n, \
            [(f.where, f.detail) for f in by.get(check, [])]
    yield "and nothing else", set(counts) == set(expected), sorted(set(counts) ^ set(expected))
    # Each finding names its kind and the checks' own meaning.
    yield "every finding is a source-pptx finding with a known check", \
        all(f.kind == "source-pptx" and f.severity in ("error", "warning", "note") for f in found), ""
    # The group's rectangle is the group's to describe; its picture isn't.
    wheres = [f.where for f in by.get("pptx-object-no-alt", [])]
    yield "a picture inside an undescribed group still needs its own alt text", \
        "slide 5, Picture 8" in wheres and not any("Rectangle 6" in w for w in
                                                   [f.where for f in found]), wheres
    # A pattern of the project's own, plain or a regular expression.
    rules = pptxcheck.placeholder_rules(["slide image", "re:fig\\. ?\\d+"])
    yield "images.alt_placeholders: a phrase and a re: pattern say nothing too", \
        pptxcheck.alt_problem("Slide Image.", rules=rules)[0] == "pptx-alt-placeholder" \
        and pptxcheck.alt_problem("Fig. 12", rules=rules)[0] == "pptx-alt-placeholder" \
        and pptxcheck.alt_problem("A figure of twelve bars", rules=rules) is None, ""
    yield "the length limit is the project's", \
        pptxcheck.alt_problem("y" * 50, limit=40)[0] == "pptx-alt-too-long" \
        and pptxcheck.alt_problem("y" * 50, limit=60) is None, ""
    yield "a decorative group quiets its pieces", not list(pptxcheck.alt_items(
        pptxparse.read(deck(os.path.join(work, "quiet.pptx"), [
            {"shapes": [title(2, "Q"), group(4, [pic(5, "rId2", (0, 0, 10, 10)),
                                                 rect(6, "Rectangle 5", (20, 0, 10, 10))],
                                             (0, 1600200, 100, 100), decorative=True)],
             "images": {"rId2": RED}}])).slides[0])), ""


def remediated(work, name, source, alts=None, tables=None, titles=None, language=None,
               core_title=True):
    out = os.path.join(work, "out", name)
    counts = rem.remediate(source, out, alts, tables, titles, language, core_title)
    return out, counts


def case_remediate(work):
    path = messy_deck(os.path.join(work, "messy.pptx"))
    d = pptxparse.read(path)
    dname = rem.deck_name(path)

    def on(number, name, deck_=None):
        """The shape a slide has by that name, and the slide."""
        slide = (deck_ or d).slides[number - 1]
        return slide, next(s for s in slide.all_shapes() if s.name == name)

    red = on(1, "Picture 4")[1].image[1]
    chart_slide, chart_shape = on(2, "Chart 5")
    group_slide, group_shape = on(5, "Group 6")
    # The marker as a person types it, not as the sidecar reader gives it:
    # a decision is decorative either way.
    alts = {rem.image_key(red): "A red square",
            rem.object_key(dname, chart_slide, chart_shape): 'Costs "rise" <fast> & fall',
            rem.object_key(dname, group_slide, group_shape): "Decorative"}
    seven = [s for s in d.slides[6].all_shapes() if s.image][0]
    alts[rem.image_key(seven.image[1])] = "A flourish, described"
    logo = [s for _p, tops in d.masters for t in tops for s in t.walk() if s.image][0]
    alts[rem.image_key(logo.image[1])] = None          # decorative, everywhere
    table_shape = on(3, "Table 4")[1]
    tables = {table_shape.table.key(): "first-row"}
    titles = {rem.slide_key(dname, d.slides[0]): "Opening",
              rem.slide_key(dname, d.slides[1]): "A chart"}
    out, counts = remediated(work, "messy.pptx", path, alts, tables, titles, "en-GB")
    e = pptxparse.read(out)
    yield "the counts say what was written", \
        (counts["described"], counts["decorative"], counts["header_rows"], counts["titles"],
         counts["language"], counts["core_title"]) == (3, 2, 1, 2, 1, 1), counts
    yield "a picture gets its alt text by its image's content", \
        on(1, "Picture 4", e)[1].descr == "A red square", [s.descr for s in e.slides[0].all_shapes()]
    yield "a chart gets its alt text by its slide and shape, escaped and read back whole", \
        on(2, "Chart 5", e)[1].descr == 'Costs "rise" <fast> & fall', on(2, "Chart 5", e)[1].descr
    grouped = on(5, "Group 6", e)[1]
    yield "a group marked decorative is marked, with no description", \
        grouped.decorative and not grouped.descr, grouped.descr
    seven = [s for s in e.slides[6].all_shapes() if s.image][0]
    yield "a decorative shape given alt text loses the mark and gets the text", \
        seven.descr == "A flourish, described" and not seven.decorative, (seven.descr, seven.decorative)
    logo = [s for _p, tops in e.masters for t in tops for s in t.walk() if s.image][0]
    yield "a picture on the master is marked decorative once, for every slide", \
        logo.decorative and not logo.descr, (logo.descr, logo.decorative)
    tbl = on(3, "Table 4", e)[1].table
    yield "a table gets the header row the sidecar decides", tbl.first_row and not tbl.first_col, ""
    yield "an empty title placeholder takes the title and moves above the slide", \
        e.slides[1].title == "A chart" and e.slides[1].title_shape.box.y < 0, \
        (e.slides[1].title, e.slides[1].title_shape and e.slides[1].title_shape.box)
    first = e.slides[0].shapes[0]
    yield "a slide with no title placeholder gets one first in its tree, above the slide", \
        e.slides[0].title == "Opening" and first.is_title and first.box.y < 0, \
        (e.slides[0].title, first)
    pres = read_part(out, "ppt/presentation.xml")
    master = read_part(out, "ppt/slideMasters/slideMaster1.xml")
    slide6 = read_part(out, "ppt/slides/slide6.xml")
    yield "a deck with no default language gets the project's in its default text style", \
        e.default_language == "en-GB" and '<a:defPPr><a:defRPr lang="en-GB"/></a:defPPr>' in pres, \
        re.findall(r"<p:defaultTextStyle>.{0,120}", pres)
    yield "and in its master's text styles, the runs left as they were", \
        master.count('lang="en-GB"') == 4 and 'lang=' not in slide6, master.count('lang="en-GB"')
    yield "the file's properties take the first slide's title, when they have none", \
        e.core_title == "Opening", e.core_title
    found = pptxcheck.check(e, kind="pptx")
    fixed = {"pptx-slide-no-title", "pptx-table-no-header", "pptx-no-language",
             "pptx-no-core-title", "pptx-master-image-no-alt", "pptx-decorative-with-alt"}
    yield "the copy's check no longer finds what was decided", \
        not fixed & set(checks_of(found)), sorted(fixed & set(checks_of(found)))
    # What wasn't decided is as it was, byte for byte, in the same order.
    with zipfile.ZipFile(path) as a, zipfile.ZipFile(out) as b:
        names_a, names_b = [i.filename for i in a.infolist()], [i.filename for i in b.infolist()]
        changed = sorted(n for n in names_a if a.read(n) != b.read(n))
        parses = all(ET.fromstring(b.read(n)) is not None for n in changed)
    yield "every part keeps its place, and only the decided ones change", \
        names_a == names_b and changed == ["docProps/core.xml", "ppt/presentation.xml",
                                           "ppt/slideMasters/slideMaster1.xml",
                                           "ppt/slides/slide1.xml", "ppt/slides/slide2.xml",
                                           "ppt/slides/slide3.xml", "ppt/slides/slide5.xml",
                                           "ppt/slides/slide7.xml"], changed
    yield "every changed part is still well-formed XML", parses, ""


def case_remediate_more(work):
    # A picture in mc:AlternateContent is described in Choice and Fallback.
    path = deck(os.path.join(work, "alt.pptx"), [
        {"shapes": [title(2, "One"), alternate(pic(4, "rId2", (0, 0, 10, 10)),
                                               pic(4, "rId2", (0, 0, 10, 10)))],
         "images": {"rId2": RED}}])
    digest = pptxparse.read(path).slides[0].shapes[1].image[1]
    out, counts = remediated(work, "alt.pptx", path, {rem.image_key(digest): "A red square"})
    xml = read_part(out, "ppt/slides/slide1.xml")
    yield "a shape in AlternateContent is described in its Choice and its Fallback", \
        xml.count('descr="A red square"') == 2 and counts["described"] == 1, \
        (xml.count('descr="A red square"'), counts)
    # A blank Alt keeps what the picture has: decided, and nothing written.
    out, counts = remediated(work, "kept.pptx", path, {rem.image_key(digest): ""})
    yield "a blank Alt leaves the picture as it is, and isn't counted", \
        counts["described"] == counts["decorative"] == 0 \
        and "descr" not in read_part(out, "ppt/slides/slide1.xml"), counts
    # A deck's own key wins over every deck's, for that deck alone.
    two = deck(os.path.join(work, "two.pptx"), [
        {"shapes": [title(2, "One"), pic(4, "rId2", (0, 0, 10, 10))], "images": {"rId2": RED}}])
    alts = {rem.image_key(digest): "Red", rem.image_key(digest, "two"): "Red, here"}
    one_out = remediated(work, "alt2.pptx", path, alts)[0]
    two_out = remediated(work, "two.pptx", two, alts)[0]
    yield "deck/media/... covers one deck's copies, media/... every other's", \
        pptxparse.read(one_out).slides[0].shapes[1].descr == "Red" \
        and pptxparse.read(two_out).slides[0].shapes[1].descr == "Red, here", ""
    # Existing extensions on a shape stay, beside the decorative mark.
    ext = ('<a:extLst><a:ext uri="{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}"><a16:creationId '
           'xmlns:a16="http://schemas.microsoft.com/office/drawing/2014/main" id="{1}"/>'
           '</a:ext></a:extLst>')
    keep = deck(os.path.join(work, "keep.pptx"), [
        {"shapes": [title(2, "One"), pic(4, "rId2", (0, 0, 10, 10), "x").replace(
            'descr="x"/>', 'descr="x">%s</p:cNvPr>' % ext)], "images": {"rId2": GREEN}}])
    green = pptxparse.read(keep).slides[0].shapes[1].image[1]
    out = remediated(work, "keep.pptx", keep, {rem.image_key(green): None})[0]
    xml = read_part(out, "ppt/slides/slide1.xml")
    yield "the decorative mark goes beside a shape's other extensions, which stay", \
        "a16:creationId" in xml and "adec:decorative" in xml and 'descr=' not in xml \
        and xml.count("<a:extLst>") == 1 and pptxparse.read(out).slides[0].shapes[1].decorative, \
        re.findall(r"<p:cNvPr.*?</p:cNvPr>", xml)
    # A table decided to have none is left, and a copy's check doesn't
    # count it as missing a header row; matrix is both.
    tdeck = deck(os.path.join(work, "tables.pptx"), [
        {"shapes": [title(2, "T"), table(4, [["a", "b"], ["c", "d"]], (0, 1600200, 900, 900)),
                    table(5, [["Year", "GDP"], ["2020", "1"]], (0, 3000000, 900, 900))]}])
    tables = pptxparse.read(tdeck).slides[0].shapes
    decided = {tables[1].table.key(): "none", tables[2].table.key(): "both"}
    out, counts = remediated(work, "tables.pptx", tdeck, tables=decided)
    copy = pptxparse.read(out).slides[0].shapes
    found = pptxcheck.check(pptxparse.read(out), tables=decided)
    yield "none on a table with no flags changes nothing, and both marks the row and the column", \
        not copy[1].table.first_row and copy[2].table.first_row and copy[2].table.first_col \
        and (counts["header_rows"], counts["header_columns"]) == (1, 1), counts
    yield "a table decided to have no headers isn't counted against the copy", \
        "pptx-table-no-header" not in checks_of(found), checks_of(found)
    # A deck that declares its language keeps it, whatever the project says.
    clean = clean_deck(os.path.join(work, "clean.pptx"))
    out, counts = remediated(work, "clean.pptx", clean, language="fr-FR")
    yield "a deck with a default language keeps it", \
        counts["language"] == 0 and pptxparse.read(out).default_language == "en-US", counts
    yield "and a deck with nothing decided comes out byte for byte", \
        open(out, "rb").read() != b"" and all(
            zipfile.ZipFile(out).read(n) == zipfile.ZipFile(clean).read(n)
            for n in zipfile.ZipFile(clean).namelist()), ""
    # A deck whose presentation has no default text style gets one.
    bare = deck(os.path.join(work, "bare.pptx"), [{"shapes": [title(2, "One")]}],
                default_lang=None, style=False)
    out, counts = remediated(work, "bare.pptx", bare, language="de-DE")
    yield "a presentation with no default text style gets one, in the schema's place", \
        pptxparse.read(out).default_language == "de-DE" and re.search(
            r'<p:notesSz [^>]*/><p:defaultTextStyle><a:defPPr><a:defRPr lang="de-DE"/>',
            read_part(out, "ppt/presentation.xml")) is not None, \
        read_part(out, "ppt/presentation.xml")[-200:]
    # A shape whose id its slide repeats is left alone, and said to be.
    dup = deck(os.path.join(work, "dup.pptx"), [
        {"shapes": [title(2, "One"), pic(4, "rId2", (0, 0, 10, 10)),
                    rect(4, "Rectangle 3", (20, 0, 10, 10))], "images": {"rId2": RED}}])
    out, counts = remediated(work, "dup.pptx", dup, {rem.image_key(digest): "Red"})
    yield "a decision for a shape whose id repeats on its slide is skipped and counted", \
        counts["skipped"] == 1 and counts["described"] == 0 \
        and "descr" not in read_part(out, "ppt/slides/slide1.xml"), counts


def case_sidecars(work):
    path = os.path.join(work, "image-alt.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["media/aaaa.png", "First"])            # no header row
        writer.writerow(["Image", "Alt", "Source"])               # one pasted in later
        writer.writerow(["media/bbbb.jpeg", "DECORATIVE"])
        writer.writerow(["deck/slide-256/shape-4", "A chart\n with a break"])
        writer.writerow(["media/cccc.png", ""])                  # reviewed: keep it
    rows = rem.alt_rows(path)
    yield "image-alt rows read by position, a header anywhere skipped, extensions aside, " \
        "a blank Alt kept as a review", \
        rows == {"media/aaaa": "First", "media/bbbb": None, "media/cccc": "",
                 "deck/slide-256/shape-4": "A chart with a break"}, rows
    path = os.path.join(work, "table-headers.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerows([["key", "headers"], ["k1", "Matrix"], ["k2", "grid"], ["k3", "manual"],
                          ["k4", "sideways"], ["k5", "first-row"]])
    unknown = set()
    rows = rem.header_rows(path, unknown)
    yield "table-headers rows: matrix and grid as both and none; manual and an unknown value " \
        "decided, leaving the table alone, the unknown one named", \
        rows == {"k1": "both", "k2": "none", "k3": "", "k4": "", "k5": "first-row"} \
        and unknown == {"sideways"}, (rows, unknown)
    path = os.path.join(work, "slide-titles.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.TITLE_COLUMNS, ["d/slide-257", "  A  title ", "", "", ""],
                                  ["d/slide-258", "", "", "", ""]])
    yield "slide-titles rows: a title per slide, spaces squeezed, blanks left out", \
        rem.title_rows(path) == {"d/slide-257": "A title"}, rem.title_rows(path)


def case_edges(work):
    """What a review of the first version found, each pinned."""
    # A backslash in alt text is a backslash, on a shape that has a
    # description already as on one that hasn't; control characters,
    # which XML has no place for, are left out.
    path = deck(os.path.join(work, "tex.pptx"), [
        {"shapes": [title(2, "One"), pic(4, "rId2", (0, 0, 10, 10), "old"),
                    pic(5, "rId3", (20, 0, 10, 10))], "images": {"rId2": RED, "rId3": GREEN}}],
        core_title=None)
    d = pptxparse.read(path)
    alt = r"\bar{x} \mu, \alpha \0 \1 \\ and a bell" + "\x07"
    alts = {rem.image_key(d.slides[0].shapes[1].image[1]): alt,
            rem.image_key(d.slides[0].shapes[2].image[1]): alt}
    titles = {rem.slide_key("tex", d.slides[0]): r"\0 \g<0>"}
    out, counts = remediated(work, "tex.pptx", path, alts, core_title=r"Means \1 \n")
    e = pptxparse.read(out)
    wanted = r"\bar{x} \mu, \alpha \0 \1 \\ and a bell"
    yield "alt text with backslashes is written as it is, replacing a description or not", \
        [s.descr for s in e.slides[0].shapes[1:]] == [wanted, wanted] \
        and counts["described"] == 2, [s.descr for s in e.slides[0].shapes[1:]]
    yield "a title with backslashes too, in the file's properties", \
        e.core_title == r"Means \1 \n", e.core_title
    del titles
    # A picture's row names every copy of its image, a copy whose own alt
    # text was fine among them, and what each has now.
    folder = os.path.join(work, "copies")
    os.makedirs(folder)
    deck(os.path.join(folder, "a.pptx"), [
        {"shapes": [title(2, "One"), pic(4, "rId2", (0, 0, 10, 10), "Bar chart of sales")],
         "images": {"rId2": RED}},
        {"shapes": [title(2, "Two"), pic(4, "rId2", (0, 0, 10, 10))], "images": {"rId2": RED}}])
    deck(os.path.join(folder, "b.pptx"), [
        {"shapes": [title(2, "Three"), pic(4, "rId2", (0, 0, 10, 10), "A logo",
                                           decorative=True)], "images": {"rId2": RED}}])
    reports = {k: os.path.join(folder, v) for k, v in (
        ("image_alt_missing", "image-alt-missing.csv"), ("table_headers_new", "t.csv"),
        ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"))}
    paths = {"image_alt": os.path.join(folder, "image-alt.csv"),
             "table_headers": os.path.join(folder, "table-headers.csv"),
             "slide_titles": os.path.join(folder, "slide-titles.csv")}
    said = []
    code = deckrun.run(folder, deckrun.deck_sources(folder), [], paths, reports,
                       check_only=True, say=said.append)
    rows = rows_of(reports["image_alt_missing"])
    yield "a picture's row names every copy of its image and what each has now", \
        code == 0 and len(rows) == 1 \
        and rows[0][2] == "a.pptx slide 1; a.pptx slide 2; b.pptx slide 1" \
        and rows[0][4] == "Bar chart of sales | (none) | (decorative)", rows
    # A shape's own row wins over its image's.
    a = pptxparse.read(os.path.join(folder, "a.pptx"))
    digest = a.slides[0].shapes[1].image[1]
    alts = {rem.image_key(digest): "Sales chart",
            rem.object_key("a", a.slides[0], a.slides[0].shapes[1]): ""}
    out = remediated(work, "a.pptx", os.path.join(folder, "a.pptx"), alts)[0]
    e = pptxparse.read(out)
    yield "a shape's own row wins over its image's, a blank one keeping what it has", \
        [s.shapes[1].descr for s in e.slides] == ["Bar chart of sales", "Sales chart"], \
        [s.shapes[1].descr for s in e.slides]
    # Two decks whose names are one key stop the run; names otherwise are
    # as the files have them.
    clash = os.path.join(work, "clash")
    os.makedirs(clash)
    for name in ("Deck.pptx", "Deck.PPTX", "Week 1.pptx", "Week-1.pptx", "経済学.pptx"):
        deck(os.path.join(clash, name), [{"shapes": [title(2, "One")]}])
    said = []
    code = deckrun.run(clash, deckrun.deck_sources(clash), [], paths, reports,
                       check_only=True, say=said.append)
    yield "two decks whose names are one key stop the run, and the run says why", \
        code == 1 and any("Deck.PPTX and Deck.pptx are one deck" in line for line in said), said
    yield "a deck's key is its file's name as it is", \
        [rem.deck_name(n) for n in ("Week 1.pptx", "Week-1.pptx", "経済学.pptx")] == \
        ["Week 1", "Week-1", "経済学"], ""
    # A table's value is its headers whole: none clears First Column too,
    # and a table with no properties gets them.
    tdeck = deck(os.path.join(work, "flags.pptx"), [
        {"shapes": [title(2, "T"),
                    table(4, [["a", "b"], ["c", "d"]], (0, 1600200, 900, 900), first_col=True),
                    table(5, [["e", "f"], ["1", "2"]], (0, 3000000, 900, 900), first_col=True),
                    table(6, [["g", "h"], ["3", "4"]], (0, 4000000, 900, 900)).replace(
                        "<a:tblPr/>", "")]}])
    shapes = pptxparse.read(tdeck).slides[0].shapes
    decided = {shapes[1].table.key(): "none", shapes[2].table.key(): "first-row",
               shapes[3].table.key(): "both"}
    out, counts = remediated(work, "flags.pptx", tdeck, tables=decided)
    copy = pptxparse.read(out).slides[0].shapes
    yield "none clears both flags, first-row sets the row and clears the column", \
        (copy[1].table.first_row, copy[1].table.first_col) == (False, False) \
        and (copy[2].table.first_row, copy[2].table.first_col) == (True, False), \
        [(c.table.first_row, c.table.first_col) for c in copy[1:]]
    yield "a table with no properties gets them, first in the table", \
        (copy[3].table.first_row, copy[3].table.first_col) == (True, True) \
        and '<a:tbl><a:tblPr firstRow="1" firstCol="1"/><a:tblGrid>' in read_part(
            out, "ppt/slides/slide1.xml"), counts
    # The decorative mark goes into the shape's own extension list, not
    # its link's, and only the shape's own counts when it's read.
    link = ('<a:hlinkClick r:id="rId3"><a:extLst><a:ext uri="{A12FA001-AC4F-418D-AE19-'
            '62706E023703}"><ahyp:hlinkClr xmlns:ahyp="http://schemas.microsoft.com/office/'
            'drawing/2018/hyperlinkcolor" val="tx"/></a:ext></a:extLst></a:hlinkClick>')
    linked = deck(os.path.join(work, "linked.pptx"), [
        {"shapes": [title(2, "L"), pic(4, "rId2", (0, 0, 10, 10), "x").replace(
            'descr="x"/>', 'descr="x">%s</p:cNvPr>' % link)],
         "images": {"rId2": BLUE}, "links": {"rId3": "https://example.org/"}}])
    blue = pptxparse.read(linked).slides[0].shapes[1].image[1]
    out = remediated(work, "linked.pptx", linked, {rem.image_key(blue): None})[0]
    xml = read_part(out, "ppt/slides/slide1.xml")
    yield "the decorative mark goes into the shape's own extension list, after its link", \
        re.search(r"</a:hlinkClick><a:extLst><a:ext uri=\"\{C183D7F6", xml) is not None \
        and pptxparse.read(out).slides[0].shapes[1].decorative, \
        re.findall(r"<p:cNvPr.*?</p:cNvPr>", xml)
    inside = deck(os.path.join(work, "inside.pptx"), [
        {"shapes": [title(2, "L"), pic(4, "rId2", (0, 0, 10, 10), "x").replace(
            'descr="x"/>', 'descr="x">%s</p:cNvPr>' % link.replace(
                "<ahyp:hlinkClr", '<adec:decorative xmlns:adec="http://schemas.microsoft.com/'
                'office/drawing/2017/decorative" val="1"/><ahyp:hlinkClr').replace(
                "{A12FA001-AC4F-418D-AE19-62706E023703}",
                "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"))],
         "images": {"rId2": BLUE}, "links": {"rId3": "https://example.org/"}}])
    yield "a mark inside a link's extension list isn't the shape's", \
        not pptxparse.read(inside).slides[0].shapes[1].decorative, ""
    # Where the schema puts things, whatever the file already holds.
    odd = deck(os.path.join(work, "odd.pptx"), [
        {"shapes": [title(2, "").replace("<p:spPr/>", '<p:spPr bwMode="auto"/>'),
                    pic(4, "rId2", (0, 0, 10, 10), "x").replace('descr="x"', "descr='x'")],
         "images": {"rId2": RED}}], default_lang=None, style=False)
    xml = read_part(odd, "ppt/presentation.xml").replace(
        '<p:sldId id="256" r:id="rId2"/>',
        '<p:sldId id="256" r:id="rId2"><p:extLst><p:ext uri="{1}"/></p:extLst></p:sldId>')
    with zipfile.ZipFile(odd) as z:
        others = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(odd, "w") as z:
        for info, data in others:
            z.writestr(info, xml if info.filename == "ppt/presentation.xml" else data)
    od = pptxparse.read(odd)
    out, counts = remediated(work, "odd.pptx", odd, {rem.image_key(od.slides[0].shapes[1].image[1]):
                                                     "Red"},
                             titles={rem.slide_key("odd", od.slides[0]): "Odd"}, language="en-US")
    slide = read_part(out, "ppt/slides/slide1.xml")
    pres = read_part(out, "ppt/presentation.xml")
    yield "a title placeholder with a self-closing spPr gets its position inside it", \
        '<p:spPr bwMode="auto"><a:xfrm>' in slide and pptxparse.read(out).slides[0].title == "Odd", \
        re.findall(r"<p:spPr.{0,80}", slide)
    yield "a single-quoted description is replaced, not repeated", \
        slide.count("descr=") == 1 and 'descr="Red"' in slide, re.findall(r"<p:cNvPr[^>]*>", slide)
    yield "a default text style goes after the notes' size, not into a slide's extension list", \
        re.search(r'<p:notesSz [^>]*/><p:defaultTextStyle>', pres) is not None \
        and ET.fromstring(pres.encode()) is not None, pres[-400:]
    # An empty title placeholder in AlternateContent is filled in its
    # Choice and its Fallback alike.
    empty = title(2, "")
    twice = deck(os.path.join(work, "twice.pptx"), [{"shapes": [alternate(empty, empty)]}])
    tw = pptxparse.read(twice)
    out, counts = remediated(work, "twice.pptx", twice,
                             titles={rem.slide_key("twice", tw.slides[0]): "Both"})
    slide = read_part(out, "ppt/slides/slide1.xml")
    yield "an empty title in AlternateContent is filled in its Choice and its Fallback", \
        counts["titles"] == 1 and slide.count("<a:t>Both</a:t>") == 2 \
        and slide.count('<a:off x="0" y="-914400"/>') == 2, (counts, slide.count("Both"))
    # The checks: a title read first wherever it sits; a picture in a
    # described group still needs its own alt text; a language the masters
    # alone declare is a language.
    checked = pptxparse.read(deck(os.path.join(work, "checks.pptx"), [
        {"shapes": [title(2, "Below", box=(457200, 5000000, 8229600, 900000)),
                    pic(4, "rId2", (457200, 300000, 2000000, 2000000), "A red square")],
         "images": {"rId2": RED}},
        {"shapes": [title(2, "Grouped"), group(4, [pic(5, "rId2", (0, 0, 100, 100)),
                                                   rect(6, "Rectangle 5", (200, 0, 100, 100))],
                                               (0, 1600200, 300, 100), descr="Two shapes")],
         "images": {"rId2": RED}}], default_lang=None, styles_lang="fr-FR"))
    found = pptxcheck.check(checked)
    yield "a title read first is in order wherever it sits on the slide", \
        "pptx-reading-order" not in checks_of(found), [(f.check, f.detail) for f in found]
    yield "a picture in a described group still needs its own alt text; its rectangle doesn't", \
        [f.where for f in found if f.check == "pptx-object-no-alt"] == ["slide 2, Picture 5"] \
        and "pptx-shape-no-alt" not in checks_of(found), [(f.check, f.where) for f in found]
    yield "a language the masters alone declare is the deck's", \
        checked.language == "fr-FR" and "pptx-no-language" not in checks_of(found), \
        checked.language
    # A deck that can't be read is named, with why, here and in the audit.
    locked = os.path.join(work, "locked")
    os.makedirs(locked)
    clean_deck(os.path.join(locked, "open.pptx"))
    with open(os.path.join(locked, "locked.pptx"), "wb") as fh:
        fh.write(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504)
    with open(os.path.join(locked, "~$open.pptx"), "wb") as fh:
        fh.write(b"lock")
    said = []
    code = deckrun.run(locked, deckrun.deck_sources(locked), [], paths, reports,
                       check_only=True, say=said.append)
    yield "a deck saved with a password is named, and why, and the lock file isn't", \
        code == 1 and deckrun.deck_sources(locked) == ["locked.pptx", "open.pptx"] \
        and any("locked.pptx couldn't be read" in l and "password" in l for l in said), said
    audited = os.path.join(work, "audited")
    result = subprocess.run(["python3", os.path.join(BIN, "audit.py"),
                             os.path.join(locked, "locked.pptx"), "-o", audited, "--no-cache",
                             "--quick"], capture_output=True, text=True)
    yield "the audit names it unreadable, and goes on", \
        [r[1] for r in rows_of(os.path.join(audited, "audit.csv"))] == ["source-unreadable"], \
        result.stderr[-300:]
    # A copy is readable by others, as any file a person writes.
    old = os.umask(0o022)
    try:
        out = remediated(work, "mode.pptx", clean_deck(os.path.join(work, "mode-src.pptx")))[0]
    finally:
        os.umask(old)
    yield "a copy's permissions are a written file's, not a temporary file's", \
        os.stat(out).st_mode & 0o777 == 0o644, oct(os.stat(out).st_mode & 0o777)


def case_powerpoint(work):
    """What PowerPoint made of three decks Pandoc wrote: one it wouldn't
    open (an empty p:sp), one it repaired by removing content (a14 used
    undeclared in a table cell), and one whose six file names as alt text
    its checker counted as six missing descriptions."""
    formula = ('<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a14:m><m:oMath xmlns:m="http://'
               'schemas.openxmlformats.org/officeDocument/2006/math"><m:r><m:t>q</m:t></m:r>'
               '</m:oMath></a14:m></a:p></a:txBody><a:tcPr/></a:tc>')
    path = deck(os.path.join(work, "pandoc.pptx"), [
        {"shapes": [title(2, "FLOER", "ctrTitle", box=TITLE_BOX), "<p:sp />"]},
        {"shapes": [title(2, "Demand"),
                    table(4, [["Price", "q"], ["1", "2"]], (457200, 1600200, 6000000, 800000),
                          first_row=True, cells={0: [cell("Price"), formula]})]},
        {"shapes": [title(2, "The base"),
                    pic(0, "rId2", (457200, 1600200, 4000000, 3000000),
                        "Monetary Base Graph\n\nassets/fred-monetary-base.png", name="Picture 1")],
         "images": {"rId2": RED}},
    ])
    d = pptxparse.read(path)
    found = pptxcheck.check(d)
    bad = [(f.where, f.detail) for f in found if f.check == "pptx-malformed"]
    yield "an empty p:sp and an undeclared a14 are each named, on their slides", \
        bad == [("slide 1", "an empty <p:sp/>"),
                ("slide 2", "the prefix a14 used without a namespace declaration")], bad
    yield "the empty shape isn't a shape needing alt text, and the table is still read", \
        not [f for f in found if f.check == "pptx-shape-no-alt"] \
        and d.slides[1].shapes[1].table is not None \
        and d.slides[1].shapes[1].table.rows[1] == ["1", "2"], checks_of(found)
    named = [f for f in found if f.check == "pptx-alt-is-file-name"]
    flagged = ("A graph (fred-M2.png) of M2", "chart.SVG.", ".png", "Image .JPG", "graph/.png",
               "An icon for an image file (.png)", "A .png file's icon, a folded corner",
               "https://example.org/a/chart.jpeg?raw=1")
    yield "a file name or extension in alt text, wherever it is, is an error, as PowerPoint " \
        "counts it", len(named) == 1 and named[0].severity == "error" \
        and all((pptxcheck.alt_problem(t) or ("",))[0] == "pptx-alt-is-file-name"
                for t in flagged), \
        [t for t in flagged if (pptxcheck.alt_problem(t) or ("",))[0] != "pptx-alt-is-file-name"]
    passed = ("Version 2.5 of the model", "U.S. GDP, 1990 to 2020", "Growth, e.g. in Japan",
              "Dr.Gifford at the board", "The JPEG committee's home page, www.jpeg.org",
              "Festival poster, www.tiff.net", "Guidance at https://www.ico.org.uk/guide")
    yield "a decimal, an abbreviation, a name after a period, or a domain isn't a file name", \
        all(pptxcheck.alt_problem(t) is None for t in passed), \
        [t for t in passed if pptxcheck.alt_problem(t) is not None]
    # A copy has both put right, as PowerPoint opened a deck with each
    # repair alone, and gets its decisions besides.
    out, counts = remediated(work, "pandoc.pptx", path,
                             alts={rem.image_key(d.slides[2].shapes[1].image[1]):
                                   "The monetary base, 2008 to 2020"})
    copied = pptxcheck.check(pptxparse.read(out), kind="pptx")
    yield "a copy has the empty shape taken out and a14 declared, and its decision written", \
        counts["repaired"] == 2 and counts["described"] == 1 and not copied, \
        (counts, checks_of(copied))
    first, second = read_part(out, "ppt/slides/slide1.xml"), read_part(out, "ppt/slides/slide2.xml")
    root = second[second.index("<p:sld"):second.index(">", second.index("<p:sld")) + 1]
    yield "the repaired parts parse as they are, a14 declared on the root, and nothing else moved", \
        "<p:sp />" not in first and ET.fromstring(first.encode()) is not None \
        and ET.fromstring(second.encode()) is not None \
        and 'xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"' in root \
        and second.replace(' xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"',
                           "", 1) == read_part(path, "ppt/slides/slide2.xml") \
        and first == read_part(path, "ppt/slides/slide1.xml").replace("<p:sp />", "") \
        and read_part(out, "ppt/presentation.xml") == read_part(path, "ppt/presentation.xml"), root
    # A shape with text but no properties isn't empty: taking it out would
    # lose the text, so it stays, and the copy's check names it.
    kept = deck(os.path.join(work, "kept.pptx"), [
        {"shapes": [title(2, "Kept"), "<p:sp><p:spPr/>%s</p:sp>" % body(["Words"])]}])
    out, counts = remediated(work, "kept.pptx", kept)
    yield "a shape with text and no properties is left, and still named", \
        counts["repaired"] == 0 and "<a:t>Words</a:t>" in read_part(out, "ppt/slides/slide1.xml") \
        and [f.detail for f in pptxcheck.check(pptxparse.read(out)) if f.check == "pptx-malformed"] \
        == ["a <p:sp> with no non-visual properties"], counts
    # a14 declared around a text box's formula, as Pandoc declares it, and
    # used undeclared in a table's on the same slide; a decision written
    # into the repaired slide too.
    textbox_math = ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-'
                    'compatibility/2006"><mc:Choice xmlns:a14="http://schemas.microsoft.com/office/'
                    'drawing/2010/main" Requires="a14"><p:sp>%s<p:spPr/><p:txBody><a:bodyPr/>'
                    '<a:lstStyle/><a:p><a:r><a:t>Demand is </a:t></a:r><a14:m><m:oMath xmlns:m="'
                    'http://schemas.openxmlformats.org/officeDocument/2006/math"><m:r><m:t>D</m:t>'
                    '</m:r></m:oMath></a14:m></a:p></p:txBody></p:sp></mc:Choice>'
                    '</mc:AlternateContent>' % nv("sp", 3, "Content Placeholder 3",
                                                  ph='<p:ph idx="1"/>'))
    mixed = deck(os.path.join(work, "mixed.pptx"), [
        {"shapes": [title(2, "Demand"), textbox_math,
                    table(4, [["Price", "q"], ["1", "2"]], (457200, 2600200, 6000000, 800000),
                          first_row=True, cells={0: [cell("Price"), formula]}),
                    pic(5, "rId2", (457200, 4000000, 900000, 900000), "chart.png")],
         "images": {"rId2": GREEN}}])
    m = pptxparse.read(mixed)
    out, counts = remediated(work, "mixed.pptx", mixed,
                             alts={rem.image_key(m.slides[0].shapes[-1].image[1]): "A demand curve"})
    slide = read_part(out, "ppt/slides/slide1.xml")
    yield "a14 declared on one element and used undeclared on another is named, declared, and " \
        "a decision written beside it", \
        m.malformed == [("ppt/slides/slide1.xml",
                         "the prefix a14 used without a namespace declaration")] \
        and counts["repaired"] == 1 and counts["described"] == 1 \
        and ET.fromstring(slide.encode()) is not None and 'descr="A demand curve"' in slide \
        and not pptxcheck.check(pptxparse.read(out)), (m.malformed, counts)
    # An empty shape with an attribute, and a group emptied by taking out
    # its one shape, are taken out too.
    groups = deck(os.path.join(work, "groups.pptx"), [
        {"shapes": [title(2, "Groups"), '<p:sp useBgFill="1"/>',
                    "<p:grpSp><p:sp/></p:grpSp>"]}])
    out, counts = remediated(work, "groups.pptx", groups)
    yield "an empty shape with an attribute, and a group emptied by the repair, are taken out", \
        counts["repaired"] == 3 \
        and not re.search(r"<p:grpSp[\s/>]", read_part(out, "ppt/slides/slide1.xml")) \
        and not pptxcheck.check(pptxparse.read(out)), counts
    # A group with no properties is read, so the ids inside it still count:
    # a decision for a shape whose id repeats there is skipped.
    hidden = deck(os.path.join(work, "hidden.pptx"), [
        {"shapes": [title(2, "Hidden"), pic(5, "rId2", (0, 1600200, 900000, 900000)),
                    "<p:grpSp><p:grpSpPr/>%s</p:grpSp>"
                    % pic(5, "rId3", (0, 3000000, 900000, 900000), "A green square")],
         "images": {"rId2": RED, "rId3": GREEN}}])
    h = pptxparse.read(hidden)
    out, counts = remediated(work, "hidden.pptx", hidden,
                             alts={rem.image_key(h.slides[0].shapes[1].image[1]): "A red square"})
    yield "a group with no properties is read, an id repeated inside it is still guarded, and " \
        "it isn't asked for alt text it can't hold", \
        counts["skipped"] == 1 and counts["described"] == 0 \
        and 'descr="A green square"' in read_part(out, "ppt/slides/slide1.xml") \
        and checks_of(pptxcheck.check(h)) == ["pptx-malformed", "pptx-object-no-alt"], \
        (counts, checks_of(pptxcheck.check(h)))
    # A part in UTF-16, which OPC allows, is repaired, and a decision written
    # into it, and it stays UTF-16, its byte-order mark and all.
    wide = utf16(deck(os.path.join(work, "wide.pptx"), [
        {"shapes": [title(2, "Wide"), "<p:sp/>", pic(4, "rId2", (0, 1600200, 900000, 900000)),
                    table(5, [["Price", "q"], ["1", "2"]], (457200, 3600200, 6000000, 800000),
                          first_row=True, cells={0: [cell("Price"), formula]})],
         "images": {"rId2": BLUE}}]), "ppt/slides/slide1.xml")
    wd = pptxparse.read(wide)
    out, counts = remediated(work, "wide.pptx", wide,
                             alts={rem.image_key(wd.slides[0].shapes[1].image[1]): "A blue square"})
    written = read_part_bytes(out, "ppt/slides/slide1.xml")
    yield "a slide in UTF-16 is read, repaired, and given its decision, and stays UTF-16", \
        [p for _part, p in wd.malformed] == ["the prefix a14 used without a namespace declaration",
                                              "an empty <p:sp/>"] \
        and counts["repaired"] == 2 and counts["described"] == 1 \
        and written.startswith(b"\xff\xfe") and "<p:sp/>" not in written.decode("utf-16") \
        and pptxparse.read(out).slides[0].shapes[1].descr == "A blue square" \
        and not pptxcheck.check(pptxparse.read(out)), counts


def order_deck(path):
    """A deck whose slides are read out of their layout's order, each in
    its own way."""
    return deck(path, [
        # 1: the title read second; nothing overlaps; the shapes on lines
        # of their own, as a pretty-printed slide has them
        {"shapes": ["\n  ", textbox(4, "TextBox 3", ["Second"], (457200, 1600200, 4000000, 600000)),
                    "\n  ", title(2, "Order"), "\n  ",
                    textbox(5, "TextBox 4", ["Third"], (457200, 4000000, 4000000, 600000)), "\n"]},
        # 2: a label over a picture starts higher than the picture, which
        # is drawn under it, though the two overlap, so neither is laid out
        # before the other; a note at the top right is read last
        {"shapes": [title(2, "A map"),
                    pic(4, "rId2", (457200, 3000000, 6000000, 3000000), "A map of the county"),
                    textbox(5, "TextBox 4", ["The river"], (1000000, 2800000, 3000000, 600000)),
                    textbox(6, "TextBox 5", ["A note"], (7000000, 1600200, 3000000, 600000))],
         "images": {"rId2": RED}},
        # 3: the title over a picture filling the slide, which is drawn first
        {"shapes": [pic(4, "rId2", (0, 0, 12192000, 6858000), "A classroom"), title(2, "Class")],
         "images": {"rId2": GREEN}},
        # 4: a group and a picture in AlternateContent, laid out bottom up
        {"shapes": [textbox(4, "TextBox 3", ["Last"], (457200, 5000000, 4000000, 600000)),
                    group(6, [rect(10, "Rectangle 9", (0, 0, 100000, 100000)),
                              rect(11, "Rectangle 10", (200000, 0, 100000, 100000))],
                          (457200, 3000000, 2000000, 1000000), descr="Two boxes"),
                    alternate(pic(8, "rId2", (457200, 1600200, 900000, 900000), "Choice"),
                              pic(8, "rId2", (457200, 1600200, 900000, 900000), "Fallback")),
                    title(2, "Whole")],
         "images": {"rId2": BLUE}},
        # 5: a decorative picture between two shapes read out of order, and
        # a wide shape turned on end, over the square below it only once
        # it's turned
        {"shapes": [textbox(4, "TextBox 3", ["Bottom"], (457200, 4500000, 3000000, 600000)),
                    pic(5, "rId2", (9000000, 4500000, 900000, 900000), decorative=True),
                    textbox(6, "TextBox 5", ["Top"], (457200, 1600200, 3000000, 600000)),
                    textbox(7, "TextBox 6", ["Turned"], (5000000, 3600000, 4000000, 200000)).replace(
                        "<a:xfrm>", '<a:xfrm rot="5400000">', 1),
                    rect(9, "Rectangle 8", (6800000, 4800000, 400000, 400000), descr="A square"),
                    title(2, "Turned")],
         "images": {"rId2": png(10, 10, 10)}},
        # 6: a decorative picture drawn over the shape before it, which can't
        # move past it, so it's read before the title
        {"shapes": [textbox(4, "TextBox 3", ["Low"], (457200, 4500000, 3000000, 600000)),
                    pic(5, "rId2", (457200, 4400000, 3000000, 900000), decorative=True),
                    textbox(6, "TextBox 5", ["High"], (457200, 1600200, 3000000, 600000)),
                    title(2, "Under")],
         "images": {"rId2": png(11, 11, 11)}},
    ])


def tree_texts(xml):
    """The XML of each shape at the top of a slide's tree, in order."""
    kids = pptxorder.tree(xml)
    return [xml[k.start:k.end] for k in kids if k.movable]


def case_order(work):
    path = order_deck(os.path.join(work, "order.pptx"))
    d = pptxparse.read(path)
    key = [rem.slide_key("order", s) for s in d.slides]
    folder = os.path.join(work, "run")
    os.makedirs(folder)
    shutil.copy(path, folder)
    reports = {k: os.path.join(folder, v) for k, v in (
        ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
        ("slide_titles_new", "s.csv"), ("reading_order_new", "reading-order-new.csv"),
        ("slides_check", "check.csv"))}
    paths = {"image_alt": os.path.join(folder, "image-alt.csv"),
             "table_headers": os.path.join(folder, "table-headers.csv"),
             "slide_titles": os.path.join(folder, "slide-titles.csv"),
             "reading_order": os.path.join(folder, "reading-order.csv")}
    said = []
    deckrun.run(folder, ["order.pptx"], [], paths, reports, check_only=True, say=said.append)
    rows = {r[0]: r for r in rows_of(reports["reading_order_new"])}
    yield "each slide read out of its layout's order gets a row, keyed on its deck and slide", \
        sorted(rows) == sorted(key), sorted(rows)
    first = rows.get(key[0], [""] * 7)
    yield "a row's order is drafted from the layout, the title first, drafted by TI", \
        first[1] == "2 4 5" and first[5] == "TI" and first[4] == "" \
        and first[2] == "order.pptx slide 1" \
        and first[3] == '4 TextBox 3 "Second"; 2 Title 2 "Order"; 5 TextBox 4 "Third"', first
    second = rows.get(key[1], [""] * 7)
    yield "a label over the picture under it, neither laid out before the other, stays after it", \
        second[1] == "2 6 4 5" and second[4] == "", second
    third = rows.get(key[2], [""] * 7)
    yield "a title over a picture that fills the slide can't be read first; the row says so", \
        third[1] == "" and third[5] == "" and "No order nearer the layout keeps what's drawn " \
        "over what" in third[4] and "4 before 2" in third[4] and "usually decorative" in third[4], \
        third
    yield "a group and a picture in AlternateContent are drafted by their own ids", \
        rows.get(key[3], [""] * 7)[1] == "2 8 6 4", rows.get(key[3])
    yield "a decorative picture isn't in the order, and a turned shape overlaps by its turn", \
        rows.get(key[4], [""] * 7)[1] == "2 6 7 4 9", rows.get(key[4])
    yield "a shape a decorative picture is drawn over stays before it, ahead of the title", \
        rows.get(key[5], [""] * 7)[1] == "4 2 6" and "4 before 5" in rows.get(key[5])[4], \
        rows.get(key[5])
    # Adopted as drafted, and one order of a person's own that isn't the
    # layout's; slide 5 in two orders, one swapping shapes that overlap
    # only once one of them is turned.
    orders = {key[0]: ["2", "4", "5"], key[1]: ["2", "6", "4", "5"], key[3]: ["2", "8", "6", "4"],
              key[4]: ["6", "4"]}
    problems = []
    out = os.path.join(work, "out", "ordered.pptx")
    counts = rem.remediate(path, out, orders=orders, problems=problems, deck="order")
    e = pptxparse.read(out)
    yield "each order is written: the shapes it names in its order, in the places they had", \
        counts["orders"] == 4 and not problems \
        and [[s.id for s in slide.shapes] for slide in e.slides] == [
            ["2", "4", "5"], ["2", "6", "4", "5"], ["4", "2"], ["2", "8", "6", "4"],
            ["6", "5", "4", "7", "9", "2"], ["4", "5", "6", "2"]], \
        [[s.id for s in slide.shapes] for slide in e.slides]
    four = read_part(out, "ppt/slides/slide4.xml")
    yield "a group moves with its pieces, and AlternateContent with its Choice and Fallback", \
        [s.id for s in e.slides[3].shapes[2].children] == ["10", "11"] \
        and four.index('descr="Choice"') < four.index('descr="Fallback"') < four.index("Group 6"), \
        four[:300]
    same = all(sorted(tree_texts(read_part(out, "ppt/slides/slide%d.xml" % n))) ==
               sorted(tree_texts(read_part(path, "ppt/slides/slide%d.xml" % n)))
               and len(read_part(out, "ppt/slides/slide%d.xml" % n)) ==
               len(read_part(path, "ppt/slides/slide%d.xml" % n)) for n in range(1, 7))
    with zipfile.ZipFile(path) as a, zipfile.ZipFile(out) as b:
        changed = sorted(n for n in a.namelist() if a.read(n) != b.read(n))
    yield "only the slides put in order change, and only in the order of their shapes", \
        same and changed == ["ppt/slides/slide1.xml", "ppt/slides/slide2.xml",
                             "ppt/slides/slide4.xml", "ppt/slides/slide5.xml"], changed
    copy_found = pptxcheck.check(e, orders=rem.slide_orders(orders, "order"))
    yield "a slide in the order the sidecar gives isn't counted against the copy, " \
        "the person's order or the layout's", \
        [f.where for f in copy_found if f.check == "pptx-reading-order"] == ["slide 3", "slide 6"], \
        [(f.where, f.detail) for f in copy_found if f.check == "pptx-reading-order"]
    # Orders that can't be written are left out, each with why.
    refused = {key[4]: ["9", "7"], key[1]: ["5", "4"], key[0]: ["4", "99"],
               key[3]: ["10", "2"], key[2]: ["2", "2"]}
    problems = []
    counts = rem.remediate(path, os.path.join(work, "out", "refused.pptx"), orders=refused,
                           problems=problems, deck="order")
    why = dict(problems)
    yield "an order drawing overlapping shapes the other way round is refused, and why", \
        "7 and 9 overlap" in why.get(key[4], "") and "4 and 5 overlap" in why.get(key[1], ""), why
    yield "an order naming an id the slide doesn't have, a piece of a group, or one twice too", \
        "names 99" in why.get(key[0], "") and "names 10" in why.get(key[3], "") \
        and "in a group" in why.get(key[3], "") and "names 2 twice" in why.get(key[2], "") \
        and counts["orders_refused"] == 5 and counts["orders"] == 0, (counts, why)
    yield "and a refused order changes nothing", all(
        read_part(os.path.join(work, "out", "refused.pptx"), "ppt/slides/slide%d.xml" % n)
        == read_part(path, "ppt/slides/slide%d.xml" % n) for n in range(1, 6)), ""
    # A shape turned the other way, or not turned, doesn't reach the square.
    unturned = deck(os.path.join(work, "unturned.pptx"), [
        {"shapes": [textbox(7, "TextBox 6", ["Flat"], (5000000, 3600000, 4000000, 200000)),
                    rect(9, "Rectangle 8", (6800000, 4800000, 400000, 400000), descr="A square"),
                    title(2, "Flat")]}])
    problems = []
    counts = rem.remediate(unturned, os.path.join(work, "out", "unturned.pptx"),
                           orders={rem.slide_key("unturned", pptxparse.read(unturned).slides[0]):
                                   ["9", "7"]}, problems=problems, deck="unturned")
    yield "the same two shapes, the wide one not turned, don't overlap and can swap", \
        counts["orders"] == 1 and not problems, problems
    # Boxes that only touch count as overlapping, as does a thick line whose
    # outline reaches a shape its box doesn't; the same line with no
    # outline doesn't.
    thick = line(4, (457200, 3000000, 3000000, 0)).replace(
        "</p:spPr>", '<a:ln w="254000"/></p:spPr>')
    edges = deck(os.path.join(work, "edges.pptx"), [
        {"shapes": [title(2, "Touch"),
                    textbox(4, "TextBox 3", ["Upper"], (457200, 3000000, 3000000, 600000)),
                    textbox(5, "TextBox 4", ["Lower"], (457200, 3600000, 3000000, 600000))]},
        {"shapes": [title(2, "Thick"), thick,
                    textbox(5, "TextBox 4", ["Under"], (457200, 3150000, 3000000, 600000))]},
        {"shapes": [title(2, "Thin"), thick.replace('<a:ln w="254000"/>',
                                                    '<a:ln w="254000"><a:noFill/></a:ln>'),
                    textbox(5, "TextBox 4", ["Under"], (457200, 3150000, 3000000, 600000))]},
        {"shapes": [title(2, "Hidden"),
                    textbox(4, "TextBox 3", ["A"], (457200, 3000000, 3000000, 600000)),
                    textbox(5, "TextBox 4", ["Gone"], (457200, 3100000, 3000000, 600000)).replace(
                        'name="TextBox 4"', 'name="TextBox 4" hidden="1"'),
                    textbox(6, "TextBox 5", ["B"], (457200, 4500000, 3000000, 600000))]},
        {"shapes": [title(2, "Empty"),
                    textbox(4, "TextBox 3", ["A"], (457200, 4500000, 3000000, 600000)),
                    content(3, []),
                    textbox(6, "TextBox 5", ["B"], (457200, 2000000, 3000000, 600000))]},
        {"shapes": [title(2, "Arrow"),
                    line(4, (457200, 3000000, 3000000, 0)).replace(
                        "</p:spPr>", '<a:ln w="50800"><a:tailEnd type="triangle"/></a:ln></p:spPr>'),
                    textbox(5, "TextBox 4", ["Near"], (457200, 3120000, 3000000, 600000))]},
        {"shapes": [title(2, "Grouped"),
                    group(6, [line(7, (0, 0, 6000000, 0)).replace(
                        "</p:spPr>", '<a:ln w="254000"/></p:spPr>')], (457200, 3000000, 3000000, 1)),
                    textbox(5, "TextBox 4", ["Under"], (457200, 3150000, 3000000, 600000))]},
        {"shapes": [title(2, "Unplaced"),
                    textbox(4, "TextBox 3", ["A"], (457200, 4500000, 3000000, 600000)),
                    "<p:sp>%s<p:spPr/>%s</p:sp>" % (nv("sp", 7, "TextBox 6"), body(["Nowhere"])),
                    textbox(6, "TextBox 5", ["B"], (457200, 2000000, 3000000, 600000))]},
        {"shapes": [title(2, "Twice"),
                    textbox(5, "TextBox 4", ["A"], (457200, 4500000, 3000000, 600000)),
                    group(8, [textbox(5, "TextBox 4", ["Inner"], (0, 0, 100000, 100000))],
                          (7000000, 5500000, 200000, 200000), descr="A group"),
                    textbox(6, "TextBox 5", ["B"], (457200, 2000000, 3000000, 600000))]}])
    ed = pptxparse.read(edges)
    problems = []
    swaps = {rem.slide_key("edges", ed.slides[n]): ids for n, ids in (
        (0, ["5", "4"]), (1, ["5", "4"]), (2, ["5", "4"]), (3, ["6", "4"]), (4, ["6", "4"]),
        (5, ["5", "4"]), (6, ["5", "6"]), (7, ["6", "4"]), (8, ["6", "5"]))}
    counts = rem.remediate(edges, os.path.join(work, "out", "edges.pptx"), orders=swaps,
                           problems=problems, deck="edges")
    refused = [k for k, _why in problems]
    yield "boxes that touch overlap, and so does a thick line's outline; one with none doesn't", \
        rem.slide_key("edges", ed.slides[0]) in refused \
        and rem.slide_key("edges", ed.slides[1]) in refused \
        and rem.slide_key("edges", ed.slides[2]) not in refused \
        and ed.slides[1].shapes[1].stroke == 254000 and ed.slides[2].shapes[1].stroke == 0, \
        (counts, problems)
    yield "a hidden shape and an empty placeholder draw nothing, and overlap nothing", \
        rem.slide_key("edges", ed.slides[3]) not in refused \
        and rem.slide_key("edges", ed.slides[4]) not in refused and counts["orders"] == 3, \
        (counts, problems)
    yield "a shape with no box overlaps everything, and an id a group's piece repeats can't " \
        "be named", rem.slide_key("edges", ed.slides[7]) in refused \
        and "more than one shape" in dict(problems).get(rem.slide_key("edges", ed.slides[8]), ""), \
        problems
    yield "a line's arrowhead reaches past its outline, and a group's line past the group", \
        rem.slide_key("edges", ed.slides[5]) in refused \
        and rem.slide_key("edges", ed.slides[6]) in refused \
        and ed.slides[5].shapes[1].stroke == 152400 and ed.slides[6].shapes[1].stroke == 254000, \
        (refused, [s.stroke for s in ed.slides[6].shapes])
    # Geometry that reaches past its box: a callout's tail, a line
    # callout's line, a connector's bend, a freeform's points, and a
    # callout in a group, each over a shape its box doesn't reach.
    def shaped(xml, prst, adjustments=()):
        guides = "".join('<a:gd name="adj%d" fmla="val %d"/>' % (n, v)
                         for n, v in enumerate(adjustments, 1))
        return re.sub(r'<a:prstGeom prst="\w+"><a:avLst/></a:prstGeom>',
                      lambda _m: '<a:prstGeom prst="%s"><a:avLst>%s</a:avLst></a:prstGeom>'
                      % (prst, guides), xml, count=1)

    def freeform(xml, points):
        path = "".join('<a:%s><a:pt x="%s" y="%s"/></a:%s>' % (verb, x, y, verb)
                       for verb, x, y in points)
        return re.sub(r'<a:prstGeom prst="\w+"><a:avLst/></a:prstGeom>',
                      lambda _m: '<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>'
                      '<a:rect l="0" t="0" r="r" b="b"/><a:pathLst><a:path w="100" h="100">'
                      + path + '<a:close/></a:path></a:pathLst></a:custGeom>', xml, count=1)
    near = textbox(5, "TextBox 4", ["Near"], (4000000, 1700000, 2000000, 400000))
    box = (457200, 1600200, 2000000, 600000)
    reach = deck(os.path.join(work, "reach.pptx"), [
        {"shapes": [title(2, "Tip"), shaped(textbox(4, "Callout 3", ["Says"], box),
                                            "wedgeRectCallout", (150000, 0)), near]},
        {"shapes": [title(2, "Line"), shaped(textbox(4, "Callout 3", ["Says"], box),
                                             "borderCallout1", (50000, 0, 50000, 250000)), near]},
        {"shapes": [title(2, "Bend"), shaped(line(4, (457200, 1600200, 1000000, 600000)),
                                             "bentConnector3", (400000,)), near]},
        {"shapes": [title(2, "Free"), freeform(textbox(4, "Freeform 3", ["Free"], box),
                                               [("moveTo", 0, 0), ("lnTo", 200, 50)]), near]},
        {"shapes": [title(2, "Guide"), freeform(textbox(4, "Freeform 3", ["Free"], box),
                                                [("moveTo", 0, 0), ("lnTo", "w", 50)]),
                    textbox(5, "TextBox 4", ["Far"], (8000000, 5000000, 1000000, 400000))]},
        {"shapes": [title(2, "Held"),
                    group(6, [shaped(textbox(7, "Callout 6", ["Says"], (0, 0, 4000000, 1200000)),
                                     "wedgeRectCallout", (150000, 0))], box),
                    near]},
        {"shapes": [title(2, "Default"),
                    shaped(textbox(4, "Callout 3", ["Says"], (457200, 1600200, 2000000, 800000)),
                           "wedgeRectCallout"),
                    textbox(5, "TextBox 4", ["Below"], (457200, 2520200, 2000000, 400000))]},
        {"shapes": [title(2, "Plain"), textbox(4, "TextBox 3", ["Says"], box), near]},
        {"shapes": [title(2, "Cloud"), shaped(textbox(4, "Callout 3", ["Says"], box),
                                              "cloudCallout", (150000, 0)),
                    textbox(5, "TextBox 4", ["Beyond"], (4600000, 1700000, 1000000, 400000))]},
        {"shapes": [title(2, "Hid"),
                    group(6, [textbox(8, "TextBox 7", ["Shown"], (0, 0, 4000000, 1200000)),
                              shaped(textbox(7, "Callout 6", ["Gone"], (0, 0, 4000000, 1200000)),
                                     "wedgeRectCallout", (150000, 0)).replace(
                                  'name="Callout 6"', 'name="Callout 6" hidden="1"')], box),
                    near]}])
    rd = pptxparse.read(reach)
    problems = []
    counts = rem.remediate(reach, os.path.join(work, "out", "reach.pptx"), problems=problems,
                           orders={rem.slide_key("reach", slide): [
                               "5", "6" if slide.number in (6, 10) else "4"]
                               for slide in rd.slides},
                           deck="reach")
    refused = sorted(int(k.rsplit("-", 1)[1]) - 255 for k, _why in problems)
    yield "a callout's tail, a line callout's line, a connector's bend, a freeform's points, " \
        "a cloud's trail, and a callout in a group reach past their boxes, a guide's point " \
        "anywhere, and a hidden piece of a group nowhere", \
        refused == [1, 2, 3, 4, 5, 6, 7, 9] and counts["orders"] == 2 \
        and rd.slides[0].shapes[1].extent == (0.0, 0.0, 2.0, 1.0) \
        and rd.slides[3].shapes[1].extent == (0.0, 0.0, 2.0, 1.0) \
        and rd.slides[4].shapes[1].extent is None, \
        (refused, [s.shapes[1].extent for s in rd.slides])
    # Two shapes with one id can't be named; the row says so.
    twin = deck(os.path.join(work, "twin.pptx"), [
        {"shapes": [pic(0, "rId2", (457200, 4000000, 900000, 900000), "Low"),
                    pic(0, "rId3", (457200, 1600200, 900000, 900000), "High"), title(2, "Twins")],
         "images": {"rId2": RED, "rId3": GREEN}}])
    t = pptxparse.read(twin)
    kids = pptxorder.tree(read_part(twin, "ppt/slides/slide1.xml"), t.slides[0])
    ids, note = pptxorder.draft(kids, pptxcheck.read_shapes(t.slides[0], t.width, t.height))
    problems = []
    rem.remediate(twin, os.path.join(work, "out", "twin.pptx"),
                  orders={rem.slide_key("twin", t.slides[0]): ["2", "0"]}, problems=problems,
                  deck="twin")
    yield "shapes sharing an id get no draft, and an order naming them isn't written", \
        ids is None and "share the id" in note and problems \
        and "more than one shape" in problems[0][1], (ids, note, problems)
    # The sidecar: ids by spaces, commas, or semicolons; anything else isn't
    # an order, and is said not to be.
    sidecar = os.path.join(work, "reading-order.csv")
    with open(sidecar, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.ORDER_COLUMNS, ["d/slide-256", "2, 4;5  6"],
                                  ["d/slide-257", ""], ["d/slide-258", "Title 1, TextBox 3"]])
    bad = []
    read = rem.order_rows(sidecar, bad)
    yield "reading-order rows: ids however separated, a blank kept, names refused and said", \
        read == {"d/slide-256": ["2", "4", "5", "6"], "d/slide-257": [], "d/slide-258": []} \
        and bad == [("d/slide-258", "Title")], (read, bad)
    # A run with the rows adopted: written, reported no more, a stale one named.
    rows[key[2]][1] = "2 4"                     # the title over the picture: refused
    with open(paths["reading_order"], "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.ORDER_COLUMNS] + [r for r in rows.values()]
                                 + [["order/slide-999", "2 4"]])
    target = type("Target", (), {"format": "source", "name": "fixed",
                                 "output_dir": os.path.join(folder, "fixed")})()
    reports["output_check"] = os.path.join(folder, "output-check.csv")
    said = []
    code = deckrun.run(folder, ["order.pptx"], [target], paths, reports, say=said.append)
    left = [r for r in rows_of(reports["output_check"]) if r[1] == "pptx-reading-order"]
    yield "adopted rows are written, the report goes, and only the slide that can't move is left", \
        code == 0 and not os.path.exists(reports["reading_order_new"]) \
        and "fixed: 5 slide(s) put in the reading order reading-order.csv gives." in said \
        and [r[0] for r in left] == ["slide 3"] and any(
            "the reading order for %s isn't written: 4 and 2 overlap" % key[2] in line
            for line in said), (said[-6:], left)
    yield "a row naming a slide no deck has is named", \
        any("1 row(s) of reading-order.csv match no slide" in line for line in said), said


def drafted(path, alts=None):
    """{slide number: (Order, Note)} of reading-order-new.csv's rows for a
    deck, as a run drafts them."""
    d = pptxparse.read(path)
    return {int(r[2].rsplit(" ", 1)[1]): (r[1], r[4])
            for r in deckrun.order_rows(path, os.path.basename(path), rem.deck_name(path), d, {},
                                        alts)}


def case_draft(work):
    inch = 914400
    top = (457200, 100000, 8000000, 700000)
    rows = [textbox(10 + n, "TextBox %d" % (10 + n), ["Point %d" % (6 - n)],
                    (457200, 5000000 - n * 800000, 4000000, 500000)) for n in range(6)]
    path = deck(os.path.join(work, "drafts.pptx"), [
        # 1: two columns side by side, their tops either side of a quarter
        # inch, the left one lower; the title read last
        {"shapes": [textbox(5, "Left column", ["Benefits"],
                            (457200, int(1.26 * inch), 5000000, 3000000)),
                    textbox(4, "Right column", ["Costs"], (6400000, int(1.20 * inch), 5000000, 3000000)),
                    title(2, "Columns", box=top)]},
        # 2: a line wholly above a text box, beside it and not over it,
        # read after it
        {"shapes": [title(2, "A line", box=top),
                    textbox(4, "TextBox 3", ["Words"], (457200, 3100000, 4000000, 500000)),
                    line(5, (5000000, 3000000, 2000000, 0))]},
        # 3: a footnote a decorative picture is drawn over, which keeps it
        # ahead of the picture and so of everything, then six points laid
        # out bottom up, and the title last
        {"shapes": [textbox(3, "Footnote", ["X"], (457200, 6000000, 3000000, 400000)),
                    pic(4, "rId2", (457200, 5900000, 3000000, 600000), decorative=True)]
         + rows + [title(2, "Points", box=top)],
         "images": {"rId2": png(12, 12, 12)}},
        # 4: three shapes laid out in a circle: the first above the second,
        # the second left of the third, the third left of the first
        {"shapes": [title(2, "Round", box=top),
                    textbox(4, "TextBox 3", ["A"], (8000000, 1000000, 2000000, 1000000)),
                    textbox(5, "TextBox 4", ["B"], (457200, 4000000, 2000000, 1000000)),
                    textbox(6, "TextBox 5", ["C"], (4000000, 1000000, 2000000, 4500000))]},
        # 5: more shapes to read than a draft takes, bottom up
        {"shapes": [rect(10 + n, "Rectangle %d" % n, (100000 + (n % 20) * 500000,
                                                      6000000 - (n // 20) * 500000, 300000, 300000))
                    for n in range(pptxorder.DRAFT_LIMIT + 1)] + [title(2, "Many", box=top)]},
        # 6: two lines at the left, and a tall box over both at the right of
        # them, which neither is laid out before; below them, a line wholly
        # left of the box, laid out before it once the two above are read
        {"shapes": [textbox(4, "TextBox 3", ["First"], (457200, 1000000, 3000000, 300000)),
                    textbox(5, "TextBox 4", ["Second"], (457200, 1500000, 3000000, 300000)),
                    textbox(6, "TextBox 5", ["Beside"], (3000000, 1000000, 3000000, 2000000)),
                    textbox(7, "TextBox 6", ["Third"], (457200, 2100000, 2393000, 300000)),
                    title(2, "Counted", box=top)]},
        # 7: a decorative picture between a line at the foot and one at the
        # head, drawn under the head's, which so can't be read first
        {"shapes": [textbox(4, "TextBox 3", ["Foot"], (457200, 5000000, 3000000, 500000)),
                    pic(5, "rId2", (457200, 1500000, 3000000, 900000), decorative=True),
                    textbox(6, "TextBox 5", ["Head"], (457200, 1400000, 3000000, 500000))],
         "images": {"rId2": png(13, 13, 13)}},
    ])
    found = drafted(path)
    yield "two columns whose tops straddle a quarter inch are read left first", \
        found.get(1, ("",))[0] == "2 5 4", found.get(1)
    yield "a line wholly above a text box beside it is read first, as the check has it", \
        found.get(2, ("",))[0] == "2 5 4", found.get(2)
    yield "a slide whose order is pinned at one end is still drafted: the rest as laid out", \
        found.get(3, ("",))[0] == "3 2 15 14 13 12 11 10" and "3 before 4" in found[3][1], \
        found.get(3)
    yield "shapes laid out in a circle get no draft, and the note says why", \
        found.get(4, ("x",))[0] == "" and "No order reads every shape after those above it and " \
        "to its left" in found[4][1], found.get(4)
    yield "the layout's order counts only the shapes not yet read before each", \
        found.get(6, ("",))[0] == "2 4 5 7 6", found.get(6)
    yield "a shape a picture that isn't read is drawn under stays after it", \
        found.get(7, ("x",))[0] == "" and "5 before 6" in found[7][1], found.get(7)
    yield "a slide with more shapes than a draft takes gets a note in place of one", \
        found.get(5, ("x",))[0] == "" and "With %d shapes to read, no order is drafted" % (
            pptxorder.DRAFT_LIMIT + 2) in found[5][1], found.get(5)
    d = pptxparse.read(path)
    yield "the check finds each slide, and lays out the columns as the draft does", \
        [s.number for s in d.slides if pptxcheck.reading_order(s, d.width, d.height)] \
        == [1, 2, 3, 4, 5, 6, 7] and [s.id for s in pptxcheck.reading_order(
            d.slides[0], d.width, d.height)[1]] == ["2", "5", "4"] \
        and [s.id for s in pptxcheck.reading_order(d.slides[5], d.width, d.height)[1]] \
        == ["2", "4", "5", "7", "6"], ""
    # Every draft, written, reads in order, and nothing overlapping swapped.
    orders = {rem.slide_key("drafts", d.slides[n - 1]): order.split()
              for n, (order, _note) in found.items() if order}
    problems = []
    out = os.path.join(work, "out", "drafts.pptx")
    counts = rem.remediate(path, out, orders=orders, problems=problems, deck="drafts")
    e = pptxparse.read(out)
    yield "each draft is written as it stands, and the copy's check finds those slides in order", \
        counts["orders"] == 4 and not problems \
        and [s.number for s in e.slides if pptxcheck.reading_order(s, e.width, e.height)] \
        == [3, 4, 5, 7], (counts, problems)
    # Whether the shapes left can still go somewhere: an overlap's order
    # carried forward, and backward, through the slots each can take.
    later = pptxorder._fits({1, 2, 3}, 1, 4, {1: 2, 2: 0, 3: 2}, {1: 3, 2: 3, 3: 3},
                            {1: [], 2: [1], 3: []}, {1: [2], 2: [], 3: []})
    sooner = pptxorder._fits({1, 2, 3}, 0, 3, {1: 0, 2: 0, 3: 0}, {1: 2, 2: 1, 3: 1},
                             {1: [], 2: [1], 3: []}, {1: [2], 2: [], 3: []})
    room = pptxorder._fits({1, 2, 3}, 0, 3, {1: 0, 2: 0, 3: 0}, {1: 2, 2: 1, 3: 2},
                           {1: [], 2: [1], 3: []}, {1: [2], 2: [], 3: []})
    yield "the search knows when the shapes left can't all go after those they're drawn over", \
        later is False and sooner is False and room is True, (later, sooner, room)
    # The picture under the title, marked decorative in the image-alt
    # sidecar, isn't read, and the slide leaves the report.
    under = order_deck(os.path.join(work, "order.pptx"))
    picture = pptxparse.read(under).slides[2].shapes[0]
    plain, decided = drafted(under), drafted(under, {rem.image_key(picture.image[1]): None})
    yield "a picture the image-alt sidecar marks decorative isn't read, so its slide is in order", \
        3 in plain and sorted(decided) == [n for n in sorted(plain) if n != 3], \
        (sorted(plain), sorted(decided))
    shared = deck(os.path.join(work, "shared.pptx"), [
        {"shapes": [pic(4, "rId2", (0, 0, 12192000, 6858000), "A classroom"),
                    rect(4, "Rectangle 3", (100000, 6000000, 100000, 100000), decorative=True),
                    title(2, "Class")], "images": {"rId2": GREEN}}])
    image = pptxparse.read(shared).slides[0].shapes[0].image[1]
    yield "but not one whose id another shape has, which a copy leaves as it is", \
        1 in drafted(shared, {rem.image_key(image): None}), ""


def styled_title(shape_id, paragraphs):
    """A title placeholder whose paragraphs are given as XML."""
    return ("<p:sp>%s<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>"
            % (nv("sp", shape_id, "Title %s" % shape_id, ph='<p:ph type="title"/>'),
               "".join(paragraphs)))


MEAN = ('<a:p><a:r><a:rPr lang="en-US"/><a:t>The mean of </a:t></a:r><a14:m xmlns:a14="'
        'http://schemas.microsoft.com/office/drawing/2010/main"><m:oMath xmlns:m="http://schemas.'
        'openxmlformats.org/officeDocument/2006/math"><m:r><m:t>x</m:t></m:r></m:oMath></a14:m>'
        '<a:endParaRPr lang="en-US"/></a:p>')


def case_retitle(work):
    bold = '<a:p><a:r><a:rPr lang="en-US" b="1"/><a:t>Demand</a:t></a:r></a:p>'
    two = ('<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US"/><a:t>Market </a:t></a:r>'
           '<a:r><a:rPr lang="en-US" i="1"/><a:t>Demand</a:t></a:r>'
           '<a:endParaRPr lang="en-US" dirty="0"/></a:p>')
    path = deck(os.path.join(work, "titles.pptx"), [
        {"shapes": [styled_title(2, [bold])]},
        {"shapes": [styled_title(2, [bold])]},
        {"shapes": [styled_title(2, [two])]},
        {"shapes": [styled_title(2, ['<a:p><a:r><a:t>Market</a:t></a:r></a:p>',
                                     '<a:p><a:r><a:t>Demand</a:t></a:r></a:p>'])]},
        {"shapes": [alternate(styled_title(2, [bold]), styled_title(2, [bold]))]},
        {"shapes": [styled_title(2, [bold.replace("Demand", "demand.")])]},
        {"shapes": [styled_title(2, [bold]), rect(2, "Rectangle 1", (0, 1600200, 10, 10))]},
        {"shapes": [styled_title(2, ['<a:p><a:r><a:t>Supply</a:t></a:r></a:p>',
                                     '<a:p><a:r><a:t>and more</a:t></a:r></a:p>'])]},
        {"shapes": [styled_title(2, ['<a:p><a:r><a:t>Supply</a:t></a:r></a:p>',
                                     '<a:p><a:r><a:t>and more</a:t></a:r></a:p>'])]},
        {"shapes": [styled_title(2, ['<a:p><a:r><a:t>Elasticity of demand</a:t></a:r></a:p>'])]},
        {"shapes": [styled_title(2, [MEAN])]},
        {"shapes": [styled_title(2, [MEAN])]},
    ])
    d = pptxparse.read(path)
    rows = deckrun.repeated_titles("titles.pptx", "titles", d, {})
    yield "each slide titled as one before it gets a row, drafted with its number among them", \
        [r[:2] for r in rows] == [
            ["titles/slide-257", "Demand (2)"], ["titles/slide-259", "Market Demand (2)"],
            ["titles/slide-260", "Demand (3)"], ["titles/slide-261", "demand. (4)"],
            ["titles/slide-262", "Demand (5)"], ["titles/slide-264", "Supply and more (2)"],
            ["titles/slide-267", "The mean of x (2)"]] and all(r[3] == "TI" for r in rows), rows
    key = [rem.slide_key("titles", s) for s in d.slides]
    titles = {key[1]: "Demand (2)", key[2]: "Shifts in <demand> & supply",
              key[3]: "Market Demand (2)", key[4]: "Demand (3)", key[5]: "demand.",
              key[6]: "Demand (4)", key[7]: "Elasticity", key[9]: "Price elasticity",
              key[11]: "The mean of x (2)"}
    out, counts = remediated(work, "titles.pptx", path, titles=titles)
    e = pptxparse.read(out)
    second = read_part(out, "ppt/slides/slide2.xml")
    yield "what a new title adds to the old goes after its last run, in that run's formatting", \
        '<a:t>Demand</a:t></a:r><a:r><a:rPr lang="en-US" b="1"/><a:t> (2)</a:t></a:r></a:p>' \
        in second and e.slides[1].title == "Demand (2)", second[second.find("<p:txBody>"):][:300]
    third = read_part(out, "ppt/slides/slide3.xml")
    yield "a new title that doesn't begin with the old is one run, in the first run's and the " \
        "first paragraph's formatting, escaped", \
        '<a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US"/><a:t>Shifts in &lt;demand&gt; &amp; ' \
        'supply</a:t></a:r><a:endParaRPr lang="en-US" dirty="0"/></a:p></p:txBody>' in third \
        and e.slides[2].title == "Shifts in <demand> & supply", \
        third[third.find("<p:txBody>"):][:400]
    fourth = read_part(out, "ppt/slides/slide4.xml")
    yield "a title of two paragraphs keeps them, its addition after the last run", \
        fourth.count("<a:p>") == 2 and '<a:t>Demand</a:t></a:r><a:r><a:t> (2)</a:t></a:r>' \
        in fourth and e.slides[3].title == "Market Demand (2)", \
        fourth[fourth.find("<p:txBody>"):][:400]
    eighth = read_part(out, "ppt/slides/slide8.xml")
    yield "and in place of every paragraph of the old title", \
        eighth.count("<a:p>") == 1 and "<a:t>Elasticity</a:t>" in eighth \
        and "Supply" not in eighth and "and more" not in eighth, \
        eighth[eighth.find("<p:txBody>"):][:300]
    yield "a title in AlternateContent is replaced in its Choice and its Fallback", \
        read_part(out, "ppt/slides/slide5.xml").count("<a:t> (3)</a:t>") == 2, ""
    yield "a row giving the title as it is keeps it, and a title whose id repeats is left", \
        read_part(out, "ppt/slides/slide6.xml") == read_part(path, "ppt/slides/slide6.xml") \
        and read_part(out, "ppt/slides/slide7.xml") == read_part(path, "ppt/slides/slide7.xml") \
        and counts["retitled"] == 6 and counts["skipped"] == 1, counts
    twelfth = read_part(out, "ppt/slides/slide12.xml")
    yield "what a new title adds goes after an equation that ends the old", \
        '</a14:m><a:r><a:rPr lang="en-US"/><a:t> (2)</a:t></a:r><a:endParaRPr' in twelfth \
        and e.slides[11].title == "The mean of x (2)", twelfth[twelfth.find("<p:txBody>"):][:500]
    # A row for a slide whose title is its own alone: the author's stands.
    folder = os.path.join(work, "titles-run")
    os.makedirs(folder)
    shutil.copy(path, folder)
    sidecar = os.path.join(folder, "slide-titles.csv")
    with open(sidecar, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.TITLE_COLUMNS] + [[k, v] for k, v in titles.items()])
    said = []
    deckrun.run(folder, ["titles.pptx"], [],
                {"slide_titles": sidecar, "image_alt": os.path.join(folder, "image-alt.csv"),
                 "table_headers": os.path.join(folder, "table-headers.csv")},
                {k: os.path.join(folder, v) for k, v in (
                    ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
                    ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"))},
                check_only=True, say=said.append)
    yield "a row for a slide with a title no other slide has isn't used, and the run says so", \
        read_part(out, "ppt/slides/slide10.xml") == read_part(path, "ppt/slides/slide10.xml") \
        and counts["titles_kept"] == 1 and deckrun.kept_titles("titles", d, titles) == [key[9]] \
        and any("1 row(s) of slide-titles.csv aren't used: each is for a slide with a title of " \
                "its own that no other slide in its deck has, which its copy keeps " \
                "(titles/slide-265)." in line for line in said), (counts, said)
    found = pptxcheck.check(e)
    yield "the copy's slides titled alike are only those the sidecar left alike", \
        [f.detail for f in found if f.check == "pptx-duplicate-title"] == [
            "3 slides titled demand"], [(f.check, f.detail) for f in found]


DOI, SHORT = "https://doi.org/10.1080/08913810508443640", "https://doi.org/10/b8xx35"
CARS = "https://dasl.datadescription.com/datafile/cars"
KEPT = "https://example.org/kept"
SPLIT = "https://example.org/split"
TIPPED = "https://example.org/tipped"
ALTERNATE = "https://example.org/alternate"


def linked(shape_id, name, box, runs):
    """A text box of one paragraph whose runs are (text, relationship id
    or None, tooltip or None)."""
    out = []
    for text, rid, tip in runs:
        if rid:
            click = '<a:hlinkClick r:id="%s"%s/>' % (rid, ' tooltip="%s"' % esc(tip) if tip else "")
            out.append('<a:r><a:rPr lang="en-US">%s</a:rPr><a:t>%s</a:t></a:r>' % (click, esc(text)))
        else:
            out.append('<a:r><a:rPr lang="en-US"/><a:t>%s</a:t></a:r>' % esc(text))
    return ('<p:sp>%s<p:spPr>%s<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr><p:txBody>'
            '<a:bodyPr/><a:lstStyle/><a:p>%s</a:p></p:txBody></p:sp>'
            % (nv("sp", shape_id, name), xfrm(*box), "".join(out)))


def equation(shape_id, omml):
    """A text box holding one equation, as PowerPoint writes one: Office
    math in a14:m, its namespace declared on m:oMath, in AlternateContent."""
    box = ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a14:m><m:oMath '
           'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">%s</m:oMath>'
           '</a14:m></a:p></p:txBody></p:sp>' % (nv("sp", shape_id, "TextBox %d" % shape_id),
                                                 xfrm(457200, 1600200, 4000000, 600000), omml))
    return ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/'
            '2006"><mc:Choice xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" '
            'Requires="a14">%s</mc:Choice><mc:Fallback>%s</mc:Fallback></mc:AlternateContent>'
            % (box, rect(shape_id, "TextBox %d" % shape_id, (457200, 1600200, 4000000, 600000))))


BAR_OMML = ('<m:limUpp><m:e><m:r><m:t>x</m:t></m:r></m:e><m:lim><m:r><m:t>¯</m:t></m:r>'
            '</m:lim></m:limUpp><m:r><m:t>–µ</m:t></m:r>')


def case_links(work):
    path = deck(os.path.join(work, "links.pptx"), [
        {"shapes": [title(2, "Sources"),
                    linked(4, "TextBox 3", (457200, 1600200, 8000000, 400000),
                           [("Klein and Stern. 2005. ", None, None),
                            ("https://doi.org/10.1080/", "rId3", None),
                            ("08913810508443640", "rId3", None)]),
                    linked(5, "TextBox 4", (457200, 2200000, 8000000, 400000),
                           [("Cars: ", None, None), (CARS, "rId4", None), (" (see ", None, None),
                            ("the codebook", "rId8", None), (")", None, None)]),
                    linked(6, "TextBox 5", (457200, 2800000, 8000000, 400000),
                           [(KEPT, "rId5", "Its own title"), (" and ", None, None),
                            ("the cars data", "rId4", None)])],
         "links": {"rId3": DOI, "rId4": CARS, "rId5": KEPT, "rId8": "https://example.org/codebook"}},
        {"shapes": [title(2, "Means"), equation(4, BAR_OMML)]},
        {"shapes": [title(2, "Grouped"),
                    group(7, [linked(8, "TextBox 7", (0, 0, 4000000, 400000),
                                     [("https://example.org/grouped", "rId6", None)])],
                          (457200, 1600200, 4000000, 400000), descr="A link in a group"),
                    linked(9, "TextBox 8", (457200, 2800000, 8000000, 400000),
                           [("https://example.org/", "rId7", None), ("split", "rId7", None)]),
                    linked(10, "TextBox 9", (457200, 3400000, 8000000, 400000),
                           [("https://example.org/grouped", "rId6", None)])],
         "links": {"rId6": "https://example.org/grouped", "rId7": SPLIT}},
        # 4: an address over two runs with a ScreenTip on one, two links to
        # a reader, as the report reads it, and the address bare elsewhere
        {"shapes": [title(2, "Tipped"),
                    linked(4, "TextBox 3", (457200, 1600200, 8000000, 400000),
                           [("https://example.org/", "rId9", "A tip"), ("tipped", "rId9", None)]),
                    linked(5, "TextBox 4", (457200, 2200000, 8000000, 400000),
                           [(TIPPED, "rId10", None)])],
         "links": {"rId9": TIPPED, "rId10": TIPPED}},
        # 5: a link in a shape in AlternateContent, in its Choice and its
        # Fallback
        {"shapes": [title(2, "Alternate"),
                    alternate(*[linked(4, "TextBox 3", (457200, 1600200, 8000000, 400000),
                                       [(ALTERNATE, "rId11", None)]) for _ in range(2)])],
         "links": {"rId11": ALTERNATE}},
    ])
    d = pptxparse.read(path)
    yield "a link inside a group is its piece's, not the group's too, and named once", \
        [len(s.links) for s in d.slides[2].all_shapes()][1:3] == [0, 1] \
        and [f.where for f in pptxcheck.check(d) if f.check == "pptx-link-bare-url"
             and "grouped" in f.detail] == ["slide 3, TextBox 7", "slide 3, TextBox 9"], \
        [(s.name, len(s.links)) for s in d.slides[2].all_shapes()]
    first = d.slides[0].shapes[1].links
    yield "a link over two runs is one link, with the text before it in its paragraph", \
        [(l.text, l.target, l.context) for l in first] == [
            ("https://doi.org/10.1080/08913810508443640", DOI, "Klein and Stern. 2005. ")], \
        [(l.text, l.target, l.context) for l in first]
    folder = os.path.join(work, "run")
    os.makedirs(folder)
    shutil.copy(path, folder)
    reports = {k: os.path.join(folder, v) for k, v in (
        ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
        ("slide_titles_new", "s.csv"), ("bare_links_new", "bare-links-new.csv"),
        ("slides_check", "check.csv"), ("output_check", "output-check.csv"))}
    paths = {k: os.path.join(folder, v) for k, v in (
        ("image_alt", "image-alt.csv"), ("table_headers", "table-headers.csv"),
        ("slide_titles", "slide-titles.csv"), ("bare_links", "bare-links.csv"))}
    deckrun.run(folder, ["links.pptx"], [], paths, reports, check_only=True, say=lambda _m: None)
    rows = rows_of(reports["bare_links_new"])
    yield "each bare address gets a row, as a book's report has it, with its own ScreenTip and " \
        "each slide it's on named once, and a link named in words none", \
        rows == [[DOI, "", "", "links.pptx slide 1", "Klein and Stern. 2005.", "", ""],
                 [CARS, "", "", "links.pptx slide 1", "Cars:", "", ""],
                 [KEPT, "", "Its own title", "links.pptx slide 1", "", "", ""],
                 ["https://example.org/grouped", "", "", "links.pptx slide 3", "", "", ""],
                 [SPLIT, "", "", "links.pptx slide 3", "", "", ""],
                 [TIPPED, "", "", "links.pptx slide 4", "", "", ""],
                 [ALTERNATE, "", "", "links.pptx slide 5", "", "", ""]], rows
    with open(paths["bare_links"], "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.LINK_COLUMNS, [DOI, SHORT, "DOI for Klein and Stern 2005"],
                                  [CARS, "The Data and Story Library's cars data", ""],
                                  [KEPT, "", ""], ["https://example.org/grouped", "", ""],
                                  [SPLIT, "", "Split over two runs"], [TIPPED, "Tipped", ""],
                                  [ALTERNATE, "", "In AlternateContent"],
                                  ["https://example.org/gone", "", ""]])
    links = rem.link_rows(paths["bare_links"])
    out = os.path.join(work, "out", "links.pptx")
    counts = rem.remediate(path, out, links=links, equations=True, deck="links")
    slide, rels = read_part(out, "ppt/slides/slide1.xml"), read_part(out, "ppt/slides/_rels/slide1.xml.rels")
    yield "an address replaces the link's address and its text, in its first run, with its " \
        "ScreenTip", ('<a:hlinkClick r:id="rId3" tooltip="DOI for Klein and Stern 2005"/></a:rPr>'
                      '<a:t>%s</a:t></a:r></a:p>' % SHORT) in slide and "08913810508443640" not in slide \
        and 'Target="%s"' % SHORT in rels and DOI not in rels, slide[slide.find("Klein"):][:400]
    yield "text replaces only the bare link's text; the same address's named link is left", \
        "<a:t>The Data and Story Library's cars data</a:t>" in slide \
        and "<a:t>the cars data</a:t>" in slide and 'Target="%s"' % CARS in rels, \
        slide[slide.find("Cars"):][:300]
    yield "a blank row keeps the link and its own ScreenTip", \
        '<a:hlinkClick r:id="rId5" tooltip="Its own title"/>' in slide \
        and "<a:t>%s</a:t>" % KEPT in slide and counts["links"] == 3 and counts["replaced"] == 3, \
        counts
    four, five = read_part(out, "ppt/slides/slide4.xml"), read_part(out, "ppt/slides/slide5.xml")
    yield "an address over runs with two ScreenTips is two links, as the report reads it: left", \
        "<a:t>https://example.org/</a:t>" in four and "<a:t>tipped</a:t>" in four \
        and "<a:t>Tipped</a:t>" in four, four[four.find("TextBox 3"):][:600]
    yield "a link in AlternateContent gets its ScreenTip in its Choice and its Fallback, " \
        "counted once", five.count('tooltip="In AlternateContent"') == 2, five
    three = read_part(out, "ppt/slides/slide3.xml")
    split = [(l.text, l.tooltip) for l in pptxparse.read(out).slides[2].shapes[2].links]
    yield "a ScreenTip alone goes on every run of its link, which stays one link", \
        three.count('<a:hlinkClick r:id="rId7" tooltip="Split over two runs"/>') == 2 \
        and split == [(SPLIT, "Split over two runs")], (split, three[three.find("TextBox 8"):][:500])
    yield "every changed part is well-formed, and nothing else changed", \
        ET.fromstring(slide.encode()) is not None and ET.fromstring(rels.encode()) is not None \
        and read_part(out, "ppt/presentation.xml") == read_part(path, "ppt/presentation.xml"), ""
    odd = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Id="rId9" Type="x" Target="https://example.org/?a>b" '
           'TargetMode="External" /><Relationship Id="rId8" Type="y" Target="../media/x.png"/>'
           '</Relationships>')
    xml, new_rels, _titled, replaced = rem.set_links(
        '<a:p><a:r><a:rPr><a:hlinkClick r:id="rId9"/></a:rPr><a:t>https://example.org/?a>b</a:t>'
        '</a:r></a:p>', odd, {"https://example.org/?a>b": ("https://example.org/", "")})
    yield "an address with > in it, which XML allows unescaped, is found and replaced", \
        replaced == 1 and "<a:t>https://example.org/</a:t>" in xml and new_rels == odd.replace(
            'Target="https://example.org/?a>b" TargetMode="External" />',
            'Target="https://example.org/" TargetMode="External"/>'), new_rels
    found = pptxcheck.check(pptxparse.read(out), links=rem.decided_links(links))
    yield "a link the sidecar decided isn't counted against the copy, kept bare or not", \
        "pptx-link-bare-url" not in checks_of(found) \
        and "pptx-link-bare-url" in checks_of(pptxcheck.check(pptxparse.read(out))), \
        [(f.check, f.detail) for f in found]
    two = read_part(out, "ppt/slides/slide2.xml")
    yield "an equation gets the characters it means, PowerPoint's as Word's: a bar for a " \
        "macron over x, a minus for an en dash, mu for the micro sign", \
        "<m:acc>" in two and "<m:limUpp>" not in two and "<m:t>−μ</m:t>" in two \
        and counts["equations_repaired"] == 1 and counts["equation_characters"] == 3 \
        and ET.fromstring(two.encode()) is not None, two[two.find("<a14:m>"):][:400]
    plain = rem.remediate(path, os.path.join(work, "out", "plain.pptx"), deck="links")
    yield "and nothing of the kind without math.repair_equations or a sidecar", \
        plain["equations_repaired"] == plain["links"] == plain["replaced"] == 0 \
        and read_part(os.path.join(work, "out", "plain.pptx"), "ppt/slides/slide2.xml") \
        == read_part(path, "ppt/slides/slide2.xml"), plain
    # A run: the target's math.repair_equations, the counts said, a stale
    # row named, the report gone.
    target = type("Target", (), {"format": "source", "name": "fixed",
                                 "output_dir": os.path.join(folder, "fixed"),
                                 "__getitem__": lambda self, key: key == "math.repair_equations"})()
    said = []
    code = deckrun.run(folder, ["links.pptx"], [target], paths, reports, say=said.append)
    left = [r[1] for r in rows_of(reports["output_check"])]
    yield "a run writes them, says so, and names a row matching no link", \
        code == 0 and not os.path.exists(reports["bare_links_new"]) \
        and "fixed: 3 bare link(s) given a ScreenTip and 3 a replacement, as bare-links.csv " \
        "says." in said and "fixed: 1 equation(s) given the characters they mean, 3 " \
        "character(s) in all (math.repair_equations)." in said \
        and any("1 row(s) of bare-links.csv match no bare link" in l for l in said) \
        and "pptx-link-bare-url" not in left, (said, left)


# ---------------------------------------------------------------------------
# convert.py over a folder of decks
# ---------------------------------------------------------------------------

def pandoc_ok():
    """Whether convert.py can read a book here, which it reads with Pandoc
    3.9 or later; a slides run needs none."""
    if shutil.which("pandoc") is None:
        print("  skip  pandoc not found; convert.py needs it for a book")
        return False
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        print(f"  skip  Pandoc {version} is too old; convert.py needs 3.9 or later")
        return False
    return True


def convert(where, *flags):
    return subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet", *flags],
                          cwd=where, capture_output=True, text=True, stdin=subprocess.DEVNULL)


def rows_of(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))[1:]


def case_convert(work):
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    messy_deck(os.path.join(folder, "messy.pptx"))
    clean_deck(os.path.join(folder, "clean.pptx"))
    deck(os.path.join(folder, "numbers.pptx"), [
        {"shapes": [title(2, "Growth"), table(4, [["Year", "GDP"], ["2020", "1.0"], ["2021", "1.1"]],
                                              (457200, 1600200, 6000000, 1200000))]}])
    with open(os.path.join(folder, "README.md"), "w") as fh:
        fh.write("# About these slides\n")
    first = convert(folder, "--check-only")
    alt = rows_of(os.path.join(folder, "image-alt-missing.csv"))
    yield "--check-only on a folder of decks: the reports, and no copies", \
        first.returncode == 0 and alt and not os.path.exists(os.path.join(folder, "remediated")) \
        and os.path.exists(os.path.join(folder, "slides-check.csv")), first.stderr[-600:]
    second = convert(folder)
    yield "a folder of decks alone is slides: the implied target writes a copy of each", \
        second.returncode == 0 and sorted(os.listdir(os.path.join(folder, "remediated"))) == \
        ["clean.pptx", "messy.pptx", "numbers.pptx"] and "Output check: 3 deck(s)" in second.stderr, \
        second.stderr[-800:]
    keys = [r[0] for r in alt]
    picture = next(k for k in keys if k.startswith("media/"))
    yield "a picture's row is keyed on its content, and its image is where the key says", \
        re.fullmatch(r"media/[0-9a-f]{16}\.png", picture) is not None \
        and os.path.isfile(os.path.join(folder, picture)), keys
    yield "an object's row is keyed on its deck, slide, and shape", \
        "messy/slide-257/shape-5" in keys and "messy/slide-260/shape-6" in keys, keys
    tables = rows_of(os.path.join(folder, "table-headers-new.csv"))
    titles = rows_of(os.path.join(folder, "slide-titles-new.csv"))
    by_source = {r[5]: r for r in tables}
    merged = deckrun.census_guess(pptxparse.read(os.path.join(folder, "messy.pptx"))
                                  .slides[2].shapes[1].table)
    yield "a table with no header row gets a row with the census's guess, drafted by TI", \
        len(tables) == 2 and by_source["numbers.pptx slide 1"][1] in ("first-row", "both") \
        and by_source["numbers.pptx slide 1"][8] == "TI" \
        and by_source["numbers.pptx slide 1"][6] == "Growth", tables
    yield "and a table the census can't guess gets an empty row, nobody's draft", \
        merged == "" and by_source["messy.pptx slide 3"][1:2] == [""] \
        and by_source["messy.pptx slide 3"][8] == "", (merged, tables)
    yield "each untitled slide gets a row, and each titled as one before it a drafted one", \
        [r[:2] + r[3:4] for r in titles] == [
            ["messy/slide-256", "", ""], ["messy/slide-257", "", ""],
            ["messy/slide-259", "Costs (2)", "TI"], ["messy/slide-262", "Words (2)", "TI"]] \
        and titles[2][2] == "messy.pptx slide 4, titled as slide 3 is", titles
    orders = rows_of(os.path.join(folder, "reading-order-new.csv"))
    yield "a slide read out of its layout's order gets a row with an order drafted", \
        [r[:2] for r in orders] == [["messy/slide-259", "2 4"]] and orders[0][5] == "TI", orders
    # Decide everything, adopting the reports' rows as a person would.
    with open(os.path.join(folder, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(deckrun.ALT_COLUMNS)
        for i, row in enumerate(alt):
            writer.writerow([row[0], "[decorative]" if "says nothing" in row[3] else
                             "" if row[3].startswith("too long") else
                             "Described, number %d" % i] + row[2:])
    # The census's row adopted as it stands, a person's value where it has
    # none, as TI's draft and a person's own.
    with open(os.path.join(folder, "table-headers.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.TABLE_COLUMNS] + [
            [r[0], r[1] or "first-row"] + r[2:] for r in tables])
    with open(os.path.join(folder, "slide-titles.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.TITLE_COLUMNS] + [[r[0], r[1] or "Slide %d" % i] + r[2:]
                                                            for i, r in enumerate(titles, 1)])
    with open(os.path.join(folder, "reading-order.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.ORDER_COLUMNS] + orders)
    with open(os.path.join(folder, "project.yaml"), "w") as fh:
        fh.write("project:\n  language: en-US\n")
    third = convert(folder)
    found = rows_of(os.path.join(folder, "output-check.csv"))
    left = sorted({r[1] for r in found})
    yield "with every decision made, the reports are gone", \
        third.returncode == 0 and not any(os.path.exists(os.path.join(folder, n)) for n in (
            "image-alt-missing.csv", "table-headers-new.csv", "slide-titles-new.csv",
            "reading-order-new.csv")), third.stderr[-800:]
    decided = {"pptx-slide-no-title", "pptx-object-no-alt", "pptx-table-no-header",
               "pptx-alt-placeholder", "pptx-alt-is-file-name", "pptx-no-language",
               "pptx-no-core-title", "pptx-shape-no-alt", "pptx-alt-auto-generated",
               "pptx-reading-order", "pptx-duplicate-title"}
    yield "and the copies' check finds nothing that was decided, but alt text kept as it was", \
        not decided & set(left) and "pptx-alt-too-long" in left, left
    copy = pptxparse.read(os.path.join(folder, "remediated", "messy.pptx"))
    yield "the copy has the titles, the language, the title in its properties, and the order", \
        [s.title for s in copy.slides][:2] == ["Slide 1", "Slide 2"] \
        and copy.default_language == "en-US" and copy.core_title == "Slide 1" \
        and [s.id for s in copy.slides[3].shapes] == ["2", "4"] \
        and [s.title for s in copy.slides][2:7] == ["Costs", "Costs (2)", "Media", "Words",
                                                    "Words (2)"], \
        ([s.title for s in copy.slides], copy.default_language, copy.core_title,
         [s.id for s in copy.slides[3].shapes])
    yield "the run says how many slides got a title in place of one another slide has", \
        "remediated: 2 slide(s) given the title slide-titles.csv gives in place of one another " \
        "slide has." in third.stderr, third.stderr[-800:]
    yield "the table's row is used, and a drafted row nobody reviewed is said to be", \
        "drafted by TextbookImprover or a model and not yet reviewed" in third.stderr \
        and copy.slides[2].shapes[1].table.first_row, third.stderr[-400:]
    # A row whose key no deck has is said to be stale.
    with open(os.path.join(folder, "slide-titles.csv"), "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(["messy/slide-999", "Gone"])
    fourth = convert(folder, "--check-only")
    yield "a sidecar row matching no slide is named", \
        "1 row(s) of slide-titles.csv match no slide" in fourth.stderr, fourth.stderr[-500:]


def case_folders(work):
    # A book's folder with a deck in it: the deck is left out, and said to be.
    # A book is read by Pandoc; the rest is slides, which need none.
    book = os.path.join(work, "book")
    os.makedirs(book)
    with open(os.path.join(book, "one.md"), "w") as fh:
        fh.write("---\ntitle: One\n---\n\n# One\n\nText.\n")
    clean_deck(os.path.join(book, "talk.pptx"))
    with open(os.path.join(book, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.slides\n  title: A Book\n")
    if pandoc_ok():
        result = convert(book, "--check-only")
        yield "a deck beside a book's pages is left out, and the run says so", \
            result.returncode == 0 and "1 PowerPoint deck(s) here are left out (talk.pptx)" \
            in result.stderr and not os.path.exists(os.path.join(book, "slides-check.csv")), \
            result.stderr[-500:]
    # project.kind: slides makes it slides, and the page is left out instead.
    with open(os.path.join(book, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.slides\n  title: A Book\n  kind: slides\n")
    result = convert(book, "--check-only")
    yield "project.kind: slides makes it slides, with the pages left out", \
        result.returncode == 0 and "1 file(s) here are left out (one.md)" in result.stderr \
        and os.path.exists(os.path.join(book, "slides-check.csv")), result.stderr[-500:]
    # Decks in a zip, wrapped in a folder, with macOS's leftovers.
    zipped = os.path.join(work, "zipped")
    os.makedirs(zipped)
    clean = clean_deck(os.path.join(work, "clean.pptx"))
    with zipfile.ZipFile(os.path.join(zipped, "slides.zip"), "w") as z:
        z.write(clean, "Slides/clean.pptx")
        z.writestr("__MACOSX/Slides/._clean.pptx", b"junk")
        link = zipfile.ZipInfo("Slides/elsewhere")
        link.external_attr = (0o120777 << 16)          # a link, as Info-ZIP stores one
        z.writestr(link, "/etc/passwd")
    result = convert(zipped)
    yield "decks in a zip are unpacked and remediated, a link in it refused and reported", \
        result.returncode == 0 and os.path.exists(os.path.join(zipped, "clean.pptx")) \
        and os.path.exists(os.path.join(zipped, "remediated", "clean.pptx")) \
        and not os.path.lexists(os.path.join(zipped, "elsewhere")) \
        and rows_of(os.path.join(zipped, "unpack-report.csv")) == [
            ["Slides/elsewhere", "not-a-file", "a link or a special file, not a file; not extracted"]] \
        and "1 PowerPoint deck(s), which are the slides" in result.stderr, result.stderr[-500:]
    # Decks in a .tgz, its link refused; the copies packed, and left alone after.
    tarred = os.path.join(work, "tarred")
    os.makedirs(tarred)
    with tarfile.open(os.path.join(tarred, "slides.tgz"), "w:gz") as t:
        t.add(clean, "Slides/clean.pptx")
        link = tarfile.TarInfo("Slides/elsewhere")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(link)
        junk = tarfile.TarInfo("Slides/._clean.pptx")
        junk.size = 4
        t.addfile(junk, io.BytesIO(b"junk"))
    with open(os.path.join(tarred, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  fixed:\n    format: source\n    archive: zip\n")
    result = convert(tarred)
    report = rows_of(os.path.join(tarred, "unpack-report.csv"))
    yield "decks in a tgz are unpacked, a link in it refused and reported", \
        result.returncode == 0 and os.path.exists(os.path.join(tarred, "clean.pptx")) \
        and not os.path.lexists(os.path.join(tarred, "elsewhere")) \
        and not os.path.exists(os.path.join(tarred, "._clean.pptx")) \
        and report == [["Slides/elsewhere", "not-a-file",
                        "a link or a special file, not a file; not extracted"]], \
        (report, result.stderr[-400:])
    with zipfile.ZipFile(os.path.join(tarred, "fixed.zip")) as z:
        packed = z.namelist()
    again = convert(tarred)
    yield "archive: zip packs the target's folder beside it, and a later run lets it be", \
        packed == ["fixed/clean.pptx"] and again.returncode == 0 \
        and "fixed.zip" not in again.stderr.replace("packed into fixed.zip", ""), \
        (packed, again.stderr[-300:])
    # A deck that can't be read: the copies that could be written are, and
    # nothing is archived, so a whole-looking archive is never half the set.
    os.remove(os.path.join(tarred, "fixed.zip"))
    with open(os.path.join(tarred, "broken.pptx"), "wb") as fh:
        fh.write(b"not a deck")
    broken = convert(tarred)
    yield "with a deck that can't be read, nothing is archived, and the run says so", \
        broken.returncode == 1 and not os.path.exists(os.path.join(tarred, "fixed.zip")) \
        and os.path.exists(os.path.join(tarred, "fixed", "clean.pptx")) \
        and "nothing was archived" in broken.stderr \
        and "broken.pptx couldn't be read as a PowerPoint deck: it isn't a PowerPoint file" \
        in broken.stderr, broken.stderr[-400:]
    # The audit reads a deck, and remediate.py writes one.
    audited = os.path.join(work, "audited")
    result = subprocess.run(["python3", os.path.join(BIN, "audit.py"), clean, "-o", audited,
                             "--no-cache", "--quick"], capture_output=True, text=True)
    rows = rows_of(os.path.join(audited, "audit.csv"))
    yield "audit.py reads a deck, and finds a clean one clean", \
        result.returncode == 0 and rows == [] and "clean.pptx: 0 finding(s)" in result.stderr, \
        result.stderr[-300:]
    messy = messy_deck(os.path.join(work, "messy.pptx"))
    sidecar = os.path.join(work, "titles.csv")
    with open(sidecar, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Slide", "Title"], ["messy/slide-256", "Opening"],
                                  ["messy/slide-260", "Video"]])
    order = os.path.join(work, "order.csv")
    with open(order, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["messy/slide-259", "2 4"], ["messy/slide-260", "6 4 4"]])
    result = subprocess.run(["python3", os.path.join(ROOT, "util", "remediate.py"), messy,
                             "--slide-titles", sidecar, "--reading-order", order,
                             "--out", os.path.join(work, "util-out")],
                            capture_output=True, text=True)
    copy = pptxparse.read(os.path.join(work, "util-out", "messy.pptx"))
    yield "remediate.py writes a deck's decisions too, the reading order among them", \
        result.returncode == 0 and copy.slides[0].title == "Opening" \
        and copy.slides[4].title == "Media" and "slides: 1 slide-titles row(s) not used: each " \
        "is for a slide with a title of its own that no other slide in its deck has, which the " \
        "copy keeps." in result.stderr \
        and [s.id for s in copy.slides[3].shapes] == ["2", "4"] \
        and "1 title(s) added above their slides, 1 slide(s) put in the reading order given" \
        in result.stderr and "the reading order for messy/slide-260 isn't written: it names 4 " \
        "twice" in result.stderr, result.stderr[-500:]
    # A deck's bare links and equations, beside a page with the same link:
    # the slides line counts the decks' alone.
    maths = deck(os.path.join(work, "maths.pptx"), [
        {"shapes": [title(2, "Means"), equation(4, BAR_OMML)]}])
    page = os.path.join(work, "page.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write('<html lang="en"><head><title>Page</title></head><body><p>'
                 '<a href="https://example.org">https://example.org</a></p></body></html>')
    links = os.path.join(work, "links.csv")
    with open(links, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["URL", "Replacement", "Title"],
                                  ["https://example.org", "Example", "An example"]])
    result = subprocess.run(["python3", os.path.join(ROOT, "util", "remediate.py"), messy, maths,
                             page, "--links", links, "--repair-equations",
                             "--out", os.path.join(work, "util-links")],
                            capture_output=True, text=True)
    copy = pptxparse.read(os.path.join(work, "util-links", "messy.pptx"))
    found = [(l.text, l.target, l.tooltip) for s in copy.slides for shape in s.all_shapes()
             for l in shape.links if l.external]
    yield "remediate.py writes a deck's bare links and equations, and counts the decks' alone", \
        result.returncode == 0 and found == [("Example", "https://example.org", "An example")] \
        and "<m:acc>" in read_part(os.path.join(work, "util-links", "maths.pptx"),
                                   "ppt/slides/slide1.xml") \
        and "1 bare link(s) given a replacement; 1 equation(s) repaired;" in result.stderr \
        and "Example</a>" in open(os.path.join(work, "util-links", "page.html"),
                                  encoding="utf-8").read(), (found, result.stderr[-600:])


def case_no_pandoc(work):
    """convert.py with no Pandoc on the PATH: a slides run reads and writes
    its decks itself, and a book says what it needs."""
    tools = os.path.join(work, "bin")
    os.makedirs(tools)
    os.symlink(sys.executable, os.path.join(tools, "python3"))

    def bare_run(where):
        return subprocess.run([os.path.join(tools, "python3"), os.path.join(BIN, "convert.py"),
                               "--quiet"], cwd=where, env=dict(os.environ, PATH=tools),
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
    decks = os.path.join(work, "decks")
    os.makedirs(decks)
    messy_deck(os.path.join(decks, "messy.pptx"))
    result = bare_run(decks)
    yield "a slides run needs no Pandoc: the reports and the copies", \
        result.returncode == 0 and os.path.exists(os.path.join(decks, "remediated", "messy.pptx")) \
        and os.path.exists(os.path.join(decks, "image-alt-missing.csv")), result.stderr[-500:]
    book = os.path.join(work, "book")
    os.makedirs(book)
    with open(os.path.join(book, "one.md"), "w") as fh:
        fh.write("---\ntitle: One\n---\n\n# One\n\nText.\n")
    with open(os.path.join(book, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.book\n  title: A Book\n")
    result = bare_run(book)
    yield "and a book's run says it needs Pandoc 3.9 or later", \
        result.returncode != 0 and "pandoc not found. Version 3.9 or later is required." \
        in result.stderr, result.stderr[-300:]


CASES = [("reading a deck", case_parse), ("the checks", case_check),
         ("the copy", case_remediate), ("the copy, more", case_remediate_more),
         ("the sidecars", case_sidecars), ("what a review found", case_edges),
         ("what PowerPoint made of Pandoc's decks", case_powerpoint),
         ("the reading order", case_order), ("drafting an order", case_draft),
         ("titles another slide has", case_retitle),
         ("links and equations", case_links),
         ("convert.py on decks", case_convert),
         ("folders, archives, and tools", case_folders),
         ("no Pandoc", case_no_pandoc)]


def main():
    failures = total = 0
    for label, case in CASES:
        print(label)
        work = tempfile.mkdtemp(prefix="slides-test-")
        try:
            for name, ok, detail in case(work):
                total += 1
                if ok:
                    print("  ok    %s" % name)
                else:
                    failures += 1
                    print("  FAIL  %s" % name)
                    if detail:
                        print("          %s" % str(detail)[:400])
        except Exception as exc:              # a case that breaks is a failure, not a stop
            failures += 1
            total += 1
            print("  ERROR %s: %s: %s" % (label, type(exc).__name__, exc))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("")
    if failures:
        print("%d of %d slides checks failed." % (failures, total), file=sys.stderr)
        return 1
    print("all %d slides checks passed" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
