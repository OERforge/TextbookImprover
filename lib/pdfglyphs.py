"""
pdfglyphs.py -- a figure's glyphs given the Unicode their names give them,
where its PDF names a glyph and maps it to nothing.

A simple font in a PDF (Type 1, TrueType, or Type 3) can know a glyph by
its name alone, in its encoding's Differences, with no ToUnicode entry
for it. PDF/UA wants every glyph's text known (ISO 14289-2, 8.4.5.8, as
veraPDF's PDF/UA-2 profile checks it), and a name the Adobe Glyph List
holds (zero, parenleft, alpha) gives it. A name the list doesn't hold, but
whose specification's rules give it a character, doesn't, for veraPDF:
one with a suffix after a period (minus.case, a font's minus sign for
capitals), ligatures' names joined by underscores (f_f_i), and uniXXXX or
uXXXX. Ghostscript's pdfwrite, which epstopdf runs on an EPS and which
embeds a PDF image's fonts (latexbuild.EMBED_GS), writes no ToUnicode
entry for such a name, in 10.02.1 and 10.07.1 alike (measured,
2026-10-30): matplotlib's EPS, whose fonts are Type 3 fonts it names the
TrueType font's glyphs in, drew its minus sign in Inter as minus.case, and
veraPDF's PDF/UA-2 profile failed the one glyph.

Each font whose encoding names such a glyph gets a ToUnicode entry for
every glyph it names that the specification maps (to_unicode), the
entries it has kept. A font whose names are all the list's own is left as
it is, as veraPDF reads them. The Adobe Glyph List is
vendor/agl/glyphlist.txt, Adobe's file as it is, with its license
(https://github.com/adobe-type-tools/agl-aglfn, BSD-3-Clause); its
specification is https://github.com/adobe-type-tools/agl-specification.

Needs pikepdf; without it, the file is left as it is.

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

import os
import re

try:
    import pikepdf
except ImportError:  # pragma: no cover -- the caller says what's missing
    pikepdf = None

GLYPH_LIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "vendor", "agl", "glyphlist.txt")
_LIST = None

SIMPLE = {"/Type1", "/MMType1", "/TrueType", "/Type3"}
UNI = re.compile(r"uni((?:[0-9A-F]{4})+)")
U = re.compile(r"u([0-9A-F]{4,6})")


def glyph_list():
    """{name: its characters}, the Adobe Glyph List's."""
    global _LIST
    if _LIST is None:
        found = {}
        with open(GLYPH_LIST, encoding="ascii") as fh:
            for line in fh:
                if line.startswith("#") or ";" not in line:
                    continue
                name, values = line.strip().split(";", 1)
                found[name] = "".join(chr(int(v, 16)) for v in values.split())
        _LIST = found
    return _LIST


def to_unicode(name):
    """The characters the Adobe Glyph List's specification maps a glyph's
    name to ("" where it maps it to none): what precedes the first period,
    each of its parts between underscores mapped by the list, as uniXXXX
    (each four digits a scalar value of the Basic Multilingual Plane), or
    as uXXXX to uXXXXXX, and the rest to nothing. Not ITC Zapf Dingbats'
    names, whose own list the specification maps that font's by."""
    agl = glyph_list()
    out = []
    for part in name.split(".", 1)[0].split("_"):
        if part in agl:
            out.append(agl[part])
            continue
        m = UNI.fullmatch(part)
        if m:
            values = [int(m.group(1)[i:i + 4], 16) for i in range(0, len(m.group(1)), 4)]
            if all(v <= 0xD7FF or 0xE000 <= v <= 0xFFFF for v in values):
                out.append("".join(chr(v) for v in values))
            continue
        m = U.fullmatch(part)
        if m:
            v = int(m.group(1), 16)
            if v <= 0xD7FF or 0xE000 <= v <= 0x10FFFF:
                out.append(chr(v))
    return "".join(out)


def utf16_hex(text):
    """text as the UTF-16BE hexadecimal a ToUnicode CMap writes."""
    return text.encode("utf-16-be").hex().upper()


def cmap_entries(data):
    """{code: UTF-16BE hex} of a ToUnicode CMap of one-byte codes, its
    bfchar and bfrange entries; None where it has others, a code of more
    than a byte or a range mapped to an array, which aren't read here."""
    text = data.decode("latin-1")
    if re.search(r"<[0-9A-Fa-f]{3,}>\s*<[0-9A-Fa-f]{3,}>\s*endcodespacerange", text):
        return None
    found = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for code, value in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            found[int(code, 16)] = value.upper()
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        if "[" in block:
            return None
        for first, last, value in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            start = int(value, 16)
            for k, code in enumerate(range(int(first, 16), int(last, 16) + 1)):
                found[code] = "%0*X" % (len(value), start + k)
    return found


def cmap_stream(entries):
    """A ToUnicode CMap's bytes, mapping each one-byte code to its hex."""
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             "1 begincodespacerange", "<00> <FF>", "endcodespacerange"]
    codes = sorted(entries)
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        lines.append("%d beginbfchar" % len(chunk))
        lines.extend("<%02X> <%s>" % (code, entries[code]) for code in chunk)
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return ("\n".join(lines) + "\n").encode("ascii")


def named_codes(font):
    """{code: glyph name} of a simple font's encoding's Differences, an
    entry that's neither a name nor a code skipped."""
    encoding = font.get("/Encoding")
    if not isinstance(encoding, pikepdf.Dictionary) or "/Differences" not in encoding:
        return {}
    differences = encoding.Differences
    if not isinstance(differences, pikepdf.Array):
        return {}
    found, code = {}, 0
    for item in differences:
        if isinstance(item, pikepdf.Name):
            found[code] = str(item)[1:]
            code += 1
        elif isinstance(item, int) and not isinstance(item, bool):
            code = item
    return found


def fonts(pdf):
    """Each font dictionary the PDF's pages draw with, form XObjects' and
    Type 3 glyphs' resources too, an indirect one once. A direct
    dictionary has one place in the file, so it's reached once: told
    apart by id(), as they had been, pikepdf's wrapper of one was freed
    and its id given another's, and a form's resources after the first
    with resources of its own were skipped (a review: GIAM's drawings'
    pages have 93 such forms)."""
    seen, found = set(), []

    def first(item):
        if not item.is_indirect:
            return True
        if item.objgen in seen:
            return False
        seen.add(item.objgen)
        return True

    def values(named):
        # items(), since pikepdf 8.7.1, Ubuntu 24.04's, has no values():
        # the AttributeError was taken for resources pikepdf can't follow,
        # and no font was mended (Python 3.12's suites).
        if not isinstance(named, pikepdf.Dictionary):
            return []
        return [value for _, value in named.items()]

    def walk(resources):
        if not isinstance(resources, pikepdf.Dictionary) or not first(resources):
            return
        for font in values(resources.get("/Font")):
            if isinstance(font, pikepdf.Dictionary) and first(font):
                found.append(font)
                walk(font.get("/Resources"))
        for xobject in values(resources.get("/XObject")):
            if (isinstance(xobject, pikepdf.Stream) and xobject.get("/Subtype") == "/Form"
                    and first(xobject)):
                walk(xobject.get("/Resources"))

    for page in pdf.pages:
        walk(page.obj.get("/Resources"))
    return found


def map_glyph_names(path):
    """The PDF at path with each simple font whose encoding names a glyph
    the Adobe Glyph List doesn't, but its specification maps, given a
    ToUnicode entry for each glyph its encoding names that maps
    (to_unicode), its own entries kept: the number of glyphs given one, 0
    where none needed it; None where pikepdf isn't installed or can't
    read the file."""
    if pikepdf is None:
        return None
    agl = glyph_list()
    try:
        pdf = pikepdf.open(path, allow_overwriting_input=True)
    except Exception:  # noqa: BLE001 -- a PDF pikepdf can't read is left alone
        return None
    added = 0
    with pdf:
        try:
            found = fonts(pdf)
        except Exception:  # noqa: BLE001 -- resources pikepdf can't follow
            return 0
        for font in found:
            # A font whose dictionary isn't as the PDF reference has it, a
            # code that isn't a number in its Differences, say, is left as
            # it is: poppler draws such a figure, and it had stopped the
            # conversion (a review).
            try:
                added += map_font(pdf, font, agl)
            except Exception:  # noqa: BLE001 -- a font pikepdf can't read as one
                continue
        if added:
            pdf.save(path)
    return added


def map_font(pdf, font, agl):
    """The ToUnicode entries map_glyph_names gives one font, as it gives
    them; how many."""
    subtype = font.get("/Subtype")
    if subtype not in SIMPLE or "ZapfDingbats" in str(font.get("/BaseFont", "")):
        return 0
    names = named_codes(font)
    entries = {}
    if "/ToUnicode" in font:
        try:
            entries = cmap_entries(font.ToUnicode.read_bytes())
        except Exception:  # noqa: BLE001 -- a CMap pikepdf can't read
            entries = None
        if entries is None:
            return 0
    wanted = {code: to_unicode(name) for code, name in names.items()
              if code not in entries and name not in agl and name != ".notdef"}
    if not any(wanted.values()):
        return 0
    added = 0
    for code, name in names.items():
        if code not in entries:
            text = to_unicode(name)
            if text:
                entries[code] = utf16_hex(text)
                added += 1
    font.ToUnicode = pdf.make_stream(cmap_stream(entries))
    return added
