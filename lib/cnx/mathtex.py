"""
cnx.mathtex -- a formula's TeX as Pandoc writes it when it reads a page:
texmath's MathML reader (Readers/MathML.hs), which makes a tree of the
formula, and its TeX writer (Writers/TeX.hs, TeX.hs), ported for the
presentation MathML OpenStax's books are written in. It's here so that a
table's cells read as lib/tablecensus.py reads them from Pandoc's AST,
where a formula is its TeX (cnx.steptables). The tables of characters and
operators are texmath's own (Unicode/ToTeX.hs, MMLDict.hs), for the
characters and operators OpenStax's books use; any other character is
taken as texmath takes a character it has no record of. A formula
texmath can't read is its text alone, as Pandoc keeps it then.

Measured against Pandoc 3.12.1 (texmath 0.13.3.1), the TeX of every
formula in seven books, 115,122 of them, is Pandoc's: Prealgebra 2e,
Elementary Algebra 2e, Intermediate Algebra 2e, College Algebra 2e,
Calculus Volume 1, University Physics Volume 2, and Chemistry 2e. An
earlier texmath writes a few accents and lengths otherwise.

Copyright 2026 Robert Szarka. Ported from texmath 0.13.3.1
(https://github.com/jgm/texmath): Readers/MathML.hs and MathML/MMLDict.hs,
Writers/TeX.hs, TeX.hs, Shared.hs, and Unicode/ToTeX.hs, Copyright (C)
2014 Matthew Pickering, under the GNU General Public License, version 2
or later; its character table is derived from Guenter Milde's list of
Unicode to LaTeX mappings.

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

from fractions import Fraction
import re
import unicodedata

from lxml import etree

# Characters whose TeX isn't the character itself, or that texmath spaces
# or fences: (category, TeX), from texmath's Unicode/ToTeX.hs records, the
# command it writes with amsmath and amssymb. Any other character is its
# own TeX, of the category Ord.
SYMBOLS = {
    "!": ("Pun", "!"), "#": ("Ord", "\\#"), "$": ("Ord", "\\$"),
    "%": ("Ord", "\\%"), "&": ("Ord", "\\&"), "(": ("Open", "("),
    ")": ("Close", ")"), "+": ("Bin", "+"), ",": ("Pun", ","),
    "-": ("Bin", "-"), ":": ("Pun", ":"), ";": ("Pun", ";"),
    "<": ("Rel", "<"), "=": ("Rel", "="), ">": ("Rel", ">"),
    "[": ("Open", "\\lbrack"), "\\": ("Ord", "\\backslash"),
    "]": ("Close", "\\rbrack"), "^": ("Ord", "\\hat{}"), "_": ("Ord", "\\_"),
    "{": ("Open", "\\{"), "|": ("Fence", "|"), "}": ("Close", "\\}"),
    "~": ("Ord", "\\sim"), "\u00a0": ("Ord", "~"),
    "\u00b0": ("Ord", "{^\\circ}"), "\u00b1": ("Bin", "\\pm"),
    "\u00b7": ("Bin", "\\cdot"), "\u00d7": ("Bin", "\\times"),
    "\u00f7": ("Bin", "\\div"), "\u0302": ("Accent", "\\hat"),
    "\u0338": ("Accent", "\\not"), "\u0393": ("Alpha", "\\Gamma"),
    "\u0394": ("Alpha", "\\Delta"), "\u0398": ("Alpha", "\\Theta"),
    "\u039b": ("Alpha", "\\Lambda"), "\u039e": ("Alpha", "\\Xi"),
    "\u03a0": ("Alpha", "\\Pi"), "\u03a3": ("Alpha", "\\Sigma"),
    "\u03a5": ("Alpha", "\\Upsilon"), "\u03a6": ("Alpha", "\\Phi"),
    "\u03a8": ("Alpha", "\\Psi"), "\u03a9": ("Alpha", "\\Omega"),
    "\u03b1": ("Alpha", "\\alpha"), "\u03b2": ("Alpha", "\\beta"),
    "\u03b3": ("Alpha", "\\gamma"), "\u03b4": ("Alpha", "\\delta"),
    "\u03b5": ("Alpha", "\\varepsilon"), "\u03b6": ("Alpha", "\\zeta"),
    "\u03b7": ("Alpha", "\\eta"), "\u03b8": ("Alpha", "\\theta"),
    "\u03b9": ("Alpha", "\\iota"), "\u03ba": ("Alpha", "\\kappa"),
    "\u03bb": ("Alpha", "\\lambda"), "\u03bc": ("Alpha", "\\mu"),
    "\u03bd": ("Alpha", "\\nu"), "\u03be": ("Alpha", "\\xi"),
    "\u03c0": ("Alpha", "\\pi"), "\u03c1": ("Alpha", "\\rho"),
    "\u03c3": ("Alpha", "\\sigma"), "\u03c4": ("Alpha", "\\tau"),
    "\u03c5": ("Alpha", "\\upsilon"), "\u03c6": ("Alpha", "\\varphi"),
    "\u03c7": ("Alpha", "\\chi"), "\u03c8": ("Alpha", "\\psi"),
    "\u03c9": ("Alpha", "\\omega"), "\u03d1": ("Alpha", "\\vartheta"),
    "\u03d2": ("Alpha", "\\mathrm{\\Upsilon}"), "\u03d5": ("Alpha", "\\phi"),
    "\u03f5": ("Alpha", "\\epsilon"), "\u2009": ("Ord", "\\,"),
    "\u200b": ("Ord", "\\hspace{0pt}"), "\u2016": ("Fence", "\\|"),
    "\u201c": ("Pun", "``"), "\u201d": ("Pun", "\""),
    "\u2021": ("Bin", "\\ddagger"), "\u2022": ("Bin", "\\bullet"),
    "\u2026": ("Ord", "\\ldots"), "\u2032": ("Ord", "\\prime"),
    "\u205f": ("Ord", "\\:"), "\u210f": ("Alpha", "\\hslash"),
    "\u2113": ("Alpha", "\\ell"), "\u2133": ("Alpha", "\\mathcal{M}"),
    "\u2135": ("Alpha", "\\aleph"), "\u2190": ("Rel", "\\leftarrow"),
    "\u2191": ("Rel", "\\uparrow"), "\u2192": ("Rel", "\\rightarrow"),
    "\u2193": ("Rel", "\\downarrow"), "\u2194": ("Rel", "\\leftrightarrow"),
    "\u2198": ("Rel", "\\searrow"), "\u2199": ("Rel", "\\swarrow"),
    "\u219b": ("Rel", "\\nrightarrow"),
    "\u21c4": ("Rel", "\\rightleftarrows"), "\u21c5": ("Rel", "\u21c5"),
    "\u21cb": ("Rel", "\\leftrightharpoons"),
    "\u21cc": ("Rel", "\\rightleftharpoons"),
    "\u21d2": ("Rel", "\\Rightarrow"), "\u21d4": ("Rel", "\\Leftrightarrow"),
    "\u2202": ("Ord", "\\partial"), "\u2205": ("Ord", "\\varnothing"),
    "\u2206": ("Ord", "\\mathrm{\\Delta}"), "\u2207": ("Ord", "\\nabla"),
    "\u2208": ("Rel", "\\in"), "\u2209": ("Rel", "\\notin"),
    "\u220f": ("Op", "\\prod"), "\u2211": ("Op", "\\sum"),
    "\u2212": ("Bin", "-"), "\u2213": ("Bin", "\\mp"),
    "\u2215": ("Bin", "\\slash"), "\u2217": ("Bin", "\\ast"),
    "\u2218": ("Bin", "\\circ"), "\u2219": ("Bin", "\\bullet"),
    "\u221a": ("Rad", "\\sqrt"), "\u221d": ("Rel", "\\propto"),
    "\u221e": ("Ord", "\\infty"), "\u2220": ("Ord", "\\angle"),
    "\u2221": ("Ord", "\\measuredangle"),
    "\u2222": ("Ord", "\\sphericalangle"), "\u2223": ("Rel", "\\mid"),
    "\u2225": ("Rel", "\\parallel"), "\u2227": ("Bin", "\\land"),
    "\u2228": ("Bin", "\\vee"), "\u2229": ("Bin", "\\cap"),
    "\u222a": ("Bin", "\\cup"), "\u222b": ("Op", "\\int"),
    "\u222c": ("Op", "\\iint"), "\u222d": ("Op", "\\iiint"),
    "\u222e": ("Op", "\\oint"), "\u222f": ("Op", "\u222f"),
    "\u2234": ("Ord", "\\therefore"), "\u2236": ("Rel", ":"),
    "\u223c": ("Rel", "\\sim"), "\u223d": ("Rel", "\\backsim"),
    "\u2243": ("Rel", "\\simeq"), "\u2245": ("Rel", "\\cong"),
    "\u2248": ("Rel", "\\approx"), "\u225f": ("Rel", "\u225f"),
    "\u2260": ("Rel", "\\neq"), "\u2261": ("Rel", "\\equiv"),
    "\u2264": ("Rel", "\\leq"), "\u2265": ("Rel", "\\geq"),
    "\u226a": ("Rel", "\\ll"), "\u226b": ("Rel", "\\gg"),
    "\u226e": ("Rel", "\\nless"), "\u226f": ("Rel", "\\ngtr"),
    "\u2270": ("Rel", "\\nleq"), "\u2282": ("Rel", "\\subset"),
    "\u2284": ("Rel", "\u2284"), "\u2286": ("Rel", "\\subseteq"),
    "\u2299": ("Bin", "\\odot"), "\u22a5": ("Ord", "\\bot"),
    "\u22c5": ("Bin", "\\cdot"), "\u22ee": ("Rel", "\\vdots"),
    "\u22ef": ("Ord", "\\cdots"), "\u230a": ("Open", "\\lfloor"),
    "\u230b": ("Close", "\\rfloor"), "\u2323": ("Rel", "\\smile"),
    "\u2329": ("Open", "\\langle"), "\u232a": ("Close", "\\rangle"),
    "\u23b5": ("TUnder", "\u23b5"), "\u23dc": ("TOver", "\u23dc"),
    "\u23df": ("TUnder", "\\underbrace"), "\u25a1": ("Ord", "\\square"),
    "\u25b3": ("Bin", "\\bigtriangleup"), "\u25fb": ("Ord", "\\square"),
    "\u2660": ("Ord", "\\spadesuit"), "\u2661": ("Ord", "\\heartsuit"),
    "\u2662": ("Ord", "\\diamondsuit"), "\u2663": ("Ord", "\\clubsuit"),
    "\u27c2": ("Rel", "\\perp"), "\u27e8": ("Open", "\\langle"),
    "\u27e9": ("Close", "\\rangle"), "\u27f6": ("Rel", "\\longrightarrow"),
    "\u27f9": ("Rel", "\\Longrightarrow"),
    "\u27fa": ("Rel", "\\Longleftrightarrow"), "\u29f8": ("Op", "\u29f8"),
    "\u2a7d": ("Rel", "\\leqslant"), "\u2a7e": ("Rel", "\\geqslant"),
    "\u3008": ("Open", "\\langle"), "\u3009": ("Close", "\\rangle"),
    "\U0001d437": ("Alpha", "D"), "\U0001d447": ("Alpha", "T"),
    "\U0001d44e": ("Alpha", "a"), "\U0001d44f": ("Alpha", "b"),
    "\U0001d453": ("Alpha", "f"), "\U0001d45d": ("Alpha", "p"),
    "\U0001d45f": ("Alpha", "r"), "\U0001d464": ("Alpha", "w"),
    "\U0001d465": ("Alpha", "x"), "\U0001d466": ("Alpha", "y"),
    "\U0001d6ff": ("Alpha", "\\delta")
}
# Characters texmath counts as letters (category Alpha) besides those
# above: ASCII's, and these.
LETTERS = set(".\u00b5\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4"
              "\u03a7\u03bf\u2115\u2119\u211a\u211d\u2124\U0001d499")

# Functions texmath writes as a command of TeX's (Shared.hs, operators).
FUNCTIONS = {"arccos", "arcsin", "arctan", "arg", "cos", "cosh", "cot", "coth",
             "csc", "deg", "det", "dim", "exp", "gcd", "hom", "inf", "ker",
             "lg", "lim", "liminf", "limsup", "ln", "log", "max", "min", "Pr",
             "sec", "sin", "sinh", "sup", "tan", "tanh"}
# The MathML operator dictionary (MMLDict.hs), for the operators OpenStax's
# formulas use and the marks over and under: each form an operator takes
# (before its operand, between two, or after), and whether in that form
# it's a fence (f), stretches (s), or is an accent (a). A fence that
# stretches is matched with its partner, an accent goes over or under, and
# what else stretches makes texmath set what follows it between \left.
# and \right. An operator not here is texmath's own symbol for its
# character, or a function's name.
OPERATORS = {
    "!": "pos", "\"": "pos:a", "%": "inf", "&": "pos", "'": "pos:a",
    "(": "pre:fs", ")": "pos:fs", "*": "inf", "+": "inf pre", ",": "inf",
    "-": "inf pre", ".": "inf", "..": "pos", "...": "pos", "/": "inf",
    "//": "inf", ":": "inf", ";": "inf", "<": "inf", "=": "inf", ">": "inf",
    "?": "inf", "[": "pre:fs", "\\": "inf", "]": "pos:fs", "^": "inf pos:as",
    "_": "inf pos:as", "`": "pos:a", "{": "pre:fs",
    "|": "inf:fs pos:fs pre:fs", "||": "inf:fs pos:fs pre:fs", "}": "pos:fs",
    "~": "pos:as", "\u00af": "pos:as", "\u00b0": "pos", "\u00b1": "inf pre",
    "\u00b2": "pos:a", "\u00b3": "pos:a", "\u00b4": "pos:a", "\u00b7": "inf",
    "\u00ba": "pos:a", "\u00d7": "inf", "\u00f7": "inf", "\u02c6": "pos:as",
    "\u02c7": "pos:as", "\u02d8": "pos:a", "\u02dc": "pos:as",
    "\u0302": "pos:as", "\u2016": "pos:fs pre:fs", "\u2018": "pre:f",
    "\u2019": "pos:f", "\u201c": "pre:f", "\u201d": "pos:f", "\u2022": "inf",
    "\u2026": "inf", "\u2032": "pos", "\u2033": "pos:a", "\u203e": "pos:as",
    "\u2061": "inf", "\u2062": "inf", "\u2063": "inf", "\u20db": "pos:a",
    "\u20dc": "pos:a", "\u2190": "inf:as", "\u2191": "inf:s",
    "\u2192": "inf:as", "\u2193": "inf:s", "\u2194": "inf:as",
    "\u2198": "inf:s", "\u2199": "inf:s", "\u219b": "inf:a",
    "\u21c4": "inf:as", "\u21cb": "inf:as", "\u21cc": "inf:as",
    "\u21d2": "inf:as", "\u21d4": "inf:as", "\u2202": "pre", "\u2206": "inf",
    "\u2207": "pre", "\u2208": "inf", "\u2209": "inf", "\u2211": "pre",
    "\u2212": "inf pre", "\u2213": "inf pre", "\u2215": "inf:s",
    "\u2217": "inf", "\u2218": "inf", "\u2219": "inf", "\u221a": "pre:s",
    "\u221d": "inf", "\u2220": "pre", "\u2221": "pre", "\u2222": "pre",
    "\u2223": "inf", "\u2225": "inf", "\u2227": "inf", "\u2228": "inf",
    "\u2229": "inf", "\u222a": "inf", "\u222b": "pre", "\u222c": "pre",
    "\u222d": "pre", "\u222e": "pre", "\u222f": "pre", "\u2234": "inf",
    "\u2236": "inf", "\u223c": "inf", "\u223d": "inf", "\u2243": "inf",
    "\u2245": "inf", "\u2248": "inf", "\u225f": "inf", "\u2260": "inf",
    "\u2261": "inf", "\u2264": "inf", "\u2265": "inf", "\u226a": "inf",
    "\u226b": "inf", "\u2270": "inf", "\u2282": "inf", "\u2284": "inf",
    "\u2286": "inf", "\u2299": "inf", "\u22a5": "inf", "\u22c5": "inf",
    "\u22ee": "inf", "\u22ef": "inf", "\u230a": "pre:fs", "\u230b": "pos:fs",
    "\u2329": "pre:fs", "\u232a": "pos:fs", "\u23b4": "pos:as",
    "\u23b5": "pos:as", "\u23dc": "pos:as", "\u23de": "pos:as",
    "\u23df": "pos:as", "\u25a1": "inf", "\u25b3": "inf", "\u25e6": "inf",
    "\u27e8": "pre:fs", "\u27e9": "pos:fs", "\u27f6": "inf:as",
    "\u27f9": "inf:as", "\u27fa": "inf:as", "\u2a7d": "inf", "\u2a7e": "inf",
    "\ufe37": "inf:as", "\ufe38": "inf:as"
}
# Invisible operators, which texmath doesn't write.
INVISIBLE = set("\u2061\u2062\u2063\u2064")
# A mark over or under (Shared.hs, diacriticals).
DIACRITICALS = {
    "\u00b4": "\\acute", "\u0301": "\\acute", "`": "\\grave", "\u0300": "\\grave",
    "\u02d8": "\\breve", "\u0306": "\\breve", "\u02c7": "\\check", "\u030c": "\\check",
    "\u0307": "\\dot", "\u0308": "\\ddot", "\u20db": "\\dddot", "\u20dc": "\\ddddot",
    "\u00b0": "\\mathring", "\u030a": "\\mathring", "\u20d7": "\\overrightarrow",
    "\u20d6": "\\overleftarrow", "^": "\\hat", "\u02c6": "\\widehat",
    "\u0302": "\\widehat", "\u02dc": "\\widetilde", "\u0303": "\\widetilde",
    "\u0304": "\\bar", "\u203e": "\\bar", "\u23de": "\\overbrace",
    "\u23b4": "\\overbracket", "\u00af": "\\overline", "\u0305": "\\overline",
    "\u23df": "\\underbrace", "\u23b5": "\\underbracket", "\u0332": "\\underline",
    "_": "\\underline", "\u0333": "\\underbar"}
UNDER = {"\\underbrace", "\\underline", "\\underbar", "\\underbracket"}
NARROW = {"\\overrightarrow": "\\vec", "\\widehat": "\\hat", "\\widetilde": "\\tilde"}
# What a delimiter can be after \left, \middle, or \right (TeX.hs).
DELIMITERS = {".", "(", ")", "\\lbrack", "\\rbrack", "|", "\\|", "\\{", "\\}",
              "\\rceil", "\\lceil", "\\langle", "\\rangle", "\\rfloor", "\\lfloor",
              "\\ulcorner", "\\urcorner"}
STYLES = {"normal": "\\mathrm", "bold": "\\mathbf", "italic": "\\mathit",
          "bold-italic": "\\mathbf", "monospace": "\\mathtt", "sans-serif": "\\mathsf",
          "double-struck": "\\mathbb", "script": "\\mathcal", "fraktur": "\\mathfrak"}
# The commands text of each style is written in (TeX.hs, getTextCommand),
# the outer first.
TEXT_STYLES = {"normal": ["\\text"], "italic": ["\\textit"], "bold": ["\\textbf"],
               "monospace": ["\\texttt"], "bold-italic": ["\\textit", "\\textbf"],
               "sans-serif": ["\\textsf"], "bold-sans-serif": ["\\textbf", "\\textsf"],
               "sans-serif-italic": ["\\textit", "\\textsf"],
               "sans-serif-bold-italic": ["\\textbf", "\\textit", "\\textsf"]}
UNITS = {"pt": Fraction(1, 10), "mm": Fraction(2845, 10000), "cm": Fraction(2845, 1000),
         "in": Fraction(7227, 1000), "ex": Fraction(43, 100), "em": Fraction(1),
         "mu": Fraction(1, 18), "dd": Fraction(107, 1000), "bp": Fraction(1004, 10000),
         "pc": Fraction(12, 10)}
NAMED_SPACES = {"veryverythinmathspace": 1, "verythinmathspace": 2, "thinmathspace": 3,
                "mediummathspace": 4, "thickmathspace": 5, "verythickmathspace": 6,
                "veryverythickmathspace": 7}
SPACE_WIDTHS = {" ": Fraction(4, 18), "\u00a0": Fraction(4, 18), "\u2000": Fraction(1, 2),
                "\u2001": Fraction(1), "\u2002": Fraction(1, 2), "\u2003": Fraction(1),
                "\u2004": Fraction(1, 3), "\u2005": Fraction(4, 18), "\u2006": Fraction(1, 6),
                "\u2007": Fraction(1, 3), "\u2008": Fraction(1, 6), "\u2009": Fraction(1, 6),
                "\u200a": Fraction(1, 9), "\u200b": Fraction(0), "\u202f": Fraction(3, 18),
                "\u205f": Fraction(4, 18)}
EMPTY = ("grp", [])


class Unreadable(Exception):
    """Markup texmath's MathML reader doesn't read."""


# Reading: MathML to texmath's tree. An expression is a tuple whose first
# item names its kind, as texmath's Exp does; while a row is read, a fence
# that stretches is ("S", position, kind, text) and a script after a
# closing fence ("T", kind, script), texmath's IR.

def _name(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _children(el):
    return [c for c in el if isinstance(c.tag, str)]


def _category(c):
    """A character's category in texmath's records."""
    if c in SYMBOLS:
        return SYMBOLS[c][0]
    if (c.isascii() and c.isalpha()) or c in LETTERS:
        return "Alpha"
    return "Ord"


def _string(el):
    """A token's text, its spaces, tabs, and newlines at either end
    taken off (MathML.hs, getString: no other space)."""
    text = (el.text or "") + "".join(c.tail or "" for c in el)
    return text.strip(" \t\n")


def _width(text):
    text = (text or "").strip()
    if text in NAMED_SPACES:
        return Fraction(NAMED_SPACES[text], 18)
    if text.startswith("negative") and text[8:] in NAMED_SPACES:
        return Fraction(-NAMED_SPACES[text[8:]], 18)
    found = re.fullmatch(r"(-?\d+(?:\.\d+)?)(.*)", text)
    if not found or found.group(2) not in UNITS:
        return Fraction(0)
    return Fraction(round(float(found.group(1)) * 18), 18) * UNITS[found.group(2)]


class _State:
    __slots__ = ("attrs", "position", "accent", "style")

    def __init__(self, attrs=None, position=None, accent=False, style="normal"):
        self.attrs, self.position = attrs or {}, position
        self.accent, self.style = accent, style

    def but(self, **changes):
        state = _State(self.attrs, self.position, self.accent, self.style)
        for key, value in changes.items():
            setattr(state, key, value)
        return state


def _expr(el, state):
    """A list of IR for an element (MathML.hs, expr)."""
    attrs = dict(state.attrs)
    for key, value in el.attrib.items():
        attrs["accent" if key == "accentunder" else key] = value
    state = state.but(attrs=attrs)
    name = _name(el)
    if name == "mi":
        text = _string(el)
        base = ("mop", text) if text in FUNCTIONS else ("id", text)
        variant = el.get("mathvariant") or state.attrs.get("mathvariant")
        if variant and variant != state.style and variant in STYLES:
            return [("E", ("styled", variant, [base]))]
        return [("E", base)]
    if name == "mn":
        return [("E", ("num", _string(el)))]
    if name == "mo":
        return [_operator(el, state)]
    if name == "mtext":
        text = _string(el)
        variant = el.get("mathvariant") or state.attrs.get("mathvariant") or "normal"
        if variant == "normal" and len(text) == 1 and text in SPACE_WIDTHS:
            return [("E", ("space", SPACE_WIDTHS[text]))]
        return [("E", ("text", variant, text))]
    if name == "ms":
        variant = el.get("mathvariant") or state.attrs.get("mathvariant") or "normal"
        return [("E", ("text", variant, "\u201c" + _string(el) + "\u201d"))]
    if name == "mspace":
        return [("E", ("space", _width(el.get("width") or "0.0em")))]
    if name in ("mrow", "mpadded"):
        return [("E", _row(el, state))]
    if name == "mstyle":
        variant = el.get("mathvariant")
        inner = state.but(style=variant or state.style,
                          attrs={k: v for k, v in state.attrs.items() if k != "mathvariant"})
        row = _row(el, inner)
        if variant and variant != state.style and variant in STYLES:
            return [("E", ("styled", variant, [row]))]
        return [("E", row)]
    if name == "mfrac":
        a, b = _two(el)
        thin = (el.get("linethickness") or "").strip() in ("0", "0em", "0pt", "0px", "0ex")
        return [("E", ("frac", "binom" if thin else "frac", _safe(a, state), _safe(b, state)))]
    if name == "msqrt":
        return [("E", ("sqrt", _row(el, state)))]
    if name == "mroot":
        base, index = _two(el)
        return [("E", ("root", _safe(index, state), _safe(base, state)))]
    if name in ("merror", "maligngroup", "malignmark"):
        return [("E", EMPTY)]
    if name == "mphantom":
        return [("E", ("phantom", _row(el, state)))]
    if name == "mfenced":
        return [("E", _fenced(el, state))]
    if name == "menclose":
        kind = {"box": "\\boxed", "updiagonalstrike": "\\cancel",
                "downdiagonalstrike": "\\bcancel",
                "updiagonalstrike downdiagonalstrike": "\\xcancel"}.get(el.get("notation"))
        row = _row(el, state)
        return [("E", ("command", kind, row) if kind else row)]
    if name in ("msub", "msup"):
        base, script = _two(el)
        return _reorder(base, script, "sub" if name == "msub" else "sup", state)
    if name == "msubsup":
        base, below, above = _three(el)
        return [("E", ("subsup", _safe(base, state), _postfix(below, state),
                       _postfix(above, state)))]
    if name == "munder":
        base, below = _two(el)
        return [("E", ("under", _safe(base, state), _postfix(below, state)))]
    if name == "mover":
        base, above = _two(el)
        return [("E", ("over", _safe(base, state), _postfix(above, state)))]
    if name == "munderover":
        base, below, above = _three(el)
        return [("E", ("underover", _safe(base, state), _postfix(below, state),
                       _postfix(above, state)))]
    if name == "mtable":
        return [("E", _table(el, state))]
    if name == "maction":
        chosen = _children(el)[int(el.get("selection") or 1) - 1:]
        if not chosen:
            raise Unreadable(name)
        return [("E", _safe(chosen[0], state))]
    if name == "mmultiscripts":
        return [("E", _multiscripts(el, state))]
    if name == "semantics":
        kids = _children(el)
        if not kids:
            raise Unreadable(name)
        first = _safe(kids[0], state)
        if first != EMPTY:
            return [("E", first)]
        for annotation in kids[1:]:
            if annotation.get("encoding") in ("application/mathml-presentation+xml",
                                              "MathML-Presentation"):
                return [("E", _row(annotation, state))]
        return [("E", EMPTY)]
    raise Unreadable(name)


def _two(el):
    kids = _children(el)
    if len(kids) != 2:
        raise Unreadable(_name(el))
    return kids


def _three(el):
    kids = _children(el)
    if len(kids) != 3:
        raise Unreadable(_name(el))
    return kids


def _properties(text, position):
    """(form, properties) of an operator's entry in the dictionary for
    where it stands, or the first in the order texmath tries (MMLDict.hs,
    getMathMLOperator): infix, postfix, prefix."""
    entry = OPERATORS.get(text)
    if entry is None:
        return None, ""
    forms = dict((part + ":").split(":")[:2] for part in entry.split())
    for form in (position, "infix", "postfix", "prefix"):
        if form[:3] in forms:
            return form, forms[form[:3]]


def _operator(el, state):
    """An mo (MathML.hs, op): a fence that stretches stays one to be
    matched with its partner; anything else is a symbol of its kind."""
    text = _string(el)
    position = el.get("form") or state.attrs.get("form") or state.position or "infix"
    form, props = _properties(text, position)
    where = {"prefix": "Open", "postfix": "Close"}.get(form, "Op")

    def has(prop, code):
        value = state.attrs.get(prop)
        return code in props if value is None else value.strip() == "true"
    if has("accent", "a"):
        kind = ("sym", "Accent", text)
    elif has("fence", "f"):
        kind = ("sym", where, text)
    elif len(text) == 1:
        kind = ("sym", _category(text), text)
    elif form is not None:
        kind = ("sym", "Ord", text)
    else:
        kind = ("mop", text)
    if has("stretchy", "s") and not state.accent:
        return ("S", where, kind, text)
    return ("E", kind)


def _safe(el, state):
    return _make(_expr(el, state))


def _postfix(el, state):
    return _safe(el, state.but(position="postfix", accent=True))


def _reorder(base, script, kind, state):
    """A script on a fence (MathML.hs, reorderScripts)."""
    based = _expr(base, state)
    scripted = _postfix(script, state)
    if len(based) == 1 and based[0][0] == "S":
        if based[0][1] == "Open":
            return [based[0], ("E", (kind, EMPTY, scripted))]
        if based[0][1] == "Close":
            return [("T", kind, scripted), based[0]]
        return [based[0], ("E", ("sub", EMPTY, scripted))]
    return [("E", (kind, _make(based), scripted))]


def _row(el, state):
    """An mrow, or anything read as one (MathML.hs, row and group): the
    space-like elements at either end apart, and each other element given
    its place, the first a prefix, the last a postfix."""
    kids = _children(el)

    def spacelike(e):
        return _name(e) in ("mtext", "mspace", "maligngroup", "malignmark") or (
            _name(e) in ("mrow", "mstyle", "mphantom", "mpadded")
            and all(spacelike(c) for c in _children(e)))
    front = 0
    while front < len(kids) and spacelike(kids[front]):
        front += 1
    end = len(kids)
    while end > front and spacelike(kids[end - 1]):
        end -= 1
    out = []
    for kid in kids[:front]:
        out += _expr(kid, state)
    body = kids[front:end]
    for i, kid in enumerate(body):
        if len(body) == 1:
            position = "infix"
        elif i == 0:
            position = "prefix"
        elif i == len(body) - 1:
            position = "postfix"
        else:
            position = "infix"
        out += _expr(kid, state.but(position=position))
    for kid in kids[end:]:
        out += _expr(kid, state.but(position=None))
    return _make(out)


def _make(irs):
    """texmath's mkExp: fences matched, then one expression or a group."""
    if len(irs) == 1 and irs[0][0] == "S":
        items = [("R", irs[0][2])]
    else:
        items = _match(irs)
    if any(kind == "L" for kind, _ in items):
        if len(items) == 1:
            return ("sym", "Ord", items[0][1])
        return ("delim", "", "", items)
    exps = [value for kind, value in items if kind == "R"]
    if len(exps) == 1:
        return exps[0]
    return ("grp", exps)


def _unstretch(irs):
    if len(irs) == 1 and irs[0][0] == "S":
        return [("R", irs[0][2])]
    return [("L", ir[3]) if ir[0] == "S" else ("R", ir[1]) if ir[0] == "E" else ir
            for ir in irs]


def _match(irs):
    """Opening and closing fences paired (MathML.hs, matchNesting): each
    pair and what's between them a delimited expression."""
    def is_fence(ir):
        return ir[0] == "S" and ir[1] in ("Open", "Close")
    split = next((i for i, ir in enumerate(irs) if is_fence(ir)), len(irs))
    before, rest = irs[:split], irs[split:]
    out = _unstretch(before)
    if not rest:
        return out
    first = rest[0]
    if first[1] == "Open":
        depth, i = 0, 1
        while i < len(rest):
            ir = rest[i]
            if ir[0] == "S" and ir[1] == "Close":
                if depth == 0:
                    break
                depth -= 1
            elif ir[0] == "S" and ir[1] == "Open":
                depth += 1
            i += 1
        body = _match(rest[1:i])
        if i >= len(rest):
            return out + [("R", _trailing(first[3], None, body))]
        return out + [("R", _trailing(first[3], rest[i][3], body))] + _match(rest[i + 1:])
    return [("R", _trailing(None, first[3], _match(before)))] + _match(rest[1:])


def _trailing(open_, close, items):
    """A delimited expression, a script after its closing fence applied
    to the whole (MathML.hs, trailingSup)."""
    if not items:
        if open_ is None and close is None:
            return EMPTY
        if close is None:
            return ("sym", "Open", open_)
        if open_ is None:
            return ("sym", "Close", close)
        return ("grp", [("sym", "Open", open_), ("sym", "Close", close)])
    if items[-1][0] == "T":
        return (items[-1][1], _trailing(open_, close, items[:-1]), items[-1][2])
    return ("delim", open_ or "", close or "",
            [(kind, value) for kind, value in items])


def _multiscripts(el, state):
    """An mmultiscripts (MathML.hs, multiscripts): the scripts after the
    base, and those before it on an empty base of their own."""
    kids = _children(el)
    split = next((i for i, k in enumerate(kids) if _name(k) == "mprescripts"), len(kids))
    post, pre = kids[:split], kids[split + 1:]

    def read(e):
        if _name(e) == "none":
            return EMPTY
        if _name(e) == "mrow":
            return _row(e, state)
        return _safe(e, state)

    def one(items):
        return items[0] if len(items) == 1 else ("grp", items)

    def scripted(base, subs, sups):
        if subs and sups:
            return ("subsup", base, one(subs), one(sups))
        if subs:
            return ("sub", base, one(subs))
        if sups:
            return ("sup", base, one(sups))
        return base
    post = [read(k) for k in post]
    pre = [read(k) for k in pre]
    base = post[0] if post else EMPTY
    right = scripted(base, post[1::2], post[2::2])
    left = scripted(EMPTY, pre[0::2], pre[1::2])
    return ("grp", [left, right])


def _fenced(el, state):
    """An mfenced as the mrow it stands for (MathML.hs, fenced)."""
    open_ = el.get("open", "(")
    close = el.get("close", ")")
    separators = el.get("separators", ",")
    kids = _children(el)
    inner = etree.Element("mrow")
    for i, kid in enumerate(kids):
        if i and separators:
            mark = etree.SubElement(inner, "mo")
            mark.text = separators[min(i - 1, len(separators) - 1)]
        inner.append(_copy(kid))
    row = etree.Element("mrow")
    if open_:
        etree.SubElement(row, "mo").text = open_
    row.append(inner)
    if close:
        etree.SubElement(row, "mo").text = close
    return _safe(row, state)


def _copy(el):
    from copy import deepcopy
    made = deepcopy(el)
    made.tail = None
    return made


def _table(el, state):
    """An mtable (MathML.hs, table): its cells, and each column's
    alignment where its cells agree. An alignment is the element's own or
    one an element around it gives (findAttrQ), the table's for a row and
    a row's for a cell only where there's neither."""
    def align(e, otherwise):
        found = e.get("columnalign")
        if found is None:
            found = state.attrs.get("columnalign")
        if found is None:
            return otherwise
        return found if found in ("left", "right", "center") else "center"
    default = align(el, "center")
    rows = []
    for tr in _children(el):
        name = _name(tr)
        if name not in ("mtr", "mlabeledtr"):
            raise Unreadable(name)
        row_align = align(tr, default)
        cells = _children(tr)[1:] if name == "mlabeledtr" else _children(tr)
        row = []
        for td in cells:
            if _name(td) != "mtd":
                raise Unreadable(_name(td))
            row.append((align(td, row_align), [_row(td, state)]))
        rows.append(row)
    width = max((len(r) for r in rows), default=0)
    columns = []
    for c in range(width):
        found = [r[c][0] for r in rows if c < len(r)]
        columns.append(found[0] if found and all(a == found[0] for a in found) else "center")
    return ("array", columns, [[cell for _, cell in r] + [[] for _ in range(width - len(r))]
                               for r in rows])


def _fix(e):
    """texmath's fixTree: empty expressions out of every list, a group of
    one its one, a delimited expression in another made one."""
    kind = e[0]
    if kind in ("grp", "styled"):
        items = [x for x in (_fix(x) for x in e[-1]) if x != EMPTY]
        e = ("grp", items) if kind == "grp" else ("styled", e[1], items)
    elif kind == "delim":
        e = ("delim", e[1], e[2], [(k, _fix(v) if k == "R" else v) for k, v in e[3]])
    elif kind == "array":
        e = ("array", e[1], [[[x for x in (_fix(y) for y in cell) if x != EMPTY]
                              for cell in row] for row in e[2]])
    elif kind in ("frac",):
        e = (kind, e[1], _fix(e[2]), _fix(e[3]))
    elif kind in ("command",):
        e = (kind, e[1], _fix(e[2]))
    elif kind in ("sub", "sup", "under", "over", "subsup", "underover", "sqrt", "root",
                  "phantom"):
        e = (kind,) + tuple(_fix(x) for x in e[1:])
    # removeNesting
    if e[0] == "delim" and len(e[3]) == 1 and e[3][0][0] == "R" \
            and e[3][0][1][0] == "delim" and e[3][0][1][1] == "" and e[3][0][1][2] == "":
        e = ("delim", e[1], e[2], e[3][0][1][3])
    if e[0] == "delim" and e[1] == "" and e[2] == "" and len(e[3]) == 1:
        k, v = e[3][0]
        e = ("sym", "Ord", v) if k == "L" else v
    if e[0] == "grp" and len(e[1]) == 1:
        e = e[1][0]
    return e


# Writing: texmath's tree to TeX (Writers/TeX.hs). A token is ("tok", c),
# ("lit", text), ("cs", command), ("sp",), or ("grp", tokens).

def _is_command(text):
    return text.startswith("\\") and (
        (len(text) == 2 and text[1] != " ") or (len(text) > 1 and text[1:].isalpha()))


def _escape(c):
    """A character of text in \\text{} (TeX.hs, escapeLaTeX)."""
    special = {"~": ("cs", "\\textasciitilde"), "^": ("lit", "\\textasciicircum"),
               "\\": ("cs", "\\textbackslash"), "\u200b": ("lit", "\\!"),
               "\u200a": ("lit", "\\,"), "\u2006": ("lit", "\\,"), "\u00a0": ("lit", "~"),
               "\u2005": ("lit", "\\:"), "\u2004": ("lit", "\\;"), "\u2001": ("cs", "\\quad"),
               "\u2003": ("cs", "\\quad"), "\u2032": ("lit", "'"), "\u2033": ("lit", "''"),
               "\u2034": ("lit", "'''")}
    if c in special:
        return special[c]
    if c in "#$%&_{} ":
        return ("lit", "\\" + c)
    return ("tok", c)


def _chars(text):
    """A string's TeX, character by character (Unicode/ToTeX.hs,
    getTeXMath)."""
    out = []
    for c in text:
        if c == "\ufe00":
            continue
        if c in SYMBOLS:
            category, raw = SYMBOLS[c]
            if _is_command(raw):
                out.append(("cs", raw))
            elif len(raw) == 1:
                out.append(("tok", raw))
            else:
                out.append(("lit", raw))
            if category in ("Accent", "Rad", "TOver", "TUnder"):
                out.append(("grp", []))
        else:
            out += _styled(c) or [_escape(c)]
    return out


# A letter in a style of its own (Unicode/ToUnicode.hs, fromUnicodeChar),
# the command for the style (Shared.hs, textTypes, with amsmath and
# amssymb).
LETTER_STYLES = (("MATHEMATICAL BOLD ", "\\mathbf"), ("MATHEMATICAL ITALIC ", "\\mathit"),
                 ("MATHEMATICAL SCRIPT ", "\\mathcal"), ("SCRIPT ", "\\mathcal"),
                 ("MATHEMATICAL FRAKTUR ", "\\mathfrak"), ("BLACK-LETTER ", "\\mathfrak"),
                 ("MATHEMATICAL DOUBLE-STRUCK ", "\\mathbb"), ("DOUBLE-STRUCK ", "\\mathbb"),
                 ("MATHEMATICAL SANS-SERIF ", "\\mathsf"),
                 ("MATHEMATICAL MONOSPACE ", "\\mathtt"))


def _unstyled(e, command):
    """An expression in a style with its letters of that style plain
    (Writers/TeX.hs, fromUnicodeExp)."""
    def plain(text):
        out = ""
        for c in text:
            made = _styled(c)
            out += made[1][1][0][1] if made and made[0][1] == command else c
        return out
    kind = e[0]
    if kind in ("num", "id", "mop"):
        return (kind, plain(e[1]))
    if kind == "sym":
        return (kind, e[1], plain(e[2]))
    if kind == "text":
        return (kind, e[1], plain(e[2]))
    if kind == "delim":
        return (kind, plain(e[1]), plain(e[2]),
                [(k, plain(v) if k == "L" else v) for k, v in e[3]])
    return e


def _styled(c):
    """A letter or digit in a style of its own as the style's command and
    the plain character, as texmath writes one it has no command for."""
    try:
        name = unicodedata.name(c)
    except ValueError:
        return None
    for prefix, command in LETTER_STYLES:
        if name.startswith(prefix):
            rest = name[len(prefix):].split()
            if len(rest) == 2 and rest[0] in ("CAPITAL", "SMALL") and len(rest[1]) == 1:
                letter = rest[1] if rest[0] == "CAPITAL" else rest[1].lower()
            elif len(rest) == 2 and rest[0] == "DIGIT":
                letter = str(["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN",
                              "EIGHT", "NINE"].index(rest[1]))
            else:
                return None
            return [("cs", command), ("grp", [("tok", letter)])]
    return None


def _space(width):
    """A space's command (TeX.hs, getSpaceCommand)."""
    n = (width * 18).__floor__()
    return {-3: "\\!", 0: "", 3: "\\,", 4: "\\ ", 5: "\\;", 18: "\\quad",
            36: "\\qquad"}.get(n, "\\mspace{%dmu}" % n)


def _fancy(e):
    return e[0] in ("sub", "sup", "subsup", "over", "under", "underover", "sqrt",
                    "root", "phantom")


def _narrow(e):
    if e[0] in ("id", "num"):
        return len(e[1]) == 1
    if e[0] == "sym":
        return len(e[2]) == 1
    if e[0] == "grp" and len(e[1]) == 1:
        return _narrow(e[1][0])
    if e[0] == "styled" and len(e[2]) == 1:
        return _narrow(e[2][0])
    return False


def _primes(e):
    if e[0] != "sym" or e[1] not in ("Pun", "Ord"):
        return None
    out = ""
    for c in e[2]:
        if c in ("'", "\u2032"):
            out += "'"
        elif c == "\u2033":
            out += "''"
        elif c == "\u2034":
            out += "'''"
        elif c == "\u2057":
            out += "''''"
        else:
            return None
    return out


def _standard(item):
    kind, e = item
    return kind == "R" and (e[0] in ("id", "num", "space")
                            or (e[0] == "sym" and e[1] in ("Ord", "Op", "Bin", "Rel", "Pun")))


def _valid(tokens):
    return len(tokens) == 1 and tokens[0][0] in ("tok", "cs") and tokens[0][1] in DELIMITERS


def _delimiter(where, text, out):
    """\\left, \\middle, or \\right and its delimiter (TeX.hs, writeDelim)."""
    tex = _chars(text)
    valid = _valid(tex)
    if where == "left":
        out += [("cs", "\\left")] + (tex if valid else [("tok", ".")]) + [("sp",)] \
            + ([] if valid else tex)
    elif where == "middle":
        out += [("sp",), ("cs", "\\middle")] + tex + [("sp",)] if valid else tex
    else:
        out += [("sp",), ("cs", "\\right")] + (tex if valid else [("tok", ".")]) \
            + ([] if valid else tex)


def _group(exps):
    out = []
    for e in exps:
        _write(e, out)
    return ("grp", out)


def _array(name, aligns, rows, out):
    out += [("cs", "\\begin"), ("grp", [("lit", name)])]
    if aligns:
        out.append(("grp", [("lit", "".join({"left": "l", "right": "r"}.get(a, "c")
                                           for a in aligns))]))
    out.append(("tok", "\n"))
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            for e in cell:
                _write(e, out)
            if c + 1 < len(row):
                out += [("sp",), ("tok", "&"), ("sp",)]
        out += [("tok", "\n")] if r + 1 == len(rows) else [("sp",), ("lit", "\\\\"), ("tok", "\n")]
    out += [("cs", "\\end"), ("grp", [("lit", name)])]


def _script(where, base, mark, out):
    """A mark over or under (TeX.hs, writeScript)."""
    command = None
    if mark[0] == "sym" and mark[1] in ("Accent", "TOver", "TUnder"):
        command = DIACRITICALS.get(mark[2])
        if command is not None and (command in UNDER) != (where == "under"):
            command = None
        if command is not None and _narrow(base):
            command = NARROW.get(command, command)
    if command:
        out += [("cs", command), _group([base])]
    elif base[0] == "mop" or (base[0] == "sym" and base[1] == "Op"):
        if _fancy(base):
            out.append(_group([base]))
        else:
            _write(base, out)
        out += [("cs", "\\limits"), ("tok", "^" if where == "over" else "_"), _group([mark])]
    else:
        out += [("cs", "\\overset" if where == "over" else "\\underset"), _group([mark]),
                _group([base])]


def _write(e, out):
    kind = e[0]
    if kind == "num":
        out += _chars(e[1])
    elif kind == "grp":
        out.append(_group(e[1]))
    elif kind == "id":
        tex = _chars(e[1])
        out += tex if len(tex) <= 1 else [("grp", tex)]
    elif kind == "mop":
        if e[1] in FUNCTIONS:
            out.append(("cs", "\\" + e[1]))
        else:
            out += [("cs", "\\operatorname"), ("grp", _chars(e[1]))]
    elif kind == "sym":
        category, text = e[1], e[2]
        if category == "Ord" and len(text) == 1 and text in INVISIBLE:
            return
        if category == "Ord" and text == "\u2032":
            out.append(("tok", "'"))
            return
        spaced = category in ("Bin", "Rel")
        if spaced:
            out.append(("sp",))
        if len(text) > 1 and category in ("Bin", "Rel", "Op"):
            out += [("cs", "\\math" + category.lower()),
                    ("grp", [("cs", "\\text"), ("grp", _chars(text))])]
        else:
            out += _chars(text)
        if spaced:
            out.append(("sp",))
    elif kind == "space":
        out.append(("cs", _space(e[1])))
    elif kind == "text":
        tokens = [("lit", " ") if t == ("lit", "\\ ") else t for t in map(_escape, e[2])]
        if tokens:
            commands = TEXT_STYLES.get(e[1], ["\\text"])
            made = ("grp", tokens)
            for command in reversed(commands[1:]):
                made = ("grp", [("cs", command), made])
            out += [("cs", commands[0]), made]
    elif kind == "styled":
        command = STYLES[e[1]]
        out += [("cs", command), _group([_unstyled(x, command) for x in e[2]])]
    elif kind == "frac":
        out += [("cs", "\\frac" if e[1] == "frac" else "\\binom"), _group([e[2]]),
                _group([e[3]])]
    elif kind in ("sub", "sup"):
        base, script = e[1], e[2]
        out.append(_group([base]) if _fancy(base) else None)
        if out[-1] is None:
            out.pop()
            _write(base, out)
        primes = _primes(script) if kind == "sup" else None
        if primes is not None:
            out += [("tok", "'")] * len(primes)
        else:
            out += [("tok", "_" if kind == "sub" else "^"), _group([script])]
    elif kind == "subsup":
        base, below, above = e[1], e[2], e[3]
        if _fancy(base):
            out.append(_group([base]))
        else:
            _write(base, out)
        out += [("tok", "_"), _group([below])]
        primes = _primes(above)
        if primes is not None:
            out += [("tok", "'")] * len(primes)
        else:
            out += [("tok", "^"), _group([above])]
    elif kind in ("over", "under"):
        _script(kind, e[1], e[2], out)
    elif kind == "underover":
        base, below, above = e[1], e[2], e[3]
        if below[0] == "sym" and below[1] == "Accent":
            _write(("under", ("over", base, above), below), out)
        elif above[0] == "sym" and above[1] == "Accent":
            _write(("over", ("under", base, below), above), out)
        elif base[0] == "mop" or (base[0] == "sym" and base[1] == "Op"):
            if _fancy(base):
                out.append(_group([base]))
            else:
                _write(base, out)
            out += [("cs", "\\limits"), ("tok", "_"), _group([below]), ("tok", "^"),
                    _group([above])]
        else:
            _write(("under", ("over", base, above), below), out)
    elif kind == "sqrt":
        out += [("cs", "\\sqrt"), _group([e[1]])]
    elif kind == "root":
        out += [("cs", "\\sqrt"), ("tok", "[")]
        _write(e[1], out)
        out += [("tok", "]"), _group([e[2]])]
    elif kind == "phantom":
        out += [("cs", "\\phantom"), _group([e[1]])]
    elif kind == "command":
        out += [("cs", e[1]), _group([e[2]])]
    elif kind == "array":
        aligns, rows = e[1], e[2]
        right_left = len(aligns) >= 2 and len(aligns) % 2 == 0 and all(
            a == ("right" if i % 2 == 0 else "left") for i, a in enumerate(aligns))
        if right_left:
            _array("aligned", [], rows, out)
        elif all(a == "center" for a in aligns):
            _array("matrix", [], rows, out)
        else:
            _array("array", aligns, rows, out)
    elif kind == "delim":
        _write_delimited(e, out)


def _write_delimited(e, out):
    open_, close, items = e[1], e[2], e[3]
    if len(items) == 1 and items[0][0] == "R" and items[0][1][0] == "array":
        inner = items[0][1]
        name = {("(", ")"): "pmatrix", ("[", "]"): "bmatrix", ("{", "}"): "Bmatrix",
                ("\u2223", "\u2223"): "vmatrix", ("\u2225", "\u2225"): "Vmatrix"}.get(
                    (open_, close))
        if open_ == "{" and close == "" and inner[1] == ["left", "left"]:
            _array("cases", [], inner[2], out)
            return
        if name and all(a == "center" for a in inner[1]):
            _array(name, [], inner[2], out)
            return
    if (all(_standard(i) for i in items) and open_ in ("(", "[", "|")
            and close in (")", "]", "|")):
        out += _chars(open_)
        for kind, value in items:
            _write(value, out)
        out += _chars(close)
        return
    _delimiter("left", open_, out)
    for kind, value in items:
        if kind == "L":
            _delimiter("middle", value, out)
        else:
            _write(value, out)
    _delimiter("right", close, out)


def _trim(tokens):
    while tokens and tokens[0] == ("sp",):
        tokens = tokens[1:]
    while tokens and tokens[-1] == ("sp",):
        tokens = tokens[:-1]
    return tokens


def _render(tokens, after=""):
    """Tokens as text (TeX.hs, renderTeX): a space after a command that a
    letter or digit follows, none before a script, a group of one group
    one group."""
    for token in reversed(tokens):
        after = _render_one(token, after)
    return after


def _render_one(token, after):
    kind = token[0]
    if kind == "tok":
        return token[1] + after
    if kind == "lit":
        text = token[1]
        if text and not text[-1].isalpha():
            return text + after
        if after[:1].isalpha():
            return text + " " + after
        return text + after
    if kind == "cs":
        text = token[1]
        if text == "\\ ":
            return text + after
        if after[:1] and (after[0].isalnum() or not after[0].isascii()):
            return text + " " + after
        return text + after
    if kind == "grp":
        inner = token[1]
        while len(inner) == 1 and inner[0][0] == "grp":
            inner = inner[0][1]
        return "{" + _render(_trim(inner)) + "}" + after
    if not after or after.startswith(("^", "_", " ", "\\limits")):
        return after
    return " " + after


def tex(math):
    """A formula's TeX as Pandoc writes it, given its <math> element; its
    text alone if texmath couldn't read it, as Pandoc keeps it then."""
    try:
        exps = _row(math, _State())
        # The formula's own list isn't cleared of empty expressions.
        exps = [_fix(x) for x in (exps[1] if exps[0] == "grp" else [exps])]
    except (Unreadable, ValueError, IndexError):
        return " ".join("".join(math.itertext()).split())
    if len(exps) == 1 and exps[0][0] == "grp":
        exps = exps[0][1]
    tokens = []
    for e in exps:
        _write(e, tokens)
    return _render([("grp", tokens)])[1:-1]
