"""
pdftext.py -- the text a tagged PDF holds for its structure elements, as
a screen reader gets it: the characters each marked-content sequence
shows, each font's codes read through its /ToUnicode map (a simple font's
encoding naming those the map lacks), and no space inferred from where
words sit on the page, as a text extractor infers one. Reads the PDF with
pikepdf alone, which the suites that use this need for the PDF anyway.

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

import re

try:
    import pikepdf
except ImportError:  # the suites' PDF cases need it, and skip without it
    pikepdf = None

# A CMap's tokens: a hex string, an array's brackets, a literal string or a
# dictionary's brackets (passed over), and any other word.
_TOKEN = re.compile(rb"<([0-9A-Fa-f\s]*)>|(\[)|(\])|\([^)]*\)|<<|>>"
                    rb"|(/?[^\s\[\]<>()/%]+|/)")

# The standard encoding's names for the codes from 32 to 126, the printable
# ASCII characters but for its curly quotes.
_STANDARD = ("space exclam quotedbl numbersign dollar percent ampersand quoteright "
             "parenleft parenright asterisk plus comma hyphen period slash zero one two "
             "three four five six seven eight nine colon semicolon less equal greater "
             "question at A B C D E F G H I J K L M N O P Q R S T U V W X Y Z bracketleft "
             "backslash bracketright asciicircum underscore quoteleft a b c d e f g h i j "
             "k l m n o p q r s t u v w x y z braceleft bar braceright asciitilde").split()
_QUOTES = {"quoteright": "’", "quoteleft": "‘", "quotesingle": "'", "grave": "`"}
_NAMES = dict({name: chr(32 + n) for n, name in enumerate(_STANDARD)}, **_QUOTES)


def _glyph(name):
    """The character a glyph's name stands for, or None: a name of the
    standard encoding's, uniXXXX, or uXXXX to uXXXXXX."""
    if name in _NAMES:
        return _NAMES[name]
    found = re.fullmatch(r"uni((?:[0-9A-F]{4})+)", name) or re.fullmatch(r"u([0-9A-F]{4,6})", name)
    if found:
        digits = found.group(1)
        if name.startswith("uni"):
            return "".join(chr(int(digits[n:n + 4], 16)) for n in range(0, len(digits), 4))
        return chr(int(digits, 16)) if int(digits, 16) <= 0x10FFFF else None
    return None


def _utf16(data):
    return data.decode("utf-16-be", "replace")


def _cmap(data):
    """A CMap's codespace ranges, [(low, high)] as bytes, and the characters
    its bfchar and bfrange give codes, {code as a number: text}."""
    ranges, chars = [], {}
    section, operands, array = None, [], None
    for found in _TOKEN.finditer(re.sub(rb"%[^\r\n]*", b"", data)):
        digits, opened, closed, word = found.groups()
        if digits is not None:
            digits = re.sub(rb"\s", b"", digits).decode()
            value = bytes.fromhex(digits + "0" * (len(digits) % 2))
            (operands if array is None else array).append(value)
        elif opened:
            array = []
        elif closed:
            operands.append(array or [])
            array = None
        elif word is None:
            continue
        elif word in (b"begincodespacerange", b"beginbfchar", b"beginbfrange"):
            section, operands = word[5:], []
        elif section is not None and word == b"end" + section:
            if section == b"codespacerange":
                ranges += [(low, high) for low, high in zip(operands[::2], operands[1::2])
                           if isinstance(low, bytes) and isinstance(high, bytes)
                           and len(low) == len(high)]
            elif section == b"bfchar":
                for source, target in zip(operands[::2], operands[1::2]):
                    text = (_utf16(target) if isinstance(target, bytes)
                            else _glyph(target[1:]) if isinstance(target, str)
                            and target.startswith("/") else None)
                    if isinstance(source, bytes) and text is not None:
                        chars[int.from_bytes(source, "big")] = text
            else:
                for low, high, target in zip(operands[::3], operands[1::3], operands[2::3]):
                    if not (isinstance(low, bytes) and isinstance(high, bytes)):
                        continue
                    first = int.from_bytes(low, "big")
                    count = min(int.from_bytes(high, "big") - first, 0xFFFF) + 1
                    if isinstance(target, list):
                        for n, one in enumerate(target[:count]):
                            if isinstance(one, bytes):
                                chars[first + n] = _utf16(one)
                    elif isinstance(target, bytes) and target:
                        # Each code's characters one past the last code's.
                        start, size = int.from_bytes(target, "big"), len(target)
                        for n in range(count):
                            chars[first + n] = _utf16(
                                ((start + n) % (1 << 8 * size)).to_bytes(size, "big"))
            section, operands = None, []
        elif section is not None:
            operands.append(word.decode("latin-1"))  # kept so pairs stay pairs
    return ranges, chars


def _encoding(font):
    """The characters a simple font's encoding gives its codes, by their
    names: the standard encoding's, WinAnsi's, or Mac Roman's, and the
    names its /Differences give. A symbolic font's own encoding is the
    font program's, and gives none."""
    encoding = font.get("/Encoding")
    base, differences = encoding, None
    if isinstance(encoding, pikepdf.Dictionary):
        base, differences = encoding.get("/BaseEncoding"), encoding.get("/Differences")
    base = str(base) if isinstance(base, pikepdf.Name) else "/StandardEncoding"
    codec = {"/WinAnsiEncoding": "cp1252", "/MacRomanEncoding": "mac_roman"}.get(base)
    if codec:
        chars = {}
        for code in range(32, 256):
            try:
                chars[code] = bytes([code]).decode(codec)
            except UnicodeDecodeError:
                pass
    else:
        chars = {32 + n: _NAMES[name] for n, name in enumerate(_STANDARD)}
    code = 0
    for item in differences or []:
        if isinstance(item, int):
            code = item
        else:
            text = _glyph(str(item)[1:])
            if text is not None:
                chars[code] = text
            else:
                chars.pop(code, None)
            code += 1
    return chars


class _Font:
    """How a font's strings split into codes, each code's characters, and
    each code's width, in thousandths of the font's size."""

    def __init__(self, font):
        ranges, self.chars = [], {}
        self.widths, self.default = {}, 0.0
        if font is not None and font.get("/Subtype") == "/Type0":
            descendants = font.get("/DescendantFonts")
            descendant = descendants[0] if isinstance(descendants, pikepdf.Array) \
                and len(descendants) else None
            if isinstance(descendant, pikepdf.Dictionary):
                self.default = float(descendant.get("/DW", 1000))
                items, at = list(descendant.get("/W") or []), 0
                while at + 1 < len(items):
                    first = int(items[at])
                    if isinstance(items[at + 1], pikepdf.Array):
                        for n, width in enumerate(items[at + 1]):
                            self.widths[first + n] = float(width)
                        at += 2
                    elif at + 2 < len(items):
                        for code in range(first, int(items[at + 1]) + 1):
                            self.widths[code] = float(items[at + 2])
                        at += 3
                    else:
                        break
        elif font is not None:
            first = int(font.get("/FirstChar", 0))
            for n, width in enumerate(font.get("/Widths") or []):
                self.widths[first + n] = float(width)
        tounicode = font.get("/ToUnicode") if font is not None else None
        if isinstance(tounicode, pikepdf.Stream):
            ranges, self.chars = _cmap(tounicode.read_bytes())
        if font is not None and font.get("/Subtype") == "/Type0":
            # Codes as the font's encoding CMap splits them: two bytes each
            # for Identity-H and Identity-V, LuaTeX's.
            encoding = font.get("/Encoding")
            own = _cmap(encoding.read_bytes())[0] if isinstance(encoding, pikepdf.Stream) else []
            identity = encoding in ("/Identity-H", "/Identity-V")
            self.ranges = own or (not identity and ranges) or [(b"\0\0", b"\xff\xff")]
        else:
            self.ranges = [(b"\0", b"\xff")]
            if font is not None:
                for code, text in _encoding(font).items():
                    self.chars.setdefault(code, text)

    def codes(self, data):
        """A string's codes, each as a number and its length in bytes."""
        out, at = [], 0
        while at < len(data):
            for size in range(1, 5):
                code = data[at:at + size]
                if len(code) == size and any(
                        len(low) == size and all(lo <= byte <= hi for lo, byte, hi
                                                 in zip(low, code, high))
                        for low, high in self.ranges):
                    break
            else:  # no range holds it: as many bytes as the shortest range's
                size = min(len(low) for low, _ in self.ranges)
                code = data[at:at + size]
            out.append((int.from_bytes(code, "big"), size))
            at += size
        return out

    def text(self, data):
        """A string's characters, ? for a code with none."""
        return "".join(self.chars.get(code, "?") for code, _size in self.codes(data))


def marked_text(path):
    """{(page index, MCID): the characters in that sequence}, text in no
    sequence with an MCID under (page index, None). A form XObject's text
    is the sequence's it's drawn in, as its marked content is."""
    texts, fonts = {}, {}

    def font_of(font):
        key = font.objgen if font is not None and font.is_indirect else id(font)
        if key not in fonts:
            fonts[key] = (font, _Font(font))  # the font kept, so its id isn't reused
        return fonts[key][1]

    def resource(resources, kind, name):
        group = resources.get(kind) if isinstance(resources, pikepdf.Dictionary) else None
        return group.get(name) if isinstance(group, pikepdf.Dictionary) else None

    def show(page, stack, font, data):
        key = (page, next((m for m in reversed(stack) if m is not None), None))
        texts[key] = texts.get(key, "") + font_of(font).text(bytes(data))

    def run(page, contents, resources, stack, drawing, font=None):
        saved = []
        for instruction in pikepdf.parse_content_stream(contents):
            operands, operator = instruction.operands, str(instruction.operator)
            if operator in ("BDC", "BMC"):
                properties = operands[1] if operator == "BDC" and len(operands) > 1 else None
                if isinstance(properties, pikepdf.Name):
                    properties = resource(resources, "/Properties", properties)
                mcid = properties.get("/MCID") if isinstance(properties, pikepdf.Dictionary) else None
                stack.append(int(mcid) if mcid is not None else None)
            elif operator == "EMC":
                if stack:
                    stack.pop()
            elif operator == "q":
                saved.append(font)
            elif operator == "Q":
                font = saved.pop() if saved else font
            elif operator == "Tf" and operands:
                font = resource(resources, "/Font", operands[0])
            elif operator == "gs" and operands:
                state = resource(resources, "/ExtGState", operands[0])
                if isinstance(state, pikepdf.Dictionary) and "/Font" in state:
                    font = state.Font[0]
            elif operator in ("Tj", "'", '"') and operands:
                if isinstance(operands[-1], pikepdf.String):
                    show(page, stack, font, operands[-1])
            elif operator == "TJ" and operands:
                for item in operands[0]:
                    if isinstance(item, pikepdf.String):
                        show(page, stack, font, item)
            elif operator == "Do" and operands:
                drawn = resource(resources, "/XObject", operands[0])
                if (isinstance(drawn, pikepdf.Stream) and drawn.get("/Subtype") == "/Form"
                        and drawn.objgen not in drawing):
                    # In the font it's drawn in, unless it sets its own.
                    run(page, drawn, drawn.get("/Resources", resources), stack,
                        drawing | {drawn.objgen}, font)

    with pikepdf.open(path) as pdf:
        for n, page in enumerate(pdf.pages):
            run(n, page.obj, page.obj.get("/Resources"), [], frozenset())
    return texts


def _times(m, n):
    """The matrix m then n, PDF's [a b c d e f] each."""
    return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]


def glyph_boxes(path):
    """[(page index, baseline, left, right, character)] for each glyph a
    page's own content shows, in the order shown, in points: where it
    starts and ends along its line, from the text and current matrices,
    the font's widths, and the spacing operators. For text set upright,
    as LaTeX sets it; a form XObject's text isn't read."""
    boxes, fonts = [], {}

    def font_of(font):
        key = font.objgen if font is not None and font.is_indirect else id(font)
        if key not in fonts:
            fonts[key] = (font, _Font(font))
        return fonts[key][1]

    with pikepdf.open(path) as pdf:
        for n, page in enumerate(pdf.pages):
            resources = page.obj.get("/Resources")
            group = resources.get("/Font") if isinstance(resources, pikepdf.Dictionary) else None
            state = {"ctm": [1, 0, 0, 1, 0, 0], "font": None, "size": 0.0, "Tc": 0.0,
                     "Tw": 0.0, "Th": 1.0, "TL": 0.0}
            saved, tm, line = [], [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0]
            for instruction in pikepdf.parse_content_stream(page.obj):
                operands, operator = instruction.operands, str(instruction.operator)
                if operator == "q":
                    saved.append(dict(state))
                elif operator == "Q" and saved:
                    state = saved.pop()
                elif operator == "cm" and len(operands) == 6:
                    state["ctm"] = _times([float(x) for x in operands], state["ctm"])
                elif operator == "BT":
                    tm, line = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0]
                elif operator == "Tf" and len(operands) == 2:
                    found = group.get(operands[0]) if isinstance(group, pikepdf.Dictionary) else None
                    state["font"], state["size"] = font_of(found), float(operands[1])
                elif operator in ("Tc", "Tw", "TL") and operands:
                    state[operator] = float(operands[0])
                elif operator == "Tz" and operands:
                    state["Th"] = float(operands[0]) / 100
                elif operator in ("Td", "TD") and len(operands) == 2:
                    if operator == "TD":
                        state["TL"] = -float(operands[1])
                    line = _times([1, 0, 0, 1, float(operands[0]), float(operands[1])], line)
                    tm = list(line)
                elif operator == "Tm" and len(operands) == 6:
                    tm = [float(x) for x in operands]
                    line = list(tm)
                elif operator in ("T*", "'", '"', "Tj", "TJ"):
                    if operator == '"' and len(operands) == 3:
                        state["Tw"], state["Tc"] = float(operands[0]), float(operands[1])
                    if operator in ("T*", "'", '"'):
                        line = _times([1, 0, 0, 1, 0, -state["TL"]], line)
                        tm = list(line)
                    if operator == "T*" or not operands or state["font"] is None:
                        continue
                    font, size, scale = state["font"], state["size"], state["Th"]
                    items = operands[0] if operator == "TJ" else [operands[-1]]
                    for item in items:
                        if not isinstance(item, pikepdf.String):
                            tm = _times([1, 0, 0, 1, -float(item) / 1000 * size * scale, 0], tm)
                            continue
                        for code, length in font.codes(bytes(item)):
                            width = font.widths.get(code, font.default) / 1000
                            at = _times(tm, state["ctm"])
                            boxes.append((n, round(at[5], 3), at[4],
                                          at[4] + width * size * scale * at[0],
                                          font.chars.get(code, "?")))
                            space = state["Tw"] if length == 1 and code == 32 else 0
                            tm = _times([1, 0, 0, 1, (width * size + state["Tc"] + space) * scale, 0],
                                        tm)
    return boxes


def own_text(element, texts, pages):
    """A structure element's own text: its marked content's characters,
    texts from marked_text, pages {page's objgen: its index}."""
    kids = element.get("/K")
    kids = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
    page = element.get("/Pg")
    text = ""
    for kid in kids:
        if isinstance(kid, pikepdf.Dictionary) and "/MCID" in kid:
            where = kid.get("/Pg") or page
            text += texts.get((pages[where.objgen], int(kid.MCID)), "")
        elif isinstance(kid, int) and page is not None:
            text += texts.get((pages[page.objgen], kid), "")
    return text


def element_texts(path, tag):
    """The text of each structure element tagged tag (as LaTeX names it,
    /codeline say), in reading order: its own marked content's characters."""
    texts = marked_text(path)
    found = []
    with pikepdf.open(path) as pdf:
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}

        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary) and "/S" in element:
                if element.S == tag:
                    found.append(own_text(element, texts, pages))
                if element.get("/K") is not None:
                    walk(element.K)

        walk(pdf.Root.StructTreeRoot.K)
    return found


def actual_texts(path, tag):
    """(ActualText, own text) for each structure element tagged tag, in
    reading order: what a screen reader says and copying gives in place
    of the element's marked content (None without an ActualText), and the
    characters of that content."""
    texts = marked_text(path)
    found = []
    with pikepdf.open(path) as pdf:
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}

        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary) and "/S" in element:
                if element.S == tag:
                    said = element.get("/ActualText")
                    found.append((None if said is None else str(said),
                                  own_text(element, texts, pages)))
                if element.get("/K") is not None:
                    walk(element.K)

        walk(pdf.Root.StructTreeRoot.K)
    return found


def span_parents(path, said):
    """For each Span whose ActualText is said, in reading order: its
    parent's tag, the parent's own text, and whether the Span holds a
    structure element of its own, which it shouldn't (its marked content
    is all it holds)."""
    texts = marked_text(path)
    found = []
    with pikepdf.open(path) as pdf:
        pages = {page.objgen: n for n, page in enumerate(pdf.pages)}

        def walk(element):
            if isinstance(element, pikepdf.Array):
                for kid in element:
                    walk(kid)
            elif isinstance(element, pikepdf.Dictionary) and "/S" in element:
                if element.S == "/Span" and str(element.get("/ActualText", "")) == said:
                    kids = element.get("/K")
                    kids = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
                    found.append((str(element.P.S), own_text(element.P, texts, pages),
                                  any(isinstance(kid, pikepdf.Dictionary) and "/S" in kid
                                      for kid in kids)))
                if element.get("/K") is not None:
                    walk(element.K)

        walk(pdf.Root.StructTreeRoot.K)
    return found


def code_lines(path):
    """Each line of code's text, as the PDF holds it."""
    return element_texts(path, "/codeline")


def diagonal_strokes(path):
    """[(page index, run, rise)] for each straight line a page's own content
    strokes that is neither level nor upright, as drawn, a path of one
    segment: a formula's term struck out, which pict2e draws as a line. A
    rule, an underline, and a box's sides are level or upright."""
    found = []
    with pikepdf.open(path) as pdf:
        for n, page in enumerate(pdf.pages):
            points = []
            for operands, op in pikepdf.parse_content_stream(page):
                op = str(op)
                if op == "m":
                    points = [[float(v) for v in operands]]
                elif op == "l" and points:
                    points.append([float(v) for v in operands])
                elif op in ("S", "s"):
                    if len(points) == 2:
                        run = points[1][0] - points[0][0]
                        rise = points[1][1] - points[0][1]
                        if abs(run) > 0.01 and abs(rise) > 0.01:
                            found.append((n, round(run, 2), round(rise, 2)))
                    points = []
                elif op in ("n", "f", "F", "f*", "B", "B*", "b", "b*", "re", "h", "c", "v",
                            "y"):
                    points = []
    return found


def curves(path):
    """{page index: how many curved segments its own content draws}, each
    of a path's Bezier curves (c, v, y): pict2e draws a circle as four, a
    quarter each, and an oval's corners so, where LaTeX's own picture mode
    draws them as glyphs of its lcircle10 font."""
    found = {}
    with pikepdf.open(path) as pdf:
        for n, page in enumerate(pdf.pages):
            count = sum(1 for _operands, op in pikepdf.parse_content_stream(page)
                        if str(op) in ("c", "v", "y"))
            if count:
                found[n] = count
    return found


def base_fonts(path):
    """The base font names a PDF's pages and their form XObjects draw with,
    a subset's tag taken off (ABCDEF+LINE10 is LINE10)."""
    names = set()

    # Each dictionary by its items: pikepdf 8, Ubuntu 24.04's, has no
    # Dictionary.values().
    def walk(resources, seen):
        if resources is None:
            return
        for _, font in (resources.get("/Font") or {}).items():
            name = str(font.get("/BaseFont", "")).lstrip("/")
            names.add(name.split("+", 1)[1] if re.match(r"[A-Z]{6}\+", name) else name)
        for _, xobject in (resources.get("/XObject") or {}).items():
            if xobject.get("/Subtype") == "/Form" and xobject.objgen not in seen:
                walk(xobject.get("/Resources"), seen | {xobject.objgen})

    with pikepdf.open(path) as pdf:
        for page in pdf.pages:
            walk(page.obj.get("/Resources"), frozenset())
    return names
