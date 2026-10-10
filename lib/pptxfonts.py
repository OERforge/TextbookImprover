"""
pptxfonts.py -- the fonts a PowerPoint deck embeds and names, which of
them a license keeps a deck from being edited with, and a copy that uses
another font in such a one's place.

PowerPoint can save the fonts a deck uses inside it (Embed fonts in the
file, which is the presentation's embedTrueTypeFonts), each as an
Embedded OpenType file in ppt/fonts/, holding only the characters the deck
uses when saveSubsetFonts is on, so the deck looks the same on a computer
without them. A font's license says how it may be embedded, in its OS/2
table's fsType, which the EOT file's header carries over: installable (no
bit), editable (8), preview and print only (4), or not at all (2), the
least restrictive bit set being the one in force
(https://learn.microsoft.com/en-us/typography/opentype/spec/os2#fstype).
A deck that embeds a font for preview and print only opens read-only on a
computer that doesn't have the font, as the license asks; and a deck that
uses such a font without embedding it, set to embed its fonts, can't be
saved on one: PowerPoint says the font isn't available. Both were seen
in ten decks made with Avenir Next, which macOS has and Windows doesn't:
six embedded it for preview and print only, and the other four used it
without embedding it, one of which PowerPoint opened for editing and then
wouldn't save.

A font is named restricted here when a deck embeds it so; a run names the
decks that embed it and those that use it without embedding it
(deckrun.py). A copy can use another font in its place
(fonts.restricted: replace): the one fonts.replacements names, else the
one the deck already uses whose PANOSE is nearest, the ten digits a deck
writes beside a typeface that classify how it looks (the kind of font,
its serif style, weight, proportion, contrast, and so on). Every element
naming the font names the other instead, with the other's PANOSE, pitch,
and character set where the deck gives them, and the restricted font's
embedded files are taken out, so the copy opens for editing anywhere.

The XML is edited as text, never parsed and written again.

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
import posixpath
import re
import struct
from collections import Counter, OrderedDict

# An OS/2 table's fsType bits (the OpenType specification's names).
RESTRICTED_LICENSE, PREVIEW_PRINT, EDITABLE = 0x0002, 0x0004, 0x0008
FONT_RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"
ATTRS = r"((?:\s+[\w:.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)"
ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
# The elements that name a typeface: text's (Latin, East Asian, complex
# script, and symbol), a bullet's, and a theme's fonts for a script.
TYPEFACE = re.compile(r"<(a:(?:latin|ea|cs|sym|buFont|font))%s\s*(/?)>" % ATTRS)
EMBEDDED_FONT = re.compile(r"<p:embeddedFont\b[^>]*>.*?</p:embeddedFont>", re.S)
STYLES = ("regular", "bold", "italic", "boldItalic")
# What a typeface carries beside its name, in the order PowerPoint writes it.
TRAITS = ("panose", "pitchFamily", "charset")
BOMS = ((b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))


def attributes(text):
    """A start tag's attributes, their values as written, escaped."""
    return OrderedDict((m.group(1), m.group(2) if m.group(2) is not None else m.group(3))
                       for m in ATTR.finditer(text or ""))


def name_of(a):
    """The typeface an element's attributes name, unescaped."""
    return html.unescape(a.get("typeface") or "")


def escaped(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def decoded(data):
    """A part's XML as text, UTF-8 or UTF-16 with its mark, as OPC allows."""
    for bom, codec in BOMS:
        if data.startswith(bom):
            return data[len(bom):].decode(codec, "replace")
    return data.decode("utf-8", "replace")


def eot_header(data):
    """(family, fsType, PANOSE) from an Embedded OpenType file's header,
    or None when data isn't one (https://www.w3.org/Submission/EOT/)."""
    if len(data) < 84 or struct.unpack_from("<H", data, 34)[0] != 0x504C:
        return None
    version, = struct.unpack_from("<I", data, 8)
    fstype, = struct.unpack_from("<H", data, 32)
    # Version 1 has no padding before the family name; 2.1 and 2.2 do.
    at = 80 if version < 0x00020001 else 82
    size, = struct.unpack_from("<H", data, at)
    family = data[at + 2:at + 2 + size].decode("utf-16-le", "replace").rstrip("\x00")
    return family, fstype, data[16:26].hex().upper()


def restricted(fstype):
    """Whether an embedding license keeps a deck that embeds the font from
    being edited: preview and print only, or not to be embedded at all,
    and not editable."""
    return not fstype & EDITABLE and bool(fstype & (RESTRICTED_LICENSE | PREVIEW_PRINT))


def license(fstype):
    """How a font a license restricts is embedded, in words."""
    return ("for preview and print only" if fstype & PREVIEW_PRINT
            else "though its license forbids it")


class Embedded:
    """A typeface a deck embeds: each style's relationship id and part,
    the license its files carry (the most restrictive of theirs), and its
    PANOSE."""

    __slots__ = ("typeface", "styles", "fstype", "panose")

    def __init__(self, typeface):
        self.typeface = typeface
        self.styles = OrderedDict()     # style: (relationship id, part or None)
        self.fstype = None
        self.panose = None

    @property
    def restricted(self):
        return self.fstype is not None and restricted(self.fstype)


class Fonts:
    """The fonts a deck embeds, and the typefaces its text, bullets, and
    themes name: how many times each is named, and what's written beside
    it, its PANOSE, pitch, and character set, as the first element naming
    it with a PANOSE gives them."""

    __slots__ = ("embedded", "used", "traits", "embedding")

    def __init__(self):
        self.embedded = OrderedDict()   # typeface: Embedded
        self.used = Counter()
        self.traits = {}
        self.embedding = False          # whether PowerPoint embeds fonts on saving

    def restricted(self):
        """{typeface: fsType} of the fonts the deck embeds restricted."""
        return OrderedDict((t, e.fstype) for t, e in self.embedded.items() if e.restricted)

    def panose(self, typeface):
        """A typeface's PANOSE, as the deck writes it beside the name, or as
        its embedded file's header gives it."""
        found = self.traits.get(typeface, {}).get("panose")
        if not found and typeface in self.embedded:
            found = self.embedded[typeface].panose
        return found if found and re.match(r"[0-9A-Fa-f]{20}$", found) else None


def relationships_part(part):
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", name + ".rels")


def relationships(xml, part):
    """{id: (type, target part, element's span)} from a relationships
    part's XML; target None for an external one."""
    folder = posixpath.dirname(part)
    out = OrderedDict()
    for m in re.finditer(r"<Relationship\b%s\s*(?:/>|>\s*</Relationship>)" % ATTRS, xml or ""):
        a = attributes(m.group(1))
        target = a.get("Target") or ""
        if a.get("TargetMode") == "External":
            target = None
        elif target.startswith("/"):
            target = target.lstrip("/")
        else:
            target = posixpath.normpath(posixpath.join(folder, target))
        out[a.get("Id")] = (a.get("Type") or "", target, m.span())
    return out


def read(names, data, presentation_part="ppt/presentation.xml"):
    """A deck's Fonts. names: its parts' names; data(name): a part's
    bytes."""
    fonts = Fonts()
    pres = decoded(data(presentation_part)) if presentation_part in names else ""
    root = re.search(r"<p:presentation\b%s\s*/?>" % ATTRS, pres)
    fonts.embedding = bool(root) and attributes(root.group(1)).get(
        "embedTrueTypeFonts") in ("1", "true")
    rels_name = relationships_part(presentation_part)
    rels = relationships(decoded(data(rels_name)) if rels_name in names else "",
                         presentation_part)
    for entry in EMBEDDED_FONT.finditer(pres):
        font = re.search(r"<p:font\b%s\s*/?>" % ATTRS, entry.group(0))
        typeface = name_of(attributes(font.group(1))) if font else None
        if not typeface:
            continue
        embedded = fonts.embedded.setdefault(typeface, Embedded(typeface))
        embedded.panose = attributes(font.group(1)).get("panose") or embedded.panose
        for style in STYLES:
            ref = re.search(r"<p:%s\b%s\s*/?>" % (style, ATTRS), entry.group(0))
            rid = attributes(ref.group(1)).get("r:id") if ref else None
            if not rid:
                continue
            part = rels.get(rid, (None, None))[1]
            embedded.styles[style] = (rid, part)
            header = eot_header(data(part)) if part in names else None
            if header:
                # The most restrictive file's license is the font's: an
                # installable regular and a preview-only bold still open
                # read-only.
                if embedded.fstype is None or restricted(header[1]) \
                        and not restricted(embedded.fstype):
                    embedded.fstype = header[1]
                if not embedded.panose and header[2].strip("0"):
                    embedded.panose = header[2]
    for name in names:
        if not name.endswith(".xml") or name.startswith("["):
            continue
        for m in TYPEFACE.finditer(decoded(data(name))):
            a = attributes(m.group(2))
            typeface = name_of(a)
            if not typeface or typeface.startswith("+"):
                continue
            fonts.used[typeface] += 1
            if typeface not in fonts.traits and a.get("panose"):
                fonts.traits[typeface] = OrderedDict((k, a[k]) for k in TRAITS if k in a)
    return fonts


def distance(panose, other):
    """How far apart two PANOSE numbers are, for sorting: a different serif
    style first (sans, or which serif), then how many digits differ, then
    by how much in all; None when they're different kinds of font (text,
    handwriting, decorative, symbol) or either is unknown."""
    if not panose or not other:
        return None
    a = [int(panose[i:i + 2], 16) for i in range(0, 20, 2)]
    b = [int(other[i:i + 2], 16) for i in range(0, 20, 2)]
    if a[0] != b[0] or a[0] < 2:
        return None
    return (a[1] != b[1], sum(x != y for x, y in zip(a, b)),
            sum(abs(x - y) for x, y in zip(a, b)))


def nearest(fonts, typeface, avoid=()):
    """The typeface the deck names whose PANOSE is nearest typeface's, not
    one of avoid's, nor one the deck embeds restricted; None when none is
    of its kind."""
    panose = fonts.panose(typeface)
    found = []
    for other in sorted(set(fonts.used) | set(fonts.embedded)):
        if other == typeface or other in avoid or (
                other in fonts.embedded and fonts.embedded[other].restricted):
            continue
        apart = distance(panose, fonts.panose(other))
        if apart is not None:
            found.append((apart, other))
    return min(found)[1] if found else None


def retypeface(xml, old, new, traits=None):
    """(xml, count): every element naming typeface old named new instead,
    with traits (TRAITS, as Fonts.traits gives them) for its PANOSE, pitch,
    and character set, or none of them when traits is None. Names are
    unescaped; every other attribute is kept as it's written."""
    count = 0

    def edit(m):
        nonlocal count
        a = attributes(m.group(2))
        if name_of(a) != old:
            return m.group(0)
        count += 1
        out = OrderedDict()
        for k, v in a.items():
            if k == "typeface":
                out[k] = escaped(new)
                out.update(traits or {})
            elif k not in TRAITS:
                out[k] = v.replace('"', "&quot;")
        return "<%s%s%s>" % (m.group(1), "".join(' %s="%s"' % kv for kv in out.items()),
                             m.group(3))

    return TYPEFACE.sub(edit, xml), count


def unembed(pres, rels, typeface, presentation_part="ppt/presentation.xml"):
    """(presentation XML, its relationships' XML, parts no longer used):
    a typeface's entry taken out of the embedded font list (the list too
    when it's left empty), with the relationships its files had."""
    gone = []
    for entry in list(EMBEDDED_FONT.finditer(pres))[::-1]:
        font = re.search(r"<p:font\b%s\s*/?>" % ATTRS, entry.group(0))
        if not font or name_of(attributes(font.group(1))) != typeface:
            continue
        gone += re.findall(r"""\br:id\s*=\s*["']([^"']+)["']""", entry.group(0))
        pres = pres[:entry.start()] + pres[entry.end():]
    pres = re.sub(r"<p:embeddedFontLst\b[^>]*>\s*</p:embeddedFontLst>|<p:embeddedFontLst\s*/>",
                  "", pres)
    found = relationships(rels, presentation_part)
    parts = []
    for rid in gone:
        if rid in found and found[rid][0] == FONT_RELATIONSHIP:
            parts.append(found[rid][1])
    spans = sorted((found[rid][2] for rid in gone if rid in found), reverse=True)
    for start, end in spans:
        rels = rels[:start] + rels[end:]
    still = {t for _type, t, _span in relationships(rels, presentation_part).values()}
    return pres, rels, [p for p in parts if p and p not in still]
