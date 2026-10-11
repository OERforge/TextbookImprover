"""
pdftext.py -- the text a tagged PDF holds for its structure elements, as
a screen reader gets it: the characters the PDF has, read with pdfminer.six
(so a font's own encoding is followed), and no space inferred from where
words sit on the page, as a text extractor infers one. For the suites that
check a PDF; AVAILABLE is false without pikepdf and pdfminer.six, and they
skip such a check, saying so.

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
    from pdfminer.pdfdevice import PDFDevice
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    AVAILABLE = True
except ImportError:
    PDFDevice = object
    AVAILABLE = False


class _Text(PDFDevice):
    """Each marked-content sequence's characters, by page and MCID."""

    def __init__(self, rsrc):
        super().__init__(rsrc)
        self.stack, self.page, self.texts = [], 0, {}

    def begin_tag(self, tag, props=None):
        self.stack.append(props.get("MCID") if isinstance(props, dict) else None)

    def end_tag(self):
        if self.stack:
            self.stack.pop()

    def render_string(self, textstate, seq, ncs, graphicstate):
        key = (self.page, next((m for m in reversed(self.stack) if m is not None), None))
        for item in seq:
            if isinstance(item, (bytes, str)):
                for cid in textstate.font.decode(item):
                    try:
                        char = textstate.font.to_unichr(cid)
                    except Exception:  # a glyph with no character
                        char = "?"
                    self.texts[key] = self.texts.get(key, "") + char


def marked_text(path):
    """{(page index, MCID): the characters in that sequence}."""
    with open(path, "rb") as fh:
        rsrc = PDFResourceManager()
        device = _Text(rsrc)
        interpreter = PDFPageInterpreter(rsrc, device)
        for n, page in enumerate(PDFPage.create_pages(PDFDocument(PDFParser(fh)))):
            device.page, device.stack = n, []
            interpreter.process_page(page)
    return device.texts


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


def code_lines(path):
    """Each line of code's text, as the PDF holds it."""
    return element_texts(path, "/codeline")
