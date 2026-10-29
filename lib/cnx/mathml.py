"""
cnx.mathml -- a module's MathML as Pandoc's HTML reader takes it.

Pandoc reads <math> written in HTML's way, with no prefix, and converts
it to TeX through texmath, whose MathML reader knows presentation
elements only (Readers/MathML.hs, expr'): anything else ends the
formula, and Pandoc keeps the formula's text and nothing else. CNXML
writes MathML with an m: prefix, which the HTML reader doesn't know as
math at all. So each formula is copied here into MathML's namespace
with no prefix. Content MathML (<apply>, <ci>), which some of the
Connexions archive's books are written in and one formula of OpenStax's
(Introductory Statistics' "<" as <reln><lt/></reln>), is made
presentation MathML where it's simple: names and numbers, relations,
arithmetic, powers and roots, a function applied. What's left, an
integral or a set, stays as it is, and is reported: Pandoc would keep
its text and lose the formula. Content MathML in an annotation is the
formula's other form, and harmless.

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

from copy import deepcopy

from lxml import etree

MATHML = "http://www.w3.org/1998/Math/MathML"

# Content MathML's elements, the ones the archive's books use and their
# relatives: a formula holding any of these can't be read by texmath.
CONTENT = {
    "apply", "ci", "cn", "csymbol", "bvar", "lowlimit", "uplimit",
    "degree", "logbase", "condition", "domainofapplication", "piecewise",
    "piece", "otherwise", "plus", "minus", "times", "divide", "power",
    "root", "eq", "neq", "lt", "gt", "leq", "geq", "approx", "equivalent",
    "and", "or", "not", "xor", "implies", "abs", "exp", "ln", "log",
    "sin", "cos", "tan", "sec", "csc", "cot", "arcsin", "arccos",
    "arctan", "sinh", "cosh", "tanh", "int", "sum", "product", "diff",
    "partialdiff", "limit", "tendsto", "lambda", "set", "list",
    "interval", "factorial", "max", "min", "gcd", "lcm", "floor",
    "ceiling", "rem", "quotient", "conjugate", "arg", "real",
    "imaginary", "mean", "sdev", "variance", "median", "mode", "union",
    "intersect", "in", "notin", "subset", "prsubset", "setdiff",
    "card", "vector", "matrix", "matrixrow", "determinant", "transpose",
    "selector", "compose", "inverse", "ident", "forall", "exists",
    "infinity", "pi", "exponentiale", "imaginaryi", "notanumber",
    "true", "false", "emptyset", "eulergamma", "naturalnumbers",
    "integers", "reals", "rationals", "complexes", "primes", "declare",
}


def copy(element):
    """A copy of a MathML element tree in MathML's namespace, written
    with no prefix. Text in another namespace inside it (rare) is kept as
    text."""
    root = etree.Element(f"{{{MATHML}}}{etree.QName(element).localname}",
                         nsmap={None: MATHML})
    _attributes(element, root)
    root.text = element.text
    for child in element:
        _copy_into(child, root)
    return root


def _attributes(src, dst):
    for key, value in src.attrib.items():
        if key.startswith("{"):
            continue
        dst.set(key, value)


# What texmath writes as TeX its own reader can't read back, so that
# Pandoc shows the whole formula as TeX, made what it means: an operator
# or a name holding a quotation mark (an author's “5 − 3” typed inside
# the formula, or a sentence's closing ."), which texmath writes with a
# bare '"', is text; a letter set as bold italic text (a table's heading
# "x"), which it writes \textit{\textbf{x}}, is the variable it is.
QUOTES = {'"', "“", "”"}
NESTED_TEXT_STYLES = {"bold-italic", "bold-sans-serif"}
# And an over- or underbrace written with the brace for vertical CJK text
# (︷ ︸, as MathType writes one) is the brace mathematics has (⏞ ⏟),
# which texmath reads as \overbrace and \underbrace and math fonts have.
BRACES = {"︷": "⏞", "︸": "⏟"}


def _copy_into(src, parent):
    if not isinstance(src.tag, str):
        if parent is not None and src.tail:
            _append_text(parent, src.tail)
        return
    if etree.QName(src).namespace != MATHML:
        _append_text(parent, "".join(src.itertext()) + (src.tail or ""))
        return
    name = etree.QName(src).localname
    text = (src.text or "").strip()
    if name in ("mi", "mn", "mo") and not len(src) \
            and any(q in text for q in QUOTES):
        name = "mtext"
    elif name == "mtext" and not len(src) and len(text) == 1 \
            and text.isalpha() \
            and src.get("mathvariant") in NESTED_TEXT_STYLES:
        name = "mi"
    el = etree.SubElement(parent, f"{{{MATHML}}}{name}")
    _attributes(src, el)
    el.text = src.text
    if name == "mo" and text in BRACES:
        el.text = src.text.replace(text, BRACES[text])
    for child in src:
        _copy_into(child, el)
    el.tail = src.tail


def _append_text(parent, text):
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def is_content(math):
    """Whether the formula holds content MathML outside an annotation."""
    return bool(_content(math))


def _content(math):
    return [el for el in math.iter(f"{{{MATHML}}}*")
            if etree.QName(el).localname in CONTENT
            and not any(etree.QName(a).localname in ("annotation-xml",
                                                     "annotation")
                        for a in el.iterancestors())]


# Content to presentation: what a converted formula shows for each
# operator, as David Carlisle's ctop.xsl shows it.
INFIX = {"eq": "=", "neq": "\u2260", "lt": "<", "gt": ">", "leq": "\u2264",
         "geq": "\u2265", "approx": "\u2248", "equivalent": "\u2261",
         "plus": "+", "times": "\u00d7", "and": "\u2227", "or": "\u2228",
         "in": "\u2208", "notin": "\u2209", "subset": "\u2286",
         "prsubset": "\u2282", "union": "\u222a", "intersect": "\u2229",
         "minus": "\u2212", "implies": "\u21d2"}
FUNCTIONS = {"sin", "cos", "tan", "sec", "csc", "cot", "arcsin", "arccos",
             "arctan", "sinh", "cosh", "tanh", "ln", "log", "exp"}
CONSTANTS = {"pi": ("mi", "\u03c0"), "infinity": ("mi", "\u221e"),
             "exponentiale": ("mi", "e"), "imaginaryi": ("mi", "i"),
             "emptyset": ("mi", "\u2205"), "true": ("mi", "true"),
             "false": ("mi", "false")}
# Lower binds looser: an operand whose operator binds looser than its
# parent's is put in parentheses.
PRECEDENCE = {"or": 1, "and": 2, "eq": 3, "neq": 3, "lt": 3, "gt": 3,
              "leq": 3, "geq": 3, "approx": 3, "equivalent": 3, "in": 3,
              "notin": 3, "subset": 3, "prsubset": 3, "implies": 0,
              "union": 4, "intersect": 4, "plus": 5, "minus": 5,
              "times": 6, "divide": 7, "power": 8}


def _m(name, text=None, *children):
    el = etree.Element(f"{{{MATHML}}}{name}")
    el.text = text
    for child in children:
        el.append(child)
    return el


def _local(el):
    return etree.QName(el).localname


class _Unconverted(Exception):
    pass


def _operator(apply):
    kids = [c for c in apply if isinstance(c.tag, str)]
    if not kids:
        raise _Unconverted("an empty apply")
    return kids[0], kids[1:]


def _fenced(el):
    return _m("mrow", None, _m("mo", "("), el, _m("mo", ")"))


def _operand(arg, parent_op, place=0):
    """An operand, in parentheses when its operator binds looser than
    the parent's (or as tightly, on a non-commutative operator's
    right)."""
    out = _convert(arg)
    if _local(arg) in ("apply", "reln"):
        head, args = _operator(arg)
        mine = PRECEDENCE.get(_local(head))
        theirs = PRECEDENCE.get(parent_op)
        if mine is not None and theirs is not None and (
                mine < theirs or (mine == theirs and place > 0
                                  and parent_op in ("minus", "divide"))):
            return _fenced(out)
        if parent_op == "power" and place == 0 and mine is not None:
            return _fenced(out)
    return out


def _convert(el):
    """el, content MathML, as presentation MathML; _Unconverted if it
    isn't one of the simple forms."""
    name = _local(el)
    if name in ("annotation-xml", "annotation"):
        return deepcopy(el)
    if name not in CONTENT and name not in ("reln",):
        # Presentation MathML: its children may still be content.
        out = _m(name, el.text)
        for key, value in el.attrib.items():
            out.set(key, value)
        for child in el:
            if isinstance(child.tag, str):
                converted = _convert(child)
                converted.tail = child.tail
                out.append(converted)
        return out
    if name == "ci" or name == "csymbol":
        if len(el):
            raise _Unconverted(f"a <{name}> with markup in it")
        return _m("mi", (el.text or "").strip())
    if name == "cn":
        if len(el):
            raise _Unconverted("a <cn> with parts")
        return _m("mn", (el.text or "").strip())
    if name in CONSTANTS:
        tag, text = CONSTANTS[name]
        return _m(tag, text)
    if name in INFIX:
        return _m("mo", INFIX[name])
    if name in ("apply", "reln"):
        head, args = _operator(el)
        op = _local(head)
        if op in INFIX and not args:
            return _m("mo", INFIX[op])
        if op == "minus" and len(args) == 1:
            return _m("mrow", None, _m("mo", INFIX["minus"]),
                      _operand(args[0], "times"))
        if op in INFIX:
            row = _m("mrow")
            for i, arg in enumerate(args):
                if i:
                    row.append(_m("mo", INFIX[op]))
                row.append(_operand(arg, op, i))
            return row
        if op == "divide" and len(args) == 2:
            return _m("mfrac", None, _convert(args[0]), _convert(args[1]))
        if op == "power" and len(args) == 2:
            return _m("msup", None, _operand(args[0], "power", 0),
                      _convert(args[1]))
        if op == "root":
            degree = [a for a in args if _local(a) == "degree"]
            rest = [a for a in args if _local(a) != "degree"]
            if len(rest) != 1:
                raise _Unconverted("a root of more than one thing")
            if degree:
                inner = [c for c in degree[0] if isinstance(c.tag, str)]
                if len(inner) != 1:
                    raise _Unconverted("a root's degree")
                return _m("mroot", None, _convert(rest[0]),
                          _convert(inner[0]))
            return _m("msqrt", None, _convert(rest[0]))
        if op == "abs" and len(args) == 1:
            return _m("mrow", None, _m("mo", "|"), _convert(args[0]),
                      _m("mo", "|"))
        if op == "factorial" and len(args) == 1:
            return _m("mrow", None, _operand(args[0], "power", 0),
                      _m("mo", "!"))
        if op == "not" and len(args) == 1:
            return _m("mrow", None, _m("mo", "\u00ac"),
                      _operand(args[0], "times"))
        if (op in FUNCTIONS or op == "ci") and args:
            if op == "ci" and any(isinstance(c.tag, str) for c in head):
                # A function's name that is markup, P with a subscript s
                # applied to k: its text alone is nothing, and the name
                # would be lost without a word ("(k)").
                raise _Unconverted("a <ci> with markup in it")
            name_el = _m("mi", op if op != "ci" else (head.text or "").strip())
            if op == "log":
                base = [a for a in args if _local(a) == "logbase"]
                args = [a for a in args if _local(a) != "logbase"]
                if base:
                    inner = [c for c in base[0] if isinstance(c.tag, str)]
                    if len(inner) != 1:
                        raise _Unconverted("a logarithm's base")
                    name_el = _m("msub", None, name_el, _convert(inner[0]))
            row = _m("mrow", None, name_el, _m("mo", "\u2061"),
                     _m("mo", "("))
            for i, arg in enumerate(args):
                if i:
                    row.append(_m("mo", ","))
                row.append(_convert(arg))
            row.append(_m("mo", ")"))
            return row
        raise _Unconverted(f"<{op}>")
    raise _Unconverted(f"<{name}>")


# A forced line break, MathML 3's <mspace linebreak="newline"/>, which
# OpenStax's books use to set a formula's forms or steps on lines of their
# own: Principles of Marketing's "Value = Benefits/Price" over "(V = B/P)",
# Algebra 1's steps of a solution in a paragraph, a system of equations
# under one brace. texmath reads an mspace as its width and drops the
# break, and MathML Core, which browsers implement, doesn't break there
# either, so the lines ran together on every target. Where a row of a
# formula holds such breaks, its lines are made the rows of a table of
# one column, which texmath reads as an array and every target sets as
# lines: centered in an equation, as OpenStax shows one, and set at the
# left elsewhere. A line the source aligns at a point of its own
# (indentalign="id") is set at the left too.
ROW_LIKE = {"math", "mrow", "mstyle", "mtd", "mpadded", "mphantom",
            "menclose", "msqrt", "merror"}


def _breaks_line(el):
    return (isinstance(el.tag, str) and etree.QName(el).localname == "mspace"
            and el.get("linebreak") == "newline")


def lines_as_rows(math, center=False):
    """A formula's forced line breaks made the rows of a one-column
    mtable, in place. Returns how many rows of the formula were so
    divided."""
    holders = [el for el in math.iter(f"{{{MATHML}}}*")
               if etree.QName(el).localname in ROW_LIKE
               and any(_breaks_line(c) for c in el)]
    for holder in holders:
        lines, line = [], []
        for child in list(holder):
            holder.remove(child)
            if _breaks_line(child):
                lines.append(line)
                line = []
            elif isinstance(child.tag, str):
                child.tail = None
                line.append(child)
        lines.append(line)
        lines = [line for line in lines if line]
        if len(lines) < 2:
            for child in (lines[0] if lines else []):
                holder.append(child)
            continue
        table = etree.SubElement(holder, f"{{{MATHML}}}mtable",
                                 columnalign="center" if center else "left")
        for line in lines:
            cell = etree.SubElement(etree.SubElement(
                table, f"{{{MATHML}}}mtr"), f"{{{MATHML}}}mtd")
            if len(line) > 1:
                cell = etree.SubElement(cell, f"{{{MATHML}}}mrow")
            for child in line:
                cell.append(child)
    return len(holders)


# A script of the wrong number of parts. An msup or msub is a base and
# its script, and texmath rejects one of any other number of children
# (Readers/MathML.hs, checkArgs2), so Pandoc keeps the whole formula as
# its text, in a span of class math. Fizyka dla szkół wyższych has 20
# such superscripts, the only scripts of the wrong number in OpenStax's
# 49 public repositories: 12 of three parts, a degree sign before C⁻¹
# (10), a coefficient before t² ("2,00", t, 2), and 10⁷ with a space
# after it; and 8 of one, a letter alone (N, G, a prime), whose script,
# if it had one, the source lost (its unit of angular momentum is
# kg⋅m/s, the English edition's kg·m²/s). A script sits on the symbol
# just before it, so of three parts or more, the last is the script and
# the one before it the base; what's before those is set before them,
# and a space at the end after them, in an mrow where the script stood
# in place of an argument (a fraction's numerator). One part is its base
# alone.
SCRIPTS = {"msup", "msub"}


def repair_scripts(math):
    """The formula's msup and msub elements of other than two children
    made a base and its script, in place. Returns each one's name and how
    many children it had."""
    repaired = []
    for el in [el for el in math.iter(f"{{{MATHML}}}*")
               if etree.QName(el).localname in SCRIPTS]:
        parts = [child for child in el if isinstance(child.tag, str)]
        if len(parts) in (0, 2):
            continue
        repaired.append((etree.QName(el).localname, len(parts)))
        if len(parts) == 1:
            el.getparent().replace(el, parts[0])
            continue
        after = []
        while len(parts) > 2 and etree.QName(parts[-1]).localname == "mspace":
            after.insert(0, parts.pop())
        if etree.QName(el.getparent()).localname not in ROW_LIKE:
            row = etree.Element(f"{{{MATHML}}}mrow")
            el.addprevious(row)
            row.append(el)
        for part in parts[:-2]:
            el.addprevious(part)
        for part in reversed(after):
            el.addnext(part)
    return repaired


def to_presentation(math):
    """The formula's content MathML made presentation MathML, in place,
    where it's one of the simple forms. Returns what couldn't be made
    so, as a short description, or None."""
    if not _content(math):
        return None
    try:
        converted = _convert(math)
    except _Unconverted as why:
        return str(why)
    for child in list(math):
        math.remove(child)
    math.text = converted.text
    for child in list(converted):
        math.append(child)
    return None
