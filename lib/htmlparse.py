"""
htmlparse -- one way to parse and serialize HTML, whichever parser is here.

html5lib is the reference: it implements the HTML standard's parsing
algorithm, so it builds the tree a browser builds. lxml is the fallback,
faster and not faithful: libxml2's HTML parser doesn't know <wbr> is a
void element and nests what follows inside it, which on one textbook's
80 saved pages changed the tree of 42 (measured). When lxml is what we
have, the run says so once.

The tree is ElementTree-shaped either way: iter(), get(), set(), attrib,
text, tail. Nothing here relies on lxml's getparent(); parents() builds
the map ElementTree needs.

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

import sys

BACKEND = None
_WARNED = False

try:
    import html5lib
    from html5lib import serializer as _serializer
    BACKEND = "html5lib"
except ImportError:                               # pragma: no cover
    try:
        import lxml.html
        BACKEND = "lxml"
    except ImportError:
        BACKEND = None


def require(backend=None):
    """Settle the backend, warning once when it isn't html5lib. A name
    forces one (for the tests that compare them)."""
    global BACKEND, _WARNED
    if backend:
        BACKEND = backend
    if BACKEND is None:
        sys.exit("Reading saved web pages needs an HTML parser: install "
                 "html5lib (python3-html5lib on Debian and Ubuntu, or pip "
                 "install html5lib), or lxml.")
    if BACKEND == "lxml" and not _WARNED:
        _WARNED = True
        print("NOTE: html5lib isn't installed, so pages are parsed with "
              "lxml, which builds a different tree from some markup than a "
              "browser does. Install html5lib (python3-html5lib) for the "
              "reference parse.", file=sys.stderr)
    return BACKEND


def parse(text):
    """The document's root element (<html>)."""
    require()
    if BACKEND == "html5lib":
        return html5lib.parse(text, treebuilder="etree",
                              namespaceHTMLElements=False)
    import lxml.html
    return lxml.html.document_fromstring(text)


def local(tag):
    """An element's name without its namespace; '' for a comment."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def serialize(element, inner=False):
    """The element as HTML; with inner, only what it holds."""
    if inner:
        return _escape_text(element.text or "") + "".join(
            serialize(child) for child in element)
    if BACKEND == "html5lib":
        walker = html5lib.getTreeWalker("etree")
        tail, element.tail = element.tail, None
        try:
            out = _serializer.HTMLSerializer(
                omit_optional_tags=False, quote_attr_values="always",
                resolve_entities=False, alphabetical_attributes=False,
                use_trailing_solidus=False).render(walker(element))
        finally:
            element.tail = tail
        return out + (_escape_text(tail) if tail else "")
    import lxml.html
    return lxml.html.tostring(element, encoding="unicode", method="html",
                              with_tail=True)


def _escape_text(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parents(root):
    return {child: parent for parent in root.iter() for child in parent}


def drop(element, parent_of):
    """Remove an element, keeping the text that followed it."""
    parent = parent_of.get(element)
    if parent is None:
        return
    tail = element.tail
    index = list(parent).index(element)
    if tail:
        if index > 0:
            before = parent[index - 1]
            before.tail = (before.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def text_of(element):
    return " ".join("".join(element.itertext()).split())


def matches(element, selector):
    """A selector of one simple part: tag, .class, #id, [attr] or
    [attr=value], combined (nav.toc, a[name]). Enough for profiles."""
    import re
    if not isinstance(element.tag, str):
        return False
    parts = re.findall(r"^[\w-]+|\.[\w-]+|#[\w-]+|\[[^\]]+\]", selector)
    if "".join(parts) != selector:
        raise ValueError(f"unsupported selector {selector!r}")
    classes = (element.get("class") or "").split()
    for part in parts:
        if part[0] == ".":
            if part[1:] not in classes:
                return False
        elif part[0] == "#":
            if element.get("id") != part[1:]:
                return False
        elif part[0] == "[":
            name, _, value = part[1:-1].partition("=")
            got = element.get(name.strip())
            if got is None or (value and got != value.strip("\"'")):
                return False
        elif local(element.tag) != part.lower():
            return False
    return True


def select(root, selector):
    return [e for e in root.iter() if matches(e, selector)]
