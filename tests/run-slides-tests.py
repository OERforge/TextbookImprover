#!/usr/bin/env python3
"""
run-slides-tests.py -- PowerPoint decks: reading one, checking it, writing
a person's decisions into a copy, converting it, and a run of convert.py
over a folder of them.

    python3 tests/run-slides-tests.py

Builds small decks as PresentationML with the standard library, so every
shape a check or a decision is about is there on purpose, and reads back
what the code wrote. A slides run of PowerPoint decks needs no Pandoc,
and runs here without one on the PATH too; the case of a deck beside a
book's pages, whose book needs Pandoc 3.9 or later, and the cases that
convert a deck skip without it, a deck's PDF without LuaLaTeX and
ltx-talk too. The rest needs nothing but the standard library, and
PyYAML where it runs convert.py.

A deck converted is held to a round trip: to Markdown, back to
PowerPoint through a Markdown deck's pptx target, and compared with
what it was, slide by slide (lib/deckcompare.py), the comparison shown
to see each kind of change and to match what the trip changes by design.

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
import hashlib
import html
import io
import json
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
import pptxfonts  # noqa: E402
import pptxorder  # noqa: E402
import pptxparse  # noqa: E402
import pptxremediate as rem  # noqa: E402
import pptxtitle  # noqa: E402

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


TRACK_REL = "http://schemas.microsoft.com/office/2017/04/relationships/track"
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nWelcome to the talk.\n"


def captioned(shape_id, rid, box, tracks=(), audio=False):
    """A video, or audio, whose media extension lists caption tracks as
    PowerPoint's Insert Captions writes them, each embedding a part by
    relationship (add_tracks)."""
    listed = "".join('<p173:track id="{%08d-6AC2-3BD8-4686-DAC71591EB65}" label="Captions" '
                     'lang="en" r:embed="%s"/>' % (i, track) for i, track in enumerate(tracks))
    ext = ('<p:extLst><p:ext uri="{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}"><p14:media xmlns:p14='
           '"http://schemas.microsoft.com/office/powerpoint/2010/main" r:embed="%s"><p14:extLst>'
           '<p:ext uri="{3AFAAA56-56D3-431D-BCD4-E75A35582382}"><p173:tracksInfo xmlns:p173='
           '"http://schemas.microsoft.com/office/powerpoint/2017/3/main" displayLoc="media">'
           '<p173:trackLst>%s</p173:trackLst></p173:tracksInfo></p:ext></p14:extLst></p14:media>'
           '</p:ext></p:extLst>' % (rid, listed)) if tracks else ""
    media = '<a:%s r:link="%s"/>' % ("audioFile" if audio else "videoFile", rid)
    return ("<p:pic>%s<p:blipFill><a:blip r:embed=\"%s\"/></p:blipFill><p:spPr>%s</p:spPr>"
            "</p:pic>" % (nv("pic", shape_id, "Media %s" % shape_id, "A talk", extra=media + ext),
                          rid, xfrm(*box)))


def add_tracks(path, tracks):
    """The deck at path with each slide's track relationships added,
    {slide number: [(id, part, its text or None, type)]}, a part with no
    text left out of the file."""
    with zipfile.ZipFile(path) as z:
        members = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            number = re.match(r"ppt/slides/_rels/slide(\d+)\.xml\.rels$", name)
            if number and int(number.group(1)) in tracks:
                added = "".join('<Relationship Id="%s" Type="%s" Target="../media/%s"/>'
                                % (rid, kind, os.path.basename(part))
                                for rid, part, _, kind in tracks[int(number.group(1))])
                data = data.decode("utf-8").replace("</Relationships>",
                                                    added + "</Relationships>").encode("utf-8")
            z.writestr(name, data)
        for entries in tracks.values():
            for _, part, text, _ in entries:
                if text is not None:
                    z.writestr(part, text.encode("utf-8"))
    return path


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
         style=True, styles_lang=None, layout=None, master=None, notes_master=None):
    """A deck: each slide a dict of shapes, and its images, links, charts,
    notes and their links, and whether it's hidden, by relationship id.
    layout and master:
    the XML of its one layout and its master, when not the usual ones;
    notes_master, the XML of a notes master its notes slides have."""
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
             ("ppt/slideMasters/slideMaster1.xml", master or master_xml(logo, styles_lang)),
             ("ppt/slideMasters/_rels/slideMaster1.xml.rels",
              rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False)]
                   + ([("rId2", "image", "../media/logo.png", False)] if logo else []))),
             ("ppt/slideLayouts/slideLayout1.xml", layout or layout_xml()),
             ("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
              rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml", False)]))]
    if logo:
        parts.append(("ppt/media/logo.png", BLUE))
    if notes_master:
        parts.append(("ppt/notesMasters/notesMaster1.xml", notes_master))
        types.append('<Override PartName="/ppt/notesMasters/notesMaster1.xml" ContentType="'
                     'application/vnd.openxmlformats-officedocument.presentationml.'
                     'notesMaster+xml"/>')
    for number, spec in enumerate(slides, 1):
        entries = [("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml", False)]
        for rid, data in sorted(spec.get("images", {}).items()):
            name = "ppt/media/s%d-%s.png" % (number, rid)
            parts.append((name, data))
            entries.append((rid, "image", "../media/" + os.path.basename(name), False))
        for rid, url in sorted(spec.get("links", {}).items()):
            entries.append((rid, "hyperlink", url, True))
        for rid, target in sorted(spec.get("slide_links", {}).items()):
            entries.append((rid, "slide", "slide%d.xml" % target, False))
        for rid in sorted(spec.get("charts", ())):
            name = "ppt/charts/chart%d%s.xml" % (number, rid)
            parts.append((name, '<?xml version="1.0"?><c:chartSpace xmlns:c="http://schemas.'
                                'openxmlformats.org/drawingml/2006/chart"/>'))
            entries.append((rid, "chart", "../charts/" + os.path.basename(name), False))
        for rid in sorted(spec.get("videos", ())):
            entries.append((rid, "video", "https://example.org/talk.mp4", True))
        if spec.get("notes"):
            # The notes' text, or their slide's XML whole.
            parts.append(("ppt/notesSlides/notesSlide%d.xml" % number,
                          spec["notes"] if spec["notes"].startswith("<?xml")
                          else notes_xml(spec["notes"])))
            entries.append(("rId99", "notesSlide", "../notesSlides/notesSlide%d.xml" % number,
                            False))
            if notes_master or spec.get("notes_links"):
                parts.append(("ppt/notesSlides/_rels/notesSlide%d.xml.rels" % number,
                              rels(([("rId1", "notesMaster", "../notesMasters/notesMaster1.xml",
                                      False)] if notes_master else [])
                                   + [(rid, "hyperlink", url, True) for rid, url
                                      in sorted(spec.get("notes_links", {}).items())])))
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


def case_captions(work):
    """A video's or audio's captions, as PowerPoint's Insert Captions keeps
    them: a track list in the media's extension, each track a WebVTT part.
    A track with a cue is captions; one whose part is missing, empty, of
    another kind, or not WebVTT isn't."""
    box = (457200, 1600200, 3000000, 2000000)
    right = (4000000, 1600200, 3000000, 2000000)
    path = deck(os.path.join(work, "captions.pptx"), [
        {"shapes": [title(2, "Captioned"), captioned(4, "rId5", box, ["rId6"])],
         "videos": ["rId5"]},
        {"shapes": [title(2, "Empty track"), captioned(4, "rId5", box, ["rId6"])],
         "videos": ["rId5"]},
        {"shapes": [title(2, "Missing track"), captioned(4, "rId5", box, ["rId6"])],
         "videos": ["rId5"]},
        {"shapes": [title(2, "Audio"), captioned(4, "rId5", box, ["rId6"], audio=True)],
         "videos": ["rId5"]},
        {"shapes": [title(2, "Plain"), captioned(4, "rId5", box)], "videos": ["rId5"]},
        {"shapes": [title(2, "Not captions"), captioned(4, "rId5", box, ["rId6"]),
                    captioned(5, "rId5", right, ["rId7"])], "videos": ["rId5"]},
        {"shapes": [title(2, "Marked"), captioned(4, "rId5", box, ["rId6"])],
         "videos": ["rId5"]}])
    add_tracks(path, {
        1: [("rId6", "ppt/media/track1.vtt", VTT, TRACK_REL)],
        2: [("rId6", "ppt/media/track2.vtt", "WEBVTT\n\n", TRACK_REL)],
        3: [("rId6", "ppt/media/track3.vtt", None, TRACK_REL)],
        4: [("rId6", "ppt/media/track4.vtt", VTT, TRACK_REL)],
        6: [("rId6", "ppt/media/track6.vtt", VTT, REL + "image"),
            ("rId7", "ppt/media/track6.srt", "1\n00:00:01,000 --> 00:00:04,000\nWelcome.\n",
             TRACK_REL)],
        7: [("rId6", "ppt/media/track7.vtt", "\ufeff" + VTT, TRACK_REL)]})
    parsed = pptxparse.read(path)
    media = {s.number: [shape for shape in s.all_shapes() if shape.media] for s in parsed.slides}
    found = [(f.where, f.detail) for f in pptxcheck.check(parsed)
             if f.check == "pptx-media-no-captions"]
    yield "a caption track is read: its part, label, language, and cues", \
        media[1][0].tracks == [("ppt/media/track1.vtt", "Captions", "en", 1)] \
        and media[3][0].tracks == [("ppt/media/track3.vtt", "Captions", "en", None)] \
        and media[5][0].tracks == [], [m[0].tracks for m in media.values() if m]
    yield "a video or audio with captions isn't reported, a byte-order mark before WebVTT's " \
        "signature allowed", not any(w.startswith(("slide 1,", "slide 4,", "slide 7,"))
                                    for w, _ in found) and media[4][0].media == "audio", found
    yield "one whose track is empty, missing, of another kind, or not WebVTT is reported, " \
        "and one with no track as before", sorted(found) == [
            ("slide 2, Media 4", "video, whose caption track holds no captions"),
            ("slide 3, Media 4", "video, whose caption track holds no captions"),
            ("slide 5, Media 4", "video"),
            ("slide 6, Media 4", "video, whose caption track holds no captions"),
            ("slide 6, Media 5", "video, whose caption track holds no captions")], found


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
    # Two prefixes used undeclared, on two elements of one slide: each is
    # found where the parse fails, and both are declared.
    noted = textbox(4, "TextBox 3", ["Noted"], (457200, 1600200, 4000000, 600000)).replace(
        '<p:cNvPr id="4" name="TextBox 3"/>', '<p:cNvPr id="4" name="TextBox 3"><a:extLst><a:ext '
        'uri="{3C9C8C24-9D32-4F4F-9A33-6B5F9B3F0D11}"><p14:modId val="1"/></a:ext></a:extLst>'
        '</p:cNvPr>')
    pair = deck(os.path.join(work, "pair.pptx"), [
        {"shapes": [title(2, "Pair"), noted,
                    table(5, [["Price", "q"], ["1", "2"]], (457200, 3600200, 6000000, 800000),
                          first_row=True, cells={0: [cell("Price"), formula]})]}])
    pd = pptxparse.read(pair)
    out, counts = remediated(work, "pair.pptx", pair)
    yield "two prefixes used undeclared on one slide are both named and both declared", \
        [p for _part, p in pd.malformed] == ["the prefixes p14, a14 used without a namespace "
                                              "declaration"] \
        and counts["repaired"] == 2 and not pptxparse.read(out).malformed, \
        ([p for _part, p in pd.malformed], counts)


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
        {"shapes": [title(2, "Below"), shaped(textbox(4, "Callout 3", ["Says"], box),
                                              "cloudCallout", (0, 150000)),
                    textbox(5, "TextBox 4", ["Under"], (457200, 2930000, 2000000, 400000))]},
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
                               "5", "6" if slide.number in (6, 11) else "4"]
                               for slide in rd.slides},
                           deck="reach")
    refused = sorted(int(k.rsplit("-", 1)[1]) - 255 for k, _why in problems)
    yield "a callout's tail, a line callout's line, a connector's bend, a freeform's points, " \
        "a cloud's trail, and a callout in a group reach past their boxes, a guide's point " \
        "anywhere, and a hidden piece of a group nowhere", \
        refused == [1, 2, 3, 4, 5, 6, 7, 9, 10] and counts["orders"] == 2 \
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


# A master whose title is centered, 44 points, in the headings' font, over
# a yellow fill, its text anchored in the middle with no insets; and a
# layout with no title placeholder, whose heading is a body placeholder
# (idx 10) of 72-point bold.
HEADING_BOX = (457200, 457200, 8229600, 914400)
TITLE_STYLE = ('<a:lvl1pPr algn="ctr"><a:lnSpc><a:spcPct val="90000"/></a:lnSpc><a:spcBef>'
               '<a:spcPct val="0"/></a:spcBef><a:buNone/><a:defRPr sz="4400" kern="1200">'
               '<a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin typeface="+mj-lt"/>'
               '<a:ea typeface="+mj-ea"/><a:cs typeface="+mj-cs"/></a:defRPr></a:lvl1pPr>')
BODY_STYLE = ('<a:lvl1pPr marL="228600" indent="-228600" algn="l"><a:spcBef><a:spcPts val="1000"/>'
              '</a:spcBef><a:buFont typeface="Arial"/><a:buChar char="o"/><a:defRPr sz="2800" '
              'kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill><a:latin '
              'typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr>'
              '</a:lvl1pPr><a:lvl2pPr marL="685800" indent="-228600" algn="l"><a:buChar char="-"/>'
              '<a:defRPr sz="2400"/></a:lvl2pPr>')
THEMED = ('<p:style><a:lnRef idx="2"><a:schemeClr val="accent1"/></a:lnRef><a:fillRef idx="1">'
          '<a:schemeClr val="accent1"/></a:fillRef><a:effectRef idx="0"><a:schemeClr '
          'val="accent1"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="lt1"/>'
          '</a:fontRef></p:style>')


def banner_master():
    title_ph = ('<p:sp>%s<p:spPr>%s<a:solidFill><a:srgbClr val="FFFF00"/></a:solidFill></p:spPr>'
                '<p:txBody><a:bodyPr vert="horz" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr">'
                '<a:normAutofit/></a:bodyPr><a:lstStyle/><a:p/></p:txBody></p:sp>'
                % (nv("sp", 2, "Title Placeholder 1", ph='<p:ph type="title"/>'), xfrm(*TITLE_BOX)))
    body_ph = ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr vert="horz" lIns="91440" '
               'tIns="45720" rIns="91440" bIns="45720"><a:normAutofit/></a:bodyPr><a:lstStyle>'
               '<a:lvl1pPr><a:defRPr sz="3000"/></a:lvl1pPr></a:lstStyle><a:p/></p:txBody></p:sp>'
               % (nv("sp", 3, "Text Placeholder 2", ph='<p:ph type="body" idx="1"/>'),
                  xfrm(*BODY_BOX)))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldMaster %s><p:cSld>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/>%s%s</p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" '
            'bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" '
            'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
            'folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/>'
            '</p:sldLayoutIdLst><p:txStyles><p:titleStyle>%s</p:titleStyle><p:bodyStyle>%s'
            '</p:bodyStyle><p:otherStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr>'
            '<a:lvl1pPr algn="r"><a:defRPr sz="1000"/></a:lvl1pPr></p:otherStyle></p:txStyles>'
            '</p:sldMaster>' % (NS, title_ph, body_ph, TITLE_STYLE, BODY_STYLE))


def banner_layout():
    heading = ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle><a:lvl1pPr marL="0" '
               'indent="0"><a:buNone/><a:defRPr sz="7200" b="1"><a:latin typeface="Avenir Next"/>'
               '</a:defRPr></a:lvl1pPr></a:lstStyle><a:p/></p:txBody></p:sp>'
               % (nv("sp", 2, "Text Placeholder 1", ph='<p:ph type="body" sz="quarter" idx="10"/>'),
                  xfrm(*HEADING_BOX)))
    # A second body placeholder, which a slide's matches by its idx alone.
    subhead = ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle><a:lvl1pPr>'
               '<a:defRPr sz="3600" i="1"/></a:lvl1pPr></a:lstStyle><a:p/></p:txBody></p:sp>'
               % (nv("sp", 4, "Text Placeholder 3", ph='<p:ph type="body" sz="quarter" idx="11"/>'),
                  xfrm(457200, 1371600, 8229600, 457200)))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:sldLayout %s '
            'preserve="1"><p:cSld name="Banner"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
            '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>%s%s%s</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
            % (NS, heading, subhead, content(3, [], box=BODY_BOX)))


def banner_heading(shape_id, text, idx=10):
    """A slide's heading in one of the layout's body placeholders, placed
    by the layout, its formatting all inherited."""
    return ('<p:sp>%s<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" '
            'dirty="0"/><a:t>%s</a:t></a:r></a:p></p:txBody></p:sp>'
            % (nv("sp", shape_id, "Text Placeholder %s" % shape_id,
                  ph='<p:ph type="body" sz="quarter" idx="%d"/>' % idx), esc(text)))


def heading_box(shape_id, text, style=""):
    """A heading in a text box, 40-point bold, inheriting the rest."""
    return ('<p:sp><p:nvSpPr><p:cNvPr id="%s" name="TextBox %s"/><p:cNvSpPr txBox="1"/><p:nvPr/>'
            '</p:nvSpPr><p:spPr>%s<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>%s'
            '<p:txBody><a:bodyPr wrap="square" rtlCol="0"><a:spAutoFit/></a:bodyPr><a:lstStyle/>'
            '<a:p><a:r><a:rPr lang="en-US" sz="4000" b="1" dirty="0"/><a:t>%s</a:t></a:r></a:p>'
            '</p:txBody></p:sp>' % (shape_id, shape_id, xfrm(*HEADING_BOX), style, esc(text)))


def looks(path, part, shape_id):
    """What a shape's paragraphs and runs look like: each one's properties
    as they come out of its chain (pptxtitle.effective()), over the
    defaults, all but its language and proofing marks."""
    with zipfile.ZipFile(path) as z:
        xml = z.read(part).decode("utf-8")
        layout = z.read("ppt/slideLayouts/slideLayout1.xml").decode("utf-8")
        master = z.read("ppt/slideMasters/slideMaster1.xml").decode("utf-8")
        pres = z.read("ppt/presentation.xml").decode("utf-8")
    return looks_of(xml, shape_id, layout, master, pres)


def looks_of(xml, shape_id, layout, master, pres):
    def flat(props, attrs, groups):
        out = dict(attrs)
        out.update(props.attrs)
        out.update({"<%s>" % k: v for k, v in dict(groups, **props.groups).items()})
        for k in ("lang", "dirty", "err", "lvl"):
            out.pop(k, None)
        return out
    return [(flat(p, pptxtitle.P_ATTR_DEFAULTS, pptxtitle.P_GROUP_DEFAULTS),
             [flat(r, pptxtitle.R_ATTR_DEFAULTS, pptxtitle.R_GROUP_DEFAULTS) for r in runs])
            for p, runs in pptxtitle.effective(xml, shape_id, layout, master, pres)]


class CopyTarget:
    """A format: source target, as a run's copies are written for one,
    with settings of its own."""
    name, format = "copies", "source"

    def __init__(self, folder, settings=None):
        self.output_dir = os.path.join(folder, "copies")
        self.settings = settings or {}

    def __getitem__(self, key):
        return self.settings[key]


def case_set_title(work):
    long_text = "A heading that goes on " + "and on " * 30
    path = deck(os.path.join(work, "banner.pptx"), [
        {"shapes": [banner_heading(2, "Market Basics"), content(3, ["Supply", "Demand"])]},
        {"shapes": [heading_box(4, "Chapter One"), content(3, ["Why it matters"])]},
        {"shapes": [banner_heading(2, "Market Basics"), content(3, ["More"])]},
        {"shapes": [banner_heading(2, "Pros & Cons")]},
        {"shapes": [group(5, [textbox(6, "TextBox 6", ["Grouped"], HEADING_BOX)], HEADING_BOX),
                    content(3, ["Under a grouped heading"])]},
        {"shapes": [banner_heading(2, "Twice"), rect(2, "Rectangle 1", (0, 6000000, 10, 10))]},
        {"shapes": [alternate(banner_heading(2, "Both"), banner_heading(2, "Both"))]},
        {"shapes": [heading_box(4, "Styled", THEMED), content(3, ["Under a styled heading"])]},
        {"shapes": [banner_heading(2, "Elasticity")]},
        {"shapes": [title(5, ""), heading_box(4, "Placed")]},
        {"shapes": [banner_heading(2, long_text)]},
        {"shapes": [title(5, "Summary")]},
        {"shapes": [banner_heading(2, "Summary"), content(3, ["Again"])]},
        {"shapes": [banner_heading(2, "Subhead", idx=11)]},
    ], layout=banner_layout(), master=banner_master())
    d = pptxparse.read(path)
    rows = deckrun.untitled_rows("banner.pptx", "banner", d, {})
    key = [rem.slide_key("banner", s) for s in d.slides]
    yield "each slide with no title is drafted from its heading, numbered as a title is when " \
        "an earlier slide has it", \
        [r[1] for r in rows] == ["Market Basics", "Chapter One", "Market Basics (2)",
                                 "Pros & Cons", "", "", "Both", "", "Elasticity", "", "",
                                 "Summary (2)", "Subhead"] \
        and [r[3] for r in rows] == ["TI" if r[1] else "" for r in rows], [r[:4] for r in rows]
    yield "a draft's source names the shape it's drafted from", \
        rows[0][2] == "banner.pptx slide 1, layout Banner, its heading in Text Placeholder 2" \
        and rows[4][2] == "banner.pptx slide 5, layout Banner", (rows[0][2], rows[4][2])
    yield "a shape that takes its look from the theme is read as styled; a text box isn't", \
        d.slides[7].shapes[0].styled and not d.slides[1].shapes[0].styled, ""
    titles = {key[0]: "Market Basics", key[1]: "Chapter One", key[2]: "Market Basics (2)",
              key[3]: "Pros & Cons", key[4]: "Grouped", key[5]: "Twice", key[6]: "Both",
              key[7]: "Styled", key[8]: "Price elasticity", key[9]: "Placed",
              key[10]: "A long slide", key[12]: "Summary (2)", key[13]: "Subhead"}
    out, counts = remediated(work, "banner.pptx", path, titles=titles)
    e = pptxparse.read(out)
    yield "a title that's a heading's text makes it the title in place; any other is added", \
        counts["titles_in_place"] == 7 and counts["titles"] == 6, counts
    yield "each slide reads back with its title, from its heading where it was", \
        [s.title for s in e.slides] == [
            "Market Basics", "Chapter One", "Market Basics (2)", "Pros & Cons", "Grouped",
            "Twice", "Both", "Styled", "Price elasticity", "Placed", "A long slide", "Summary",
            "Summary (2)", "Subhead"] \
        and [(e.slides[n].title_shape.id, e.slides[n].shapes.index(e.slides[n].title_shape))
             for n in (0, 1, 2, 3, 6, 12)] == [("2", 0), ("4", 0), ("2", 0), ("2", 0), ("2", 0),
                                                ("2", 0)], [s.title for s in e.slides]
    first = read_part(out, "ppt/slides/slide1.xml")
    sp = first[first.find('<p:cNvPr id="2"'):]
    yield "a placeholder heading becomes a title that matches no placeholder of the layout", \
        '<p:nvPr><p:ph type="title" idx="4294967295"/></p:nvPr>' in sp and 'type="body"' not in sp, \
        sp[:300]
    yield "what it inherited is written into its own list style, and what a title would " \
        "inherit and it didn't, as its default", \
        '<a:lvl1pPr marL="0" indent="0" algn="l"><a:lnSpc><a:spcPct val="100000"/></a:lnSpc>' \
        '<a:spcBef><a:spcPts val="1000"/></a:spcBef><a:buFont typeface="Arial"/><a:buNone/>' \
        '<a:defRPr lang="en-US" sz="7200" b="1" kern="1200"><a:solidFill><a:schemeClr ' \
        'val="tx1"/></a:solidFill><a:latin typeface="Avenir Next"/><a:ea typeface="+mn-ea"/>' \
        '<a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr><a:lvl2pPr marL="685800" ' \
        'indent="-228600" algn="l">' in sp, re.findall(r"<a:lstStyle>.{0,700}", sp)
    yield "and its text body's and shape's properties: its own, the layout's and master's, and " \
        "the defaults of what a title's have", \
        '<p:spPr>%s<a:noFill/></p:spPr><p:txBody><a:bodyPr vert="horz" lIns="91440" ' \
        'tIns="45720" rIns="91440" bIns="45720" anchor="t"><a:normAutofit/></a:bodyPr>' \
        % xfrm(*HEADING_BOX) in sp, sp[sp.find("<p:spPr"):][:400]
    second = read_part(out, "ppt/slides/slide2.xml")
    box = second[second.find('<p:cNvPr id="4"'):]
    yield "a text box's heading becomes a title too, locked as PowerPoint locks it", \
        '<p:cNvSpPr txBox="1"><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title" ' \
        'idx="4294967295"/></p:nvPr>' in box, box[:300]
    yield "inheriting what the presentation's default text style gives it, and the defaults of " \
        "what a title's chain gives", \
        '<a:bodyPr vert="horz" wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" ' \
        'rtlCol="0" anchor="t"><a:spAutoFit/></a:bodyPr><a:lstStyle><a:lvl1pPr algn="l">' \
        '<a:lnSpc><a:spcPct val="100000"/></a:lnSpc><a:spcBef><a:spcPts val="0"/></a:spcBef>' \
        '<a:buNone/><a:defRPr lang="en-US" sz="1800" kern="0"><a:solidFill><a:schemeClr ' \
        'val="tx1"/></a:solidFill><a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs ' \
        'typeface="+mn-cs"/></a:defRPr></a:lvl1pPr>' in box \
        and '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>' in box, \
        box[box.find("<p:spPr"):][:700]
    sub = read_part(out, "ppt/slides/slide14.xml")
    yield "a placeholder takes what it inherited from the layout's of its idx, not another of " \
        "its type", '<a:lvl1pPr marL="228600" indent="-228600" algn="l"><a:lnSpc><a:spcPct ' \
        'val="100000"/></a:lnSpc><a:spcBef><a:spcPts val="1000"/></a:spcBef><a:buFont ' \
        'typeface="Arial"/><a:buChar char="o"/><a:defRPr lang="en-US" sz="3600" i="1" ' \
        'kern="1200">' in sub, re.findall(r"<a:lstStyle>.{0,400}", sub)
    same = [(n, looks(path, "ppt/slides/slide%d.xml" % n, sid) == looks(
        out, "ppt/slides/slide%d.xml" % n, sid)) for n, sid in ((1, "2"), (2, "4"), (4, "2"),
                                                              (7, "2"), (14, "2"))]
    before = looks(path, "ppt/slides/slide1.xml", "2")
    yield "every paragraph and run looks as it did", \
        all(ok for _n, ok in same) and before[0][0]["algn"] == "l" \
        and before[0][1][0]["sz"] == "7200" and before[0][1][0]["b"] == "1", same
    # The placeholder made a title and nothing else: the master's title
    # style shows through, as it would in PowerPoint.
    with zipfile.ZipFile(path) as z:
        parts = [z.read(p).decode("utf-8") for p in (
            "ppt/slides/slide1.xml", "ppt/slideLayouts/slideLayout1.xml",
            "ppt/slideMasters/slideMaster1.xml", "ppt/presentation.xml")]
    bare = parts[0].replace('<p:ph type="body" sz="quarter" idx="10"/>', pptxtitle.TITLE_PH)
    shown = looks_of(bare, "2", *parts[1:])
    yield "where a placeholder made a title and nothing more would look like the master's title", \
        shown[0][0]["algn"] == "ctr" and shown[0][1][0]["sz"] == "4400" \
        and shown[0][1][0]["<latin>"] == '<a:latin typeface="+mj-lt"/>', shown[0]
    third = read_part(out, "ppt/slides/slide3.xml")
    yield "a number added to a heading's text goes after its last run, in that run's formatting", \
        '<a:t>Market Basics</a:t></a:r><a:r><a:rPr lang="en-US" dirty="0"/><a:t> (2)</a:t></a:r>' \
        in third and pptxtitle.TITLE_PH in third, third[third.find("<a:t>"):][:200]
    yield "a heading with an ampersand is matched by its text and stays escaped", \
        "<a:t>Pros &amp; Cons</a:t>" in read_part(out, "ppt/slides/slide4.xml"), ""
    yield "a heading in AlternateContent is made the title in its Choice and its Fallback", \
        read_part(out, "ppt/slides/slide7.xml").count(pptxtitle.TITLE_PH) == 2, ""
    ninth = read_part(out, "ppt/slides/slide9.xml")
    heading = re.search(r"<p:sp><p:nvSpPr><p:cNvPr id=\"2\".*?</p:sp>",
                        read_part(path, "ppt/slides/slide9.xml")).group(0)
    yield "a title that isn't a heading's text is added above the slide, the heading left as " \
        "it was", heading in ninth and e.slides[8].shapes[0].is_title \
        and e.slides[8].shapes[0].box.y < 0, [s.name for s in e.slides[8].shapes]
    yield "and so is one for a heading in a group, a heading whose id repeats, a styled one, " \
        "and one on a slide with an empty title placeholder, which takes it", \
        all(e.slides[n].title_shape.box.y < 0 for n in (4, 5, 7, 9, 10)) \
        and e.slides[9].title_shape.id == "5" \
        and pptxtitle.TITLE_PH not in read_part(out, "ppt/slides/slide8.xml"), \
        [(n, e.slides[n].title_shape.id, e.slides[n].title_shape.box) for n in (4, 5, 7, 9, 10)]
    found = pptxcheck.check(e)
    with zipfile.ZipFile(out) as z:
        parses = all(ET.fromstring(z.read(n)) is not None for n in z.namelist()
                     if n.endswith(".xml"))
    yield "the copy's slides all have titles, none of them another's, and every part parses", \
        not {"pptx-slide-no-title", "pptx-duplicate-title"} & set(checks_of(found)) and parses, \
        checks_of(found)
    # A run's report: the drafts, and what a drafted title does.
    folder = os.path.join(work, "banner-run")
    os.makedirs(folder)
    shutil.copy(path, folder)
    said = []
    deckrun.run(folder, ["banner.pptx"], [],
                {"slide_titles": os.path.join(folder, "slide-titles.csv"),
                 "image_alt": os.path.join(folder, "image-alt.csv"),
                 "table_headers": os.path.join(folder, "table-headers.csv")},
                {k: os.path.join(folder, v) for k, v in (
                    ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
                    ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"))},
                check_only=True, say=said.append)
    yield "a run writes the drafts and says what a drafted title does", \
        [r[1] for r in rows_of(os.path.join(folder, "s.csv"))] == [r[1] for r in rows] \
        and any("A Title drafted from a slide's heading makes the heading its title, in place, " \
                "as PowerPoint's Set as Slide Title does" in line for line in said), said[-4:]
    # A slide the sidecar decides isn't drafted, and its title counts.
    decided = deckrun.untitled_rows("banner.pptx", "banner", d, {key[0]: "Market Basics"})
    yield "a slide the sidecar decides gets no row, and a later one is numbered after it", \
        [r[1] for r in decided][:2] == ["Chapter One", "Market Basics (2)"], decided[:2]
    # A copy's run says how many titles were made in place.
    with open(os.path.join(folder, "slide-titles.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.TITLE_COLUMNS] + [[k, v] for k, v in titles.items()])
    said = []
    deckrun.run(folder, ["banner.pptx"], [CopyTarget(folder)],
                {"slide_titles": os.path.join(folder, "slide-titles.csv"),
                 "image_alt": os.path.join(folder, "image-alt.csv"),
                 "table_headers": os.path.join(folder, "table-headers.csv")},
                {k: os.path.join(folder, v) for k, v in (
                    ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
                    ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"))},
                say=said.append)
    yield "a run's copies say how many headings were made titles, and how many titles added", \
        any("7 slide(s) given the heading they show as their title, in place, 6 title(s) added " \
            "above their slides" in line for line in said), said[-3:]
    # set_as_title() itself refuses a shape in a group, one styled by the
    # theme, and a title.
    with zipfile.ZipFile(path) as z:
        inherited = [z.read(p).decode("utf-8") for p in (
            "ppt/slideLayouts/slideLayout1.xml", "ppt/slideMasters/slideMaster1.xml",
            "ppt/presentation.xml")]
        refused = [pptxtitle.set_as_title(z.read("ppt/slides/slide%d.xml" % n).decode("utf-8"),
                                          sid, *inherited)[1]
                   for n, sid in ((5, "6"), (8, "4"), (12, "5"))]
    yield "a shape in a group, one the theme styles, and a title aren't made titles", \
        refused == [0, 0, 0], refused


AVENIR, ARIAL, GEORGIA = "020B0503020202020204", "020B0604020202020204", "02040502050405020303"


def eot(family, fstype, panose, style="regular"):
    """An Embedded OpenType file's header as PowerPoint writes one, version
    2.2, and no font data after it: what a deck's fonts are read from."""
    def name(text):
        data = text.encode("utf-16-le")
        return struct.pack("<HH", 0, len(data)) + data
    data = (struct.pack("<IIII", 0, 0, 0x00020002, 0x5) + bytes.fromhex(panose)
            + struct.pack("<BBIHH", 1, 0, 400, fstype, 0x504C) + bytes(44)
            + name(family) + name(style) + name("Version 1.0") + name(family))
    return struct.pack("<I", len(data)) + data[4:]


def embed_fonts(path, fonts, embedding=True, override=False):
    """A deck with fonts embedded as PowerPoint embeds them: for each
    (typeface, fsType, PANOSE, styles), an entry in the presentation's
    list, a file for each style in ppt/fonts/, and a relationship to each;
    embedTrueTypeFonts on when embedding; override: the first file's
    content type given by name too, not only by its extension."""
    with zipfile.ZipFile(path) as z:
        members = [(i, z.read(i.filename)) for i in z.infolist()]
    files, entries, added = [], [], []
    for typeface, fstype, panose, styles in fonts:
        refs = []
        for n, style in enumerate(styles):
            # one license for every style, or one each; None, a file that
            # isn't EOT at all
            each = fstype[n] if isinstance(fstype, tuple) else fstype
            files.append(("ppt/fonts/font%d.fntdata" % (len(files) + 1),
                          eot(typeface, each, panose, style) if each is not None
                          else b"\x00\x01\x00\x00" + b" a TrueType font, not EOT" * 8))
            added.append('<Relationship Id="rIdF%d" Type="%sfont" Target="fonts/font%d.fntdata"/>'
                         % (len(files), REL, len(files)))
            refs.append('<p:%s r:id="rIdF%d"/>' % (style, len(files)))
        entries.append('<p:embeddedFont><p:font typeface="%s" panose="%s" pitchFamily="34" '
                       'charset="0"/>%s</p:embeddedFont>' % (esc(typeface), panose, "".join(refs)))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            text = data.decode("utf-8") if info.filename.endswith((".xml", ".rels")) else None
            if info.filename == "ppt/presentation.xml":
                if entries:
                    text = text.replace('<p:notesSz cx="6858000" cy="9144000"/>',
                                        '<p:notesSz cx="6858000" cy="9144000"/><p:embeddedFontLst>'
                                        '%s</p:embeddedFontLst>' % "".join(entries))
                if embedding:
                    text = text.replace("<p:presentation %s>" % NS, '<p:presentation %s '
                                        'embedTrueTypeFonts="1" saveSubsetFonts="1">' % NS)
            elif info.filename == "ppt/_rels/presentation.xml.rels":
                text = text.replace("</Relationships>", "".join(added) + "</Relationships>")
            elif info.filename == "[Content_Types].xml" and files:
                text = text.replace('<Default Extension="png"', '<Default Extension="fntdata" '
                                    'ContentType="application/x-fontdata"/><Default Extension="png"')
                if override:
                    text = text.replace("</Types>", '<Override PartName="/%s" ContentType="'
                                        'application/x-fontdata"/></Types>' % files[0][0])
            z.writestr(info, text.encode("utf-8") if text is not None else data)
        for part, data in files:
            z.writestr(part, data)
    return path


def font_box(shape_id, text, typeface, panose=None, y=1600200):
    """A text box whose run names a typeface, as its Latin and complex
    script font, with its PANOSE when given."""
    traits = ' panose="%s" pitchFamily="34" charset="0"' % panose if panose else ""
    return ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr '
            'lang="en-US"><a:latin typeface="%s"%s/><a:cs typeface="%s"%s/></a:rPr><a:t>%s</a:t>'
            '</a:r></a:p></p:txBody></p:sp>'
            % (nv("sp", shape_id, "TextBox %s" % shape_id), xfrm(457200, y, 8000000, 500000),
               esc(typeface), traits, esc(typeface), traits, esc(text)))


def font_bullet(shape_id, typeface, panose):
    """A text box whose bullet is in a typeface."""
    return ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:buFont '
            'typeface="%s" panose="%s" pitchFamily="34" charset="0"/><a:buChar char="-"/></a:pPr>'
            '<a:r><a:rPr lang="en-US"/><a:t>A point</a:t></a:r></a:p></p:txBody></p:sp>'
            % (nv("sp", shape_id, "TextBox %s" % shape_id), xfrm(457200, 3000000, 8000000, 500000),
               esc(typeface), panose))


def case_fonts(work):
    header = pptxfonts.eot_header(eot("Avenir Next", 4, AVENIR))
    yield "an embedded font's family, license, and PANOSE are read from its EOT header", \
        header == ("Avenir Next", 4, AVENIR), header
    yield "a license restricts a deck that embeds the font unless it lets the font be edited", \
        [pptxfonts.restricted(x) for x in (0, 2, 4, 6, 8, 12, 0x104)] \
        == [False, True, True, True, False, False, True], ""
    yield "PANOSE puts a sans nearer a sans than a serif, and a font of unknown look nowhere", \
        pptxfonts.distance(AVENIR, ARIAL) < pptxfonts.distance(AVENIR, GEORGIA) \
        and pptxfonts.distance(AVENIR, "00000500000000000000") is None, ""
    folder = os.path.join(work, "fonts")
    os.makedirs(folder)
    slide = [title(2, "Fonts"), font_box(6, "Plain", "Arial", y=1000000),
             font_box(3, "Body", "Avenir Next", AVENIR),
             font_box(4, "Other", "Arial", ARIAL, y=2200000),
             font_box(5, "Serif", "Georgia", GEORGIA, y=2800000)]
    embeds = embed_fonts(deck(os.path.join(folder, "embeds.pptx"), [
        {"shapes": slide}, {"shapes": [title(2, "Points"), font_bullet(3, "Avenir Next", AVENIR)]}]),
        [("Avenir Next", 4, AVENIR, ("regular", "bold")), ("Georgia", 8, GEORGIA, ("regular",))],
        override=True)
    uses = embed_fonts(deck(os.path.join(folder, "uses.pptx"), [{"shapes": slide}]),
                       [("Georgia", 8, GEORGIA, ("regular",))])
    editable = embed_fonts(deck(os.path.join(folder, "editable.pptx"), [{"shapes": slide}]),
                           [("Avenir Next", 8, AVENIR, ("regular",))])
    loose = deck(os.path.join(folder, "loose.pptx"), [{"shapes": slide}])
    d = pptxparse.read(embeds)
    yield "a deck's fonts: what it embeds, under what license, and how often it names each", \
        dict(d.fonts.restricted()) == {"Avenir Next": 4} and d.fonts.used["Avenir Next"] == 3 \
        and d.fonts.embedding and not d.fonts.embedded["Georgia"].restricted \
        and d.fonts.traits["Arial"] == {"panose": ARIAL, "pitchFamily": "34", "charset": "0"} \
        and pptxfonts.nearest(d.fonts, "Avenir Next") == "Arial", \
        (dict(d.fonts.restricted()), d.fonts.used, d.fonts.traits)
    # The most restrictive style's license is the font's, a file that isn't
    # EOT has none, and the nearest font is never a restricted one, nor
    # another kind of font, nor one with another serif style.
    mixed = pptxparse.read(embed_fonts(deck(os.path.join(work, "mixed.pptx"), [{"shapes": slide}]),
                                       [("Avenir Next", (8, 4), AVENIR, ("regular", "bold")),
                                        ("Georgia", (None,), GEORGIA, ("regular",))]))
    near = pptxparse.read(embed_fonts(deck(os.path.join(work, "near.pptx"), [{"shapes": [
        title(2, "Near"), font_box(3, "Body", "Avenir Next", AVENIR),
        font_box(4, "Script", "Brush", "030B0503020202020204", y=2200000),
        font_box(5, "Serif", "Serifa", "02020503020202020204", y=2800000),
        font_box(6, "Close", "Futura", "020B0502020202020204", y=3400000),
        font_box(7, "Other", "Arial", ARIAL, y=4000000)]}]),
        [("Futura", 4, "020B0502020202020204", ("regular",))]))
    yield "a font's most restrictive file is its license, and the nearest font is the same kind, " \
        "then the same serif style, and never a restricted one", \
        dict(mixed.fonts.restricted()) == {"Avenir Next": 4} \
        and mixed.fonts.embedded["Georgia"].fstype is None \
        and pptxfonts.nearest(near.fonts, "Avenir Next") == "Arial", \
        (dict(mixed.fonts.restricted()), pptxfonts.nearest(near.fonts, "Avenir Next"))
    found = {os.path.basename(p): [(f.check, f.detail) for f in pptxcheck.check(
        pptxparse.read(p), restricted={"Avenir Next": 4}) if f.check.startswith("pptx-font")]
        for p in (embeds, uses, editable, loose)}
    yield "a deck that embeds a font for preview and print only is found, and so is one that " \
        "uses it without embedding it, set to embed its fonts; one that embeds it editable, or " \
        "doesn't embed fonts, isn't", found == {
            "embeds.pptx": [("pptx-font-restricted", "Avenir Next, embedded for preview and print "
                             "only: PowerPoint opens the deck read-only where Avenir Next isn't "
                             "installed")],
            "uses.pptx": [("pptx-font-unembedded", "Avenir Next, which another deck embeds for "
                           "preview and print only, used without being embedded: the deck is set "
                           "to embed its fonts, so PowerPoint won't save it where Avenir Next "
                           "isn't installed")],
            "editable.pptx": [], "loose.pptx": []}, found
    replaced, problems = [], []
    out = os.path.join(work, "out", "embeds.pptx")
    counts = rem.remediate(embeds, out, fonts={"Avenir Next": None}, replaced=replaced,
                           problems=problems)
    first = read_part(out, "ppt/slides/slide1.xml")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        pres, rels = z.read("ppt/presentation.xml").decode(), \
            z.read("ppt/_rels/presentation.xml.rels").decode()
        types = z.read("[Content_Types].xml").decode()
        parses = all(ET.fromstring(z.read(n)) is not None for n in names
                     if n.endswith((".xml", ".rels")))
    yield "a restricted font is replaced with the nearest the deck uses, its PANOSE, pitch, and " \
        "character set with it, bullets too", \
        replaced == [("Avenir Next", "Arial", 3, True)] and counts["fonts_replaced"] == 1 \
        and '<a:latin typeface="Arial" panose="%s" pitchFamily="34" charset="0"/><a:cs ' \
        'typeface="Arial" panose="%s" pitchFamily="34" charset="0"/></a:rPr><a:t>Body' \
        % (ARIAL, ARIAL) in first and '<a:buFont typeface="Arial" panose="%s"' % ARIAL \
        in read_part(out, "ppt/slides/slide2.xml") and "Avenir" not in first, (replaced, counts)
    yield "and its embedded files are taken out, with their relationships, list entry, and " \
        "content type, the deck's other font kept", \
        counts["fonts_unembedded"] == 1 and "ppt/fonts/font1.fntdata" not in names \
        and "ppt/fonts/font2.fntdata" not in names and "ppt/fonts/font3.fntdata" in names \
        and "rIdF1" not in rels and "rIdF2" not in rels and 'Id="rIdF3"' in rels \
        and re.findall(r'<p:font typeface="([^"]+)"', pres) == ["Georgia"] \
        and "font1.fntdata" not in types and 'Extension="fntdata"' in types and parses, \
        (names, re.findall(r"<p:embeddedFontLst>.*</p:embeddedFontLst>", pres))
    copy = pptxparse.read(out)
    yield "the copy's check finds no restricted font", \
        not [f for f in pptxcheck.check(copy, restricted={"Avenir Next": 4})
             if f.check.startswith("pptx-font")] and not copy.fonts.restricted(), ""
    named = rem.remediate(embeds, os.path.join(work, "out", "named.pptx"),
                          fonts={"Avenir Next": "Georgia"}, replaced=replaced)
    yield "a replacement fonts.replacements names is used in place of the nearest", \
        replaced[-1] == ("Avenir Next", "Georgia", 3, True) and named["fonts_replaced"] == 1 \
        and '<a:latin typeface="Georgia" panose="%s"' % GEORGIA \
        in read_part(os.path.join(work, "out", "named.pptx"), "ppt/slides/slide1.xml"), replaced
    alone = embed_fonts(deck(os.path.join(work, "alone.pptx"), [{"shapes": [
        title(2, "Alone"), font_box(3, "Body", "Avenir Next"),
        font_box(4, "Other", "Montserrat", "00000500000000000000", y=2200000)]}]),
        [("Avenir Next", 4, "00000000000000000000", ("regular",))])
    problems = []
    kept = rem.remediate(alone, os.path.join(work, "out", "alone.pptx"),
                         fonts={"Avenir Next": None}, problems=problems)
    yield "a font with nothing near it is left, and the copy says to name one", \
        kept["fonts_replaced"] == 0 and problems == [
            ("alone", "Avenir Next isn't replaced: no font the deck uses is near it by PANOSE; "
                      "fonts.replacements can name one")] \
        and "ppt/fonts/font1.fntdata" in zipfile.ZipFile(
            os.path.join(work, "out", "alone.pptx")).namelist(), problems
    both = []
    rem.remediate(embeds, os.path.join(work, "out", "both.pptx"),
                  fonts={"Avenir Next": None, "Arial": "Helvetica"}, replaced=both)
    none = []
    clean = rem.remediate(clean_deck(os.path.join(work, "clean.pptx")),
                          os.path.join(work, "out", "clean.pptx"),
                          fonts={"Avenir Next": "Arial"}, replaced=none)
    yield "the nearest font isn't one being replaced itself, and a deck without the font is " \
        "left alone", both == [("Avenir Next", "Georgia", 3, True), ("Arial", "Helvetica", 4,
                                                                      False)] \
        and none == [] and clean["fonts_replaced"] == 0, (both, none)
    styled = deck(os.path.join(work, "styled.pptx"), [{"shapes": slide}])
    with zipfile.ZipFile(styled) as z:
        members = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(styled, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            if info.filename == "ppt/presentation.xml":
                data = data.replace(b'<a:lvl1pPr><a:defRPr sz="1800"/>',
                                    b'<a:lvl1pPr><a:defRPr sz="1800"><a:latin typeface="Avenir '
                                    b'Next" panose="020B0503020202020204"/></a:defRPr>')
            z.writestr(info, data)
    told = []
    rem.remediate(styled, os.path.join(work, "out", "styled.pptx"), fonts={"Avenir Next": None},
                  replaced=told)
    yield "a typeface the presentation's default text style names counts, and is replaced", \
        pptxparse.read(styled).fonts.used["Avenir Next"] == 3 and told == [
            ("Avenir Next", "Arial", 3, False)] and "Avenir" not in read_part(
            os.path.join(work, "out", "styled.pptx"), "ppt/presentation.xml"), told
    only = embed_fonts(deck(os.path.join(work, "only.pptx"), [{"shapes": slide}]),
                       [("Avenir Next", 4, AVENIR, ("regular",))])
    rem.remediate(only, os.path.join(work, "out", "only.pptx"), fonts={"Avenir Next": None})
    fish = deck(os.path.join(work, "fish.pptx"), [{"shapes": [
        title(2, "Fish"), font_box(3, "Body", "Fish & Chips", AVENIR)]}])
    rem.remediate(fish, os.path.join(work, "out", "fish.pptx"), fonts={"Fish & Chips": "Q&A Sans"})
    fished = read_part(os.path.join(work, "out", "fish.pptx"), "ppt/slides/slide1.xml")
    yield "a list left with no font goes, and names are matched and written escaped", \
        "embeddedFontLst" not in read_part(os.path.join(work, "out", "only.pptx"),
                                           "ppt/presentation.xml") \
        and '<a:latin typeface="Q&amp;A Sans"/>' in fished \
        and pptxparse.read(os.path.join(work, "out", "fish.pptx")).fonts.used["Q&A Sans"] == 2, \
        fished[fished.find("<a:rPr"):][:200]
    # A run: what it says of the font, then a copy with it replaced.
    said = []
    paths = {"slide_titles": os.path.join(folder, "slide-titles.csv"),
             "image_alt": os.path.join(folder, "image-alt.csv"),
             "table_headers": os.path.join(folder, "table-headers.csv")}
    reports = {k: os.path.join(folder, v) for k, v in (
        ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
        ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"),
        ("output_check", "output-check.csv"))}
    decks = ["editable.pptx", "embeds.pptx", "loose.pptx", "uses.pptx"]
    deckrun.run(folder, decks, [], paths, reports, check_only=True, say=said.append)
    yield "a run says how many decks use a restricted font, and how, and names the setting", \
        any("WARNING: 3 of 4 deck(s) use the restricted font Avenir Next, whose license lets a "
            "deck embed it for preview and print only: 1 embed it, so PowerPoint opens them "
            "read-only where Avenir Next isn't installed; 1 use it without embedding it, set to "
            "embed their fonts, so PowerPoint won't save them there; 1 use it without embedding "
            "it, so it's shown in another font there. Set fonts.restricted: replace for the "
            "copies to use another font in its place: the nearest each deck uses (Arial), or "
            "the one fonts.replacements names." == line for line in said), said
    said = []
    deckrun.run(folder, decks, [CopyTarget(folder)], paths, reports, say=said.append)
    yield "by default the copies keep the font, and their check names it", \
        sorted(r[1] for r in rows_of(reports["output_check"]) if r[1].startswith("pptx-font")) \
        == ["pptx-font-restricted", "pptx-font-unembedded"], said
    said = []
    deckrun.run(folder, decks, [CopyTarget(folder, {"fonts.restricted": "replace"})], paths,
                reports, say=said.append)
    yield "with fonts.restricted: replace, the copies use another font, and their check is clear", \
        any("copies: Avenir Next replaced with Arial in 3 deck(s), 7 place(s) in all, and its "
            "embedded files taken out of 1." == line for line in said) \
        and any("copies's copies use another font in its place" in line for line in said) \
        and not [r for r in rows_of(reports["output_check"]) if r[1].startswith("pptx-font")], \
        said
    said = []
    deckrun.run(folder, decks, [CopyTarget(folder, {"fonts.replacements": {
        "Avenir Next": "Georgia"}})], paths, reports, say=said.append)
    yield "fonts.replacements replaces what it names, in every deck that uses it", \
        any("copies: Avenir Next replaced with Georgia in 4 deck(s), 9 place(s) in all, and its "
            "embedded files taken out of 2." == line for line in said), said
    said = []
    deckrun.run(folder, decks, [CopyTarget(folder, {"fonts.replacements": ["Avenir Next"]})],
                paths, reports, check_only=False, say=said.append)
    yield "fonts.replacements that isn't a map is left out, and the run says so", \
        any("fonts.replacements is a map of fonts" in line for line in said) \
        and not any("replaced with" in line for line in said), said


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


def display_paragraph(shape_id, *bodies):
    """A text box holding a display paragraph of several equations, an
    m:oMathPara of an m:oMath each, as equation() writes one."""
    para = ('<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
            + "".join("<m:oMath>%s</m:oMath>" % body for body in bodies) + "</m:oMathPara>")
    box = ('<p:sp>%s<p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a14:m>%s'
           '</a14:m></a:p></p:txBody></p:sp>' % (nv("sp", shape_id, "TextBox %d" % shape_id),
                                                 xfrm(457200, 1600200, 4000000, 600000), para))
    return ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/'
            '2006"><mc:Choice xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" '
            'Requires="a14">%s</mc:Choice><mc:Fallback>%s</mc:Fallback></mc:AlternateContent>'
            % (box, rect(shape_id, "TextBox %d" % shape_id, (457200, 1600200, 4000000, 600000))))


# Two bars written as upper limits, a macron's and an en dash's, as
# OpenStax's decks have them, and an en dash and the micro sign.
BAR_OMML = ('<m:limUpp><m:e><m:r><m:t>x</m:t></m:r></m:e><m:lim><m:r><m:t>¯</m:t></m:r>'
            '</m:lim></m:limUpp><m:r><m:t>–µ</m:t></m:r><m:limUpp><m:e><m:r><m:t>y</m:t>'
            '</m:r></m:e><m:lim><m:r><m:t>–</m:t></m:r></m:lim></m:limUpp>')


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
    yield "an equation gets the characters it means, PowerPoint's as Word's, but a bar stays " \
        "an upper limit, NVDA reading only characters: a macron's limit kept, a macron for " \
        "an en dash's, a minus for an en dash, mu for the micro sign", \
        two.count("<m:limUpp>") == 2 and two.count("<m:t>¯</m:t>") == 2 \
        and "<m:bar>" not in two and "<m:acc>" not in two and "–" not in two \
        and "<m:t>−μ</m:t>" in two \
        and counts["equations_repaired"] == 1 and counts["equation_characters"] == 3 \
        and ET.fromstring(two.encode()) is not None, two[two.find("<a14:m>"):][:600]
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


# A fraction with an en dash and the micro sign in it, a root that needs
# nothing, and the increment sign, which looks like Delta.
Z_OMML = ('<m:r><m:t>z=</m:t></m:r><m:f><m:num><m:r><m:t>x–µ</m:t></m:r></m:num><m:den><m:r>'
          '<m:t>σ</m:t></m:r></m:den></m:f>')
ROOT_OMML = ('<m:r><m:t>σ=</m:t></m:r><m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/>'
             '<m:e><m:r><m:t>npq</m:t></m:r></m:e></m:rad>')
DELTA_OMML = '<m:r><m:t>∆x=2</m:t></m:r>'
# Z_OMML in the TeX Pandoc's Word reader reads, as math-repaired.csv names it.
Z_TEX = "z = \\frac{x–µ}{\\sigma}"


def omml(body):
    return ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">%s'
            '</m:oMath>' % body)


def mr(text):
    return '<m:r><a:rPr lang="en-US" i="1"/><m:t>%s</m:t></m:r>' % text


def case_math_keep(work):
    """math-keep.csv for decks: an equation named by its TeX, as
    math-repaired.csv shows it, as a book's are, or by the line it's
    written out in, as the report showed it before, kept as it was."""
    written = {
        "a fraction, its parts in parentheses": (
            '<m:f><m:fPr><m:ctrlPr/></m:fPr><m:num>%s</m:num><m:den>%s</m:den></m:f>'
            % (mr("a+b"), mr("2")), "(a+b)/2"),
        "scripts": ('<m:sSubSup><m:e>%s</m:e><m:sub>%s</m:sub><m:sup>%s</m:sup></m:sSubSup>'
                    % (mr("x"), mr("i"), mr("2")), "x_i^2"),
        "a root, its degree hidden": (ROOT_OMML, "σ=√(npq)"),
        "a cube root": ('<m:rad><m:deg>%s</m:deg><m:e>%s</m:e></m:rad>' % (mr("3"), mr("x")),
                        "∛x"),
        "another root": ('<m:rad><m:deg>%s</m:deg><m:e>%s</m:e></m:rad>' % (mr("n"), mr("x")),
                         "√(n&x)"),
        "a root whose degree is hidden, though it has one": (
            '<m:rad><m:radPr><m:degHide/></m:radPr><m:deg>%s</m:deg><m:e>%s</m:e>'
            '</m:rad>' % (mr("3"), mr("x")), "√x"),
        "a sum": ('<m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr><m:sub>%s</m:sub><m:sup>%s'
                  '</m:sup><m:e>%s</m:e></m:nary>' % (mr("i=1"), mr("n"), mr("x")), "∑_(i=1)^n▒x"),
        "an accent, Office's circumflex where it names none": (
            '<m:acc><m:accPr/><m:e>%s</m:e></m:acc>' % mr("y"), "y" + chr(0x302)),
        "delimiters, their own parentheses kept": (
            '<m:sSup><m:e><m:d><m:dPr><m:ctrlPr/></m:dPr><m:e>%s</m:e></m:d></m:e><m:sup>%s'
            '</m:sup></m:sSup>' % (mr("a+b"), mr("2")), "(a+b)^2"),
        "a delimiter's separator": (
            '<m:d><m:dPr><m:sepChr m:val=","/></m:dPr><m:e>%s</m:e><m:e>%s</m:e></m:d>'
            % (mr("a"), mr("b")), "(a,b)"),
        "a function": ('<m:func><m:fName>%s</m:fName><m:e>%s</m:e></m:func>'
                       % (mr("log"), mr("2x")), "log(2x)"),
        "a bar over": ('<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>%s</m:e></m:bar>'
                       % mr("x"), "¯x"),
        "a matrix": ('<m:m><m:mr><m:e>%s</m:e><m:e>%s</m:e></m:mr><m:mr><m:e>%s</m:e><m:e>%s'
                     '</m:e></m:mr></m:m>' % (mr("a"), mr("b"), mr("c"), mr("d")), "■(a&b@c&d)"),
        "limits": (BAR_OMML, "x┴¯–µy┴–"),
        "one that isn't XML alone": ('<m:r><x:rPr/><m:t>q</m:t></m:r>', "q"),
    }
    for name, (body, line) in written.items():
        got = rem.equation_text(omml(body))
        yield "an equation written out in one line: %s" % name, got == line, (got, line)
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    deck(os.path.join(folder, "maths.pptx"), [
        {"shapes": [title(2, "Means"), equation(4, BAR_OMML)]},
        {"shapes": [title(2, "Scores"), equation(4, Z_OMML)]},
        {"shapes": [title(2, "Spread"), equation(4, ROOT_OMML)]},
        {"shapes": [title(2, "Change"), equation(4, DELTA_OMML)]}])
    deck(os.path.join(folder, "other.pptx"),
         [{"shapes": [title(2, "Scores"), equation(4, Z_OMML)]}])
    reports = {k: os.path.join(folder, v) for k, v in (
        ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
        ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"),
        ("output_check", "output-check.csv"), ("math_repaired", "math-repaired.csv"))}
    paths = {k: os.path.join(folder, v) for k, v in (
        ("image_alt", "image-alt.csv"), ("table_headers", "table-headers.csv"),
        ("slide_titles", "slide-titles.csv"), ("math_keep", "math-keep.csv"))}

    def target(on=True):
        return type("Target", (), {"format": "source", "name": "fixed",
                                   "output_dir": os.path.join(folder, "fixed"),
                                   "__getitem__": lambda self, key:
                                   on and key == "math.repair_equations"})()

    def run(on=True):
        said = []
        code = deckrun.run(folder, ["maths.pptx", "other.pptx"], [target(on)], paths, reports,
                           say=said.append)
        return code, said
    code, said = run()
    first = rows_of(reports["math_repaired"])
    yield "a run's math repairs are a report, a book's columns, each equation in the TeX " \
        "Pandoc's Word reader reads, as a book's are, once a deck, and the run says nothing " \
        "of a line, no row being written out in one", code == 0 and first == [
            ["equation", "maths", "\\overset{¯}{x}–µ\\overset{–}{y}",
             "\\overset{¯}{x} - \\mu\\overset{¯}{y}"],
            ["equation", "maths", Z_TEX, "z = \\frac{x - \\mu}{\\sigma}"],
            ["equation", "maths", "\\mathrm{\\Delta}x = 2", "\\Delta x = 2"],
            ["equation", "other", Z_TEX, "z = \\frac{x - \\mu}{\\sigma}"]] \
        and "Wrote %s (4 math repair(s))." % reports["math_repaired"] in said \
        and not any("Fill in the second column" in s and "math" in s for s in said) \
        and not any("written out in one line" in s for s in said), (first, said)
    with open(paths["math_keep"], "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Kind", "Page", "Before", "After"],
                                  ["equation", "maths", "z=(x–µ)/σ", "z=(x−μ)/σ"],
                                  ["equation", "maths", "x┴¯–µy┴–", "x┴¯−μy┴¯"],
                                  ["equation", "", "x┴¯–µy┴–", ""],
                                  ["equation", "", "∆x=2"],
                                  ["equation", "", "σ=√(npq)"],
                                  ["equation", "gone", "q"],
                                  ["expression", "", "z=(x–µ)/σ"]])
    # A row for a slide with its own title, which no other slide has, is
    # left as it was, as the kept equations are: neither is a change.
    spread = rem.slide_key("maths", pptxparse.read(os.path.join(folder, "maths.pptx")).slides[2])
    with open(paths["slide_titles"], "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([deckrun.TITLE_COLUMNS, [spread, "Another title"]])
    code, said = run()
    maths, other = (os.path.join(folder, "fixed", n) for n in ("maths.pptx", "other.pptx"))
    source = os.path.join(folder, "maths.pptx")
    yield "a row copied from the report keeps its equation as it was, in the deck it names, " \
        "or in every deck with a blank Page", code == 0 \
        and all(read_part(maths, "ppt/slides/slide%d.xml" % n)
                == read_part(source, "ppt/slides/slide%d.xml" % n) for n in (1, 2, 3, 4)) \
        and "<m:t>x−μ</m:t>" in read_part(other, "ppt/slides/slide1.xml") \
        and rows_of(reports["math_repaired"]) == [
            ["equation", "other", Z_TEX, "z = \\frac{x - \\mu}{\\sigma}"]], \
        rows_of(reports["math_repaired"])
    yield "the run says so, and a deck whose only change was kept isn't counted changed", \
        "fixed: 1 equation(s) given the characters they mean, 2 character(s) in all " \
        "(math.repair_equations); 3 kept as they were, as math-keep.csv says." in said \
        and any(s.startswith("fixed: 2 deck(s) written, 1 of them changed:") for s in said), said
    yield "a row that keeps nothing is warned about, one naming an equation that needs " \
        "nothing too, and a blank Page's where the deck's own row kept it, as a page's does " \
        "a book's; not one of a kind decks don't have, which keeps nothing in them", \
        "WARNING: 3 row(s) of math-keep.csv kept nothing in this run; the math they name " \
        "isn't in these decks as written there, or the repairs wouldn't change it:" in said \
        and "  equation,,x┴¯–µy┴–" in said and "  equation,,σ=√(npq)" in said \
        and "  equation,gone,q" in said and not any("expression" in s for s in said), said
    with open(paths["math_keep"], "a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow(["equation", "other", Z_TEX])
    code, said = run()
    yield "with every equation kept, one named in TeX as the report has it, the run says so, " \
        "and the report is gone", code == 0 \
        and "fixed: 0 equation(s) given the characters they mean, 0 character(s) in all " \
        "(math.repair_equations); 4 kept as they were, as math-keep.csv says." in said \
        and not os.path.exists(reports["math_repaired"]), said
    code, said = run(on=False)
    yield "with math.repair_equations off, nothing repaired, the report gone, and no row " \
        "warned about, since none could keep anything", code == 0 \
        and not os.path.exists(reports["math_repaired"]) \
        and read_part(other, "ppt/slides/slide1.xml") == read_part(
            os.path.join(folder, "other.pptx"), "ppt/slides/slide1.xml") \
        and not any("kept nothing" in s for s in said), said
    # With a conversion after, which writes the report with the pages'
    # repairs (convert.py), the copies' rows are handed over, and written
    # all the same, unsaid, for a run that stops before then.
    os.remove(paths["math_keep"])
    handed, said = {}, []
    code = deckrun.run(folder, ["maths.pptx", "other.pptx"], [target()], paths, reports,
                       say=said.append, math=handed)
    yield "with a conversion after, the copies' rows are handed over and written all the " \
        "same, unsaid, so that a run stopping before the conversion's report leaves them, " \
        "none of them said to be written out in one line", \
        code == 0 and len(handed.get("rows", ())) == 4 \
        and rows_of(reports["math_repaired"]) == first \
        and not any("math repair" in s for s in said) \
        and handed.get("in_one_line") is False, (handed, said)
    reading = deckrun.equation_tex
    deckrun.equation_tex = lambda path: {}
    try:
        code, said = run()
        written_out = rows_of(reports["math_repaired"])
        handed = {}
        deckrun.run(folder, ["maths.pptx", "other.pptx"], [target()], paths, reports,
                    say=lambda s: None, math=handed)
    finally:
        deckrun.equation_tex = reading
    yield "an equation Pandoc doesn't read, or isn't there to, is written out in one line, " \
        "and the run says so, or hands the conversion's report the word to", code == 0 \
        and ["equation", "other", "z=(x–µ)/σ", "z=(x−μ)/σ"] in written_out \
        and any("or written out in one line" in s for s in said) \
        and handed.get("in_one_line") is True, (written_out, said, handed)


# ---------------------------------------------------------------------------
# pictures cropped differently, alt text copied from the web, and the
# file's lists of fonts and slide titles
# ---------------------------------------------------------------------------

PARTS, DOTS, ALIKE, BARE = png(10, 20, 30), png(40, 50, 60), png(70, 80, 90), png(100, 110, 120)
WEB = png(130, 140, 150)


def cropped(shape_id, rid, box, crop, descr=None, decorative=False):
    """A picture cropped as PowerPoint crops one: a:srcRect's l, t, r, and
    b, each how far in from its side, in thousandths of a percent (None
    leaves one out)."""
    rect = "<a:srcRect %s/>" % " ".join('%s="%s"' % (side, value)
                                        for side, value in zip("ltrb", crop) if value is not None)
    return pic(shape_id, rid, box, descr, decorative).replace(
        '<a:blip r:embed="%s"/>' % rid, '<a:blip r:embed="%s"/>%s' % (rid, rect))


LEFT, RIGHT = (None, None, 50000, None), (50000, None, None, None)
SPOT = (457200, 1600200, 2000000, 2000000)
SPOT2 = (3000000, 1600200, 2000000, 2000000)
SPOT3 = (5500000, 1600200, 2000000, 2000000)
SPOT4 = (457200, 4000000, 2000000, 2000000)


def parts_deck(path):
    """Pictures on two slides: one image cropped to a different half on
    each, with one alt text for both; one cropped so with an alt text
    each; one cropped alike, to within a fiftieth, with one alt text; and
    one cropped to different halves with none."""
    return deck(path, [
        {"shapes": [title(2, "Left"), cropped(3, "rId2", SPOT, LEFT, "Two icons"),
                    cropped(4, "rId3", SPOT2, LEFT, "A green dot"),
                    cropped(5, "rId4", SPOT3, (None, None, 50000, None), "A dot"),
                    cropped(6, "rId5", SPOT4, LEFT)],
         "images": {"rId2": PARTS, "rId3": DOTS, "rId4": ALIKE, "rId5": BARE}},
        {"shapes": [title(2, "Right"), cropped(3, "rId2", SPOT, RIGHT, "Two icons"),
                    cropped(4, "rId3", SPOT2, RIGHT, "Another green dot"),
                    cropped(5, "rId4", SPOT3, (None, None, 48000, None), "A dot"),
                    cropped(6, "rId5", SPOT4, RIGHT)],
         "images": {"rId2": PARTS, "rId3": DOTS, "rId4": ALIKE, "rId5": BARE}}])


def case_crops(work):
    path = parts_deck(os.path.join(work, "parts.pptx"))
    d = pptxparse.read(path)
    crops = [[s.crop for s in slide.shapes if s.image] for slide in d.slides]
    filled = rect(5, "Filled", SPOT3).replace(
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
        '<a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom><a:blipFill><a:blip r:embed="rId2"/>'
        '<a:srcRect t="10000" b="20000"/><a:stretch><a:fillRect/></a:stretch></a:blipFill>')
    odd = pptxparse.read(deck(os.path.join(work, "odd.pptx"), [{"shapes": [
        title(2, "Odd"), cropped(3, "rId2", SPOT, ("25.5%", "-10000", "0", "125000")),
        pic(4, "rId2", SPOT2), filled, cropped(6, "rId2", SPOT4, (None, "60000", None, "60000"))],
        "images": {"rId2": RED}}]))
    yield "a picture's crop is the part of its image it shows: a:srcRect read, the strict form " \
        "too, a negative crop showing all of that side, one past the whole image or past the " \
        "other side none of it, an uncropped picture all of it, and a shape filled with a picture " \
        "its fill's crop", \
        crops[0][0] == (0, 0, 50000, 100000) and crops[1][0] == (50000, 0, 100000, 100000) \
        and [s.crop for s in odd.slides[0].shapes if s.image] == [
            (25500, 0, 100000, 0), (0, 0, 100000, 100000), (0, 10000, 100000, 80000),
            (0, 60000, 100000, 60000)], \
        (crops, [s.crop for s in odd.slides[0].shapes if s.image])
    views = pptxcheck.crop_views([(0, 0, 100000, 100000), (5000, 0, 100000, 100000),
                                  (5001, 0, 100000, 100000), None, (0, 0, 50000, 100000)])
    yield "copies cropped alike to within a twentieth of the image on every side show one part " \
        "of it", views == [0, 0, 1, 0, 2], views
    found = [(f.where, f.check) for f in pptxcheck.check(d)
             if f.check.startswith("pptx-alt") or f.check.endswith("no-alt")]
    yield "one alt text on copies cropped to show different parts is found on each copy; " \
        "different alt texts, or copies cropped alike, aren't", sorted(found) == [
            ("slide 1, Picture 3", "pptx-alt-same-for-crops"),
            ("slide 1, Picture 6", "pptx-object-no-alt"),
            ("slide 2, Picture 3", "pptx-alt-same-for-crops"),
            ("slide 2, Picture 6", "pptx-object-no-alt")], found
    titled = pptxparse.read(deck(os.path.join(work, "titled.pptx"), [
        {"shapes": [title(2, "A"), cropped(3, "rId2", SPOT, LEFT, "Icons | Freepik")],
         "images": {"rId2": PARTS}},
        {"shapes": [title(2, "B"), cropped(3, "rId2", SPOT, RIGHT, "Icons | Freepik")],
         "images": {"rId2": PARTS}},
        {"shapes": [title(2, "C"), cropped(3, "rId2", SPOT, LEFT, "Two", decorative=True),
                    cropped(4, "rId3", SPOT2, RIGHT, "Two")], "images": {"rId2": DOTS, "rId3": DOTS}},
        {"shapes": [title(2, "D"), cropped(3, "rId2", SPOT, LEFT, "One")],
         "images": {"rId2": DOTS}},
        {"shapes": [title(2, "E"), cropped(3, "rId2", SPOT, RIGHT, "One")],
         "images": {"rId2": DOTS}}]))
    found = sorted((f.where, f.check) for f in pptxcheck.check(titled)
                   if f.check.startswith("pptx-alt"))
    yield "a copy another alt-text finding names isn't named again, and a decorative copy's alt " \
        "text is no copy's", \
        found == [("slide 1, Picture 3", "pptx-alt-page-title"),
                  ("slide 2, Picture 3", "pptx-alt-page-title"),
                  ("slide 4, Picture 3", "pptx-alt-same-for-crops"),
                  ("slide 5, Picture 3", "pptx-alt-same-for-crops")], found
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    parts_deck(os.path.join(folder, "parts.pptx"))
    deck(os.path.join(folder, "logo.pptx"), [
        {"shapes": [title(2, "Logo"), cropped(3, "rId2", SPOT, LEFT),
                    pic(4, "rId3", SPOT2, "Marketing Mix Explained | Quizlet")],
         "images": {"rId2": BLUE, "rId3": WEB}}], logo=True)
    run = convert(folder, "--check-only")
    alt = {r[0]: r for r in rows_of(os.path.join(folder, "image-alt-missing.csv"))}
    parts_key, bare_key = (rem.image_key(hashlib.sha256(data).hexdigest()) + ".png"
                           for data in (PARTS, BARE))
    blue_key, web_key = (rem.image_key(hashlib.sha256(data).hexdigest()) + ".png"
                         for data in (BLUE, WEB))
    crop_reason = "; a crop of %s, which other copies crop differently"
    yield "each copy of a picture cropped to show a different part has a row of its own, keyed " \
        "on its shape and naming its image, which is written where its key would point", \
        run.returncode == 0 and sorted(alt) == sorted([
            "parts/slide-256/shape-3", "parts/slide-257/shape-3", "parts/slide-256/shape-6",
            "parts/slide-257/shape-6", blue_key, web_key]) \
        and alt["parts/slide-256/shape-3"][2:5] == [
            "parts.pptx slide 1", "shared with a copy showing another part" + crop_reason % parts_key,
            "Two icons"] \
        and alt["parts/slide-257/shape-6"][2:5] == [
            "parts.pptx slide 2", "missing (picture)" + crop_reason % bare_key, ""] \
        and all(os.path.isfile(os.path.join(folder, k)) for k in (parts_key, bare_key)) \
        and "has a row of its own, keyed on its shape" in run.stderr, (sorted(alt), run.stderr[-600:])
    yield "a picture with a copy on a layout keeps its one row, whose key can name that copy", \
        alt.get(blue_key, [""] * 5)[2] == "logo.pptx slide 1; logo.pptx layout or master", alt.get(blue_key)
    yield "a page's title copied as alt text has a row, which says so", \
        alt.get(web_key, [""] * 5)[3] == "a web page's title", alt.get(web_key)
    alike_key = rem.image_key(hashlib.sha256(ALIKE).hexdigest()) + ".png"
    with open(os.path.join(folder, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Image", "Alt"], [parts_key, "Two icons, described once"],
                                  [alike_key, "A dot, described once"],
                                  [bare_key, "[decorative]"]])
    noted = convert(folder, "--check-only")
    said = [l for l in noted.stderr.splitlines()
            if l.startswith("NOTE:") and "cropped to show different parts" in l]
    yield "a picture's row giving copies that show different parts one alt text is named in a " \
        "note; one for copies cropped alike, or decorative, isn't", \
        len(said) == 1 and said[0].startswith("NOTE: 1 row(s) of image-alt.csv give one alt text") \
        and parts_key[:-4] + ": parts.pptx slide 1, parts.pptx slide 2" in said[0], noted.stderr[-800:]
    with open(os.path.join(folder, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Image", "Alt"], [parts_key, "Two icons, described once"],
                                  ["parts/slide-256/shape-3", "The left icon"]])
    one = convert(folder, "--check-only")
    yield "nor one that gives one alt text to the only copy no row of its own describes", \
        not any(l.startswith("NOTE:") and "cropped" in l for l in one.stderr.splitlines()), \
        one.stderr[-600:]
    with open(os.path.join(folder, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Image", "Alt"], [parts_key, "Two icons, described once"],
                                  ["parts/slide-256/shape-3", "The left icon"],
                                  ["parts/slide-257/shape-3", "The right icon"],
                                  [bare_key, "[decorative]"], [blue_key, "[decorative]"],
                                  [web_key, "A diagram of the marketing mix"]])
    done = convert(folder)
    copy = pptxparse.read(os.path.join(folder, "remediated", "parts.pptx"))
    left = sorted({r[1] for r in rows_of(os.path.join(folder, "output-check.csv"))})
    yield "rows keyed on each copy's shape give each its own alt text, over the picture's row, " \
        "and the copy's check finds nothing left of it", done.returncode == 0 \
        and [s.descr for slide in copy.slides for s in slide.shapes if s.id == "3"] == [
            "The left icon", "The right icon"] \
        and not any(l.startswith("NOTE:") for l in done.stderr.splitlines()) \
        and not any(c.startswith("pptx-alt") or c.endswith("no-alt") for c in left), \
        (done.stderr[-600:], left)


def case_web_titles(work):
    # One of each kind, made up: a site after a pipe, a short name after a
    # dash, a title cut off, a search engine's "What Is It", a numbered
    # section and its book, a stock site's words, and a stock site's name.
    examples = [
        "Marketing Mix Explained | Quizlet",
        "Why Do Supply Chains Fail? - Examplepedia",
        "Ten Tips for Better Slides - example.com",
        "Robot Shaking Hands With A Person ...",
        "Opportunity Cost - What Is It and Why It Matters",
        "4.3 Demand and Supply Together – Introductory Economics",
        "Download Free High-Quality Vectors of Teamwork",
        "Handshake Royalty-Free Images",
        "Woman with a tablet flat concept icon",
        "A laptop on a desk from Shutterstock",
        "Notebook vector illustration isolated on white background",
    ]
    found = [(pptxcheck.alt_problem(t, limit=0) or ("",))[0] for t in examples]
    yield "alt text copied from a web page with its picture, the page's title or a stock " \
        "site's caption, is found", found == ["pptx-alt-page-title"] * len(examples), \
        list(zip(found, examples))
    fine = [
        "Two overlapping circles model P(A | B) = P(A AND B)/P(B).",
        "The residual (|e|) is the vertical distance from a data point to the line.",
        "The cover of a book whose author is Jo Smith – Jones.",
        "A sign that reads “Recycling. What is it? And why does it matter?”",
        "A vector diagram showing the forces on a block, and the net force vector.",
        "Map of Europe in 1914, the Central Powers in gray.",
        "A flat, open field under a cloudy sky.",
        "A stock chart of the S&P 500 rising from 2010 to 2020.",
        "A comparison of raster and vector images of the same letter.",
        "A camera that takes high-quality images, beside a phone.",
        "A website with a flat design and a menu at the top.",
        "The Golden Gate Bridge at dusk - San Francisco Bay",
        # A label: a word or two, and a name after a dash.
        "Attribution - By",
        "Knowledge Check - Memo",
        # Made up, in the shapes a book's descriptions take that ended as
        # a title does: a matrix's row and a set's condition after a pipe,
        # a sequence going on, a long description's quotation and its
        # author, a word processor's button, a figure on a white ground.
        "An augmented matrix whose second row is [0 1 1 | 2].",
        "The solution set {x | x > 2} shaded on a number line.",
        "A sequence of multiples of 3: 3, 6, 9, 12, ...",
        "The counting numbers 1, 2, 3 …",
        "A stone plaque beside the entrance to a library, carved in capitals, that reads, "
        "THE PUBLIC LIBRARY IS OPEN TO EVERY READER - FOUNDER",
        "The Insert Pictures menu: This Device, Stock Images, and Online Pictures.",
        "The number seven isolated on a white background.",
    ]
    found = [pptxcheck.alt_problem(t, limit=0) for t in fine]
    yield "a description that only shares a pipe, a dash, an ellipsis, or a word with a page's " \
        "title isn't", found == [None] * len(fine), list(zip(found, fine))
    generated = pptxcheck.alt_problem("A clipboard with a paper on it\n\nAI-generated content may "
                                      "be incorrect.")
    yield "Office's generated description is found in its newer wording as in its older ones", \
        generated == ("pptx-alt-auto-generated", "A clipboard with a paper on it AI-generated "
                      "content may be incorrect.") \
        and pptxcheck.alt_problem("A dog Description automatically generated")[0] \
        == "pptx-alt-auto-generated", generated
    yield "the report says why: a web page's title, or that it says nothing and why, " \
        "in the words a book's report uses", \
        deckrun.reason_of("pptx-alt-page-title", examples[0]) == "a web page's title" \
        and deckrun.reason_of("pptx-alt-same-for-crops", "Two icons") \
        == "shared with a copy showing another part" \
        and deckrun.reason_of(*pptxcheck.alt_problem("Image.")) == "says nothing" \
        and deckrun.reason_of(*pptxcheck.alt_problem("j0309720")) \
        == "says nothing (a clip-art id)", ""


def case_credits(work):
    # Made up, in the forms a credit takes: Wikimedia Commons' attribution,
    # a work and its author, a license and an address, a source, a byline,
    # a courtesy line, a copyright line, and a caption's credit line.
    credits = [
        "By Jane Roe - Own work, CC BY-SA 4.0, https://commons.wikimedia.org/w/index.php?curid=1",
        "From _A Book of Networks_ by Jo Smith, Licensed CC-BY-SA 4.0",
        "Public Domain, https://commons.wikimedia.org/w/index.php?curid=2",
        "Source: Roe and Doe (2020, 41)",
        "Photo by Jane Roe on Flickr",
        "Image courtesy of the Example Archive",
        "© 2021 Jane Roe",
        "(c) 2021 Jane Roe",
        "Credit: Jane Roe/Example Agency",
    ]
    found = [pptxcheck.alt_problem(t, limit=0) for t in credits]
    yield "alt text that is only a credit is found, the detail its text", \
        found == [("pptx-alt-credit", t) for t in credits], list(zip(found, credits))
    fine = [
        # A license's badge.
        "Public Domain",
        "CC BY 4.0",
        "Creative Commons Attribution-ShareAlike graphic",
        "Painting by Claude Monet of water lilies on a pond",
        "By World War I, women had entered the workforce in large numbers.",
        "By May 1945, the war in Europe had ended.",
        "A car being charged at a station. (credit: Jane Roe, Flickr)",
        "Debits and credits in a T-account: Cash on the left, Revenue on the right.",
    ]
    found = [pptxcheck.alt_problem(t, limit=0) for t in fine]
    yield "a license's badge, a byline going on to say what the picture shows, a sentence " \
        "opening with By and a capital, and a description with a credit after it aren't", \
        found == [None] * len(fine), list(zip(found, fine))
    yield "the report says so, in the words a book's report uses", \
        deckrun.reason_of(*pptxcheck.alt_problem(credits[0])) == "a credit or a source", ""


UP, DOWN, CAMERA, CAMERA2 = png(1, 2, 3), png(4, 5, 6), png(7, 8, 9), png(11, 12, 13)


def case_shared_alt(work):
    path = deck(os.path.join(work, "alike.pptx"), [
        {"shapes": [title(2, "One"), pic(3, "rId2", SPOT, "A rising line"),
                    pic(4, "rId3", SPOT2, "A rising line.")],
         "images": {"rId2": UP, "rId3": DOWN}},
        {"shapes": [title(2, "Two"), pic(3, "rId2", SPOT, "a rising line"),
                    pic(4, "rId3", SPOT2, "Credit: Jane Roe"),
                    pic(5, "rId4", SPOT3, "A rising line", decorative=True)],
         "images": {"rId2": UP, "rId3": GREEN, "rId4": RED}},
        {"shapes": [title(2, "Three"), pic(3, "rId2", SPOT, "Two dots"),
                    pic(4, "rId3", SPOT2, "Two dots")],
         "images": {"rId2": DOTS, "rId3": DOTS}},
        {"shapes": [title(2, "Four"), pic(3, "rId2", SPOT, "IMG_2041"),
                    pic(4, "rId3", SPOT2, "IMG_2041")],
         "images": {"rId2": CAMERA, "rId3": CAMERA2}}])
    found = sorted((f.where, f.check, f.detail) for f in pptxcheck.check(pptxparse.read(path))
                   if f.check.startswith("pptx-alt"))
    yield "one alt text on different pictures is found on each copy, case and closing " \
        "punctuation aside, with how many others have it; not on copies of one picture in two " \
        "parts, a decorative one, or one another finding names", found == [
            ("slide 1, Picture 3", "pptx-alt-shared", "shared with 1 other picture: A rising line"),
            ("slide 1, Picture 4", "pptx-alt-shared",
             "shared with 1 other picture: A rising line."),
            ("slide 2, Picture 3", "pptx-alt-shared", "shared with 1 other picture: a rising line"),
            ("slide 2, Picture 4", "pptx-alt-credit", "Credit: Jane Roe"),
            ("slide 4, Picture 3", "pptx-alt-placeholder",
             "a camera's or tool's name for a file: IMG_2041"),
            ("slide 4, Picture 4", "pptx-alt-placeholder",
             "a camera's or tool's name for a file: IMG_2041")], found
    folder = os.path.join(work, "alike")
    os.makedirs(folder)
    shutil.copy(path, folder)
    run = convert(folder, "--check-only")
    alt = {r[0]: r for r in rows_of(os.path.join(folder, "image-alt-missing.csv"))}
    up, down, green, camera, camera2 = (rem.image_key(hashlib.sha256(data).hexdigest()) + ".png"
                                        for data in (UP, DOWN, GREEN, CAMERA, CAMERA2))
    yield "each picture has a row that says why, one for every copy of it", \
        run.returncode == 0 and sorted(alt) == sorted([up, down, green, camera, camera2]) \
        and alt[up][2:4] == ["alike.pptx slide 1; alike.pptx slide 2",
                             "shared with 1 other picture"] \
        and alt[down][3] == "shared with 1 other picture" \
        and alt[green][3] == "a credit or a source", (sorted(alt.values()), run.stderr[-400:])
    with open(os.path.join(folder, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Image", "Alt"], [down, "A falling line"]])
    again = convert(folder, "--check-only")
    left = sorted(r[0] for r in rows_of(os.path.join(folder, "image-alt-missing.csv")))
    yield "a row describing one of them leaves the other's alt text its own, so it has no row", \
        again.returncode == 0 and left == sorted([green, camera, camera2]), \
        (left, again.stderr[-400:])
    with open(os.path.join(folder, "image-alt.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Image", "Alt"], [down, "A falling line"],
                                  [camera, "A rising line"]])
    third = convert(folder, "--check-only")
    rows = {r[0]: r for r in rows_of(os.path.join(folder, "image-alt-missing.csv"))}
    yield "and a row giving a picture whose own alt text said nothing another's alt text is " \
        "compared as given", third.returncode == 0 and sorted(rows) == sorted([up, green, camera2]) \
        and rows[up][3] == "shared with 1 other picture", (sorted(rows.values()), third.stderr[-400:])


def app_xml(fonts, titles, names=("Fonts Used", "Theme", "Slide Titles")):
    """docProps/app.xml as PowerPoint writes it: the fonts a deck uses, its
    theme, and its slides' titles, each list counted in HeadingPairs and
    its entries in TitlesOfParts, an empty one written <vt:lpstr/>."""
    lists = list(zip(names, (fonts, ["Office Theme"], titles)))
    heading = "".join('<vt:variant><vt:lpstr>%s</vt:lpstr></vt:variant><vt:variant><vt:i4>%d'
                      '</vt:i4></vt:variant>' % (esc(n), len(items)) for n, items in lists)
    entries = "".join("<vt:lpstr>%s</vt:lpstr>" % esc(e) if e else "<vt:lpstr/>"
                      for _n, items in lists for e in items)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://'
            'schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://'
            'schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>Microsoft '
            'Office PowerPoint</Application><Slides>%d</Slides><HeadingPairs><vt:vector size="%d" '
            'baseType="variant">%s</vt:vector></HeadingPairs><TitlesOfParts><vt:vector size="%d" '
            'baseType="lpstr">%s</vt:vector></TitlesOfParts></Properties>'
            % (len(titles), 2 * len(lists), heading, sum(len(i) for _n, i in lists), entries))


def app_lists(xml):
    """The lists in an app.xml, as {name: entries}, if they add up."""
    heading = re.findall(r"<vt:lpstr>([^<]*)</vt:lpstr></vt:variant><vt:variant><vt:i4>(\d+)<", xml)
    entries = [html.unescape(m.group(1) or "") for m in re.finditer(
        r"<vt:lpstr/>|<vt:lpstr>([^<]*)</vt:lpstr>",
        re.search(r"<TitlesOfParts>.*</TitlesOfParts>", xml, re.S).group(0))]
    size = int(re.search(r'<TitlesOfParts><vt:vector size="(\d+)"', xml).group(1))
    out, at = {}, 0
    for name, n in heading:
        out[name] = entries[at:at + int(n)]
        at += int(n)
    return out if at == len(entries) == size else None


def with_app(path, xml):
    """A deck with docProps/app.xml, its relationship, and its type."""
    with zipfile.ZipFile(path) as z:
        members = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            if info.filename == "_rels/.rels":
                data = data.replace(b"</Relationships>", b'<Relationship Id="rId9" Type="http://'
                                    b'schemas.openxmlformats.org/officeDocument/2006/relationships/'
                                    b'extended-properties" Target="docProps/app.xml"/>'
                                    b"</Relationships>")
            elif info.filename == "[Content_Types].xml":
                data = data.replace(b"</Types>", b'<Override PartName="/docProps/app.xml" '
                                    b'ContentType="application/vnd.openxmlformats-officedocument.'
                                    b'extended-properties+xml"/></Types>')
            z.writestr(info, data)
        z.writestr("docProps/app.xml", xml)
    return path


def case_app_properties(work):
    xml = app_xml(["Montserrat", "Avenir Next", "Arial", "Georgia", "Futura"],
                  ["PowerPoint Presentation", "Kept", ""])
    out, n = rem.set_app_properties(xml, {"Avenir Next": "Arial", "Futura": "Helvetica"},
                                    ["The First", None, "A & B"])
    yield "the copy's list of fonts names a replacement in the font's place, or drops the font " \
        "where the replacement is listed, and its list of titles the titles it wrote", \
        n == 4 and app_lists(out) == {
            "Fonts Used": ["Montserrat", "Arial", "Georgia", "Helvetica"],
            "Theme": ["Office Theme"], "Slide Titles": ["The First", "Kept", "A & B"]} \
        and "<vt:lpstr>A &amp; B</vt:lpstr>" in out and '<vt:vector size="6"' in out, out
    same = [rem.set_app_properties(xml, {"Avenir Next": "Arial"}, ["One", "Two"])[0] == xml,
            rem.set_app_properties(xml, {"Courier": "Arial"}, [None, None, None]) == (xml, 0),
            rem.set_app_properties(app_xml(["Avenir Next"], ["PowerPoint Presentation"],
                                           ("Verwendete Schriftarten", "Design", "Folientitel")),
                                   {"Avenir Next": "Arial"}, ["One"])[1] == 0,
            rem.set_app_properties(xml.replace("<vt:i4>5</vt:i4>", "<vt:i4>4</vt:i4>"),
                                   {"Avenir Next": "Arial"}, ["One", None, None])[1] == 0]
    first, second = (re.search(r"<%s>.*?</%s>" % (n, n), xml, re.S).group(0)
                     for n in ("HeadingPairs", "TitlesOfParts"))
    swapped = xml.replace(first, "\0").replace(second, first).replace("\0", second)
    turned = rem.set_app_properties(swapped, {"Avenir Next": "Arial"}, ["One", None, None])
    yield "and so does one whose list of titles comes before its counts", \
        turned[1] == 2 and swapped.index("TitlesOfParts") < swapped.index("HeadingPairs") \
        and ET.fromstring(turned[0].encode("utf-8")) is not None \
        and turned[0].count("<HeadingPairs>") == turned[0].count("<TitlesOfParts>") == 1 \
        and app_lists(turned[0]) == {
            "Fonts Used": ["Montserrat", "Arial", "Georgia", "Futura"],
            "Theme": ["Office Theme"], "Slide Titles": ["One", "Kept", ""]}, turned
    yield "a list of titles that isn't one for each slide is left, and so is a file whose lists " \
        "change nothing, are named in another language, or don't add up", \
        same == [False, True, True, True] and app_lists(rem.set_app_properties(
            xml, {"Avenir Next": "Arial"}, ["One", "Two"])[0])["Slide Titles"] == [
                "PowerPoint Presentation", "Kept", ""], same
    path = with_app(embed_fonts(deck(os.path.join(work, "app.pptx"), [
        {"shapes": [textbox(2, "Heading", ["Growth"], (457200, 274320, 8229600, 1143000)),
                    font_box(3, "Body", "Avenir Next", AVENIR),
                    font_box(4, "Other", "Arial", ARIAL, y=2200000)]},
        {"shapes": [title(2, "Costs"), font_box(3, "More", "Avenir Next", AVENIR)]},
        {"shapes": [font_box(3, "Note", "Arial", ARIAL)]},
        {"shapes": [title(2, "Costs")]}]),
        [("Avenir Next", 4, AVENIR, ("regular",))]),
        app_xml(["Avenir Next", "Arial"], ["PowerPoint Presentation", "Costs",
                                           "PowerPoint Presentation", "Costs"]))
    out = os.path.join(work, "out", "app.pptx")
    rem.remediate(path, out, titles={"app/slide-256": "Growth", "app/slide-258": "A note",
                                     "app/slide-259": "Costs (2)"},
                  fonts={"Avenir Next": None})
    lists = app_lists(read_part(out, "docProps/app.xml"))
    yield "a copy whose fonts and titles change lists them so in its properties: a heading " \
        "made its title, a title above its slide, and a title another slide had", lists == {
            "Fonts Used": ["Arial"], "Theme": ["Office Theme"],
            "Slide Titles": ["Growth", "Costs", "A note", "Costs (2)"]}, lists
    plain = with_app(deck(os.path.join(work, "plain.pptx"), [{"shapes": [title(2, "Plain")]}]),
                     app_xml(["Calibri"], ["Plain"]).replace("Microsoft Office PowerPoint", "x"))
    out = os.path.join(work, "out", "plain.pptx")
    rem.remediate(plain, out, alts={})
    yield "a copy whose fonts and titles don't change keeps its properties byte for byte", \
        read_part_bytes(out, "docProps/app.xml") == read_part_bytes(plain, "docProps/app.xml"), ""


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
    with open(path, encoding="utf-8-sig", newline="") as fh:
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
    # project.kind: slides makes it slides, where Markdown is a deck too: a
    # folder of both kinds stops, nothing written.
    with open(os.path.join(book, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.slides\n  title: A Book\n  kind: slides\n")
    result = convert(book, "--check-only")
    yield "project.kind: slides with a deck of each kind stops, and says to part them", \
        result.returncode != 0 and "1 PowerPoint deck(s) and 1 written in Markdown " \
        "(talk.pptx, one.md)" in result.stderr and "folder of its own" in result.stderr \
        and not os.path.exists(os.path.join(book, "slides-check.csv")), result.stderr[-500:]
    # A Word file in a folder of PowerPoint decks is left out, and said to be.
    os.remove(os.path.join(book, "one.md"))
    shutil.copy(clean_deck(os.path.join(work, "word-stand-in.pptx")),
                os.path.join(book, "notes.docx"))
    result = convert(book, "--check-only")
    yield "project.kind: slides makes it slides, with the pages left out", \
        result.returncode == 0 and "1 file(s) here are left out (notes.docx)" in result.stderr \
        and "decks, PowerPoint or Markdown" in result.stderr \
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
        and read_part(os.path.join(work, "util-links", "maths.pptx"),
                      "ppt/slides/slide1.xml").count("<m:t>¯</m:t>") == 2 \
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


# ---------------------------------------------------------------------------
# A deck converted: read as a deck written in Markdown is (pptxsource.py)
# ---------------------------------------------------------------------------

BULLETED = ('<a:lvl1pPr marL="342900" indent="-342900"><a:buFont typeface="Arial"/>'
            '<a:buChar char="&#8226;"/><a:defRPr sz="2800"/></a:lvl1pPr>'
            '<a:lvl2pPr marL="742950" indent="-285750"><a:buFont typeface="Arial"/>'
            '<a:buChar char="&#8211;"/><a:defRPr sz="2400"/></a:lvl2pPr>')
M_NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
A14_CHOICE = ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-'
              'compatibility/2006"><mc:Choice xmlns:a14="http://schemas.microsoft.com/office/'
              'drawing/2010/main" Requires="a14">%s</mc:Choice><mc:Fallback>%s</mc:Fallback>'
              '</mc:AlternateContent>')
PLAIN = '<a:pPr marL="0" indent="0"><a:buNone/></a:pPr>'
BREAK = '<a:br><a:rPr lang="en-US"/></a:br>'
GRAY, GOLD, PINK = png(120, 120, 120), png(200, 160, 0), png(240, 120, 160)
SLIDE_ID = 255     # a slide's id is this and its number, as presentation_xml() gives them


def bulleted_master():
    """The usual master, its body text bulleted at two levels, as a
    master PowerPoint makes is."""
    plain = '<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2800"/></a:lvl1pPr></p:bodyStyle>'
    xml = master_xml()
    assert xml.count(plain) == 1
    return xml.replace(plain, "<p:bodyStyle>%s</p:bodyStyle>" % BULLETED)


def r(text, click="", **props):
    """A run, props its a:rPr's attributes, click an a:hlinkClick."""
    attrs = "".join(' %s="%s"' % (k, v) for k, v in props.items())
    return '<a:r><a:rPr lang="en-US"%s>%s</a:rPr><a:t>%s</a:t></a:r>' % (attrs, click, esc(text))


def p(*pieces, ppr=""):
    return "<a:p>%s%s</a:p>" % (ppr, "".join(pieces))


def lvl(n, bullet=""):
    return '<a:pPr lvl="%d">%s</a:pPr>' % (n, bullet)


def shape(shape_id, name, paragraphs, ph=None, box=None):
    """A shape holding paragraphs as written: a placeholder, placed by its
    layout unless box says, or a text box."""
    sppr = ('<p:spPr>%s<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>' % xfrm(*box)
            if box else "<p:spPr/>")
    return ("<p:sp>%s%s<p:txBody><a:bodyPr/><a:lstStyle/>%s</p:txBody></p:sp>"
            % (nv("sp", shape_id, name, ph=ph), sppr, "".join(paragraphs)))


def math(body, display=False):
    """Office math in a paragraph, as PowerPoint writes it."""
    if display:
        return '<a14:m><m:oMathPara %s><m:oMath>%s</m:oMath></m:oMathPara></a14:m>' % (M_NS, body)
    return "<a14:m><m:oMath %s>%s</m:oMath></a14:m>" % (M_NS, body)


def in_a14(xml, shape_id):
    """A shape holding an equation, in AlternateContent as PowerPoint wraps
    one, its Fallback another shape with the same id."""
    return A14_CHOICE % (xml, rect(shape_id, "Fallback %d" % shape_id, (0, 0, 914400, 914400)))


def notes_of(paragraphs):
    """A notes slide whose body holds paragraphs as written."""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:notes %s><p:cSld>'
            '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/><p:sp>%s<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>%s'
            '</p:txBody></p:sp></p:spTree></p:cSld></p:notes>'
            % (NS, nv("sp", 3, "Notes Placeholder 2", ph='<p:ph type="body" idx="1"/>'),
               "".join(paragraphs)))


def bulleted_notes_master():
    """A notes master whose notes style bullets its first two levels, and
    whose body placeholder's list style takes the second's away."""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:notesMaster %s>'
            '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
            '</p:nvGrpSpPr><p:grpSpPr/><p:sp>%s<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle>'
            '<a:lvl2pPr><a:buNone/></a:lvl2pPr></a:lstStyle><a:p/></p:txBody></p:sp>'
            '</p:spTree></p:cSld><p:notesStyle><a:lvl1pPr marL="171450" indent="-171450">'
            '<a:buFont typeface="Arial"/><a:buChar char="&#8226;"/></a:lvl1pPr>'
            '<a:lvl2pPr marL="628650" indent="-171450"><a:buFont typeface="Arial"/>'
            '<a:buChar char="&#8226;"/></a:lvl2pPr></p:notesStyle></p:notesMaster>'
            % (NS, nv("sp", 2, "Notes Placeholder 1", ph='<p:ph type="body" idx="1"/>')))


def linked_pic(shape_id, rid, link_rid, box, descr):
    """A picture that is a link, as its own properties say."""
    return pic(shape_id, rid, box, descr).replace(
        'descr="%s"/>' % esc(descr), 'descr="%s"><a:hlinkClick r:id="%s"/></p:cNvPr>'
        % (esc(descr), link_rid))


def tc(paragraphs, attrs=""):
    """A table cell holding paragraphs as written."""
    return ("<a:tc%s><a:txBody><a:bodyPr/><a:lstStyle/>%s</a:txBody><a:tcPr/></a:tc>"
            % (attrs, "".join(paragraphs) or "<a:p/>"))


BAR = '<m:acc><m:accPr><m:chr m:val="&#175;"/></m:accPr><m:e><m:r><m:t>x</m:t></m:r></m:e></m:acc>'
FIELD = "https://example.org/data"
WIDE = (457200, 1600200, 8229600, 900000)
LOW = (457200, 3000000, 8229600, 900000)


def reader_deck(path):
    """A deck holding what the reader reads, on a master whose body text is
    bulleted: a title slide, two sections, formatting, lists inherited and
    numbered, links of every kind, tables, pictures, equations, notes, a
    slide with no title, a hidden one, objects it can't convert, a title
    from the sidecar, and a reading order from it."""
    return deck(path, [
        # 1, the title slide
        {"shapes": [title(2, "A Course of Talks", "ctrTitle", box=TITLE_BOX),
                    shape(3, "Subtitle 2", [p(r("Week one")), p(r("Second line"))],
                          ph='<p:ph type="subTitle" idx="1"/>'),
                    pic(4, "rId2", (457200, 4000000, 1000000, 1000000), "A lecture hall")],
         "images": {"rId2": PINK}, "notes": "Welcome everyone."},
        # 2
        {"shapes": [title(2, "Formatting"), shape(3, "Content Placeholder 2", [
            p(r("Plain "), r("bold", b="1"), r(" and "), r("italic", i="1"), r(" and "),
              r("under", u="sng"), r(" and "), r("struck", strike="sngStrike"), r(" and "),
              r("caps", cap="small"), r(" H"), r("2", baseline="-25000"), r("O, x"),
              r("2", baseline="30000"), r("."), ppr=PLAIN),
            p(r("H", i="1"), r("0", i="1", baseline="-25000"), r(" holds."), ppr=PLAIN),
            p(r("First line "), BREAK, r("second line"), ppr=PLAIN),
            p(r("Bold st", b="1"), r("ill bold", b="1"), ppr=PLAIN)],
            ph='<p:ph idx="1"/>')],
         "notes": notes_of([p(r("Ask "), r("who", b="1"), r(" paid.")),
                            p(r("One"), ppr='<a:pPr><a:buChar char="&#8226;"/></a:pPr>'),
                            p(r("Two"), ppr='<a:pPr><a:buChar char="&#8226;"/></a:pPr>')])},
        # 3
        {"shapes": [title(2, "Lists"), shape(3, "Content Placeholder 2", [
            p(r("Apples")), p(r("Pears")), p(r("Green"), ppr=lvl(1)), p(r("Red"), ppr=lvl(1)),
            p(r("Plums")), p(r("Then:"), ppr=PLAIN),
            p(r("Third"), ppr=lvl(0, '<a:buAutoNum type="alphaLcParenR" startAt="3"/>')),
            p(r("Fourth"), ppr=lvl(0, '<a:buAutoNum type="alphaLcParenR" startAt="3"/>')),
            p(r("More about the fourth."), ppr=lvl(1, "<a:buNone/>")), p()],
            ph='<p:ph idx="1"/>')]},
        # 4
        {"shapes": [title(2, "Links"), shape(3, "TextBox 2", [
            p(r("See "), r("the source", click='<a:hlinkClick r:id="rId3" tooltip="Where the '
                                               'data are"/>'), r(".")),
            p(r("Back to "), r("formatting", click='<a:hlinkClick r:id="rId4" action="ppaction'
                                                    '://hlinksldjump"/>'), r(".")),
            p(r("Run "), r("a macro", click='<a:hlinkClick r:id="" action="ppaction://macro?'
                                            'name=Hello"/>'), r(".")),
            p(r("Next", click='<a:hlinkClick r:id="" action="ppaction://hlinkshowjump?'
                              'jump=nextslide"/>')),
            p(r("See "), r("the hidden one", click='<a:hlinkClick r:id="rId6" action="ppaction'
                                                    '://hlinksldjump"/>'), r("."))], box=WIDE),
            linked_pic(4, "rId5", "rId3", (457200, 4000000, 1000000, 1000000), "A chart")],
         "links": {"rId3": FIELD}, "slide_links": {"rId4": 2, "rId6": 9},
         "images": {"rId5": GRAY}},
        # 5, Part Two
        {"shapes": [title(2, "A Table"),
                    table(3, [["Name", "Value", "Note"], ["x", "both", ""], ["y", "1", "a b"]],
                          WIDE, first_row=True, first_col=True,
                          cells={0: [cell("Name", True), cell("Value", True), cell("Note", True)],
                                 1: [cell("x"), tc([p(r("both"))], ' gridSpan="2"'),
                                     tc([], ' hMerge="1"')],
                                 2: [cell("y"), cell("1"), tc([p(r("a")), p(r("b"))])]}),
                    table(4, [["Year", "Rate"], ["2020", "3"]], LOW)]},
        # 6
        {"shapes": [title(2, "Pictures"),
                    pic(3, "rId2", SPOT, "A red square"), pic(4, "rId3", SPOT2, decorative=True),
                    pic(5, "rId4", SPOT3, "Old words"), pic(6, "rId5", SPOT4, "Its own words"),
                    cropped(7, "rId6", (6000000, 4000000, 1000000, 1000000), LEFT, "...")],
         "images": {"rId2": RED, "rId3": GREEN, "rId4": BLUE, "rId5": GOLD, "rId6": GRAY}},
        # 7
        {"shapes": [title(2, "Equations"),
                    in_a14(shape(3, "TextBox 2", [
                        p(r("The mean "), math(BAR + "<m:r><m:t>=1</m:t></m:r>"), r(" is shown.")),
                        p(math("<m:r><m:t>y=2</m:t></m:r>", display=True))], box=WIDE), 3),
                    in_a14(table(4, [["Term", "z=3"]], LOW, first_row=True, cells={0: [
                        cell("Term"), tc([p(math("<m:r><m:t>z=3</m:t></m:r>"))])]}), 4)]},
        # 8, no title
        {"shapes": [shape(2, "TextBox 1", [p(r("No title here."))], box=WIDE)]},
        # 9, hidden
        {"shapes": [title(2, "Hidden"), content(3, ["Not shown."])], "hidden": True},
        # 10
        {"shapes": [title(2, "Objects"), chart(3, "rId2", WIDE, "Sales by year"),
                    group(4, [shape(5, "TextBox 4", [p(r("Left box"))], box=(0, 0, 100, 100)),
                              shape(6, "TextBox 5", [p(r("Right box"))], box=(100, 0, 100, 100))],
                          LOW, descr="Two boxes"),
                    video(7, "rId3", SPOT4)],
         "charts": ("rId2",), "videos": ("rId3",)},
        # 11, its heading a text box the sidecar makes its title
        {"shapes": [shape(2, "TextBox 1", [p(r("A Heading"))], box=TITLE_BOX),
                    shape(3, "TextBox 2", [p(r("Body text."))], box=WIDE)]},
        # 12, read in the order the sidecar gives
        {"shapes": [title(2, "Order"), shape(4, "TextBox 3", [p(r("Second words"))], box=LOW),
                    shape(3, "TextBox 2", [p(r("First words"))], box=WIDE)]},
    ], sections=[("Part One", [0, 1, 2, 3]), ("Part Two", list(range(4, 12)))],
        master=bulleted_master())


def inline_text(inlines):
    """Inlines as text, formatting aside."""
    out = []
    for inline in inlines:
        kind = inline["t"]
        if kind == "Str":
            out.append(inline["c"])
        elif kind in ("Space", "LineBreak"):
            out.append(" ")
        elif kind == "Math":
            out.append("$%s$" % inline["c"][1])
        elif kind in ("Link", "Image", "Span"):
            out.append(inline_text(inline["c"][1]))
        elif isinstance(inline.get("c"), list):
            out.append(inline_text(inline["c"]))
    return "".join(out)


def slide_blocks(doc, heading):
    """A slide's blocks, after its heading (its text) to the next heading
    or rule; none for no such heading."""
    blocks = doc["blocks"]
    for i, block in enumerate(blocks):
        if block["t"] == "Header" and inline_text(block["c"][2]) == heading:
            out = []
            for later in blocks[i + 1:]:
                if later["t"] in ("Header", "HorizontalRule"):
                    break
                out.append(later)
            return out
    return []


def walk_json(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def of_kind(node, kind):
    return [n for n in walk_json(node) if n.get("t") == kind]


def S(text):
    return {"t": "Str", "c": text}


SP = {"t": "Space"}


def reader_sidecars(folder, path):
    """The sidecars for reader_deck's decisions: a picture's alt text by its
    image and another's by its shape, over its image's in the deck, the
    header row of the table that has none, the title of the slide whose
    heading is a text box, and the reading order of the slide whose shapes
    are out of order."""
    deck_ = pptxparse.read(path)
    blue = next(s for s in deck_.slides[5].all_shapes() if s.id == "5").image[1]
    gold = next(s for s in deck_.slides[5].all_shapes() if s.id == "6").image[1]
    plain = next(s for s in deck_.slides[4].all_shapes() if s.id == "4").table.key()
    files = {"image-alt.csv": "Image,Alt\n%s.png,New words\nReader/slide-%d/shape-6,Shape words\n"
                              "%s.png,The image's words\n"
                              % (rem.image_key(blue), SLIDE_ID + 6, rem.image_key(gold, "Reader")),
             "table-headers.csv": "key,headers\n%s,first-row\n" % plain,
             "slide-titles.csv": "Slide,Title\nReader/slide-%d,A Heading\n" % (SLIDE_ID + 11),
             "reading-order.csv": "Slide,Order\nReader/slide-%d,2 3 4\n" % (SLIDE_ID + 12)}
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    return blue


def case_reader(work):
    """A PowerPoint deck read into the intermediate a deck written in
    Markdown has, as pptxsource.read() reads it, its equations through
    Pandoc's Word reader."""
    if not pandoc_ok():
        return
    import pptxsource
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    path = reader_deck(os.path.join(folder, "Reader.pptx"))
    blue = reader_sidecars(folder, path)
    doc, record = pptxsource.read(
        path, folder, work, rem.alt_rows(os.path.join(folder, "image-alt.csv")),
        rem.header_rows(os.path.join(folder, "table-headers.csv")),
        rem.title_rows(os.path.join(folder, "slide-titles.csv")),
        rem.order_rows(os.path.join(folder, "reading-order.csv")),
        api_version=pptxsource.api_version())
    meta, blocks = doc["meta"], doc["blocks"]
    headings = [(b["c"][0], inline_text(b["c"][2]), b["c"][1][0]) for b in blocks
                if b["t"] == "Header"]
    losses = {}
    for kind, where in record.losses:
        losses.setdefault(kind, []).append(where)
    yield "the title slide is the deck's title and subtitle, its paragraphs as lines", \
        inline_text(meta["title"]["c"]) == "A Course of Talks" \
        and meta["subtitle"]["c"] == [S("Week"), SP, S("one"), {"t": "LineBreak"}, S("Second"),
                                      SP, S("line")], meta.get("subtitle")
    yield "its notes come first, before any heading, where Pandoc's writer gives them the title " \
        "slide", blocks[0]["t"] == "Div" and blocks[0]["c"][0][1] == ["notes"] \
        and inline_text(blocks[0]["c"][1][0]["c"]) == "Welcome everyone.", blocks[0]
    yield "and the rest of the title slide, its picture, is left out and said to be", \
        losses.get("title-slide") == ["Reader.pptx slide 1: a picture"], losses
    yield "sections are headings at level 1 and slides at 2, with the ids Pandoc's reader gives", \
        headings == [(1, "Part One", "part-one"), (2, "Formatting", "formatting"),
                     (2, "Lists", "lists"), (2, "Links", "links"), (1, "Part Two", "part-two"),
                     (2, "A Table", "a-table"), (2, "Pictures", "pictures"),
                     (2, "Equations", "equations"), (2, "Objects", "objects"),
                     (2, "A Heading", "a-heading"), (2, "Order", "order")], headings
    yield "the slide level is recorded, 2, and the deck's language", \
        meta.get("deck-slide-level") == {"t": "MetaString", "c": "2"} \
        and meta.get("lang") == {"t": "MetaString", "c": "en-US"} and "slide-level" not in meta, \
        sorted(meta)
    formatting = slide_blocks(doc, "Formatting") + [{"t": None, "c": [None]}] * 5
    first = formatting[0]["c"]
    expected = [S("Plain"), SP, {"t": "Strong", "c": [S("bold")]}, SP, S("and"), SP,
                {"t": "Emph", "c": [S("italic")]}, SP, S("and"), SP,
                {"t": "Underline", "c": [S("under")]}, SP, S("and"), SP,
                {"t": "Strikeout", "c": [S("struck")]}, SP, S("and"), SP,
                {"t": "SmallCaps", "c": [S("caps")]}, SP, S("H"),
                {"t": "Subscript", "c": [S("2")]}, S("O,"), SP, S("x"),
                {"t": "Superscript", "c": [S("2")]}, S(".")]
    yield "a run's own bold, italic, underline, strikethrough, small capitals, and scripts", \
        first == expected, first
    yield "runs that share a format are one element of it, an italic H and its italic subscript", \
        formatting[1]["c"][0] == {"t": "Emph", "c": [S("H"), {"t": "Subscript", "c": [S("0")]}]}, \
        formatting[1]["c"]
    yield "a line break, the space before it gone", \
        formatting[2]["c"] == [S("First"), SP, S("line"), {"t": "LineBreak"}, S("second"), SP,
                               S("line")], formatting[2]["c"]
    yield "runs of the same formatting joined, a word split between them one word", \
        formatting[3]["c"] == [{"t": "Strong", "c": [S("Bold"), SP, S("still"), SP, S("bold")]}], \
        formatting[3]["c"]
    notes = next((b for b in formatting if b["t"] == "Div"), {"t": None, "c": [[None, []], []]})
    yield "a slide's notes are a notes div after its content, read as its text is", \
        notes["t"] == "Div" and notes["c"][0][1] == ["notes"] \
        and notes["c"][1][0]["c"] == [S("Ask"), SP, {"t": "Strong", "c": [S("who")]}, SP,
                                      S("paid.")] \
        and [b["t"] for b in notes["c"][1]] == ["Para", "BulletList"], notes
    lists = slide_blocks(doc, "Lists")
    bullets, then, numbered = (lists + [{"t": None, "c": [None, None]}] * 3)[:3]
    yield "bullets the master gives the body inherited, nested by level", \
        bullets == {"t": "BulletList", "c": [
            [{"t": "Plain", "c": [S("Apples")]}],
            [{"t": "Plain", "c": [S("Pears")]}, {"t": "BulletList", "c": [
                [{"t": "Plain", "c": [S("Green")]}], [{"t": "Plain", "c": [S("Red")]}]]}],
            [{"t": "Plain", "c": [S("Plums")]}]]}, bullets
    yield "a paragraph whose own pPr says no bullet ends the list", \
        then == {"t": "Para", "c": [S("Then:")]}, then
    yield "numbering from its scheme and start, and a paragraph with no number under an item " \
        "a paragraph of the item, the list loose", \
        numbered["t"] == "OrderedList" and numbered["c"][0] == [
            3, {"t": "LowerAlpha"}, {"t": "OneParen"}] \
        and numbered["c"][1] == [[{"t": "Para", "c": [S("Third")]}],
                                 [{"t": "Para", "c": [S("Fourth")]},
                                  {"t": "Para", "c": [S("More"), SP, S("about"), SP, S("the"), SP,
                                                      S("fourth.")]}]], numbered
    links = slide_blocks(doc, "Links")
    found = [(inline_text(l["c"][1]), l["c"][2]) for l in of_kind(links, "Link")]
    yield "a link to an address, its ScreenTip its title; to a slide, its heading's id; a jump " \
        "to the next slide shown, that slide's; and a picture that is a link", \
        found == [("the source", [FIELD, "Where the data are"]), ("formatting", ["#formatting", ""]),
                  ("Next", ["#a-table", ""]), ("A chart", [FIELD, ""])], found
    yield "a link that runs a macro is its words, and said to be", \
        "a macro" in inline_text(links[2]["c"]) and not of_kind(links[2], "Link") \
        and any("runs macro" in w for w in losses.get("link", [])), losses.get("link")
    yield "and one to a hidden slide, which isn't shown, where it is", \
        inline_text(links[4]["c"]) == "See the hidden one." and not of_kind(links[4], "Link") \
        and "Reader.pptx slide 4: a link to a slide with no title, or to none shown" \
        in losses.get("link", []), (links[4:5], losses.get("link"))
    tables = slide_blocks(doc, "A Table")
    head, body = tables[0]["c"][3], tables[0]["c"][4][0]
    yield "a table's header row and column as the deck flags them", \
        len(head[1]) == 1 and body[1] == 1, (len(head[1]), body[1])
    spanned = body[3][0][1][1]
    yield "a merged cell spans its columns, and the cell it covers isn't a cell", \
        spanned[3] == 2 and len(body[3][0][1]) == 2, body[3][0]
    two = body[3][1][1][2][4]
    yield "a cell of two paragraphs is two paragraphs, a cell of one plain", \
        [b["t"] for b in two] == ["Para", "Para"] and body[3][1][1][0][4][0]["t"] == "Plain", two
    yield "the table-headers sidecar's header row for the table that has none", \
        len(tables[1]["c"][3][1]) == 1 and tables[1]["c"][4][0][1] == 0, tables[1]["c"][3]
    pictures = [i["c"] for i in of_kind(slide_blocks(doc, "Pictures"), "Image")]
    alts = [("decorative" if "decorative" in a[0][1] else inline_text(a[1])) for a in pictures]
    yield "pictures with their alt text, the decorative mark as a class, and the sidecar's " \
        "decisions by image and by shape", \
        alts == ["A red square", "decorative", "New words", "Shape words", "..."], alts
    srcs = [a[2][0] for a in pictures]
    yield "each image written once to media/ under its key, the report's path for it", \
        srcs[2] == rem.image_key(blue) + ".png" \
        and all(os.path.isfile(os.path.join(folder, s)) for s in srcs) \
        and len(os.listdir(os.path.join(folder, "media"))) == 5, srcs
    yield "a picture shown cropped is shown whole, and said to be", \
        losses.get("crop") == ["Reader.pptx slide 6: a picture shown whole, which the slide "
                               "shows cropped"], losses.get("crop")
    equations = slide_blocks(doc, "Equations")
    maths = [(m["c"][0]["t"], m["c"][1]) for m in of_kind(equations, "Math")]
    yield "equations through Pandoc's Word reader, in their places, a display one display math", \
        len(maths) == 3 and maths[0][0] == "InlineMath" and maths[1] == ("DisplayMath", "y = 2") \
        and inline_text(equations[0]["c"]).startswith("The mean $") \
        and inline_text(equations[0]["c"]).endswith("$ is shown."), maths
    yield "a bar accent of the macron is \\bar, as a Word file's is read", \
        [m[1].replace(" ", "") for m in maths[:1]] == ["\\bar{x}=1"], maths[:1]
    yield "an equation in a table's cell, the table read from mc:AlternateContent's Choice", \
        maths[2:] == [("InlineMath", "z = 3")] and equations[-1]["t"] == "Table", maths[2:]
    rules = [i for i, b in enumerate(blocks) if b["t"] == "HorizontalRule"]
    yield "a slide with no title begins with a horizontal rule, as Pandoc begins one", \
        len(rules) == 1 and inline_text(blocks[rules[0] + 1]["c"]) == "No title here.", rules
    yield "a hidden slide is left out, and said to be", \
        "Hidden" not in [h[1] for h in headings] and losses.get("hidden") == [
            "Reader.pptx slide 9"], losses.get("hidden")
    objects = slide_blocks(doc, "Objects")
    yield "a group's pieces are read in turn, and its alt text said to be left out", \
        [inline_text(b["c"]) for b in objects] == ["Left box", "Right box"] \
        and losses.get("group") == ["Reader.pptx slide 10: a group described as 'Two boxes'"], \
        objects
    yield "a chart and a video are left out, and said to be", \
        losses.get("chart") == ["Reader.pptx slide 10: a chart"] \
        and losses.get("media") == ["Reader.pptx slide 10: a video"], losses
    yield "the slide-titles sidecar's title for a slide whose heading is a text box, the text " \
        "box its heading and not its text", \
        [inline_text(b["c"]) for b in slide_blocks(doc, "A Heading")] == ["Body text."], \
        slide_blocks(doc, "A Heading")
    yield "the reading-order sidecar's order", \
        [inline_text(b["c"]) for b in slide_blocks(doc, "Order")] == ["First words",
                                                                     "Second words"], \
        slide_blocks(doc, "Order")
    counts = record.counts
    yield "what it read, counted", \
        (counts["slides"], counts["pictures"], counts["decorative"], counts["tables"],
         counts["equations"], counts["notes"]) == (11, 5, 1, 3, 3, 2), dict(counts)
    unread, unread_record = pptxsource.read(path, os.path.join(work, "again"), work,
                                            pandoc=os.path.join(work, "no-pandoc"))
    yield "without Pandoc, an equation is its characters, as PowerPoint's linear format writes " \
        "it, and said to be", \
        not of_kind(unread, "Math") and "y=2" in inline_text(slide_blocks(unread, "Equations")[1][
            "c"]) and len([k for k, _ in unread_record.losses if k == "equation"]) == 3, \
        unread_record.losses
    ids = [pptxsource.identifier(t, {"a-table"}) for t in (
        "A Table", "1. Intro: the Basics", "", "Café au lait", "x.y_z-w")]
    yield "a heading's id is Pandoc's: lowercased, its punctuation and what's before its first " \
        "letter dropped, numbered after one used, \"section\" for none", \
        ids == ["a-table-1", "intro-the-basics", "section", "café-au-lait", "x.y_z-w"], ids
    small = deck(os.path.join(work, "Small.pptx"), [
        # 1, its title not a title slide's
        {"shapes": [title(2, "Notes"), content(3, ["Shown."]),
                    shape(4, "Footer 3", [p(r("A footer"))],
                          ph='<p:ph type="ftr" sz="quarter" idx="11"/>'),
                    shape(5, "Slide Number 4", [p(r("1"))],
                          ph='<p:ph type="sldNum" sz="quarter" idx="12"/>'),
                    textbox(6, "Hidden 5", ["Not shown."], LOW).replace(
                        'name="Hidden 5"', 'name="Hidden 5" hidden="1"')],
         "notes": notes_of([p(r("Said."), ppr="<a:pPr><a:buNone/></a:pPr>"), p(r("A point")),
                            p(r("Under it"), ppr=lvl(1)), p(r("Next point"))])},
        # 2 and 3, a title they share; 4, its own
        {"shapes": [title(2, "Same"), content(3, ["One."])]},
        {"shapes": [title(2, "Same"), content(3, ["Two."])]},
        {"shapes": [title(2, "Other"), content(3, ["Three."])]},
        # 5, two pictures with one id
        {"shapes": [title(2, "Twins"), pic(3, "rId2", SPOT, "Its own"),
                    pic(3, "rId3", SPOT2, "Its twin's")],
         "images": {"rId2": RED, "rId3": GREEN}},
        # 6, a shared title whose shape's id the slide repeats; 7, a heading so
        {"shapes": [title(2, "Same"), content(2, ["Three."])]},
        {"shapes": [textbox(3, "TextBox 2", ["A heading"], TITLE_BOX),
                    textbox(3, "TextBox 3", ["Body."], WIDE)]}],
        notes_master=bulleted_notes_master())
    small_doc, _ = pptxsource.read(
        small, folder, work,
        {"Small/slide-%d/shape-3" % (SLIDE_ID + 5): "Decided"},
        titles={"Small/slide-%d" % (SLIDE_ID + 3): "Same, again",
                "Small/slide-%d" % (SLIDE_ID + 4): "Changed",
                "Small/slide-%d" % (SLIDE_ID + 6): "Same, a third time",
                "Small/slide-%d" % (SLIDE_ID + 7): "A heading"})
    small_notes = of_kind(small_doc["blocks"], "Div")
    yield "notes take the bullets their notes master gives, its body placeholder's over its " \
        "notes style", \
        small_notes and small_notes[0]["c"][1] == [
            {"t": "Para", "c": [S("Said.")]},
            {"t": "BulletList", "c": [[{"t": "Para", "c": [S("A"), SP, S("point")]},
                                       {"t": "Para", "c": [S("Under"), SP, S("it")]}],
                                      [{"t": "Para", "c": [S("Next"), SP, S("point")]}]]}], \
        small_notes
    shown = slide_blocks(small_doc, "Notes")
    yield "a slide's footer and number, and a shape hidden on it, are left out", \
        [b["t"] for b in shown] == ["Para", "Div"] and inline_text(shown[0]["c"]) == "Shown.", \
        shown
    yield "a deck whose first slide isn't a title slide has no title but its file's, which is " \
        "its title-meta, and that slide is its first", \
        "title" not in small_doc["meta"] and small_doc["meta"].get("title-meta") == {
            "t": "MetaString", "c": "A Deck"} and small_doc["blocks"][0]["t"] == "Header", \
        small_doc["meta"]
    small_headings = [inline_text(b["c"][2]) for b in small_doc["blocks"] if b["t"] == "Header"]
    yield "the slide-titles sidecar's title replaces one another slide has too, but not one " \
        "the slide has alone, as the copy's does", \
        small_headings[:5] == ["Notes", "Same", "Same, again", "Other", "Twins"], small_headings
    twins = [inline_text(i["c"][1]) for i in of_kind(slide_blocks(small_doc, "Twins"), "Image")]
    headed = [inline_text(b["c"]) for b in slide_blocks(small_doc, "A heading")]
    yield "and a decision for a shape whose id its slide repeats is skipped, as the copy skips " \
        "it: a picture's alt text, a title in place of a shared one, and a heading made the " \
        "title, which is the title above the slide instead, the heading kept", \
        twins == ["Its own", "Its twin's"] and small_headings[5:] == ["Same", "A heading"] \
        and headed == ["A heading", "Body."], (twins, small_headings, headed)
    linked = deck(os.path.join(work, "Linked.pptx"), [
        {"shapes": [title(2, "Linked", "ctrTitle", box=TITLE_BOX),
                    shape(3, "Subtitle 2", [p(r("See "), r("the second", click='<a:hlinkClick '
                                                'r:id="rId2" action="ppaction://hlinksldjump"/>'),
                                              r(" and "), r("the hidden", click='<a:hlinkClick '
                                                'r:id="rId3" action="ppaction://hlinksldjump"/>'))],
                          ph='<p:ph type="subTitle" idx="1"/>')],
         "slide_links": {"rId2": 2, "rId3": 3}},
        {"shapes": [title(2, "Second"), content(3, ["Shown."])]},
        {"shapes": [title(2, "Third"), content(3, ["Not shown."])], "hidden": True}])
    linked_doc, linked_record = pptxsource.read(linked, folder, work)
    subtitle = linked_doc["meta"].get("subtitle", {}).get("c", [])
    yield "a link in the title slide's subtitle goes to its slide, and one to a hidden slide is " \
        "its words", \
        [(inline_text(l["c"][1]), l["c"][2][0]) for l in of_kind(subtitle, "Link")] == [
            ("the second", "#second")] and inline_text(subtitle) == "See the second and the hidden" \
        and ("link", "Linked.pptx slide 1: a link to a slide with no title, or to none shown") \
        in linked_record.losses, (subtitle, linked_record.losses)
    lines = deck(os.path.join(work, "Lines.pptx"), [
        {"shapes": [title(2, "Lines"), shape(3, "TextBox 2", [
            p(r("First", b="1"), r(" "), BREAK, r("   "), r("second", b="1"), ppr=PLAIN)],
            box=WIDE)]}])
    lined = [b["c"] for b in slide_blocks(pptxsource.read(lines, folder, work)[0], "Lines")]
    yield "two bold lines are one bold holding their line break: the plain white space beside " \
        "the break, which goes, doesn't part them", \
        lined == [[{"t": "Strong", "c": [S("First"), {"t": "LineBreak"}, S("second")]}]], lined


CONVERTING = """\
targets:
  pages:
    format: html
  md:
    format: markdown
  copy:
    format: source
  again:
    format: pptx
"""


def converted_folder(work, config=CONVERTING):
    """A folder holding reader_deck, its sidecars, and a configuration."""
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    reader_deck(os.path.join(folder, "Reader.pptx"))
    reader_sidecars(folder, os.path.join(folder, "Reader.pptx"))
    with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
        fh.write(config)
    return folder


def page_headings(page):
    return [(int(level), " ".join(re.sub(r"<[^>]+>", "", text).split()))
            for level, text in re.findall(r"<h([1-6])[^>]*>(.*?)</h\1>", page, re.S)]


def with_custom(path, properties):
    """The deck at path with custom properties, as a producer's own tools
    write them: OpenStax's, its company and its language."""
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://'
           'schemas.openxmlformats.org/officeDocument/2006/custom-properties" xmlns:vt="http://'
           'schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">' + "".join(
               '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="%d" name="%s">'
               "<vt:lpwstr>%s</vt:lpwstr></property>" % (n, k, v)
               for n, (k, v) in enumerate(properties.items(), 2)) + "</Properties>")
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("docProps/custom.xml", xml)
    return path


def case_deck_languages(work):
    """Each deck's language, decided as a book's pages' are: its row in
    languages.csv, else its own (the language most of its runs say, or
    OpenStax's language property), else the project's; its copy given a
    row's or the property's in place of its own runs' and default's, and
    its own where it declares no default; its page in it."""
    if not pandoc_ok():
        return
    folder = os.path.join(work, "decks")
    os.makedirs(folder)

    def one(name, words, lang, default):
        return deck(os.path.join(folder, name + ".pptx"), [
            {"shapes": [title(2, words[0], lang=lang), content(3, [words[1]], lang=lang)]}],
            default_lang=default, core_title=words[0])
    with_custom(one("openstax-es", ("Funciones", "Una función"), "en-US", "en-US"),
                {"company": "OpenStax", "language": "es"})
    one("francais", ("Bonjour", "Une phrase"), "fr-FR", None)
    one("row", ("Zeile", "Ein Satz"), "en-US", "en-US")
    one("english", ("English", "A sentence"), "en-US", "en-US")
    with open(os.path.join(folder, "languages.csv"), "w", encoding="utf-8") as fh:
        fh.write("source,language\nrow,de\n")
    with open(os.path.join(folder, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("targets:\n  copy:\n    format: source\n  pages:\n    format: html\n")
    checked = convert(folder, "--check-only")
    first_drafted = rows_of(os.path.join(folder, "languages-new.csv"))
    result = convert(folder, "--quick")
    said = result.stderr

    def part(name, inner):
        path = os.path.join(folder, "copy", name + ".pptx")
        return read_part(path, inner) if os.path.isfile(path) else ""

    def page(name):
        path = os.path.join(folder, "pages", name + ".html")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            found = re.search(r'<html\b[^>]*\slang="([^"]*)"', fh.read())
        return found.group(1) if found else None
    drafted = rows_of(os.path.join(folder, "languages-new.csv"))
    yield "checked only, the decks' languages are reported, as a slides run writes its " \
        "reports before it converts", \
        checked.returncode == 0 and "3 page(s) are in another language than the book's" \
        in checked.stderr and len(first_drafted) == 2, checked.stderr[-800:]
    yield "the decks are copied and converted", result.returncode == 0, said[-600:]
    yield "a copy is given OpenStax's language in place of the US English its runs, its " \
        "default, and its masters say", \
        'lang="en-US"' not in part("openstax-es", "ppt/slides/slide1.xml") \
        and part("openstax-es", "ppt/slides/slide1.xml").count('lang="es"') >= 2 \
        and '<a:defRPr lang="es"/>' in part("openstax-es", "ppt/presentation.xml") \
        and 'lang="en-US"' not in part("openstax-es", "ppt/presentation.xml") \
        and 'lang="es"' in part("openstax-es", "ppt/slideMasters/slideMaster1.xml"), \
        (part("openstax-es", "ppt/presentation.xml")[-400:], said[-400:])
    yield "and a row's in place of its own", \
        'lang="en-US"' not in part("row", "ppt/slides/slide1.xml") \
        and '<a:defRPr lang="de"/>' in part("row", "ppt/presentation.xml"), \
        part("row", "ppt/presentation.xml")[-300:]
    yield "a deck with no default is given its runs' language, though the project declares " \
        "none, and its runs keep theirs; one in the book's language keeps its own", \
        '<a:defRPr lang="fr-FR"/>' in part("francais", "ppt/presentation.xml") \
        and part("francais", "ppt/slides/slide1.xml").count('lang="fr-FR"') >= 2 \
        and '<a:defRPr lang="en-US"/>' in part("english", "ppt/presentation.xml"), \
        part("francais", "ppt/presentation.xml")[-300:]
    yield "the run counts the decks given their language as their default, and those given " \
        "another in place of their own", \
        "1 deck(s) given their language as their default and 2 another in place of their " \
        "own, and" in said, said[-1200:]
    yield "each deck's page is in its language, one in the book's in the book's", \
        [page(n) for n in ("openstax-es", "row", "francais", "english")] \
        == ["es", "de", "fr-FR", "en"], [page(n) for n in ("openstax-es", "row", "francais",
                                                         "english")]
    yield "the run names the decks in another language than the book's, and drafts a row for " \
        "each its own file put there", \
        "3 page(s) are in another language than the book's, en, the default" in said \
        and "row de (languages.csv)" in said \
        and sorted(r[:2] for r in drafted) == [["francais", "fr-FR"], ["openstax-es", "es"]], \
        (drafted, said[-1200:])


def case_converting(work):
    """convert.py on a folder of PowerPoint decks with targets of other
    formats than source: each deck checked and copied as before, then
    read (pptxsource.py) and written as a page and as Markdown, as a deck
    written in Markdown is; a pptx target refused without a template."""
    if not pandoc_ok():
        return
    folder = converted_folder(work)
    result = convert(folder, "--quick")
    out = result.stderr
    read = lambda *names: open(os.path.join(folder, *names), encoding="utf-8").read()  # noqa
    yield "the decks are checked and copied, then converted, as the run says", \
        result.returncode == 0 and "Slides: 1 PowerPoint deck(s), each checked and remediated" \
        in out and "Slides: 1 PowerPoint deck(s), each converted on its own: pages (html), " \
        "md (markdown)." in out and os.path.isfile(os.path.join(folder, "copy", "Reader.pptx")), \
        out[-800:]
    yield "a pptx target on a PowerPoint deck writes nothing without a template, and says what " \
        "the copy is and what a template would do", \
        "target again is format pptx, and nothing is written for it" in out \
        and "slides.reference_doc names" in out and not os.path.exists(
            os.path.join(folder, "again")), out[:1200]
    page = read("pages", "Reader.html")
    flat = " ".join(page.split())
    yield "the page is titled by the title slide, its sections and slides below it", \
        page_headings(page)[:5] == [(1, "A Course of Talks"), (2, "Part One"), (3, "Formatting"),
                                    (3, "Lists"), (3, "Links")] \
        and '<p class="subtitle">Week one<br />' in page, page_headings(page)
    yield "the formatting, the lists, and the links, as HTML has them", \
        all(s in flat for s in ("<strong>bold</strong>", "<em>italic</em>", "<u>under</u>",
                                "<del>struck</del>", '<span class="smallcaps">caps</span>',
                                "H<sub>2</sub>O", '<ol start="3" type="a">',
                                '<a href="https://example.org/data" title="Where the data are">',
                                '<a href="#formatting">')), page[:300]
    missing = [s for s in ('<th scope="col"><strong>Name</strong></th>', '<th scope="row">x</th>',
                           'colspan="2"', 'alt="New words"', 'alt="Shape words"',
                           'alt="" aria-hidden="true"', "<math") if s not in flat]
    yield "a table's header row and column, its merged cell, a picture's alt text, its shape's " \
        "over its image's, a decorative one hidden, and equations as MathML", not missing, missing
    yield "the notes under their slide, in a closed disclosure", \
        re.search(r'<details class="notes">\s*<summary>Speaker notes</summary>\s*<p>Ask '
                  r'<strong>who</strong> paid\.</p>', page) is not None, ""
    md = read("md", "Reader.md")
    yield "the Markdown is a deck written in Markdown: its title block, slides as ## headings, " \
        "notes divs", \
        'title: A Course of Talks' in md and "## Formatting" in md and "# Part One" in md \
        and "::: notes" in md and "deck-slide-level" not in md, md[:400]
    yield "its formatting, a decorative picture's class, its equations' TeX, and its pictures " \
        "beside it", \
        all(s in md for s in ("**bold**", "*italic*", "~2~", "^2^", "{.decorative}",
                              "$\\bar{x} = 1$")) \
        and os.path.isdir(os.path.join(folder, "md", "media")), md[:600]
    alt = rows_of(os.path.join(folder, "image-alt-missing.csv"))
    yield "the reports are the deck's, as its checks write them, not the filter's of the " \
        "intermediate", \
        alt and all(row[2].startswith("Reader.pptx slide") for row in alt) \
        and not os.path.exists(os.path.join(folder, "table-captions-missing.csv")), alt
    checks = {row[1] for row in rows_of(os.path.join(folder, "output-check.csv"))}
    yield "the output check holds the copy's findings and the page's", \
        any(c.startswith("pptx-") for c in checks) \
        and any(not c.startswith("pptx-") for c in checks), sorted(checks)
    yield "what the conversion leaves out is said: the title slide's picture, a hidden slide, a " \
        "chart, a video, a group's alt text, a crop, a macro's link", \
        all(s in out for s in ("1 title slide(s) holding more than a title and a subtitle",
                               "1 hidden slide(s) in 1 deck(s) are left out",
                               "1 chart(s) in 1 deck(s) aren't converted yet",
                               "1 video(s) and sound(s)", "1 group(s) of shapes",
                               "1 picture(s) a slide shows cropped",
                               "link(s) that don't go to an address or to a slide shown")), out
    yield "and the filter says nothing again of the deck's pictures and tables", \
        "[figures-and-tables]" not in out, out[-600:]
    checked = convert(folder, "--check-only")
    yield "a check-only run converts nothing", \
        checked.returncode == 0 and "each converted on its own" not in checked.stderr, \
        checked.stderr[-300:]
    alone = converted_folder(os.path.join(work, "alone"), "targets:\n  pages:\n    format: html\n")
    paged = convert(alone, "--quick")
    yield "with no format: source target, the decks are checked and converted, and no copy " \
        "is made", \
        paged.returncode == 0 and "Slides: 1 PowerPoint deck(s), each checked on its own, since " \
        "they're all this folder holds." in paged.stderr \
        and os.path.isfile(os.path.join(alone, "pages", "Reader.html")) \
        and sorted(n for n in os.listdir(alone) if n.endswith(".pptx")) == ["Reader.pptx"] \
        and not os.path.exists(os.path.join(alone, "remediated")), paged.stderr[:400]
    zipped = converted_folder(os.path.join(work, "zipped"), "targets:\n  pages:\n    format: html\n"
                              "    archive: zip\n  copy:\n    format: source\n    archive: zip\n")
    packed = convert(zipped, "--quick")
    names = []
    for name in ("pages.zip", "copy.zip"):
        if os.path.isfile(os.path.join(zipped, name)):
            with zipfile.ZipFile(os.path.join(zipped, name)) as z:
                names += z.namelist()
    yield "archive: zip packs the copy's folder and the page's when the decks are converted", \
        packed.returncode == 0 and "copy/Reader.pptx" in names and "pages/Reader.html" in names, \
        (names, packed.stderr[-300:])
    for name in ("pages.zip", "copy.zip"):
        os.remove(os.path.join(zipped, name))
    with open(os.path.join(zipped, "broken.pptx"), "wb") as fh:
        fh.write(b"not a deck")
    broken = convert(zipped, "--quick")
    yield "and with a deck that can't be read, the others are converted, nothing is archived, " \
        "and the run says so once", \
        broken.returncode == 1 and os.path.isfile(os.path.join(zipped, "pages", "Reader.html")) \
        and not any(os.path.exists(os.path.join(zipped, n)) for n in ("pages.zip", "copy.zip")) \
        and broken.stderr.count("nothing was archived") == 1, broken.stderr[-400:]


def case_converting_math(work):
    """A deck's math-repaired.csv when the decks are converted too: the
    copy's equations repaired and the page's repairs, its equations' and
    the text made an equation, each in TeX under the deck's name, a repair
    the copy and the page both make once; math-keep.csv's rows keeping
    them in both, by the deck's name, and a row that keeps nothing in
    either warned about."""
    if not pandoc_ok():
        return
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    deck(os.path.join(folder, "Two Words.pptx"), [
        {"shapes": [title(2, "Scores"), equation(4, Z_OMML)]},
        {"shapes": [title(2, "Means"),
                    textbox(5, "TextBox 5", ["The mean \u03bc = 34 here."],
                            (457200, 1600200, 4000000, 600000))]}])
    with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  pages:\n    format: html\n  copy:\n    format: source\n")
    report = os.path.join(folder, "math-repaired.csv")
    first = convert(folder, "--quick")
    rows = rows_of(report)
    yield "the report has the copy's equation and the page's text made an equation, in TeX, " \
        "under the deck's name, the equation once, as the page repaired it, though both did", \
        first.returncode == 0 and sorted(rows) == sorted([
            ["equation", "Two Words", Z_TEX, "z = \\frac{x-\u03bc}{\\sigma}"],
            ["expression", "Two Words", "\u03bc = 34", "\u03bc=34"]]), (rows, first.stderr[-600:])
    with open(os.path.join(folder, "math-keep.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Kind", "Page", "Before", "After"],
                                  ["equation", "Two Words", Z_TEX],
                                  ["equation", "Two Words", "z=(x\u2013\u00b5)/\u03c3"],
                                  ["expression", "Two Words", "\u03bc = 34"],
                                  ["symbol", "Two Words", "\u03b2"]])
    again = convert(folder, "--quick")
    page = html.unescape(open(os.path.join(folder, "pages", "Two-Words.html"),
                              encoding="utf-8").read()) \
        if os.path.exists(os.path.join(folder, "pages", "Two-Words.html")) else ""
    copy = os.path.join(folder, "copy", "Two Words.pptx")
    yield "rows copied from it keep the equation in the copy and on the page, and the text " \
        "as text, by the deck's name; the report is gone", \
        again.returncode == 0 and not os.path.exists(report) \
        and os.path.exists(copy) and "x–µ" in read_part(copy, "ppt/slides/slide1.xml") \
        and "The mean \u03bc = 34 here." in " ".join(re.sub(r"<[^>]+>", "", page).split()) \
        and "\u03bc=34" not in page, again.stderr[-800:]
    yield "and the row that kept nothing in either is warned about, the others not, one that " \
        "names the equation in one line, which keeps it in the copy alone, among them", \
        "1 row(s) of math-keep.csv kept nothing" in again.stderr \
        and "  symbol,Two Words,\u03b2" in again.stderr \
        and "  equation,Two Words" not in again.stderr \
        and "  expression,Two Words" not in again.stderr, again.stderr[-800:]


def case_display_paragraph(work):
    """A display paragraph of two equations, each a display of its own on
    the page, as the copy repairs it, so each has a row of its own in
    math-repaired.csv, and a row keeps that one in the copy and on the
    page; Pandoc's Word reader reads such a paragraph as one formula."""
    if not pandoc_ok():
        return
    folder = os.path.join(work, "decks")
    os.makedirs(folder)
    deck(os.path.join(folder, "Lines.pptx"), [
        {"shapes": [title(2, "Two Lines"),
                    display_paragraph(4, "<m:r><m:t>x\u2013\u00b5=1</m:t></m:r>",
                                      "<m:r><m:t>y=\u00b5</m:t></m:r>")]}])
    with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  pages:\n    format: html\n  copy:\n    format: source\n")
    report = os.path.join(folder, "math-repaired.csv")
    first = convert(folder, "--quick")
    page_path = os.path.join(folder, "pages", "Lines.html")
    page = html.unescape(open(page_path, encoding="utf-8").read()) \
        if os.path.exists(page_path) else ""
    annotations = re.findall(r'<annotation encoding="application/x-tex">([^<]*)</annotation>',
                             page)
    yield "each equation of the paragraph is a display of its own on the page, repaired, " \
        "where Pandoc's Word reader runs them together into one formula", \
        first.returncode == 0 and page.count('display="block"') == 2 \
        and annotations == ["x-\u03bc = 1", "y = \u03bc"], (annotations, first.stderr[-600:])
    rows = rows_of(report)
    intermediate = os.path.join(folder, "Lines.json")
    blocks = json.load(open(intermediate, encoding="utf-8"))["blocks"] \
        if os.path.exists(intermediate) else []
    yield "each a paragraph of its own, as Pandoc's PowerPoint writer writes it, so the deck " \
        "reads back the same", [b["t"] for b in blocks][1:] == ["Para", "Para"] \
        and all(len(b["c"]) == 1 and b["c"][0]["t"] == "Math" for b in blocks[1:]), blocks
    yield "and each has a row of its own in the report, the copy's and the page's once", \
        sorted(rows) == sorted([["equation", "Lines", "x\u2013\u00b5 = 1", "x-\u03bc = 1"],
                                ["equation", "Lines", "y = \u00b5", "y = \u03bc"]]), rows
    with open(os.path.join(folder, "math-keep.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Kind", "Page", "Before", "After"],
                                  ["equation", "Lines", "y = \u00b5"]])
    again = convert(folder, "--quick")
    page = html.unescape(open(page_path, encoding="utf-8").read()) \
        if os.path.exists(page_path) else ""
    copy = os.path.join(folder, "copy", "Lines.pptx")
    slide = read_part(copy, "ppt/slides/slide1.xml") if os.path.exists(copy) else ""
    yield "a row copied from it keeps its equation in the copy and on the page, the other " \
        "repaired in both, and nothing is warned about", \
        again.returncode == 0 and "<m:t>y=\u00b5</m:t>" in slide and "<m:t>x\u2212\u03bc=1" \
        in slide and re.findall(r'<annotation encoding="application/x-tex">([^<]*)</annotation>',
                                page) == ["x-\u03bc = 1", "y = \u00b5"] \
        and "kept nothing" not in again.stderr, (slide[-600:], again.stderr[-600:])


def case_math_pandoc_and_stop(work):
    """A deck's math report with a Pandoc older than a conversion needs,
    its equations written out in one line and the run saying why; and
    math-keep.csv's rows tried on the copies and said when the
    conversion stops before its pages are made."""
    if not pandoc_ok():
        return
    folder = os.path.join(work, "old")
    os.makedirs(folder)
    deck(os.path.join(folder, "maths.pptx"), [
        {"shapes": [title(2, "Scores"), equation(4, Z_OMML)]}])
    reports = {k: os.path.join(folder, v) for k, v in (
        ("image_alt_missing", "a.csv"), ("table_headers_new", "t.csv"),
        ("slide_titles_new", "s.csv"), ("slides_check", "check.csv"),
        ("output_check", "output-check.csv"), ("math_repaired", "math-repaired.csv"))}
    paths = {k: os.path.join(folder, v) for k, v in (
        ("image_alt", "image-alt.csv"), ("table_headers", "table-headers.csv"),
        ("slide_titles", "slide-titles.csv"), ("math_keep", "math-keep.csv"))}
    target = type("Target", (), {"format": "source", "name": "fixed",
                                 "output_dir": os.path.join(folder, "fixed"),
                                 "__getitem__": lambda self, key: key == "math.repair_equations"})()
    tools = os.path.join(work, "old-pandoc")
    os.makedirs(tools)
    with open(os.path.join(tools, "pandoc"), "w") as fh:
        fh.write("#!/bin/sh\necho 'pandoc 2.19.2'\n")
    os.chmod(os.path.join(tools, "pandoc"), 0o755)
    path, said = os.environ["PATH"], []
    os.environ["PATH"] = tools + os.pathsep + path
    del deckrun._tex_pandoc[:]
    try:
        code = deckrun.run(folder, ["maths.pptx"], [target], paths, reports, say=said.append)
    finally:
        os.environ["PATH"] = path
        del deckrun._tex_pandoc[:]
    yield "with a Pandoc older than 3.9 first on the PATH, a copies-only run's report has its " \
        "equations written out in one line, and the run says why", \
        code == 0 and rows_of(reports["math_repaired"]) == [
            ["equation", "maths", "z=(x\u2013\u00b5)/\u03c3", "z=(x\u2212\u03bc)/\u03c3"]] \
        and any(s.startswith("NOTE: Pandoc 2.19.2 is older than 3.9, so the copies' equations")
                for s in said), said
    said = []
    code = deckrun.run(folder, ["maths.pptx"], [target], paths, reports, say=said.append)
    yield "and with this one, TeX, and nothing said of Pandoc", code == 0 \
        and rows_of(reports["math_repaired"])[0][2] == Z_TEX \
        and not any("is older than" in s for s in said), \
        (rows_of(reports["math_repaired"]), said[-6:])
    stops = os.path.join(work, "stops")
    os.makedirs(stops)
    for name in ("Two Words.pptx", "Two-Words.pptx"):
        deck(os.path.join(stops, name), [{"shapes": [title(2, "Scores"), equation(4, Z_OMML)]}])
    with open(os.path.join(stops, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  pages:\n    format: html\n  copy:\n    format: source\n")
    with open(os.path.join(stops, "math-keep.csv"), "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([["Kind", "Page", "Before", "After"],
                                  ["equation", "Two Words", Z_TEX],
                                  ["equation", "Two Words", "q"],
                                  ["expression", "Two Words", "\u03bc = 34"]])
    stopped = convert(stops, "--quick")
    out = stopped.stderr
    yield "when the conversion stops after the copies are written, the keep sidecar's rows " \
        "that kept nothing in the copies are said, before the reason it stopped, and not a " \
        "row the copies can't keep", \
        stopped.returncode != 0 and "rows were tried on the copies alone" in out \
        and "  equation,Two Words,q" in out and "  equation,Two Words,z" not in out \
        and "  expression,Two Words" not in out \
        and out.find("tried on the copies alone") < out.find("would each be the same page"), \
        out[-900:]


def case_converting_more(work):
    """A PowerPoint deck's PDF, through ltx-talk, and its reveal.js
    presentation, as a deck written in Markdown has them."""
    if not pandoc_ok():
        return
    import decks
    problem = decks.ltx_talk_problem()
    if problem:
        print("  skip  %s; a PowerPoint deck's PDF isn't checked" % problem)
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    present = tuple(int(n) for n in re.findall(r"\d+", version)[:3]) >= (3, 12)
    if not present:
        print("  skip  Pandoc %s writes no reveal.js presentation; 3.12 or later does" % version)
    if problem and not present:
        return
    folder = converted_folder(work, "targets:\n" + ("" if problem else "  pdf:\n    format: pdf\n")
                              + ("  present:\n    format: revealjs\n" if present else ""))
    result = convert(folder, "--quick")
    out = result.stderr
    yield "the decks are converted as the targets say", result.returncode == 0, out[-600:]
    if not problem:
        sys.path.insert(0, HERE)
        import pdftext
        pdf = os.path.join(folder, "pdf", "Reader.pdf")
        text = " ".join(pdftext.marked_text(pdf).values()) \
            if os.path.isfile(pdf) and pdftext.pikepdf is not None else ""
        yield "a pdf target writes each deck's PDF through ltx-talk, its slides the deck's: " \
            "its title slide, a slide for each section, and the slides shown, no notes", \
            "Wrote 1 PDF(s)" in out and "through ltx-talk: 13 page(s)" in out \
            and "A Course of Talks" in text and "Ask who paid" not in text \
            and "Not shown." not in text, out[-600:]
    if present:
        page = os.path.join(folder, "present", "Reader.html")
        shown = open(page, encoding="utf-8").read() if os.path.isfile(page) else ""
        yield "a revealjs target writes each deck's presentation, its slides the deck's, its " \
            "notes in the speaker view", \
            "Wrote 1 presentation(s)" in out and '<aside class="notes">' in shown \
            and "Ask <strong>who</strong> paid." in shown and "Not shown." not in shown, \
            out[-600:]


def reference_deck(path):
    """Pandoc's own reference document, a template to rebuild on."""
    with open(path, "wb") as fh:
        fh.write(subprocess.run(["pandoc", "--print-default-data-file", "reference.pptx"],
                                capture_output=True).stdout)
    return path


def case_rebuild(work):
    """A pptx target on a PowerPoint deck, given a template, rebuilds the
    deck on it, and says what that loses."""
    if not pandoc_ok():
        return
    folder = converted_folder(work, "targets:\n  again:\n    format: pptx\n    slides:\n"
                                    "      reference_doc: template.pptx\n  plain:\n"
                                    "    format: pptx\n")
    reference_deck(os.path.join(folder, "template.pptx"))
    result = convert(folder, "--quick")
    out = result.stderr
    rebuilt = os.path.join(folder, "again", "Reader.pptx")
    yield "the deck is rebuilt on the template, and the run says what's lost and what it's for", \
        result.returncode == 0 and os.path.isfile(rebuilt) and "rebuilds 1 PowerPoint deck(s) " \
        "on slides.reference_doc, template.pptx" in out and "It's for moving decks onto a " \
        "template" in out, out[-900:]
    titles = [s.title for s in pptxparse.read(rebuilt).slides] if os.path.isfile(rebuilt) else []
    yield "its slides are the deck's, the title slide first", \
        titles[:3] == ["A Course of Talks", "Part One", "Formatting"], titles
    yield "and the target without one writes nothing", \
        "target plain is format pptx, and nothing is written for it" in out \
        and not os.path.exists(os.path.join(folder, "plain")), out[:600]
    alone = os.path.join(work, "alone")
    os.makedirs(alone)
    clean_deck(os.path.join(alone, "clean.pptx"))
    with open(os.path.join(alone, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  again:\n    format: pptx\n")
    result = convert(alone)
    yield "a run whose only target is a pptx target with no template stops, nothing written", \
        result.returncode != 0 and "Every target here is format pptx" in result.stderr \
        and not os.path.exists(os.path.join(alone, "slides-check.csv")), result.stderr[-400:]


def pptx_pandoc_ok():
    """Whether a deck written in Markdown can be written as PowerPoint here:
    Pandoc 3.10.1 or later (convert.py's PPTX_PANDOC)."""
    if not pandoc_ok():
        return False
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 10, 1):
        print(f"  skip  Pandoc {version} writes no deck's PowerPoint file; 3.10.1 or later does")
        return False
    return True


def case_round_trip(work):
    """The reader's check: a deck through the markdown target, that
    Markdown through a Markdown deck's pptx target, and the two decks
    compared slide by slide (deckcompare.py)."""
    import deckcompare
    yield "TeX is compared without the white space TeX doesn't read, a Greek letter's command " \
        "as the letter", \
        [deckcompare.tex_text(t) for t in ("\\sigma_{1}^{2} = \\sigma _ {2}^{2}",
                                           "\\mathrm{d} x", "\\alpha\\,\\beta")] \
        == ["σ_{1}^{2}=σ_{2}^{2}", "\\mathrm{d}x", "α\\,β"], None
    empty = {"t": "Table", "c": [["", [], []], [None, []], [], [["", [], []], [[["", [], []], [
        [["", [], []], {"t": "AlignDefault"}, 1, 1, []]]]]], [[["", [], []], 0, [], [[["", [], []], [
            [["", [], []], {"t": "AlignDefault"}, 1, 1, [{"t": "Plain", "c": [S("x")]}]]]]]]],
        [["", [], []], []]]}
    yield "and a table's empty header row, which a Markdown table can't hold, is none", \
        deckcompare.table(empty, {}) == ("table", 0, 0, [["x"]], ""), deckcompare.table(empty, {})
    broken = deckcompare.heading([S("Thanks"), {"t": "LineBreak"}, {"t": "LineBreak"},
                                  {"t": "Space"}, {"t": "LineBreak"}, S("Questions")], {})
    yield "a title's line breaks in a row are one space, as the Markdown's are when read back", \
        broken == "Thanks Questions", broken

    def made(title, *texts):
        slide = deckcompare.Slide(title, 0)
        slide.items = [("text", t) for t in texts]
        return slide

    def held(pairs):
        return [(slide and slide.title, [[t for _k, t in part.items] for part in parts])
                for slide, parts in pairs]
    untitled, titled = made("", "a", "b"), made("T", "a", "b")
    parted = [held(deckcompare.aligned([untitled], [made("", "a"), made("", "c")])),
              held(deckcompare.aligned([untitled], [made("", "a"), made("U", "b")])),
              held(deckcompare.aligned([titled], [made("T", "a"), made("", "b")]))]
    yield "a slide with no title has as its parts the untitled slides after it that go on with " \
        "what it holds, not another, nor a titled one; and a titled slide no untitled part", \
        parted == [[("", [["a"]]), (None, [["c"]])], [("", [["a"]]), (None, [["b"]])],
                   [("T", [["a"]]), (None, [["b"]])]], parted
    if not pptx_pandoc_ok():
        return
    folder = converted_folder(work, "targets:\n  md:\n    format: markdown\n")
    # Beside it, a deck the trip changes on its way, by design: a slide with
    # no title that the pptx target cuts after its picture, then two of
    # their own, one holding only notes, a title of two lines, two bold
    # lines a plain indent parts, and lists going on from a slide before,
    # each nested in an item and starting past one, one in the notes, which
    # the Markdown target writes from one with its start beside it; and a
    # link in the notes, which Pandoc's PowerPoint writer takes out.
    deck(os.path.join(folder, "Cut.pptx"), [
        {"shapes": [title(2, "Cut Apart", "ctrTitle", box=TITLE_BOX)]},
        {"shapes": [pic(2, "rId2", SPOT, "A red square"),
                    shape(3, "TextBox 2", [p(r("Words after it."))], box=SPOT4)],
         "images": {"rId2": RED}, "notes": "Said of both."},
        {"shapes": [], "notes": "A pause."},
        {"shapes": [shape(2, "TextBox 1", [p(r("Its own slide, before "), r("the results", click=(
            '<a:hlinkClick r:id="rId2" action="ppaction://hlinksldjump"/>')), r("."))], box=WIDE)],
         "slide_links": {"rId2": 5}},
        {"shapes": [shape(2, "Title 1", [p(r("Results"), BREAK, r("(Panel)"))],
                          ph='<p:ph type="title"/>'),
                    shape(3, "TextBox 2", [p(r("First", b="1"), r(" "), BREAK, r("   "),
                                             r("second", b="1"), ppr=PLAIN)], box=WIDE)]},
        {"shapes": [title(2, "Continued"), shape(3, "Content Placeholder 2", [
            p(r("Pluralism"), ppr=lvl(0, '<a:buAutoNum type="alphaUcPeriod" startAt="2"/>')),
            p(r("Third question"), ppr=lvl(1, '<a:buAutoNum type="arabicPeriod" startAt="3"/>')),
            p(r("Fourth question"), ppr=lvl(1, '<a:buAutoNum type="arabicPeriod" startAt="3"/>')),
            p(r("Regulation"), ppr=lvl(0, '<a:buAutoNum type="arabicPeriod" startAt="5"/>')),
            p(r("Labor"), ppr=lvl(1, '<a:buAutoNum type="alphaLcPeriod" startAt="2"/>')),
            p(r("Hiring"), ppr=lvl(2, '<a:buAutoNum type="romanLcPeriod"/>'))],
            ph='<p:ph idx="1"/>')],
         "notes": notes_of([p(r("Ask about"), ppr=lvl(0, '<a:buAutoNum type="arabicPeriod"/>')),
                            p(r("the third"), ppr=lvl(1, '<a:buAutoNum type="alphaLcPeriod" '
                                                         'startAt="3"/>')),
                            p(r("Source: "), r("the data", click='<a:hlinkClick r:id="rId3"/>',
                                               u="sng"), r("."), ppr=PLAIN)]),
         "notes_links": {"rId3": FIELD}}],
        master=bulleted_master())
    first = convert(folder, "--quick")
    trip = os.path.join(work, "trip")
    shutil.copytree(os.path.join(folder, "md"), trip)
    with open(os.path.join(trip, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.trip\n  title: Trip\n  kind: slides\n")
    with open(os.path.join(trip, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  decks:\n    format: pptx\n")
    second = convert(trip, "--quick")
    original = os.path.join(folder, "Reader.pptx")
    tripped = os.path.join(trip, "decks", "Reader.pptx")
    yield "the deck goes to Markdown and back to PowerPoint", \
        first.returncode == 0 and second.returncode == 0 and os.path.isfile(tripped), \
        (first.stderr + second.stderr)[-600:]
    if not os.path.isfile(tripped):
        return
    # The original as its conversion read it, with its sidecars' decisions.
    a = deckcompare.read(original, work, alts=rem.alt_rows(os.path.join(folder, "image-alt.csv")),
                         tables=rem.header_rows(os.path.join(folder, "table-headers.csv")),
                         titles=rem.title_rows(os.path.join(folder, "slide-titles.csv")),
                         orders=rem.order_rows(os.path.join(folder, "reading-order.csv")))
    b = deckcompare.read(tripped, work)
    found = deckcompare.compare(a, b)
    what = sorted((d.where, d.what) for d in found)
    yield "slide for slide, the same titles, text and its formatting, lists, tables, pictures " \
        "and their alt text, equations, and notes, but for what Pandoc's PowerPoint writer " \
        "doesn't write: a merged cell", \
        what == [("slide 5 (A Table)", "content")], found
    tips = [(l.text, l.target, l.tooltip) for s in pptxparse.read(tripped).slides
            for shape in s.all_shapes() for l in shape.links]
    yield "a link's ScreenTip comes back, which Pandoc's PowerPoint writer doesn't write and " \
        "the pptx target does", \
        ("the source", "https://example.org/data", "Where the data are") in tips, tips
    cells = next((d for d in found if d.where == "slide 5 (A Table)"), None)
    yield "and the table's, its merged cell", \
        cells is not None and cells.first[0][-1] == "spans" and cells.second[0][-1] == "", \
        cells
    cut_trip = os.path.join(trip, "decks", "Cut.pptx")
    cut_b = deckcompare.read(cut_trip, work) if os.path.isfile(cut_trip) else {"blocks": []}
    cut_found = deckcompare.compare(deckcompare.read(os.path.join(folder, "Cut.pptx"), work),
                                    cut_b)
    cut_titles = [s.title for s in deckcompare.slides_of(cut_b)[3]]
    yield "a deck the trip changes by design comes back the same: a slide with no title that " \
        "the target cut in two one slide again, and the slides after it their own, one holding " \
        "only notes; a title's line break a space, a link to its slide too; two bold lines one " \
        "bold either way; lists nested in an item and starting past one, as they were; and a " \
        "link in the notes", \
        cut_titles == ["", "", "", "", "Results (Panel)", "Continued"] and not cut_found, \
        (cut_titles, cut_found)
    cut_md = ""
    if os.path.isfile(os.path.join(folder, "md", "Cut.md")):
        with open(os.path.join(folder, "md", "Cut.md"), encoding="utf-8") as fh:
            cut_md = fh.read()
    yield "the Markdown writes such a list from one, its start an empty span at its first item, " \
        "and a list in no item from its own start", \
        "    1.  []{start=\"3\"}Third question" in cut_md \
        and "    a.  []{start=\"2\"}Labor" in cut_md and "B.  Pluralism" in cut_md \
        and "    a.  []{start=\"3\"}the third" in cut_md \
        and "5.  Regulation" in cut_md and "i.  Hiring" in cut_md, cut_md[-400:]
    yield "and the link in the notes as a link, underlined as Google Slides writes one", \
        "Source: [[the data]{.underline}](%s)." % FIELD in cut_md, cut_md[-400:]
    read_back = {}
    if os.path.isfile(os.path.join(trip, "Cut.filtered.json")):
        with open(os.path.join(trip, "Cut.filtered.json"), encoding="utf-8") as fh:
            read_back = json.load(fh)
    starts = [(b["c"][0][0], b["c"][0][1]["t"]) for b in of_kind(read_back, "OrderedList")]
    left = [s for s in of_kind(read_back, "Span") if any(k == "start" for k, _v in s["c"][0][2])]
    yield "and reading it back puts each start on its list and takes the span off", \
        starts == [(2, "UpperAlpha"), (3, "Decimal"), (5, "Decimal"), (2, "LowerAlpha"),
                   (1, "LowerRoman"), (1, "Decimal"), (3, "LowerAlpha")] and not left, \
        (starts, left)
    # The comparison sees what it's for: each of these changed in the deck
    # that made the trip is a difference, where it was made.
    changes = [("a picture's alt text", b'descr="New words"', b'descr="Other words"',
                ("slide 6 (Pictures)", "content")),
               ("a word's bold", b'<a:rPr b="1" lang="en"/><a:t>bold</a:t>',
                b'<a:rPr lang="en"/><a:t>bold</a:t>', ("slide 2 (Formatting)", "content")),
               ("a list's item", b"<a:t>Pears</a:t>", b"<a:t>Peers</a:t>",
                ("slide 3 (Lists)", "content")),
               ("a list's numbering", b'type="alphaLcParenR"', b'type="arabicPeriod"',
                ("slide 3 (Lists)", "content")),
               ("a table's cell", b"<a:t>2020</a:t>", b"<a:t>2021</a:t>",
                ("slide 5 (A Table)", "content")),
               ("an equation", b"<m:t>2</m:t>", b"<m:t>5</m:t>", ("slide 7 (Equations)", "content")),
               ("a word of the notes", b"<a:t> paid.</a:t>", b"<a:t> paused.</a:t>",
                ("slide 2 (Formatting)", "notes")),
               ("the subtitle", b"<a:t>Second line</a:t>", b"<a:t>Third line</a:t>",
                ("the title slide", "subtitle")),
               ("a slide's title", b"<a:t>Order</a:t>", b"<a:t>Sequence</a:t>",
                ("slide 11 (Order)", "a slide only the first deck has"),
                ("slide 18 of the second deck", "a slide only it has"))]
    before = {(d.where, d.what, repr(d.second)) for d in found}
    seen = []
    for n, (label, old, replacement, *where) in enumerate(changes):
        changed = os.path.join(work, "changed-%d.pptx" % n)
        made = 0
        with zipfile.ZipFile(tripped) as zin, zipfile.ZipFile(changed, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if re.match(r"ppt/(slides|notesSlides)/\w+\.xml$", info.filename):
                    made += data.count(old)
                    data = data.replace(old, replacement)
                zout.writestr(info, data)
        after = {(d.where, d.what, repr(d.second))
                 for d in deckcompare.compare(a, deckcompare.read(changed, work))}
        seen.append((label, made > 0, sorted({(w, k) for w, k, _ in after - before})))
    # util/round-trip-decks.py makes the same trip of a folder's decks.
    tool = subprocess.run(["python3", os.path.join(ROOT, "util", "round-trip-decks.py"), folder,
                           "--keep", os.path.join(work, "kept")], capture_output=True, text=True)
    yield "util/round-trip-decks.py makes the trip of a folder's decks and reports the same", \
        tool.returncode == 1 and "Reader.pptx: 1 difference(s)" in tool.stdout \
        and "Cut.pptx: the same" in tool.stdout and "slide 4 (Links)" not in tool.stdout \
        and "slide 5 (A Table), content:" in tool.stdout \
        and os.path.isfile(os.path.join(work, "kept", "trip", "decks", "Reader.pptx")), \
        (tool.stdout + tool.stderr)[-600:]
    # A folder whose sidecar Excel's plain "CSV" saved, in Windows-1252.
    ansi = os.path.join(work, "ansi-decks")
    os.makedirs(ansi)
    shutil.copy(os.path.join(folder, "Cut.pptx"), ansi)
    with open(os.path.join(ansi, "slide-titles.csv"), "w", encoding="cp1252", newline="") as fh:
        fh.write("Slide,Title,Source,Drafted by,Reviewed\r\nCut/slide-256,Caf\u00e9,,,\r\n")
    stopped = subprocess.run(["python3", os.path.join(ROOT, "util", "round-trip-decks.py"), ansi],
                             capture_output=True, text=True)
    yield "and stops on a sidecar that isn't UTF-8, naming the folder's own file and its line", \
        stopped.returncode != 0 and os.path.join(ansi, "slide-titles.csv") \
        + ": line 2 isn't UTF-8 (byte 0xE9)" in stopped.stderr \
        and "Traceback" not in stopped.stderr, stopped.stderr[-400:]
    yield "and each of these changed in the trip is a difference where it is: a picture's alt " \
        "text, a word's bold, a list's item and its numbering, a table's cell, an equation, a " \
        "word of the notes, the subtitle; and a slide's title changed leaves its slide " \
        "unmatched in each deck", \
        seen == [(label, True, sorted(where)) for label, _o, _n, *where in changes], seen


CASES = [("reading a deck", case_parse), ("the checks", case_check),
         ("captions on video and audio", case_captions),
         ("the copy", case_remediate), ("the copy, more", case_remediate_more),
         ("the sidecars", case_sidecars), ("what a review found", case_edges),
         ("what PowerPoint made of Pandoc's decks", case_powerpoint),
         ("the reading order", case_order), ("drafting an order", case_draft),
         ("titles another slide has", case_retitle),
         ("a heading made a slide's title", case_set_title),
         ("fonts a license restricts", case_fonts),
         ("links and equations", case_links),
         ("math kept as it was", case_math_keep),
         ("pictures cropped differently", case_crops),
         ("alt text copied from a web page", case_web_titles),
         ("alt text that is only a credit", case_credits),
         ("one alt text on different pictures", case_shared_alt),
         ("the file's lists of fonts and titles", case_app_properties),
         ("convert.py on decks", case_convert),
         ("folders, archives, and tools", case_folders),
         ("no Pandoc", case_no_pandoc),
         ("a deck read for converting", case_reader),
         ("convert.py converting decks", case_converting),
         ("convert.py converting decks, their math report", case_converting_math),
         ("a display paragraph of two equations", case_display_paragraph),
         ("a deck's math report with an old Pandoc, and a conversion that stops",
          case_math_pandoc_and_stop),
         ("each deck's language", case_deck_languages),
         ("a converted deck's PDF and presentation", case_converting_more),
         ("a deck rebuilt on a template", case_rebuild),
         ("the round trip", case_round_trip)]


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
