"""
pptxremediate.py -- write a person's decisions about a PowerPoint deck
into a copy of it, and change nothing else.

What's written is each a decision from a sidecar, never a guess, as
docxremediate.py does for Word:

- alt text into a picture's or object's description (`descr`), and
  `[decorative]` as PowerPoint's decorative mark, which also clears the
  description. A picture is found by its image's SHA-256, so one row
  covers every copy of an image, on every slide and on the layouts and
  masters; an object with no image (a chart, SmartArt, an embedded
  object, a group, a shape) by its slide and shape id;
- a table's header row and column, PowerPoint's firstRow and firstCol,
  for the table whose content hash the sidecar names;
- a title for a slide that has none, placed above the slide, where it's
  read and not seen, as PowerPoint's own Add Hidden Slide Title does; an
  empty title placeholder takes the text and moves above the slide;
- a title for a slide whose title another slide has, in its place on the
  slide: what's added to the old title, as " (2)" is, goes after its last
  run, in that run's formatting;
- a slide's reading order, the shapes at the top of its tree put in the
  order given, unless that would draw two that overlap the other way
  round (pptxorder.py);
- the language, on text that declares none, when the project declares one;
- the title in the file's core properties, when they have none.

And two repairs, which lose nothing, of XML PowerPoint can't read as
written, both of which Pandoc's PowerPoint writer leaves: a shape element
with nothing in it is taken out, which stopped PowerPoint opening a deck,
and a prefix used without its namespace declared is declared on the
part's root, where PowerPoint had repaired the deck by removing content.
Each was confirmed in PowerPoint on a deck with that repair alone.

The XML is edited as text, never parsed and written again, and every part
not changed is copied byte for byte. A shape in mc:AlternateContent is
edited in both its Choice and its Fallback, which carry the same id.

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
import html
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter

import pptxorder
import pptxparse
import sidecars

DECORATIVE_EXT = ('<a:ext uri="%s"><adec:decorative xmlns:adec="%s" val="1"/></a:ext>'
                  % (pptxparse.DECORATIVE_URI, pptxparse.NS["adec"]))
# A start tag's attributes, quoted values allowed to hold ">", which XML
# permits and not every writer escapes.
ATTRS = r"((?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*"


def start_tag(name):
    return re.compile(r"<%s%s(/?)>" % (re.escape(name), ATTRS))


CNVPR = start_tag("p:cNvPr")
TBLPR = start_tag("a:tblPr")
# A shape with nothing in it, as Pandoc writes one for a field its layout
# has no placeholder for.
EMPTY_SHAPE = re.compile(r"<p:(sp|pic|graphicFrame|grpSp|cxnSp)%s(?:/>|>\s*</p:\1\s*>)" % ATTRS)
HEADERS = ("first-row", "first-column", "both", "none")
# As the header pre-pass reads a book's sidecar (table-headers.py): two
# other names for values, and two that leave a table to a person.
HEADER_ALIASES = {"matrix": "both", "grid": "none"}
HEADER_RESERVED = ("manual", "list")


# --------------------------------------------------------------------------
# keys
# --------------------------------------------------------------------------

def current_umask():
    """The process's umask, which can only be read by setting it."""
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


def deck_name(path):
    """A deck's name in its sidecar keys: its file's name without .pptx,
    as it is. A key is text in a CSV, not a path, so nothing in a name
    has to be made safe; made safe as a page's name is, "Week 1" and
    "Week-1" were one deck, and a name in another script none at all."""
    return os.path.splitext(os.path.basename(path))[0].strip()


def image_key(digest, deck=None):
    """An image's key: any deck's copy, or one deck's."""
    key = "media/" + pptxparse.short_hash(digest)
    return deck + "/" + key if deck else key


def object_key(deck, slide, shape):
    return "%s/slide-%s/shape-%s" % (deck, slide.slide_id, shape.id)


def slide_key(deck, slide):
    return "%s/slide-%s" % (deck, slide.slide_id)


# The first cell of a report's header row, which pasting its rows into a
# sidecar again and again carries along each time.
HEADER_CELLS = {"image", "key", "slide", "label", "table", "file", "url"}


def sidecar_rows(path):
    """A sidecar's rows by position, the key first and the value second,
    a header row anywhere skipped, as the filter reads every sidecar."""
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip() or row[0].strip().lower() in HEADER_CELLS:
                continue
            yield [c.strip() for c in row] + ["", ""]


def alt_rows(path):
    """{key without extension: alt, None for decorative, or "" to keep
    what the deck has} from an image-alt sidecar. A blank Alt is a
    person's review, as it is for a book's image: checked, and fine as it
    is, so it's decided and not reported again."""
    found = {}
    for row in sidecar_rows(path):
        image, alt = row[0], " ".join(row[1].split())
        key = image if "/slide-" in image else os.path.splitext(image)[0]
        found[key] = None if sidecars.is_decorative(alt) else alt
    return found


def header_rows(path, unknown=None):
    """{table key: first-row, first-column, both, none, or "" to leave
    the table as it is} from a table-headers sidecar, its other names for
    values read as the header pre-pass reads them. Every row is a
    decision, as it is for a book's table: a blank value, manual, list,
    and a value this version doesn't know (added to unknown) all leave
    the table alone, and none of them sends it back to the report."""
    found = {}
    for row in sidecar_rows(path):
        key, value = row[0], row[1].lower()
        value = HEADER_ALIASES.get(value, value)
        if value and value not in HEADERS and value not in HEADER_RESERVED \
                and unknown is not None:
            unknown.add(row[1])
        found[key] = value if value in HEADERS else ""
    return found


def title_rows(path):
    """{slide key: title} from a slide-titles sidecar."""
    found = {}
    for row in sidecar_rows(path):
        title = " ".join(row[1].split())
        if title:
            found[row[0]] = title
    return found


def order_rows(path, bad=None):
    """{slide key: [shape ids], or [] to leave the slide's order as it
    is} from a reading-order sidecar. An order that isn't a list of ids
    (bad, a list, is told the key and what isn't an id) leaves its slide
    alone, as a blank one does; either is a decision, and isn't reported
    again."""
    found = {}
    for row in sidecar_rows(path):
        try:
            found[row[0]] = pptxorder.parse_order(row[1])
        except ValueError as exc:
            found[row[0]] = []
            if bad is not None:
                bad.append((row[0], str(exc)))
    return found


def slide_orders(orders, deck):
    """One deck's orders, by its slides' ids, as pptxcheck.check() takes
    them."""
    prefix = deck + "/slide-"
    return {key[len(prefix):]: ids for key, ids in orders.items()
            if key.startswith(prefix) and ids}


def decision(alts, deck, slide, shape):
    """(found, alt, None for decorative, or "" to keep what it has) for a
    shape: its image's row, this deck's first, else its own row."""
    keys = []
    # The most particular row wins: this shape's own, then its image's in
    # this deck, then its image's anywhere.
    if slide is not None and shape.id:
        keys.append(object_key(deck, slide, shape))
    if shape.image and shape.image[1]:
        keys += [image_key(shape.image[1], deck), image_key(shape.image[1])]
    for key in keys:
        if key in alts:
            value = alts[key]
            return True, None if value is None or sidecars.is_decorative(value) else value
    return False, None


# --------------------------------------------------------------------------
# edits, as text
# --------------------------------------------------------------------------

# The characters XML 1.0 has no place for, which a description pasted
# from elsewhere can carry: a part holding one isn't XML at all.
NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _text(value):
    """Text for an element's content."""
    return html.escape(NOT_XML.sub("", value), quote=False)


def _attr(value):
    """Text for an attribute's value, in double quotes."""
    return (html.escape(NOT_XML.sub("", value), quote=True)
            .replace("\n", "&#xA;").replace("\r", "&#xD;").replace("\t", "&#x9;"))


def _set_attr(attrs, name, value):
    """A start tag's attributes with one set (None removes it), in either
    kind of quotes. The new value is given as a function, never as a
    replacement template, so a backslash in it is a backslash."""
    pattern = re.compile(r"""\s%s\s*=\s*(?:"[^"]*"|'[^']*')""" % re.escape(name))
    if value is None:
        return pattern.sub("", attrs)
    written = ' %s="%s"' % (name, _attr(value))
    if pattern.search(attrs):
        return pattern.sub(lambda _match: written, attrs, count=1)
    return attrs + written


def _cnvpr_spans(xml, shape_id):
    """(start, end, attrs, self_closing) of every p:cNvPr with an id,
    Choice and Fallback alike."""
    out = []
    for match in CNVPR.finditer(xml):
        if re.search(r'\sid="%s"' % re.escape(str(shape_id)), match.group(1)):
            end = match.end()
            if not match.group(2):
                close = xml.find("</p:cNvPr>", end)
                end = close + len("</p:cNvPr>") if close >= 0 else end
            out.append((match.start(), end, match.group(1), bool(match.group(2))))
    return out


def _rewrite_cnvpr(element, alt, decorative):
    """A p:cNvPr element with its description set and the decorative
    mark added or removed."""
    match = CNVPR.match(element)
    attrs, closing = match.group(1), match.group(2)
    attrs = _set_attr(attrs, "descr", None if decorative else alt)
    inner = "" if closing else element[match.end():-len("</p:cNvPr>")]
    inner = re.sub(r'<a:ext uri="%s">.*?</a:ext>' % re.escape(pptxparse.DECORATIVE_URI),
                   "", inner, flags=re.S)
    inner = re.sub(r"<a:extLst>\s*</a:extLst>|<a:extLst/>", "", inner)
    if decorative:
        # cNvPr's own extension list is its last child; a link's, inside
        # a:hlinkClick before it, isn't the shape's.
        if inner.rstrip().endswith("</a:extLst>"):
            at = inner.rindex("</a:extLst>")
            inner = inner[:at] + DECORATIVE_EXT + inner[at:]
        else:
            inner += "<a:extLst>" + DECORATIVE_EXT + "</a:extLst>"
    if inner:
        return "<p:cNvPr%s>%s</p:cNvPr>" % (attrs, inner)
    return "<p:cNvPr%s/>" % attrs


def set_alt(xml, shape_id, alt, decorative):
    """xml with a shape's description and mark set; (xml, count)."""
    spans = _cnvpr_spans(xml, shape_id)
    for start, end, _attrs, _closing in reversed(spans):
        xml = xml[:start] + _rewrite_cnvpr(xml[start:end], alt, decorative) + xml[end:]
    return xml, len(spans)


def set_headers(xml, shape_id, headers):
    """xml with a table's firstRow and firstCol as decided: the value is
    the table's headers, whole, so each sets both of PowerPoint's
    checkboxes, Header Row and First Column."""
    row = "1" if headers in ("first-row", "both") else None
    column = "1" if headers in ("first-column", "both") else None
    count = 0
    for start, end, _attrs, _closing in reversed(_cnvpr_spans(xml, shape_id)):
        frame_end = xml.find("</p:graphicFrame>", end)
        if frame_end < 0:
            continue
        table = start_tag("a:tbl").search(xml, end, frame_end)
        if table is None or table.group(2):
            continue
        match = TBLPR.search(xml, table.end(), frame_end)
        if match is None or xml[table.end():match.start()].strip():
            # No table properties, which come first in a table when there
            # are any: they're added, with the flags decided.
            flags = (' firstRow="1"' if row else "") + (' firstCol="1"' if column else "")
            if flags:
                xml = xml[:table.end()] + "<a:tblPr%s/>" % flags + xml[table.end():]
                count += 1
            continue
        attrs = _set_attr(_set_attr(match.group(1), "firstRow", row), "firstCol", column)
        xml = xml[:match.start()] + "<a:tblPr%s%s>" % (attrs, match.group(2)) + xml[match.end():]
        count += 1
    return xml, count


def _title_run(title, language):
    lang = ' lang="%s"' % _attr(language) if language else ""
    return '<a:r><a:rPr%s dirty="0"/><a:t>%s</a:t></a:r>' % (lang, _text(title))


def _fill_title(shape, off, run):
    """An empty title placeholder's XML, from its cNvPr to its end, with
    the title's run in it and its position above the slide."""
    sppr = start_tag("p:spPr").search(shape)
    if sppr is not None and sppr.group(2):
        shape = shape[:sppr.start()] + "<p:spPr%s>%s</p:spPr>" % (sppr.group(1), off) \
            + shape[sppr.end():]
    elif sppr is not None:
        close = shape.find("</p:spPr>", sppr.end())
        xfrm = re.compile(r"<a:xfrm\b[^>]*?(?:/>|>.*?</a:xfrm>)", re.S)
        found = xfrm.search(shape, sppr.end(), close)
        if found:
            shape = shape[:found.start()] + off + shape[found.end():]
        else:
            # the position comes first in spPr
            shape = shape[:sppr.end()] + off + shape[sppr.end():]
    empty = re.compile(r"<a:p>(\s*(?:<a:pPr\b[^>]*/>)?)(\s*(?:<a:endParaRPr\b[^>]*/>)?)\s*</a:p>"
                       r"|<a:p\s*/>")
    if empty.search(shape):
        return empty.sub(lambda m: "<a:p>%s%s%s</a:p>" % (m.group(1) or "", run, m.group(2) or ""),
                         shape, count=1)
    if "</p:txBody>" in shape:
        return shape.replace("</p:txBody>", "<a:p>%s</a:p></p:txBody>" % run, 1)
    body = "<p:txBody><a:bodyPr/><a:lstStyle/><a:p>%s</a:p></p:txBody>" % run
    # the text body before the shape's own extension list, its last child
    if shape.rstrip().endswith("</p:extLst>"):
        at = shape.rindex("<p:extLst")
        return shape[:at] + body + shape[at:]
    return shape + body


def add_title(xml, slide, title, width, language):
    """xml with a title read but not seen: an empty title placeholder
    filled and moved above the slide, or a new one there."""
    height = pptxparse.EMU_PER_INCH // 2
    off = '<a:xfrm><a:off x="0" y="%d"/><a:ext cx="%d" cy="%d"/></a:xfrm>' % (
        -2 * height, width or 9144000, height)
    shapes = list(slide.all_shapes())
    empty = next((s for s in shapes if s.is_title and not s.text.strip()), None)
    if empty is not None and empty.id and [s.id for s in shapes].count(empty.id) == 1:
        spans = _cnvpr_spans(xml, empty.id)
        for start, _end, _attrs, _closing in reversed(spans):
            sp_end = xml.find("</p:sp>", start)
            if sp_end < 0:
                continue
            xml = xml[:start] + _fill_title(xml[start:sp_end], off,
                                            _title_run(title, language)) + xml[sp_end:]
        if spans:
            return xml, 1
    ids = [int(i) for i in re.findall(r'<p:cNvPr\b[^>]*?\sid="(\d+)"', xml)]
    new_id = max(ids, default=1) + 1
    element = ('<p:sp><p:nvSpPr><p:cNvPr id="%d" name="Title %d"/><p:cNvSpPr>'
               '<a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="title"/></p:nvPr>'
               '</p:nvSpPr><p:spPr>%s</p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p>%s'
               '</a:p></p:txBody></p:sp>' % (new_id, new_id, off, _title_run(title, language)))
    # first in the tree, so it's read first: after the tree's own group
    # properties, which don't nest
    tree = xml.find("<p:spTree>")
    props = start_tag("p:grpSpPr").search(xml, tree) if tree >= 0 else None
    if props is None:
        return xml, 0
    at = props.end() if props.group(2) else xml.find("</p:grpSpPr>", props.end()) + len("</p:grpSpPr>")
    return xml[:at] + element + xml[at:], 1


# A run or a field, a run's properties, and a paragraph, none of which
# nests in its own kind.
RUN = re.compile(r"<a:(r|fld)\b[^>]*>.*?</a:\1>", re.S)
RPR = re.compile(r"<a:rPr\b[^>]*?(?:/>|>.*?</a:rPr>)", re.S)
PARAGRAPH = re.compile(r"<a:p\b[^>]*?(?:/>|>(.*?)</a:p>)", re.S)


def _retitle_body(body, old, new):
    """A title's text body with new for its text: what old lacks added
    after its last run, in that run's formatting, when new begins with
    old; otherwise one paragraph of one run in place of all of them, in
    the first paragraph's and the first run's formatting."""
    runs = list(RUN.finditer(body))
    if new.startswith(old) and runs:
        last = runs[-1]
        rpr = RPR.search(last.group(0))
        run = "<a:r>%s<a:t>%s</a:t></a:r>" % (rpr.group(0) if rpr else "", _text(new[len(old):]))
        return body[:last.end()] + run + body[last.end():]
    paragraphs = list(PARAGRAPH.finditer(body))
    if not paragraphs:
        return None
    inner = paragraphs[0].group(1) or ""
    ppr = re.match(r"\s*(<a:pPr\b[^>]*?(?:/>|>.*?</a:pPr>))", inner, re.S)
    end = re.search(r"<a:endParaRPr\b[^>]*?(?:/>|>.*?</a:endParaRPr>)", inner, re.S)
    rpr = RPR.search(runs[0].group(0)) if runs else None
    paragraph = "<a:p>%s<a:r>%s<a:t>%s</a:t></a:r>%s</a:p>" % (
        ppr.group(1) if ppr else "", rpr.group(0) if rpr else "", _text(new),
        end.group(0) if end else "")
    return body[:paragraphs[0].start()] + paragraph + body[paragraphs[-1].end():]


def retitle(xml, slide, title):
    """xml with a slide's title, which another slide has too, replaced by
    title, in its Choice and its Fallback alike: (xml, count)."""
    shape = slide.title_shape
    shapes = list(slide.all_shapes())
    if shape is None or not shape.id or [s.id for s in shapes].count(shape.id) != 1:
        return xml, 0
    old, count = slide.title, 0
    for start, _end, _attrs, _closing in reversed(_cnvpr_spans(xml, shape.id)):
        close = xml.find("</p:sp>", start)
        body = start_tag("p:txBody").search(xml, start, close) if close >= 0 else None
        if body is None or body.group(2):
            continue
        end = xml.find("</p:txBody>", body.end(), close)
        changed = _retitle_body(xml[body.end():end], old, title) if end >= 0 else None
        if changed is not None:
            xml = xml[:body.end()] + changed + xml[end:]
            count = 1
    return xml, count


def _lang_on_defaults(region, language):
    """A text style list with a language on each default run property that
    declares none; (region, count)."""
    count = 0

    def tag(match):
        nonlocal count
        attrs, close = match.group(1), match.group(2)
        if re.search(r'\slang="', attrs):
            return match.group(0)
        count += 1
        return '<a:defRPr%s lang="%s"%s>' % (attrs, _attr(language), close)

    return re.sub(r"<a:defRPr%s(/?)>" % ATTRS, tag, region), count


def _in_elements(xml, names, edit):
    """xml with edit applied inside each element named; (xml, count)."""
    total = 0
    for name in names:
        out, at = [], 0
        for match in start_tag(name).finditer(xml):
            if match.start() < at or match.group(2):
                continue
            end = xml.find("</%s>" % name, match.end())
            if end < 0:
                continue
            region, n = edit(xml[match.end():end])
            out.append(xml[at:match.end()] + region)
            at = end
            total += n
        xml = "".join(out) + xml[at:]
    return xml, total


# What may come between a presentation's notes size and its default text
# style, in the schema's order.
BEFORE_DEFAULT_STYLE = ("p:smartTags", "p:embeddedFontLst", "p:custShowLst", "p:photoAlbum",
                        "p:custDataLst", "p:kinsoku")


def _after_notes_size(xml):
    """Where a default text style goes in presentation.xml: after
    p:notesSz and the elements the schema puts between, or -1."""
    def past(match, name):
        """Where an element that starts at match ends."""
        if match.group(2):
            return match.end()
        close = xml.find("</%s>" % name, match.end())
        return close + len("</%s>" % name) if close >= 0 else -1

    size = start_tag("p:notesSz").search(xml)
    at = past(size, "p:notesSz") if size is not None else -1
    for name in BEFORE_DEFAULT_STYLE:
        if at < 0:
            break
        found = start_tag(name).match(xml, len(xml) - len(xml[at:].lstrip()))
        if found is not None:
            at = past(found, name)
    return at


def set_default_language(xml, language):
    """presentation.xml with the deck's default language where PowerPoint
    writes it, on the default text style's defPPr, added when the style
    has none; and on each level's defaults that declare none. (xml, count)"""
    lang = _attr(language)
    match = start_tag("p:defaultTextStyle").search(xml)
    if match is None:
        # No default text style at all: one with the language alone, where
        # the schema's order puts it, after the notes' size and whichever
        # of the elements between them the presentation has.
        at = _after_notes_size(xml)
        if at < 0:
            return xml, 0
        return (xml[:at] + '<p:defaultTextStyle><a:defPPr><a:defRPr lang="%s"/></a:defPPr>'
                '</p:defaultTextStyle>' % lang + xml[at:]), 1
    if match.group(2):
        return (xml[:match.start()] + '<p:defaultTextStyle%s><a:defPPr><a:defRPr lang="%s"/>'
                '</a:defPPr></p:defaultTextStyle>' % (match.group(1), lang)
                + xml[match.end():]), 1
    end = xml.find("</p:defaultTextStyle>", match.end())
    region = xml[match.end():end]
    count = 0
    pp = start_tag("a:defPPr").search(region)
    if pp is None:
        region = '<a:defPPr><a:defRPr lang="%s"/></a:defPPr>' % lang + region
        count += 1
    elif pp.group(2):
        region = (region[:pp.start()] + '<a:defPPr%s><a:defRPr lang="%s"/></a:defPPr>'
                  % (pp.group(1), lang) + region[pp.end():])
        count += 1
    else:
        close = region.find("</a:defPPr>", pp.end())
        if not start_tag("a:defRPr").search(region, pp.end(), close):
            # defRPr comes last but for an extension list
            ext = region.find("<a:extLst", pp.end(), close)
            at = ext if ext >= 0 else close
            region = region[:at] + '<a:defRPr lang="%s"/>' % lang + region[at:]
            count += 1
    region, n = _lang_on_defaults(region, language)
    return xml[:match.end()] + region + xml[end:], count + n


def set_master_language(xml, language):
    """A slide master's or notes master's text styles with the language on
    each default that declares none; (xml, count)."""
    return _in_elements(xml, ("p:txStyles", "p:notesStyle"),
                        lambda region: _lang_on_defaults(region, language))


def set_core_title(xml, title):
    """core.xml with a title when it has none."""
    if re.search(r"<dc:title>\s*[^\s<]", xml):
        return xml, 0
    element = "<dc:title>%s</dc:title>" % _text(title)
    if re.search(r"<dc:title\s*/>|<dc:title>\s*</dc:title>", xml):
        return re.sub(r"<dc:title\s*/>|<dc:title>\s*</dc:title>", lambda _match: element, xml,
                      count=1), 1
    match = re.search(r"<cp:coreProperties\b[^>]*>", xml)
    if not match or "xmlns:dc=" not in xml:
        return xml, 0
    return xml[:match.end()] + element + xml[match.end():], 1


def repair_part(xml):
    """A part with what PowerPoint can't read put right, where nothing is
    lost by it: (xml, empty shapes taken out, prefixes declared). Each
    prefix is declared first among the root's attributes, as the deck
    PowerPoint opened had it; a part that still wouldn't parse keeps its
    prefixes as they were, and its copy's check names it."""
    removed = 0
    while True:                 # a group emptied by taking out its shapes
        xml, n = EMPTY_SHAPE.subn("", xml)
        if not n:
            break
        removed += n
    fixed, declared = pptxparse.declare_unbound(xml)
    if fixed is None:
        return xml, removed, []
    return fixed, removed, declared


# --------------------------------------------------------------------------
# the copy
# --------------------------------------------------------------------------

def remediate(source, destination, alts=None, tables=None, titles=None, language=None,
              core_title=True, deck=None, orders=None, problems=None):
    """Write source's decisions into destination; counts of what was
    written. alts, tables, titles, orders as alt_rows(), header_rows(),
    title_rows(), and order_rows() read them; deck, the name keys use
    (deck_name()). The file's properties get core_title as their title
    when they have none, or, when it's True, the first slide's title, the
    sidecar's if the slide has none of its own. problems, a list, is told
    each order not written, by its slide's key, and why."""
    alts, tables, titles, orders = alts or {}, tables or {}, titles or {}, orders or {}
    deck = deck or deck_name(source)
    parsed = pptxparse.read(source)
    if core_title is True:
        first = parsed.slides[0] if parsed.slides else None
        core_title = first and (first.title or titles.get(slide_key(deck, first)))
    counts = {"described": 0, "decorative": 0, "header_rows": 0, "header_columns": 0,
              "titles": 0, "language": 0, "core_title": 0, "repaired": 0, "skipped": 0,
              "orders": 0, "orders_refused": 0, "retitled": 0}
    with zipfile.ZipFile(source) as zin:
        infos = zin.infolist()
        parts = {info.filename: zin.read(info.filename) for info in infos}
    texts, encodings = {}, {}

    def text_of(part):
        """A part's XML as text, UTF-8 or UTF-16 as OPC allows, written
        back as it was found."""
        if part not in texts:
            texts[part], encodings[part] = pptxparse.part_text(parts[part])
        return texts[part]

    # What PowerPoint can't read as written is put right first, so the
    # decisions go into XML it reads.
    for part in sorted({part for part, _problem in parsed.malformed}):
        xml, removed, declared = repair_part(text_of(part))
        if removed or declared:
            texts[part] = xml
            counts["repaired"] += removed + len(declared)

    shapes_by_part = [(slide.part, slide, list(slide.all_shapes())) for slide in parsed.slides]
    shapes_by_part += [(part, None, [s for top in tops for s in top.walk()])
                       for part, tops in parsed.masters]
    for part, slide, shapes in shapes_by_part:
        done = set()
        # A shape is found by its id, which PowerPoint keeps unique on a
        # slide; a file that repeats one would have the edit land on
        # every shape with it, so a decision for such a shape is skipped.
        repeated = {i for i, n in Counter(s.id for s in shapes if s.id).items() if n > 1}
        for shape in shapes:
            if not shape.id or shape.id in done:
                continue
            if shape.id in repeated:
                found = decision(alts, deck, slide, shape)[0] or (
                    shape.table is not None and shape.table.key() in tables)
                counts["skipped"] += 1 if found else 0
                done.add(shape.id)
                continue
            found, alt = decision(alts, deck, slide, shape)
            if found and alt != "":
                xml, n = set_alt(text_of(part), shape.id, alt, alt is None)
                if n:
                    texts[part] = xml
                    done.add(shape.id)
                    counts["decorative" if alt is None else "described"] += 1
            if shape.table is not None:
                headers = tables.get(shape.table.key())
                if headers in HEADERS:
                    xml, n = set_headers(text_of(part), shape.id, headers)
                    if n:
                        texts[part] = xml
                        counts["header_rows"] += headers in ("first-row", "both")
                        counts["header_columns"] += headers in ("first-column", "both")
        # The reading order, before a title is added first in the tree: the
        # shapes the order names take their places in it, unless that would
        # draw two that overlap the other way round.
        ids = orders.get(slide_key(deck, slide)) if slide is not None else None
        if ids:
            xml = text_of(part)
            kids = pptxorder.tree(xml, slide)
            arrangement, why = pptxorder.arrange(kids, ids) if kids else (
                None, "the slide has no shapes to put in order")
            if why:
                counts["orders_refused"] += 1
                if problems is not None:
                    problems.append((slide_key(deck, slide), why))
            elif arrangement != list(range(len(kids))):
                texts[part] = pptxorder.rewrite(xml, kids, arrangement)
                counts["orders"] += 1
        if slide is not None and slide.title:
            # A title another slide has too, replaced on the slide
            title = titles.get(slide_key(deck, slide))
            shape = slide.title_shape
            if title and title != slide.title and shape.id in repeated:
                counts["skipped"] += 1
            elif title and title != slide.title:
                xml, n = retitle(text_of(part), slide, title)
                if n:
                    texts[part] = xml
                    counts["retitled"] += 1
        if slide is not None and not slide.title:
            title = titles.get(slide_key(deck, slide))
            if title:
                xml, n = add_title(text_of(part), slide, title, parsed.width,
                                   language or parsed.language)
                if n:
                    texts[part] = xml
                    counts["titles"] += 1
    # The language goes where PowerPoint declares a deck's, its default
    # text style and its masters' text styles, which every run that says
    # nothing of its own inherits, and only when the deck has no default:
    # a run that names a language is the author's.
    if language and not parsed.default_language:
        edits = 0
        for part in sorted(parts):
            if part == parsed.presentation_part:
                xml, n = set_default_language(text_of(part), language)
            elif re.match(r"ppt/(slideMasters|notesMasters)/[^/]+\.xml$", part):
                xml, n = set_master_language(text_of(part), language)
            else:
                continue
            if n:
                texts[part] = xml
                edits += n
        counts["language"] += 1 if edits else 0
    if core_title and "docProps/core.xml" in parts and not parsed.core_title:
        xml, n = set_core_title(text_of("docProps/core.xml"), core_title)
        if n:
            texts["docProps/core.xml"] = xml
            counts["core_title"] += 1
    for part, xml in texts.items():
        if xml != pptxparse.part_text(parts[part])[0]:
            parts[part] = pptxparse.encode_part(xml, encodings[part])
    folder = os.path.dirname(os.path.abspath(destination))
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(suffix=".pptx", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp, "w") as zout:
            for info in infos:
                zout.writestr(info, parts[info.filename])
        # mkstemp's file is the owner's alone; a copy is for handing on
        os.chmod(temp, 0o666 & ~current_umask())
        shutil.move(temp, destination)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return counts
