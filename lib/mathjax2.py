"""Formulas as MathJax 2 drew them, made math again.

A page saved from a browser after MathJax 2 ran holds each formula as its
HTML-CSS rendering: a span of class MathJax (in a div of class
MathJax_Display for a displayed formula) holding spans nested ten deep and
more, positioned by inline styles. Pandoc's HTML reader reads that as
nested spans of text, and the Markdown writer writes them as nested
bracketed spans its own reader then takes minutes or forever to read
back. An .mhtml save keeps no scripts, so the TeX is gone and the
rendering is all there is.

It's enough. Each span MathJax drew for a MathML element names it in its
class (mi, mo, mn, mfrac, msup, msqrt, ...), and carries an id,
MathJax-Span-N, numbered in the formula's own tree order. So the MathML
is rebuilt from the spans that name an element, each one's children
ordered by those numbers rather than by where the layout put them (a
superscript can come before its subscript on the page), and a token's
text taken as its content. The spans that only position things are
passed through.

Where the TeX survives -- a browser save of a live page, with MathJax's
<script type="math/tex"> right after its rendering -- Pandoc reads the
script, so the rendering is dropped instead of rebuilt, and the formula
isn't there twice.
"""
import re

import htmlparse as hp

TOKENS = ("mi", "mo", "mn", "mtext", "ms")
CONTAINERS = ("math", "mrow", "texatom", "mfrac", "msup", "msub", "msubsup",
              "msqrt", "mroot", "munder", "mover", "munderover", "mstyle",
              "mpadded", "mphantom", "menclose", "merror", "mtable", "mtr",
              "mtd", "mlabeledtr", "mspace")
KINDS = TOKENS + CONTAINERS
MATHML = "http://www.w3.org/1998/Math/MathML"


def _classes(element):
    return (element.get("class") or "").split()


def _kind(element):
    for name in _classes(element):
        if name in KINDS:
            return name
    return None


def _number(element):
    found = re.match(r"MathJax-Span-(\d+)$", element.get("id") or "")
    return int(found.group(1)) if found else float("inf")


def _math_children(element):
    """The nearest descendants that name a MathML element, in the
    formula's order: through the spans that only position things."""
    out = []
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if _kind(child):
            out.append(child)
        else:
            out.extend(_math_children(child))
    return sorted(out, key=_number)


# How many children each kind takes; a count that doesn't fit is an mrow.
ARITY = {"mfrac": 2, "mroot": 2, "msup": 2, "msub": 2, "munder": 2,
         "mover": 2, "msubsup": 3, "munderover": 3}


def _top(element, within):
    """The em offset of the nearest positioned span from element up to
    within: how high MathJax placed it."""
    parent_of = {c: p for p in within.iter() for c in p}
    node = element
    while node is not None and node is not within:
        found = re.search(r"(?:^|;)\s*top:\s*(-?[\d.]+)em", node.get("style") or "")
        if found:
            return float(found.group(1))
        node = parent_of.get(node)
    return None


def _build(element, maker):
    kind = _kind(element)
    if kind in TOKENS:
        node = maker(kind, {})
        node.text = hp.text_of(element).replace("\u200b", "").strip()
        return node, 1
    name = "mrow" if kind == "texatom" else kind
    kids = [] if kind == "mspace" else _math_children(element)
    # MathJax 2 draws msup and msub with its msubsup, and munder and mover
    # with its munderover, so one script means one of the two-child kinds:
    # a superscript (over) when the layout raised it above its base, which
    # is also the likelier when the layout doesn't say.
    if name in ("msubsup", "munderover") and len(kids) == 2:
        base, script = _top(kids[0], element), _top(kids[1], element)
        raised = base is None or script is None or script < base
        name = {"msubsup": ("msup", "msub"),
                "munderover": ("mover", "munder")}[name][0 if raised else 1]
    if name in ARITY and len(kids) != ARITY[name]:
        name = "mrow"
    node = maker(name, {})
    tokens = 0
    # MathJax 2 lays a table out by columns and draws no span for a row,
    # so its cells arrive without their mtr. In the formula's order they're
    # row by row, and a row's cells sit at one height: a new height starts
    # a new row. Without heights, one row, which is at least MathML.
    if name == "mtable" and kids and all(_kind(k) == "mtd" for k in kids):
        rows = []
        for child in kids:
            top = _top(child, element)
            if rows and rows[-1][0] == top:
                rows[-1][1].append(child)
            else:
                rows.append((top, [child]))
        if any(top is None for top, _ in rows):
            rows = [(None, kids)]
        for _, cells in rows:
            row = maker("mtr", {})
            for child in cells:
                built, count = _build(child, maker)
                row.append(built)
                tokens += count
            node.append(row)
        return node, tokens
    for child in kids:
        built, count = _build(child, maker)
        node.append(built)
        tokens += count
    return node, tokens


def rebuilt(markup):
    """(markup, rebuilt, dropped): the page with each MathJax 2 rendering
    turned back into MathML, or dropped where its TeX follows it. A page
    that doesn't mention MathJax is returned as it was, untouched."""
    if "MathJax" not in markup:
        return markup, 0, 0
    root = hp.parse(markup)
    parent_of = hp.parents(root)

    def inside_display(element):
        parent = parent_of.get(element)
        while parent is not None:
            if "MathJax_Display" in _classes(parent):
                return True
            parent = parent_of.get(parent)
        return False
    renderings = [e for e in root.iter() if isinstance(e.tag, str) and (
        "MathJax_Display" in _classes(e)
        or ("MathJax" in _classes(e) and not inside_display(e)))]
    made = dropped = 0
    for rendering in renderings:
        parent = parent_of.get(rendering)
        if parent is None:
            continue
        siblings = [s for s in parent if isinstance(s.tag, str)]
        at = siblings.index(rendering)
        following = siblings[at + 1] if at + 1 < len(siblings) else None
        if following is not None and hp.local(following.tag) == "script" \
                and (following.get("type") or "").startswith("math/"):
            hp.drop(rendering, parent_of)
            dropped += 1
            continue
        top = next((e for e in rendering.iter() if isinstance(e.tag, str)
                    and "math" in _classes(e)), None)
        if top is None:
            continue
        maker = rendering.makeelement
        attrs = {"xmlns": MATHML}
        if "MathJax_Display" in _classes(rendering):
            attrs["display"] = "block"
        formula = maker("math", attrs)
        tokens = 0
        for child in _math_children(top):
            built, count = _build(child, maker)
            formula.append(built)
            tokens += count
        if not tokens:
            continue
        index = list(parent).index(rendering)
        formula.tail = rendering.tail
        parent.remove(rendering)
        parent.insert(index, formula)
        made += 1
    if not made and not dropped:
        return markup, 0, 0
    doctype = "<!DOCTYPE html>\n" if markup.lstrip()[:9].lower() == "<!doctype" else ""
    return doctype + hp.serialize(root), made, dropped
