"""
mhchem -- mhchem's \\ce{...} written as the plain TeX it stands for.

A chemistry book written for MathJax writes its formulas with mhchem
(\\ce{Fe(CN)6^{3-}}, \\ce{2 e-}, \\ce{<=>}), which MathJax's mhchem
extension reads, as LaTeX's mhchem package does. texmath, which writes a
formula's MathML for every target but the PDF, reads neither: a formula
holding a \\ce is left as TeX on the page (measured with Pandoc 3.12.1:
"unexpected control sequence \\ce"). So a \\ce is rewritten as the TeX
mhchem itself would produce, in the commands both texmath and LaTeX know:
a formula's letters upright, a count after them a subscript, a charge a
superscript, a state in parentheses after a thin space, a bond a dash,
an arrow an arrow.

What is read is the part of mhchem's language a formula and a simple
equation need, as mhchem 4 reads it (checked against mhchemparser 4.2.1,
the parser MathJax uses, form by form):

  - a run of letters (Fe, SiO, KE) upright; lowercase alone too (e);
  - digits after a run, ) or ] a count, subscript (CH4, Fe(CN)6);
  - a + or - ending a word a charge (Ag+, e-, CH5+); ^ with braces or
    with digits and signs a superscript (Fe^{3+}, SO4^2-, M^{+•}); _
    likewise a subscript (C_nH_{2n+2});
  - ( ) holding lowercase letters only a state, (s) or (aq); any other
    group read the same way inside; [ ] an expression, spaces and all;
  - - (or an en dash), =, and # between parts a single, double, and
    triple bond;
  - a number, a fraction (1/2), or a decimal before a formula its
    coefficient, apart or not (2 e-, 1/2H2O);
  - apart: + a plus, -> <- <-> <=> arrows, v and ^ a precipitate's and
    a gas's arrow, * and . an adduct's dot.

Anything else (an arrow with a label, an isotope's mass before its
symbol, a charge in roman numerals) is not guessed at: ce_tex returns
None and the caller leaves the \\ce as it was, and says so.

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

# mhchem's arrows are its own long ones (\longrightleftharpoons); these
# are the nearest every target knows.
ARROWS = {"->": r"\longrightarrow", "<-": r"\longleftarrow",
          "<->": r"\longleftrightarrow", "<=>": r"\rightleftharpoons"}
APART = {"+": "+", "v": r"\downarrow", "^": r"\uparrow",
         "*": r"\cdot", ".": r"\cdot"}
BONDS = {"-": "{-}", "\u2013": "{-}", "=": "{=}", "#": r"{\equiv}"}
NUMBER = re.compile(r"(\d+)/(\d+)|\d+(?:\.\d+)?|\.\d+")
CE = re.compile(r"\\ce(?![A-Za-z])\s*\{")


class Unread(ValueError):
    """Something in a \\ce this module doesn't read."""


def _close(text, at, opening, closing):
    """The index just past the bracket matching the one at text[at]."""
    depth = 0
    for i in range(at, len(text)):
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i + 1
    raise Unread("an unclosed " + opening)


def _words(text):
    """The argument split at spaces outside brackets."""
    words, start, depth = [], None, 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch.isspace() and depth == 0:
            if start is not None:
                words.append(text[start:i])
                start = None
        elif start is None:
            start = i
    if start is not None:
        words.append(text[start:])
    if depth:
        raise Unread("unbalanced brackets")
    return words


def _number(text):
    m = NUMBER.fullmatch(text)
    if not m:
        return None
    return r"\tfrac{%s}{%s}" % (m.group(1), m.group(2)) if m.group(1) else text


def _script(text, at, upright):
    """(TeX, end) for what follows a ^ or _ at text[at]: a braced group,
    digits and signs, or one letter. In a superscript, a charge, letters
    are upright (Fe^{III}); in a subscript, a count, a variable (C_n)."""
    if at < len(text) and text[at] == "{":
        end = _close(text, at, "{", "}")
        inner = text[at + 1:end - 1]
    else:
        m = re.compile(r"[0-9]+[+\-\u2022.]*|[+\-\u2022.]+|[A-Za-z]").match(text, at)
        if not m:
            raise Unread("a ^ or _ with nothing after it")
        end, inner = m.end(), m.group(0)
    if re.search(r"[^A-Za-z0-9+\-\u2022. ]", inner):
        raise Unread("a superscript or subscript holding " + inner)
    inner = " ".join(inner.split()).replace("\u2022", r"\bullet ").strip()
    if upright:
        inner = re.sub(r"(?<!\\)\b([A-Za-z]+)", r"\\mathrm{\1}", inner)
    return inner, end


def _formula(text):
    """A formula with no spaces in it, as TeX."""
    out, i = [], 0
    m = re.match(r"(\d+/\d+|\d+(?:\.\d+)?)(?=[A-Za-z(\[])", text)
    if m:                                     # 1/2H2O, 2H2
        out.append(_number(m.group(1)) + r"\,")
        i = m.end()
    after_part = False          # whether a count or a charge may follow
    while i < len(text):
        ch = text[i]
        if ch.isalpha() and ch.isascii():
            run = re.compile(r"[A-Za-z]+").match(text, i)
            out.append(r"\mathrm{%s}" % run.group(0))
            i, after_part = run.end(), True
        elif ch.isdigit() and after_part:
            run = re.compile(r"\d+").match(text, i)
            out.append("_{%s}" % run.group(0))
            i = run.end()
        elif ch in "^_" and after_part:
            inner, i = _script(text, i + 1, ch == "^")
            out.append("%s{%s}" % (ch, inner))
        elif ch in "+-" and after_part and i == len(text) - 1:
            out.append("^{%s}" % ch)             # Ag+, e-: a charge
            i += 1
        elif ch in BONDS and i + 1 < len(text) and (
                text[i + 1].isalpha() or text[i + 1] in "(["):
            out.append(BONDS[ch])
            i, after_part = i + 1, False
        elif ch == "(":
            end = _close(text, i, "(", ")")
            inner = text[i + 1:end - 1]
            if re.fullmatch(r"[a-z]+", inner):   # (s), (aq): a state
                out.append(r"\,(\mathrm{%s})" % inner)
                after_part = False
            else:
                out.append("(" + _formula(inner) + ")")
                after_part = True
            i = end
        elif ch == "[":
            end = _close(text, i, "[", "]")
            out.append("[" + _expression(text[i + 1:end - 1]) + "]")
            i, after_part = end, True
        else:
            raise Unread(f"{ch!r} in {text!r}")
    return "".join(out)


def _expression(text):
    parts = []
    for word in _words(text):
        if word in ARROWS:
            parts.append(ARROWS[word])
        elif word in APART:
            parts.append(APART[word])
        elif _number(word) is not None:
            parts.append(_number(word) + r"\,")
        else:
            parts.append(_formula(word))
    out = ""
    for part in parts:
        out += part if out.endswith(r"\,") or not out else " " + part
    return out


def ce_tex(argument):
    """The TeX \\ce{argument} stands for, or None when something in it
    isn't read here. A formula is one group, as mhchem makes it; an arrow
    stands alone, so it still spaces as a relation."""
    try:
        tex = _expression(argument)
    except Unread:
        return None
    if not tex:
        return None
    return tex if tex in ARROWS.values() or tex in APART.values() \
        else "{" + tex + "}"


def rewrite(tex):
    """(TeX with each \\ce rewritten, [arguments left as they were])."""
    out, unread, at = [], [], 0
    for m in CE.finditer(tex):
        if m.start() < at:
            continue
        try:
            end = _close(tex, m.end() - 1, "{", "}")
        except Unread:
            continue
        argument = tex[m.end():end - 1]
        new = ce_tex(argument)
        out.append(tex[at:m.start()])
        if new is None:
            unread.append(argument)
            out.append(tex[m.start():end])
        else:
            out.append(new)
        at = end
    out.append(tex[at:])
    return "".join(out), unread
