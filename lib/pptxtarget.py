"""
pptxtarget.py -- a deck written in Markdown made a PowerPoint file.

Pandoc's PowerPoint writer writes it from the deck's intermediate, after
target-blocks.lua and deck-pptx.lua, which works around what the writer
does with a deck as it reads it (see the filter). Here is the reference
document the writer takes the slides' size and look from (reference_doc),
the run of the writer (build), and what's put right in what it wrote
(finish), each read in Writers/Powerpoint/ at 3.12.1 and measured on the
writer's output:

- the reference document is Pandoc's own at PowerPoint's size for the
  slides' shape, 16:9 PowerPoint's Widescreen, 13.333 inches by 7.5, where
  Pandoc's is its older On-screen Show (16:9), 10 by 5.625
  (slides.size); and its tables take PowerPoint's Light Style 1 - Accent
  1, dark text on white and a pale blue, where Pandoc's reference
  document gives Medium Style 2 - Accent 1, whose header row's white on
  its theme's blue has a contrast of 4.0:1, under the 4.5:1 PowerPoint's
  Accessibility Checker asks for;
- each picture's description is its alt text, or it has PowerPoint's
  decorative mark and no description, in place of the title and file path
  the writer gives every picture (makePicElements); a caption that repeats
  its picture's alt text, as the deck's page hides one from a screen
  reader, has the decorative mark too;
- each shape's id is its own on its slide, where the writer gives every
  picture 0, every caption 1, which the slide's shape tree has, and every
  table 6;
- a table whose first column is its header has PowerPoint's First Column
  (firstCol), and the marker the filter put in its first cell is taken
  out;
- a table's caption is read before the table, as on the deck's page and
  in its PDF, and shown above it, as in the PDF, where the writer puts it
  under the table, read after it;
- a table taller than its room is set smaller, down to three quarters
  of its size (ten points of Pandoc's 13.5), so it fits, as it does in
  the PDF: the writer sets every table in the
  master's size, and PowerPoint doesn't shrink a table to fit. Its room
  ends at the slide's foot, or at the text the writer stacks under it,
  which it gives a share of the slide by its paragraphs and rows, not by
  what they need (shapesToElementsStacked); and a caption is as tall as
  its text;
- an incremental list's animation names the shape holding the list: the
  writer names each shape by its place among the slide's, so where a
  table's caption or text stacked around a table puts the list elsewhere,
  the animation named another shape, or none;
- text its shape can't hold at its size is shrunk to fit, as PowerPoint's
  "Shrink text on overflow" would shrink it, which the master asks of its
  placeholders (normAutofit) and PowerPoint does only once the text is
  edited: the scale it would record (fontScale, lnSpcReduction) is
  reckoned here and written;
- a bar over a letter, which Pandoc writes as an accent whose character
  is an overline (U+203E), is an accent of the macron (U+00AF), as a Word
  file's is: of six forms tried in PowerPoint, Narrator reads it
  "overbar", where it read the overline's as nothing, and LibreOffice
  draws it as a bar, where it drew the overline's as an acute accent;
  NVDA reads no accent's character in PowerPoint, and read the upper
  limit's macron only character by character, in the editor
  (2026-10-10 and 12);
- a display equation, and the paragraph after one, have half a line of
  space before them, where the writer gives them a paragraph's, a fifth:
  set off from the text around them, as on the page and in the PDF; but
  where the deck gives them space of its own that the writer keeps, an
  empty paragraph or a line break, which deck-pptx.lua looks for as it
  marks them, or at the top of a shape's text;
- vertical space the deck gives in raw LaTeX, which the writer leaves out
  (\\vspace, \\vskip, \\addvspace, \\smallskip, \\medskip, \\bigskip), is added to
  the space before the paragraph of text after it, in lines of the deck's
  PDF (11-point text 13.6 points apart): a display equation's half line,
  a paragraph's own, or its level's in the master; at the top of a
  shape's text, which PowerPoint gives no space before, the text body is
  told to respect it (spcFirstLastPara), and less than none is none;
- the deck's language is on every run and on the text styles every run
  inherits from, in place of the reference document's, since the writer
  writes no language;
- the file's title is the deck's (its title-meta, else its title, else its
  file's name), and its creator the authors alone, where an institute was
  put under them;
- the custom properties hold the deck's own fields alone: the writer
  writes every metadata field there, the pipeline's own and other
  writers' too;
- the slide titles and counts PowerPoint keeps in docProps/app.xml are
  the deck's, where the writer copies the reference document's;
- an SVG image, which the writer embeds as it is, where PowerPoint shows a
  picture that has a PNG beside its SVG, is a PNG with the SVG beside it,
  as PowerPoint itself inserts an SVG;
- a shape or table holding an equation has a fallback, which a program
  that reads no PowerPoint equations shows (LibreOffice, for one), each
  equation written there as a line of text (x̄ = 1/n∑xᵢ): the writer gives
  such a shape none, so the program showed nothing of it, its other words
  too, as PowerPoint gives one a picture of each equation;
- and what PowerPoint can't read as written is put right
  (pptxremediate.repair_part): a shape element with nothing in it, and an
  equation in a table's cell, whose prefix the writer doesn't declare.

What can't be put right is counted: slides on which the writer placed
shapes over one another, as it places every picture of a slide in one
place; the blocks it says it didn't write; the layouts a reference
document lacks, for which it takes its own; and its other warnings.

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

import html
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from urllib.parse import unquote

import decks
import docxtarget
import pptxorder
import pptxparse
import pptxremediate

ATTRS = pptxorder.ATTRS
_attr_value = pptxremediate._attr_value
_set_attr = pptxremediate._set_attr

# --------------------------------------------------------------------------
# the reference document
# --------------------------------------------------------------------------

# The sizes PowerPoint gives the shapes it names, as it writes them in
# presentation.xml (p:sldSz and its type) and docProps/app.xml: 4:3 and
# 16:10 ten inches wide, and 16:9 its Widescreen, 13.333 inches by 7.5,
# the size of a new deck since PowerPoint 2013, which it writes with no
# type; or, with slides.size on-screen-show, its older On-screen Show
# (16:9), ten inches by 5.625, Pandoc's reference document's. A slide of
# another shape is ten inches wide and as tall as its ratio makes it.
WIDTH = 9144000
SIZES = {(4, 3): (9144000, 6858000, "screen4x3", "On-screen Show (4:3)"),
         (16, 9): (12192000, 6858000, None, "Widescreen"),
         (16, 10): (9144000, 5715000, "screen16x10", "On-screen Show (16:10)")}
ON_SCREEN_SHOW = {(16, 9): (9144000, 5143500, "screen16x9", "On-screen Show (16:9)")}
SLIDE_SIZE = re.compile(r"<p:sldSz" + ATTRS + r"(/?)>")
POSITION = re.compile(r"<a:(off|ext|chOff|chExt)" + ATTRS + r"(/?)>")
# What a text's size and measures are given in, scaled with it: a run's
# size and spacing (hundredths of a point), a paragraph's margins and tab
# size, a text body's insets, and a line's width (EMU).
TEXT_MEASURES = [
    (re.compile(r"<a:(rPr|defRPr|endParaRPr)" + ATTRS + r"(/?)>"), ("sz", "spc", "kern")),
    (re.compile(r"<a:(pPr|lvl[1-9]pPr)" + ATTRS + r"(/?)>"), ("marL", "indent", "defTabSz")),
    (re.compile(r"<a:(bodyPr)" + ATTRS + r"(/?)>"), ("lIns", "tIns", "rIns", "bIns")),
    (re.compile(r"<a:(spcPts)" + ATTRS + r"(/?)>"), ("val",)),
    (re.compile(r"<a:(tab)" + ATTRS + r"(/?)>"), ("pos",)),
    (re.compile(r"<a:(ln)" + ATTRS + r"(/?)>"), ("w",)),
]


def slide_size(ratio, size="widescreen"):
    """(width, height, the size's type or None, PowerPoint's name for it)
    in EMU, for a ratio as slides.aspect_ratio gives one (16:9, 1.41:1),
    and size as slides.size does (widescreen, on-screen-show)."""
    match = decks.RATIO.match(ratio)
    w, h = float(match.group(1)), float(match.group(2))
    sizes = {**SIZES, **ON_SCREEN_SHOW} if size == "on-screen-show" else SIZES
    for (a, b), found in sizes.items():
        if abs(w * b - h * a) < 1e-9:
            return found
    return WIDTH, int(round(WIDTH * h / w)), None, "Custom"


def _times(attrs, keys, factor):
    """A start tag's attributes with each of keys that's a number scaled."""
    for key in keys:
        value = _attr_value(attrs, key)
        if value is not None and re.fullmatch(r"-?\d+", value):
            attrs = _set_attr(attrs, key, str(int(round(int(value) * factor))))
    return attrs


def _scaled(xml, across, down, text):
    """A part's shapes scaled: their places and widths across the slide by
    across, down it and their heights by down, and their text's sizes and
    measures by text."""
    def place(match):
        name, attrs, close = match.groups()
        keys = (("x", across), ("y", down)) if name in ("off", "chOff") else \
            (("cx", across), ("cy", down))
        for key, factor in keys:
            attrs = _times(attrs, (key,), factor)
        return "<a:%s%s%s>" % (name, attrs, close)
    if (across, down) != (1, 1):
        xml = POSITION.sub(place, xml)
    if text != 1:
        for pattern, keys in TEXT_MEASURES:
            xml = pattern.sub(lambda m, keys=keys: "<a:%s%s%s>" % (
                m.group(1), _times(m.group(2), keys, text), m.group(3)), xml)
    return xml


def _show_name(xml, name):
    return re.sub(r"<PresentationFormat>[^<]*</PresentationFormat>",
                  lambda _m: "<PresentationFormat>%s</PresentationFormat>" % name, xml, count=1)


def reference_doc(ratio, out, size="widescreen"):
    """Pandoc's own reference document (16:9) as a reference document for
    slides of ratio, written to out, at PowerPoint's size for the ratio
    (SIZES, or with size on-screen-show ON_SCREEN_SHOW): each placeholder
    on its layouts and master as far across and down them, and as wide and
    tall, in proportion, and their text as large as the slides' height and
    width both allow, as PowerPoint scales a deck's slides when their size
    changes ("Ensure Fit"). So a 4:3 deck's title is 274638 EMU down, where
    PowerPoint's own 4:3 has it, in Pandoc's 33 points, and a 16:9 deck is
    Pandoc's enlarged a third, Widescreen, its title 44 points and its text
    32. Its tables take a style of PowerPoint's own whose text has the
    contrast PowerPoint's checker asks for (TABLE_STYLE), where Pandoc's
    reference document's default has 4.0:1 in a table's header row."""
    data = subprocess.run(["pandoc", "--print-default-data-file", "reference.pptx"],
                          capture_output=True, check=True).stdout
    width, height, kind, name = slide_size(ratio, size)
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        infos = zin.infolist()
        parts = {info.filename: zin.read(info.filename) for info in infos}
    presentation = parts["ppt/presentation.xml"].decode("utf-8")
    found = SLIDE_SIZE.search(presentation)
    across = width / int(_attr_value(found.group(1), "cx"))
    down = height / int(_attr_value(found.group(1), "cy"))
    text = min(across, down)
    attrs = _set_attr(_set_attr(found.group(1), "cx", str(width)), "cy", str(height))
    attrs = _set_attr(attrs, "type", kind)
    presentation = (presentation[:found.start()] + "<p:sldSz%s%s>" % (attrs, found.group(2))
                    + presentation[found.end():])
    # The text styles a text box outside a placeholder takes.
    parts["ppt/presentation.xml"] = _scaled(presentation, 1, 1, text).encode("utf-8")
    for part in parts:
        if re.match(r"ppt/(slideMasters|slideLayouts|slides)/[^/]+\.xml$", part):
            parts[part] = _scaled(parts[part].decode("utf-8"), across, down, text).encode("utf-8")
    # The default table style, which the writer gives every table.
    styles = parts["ppt/tableStyles.xml"].decode("utf-8")
    parts["ppt/tableStyles.xml"] = re.sub(
        r'(<a:tblStyleLst\b[^>]*?\sdef=")[^"]*(")', lambda m: m.group(1) + TABLE_STYLE + m.group(2),
        styles, count=1).encode("utf-8")
    if "docProps/app.xml" in parts:
        parts["docProps/app.xml"] = _show_name(parts["docProps/app.xml"].decode("utf-8"),
                                               name).encode("utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in infos:
            zout.writestr(info, parts[info.filename])
    return out


# --------------------------------------------------------------------------
# a table's contrast
# --------------------------------------------------------------------------

# PowerPoint's built-in table styles, by their ids, as LibreOffice names
# and builds them (oox/source/drawingml/table/predefined-table-styles.cxx,
# after ECMA-376's presetTableStyles.xml): each family's style with no
# accent, then its Accent 1 to 6.
STYLE_FAMILIES = {
    "Themed Style 1": "2D5ABB26-0587-4C30-8999-92F81FD0307C 3C2FFA5D-87B4-456A-9821-1D502468CF0F "
                      "284E427A-3D55-4303-BF80-6455036E1DE7 69C7853C-536D-4A76-A0AE-DD22124D55A5 "
                      "775DCB02-9BB8-47FD-8907-85C794F793BA 35758FB7-9AC5-4552-8A53-C91805E547FA "
                      "08FB837D-C827-4EFA-A057-4D05807E0F7C",
    "Themed Style 2": "5940675A-B579-460E-94D1-54222C63F5DA D113A9D2-9D6B-4929-AA2D-F23B5EE8CBE7 "
                      "18603FDC-E32A-4AB5-989C-0864C3EAD2B8 306799F8-075E-4A3A-A7F6-7FBC6576F1A4 "
                      "E269D01E-BC32-4049-B463-5C60D7B0CCD2 327F97BB-C833-4FB7-BDE5-3F7075034690 "
                      "638B1855-1B75-4FBE-930C-398BA8C253C6",
    "Light Style 1": "9D7B26C5-4107-4FEC-AEDC-1716B250A1EF 3B4B98B0-60AC-42C2-AFA5-B58CD77FA1E5 "
                     "0E3FDE45-AF77-4B5C-9715-49D594BDF05E C083E6E3-FA7D-4D7B-A595-EF9225AFEA82 "
                     "D27102A9-8310-4765-A935-A1911B00CA55 5FD0F851-EC5A-4D38-B0AD-8093EC10F338 "
                     "68D230F3-CF80-4859-8CE7-A43EE81993B5",
    "Light Style 2": "7E9639D4-E3E2-4D34-9284-5A2195B3D0D7 69012ECD-51FC-41F1-AA8D-1B2483CD663E "
                     "72833802-FEF1-4C79-8D5D-14CF1EAF98D9 F2DE63D5-997A-4646-A377-4702673A728D "
                     "17292A2E-F333-43FB-9621-5CBBE7FDCDCB 5A111915-BE36-4E01-A7E5-04B1672EAD32 "
                     "912C8C85-51F0-491E-9774-3900AFEF0FD7",
    "Light Style 3": "616DA210-FB5B-4158-B5E0-FEB733F419BA BC89EF96-8CEA-46FF-86C4-4CE0E7609802 "
                     "5DA37D80-6434-44D0-A028-1B22A696006F 8799B23B-EC83-4686-B30A-512413B5E67A "
                     "ED083AE6-46FA-4A59-8FB0-9F97EB10719F BDBED569-4797-4DF1-A0F4-6AAB3CD982D8 "
                     "E8B1032C-EA38-4F05-BA0D-38AFFFC7BED3",
    "Medium Style 1": "793D81CF-94F2-401A-BA57-92F5A7B2D0C5 B301B821-A1FF-4177-AEE7-76D212191A09 "
                      "9DCAF9ED-07DC-4A11-8D7F-57B35C25682E 1FECB4D8-DB02-4DC6-A0A2-4F2EBAE1DC90 "
                      "1E171933-4619-4E11-9A3F-F7608DF75F80 FABFCF23-3B69-468F-B69F-88F6DE6A72F2 "
                      "10A1B5D5-9B99-4C35-A422-299274C87663",
    "Medium Style 2": "073A0DAA-6AF3-43AB-8588-CEC1D06C72B9 5C22544A-7EE6-4342-B048-85BDC9FD1C3A "
                      "21E4AEA4-8DFA-4A89-87EB-49C32662AFE0 F5AB1C69-6EDB-4FF4-983F-18BD219EF322 "
                      "00A15C55-8517-42AA-B614-E9B94910E393 7DF18680-E054-41AD-8BC1-D1AEF772440D "
                      "93296810-A885-4BE3-A3E7-6D5BEEA58F35",
    "Medium Style 3": "8EC20E35-A176-4012-BC5E-935CFFF8708E 6E25E649-3F16-4E02-A733-19D2CDBF48F0 "
                      "85BE263C-DBD7-4A20-BB59-AAB30ACAA65A EB344D84-9AFB-497E-A393-DC336BA19D2E "
                      "EB9631B5-78F2-41C9-869B-9F39066F8104 74C1A8A3-306A-4EB7-A6B1-4F7E0EB9C5D6 "
                      "2A488322-F2BA-4B5B-9748-0D474271808F",
}
STYLES = {"{%s}" % guid: (family, n) for family, guids in STYLE_FAMILIES.items()
          for n, guid in enumerate(guids.split())}
# A family's header row: its text's color and its fill's, each a theme
# color, "accent" its accent (the style with none: dk1), the fill None for
# none, the slide's background, taken as lt1. A family whose header is
# drawn with a tint, a shade, or a transparency (Medium Style 4, the dark
# styles), or the themed styles with no accent, isn't judged.
HEADERS = {"Themed Style 1": ("lt1", "accent"), "Themed Style 2": ("lt1", "accent"),
           "Light Style 1": ("dk1", None), "Light Style 2": ("lt1", "accent"),
           "Light Style 3": ("accent", None), "Medium Style 1": ("lt1", "accent"),
           "Medium Style 2": ("lt1", "accent"), "Medium Style 3": ("lt1", "accent")}
# Pandoc's reference document's default, and Office's: Medium Style 2 -
# Accent 1, a header row of white on Accent 1, which in Pandoc's theme
# (Office 2007's colors) is 4.0:1; and the style ours takes, Light Style 1
# - Accent 1, a header row of the theme's dark text in bold over a rule in
# Accent 1, its rows banded in a pale Accent 1.
MEDIUM_STYLE_2 = "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"
TABLE_STYLE = "{3B4B98B0-60AC-42C2-AFA5-B58CD77FA1E5}"
# What WCAG 2's 1.4.3 asks of text under 18 points, or 14 in bold, and
# PowerPoint's Accessibility Checker of a slide's text.
CONTRAST = 4.5


def _linear(channel):
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast(first, second):
    """WCAG 2's contrast ratio of two colors given as six hex digits."""
    def luminance(color):
        r, g, b = (_linear(int(color[i:i + 2], 16)) for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def theme_color(theme, slot):
    """A theme's color in a slot (dk1, lt1, accent1, ...) as six hex
    digits, or None: an sRGB color's value, a system color's last."""
    found = re.search(r"<a:%s>(.*?)</a:%s>" % (slot, slot), theme, re.S)
    if found is None:
        return None
    value = re.search(r'<a:srgbClr\b[^>]*?\sval="([0-9A-Fa-f]{6})"', found.group(1)) or \
        re.search(r'<a:sysClr\b[^>]*?\slastClr="([0-9A-Fa-f]{6})"', found.group(1))
    return value.group(1).upper() if value else None


def table_contrast(path):
    """(the style's name, its header row's text color, its fill's, their
    contrast) for a reference document's default table style, which the
    writer gives every table, when it's one of PowerPoint's whose header
    row is one theme color on another (HEADERS); else None."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        styles = z.read("ppt/tableStyles.xml").decode("utf-8", "replace") \
            if "ppt/tableStyles.xml" in names else ""
        theme = next((z.read(n).decode("utf-8", "replace") for n in sorted(names)
                      if re.match(r"ppt/theme/theme\d+\.xml$", n)), "")
    default = re.search(r'<a:tblStyleLst\b[^>]*?\sdef="([^"]*)"', styles)
    style = STYLES.get(default.group(1).upper()) if default else None
    if style is None or style[0] not in HEADERS or (style[1] == 0 and "Themed" in style[0]):
        return None
    family, n = style
    accent = "accent%d" % n if n else "dk1"
    text, fill = (accent if slot == "accent" else slot or "lt1" for slot in HEADERS[family])
    colors = theme_color(theme, text), theme_color(theme, fill)
    if None in colors:
        return None
    name = family + (" - Accent %d" % n if n else "")
    return (name,) + colors + (contrast(*colors),)


def reference_size(path):
    """(width, height) of a reference document's slides, in EMU."""
    with zipfile.ZipFile(path) as z:
        size = SLIDE_SIZE.search(z.read("ppt/presentation.xml").decode("utf-8", "replace"))
    if size is None:
        return None
    return int(_attr_value(size.group(1), "cx") or 0), int(_attr_value(size.group(1), "cy") or 0)


# --------------------------------------------------------------------------
# the writer
# --------------------------------------------------------------------------

# rsvg-convert fits an SVG in this many pixels each way: 192 to the inch
# across a slide ten inches wide, for a version of PowerPoint, or another
# program, that shows the PNG.
SVG_PIXELS = 1920


def svgs_to_png(doc, base, out_dir):
    """Each local SVG image made a PNG in out_dir with rsvg-convert, and the
    image pointed at it by its absolute path, as decks.svgs_to_pdf does for
    the PDF. Returns ({PNG's path: SVG's path}, [(src, why it failed)])."""
    made, failed, done = {}, [], {}

    def one(node):
        if node.get("t") != "Image" or not decks.is_svg(node["c"][2][0]):
            return
        target = node["c"][2]
        src = target[0]
        if src not in done:
            out = os.path.join(out_dir, "svg-%d.png" % len(done))
            source = os.path.join(base, unquote(src))
            why = None
            if not os.path.isfile(source):
                why = "there's no such file"
            elif shutil.which("rsvg-convert") is None:
                why = "rsvg-convert isn't installed"
            else:
                run = subprocess.run(["rsvg-convert", "-f", "png", "-w", str(SVG_PIXELS),
                                      "-h", str(SVG_PIXELS), "-a", "-o", out, source],
                                     capture_output=True, text=True, errors="replace",
                                     stdin=subprocess.DEVNULL)
                if run.returncode:
                    why = "rsvg-convert: " + (" ".join(run.stderr.split())[:120]
                                              or "exit %d" % run.returncode)
            done[src] = None if why else out
            if why:
                failed.append((src, why))
            else:
                made[out] = os.path.abspath(source)
        if done[src]:
            target[0] = done[src]
    decks.visit(doc.get("blocks", []), one)
    return made, failed


# What the writer says it didn't write, in its log (--log): a third column,
# what follows a slide's columns in its columns div, a table in a list,
# raw HTML or LaTeX. Pandoc gives these as information, which it prints
# only with --verbose.
NOT_RENDERED = ("BlockNotRendered", "InlineNotRendered")
LAYOUT_NAMED = re.compile(r'layout named "([^"]+)"')


def build(intermediate, base, out, *, filters, reference, level, language, title,
          notes="collapsed", env=None):
    """One deck's PowerPoint file, out, from its filtered intermediate:
    Pandoc's PowerPoint writer with filters and reference (reference_doc,
    or slides.reference_doc), at the deck's slide level, then finish(),
    with language and title (the deck's file's name, for a deck with no
    title). notes is slides.notes. Returns a dict: ok; log, Pandoc's
    errors; svg_failed, the SVGs that couldn't be made PNGs and why;
    not_rendered, what Pandoc said it didn't write, each ("block" or
    "inline", what it said); layouts, those the reference document lacks,
    which the writer took from its own; warnings, the writer's others;
    record, what the filter recorded; finish's counts and notes; slides;
    overlaps, the numbers of the slides whose shapes overlap."""
    with open(intermediate, encoding="utf-8") as fh:
        doc = json.load(fh)
    result = {"ok": False, "log": "", "svg_failed": [], "not_rendered": [], "layouts": [],
              "warnings": [], "record": {}, "counts": {}, "notes": [], "slides": 0,
              "overlaps": [], "pptx": out}
    work = tempfile.mkdtemp(prefix="deck-pptx-")
    try:
        svgs, result["svg_failed"] = svgs_to_png(doc, base, work)
        if result["svg_failed"]:
            return result
        source = intermediate
        if svgs:
            source = os.path.join(work, "deck.json")
            with open(source, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
        record_path, log_path = os.path.join(work, "record.json"), os.path.join(work, "log.json")
        command = ["pandoc", "-f", "json", "-t", "pptx", source, "-o", out,
                   "--reference-doc", reference, "--slide-level", str(level),
                   "--log", log_path]
        for path in filters:
            command += ["--lua-filter", path]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        done = subprocess.run(command, cwd=base, capture_output=True, text=True,
                              env=dict(env or os.environ, DECK_PPTX_RECORD=record_path,
                                       DECK_SLIDE_LEVEL=str(level), DECK_NOTES=str(notes)))
        if done.returncode:
            result["log"] = done.stderr
            return result
        try:
            with open(log_path, encoding="utf-8") as fh:
                log = json.load(fh)
        except (OSError, ValueError):
            log = []
        result["not_rendered"] = [
            ("inline" if entry.get("type") == "InlineNotRendered" else "block",
             " ".join(str(entry.get("pretty", "")).split())[:100])
            for entry in log if entry.get("type") in NOT_RENDERED]
        # A reference document without a layout the writer looks for by
        # name, whose slides it gives its own; and its other warnings.
        result["layouts"] = sorted({m.group(1) for entry in log
                                    if entry.get("type") == "PowerpointTemplateWarning"
                                    for m in [LAYOUT_NAMED.search(str(entry.get("pretty", "")))]
                                    if m})
        result["warnings"] = sorted({" ".join(str(entry.get("pretty", "")).split())[:160]
                                     for entry in log if entry.get("verbosity") == "WARNING"
                                     and entry.get("type") != "PowerpointTemplateWarning"})
        with open(record_path, encoding="utf-8") as fh:
            result["record"] = json.load(fh)
        result["counts"] = finish(out, result["record"], language=language, title=title,
                                  svgs=svgs, notes=result["notes"])
        deck = pptxparse.read(out)
        result["slides"] = len(deck.slides)
        result["overlaps"] = overlapping(deck)
        result["ok"] = True
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------
# what the writer wrote, put right
# --------------------------------------------------------------------------

CNVPR = pptxremediate.CNVPR
CNVPR_ID = re.compile(r'(<p:cNvPr\b[^>]*?\sid=")(\d+)(")')
PICTURE = re.compile(r"oer-pic-(\d+)\s*(.*)", re.S)
TABLE_MARK = re.compile("\ue000oer-tbl-(\\d+)\ue001")
# A run holding nothing, as the marker's is when it held only the marker.
EMPTY_RUN = re.compile(r"<a:r>(?:<a:rPr" + ATTRS + r"/>|<a:rPr" + ATTRS
                       + r">(?:(?!</a:rPr>).)*</a:rPr>)?<a:t" + ATTRS + r"(?:/>|></a:t>)</a:r>",
                       re.S)
TBLPR = pptxremediate.TBLPR
OFFSET = re.compile(r"<a:off" + ATTRS + r"(/?)>")
EXTENT = re.compile(r"<a:ext" + ATTRS + r"(/?)>")
BLIP = re.compile(r"<a:blip" + ATTRS + r"(/?)>")
SVG_BLIP = ('<a:extLst><a:ext uri="{96DAC541-7B7A-43D3-8B79-37D633B846F1}">'
            '<asvg:svgBlip xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main"'
            ' r:embed="%s"/></a:ext></a:extLst>')
IMAGE_RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
LANG_TAG = re.compile(r"<a:(defRPr|rPr|endParaRPr)" + ATTRS + r"(/?)>")
TABLE_ROW = re.compile(r"<a:tr\b[^>]*>(.*?)</a:tr>", re.S)
TABLE_CELL = re.compile(r"<a:tc\b([^>]*)>(.*?)</a:tc>", re.S)
GRID_COLUMN = re.compile(r'<a:gridCol\b[^>]*?\sw="(\d+)"')
PARAGRAPH = re.compile(r"<a:p\b[^>]*?(?:/>|>(.*?)</a:p>)", re.S)
SHOWN_TEXT = re.compile(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>|<m:t(?:\s[^>]*)?>([^<]*)</m:t>")
RUN_PROPERTIES = re.compile(r"<a:(rPr|endParaRPr)" + ATTRS + r"(/?)>")
PARAGRAPH_PROPERTIES = re.compile(r"<a:pPr" + ATTRS + r"(/?)>")
# Text in a table's cell as PowerPoint sets it: inset a tenth of an inch at
# each side and a twentieth above and below, a line 1.2 times its size,
# and a character half its size wide on average (Calibri's digits are
# 0.507 of it, its lowercase letters narrower). A table's text is the
# master's size for text that isn't a placeholder's (otherStyle), as
# LibreOffice draws it; set smaller to fit, these are the parts of that
# size tried, down to three quarters of it (10 points of Pandoc's 13.5), a
# table reaching to a little over a thirtieth of the slide's height above
# its foot (a fifth of an inch on Pandoc's slide), past its layout's
# content, where the writer puts no footer.
CELL_SIDES, CELL_ENDS = 182880, 91440
TABLE_FOOT = 182880 / 5143500
LINE, CHARACTER = 1.2, 0.5
TABLE_STEPS = (12 / 13.5, 11 / 13.5, 10 / 13.5)
EMU_PER_POINT = 12700
# The metadata a deck's file holds that isn't the deck's own field: the
# pipeline's, what another writer reads (Pandoc's manual's variables for
# HTML, HTML slides, beamer, and LaTeX), what the PowerPoint writer shows
# or reads itself, and Pandoc's options given in a YAML block.
NOT_PROPERTIES = frozenset("""
    deck-slide-level title-heading title-index title-id title-from title-meta page-type
    page-role page-position page-part page-parents source-page source-title heading-offset
    has-frontmatter language pagetitle title-prefix linkcolordark header-includes
    include-before include-after css toc toc-depth toc-title numbersections
    subtitle date institute notes notes-title monofont abstract abstract-title
    slide-level pdf-engine pdf-engine-opt highlight-style syntax-highlighting
    incremental reference-doc reference-location
    backgroundcolor backgroundcolordark document-css fontcolor fontcolordark fontsize
    linestretch linkcolor mainfont margin-bottom margin-left margin-right margin-top
    maxwidth monobackgroundcolor monobackgroundcolordark quotebordercolor
    quotebordercolordark quotecolor quotecolordark
    highlightjs-theme revealjs-url s5-url slideous-url slidy-url title-slide-attributes
    theme transition
    aspectratio beameroption colortheme colorthemeoptions fonttheme fontthemeoptions
    innertheme innerthemeoptions logo logooptions navigation outertheme
    outerthemeoptions section-titles shortauthor shortdate shortinstitute
    shortsubtitle shorttitle themeoptions titlegraphic titlegraphicoptions
    CJKmainfont CJKmonofont CJKoptions CJKsansfont babelfonts babeloptions beamerarticle
    biblatexoptions biblio-style biblio-title bibliography block-headings boxlinks
    citecolor classoption colorlinks csquotes csquotesoptions documentclass filecolor
    fontenc fontfamily fontfamilyoptions geometry handout hyperrefoptions indent
    links-as-notes lof lot luatexjapresetoptions mainfontfallback mainfontoptions
    mathfont mathfontoptions microtypeoptions monofontfallback monofontoptions
    natbiboptions pagestyle papersize pdf-trailer-id pdfstandard sansfont
    sansfontfallback sansfontoptions secnumdepth shorthands thanks toccolor urlcolor
    urlstyle
""".split())


def bar_accents(xml):
    """xml with each of Pandoc's bar accents, an accent of the overline
    (U+203E), which Narrator reads nothing for and LibreOffice draws as an
    acute accent, given the macron (U+00AF), as a Word file's is (round 6's
    form E, docxtarget.bar_accents): Narrator reads it "overbar", and
    LibreOffice draws a bar. NVDA reads no accent's character in
    PowerPoint, the macron's or another. (xml, count)."""
    return docxtarget.bar_accents(xml)


def relanguage(xml, language):
    """xml with language on every run's, paragraph end's, and default's
    properties, whatever they said: (xml, count changed)."""
    count = 0

    def one(match):
        nonlocal count
        name, attrs, close = match.groups()
        if _attr_value(attrs, "lang") == language:
            return match.group(0)
        count += 1
        return "<a:%s%s%s>" % (name, _set_attr(attrs, "lang", language), close)
    return LANG_TAG.sub(one, xml), count


def unique_ids(xml):
    """A slide with each shape's id its own, the first of each kept and
    the writer's 0 and every later copy given the next id free: (xml,
    count changed). An animation names its shape by its id; the writer's
    names a text shape's, which keeps it, as the first with its id."""
    used = {int(m.group(2)) for m in CNVPR_ID.finditer(xml)}
    seen, count, free = set(), 0, [max(used | {1}) + 1]

    def one(match):
        nonlocal count
        number = int(match.group(2))
        if number and number not in seen:
            seen.add(number)
            return match.group(0)
        while free[0] in used:
            free[0] += 1
        used.add(free[0])
        seen.add(free[0])
        count += 1
        return match.group(1) + str(free[0]) + match.group(3)
    return CNVPR_ID.sub(one, xml), count


def _cnvpr(piece):
    """(start, end) of a piece's first p:cNvPr element, or None."""
    match = CNVPR.search(piece)
    if match is None:
        return None
    end = match.end()
    if not match.group(2):
        close = piece.find("</p:cNvPr>", end)
        end = close + len("</p:cNvPr>") if close >= 0 else end
    return match.start(), end


def _is_caption(piece):
    """Whether a piece of a slide's tree is a caption the writer made: a
    text box it names TextBox 3 (createCaption)."""
    span = _cnvpr(piece)
    return bool(span) and _attr_value(CNVPR.match(piece, span[0]).group(1), "name") == "TextBox 3" \
        and 'txBox="1"' in piece[span[1]:span[1] + 200]


def _marked(piece, decorative):
    """A piece with its first cNvPr given the decorative mark and no
    description, or its description alone when decorative is a string."""
    span = _cnvpr(piece)
    if span is None:
        return piece
    alt = None if decorative is True else decorative
    element = pptxremediate._rewrite_cnvpr(piece[span[0]:span[1]], alt, decorative is True)
    return piece[:span[0]] + element + piece[span[1]:]


def _extent(piece):
    """A piece's first extent with a size: not an extension, also a:ext."""
    return next((m for m in EXTENT.finditer(piece) if _attr_value(m.group(1), "cx")), None)


def _place(piece):
    """(x, y, cx, cy) of a piece's first offset and extent, or None."""
    off, ext = OFFSET.search(piece), _extent(piece)
    if off is None or ext is None:
        return None
    values = [_attr_value(off.group(1), "x"), _attr_value(off.group(1), "y"),
              _attr_value(ext.group(1), "cx"), _attr_value(ext.group(1), "cy")]
    if not all(v and re.fullmatch(r"-?\d+", v) for v in values):
        return None
    return tuple(int(v) for v in values)


def _resized(piece, **place):
    """A piece with its first offset's x and y and its extent's cx and cy
    as given."""
    for match, keys in ((_extent(piece), ("cx", "cy")), (OFFSET.search(piece), ("x", "y"))):
        attrs = match.group(1)
        for key in keys:
            if key in place:
                attrs = _set_attr(attrs, key, str(int(place[key])))
        tag = "a:ext" if keys[0] == "cx" else "a:off"
        piece = piece[:match.start()] + "<%s%s%s>" % (tag, attrs, match.group(2)) \
            + piece[match.end():]
    return piece


def _moved(piece, y):
    """A piece with its first offset at y down the slide."""
    return _resized(piece, y=y)


def text_height(piece, size, width):
    """How tall a shape's text is, in EMU, at size points, wrapped at
    width EMU, inside a text box's insets, as a table's cell's text is
    reckoned (CELL_SIDES)."""
    room = max(width - CELL_SIDES, EMU_PER_POINT) / EMU_PER_POINT
    lines = 0
    for paragraph in PARAGRAPH.finditer(piece):
        text = "".join(html.unescape(a or b) for a, b in SHOWN_TEXT.findall(paragraph.group(1) or ""))
        lines += max(1, math.ceil(len(text) * CHARACTER * size / room))
    return int(lines * LINE * size * EMU_PER_POINT + CELL_ENDS)


def caption_room(picture, caption, size):
    """A picture and its caption, the caption as tall as its text (size:
    the points it's set in) and the picture made smaller above it where
    the writer's 40 points don't hold it, as a long caption's second line
    would otherwise run over the picture or off the slide."""
    shown, under = _place(picture), _place(caption)
    if not shown or not under:
        return picture, caption, False
    need = text_height(caption, size, under[2])
    if need <= under[3]:
        return picture, caption, False
    top = under[1] + under[3] - need
    caption = _resized(caption, y=top, cy=need)
    x, y, cx, cy = shown
    if y + cy > top and cy > 0:
        height = max(top - y, cy // 4)
        width = int(cx * height / cy)
        picture = _resized(picture, x=x + (cx - width) // 2, cx=width, cy=height)
    return picture, caption, True


def _unmarked(piece, mark):
    """A table without the filter's marker in its first cell: the marker
    out of its run, and the run out when it held nothing else."""
    start = piece.rfind("<a:r>", 0, mark.start())
    end = piece.find("</a:r>", mark.end())
    piece = piece[:mark.start()] + piece[mark.end():]
    if start < 0 or end < 0:
        return piece
    end += len("</a:r>") - (mark.end() - mark.start())
    if EMPTY_RUN.fullmatch(piece, start, end):
        piece = piece[:start] + piece[end:]
    return piece


def _svg_blip(piece, rid):
    """A picture with its SVG beside its PNG, as PowerPoint inserts one."""
    blip = BLIP.search(piece)
    if blip is None:
        return piece
    inner = SVG_BLIP % rid
    if blip.group(2):
        return piece[:blip.start()] + "<a:blip%s>%s</a:blip>" % (blip.group(1), inner) \
            + piece[blip.end():]
    return piece[:blip.end()] + inner + piece[blip.end():]


def _next_rid(rels):
    numbers = [int(n) for n in re.findall(r'\sId="rId(\d+)"', rels)]
    return "rId%d" % (max(numbers, default=0) + 1)


def slide_tree(xml, record, svgs, add_svg, counts, size=18, height=5143500, caption_size=24):
    """A slide's shape tree put right: each picture's description or mark,
    a caption that repeats its picture's alt text marked decorative, each
    table's marker out and its header column flagged, a table's caption
    above it, a caption as tall as its text (caption_size: the points it's
    set in), and a table too tall for its slide set smaller (size: the
    points its text is set in; height: the slide's, in EMU). add_svg(path)
    gives the relationship id of an SVG added to the slide. Returns the
    slide's XML."""
    tree = pptxorder.TREE.search(xml)
    if tree is None or tree.group(2):
        return xml
    close = xml.find("</p:spTree>", tree.end())
    kids = pptxorder.children(xml, tree.end(), close)
    pieces = [xml[s:e] for s, e, _ in kids]
    names = [name for _, _, name in kids]
    pictures, tables = record.get("pictures") or {}, record.get("tables") or {}
    i = 0
    while i < len(pieces):
        piece, name = pieces[i], names[i]
        caption = i + 1 < len(pieces) and _is_caption(pieces[i + 1])
        span = _cnvpr(piece)
        descr = _attr_value(CNVPR.match(piece, span[0]).group(1), "descr") if span else None
        found = PICTURE.match(descr or "") if name == "p:pic" else None
        if found:
            facts = pictures.get(found.group(1), {})
            if facts.get("decorative"):
                pieces[i] = _marked(piece, True)
                counts["decorative"] += 1
            else:
                pieces[i] = _marked(piece, facts.get("alt", ""))
                counts["described"] += 1 if facts.get("alt") else 0
            if found.group(2).strip() in svgs:
                pieces[i] = _svg_blip(pieces[i], add_svg(svgs[found.group(2).strip()]))
                counts["svgs"] += 1
            if caption:
                counts["captions"] += 1
                if facts.get("repeats"):
                    pieces[i + 1] = _marked(pieces[i + 1], True)
                    counts["captions_marked"] += 1
                pieces[i], pieces[i + 1], taller = caption_room(pieces[i], pieces[i + 1],
                                                                caption_size)
                counts["captions_taller"] += 1 if taller else 0
        mark = TABLE_MARK.search(piece) if name == "p:graphicFrame" else None
        if mark:
            facts = tables.get(mark.group(1), {})
            piece = _unmarked(piece, mark)
            if facts.get("first_column"):
                props = TBLPR.search(piece)
                if props is not None:
                    piece = (piece[:props.start()] + "<a:tblPr%s%s>" % (
                        _set_attr(props.group(1), "firstCol", "1"), props.group(2))
                        + piece[props.end():])
                    counts["first_columns"] += 1
            pieces[i] = piece
            frame, under = _place(piece), _place(pieces[i + 1]) if caption else None
            at = i
            if caption and frame and under:
                # Read before the table and shown above it, as tall as its
                # text, the table that much lower.
                need = max(under[3], text_height(pieces[i + 1], caption_size, under[2]))
                counts["captions_taller"] += 1 if need > under[3] else 0
                pieces[i], pieces[i + 1] = (_resized(pieces[i + 1], y=frame[1], cy=need),
                                            _moved(piece, frame[1] + need))
                names[i], names[i + 1] = names[i + 1], names[i]
                counts["table_captions"] += 1
                at = i + 1
                i += 1
            # Its room ends at the slide's foot, or at the shape below it,
            # where the writer stacks text after a table.
            top = (_place(pieces[at]) or (0, 0, 0, 0))[1]
            below = [place[1] for place in (_place(x) for x in pieces[at + 1:])
                     if place and place[1] > top]
            pieces[at], smaller, overflow = fit_table(
                pieces[at], size, min(below) if below else height - int(height * TABLE_FOOT))
            counts["tables_fitted"] += 1 if smaller and not overflow else 0
            counts["tables_overflow"] += 1 if overflow else 0
        i += 1
    return xml[:tree.end()] + "".join(pieces) + xml[close:]


def table_height(piece, size):
    """How tall a table is, in EMU, with its text size points (see
    CELL_SIDES): each row as tall as its tallest cell, a cell's paragraphs
    wrapped at its width."""
    widths = [int(w) for w in GRID_COLUMN.findall(piece)]
    total = 0
    for row in TABLE_ROW.finditer(piece):
        column, tallest = 0, 0
        for cell in TABLE_CELL.finditer(row.group(1)):
            span = int(_attr_value(cell.group(1), "gridSpan") or 1)
            width = sum(widths[column:column + span]) or (widths[-1] if widths else WIDTH // 2)
            column += span
            room = max(width - CELL_SIDES, EMU_PER_POINT) / EMU_PER_POINT
            lines = 0
            for paragraph in PARAGRAPH.finditer(cell.group(2)):
                text = "".join(html.unescape(a or b) for a, b in
                               SHOWN_TEXT.findall(paragraph.group(1) or ""))
                lines += max(1, math.ceil(len(text) * CHARACTER * size / room))
            tallest = max(tallest, lines * LINE * size * EMU_PER_POINT + CELL_ENDS)
        total += tallest
    return int(total)


def _sized(piece, size):
    """A table with its text size points: on each run and paragraph end,
    and as each paragraph's default, which an equation takes."""
    value = str(int(round(size * 100)))
    piece = RUN_PROPERTIES.sub(lambda m: "<a:%s%s%s>" % (
        m.group(1), _set_attr(m.group(2), "sz", value), m.group(3)), piece)
    default = '<a:defRPr sz="%s"/>' % value
    out, pos = [], 0
    for match in PARAGRAPH_PROPERTIES.finditer(piece):
        if match.start() < pos:
            continue
        attrs, closing = match.groups()
        if closing:
            out.append(piece[pos:match.start()] + "<a:pPr%s>%s</a:pPr>" % (attrs, default))
            pos = match.end()
            continue
        end = piece.find("</a:pPr>", match.end())
        if end < 0:
            continue
        inner = re.sub(r"<a:defRPr\b[^>]*?(?:/>|>.*?</a:defRPr>)", "", piece[match.end():end],
                       flags=re.S)
        # before an extension list, a paragraph's properties' last child
        ext = inner.find("<a:extLst")
        inner = inner[:ext] + default + inner[ext:] if ext >= 0 else inner + default
        out.append(piece[pos:match.end()] + inner + "</a:pPr>")
        pos = end + len("</a:pPr>")
    out.append(piece[pos:])
    return "".join(out)


def fit_table(piece, size, bottom):
    """A table frame set small enough to fit between its top and bottom,
    in EMU down the slide, at the largest of its size and the parts of it
    TABLE_STEPS gives that does: (piece, size set or None, whether it's
    still too tall at the smallest)."""
    place = _place(piece)
    if place is None:
        return piece, None, False
    room = bottom - place[1]
    if table_height(piece, size) <= room:
        return piece, None, False
    smaller = size
    for step in TABLE_STEPS:
        smaller = round(size * step, 2)
        if table_height(piece, smaller) <= room:
            return _sized(piece, smaller), smaller, False
    return _sized(piece, smaller), smaller, True


LEVEL_STYLE = re.compile(r"<a:lvl(\d)pPr\b([^>]*?)(?:/>|>(.*?)</a:lvl\1pPr>)", re.S)
PLACEHOLDER_SHAPE = re.compile(r"<p:sp>.*?</p:sp>", re.S)
BODY_PROPERTIES = re.compile(r"<a:bodyPr" + ATTRS + r"(/?)>")
LINE_BREAK = re.compile(r"<a:br\b[^>]*?(?:/>|>.*?</a:br>)", re.S)
# The scales PowerPoint's "Shrink text on overflow" records: the lines
# brought closer first, then the text made smaller in steps of 7.5 percent,
# to a quarter of its size (fontScale and lnSpcReduction, in thousandths
# of a percent).
AUTOFIT_STEPS = [(100000, 10000), (100000, 20000)] + [
    (scale, 20000) for scale in (92500, 85000, 77500, 70000, 62500, 55000, 47500, 40000,
                                 32500, 25000)]
# A monospaced character, which code is set in, is wider than the average
# one (CHARACTER): Courier's are 0.6 of their size.
MONOSPACED = 0.6
# Text shrunk below half its size, which the run names.
SMALL_TEXT = 50000


def _levels(region):
    """{level, 0 to 8: (size in points, left margin in EMU, space before as
    a fraction of a line), each None where the list style doesn't say} for
    a list style's levels (a master's text style, a placeholder's
    lstStyle)."""
    out = {}
    for match in LEVEL_STYLE.finditer(region or ""):
        attrs, inner = match.group(2), match.group(3) or ""
        size = re.search(r'<a:defRPr\b[^>]*?\ssz="(\d+)"', inner)
        before = re.search(r'<a:spcBef>\s*<a:spcPct\s+val="(\d+)"', inner)
        margin = _attr_value(attrs, "marL")
        out[int(match.group(1)) - 1] = (
            int(size.group(1)) / 100 if size else None,
            int(margin) if margin and re.fullmatch(r"-?\d+", margin) else None,
            int(before.group(1)) / 100000 if before else None)
    return out


def _merged(*styles):
    """Levels from the first style that says each thing of each level."""
    out = {}
    for level in range(9):
        values = [None, None, None]
        for style in styles:
            for k, value in enumerate(style.get(level, (None, None, None))):
                if values[k] is None:
                    values[k] = value
        out[level] = (values[0] or 18, values[1] or 0, values[2] or 0)
    return out


def text_styles(master):
    """A master's text styles' levels: title, body, and other."""
    def region(name):
        found = re.search(r"<p:%s>(.*?)</p:%s>" % (name, name), master, re.S)
        return found.group(1) if found else ""
    return {key: _levels(region(name)) for key, name in (
        ("title", "titleStyle"), ("body", "bodyStyle"), ("other", "otherStyle"))}


def layout_styles(layout):
    """{("idx", n) or ("type", t): levels} of a layout's placeholders'
    own list styles."""
    out = {}
    for shape in PLACEHOLDER_SHAPE.finditer(layout):
        ph = re.search(r"<p:ph\b([^>]*)", shape.group(0))
        if ph is None:
            continue
        lists = re.search(r"<a:lstStyle>(.*?)</a:lstStyle>", shape.group(0), re.S)
        levels = _levels(lists.group(1) if lists else "")
        kind = _attr_value(ph.group(1), "type") or "obj"
        out.setdefault(("idx", _attr_value(ph.group(1), "idx") or "0"), levels)
        out.setdefault(("type", kind), levels)
    return out


def body_height(piece, levels, width, scale=1.0, reduction=0.0):
    """How tall a shape's text is, in EMU, its paragraphs at their
    levels' sizes and margins and space before them (levels: _merged's),
    or their own, wrapped at width EMU inside the insets, at a fontScale
    and lnSpcReduction (fractions). A display equation holding a fraction,
    a sum or integral, a stack, or a matrix takes a line more."""
    total, first = CELL_ENDS, True
    body = re.search(r"<p:txBody>(.*?)</p:txBody>", piece, re.S)
    respected = bool(body and FIRST_LAST.search(body.group(1)))
    for paragraph in PARAGRAPH.finditer(body.group(1) if body else ""):
        inner = paragraph.group(1) or ""
        props = PARAGRAPH_PROPERTIES.search(inner)
        attrs = props.group(1) if props else ""
        level = int(_attr_value(attrs, "lvl") or 0)
        size, margin, before = levels.get(min(max(level, 0), 8), (18, 0, 0))
        own = _attr_value(attrs, "marL")
        if own and re.fullmatch(r"-?\d+", own):
            margin = int(own)
        spaced = SPACE_BEFORE_PERCENT.search(_paragraph_properties(inner))
        if spaced:
            before = int(spaced.group(1)) / 100000
        sizes = [int(v) / 100 for v in re.findall(r'<a:rPr\b[^>]*?\ssz="(\d+)"', inner)]
        size = max(sizes) if sizes else size
        wide = MONOSPACED if "<a:latin " in inner else CHARACTER
        room = max(width - CELL_SIDES - margin, EMU_PER_POINT) / EMU_PER_POINT
        lines = 1 if OMATH_PARA.search(inner) and TALL_MATH.search(inner) else 0
        for part in LINE_BREAK.split(inner):
            text = "".join(html.unescape(a or b) for a, b in SHOWN_TEXT.findall(part))
            lines += max(1, math.ceil(len(text) * wide * size * scale / room))
        line = LINE * size * scale * EMU_PER_POINT
        # PowerPoint puts no space before a text body's first paragraph,
        # unless the body says to (spcFirstLastPara).
        total += lines * line * (1 - reduction) + (0 if first and not respected
                                                   else before * line)
        first = False
    return int(total)


# A display equation, and the paragraph after one, which deck-pptx.lua
# marks where the deck gives them no space of its own (SPACE_MARK at their
# head), are given this much space before them, a fraction of a line
# (thousandths of a percent), where the master gives a paragraph a fifth:
# set off from the text around it, as the page and the PDF set one off.
# The deck's own vertical space in raw LaTeX, which deck-pptx.lua takes out
# and marks on the paragraph after it (VSPACE_MARK and a character naming
# its amount in record["spaces"], U+F0001 the first), in lines, is added to
# the space that paragraph has otherwise, as LaTeX adds it: the half line
# of a display equation or of one after it, the paragraph's own (a
# heading's 30 points), or its level's in the master; none for a text
# body's first paragraph, whose space before PowerPoint leaves out unless
# the body says to respect it (spcFirstLastPara), which it's then told to.
# Space that comes to less than none is none, as close as PowerPoint comes.
DISPLAY_SPACE = 50000
SPACE_MARK = "\ue002"
VSPACE_MARK = "\ue003"
SPACE_BASE = 0xF0000
SPACE_INDEX = re.compile("\ue003([\U000F0000-\U000FFFFD])")
SPACE_CHARACTERS = re.compile("[\ue002\ue003\U000F0000-\U000FFFFD]")
SPACE_BEFORE_POINTS = re.compile(r'<a:spcBef>\s*<a:spcPts\s+val="(\d+)"')
FIRST_LAST = re.compile(r'<a:bodyPr\b[^>]*?\sspcFirstLastPara="(?:1|true)"')
BODY_PROPERTIES = re.compile(r"<a:bodyPr" + ATTRS + r"(/?)>")
OMATH_PARA = re.compile(r"<m:oMathPara\b")
TALL_MATH = re.compile(r"<m:(?:f|nary|eqArr|m)\b")
SPACE_BEFORE = re.compile(r"<a:spcBef>.*?</a:spcBef>", re.S)
SPACE_BEFORE_PERCENT = re.compile(r'<a:spcBef>\s*<a:spcPct\s+val="(\d+)"')
LINE_SPACING = re.compile(r"<a:lnSpc>.*?</a:lnSpc>", re.S)
TEXT_BODY = re.compile(r"(<p:txBody>)(.*?)(</p:txBody>)", re.S)
RUN = re.compile(r"<a:r>.*?</a:r>", re.S)
MATH_RUN = re.compile(r"<m:r>.*?</m:r>", re.S)
EMPTY_MATH_RUN = re.compile(r"<m:r>(?:<m:rPr>(?:(?!</m:rPr>).)*</m:rPr>|<m:rPr\s*/>)?"
                            r"(?:<a:rPr\b[^>]*?(?:/>|>(?:(?!</a:rPr>).)*</a:rPr>))?"
                            r"<m:t(?:\s[^>]*)?(?:/>|></m:t>)</m:r>", re.S)


def _paragraph_properties(inner):
    """A paragraph's own properties' XML (inner: what <a:p> holds), or ""."""
    props = PARAGRAPH_PROPERTIES.match(inner)
    if props is None:
        return ""
    if props.group(2):
        return props.group(0)
    end = inner.find("</a:pPr>", props.end())
    return inner[:end + len("</a:pPr>")] if end >= 0 else props.group(0)


def _unspaced(inner):
    """A paragraph's insides (what <a:p> holds) without the marks
    deck-pptx.lua puts in (SPACE_CHARACTERS), a run of its text or of an
    equation that held nothing else taken out with it."""
    def run(match):
        if not SPACE_CHARACTERS.search(match.group(0)):
            return match.group(0)
        text = SPACE_CHARACTERS.sub("", match.group(0))
        return "" if EMPTY_RUN.fullmatch(text) or EMPTY_MATH_RUN.fullmatch(text) else text
    return MATH_RUN.sub(run, RUN.sub(run, inner))


def _space_now(inner, levels):
    """The space before a paragraph (what <a:p> holds) it has as it is, in
    lines: its own, or its level's in levels (_merged's)."""
    own = _paragraph_properties(inner)
    attrs = PARAGRAPH_PROPERTIES.match(own).group(1) if own else ""
    level = min(max(int(_attr_value(attrs, "lvl") or 0), 0), 8)
    size, _margin, before = levels.get(level, (18, 0, 0))
    percent = SPACE_BEFORE_PERCENT.search(own)
    if percent:
        return int(percent.group(1)) / 100000
    points = SPACE_BEFORE_POINTS.search(own)
    if points:
        sizes = [int(v) / 100 for v in re.findall(r'<a:rPr\b[^>]*?\ssz="(\d+)"', inner)]
        return int(points.group(1)) / 100 / (LINE * (max(sizes) if sizes else size))
    return before


def _space_before(inner, amount):
    """A paragraph's insides (what <a:p> holds) with amount of space before
    it, a spcPct value, in place of any it had."""
    own = _paragraph_properties(inner)
    spacing = '<a:spcBef><a:spcPct val="%d"/></a:spcBef>' % amount
    if not own:
        return "<a:pPr>%s</a:pPr>" % spacing + inner
    if SPACE_BEFORE.search(own):
        new = SPACE_BEFORE.sub(lambda _m: spacing, own, count=1)
    elif own.endswith("/>"):
        new = own[:-2].rstrip() + ">%s</a:pPr>" % spacing
    else:
        start = PARAGRAPH_PROPERTIES.match(own).end()
        line = LINE_SPACING.match(own, start)
        at = line.end() if line else start
        new = own[:at] + spacing + own[at:]
    return new + inner[len(own):]


def _space_amount(spaces, character):
    """The lines the deck's space a mark's character names (U+F0001 the
    first of spaces) gives, or none."""
    n = ord(character) - SPACE_BASE
    return float(spaces[n - 1]) if 1 <= n <= len(spaces) else 0.0


def paragraph_spacing(xml, counts, spaces=(), levels=None):
    """A slide whose paragraphs deck-pptx.lua marked, each given the space
    before it the marks call for (see DISPLAY_SPACE), the marks taken out,
    as is any mark elsewhere: a display equation, and the paragraph after
    one, DISPLAY_SPACE, but the first paragraph of a shape's text, which
    has no text above it to be set off from, as a display equation has
    after a slide's title or where a slide is cut; and the deck's own space
    added. spaces: record["spaces"]; levels: the master's body text's
    (_merged's). counts["displays"] counts the equations given space,
    counts["spaces"] the deck's spaces given."""
    levels = levels or {}

    def body(match):
        state = {"first": True, "respected": False}

        def paragraph(found):
            inner, opening = found.group(1), state["first"]
            state["first"] = False
            if inner is None or not SPACE_CHARACTERS.search(inner):
                return found.group(0)
            shown = "".join(re.findall(r">([^<]*)<", ">" + inner + "<"))
            given = [_space_amount(spaces, c) for c in SPACE_INDEX.findall(shown)]
            set_off = SPACE_MARK in shown
            start = found.group(0)[:found.start(1) - found.start()]
            inner = _unspaced(inner)
            if opening and not given:
                return start + inner + "</a:p>"
            if set_off and not opening:
                counts["displays"] += 1 if OMATH_PARA.search(inner) else 0
            counts["spaces"] += len(given)
            if opening:
                state["respected"] = True
                base = 0.0
            elif set_off:
                base = DISPLAY_SPACE / 100000
            else:
                base = _space_now(inner, levels)
            amount = int(round(max(0.0, base + sum(given)) * 100000))
            return start + _space_before(inner, amount) + "</a:p>"
        inside = PARAGRAPH.sub(paragraph, match.group(2))
        if state["respected"]:
            inside = BODY_PROPERTIES.sub(lambda m: "<a:bodyPr%s%s>" % (
                _set_attr(m.group(1), "spcFirstLastPara", "1"), m.group(2)), inside, count=1)
        return match.group(1) + inside + match.group(3)
    return SPACE_CHARACTERS.sub("", TEXT_BODY.sub(body, xml))


def _autofit(piece, scale, reduction):
    """A shape whose text body shrinks its text to fit, at the scale
    PowerPoint would record."""
    fit = "<a:normAutofit%s%s/>" % (' fontScale="%d"' % scale if scale < 100000 else "",
                                   ' lnSpcReduction="%d"' % reduction if reduction else "")
    match = BODY_PROPERTIES.search(piece)
    if match is None:
        return piece
    if match.group(2):
        return piece[:match.start()] + "<a:bodyPr%s>%s</a:bodyPr>" % (match.group(1), fit) \
            + piece[match.end():]
    end = piece.find("</a:bodyPr>", match.end())
    inner = re.sub(r"<a:(?:noAutofit|normAutofit|spAutoFit)\b[^>]*?(?:/>|>.*?</a:\w+>)", "",
                   piece[match.end():end], flags=re.S)
    warp = re.search(r"<a:prstTxWarp\b.*?(?:/>|</a:prstTxWarp>)", inner, re.S)
    at = warp.end() if warp else 0
    return piece[:match.end()] + inner[:at] + fit + inner[at:] + piece[end:]


def fit_text(xml, slide, styles, layout, counts, master=None, notes=None):
    """A slide whose text shapes each fit their boxes, as PowerPoint
    would shrink them (AUTOFIT_STEPS): slide, the parsed slide, its shapes'
    boxes found on its layout and master; styles, the master's
    (text_styles); layout and master, the slide layout's placeholders'
    list styles and its master's (layout_styles). A placeholder's text
    takes its layout's placeholder's style, then its master's, then the
    master's title or body style; any other text, the master's other.
    notes, a list, is told ("small", the slide's number) for text shrunk
    below SMALL_TEXT, and ("overflow", it) for text too much for its box
    at the smallest."""
    master = master or {}
    for shape in slide.shapes:
        if shape.kind != "sp" or shape.box is None or not shape.text.strip() or not shape.id:
            continue
        kind = pptxparse._base_type(shape.ph_type) if shape.placeholder else None
        own = (layout.get(("idx", shape.ph_idx)) or layout.get(("type", shape.ph_type)) or {}) \
            if shape.placeholder else {}
        inherited = master.get(("type", kind), {}) if kind else {}
        base = styles["title"] if kind == "title" else \
            styles["body"] if kind == "body" else styles["other"]
        levels = _merged(own, inherited, base)
        spans = pptxremediate._cnvpr_spans(xml, shape.id)
        if not spans:
            continue
        start = xml.rfind("<p:sp>", 0, spans[0][0])
        end = xml.find("</p:sp>", spans[0][1])
        if start < 0 or end < 0:
            continue
        piece = xml[start:end]
        if body_height(piece, levels, shape.box.cx) <= shape.box.cy:
            continue
        fits = False
        for scale, reduction in AUTOFIT_STEPS:
            if body_height(piece, levels, shape.box.cx, scale / 100000,
                           reduction / 100000) <= shape.box.cy:
                fits = True
                break
        counts["text_fitted" if fits else "text_overflow"] += 1
        if notes is not None and not fits:
            notes.append(("overflow", slide.number))
        elif notes is not None and scale < SMALL_TEXT:
            notes.append(("small", slide.number))
        # Choice and Fallback alike, from the end, so each one's place holds.
        for at, _end, _attrs, _closing in reversed(spans):
            begin, close = xml.rfind("<p:sp>", 0, at), xml.find("</p:sp>", at)
            if begin >= 0 and close >= 0:
                xml = xml[:begin] + _autofit(xml[begin:close], scale, reduction) + xml[close:]
    return xml


M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MATH_NAMESPACES = ('xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" '
                   'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                   'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')
A14_MATH = re.compile(r"<a14:m\b[^>]*>.*?</a14:m>", re.S)
ALTERNATE = re.compile(r"<mc:AlternateContent\b[^>]*>(.*?)</mc:AlternateContent>", re.S)
CHOICE = re.compile(r"\s*<mc:Choice\b([^>]*)>(.*)</mc:Choice>\s*$", re.S)
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
A14 = 'xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main"'
SUPERSCRIPTS = dict(zip("0123456789+-=()abcdefghijklmnoprstuvwxyz",
                        "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a"
                        "\u207b\u207c\u207d\u207e\u1d43\u1d47\u1d9c\u1d48\u1d49\u1da0\u1d4d"
                        "\u02b0\u2071\u02b2\u1d4f\u02e1\u1d50\u207f\u1d52\u1d56\u02b3\u02e2"
                        "\u1d57\u1d58\u1d5b\u02b7\u02e3\u02b8\u1dbb"))
SUBSCRIPTS = dict(zip("0123456789+-=()aeoxhklmnpstijruv", "\u2080\u2081\u2082\u2083\u2084"
                      "\u2085\u2086\u2087\u2088\u2089\u208a\u208b\u208c\u208d\u208e\u2090"
                      "\u2091\u2092\u2093\u2095\u2096\u2097\u2098\u2099\u209a\u209b\u209c"
                      "\u1d62\u2c7c\u1d63\u1d64\u1d65"))
RELATION = re.compile("\\s*([=<>\u2264\u2265\u2260\u2248\u2261\u2192\u221d])\\s*")
# An accent's spacing character, as the combining one that goes after the
# letter in a line of text.
COMBINING = {"\u00af": "\u0304", "\u203e": "\u0305", "^": "\u0302", "\u02c6": "\u0302",
             "~": "\u0303", "\u02dc": "\u0303", "\u02d9": "\u0307", "\u00a8": "\u0308",
             "\u2192": "\u20d7", "\u00b4": "\u0301", "`": "\u0300", "\u02c7": "\u030c"}


def _script(text, table, mark):
    """A superscript's or subscript's text, in Unicode's raised or lowered
    characters where it has them all, else after mark."""
    if not text:
        return ""
    if all(c in table for c in text):
        return "".join(table[c] for c in text)
    return mark + (text if len(text) == 1 else "(%s)" % text)


def _value(props, name, default):
    """A math property's m:val, from props' child name."""
    found = props.find(M + name) if props is not None else None
    if found is None:
        return default
    return found.get(M + "val", default)


def math_text(element):
    """An Office equation (an ElementTree element) as a line of text: a
    fraction a/b, a script in Unicode's raised or lowered characters
    (x\u00b2, x\u1d62) or after ^ or _, an accent or a bar as the combining
    character after its letter (x\u0304), a root \u221a(x), a delimiter's
    own characters."""
    tag = element.tag[len(M):] if element.tag.startswith(M) else ""

    def part(name):
        found = element.find(M + name)
        return math_text(found) if found is not None else ""

    def wrapped(text):
        return text if len(text) <= 1 or (text[0] + text[-1]) in ("()", "[]", "{}") \
            else "(%s)" % text
    if tag == "t":
        return element.text or ""
    if tag.endswith("Pr"):
        return ""
    if tag == "f":
        return "%s/%s" % (wrapped(part("num")), wrapped(part("den")))
    if tag == "sSup":
        return part("e") + _script(part("sup"), SUPERSCRIPTS, "^")
    if tag == "sSub":
        return part("e") + _script(part("sub"), SUBSCRIPTS, "_")
    if tag == "sSubSup":
        return part("e") + _script(part("sub"), SUBSCRIPTS, "_") + _script(
            part("sup"), SUPERSCRIPTS, "^")
    if tag == "sPre":
        return _script(part("sub"), SUBSCRIPTS, "_") + _script(part("sup"), SUPERSCRIPTS, "^") \
            + part("e")
    if tag == "rad":
        degree = part("deg")
        sign = {"": "\u221a", "2": "\u221a", "3": "\u221b", "4": "\u221c"}.get(
            degree, _script(degree, SUPERSCRIPTS, "") + "\u221a")
        return sign + wrapped(part("e"))
    if tag == "d":
        props = element.find(M + "dPr")
        return _value(props, "begChr", "(") + _value(props, "sepChr", "|").join(
            math_text(e) for e in element.findall(M + "e")) + _value(props, "endChr", ")")
    if tag == "acc":
        mark = _value(element.find(M + "accPr"), "chr", "\u0302")
        return part("e") + COMBINING.get(mark, mark)
    if tag == "limUpp":
        limit = part("lim")
        if limit in COMBINING and len(limit) == 1:
            return part("e") + COMBINING[limit]
        return part("e") + _script(limit, SUPERSCRIPTS, "^")
    if tag == "limLow":
        return part("e") + _script(part("lim"), SUBSCRIPTS, "_")
    if tag == "bar":
        mark = "\u0305" if _value(element.find(M + "barPr"), "pos", "bot") == "top" else "\u0332"
        return "".join(c + mark for c in part("e"))
    if tag == "nary":
        props = element.find(M + "naryPr")
        return _value(props, "chr", "\u222b") + _script(part("sub"), SUBSCRIPTS, "_") + _script(
            part("sup"), SUPERSCRIPTS, "^") + part("e")
    if tag == "func":
        return part("fName") + " " + part("e")
    if tag == "eqArr":
        return "; ".join(math_text(e) for e in element.findall(M + "e"))
    if tag == "m":
        return "[" + "; ".join(", ".join(math_text(e) for e in row.findall(M + "e"))
                               for row in element.findall(M + "mr")) + "]"
    if tag == "oMathPara":
        return " ".join(math_text(e) for e in element.findall(M + "oMath"))
    return "".join(math_text(child) for child in element)


def _math_run(fragment):
    """An a14:m equation as a run of its text (math_text)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring("<root %s>%s</root>" % (MATH_NAMESPACES, fragment))
        text = math_text(root)
    except ET.ParseError:
        text = "".join(html.unescape(t) for t in re.findall(r"<m:t(?:\s[^>]*)?>([^<]*)</m:t>",
                                                           fragment))
    # A relation set apart, as an equation shows it.
    text = RELATION.sub(lambda m: " %s " % m.group(1), text).strip()
    return "<a:r><a:rPr/><a:t>%s</a:t></a:r>" % pptxremediate._text(text)


def math_fallbacks(xml, counts):
    """A slide with a fallback for each shape the writer wrapped in
    mc:AlternateContent for its equations (a Choice alone), and each table
    holding one wrapped so, its fallback the same with each equation a run
    of its text (_math_run)."""
    def wrapped(match):
        inner = match.group(1)
        choice = CHOICE.match(inner)
        if "<mc:Fallback" in inner or choice is None or "a14" not in (
                _attr_value(choice.group(1), "Requires") or "").split():
            return match.group(0)
        counts["math_fallbacks"] += 1
        close = "</mc:AlternateContent>"
        return match.group(0)[:-len(close)] + "<mc:Fallback>%s</mc:Fallback>" % A14_MATH.sub(
            lambda m: _math_run(m.group(0)), choice.group(2)) + close
    xml = ALTERNATE.sub(wrapped, xml)
    tree = pptxorder.TREE.search(xml)
    if tree is None or tree.group(2):
        return xml
    close = xml.find("</p:spTree>", tree.end())
    out, pos = [], tree.end()
    for start, end, name in pptxorder.children(xml, tree.end(), close):
        piece = xml[start:end]
        if name == "p:graphicFrame" and "<a14:m" in piece:
            piece = ('<mc:AlternateContent %s><mc:Choice %s Requires="a14">%s</mc:Choice>'
                     "<mc:Fallback>%s</mc:Fallback></mc:AlternateContent>" % (
                         MC, A14, piece, A14_MATH.sub(lambda m: _math_run(m.group(0)), piece)))
            counts["math_fallbacks"] += 1
        out.append(xml[pos:start] + piece)
        pos = end
    return xml[:tree.end()] + "".join(out) + xml[pos:]


TARGET = re.compile(r'<p:spTgt spid="(\d+)">\s*<p:txEl>\s*<p:pRg st="(\d+)" end="(\d+)"\s*/>')
BUILD = re.compile(r'(<p:bldP\b[^>]*?\sspid=")(\d+)(")')


def _text_shapes(xml):
    """(id, [whether each paragraph is a list's]) of each text shape at the
    top of a slide's tree but its title, in order, a shape in
    mc:AlternateContent read from its Choice."""
    tree = pptxorder.TREE.search(xml)
    if tree is None or tree.group(2):
        return []
    close = xml.find("</p:spTree>", tree.end())
    found = []
    for start, end, name in pptxorder.children(xml, tree.end(), close):
        piece = re.sub(r"<mc:Fallback>.*?</mc:Fallback>", "", xml[start:end], flags=re.S)
        body = re.search(r"<p:txBody>(.*?)</p:txBody>", piece, re.S)
        span = _cnvpr(piece)
        if body is None or span is None or re.search(r'<p:ph\b[^>]*\stype="(?:title|ctrTitle)"',
                                                     piece):
            continue
        found.append((_attr_value(CNVPR.match(piece, span[0]).group(1), "id"),
                      ["<a:buNone" not in (m.group(1) or "") for m in PARAGRAPH.finditer(
                          body.group(1))]))
    return found


def animation_targets(xml, counts):
    """A slide whose incremental lists' animations name the shapes holding
    the lists. The writer names a shape by its id paired with its shape in
    order, so where it gives text boxes stacked around a table one id, or
    pairs a table's caption's id with the next shape, an animation named
    another shape or the slide's own group, and renumbering the copies
    (unique_ids) left it naming the first. Each run of an animation's steps
    on one shape is given the next text shape whose paragraphs at those
    steps are a list's, and the build list its shapes in the same order."""
    timing = xml.find("<p:timing>")
    if timing < 0:
        return xml
    shapes = _text_shapes(xml)
    groups = []
    for match in TARGET.finditer(xml, timing):
        spid, first, last = match.group(1), int(match.group(2)), int(match.group(3))
        if groups and groups[-1]["spid"] == spid and first > groups[-1]["last"]:
            groups[-1]["matches"].append(match)
            groups[-1]["ranges"].append((first, last))
            groups[-1]["last"] = last
        else:
            groups.append({"spid": spid, "matches": [match], "ranges": [(first, last)],
                           "last": last})
    used, edits, ids = -1, [], []
    for group in groups:
        new = group["spid"]
        for k in range(used + 1, len(shapes)):
            listed = shapes[k][1]
            if all(last < len(listed) and all(listed[first:last + 1])
                   for first, last in group["ranges"]):
                used, new = k, shapes[k][0]
                break
        ids.append(new)
        if new != group["spid"]:
            counts["animations"] += 1
        edits += [(m.start(1), m.end(1), new) for m in group["matches"]]
    builds = list(BUILD.finditer(xml, timing))
    edits += [(m.start(2), m.end(2), new) for m, new in zip(builds, ids)]
    for start, end, new in sorted(edits, reverse=True):
        xml = xml[:start] + new + xml[end:]
    return xml


def _drop_properties(xml):
    """custom.xml without the fields that aren't the deck's own: (xml,
    count)."""
    count = 0

    def one(match):
        nonlocal count
        name = _attr_value(match.group(1), "name")
        if name in NOT_PROPERTIES:
            count += 1
            return ""
        return match.group(0)
    return re.sub(r"<property" + ATTRS + r">.*?</property>", one, xml, flags=re.S), count


def _core(xml, title, creator):
    """core.xml with title as its title when given (else kept, or the
    fallback when empty) and creator as its creator when given."""
    def element(name, value):
        return "<%s>%s</%s>" % (name, pptxremediate._text(value), name)
    for name, value in (("dc:title", title), ("dc:creator", creator)):
        if value is None:
            continue
        pattern = re.compile(r"<%s\s*/>|<%s>.*?</%s>" % (name, name, name), re.S)
        if pattern.search(xml):
            xml = pattern.sub(lambda _m: element(name, value), xml, count=1)
        else:
            start = re.search(r"<cp:coreProperties\b[^>]*>", xml)
            if start:
                xml = xml[:start.end()] + element(name, value) + xml[start.end():]
    return xml


def app_properties(xml, titles, notes):
    """docProps/app.xml as the deck's, where the writer copies the
    reference document's: its slides' titles, the reference's other lists
    as they were; and its counts of slides and notes. The name of its
    slides' size is the reference's, as they are (reference_doc names its
    own). A list whose counts don't add up is left; the counts the deck
    can't give (words, paragraphs, editing time) go."""
    pairs = re.search(r"(<HeadingPairs>\s*<vt:vector\b[^>]*>)(.*?)(</vt:vector>\s*</HeadingPairs>)",
                      xml, re.S)
    named = re.search(r"(<TitlesOfParts>\s*<vt:vector\b[^>]*>)(.*?)(</vt:vector>\s*"
                      r"</TitlesOfParts>)", xml, re.S)
    if pairs and named:
        groups = [[html.unescape(m.group(2)), int(m.group(4))]
                  for m in pptxremediate.APP_HEADING.finditer(pairs.group(2))]
        entries = [html.unescape(m.group(1) or "")
                   for m in pptxremediate.APP_ENTRY.finditer(named.group(2))]
        if groups and sum(n for _, n in groups) == len(entries):
            lists, at = [], 0
            for _, n in groups:
                lists.append(entries[at:at + n])
                at += n
            names = [g[0] for g in groups]
            if pptxremediate.APP_TITLES in names:
                lists[names.index(pptxremediate.APP_TITLES)] = list(titles)
            else:
                groups.append([pptxremediate.APP_TITLES, 0])
                lists.append(list(titles))
            heading = "".join("<vt:variant><vt:lpstr>%s</vt:lpstr></vt:variant><vt:variant>"
                              "<vt:i4>%d</vt:i4></vt:variant>" % (pptxremediate._text(g[0]),
                                                                  len(items))
                              for g, items in zip(groups, lists))
            flat = [e for items in lists for e in items]
            body = "".join("<vt:lpstr>%s</vt:lpstr>" % pptxremediate._text(e) if e
                           else "<vt:lpstr/>" for e in flat)
            start = re.sub(r'\bsize="\d+"', 'size="%d"' % (2 * len(groups)), pairs.group(1),
                           count=1)
            named_start = re.sub(r'\bsize="\d+"', 'size="%d"' % len(flat), named.group(1),
                                 count=1)
            for match, replacement in sorted(((named, named_start + body + named.group(3)),
                                              (pairs, start + heading + pairs.group(3))),
                                             key=lambda item: -item[0].start()):
                xml = xml[:match.start()] + replacement + xml[match.end():]
    for tag, value in (("Slides", len(titles)), ("Notes", notes), ("HiddenSlides", 0)):
        xml = re.sub(r"<%s>\d*</%s>" % (tag, tag), "<%s>%d</%s>" % (tag, value, tag), xml,
                     count=1)
    for tag in ("TotalTime", "Words", "Paragraphs"):
        xml = re.sub(r"<%s>[^<]*</%s>" % (tag, tag), "", xml, count=1)
    return xml


def finish(path, record, *, language, title, svgs=None, notes=None):
    """What the writer wrote, put right in place (see the module's
    docstring). record: what deck-pptx.lua recorded; language: the deck's;
    title: the file's title for a deck with none; svgs: {PNG's path: SVG's
    path} for the pictures made from SVGs; notes, a list, told (what, the
    slide's number) of each slide whose table or text is still too much for
    it at the smallest ("overflow") or whose text is shrunk below half its
    size ("small"). Returns counts."""
    svgs = svgs or {}
    notes = notes if notes is not None else []
    counts = {"described": 0, "decorative": 0, "captions": 0, "captions_marked": 0,
              "first_columns": 0, "table_captions": 0, "captions_taller": 0,
              "tables_fitted": 0, "tables_overflow": 0, "text_fitted": 0, "text_overflow": 0,
              "bars": 0, "math_fallbacks": 0, "ids": 0, "animations": 0, "repaired": 0,
              "svgs": 0, "properties": 0, "displays": 0, "spaces": 0}
    with zipfile.ZipFile(path) as zin:
        infos = zin.infolist()
        parts = {info.filename: zin.read(info.filename) for info in infos}
    texts = {}

    def text(name):
        if name not in texts:
            texts[name] = pptxparse.part_text(parts[name])[0]
        return texts[name]

    added = {}      # media part: SVG's path
    master = next((text(n) for n in sorted(parts)
                   if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", n)), "")
    styles = text_styles(master)
    body_levels = _merged(styles["body"])
    spaces = record.get("spaces") or []
    size = styles["other"].get(0, (None,))[0] or 18
    # A caption the writer makes takes the body's size (createCaption's
    # placeholder index is the body's).
    caption_size = styles["body"].get(0, (None,))[0] or 24
    sized = SLIDE_SIZE.search(text("ppt/presentation.xml"))
    height = int(_attr_value(sized.group(1), "cy") or 5143500) if sized else 5143500
    slide_parts = sorted((n for n in parts if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                         key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    notes_parts = [n for n in parts if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)]
    for name in slide_parts + notes_parts:
        xml, removed, declared = pptxremediate.repair_part(text(name))
        counts["repaired"] += removed + len(declared)
        xml, n = bar_accents(xml)
        counts["bars"] += n
        if name in slide_parts:
            folder, base = name.rsplit("/", 1)
            rels_name = "%s/_rels/%s.rels" % (folder, base)

            def add_svg(svg, rels_name=rels_name):
                media = next((m for m, s in added.items() if s == svg), None)
                if media is None:
                    media = "ppt/media/oer-svg%d.svg" % (len(added) + 1)
                    added[media] = svg
                rels = text(rels_name)
                rid = _next_rid(rels)
                texts[rels_name] = rels.replace(
                    "</Relationships>", '<Relationship Id="%s" Type="%s" Target="../media/%s"/>'
                    "</Relationships>" % (rid, IMAGE_RELATIONSHIP, media.rsplit("/", 1)[1]), 1)
                return rid
            before = counts["tables_overflow"]
            xml = slide_tree(xml, record, svgs, add_svg, counts, size, height, caption_size)
            if counts["tables_overflow"] > before:
                notes.append(("overflow", slide_parts.index(name) + 1))
            xml, n = unique_ids(xml)
            counts["ids"] += n
            xml = animation_targets(xml, counts)
            xml = paragraph_spacing(xml, counts, spaces, body_levels)
        xml = math_fallbacks(xml, counts)
        if language:
            xml, _ = relanguage(xml, language)
        texts[name] = xml
    if language:
        for name in parts:
            if re.match(r"ppt/(slideMasters|slideLayouts|notesMasters|handoutMasters)/[^/]+\.xml$",
                        name):
                texts[name] = relanguage(text(name), language)[0]
        xml, _ = relanguage(text("ppt/presentation.xml"), language)
        texts["ppt/presentation.xml"] = pptxremediate.set_default_language(xml, language)[0]
    if added:
        types = text("[Content_Types].xml")
        if not re.search(r'<Default\b[^>]*\sExtension="svg"', types, re.I):
            texts["[Content_Types].xml"] = types.replace(
                "</Types>", '<Default Extension="svg" ContentType="image/svg+xml"/></Types>', 1)
    if "docProps/core.xml" in parts:
        core = text("docProps/core.xml")
        own = record.get("core_title") or None
        if own is None and not re.search(r"<dc:title>\s*[^\s<]", core):
            own = title
        texts["docProps/core.xml"] = _core(core, own, record.get("creator")
                                           if record.get("institute") else None)
    if "docProps/custom.xml" in parts:
        texts["docProps/custom.xml"], counts["properties"] = _drop_properties(
            text("docProps/custom.xml"))
    # The slides as they'll be written, read for their shapes' boxes,
    # which a placeholder takes from its layout, and their titles.
    temporary = path + ".reading"
    _write(temporary, infos, parts, texts, added)
    try:
        deck = pptxparse.read(temporary)
    finally:
        os.remove(temporary)
    placeholders = layout_styles(master)
    layouts = {}
    for slide in deck.slides:
        if slide.layout_part and slide.layout_part not in layouts:
            layouts[slide.layout_part] = layout_styles(text(slide.layout_part)) \
                if slide.layout_part in parts else {}
        texts[slide.part] = fit_text(text(slide.part), slide, styles,
                                     layouts.get(slide.layout_part, {}), counts, placeholders,
                                     notes)
    if "docProps/app.xml" in parts:
        texts["docProps/app.xml"] = app_properties(
            text("docProps/app.xml"), [s.title or "" for s in deck.slides], len(notes_parts))
    _write(path, infos, parts, texts, added)
    return counts


def _write(path, infos, parts, texts, added):
    """The package with the parts changed and the SVGs added."""
    handle, temporary = tempfile.mkstemp(suffix=".pptx", dir=os.path.dirname(os.path.abspath(path)))
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in infos:
                data = texts[info.filename].encode("utf-8") if info.filename in texts \
                    else parts[info.filename]
                zout.writestr(info, data)
            for media, svg in added.items():
                with open(svg, "rb") as fh:
                    zout.writestr(media, fh.read())
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def _overlap(a, b):
    """Whether two boxes overlap by a point or more each way: the writer
    places a shape in whole points, so a picture on a comparison slide
    reaches into the text above it by less than one, which no one sees."""
    return (min(a.x + a.cx, b.x + b.cx) - max(a.x, b.x) >= EMU_PER_POINT
            and min(a.y + a.cy, b.y + b.cy) - max(a.y, b.y) >= EMU_PER_POINT)


def overlapping(deck):
    """The numbers of the slides on which shapes other than the title
    overlap: where the writer placed a picture over text or over another
    picture."""
    found = []
    for slide in deck.slides:
        body = [s for s in slide.shapes if not s.is_title and s.box is not None]
        if any(_overlap(a.box, b.box) for i, a in enumerate(body) for b in body[i + 1:]):
            found.append(slide.number)
    return found
