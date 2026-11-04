r"""
cnx.texforms -- a formula of OpenStax's exercise bank in forms Pandoc's
TeX reader takes.

The bank keeps an exercise's formulas as TeX, written for MathJax, which
reads more of plain TeX and of its own extensions than Pandoc's TeX
reader (texmath) does. Of the 11,070 different formulas in the 19,258
exercises fetched for the 26 books that embed them (17,871 formulas in
2,733 exercises; 2026-11-03), 383 stopped Pandoc 3.12.1's reader as
written, all but one for one of these, which latex_forms writes as
LaTeX writes them:

    {\rm wrench}      plain TeX's font switches, which act on the rest of
                      their group, or of the alignment's cell or the
                      \left's group they're in, past an \over: where
                      that's nothing but text and holds a word, of two
                      letters or more, each run of words (and the
                      numbers and spaces among them) \text{wrench}, so
                      that MathML holds the word, not its letters (which
                      \mathrm gives, one identifier each), as an
                      upright identifier of two letters is text for an
                      HTML source; the operators, relations, and brackets
                      between runs math, as TeX sets them ({\rm max -
                      min} is \text{max}-\text{min}), one a control word
                      names too (\wedge, \le); \mathrm{C} otherwise;
                      \bf, \it, \sf, \tt, and \cal as \mathbf and the
                      rest
    {1 \over 8}       plain TeX's fraction: \frac{1}{8}
    \unicode[A]{x3B2} MathJax's character by its number: the character,
                      or its control symbol where TeX gives it a
                      meaning (\%, \{); a backslash, ^, ~, and what
                      XML doesn't allow (a control character, half a
                      surrogate pair) are left as written
    \mkern 1mu        a space as plain TeX gives it: \mspace{1mu}, in
    \kern 1pt         whole mu (a point taken as 1.8 mu, at 10 points)
    \hfill            ending each row of an array of one column, as
                      MathType writes rows aligned left and MathJax
                      aligns them: the column aligned left; and every
                      \hfill left out, which texmath doesn't read, a
                      cell aligned as its column is, as MathJax 3.2.2
                      aligns gathered's (it reads no \hfill there)
    50%  $10          a percent sign or a dollar sign as written, which
                      TeX reads as a comment, or as the end of the
                      formula: \% and \$ (in a \text, \% alone)
    a\\b              a line break outside an environment, which MathJax
                      sets as the next line: an array of one column, its
                      rows left-aligned, a break at the end left out
    % <![CDATA[ ... %]]>
                      a formula wrapped as XHTML pages once wrapped
                      them, the TeX comments hiding the markers: the
                      formula

latex_forms gives None for a formula whose braces don't balance; the
unpacker uses what it gives only for a formula Pandoc can't read as
written, and reports one it can't read either way.

And one form texmath reads otherwise than MathJax, which mathjax_rows
writes as MathJax reads it, for every formula: a line break just before
an environment's end (a \\ \end{array}), which MathJax 3.2.2 ends no
row at, where texmath reads one more row, empty; LaTeX's array makes no
row of it either, amsmath's gathered an empty one (measured with
LuaLaTeX, TeX Live 2026). 50 of the 17,871 formulas end an array (41) or
gathered (9) so.

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

SWITCHES = {"rm": "mathrm", "bf": "mathbf", "it": "mathit",
            "sf": "mathsf", "tt": "mathtt", "cal": "mathcal"}
# Commands whose argument is text: a switch, a $, or a line break in it
# is left as it is.
TEXT_ARGUMENTS = {"text", "textrm", "textbf", "textit", "textsf", "texttt",
                  "textnormal", "textup", "mbox", "hbox", "operatorname"}
# What may stand in a word set as \text: a control symbol that means a
# space or a character in text too.
TEXT_SYMBOLS = set(" ,;:!%$&#{}_")
FRACTIONS = {"over": "frac", "choose": "binom"}
# A character TeX gives a meaning, as \unicode gives it: its control
# symbol. ^ and ~ have none in math, and \backslash is U+2216, set minus,
# to texmath as to MathJax, where \unicode{x5C} is a backslash: those
# three are left as written.
ESCAPED = {"%": "\\%", "$": "\\$", "#": "\\#", "&": "\\&", "_": "\\_",
           "{": "\\{", "}": "\\}"}
# Under \rm, a word: two letters running.
_WORD = re.compile(r"[^\W\d_]{2}")
# Control words that take no argument and stand between words under
# \rm as an operator, a relation, or a space does, so that the words
# around them are text: "{\rm True \wedge False}" is
# \text{True}\wedge\text{False}, as Contemporary Mathematics' truth
# tables write theirs (CM-C02-M3-Q002).
BETWEEN_WORDS = {"wedge", "vee", "land", "lor", "neg", "lnot", "times", "cdot",
                 "div", "pm", "mp", "le", "leq", "ge", "geq", "ne", "neq",
                 "approx", "equiv", "sim", "cong", "propto", "to",
                 "rightarrow", "leftarrow", "leftrightarrow", "Rightarrow",
                 "Leftarrow", "Leftrightarrow", "implies", "iff", "mapsto",
                 "cup", "cap", "in", "notin", "ni", "subset", "subseteq",
                 "supset", "supseteq", "setminus", "oplus", "otimes", "circ",
                 "ast", "star", "bullet", "mid", "parallel", "perp", "colon",
                 "ldots", "cdots", "dots", "quad", "qquad"}
MU = {"mu": 1.0, "pt": 1.8, "em": 18.0}

_TOKEN = re.compile(r"\\([A-Za-z]+)(\s*)|\\(.)|([{}])|(.)", re.S)
_CDATA = re.compile(r"\s*\\?%?\s*<!\[CDATA\[(.*?)\\?%?\s*\]\]>\s*\Z", re.S)
# What XML doesn't allow, which can't stand in a page: a control
# character but a tab or a line's end, half a surrogate pair, U+FFFE, and
# U+FFFF (exercises._NOT_XML).
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_KERN = re.compile(r"\s*(-?(?:\d+\.?\d*|\.\d+))\s*(mu|pt|em)")


# A token is (kind, name, written): a control word ("word", "rm",
# "\\rm "), a control symbol ("symbol", ",", "\\,"), or a character
# ("char", "x", "x"); a group is ("group", [tokens and groups]).

def _tokens(tex):
    out = []
    for m in _TOKEN.finditer(tex):
        word, _space, symbol, brace, char = m.groups()
        if word is not None:
            out.append(("word", word, m.group(0)))
        elif symbol is not None:
            out.append(("symbol", symbol, m.group(0)))
        elif brace is not None:
            out.append(("brace", brace, brace))
        else:
            out.append(("char", char, char))
    return out


def _tree(tokens):
    stack = [[]]
    for token in tokens:
        if token[0] == "brace" and token[1] == "{":
            stack.append([])
        elif token[0] == "brace":
            if len(stack) == 1:
                return None
            inner = stack.pop()
            stack[-1].append(("group", inner))
        else:
            stack[-1].append(token)
    return stack[0] if len(stack) == 1 else None


def _write(items):
    return "".join("{" + _write(item[1]) + "}" if item[0] == "group"
                   else item[2] for item in items)


def _plain(items):
    """The tokens of items flattened, groups opened and spaces dropped,
    or None where anything but text, or an operator between words, stands
    among them."""
    out = []
    for item in items:
        if item[0] == "group":
            inner = _plain(item[1])
            if inner is None:
                return None
            out += inner
        elif item[0] == "char":
            if item[1] in "^_&~":
                return None
            if not item[1].isspace():
                out.append(item)
        elif (item[0] == "symbol" and item[1] in TEXT_SYMBOLS
              or item[0] == "word" and item[1] in BETWEEN_WORDS):
            out.append(item)
        else:
            return None
    return out


def _switched(name, rest):
    """A font switch and the rest of its group, as LaTeX's commands."""
    if name == "rm":
        tokens = _plain(rest)
        if tokens is not None and _WORD.search(_spelled(tokens)):
            return _words(tokens)
    command = SWITCHES[name]
    return [("word", command, "\\" + command), ("group", rest)]


def _words(tokens):
    """A \\rm's reach, flattened, as tokens: each run of what text holds
    \\text where it holds a word, \\mathrm where it holds a letter, as it
    is otherwise; what stands between runs as it is."""
    out, run = [], []
    for token in tokens + [None]:
        if token is not None and _in_text(token):
            run.append(token)
            continue
        if run:
            spelled = _spelled(run)
            if _WORD.search(spelled):
                out += [("word", "text", "\\text"), ("group", run)]
            elif re.search(r"[^\W\d_]", spelled):
                out += [("word", "mathrm", "\\mathrm"), ("group", run)]
            else:
                out += run
            run = []
        if token is not None:
            out.append(token)
    return out


def _in_text(token):
    """Whether a token is of what a word set as \\text holds: a letter, a
    digit, a period, a comma, or an apostrophe, or a control symbol for
    a space or a character text has (not a brace, which is math's)."""
    if token[0] == "char":
        return bool(re.match(r"[^\W_]|[.,']\Z", token[1]))
    return token[0] == "symbol" and token[1] in TEXT_SYMBOLS and token[1] not in "{}"


def _spelled(tokens):
    """Tokens as text for finding a word in: an operator between words
    parts them."""
    return "".join("\0" if token[0] == "word" else token[2] for token in tokens)


def _characters(text):
    return [("char", c, c) for c in text]


def _fix(items, in_text=False):
    out = []
    i = 0
    while i < len(items):
        item = items[i]
        kind, name = item[0], item[1]
        if kind == "group":
            before = out[-1] if out else None
            text = in_text or (before is not None and before[0] == "word"
                               and before[1] in TEXT_ARGUMENTS)
            out.append(("group", _fix(item[1], text)))
        elif kind == "word" and name in SWITCHES and not in_text:
            end = _scope_end(items, i + 1)
            out += _switched(name, _fix(items[i + 1:end], in_text))
            i = end
            continue
        elif kind == "word" and name == "unicode":
            char, after = _unicode(items, i + 1)
            if char is None:
                out.append(item)
            else:
                out.append(_character(char, out[-1] if out else None))
                i = after
                continue
        elif kind == "word" and name in ("mkern", "kern"):
            space, after = _kern(items, i + 1)
            if space is None:
                out.append(item)
            else:
                out += space
                i = after
                continue
        elif kind == "word" and name == "hfill":
            pass
        elif kind == "char" and (name == "%" or name == "$" and not in_text):
            out.append(("symbol", name, "\\" + name))
        else:
            out.append(item)
        i += 1
    return out


def _scope_end(items, i):
    """Where a font switch's reach ends: its group's end, or the end of
    an alignment's cell or row, an environment, or a \\left's group, not
    of one that opens inside the reach."""
    depth = 0
    while i < len(items):
        depth, ends = _reach_step(items[i], depth)
        if ends:
            return i
        i += 1
    return i


def _reach_step(item, depth):
    """(depth after item, whether item ends a reach): a \\left or a
    \\begin opens a level, a \\right or an \\end closes one, and at the
    reach's own level a \\right, an \\end, an &, a \\\\, or a \\cr ends
    it."""
    if item[0] == "word" and item[1] in ("left", "begin"):
        return depth + 1, False
    if depth and item[0] == "word" and item[1] in ("right", "end"):
        return depth - 1, False
    return depth, not depth and _ends_reach(item)


def _unicode(items, i):
    """\\unicode's character and where its arguments end, or (None, i)."""
    if i < len(items) and items[i] == ("char", "[", "["):
        while i < len(items) and items[i] != ("char", "]", "]"):
            i += 1
        i += 1
    if i >= len(items) or items[i][0] != "group":
        return None, i
    code = _write(items[i][1]).strip()
    try:
        number = int(code[1:], 16) if code[:1] in "xX" else int(code)
        char = chr(number)
    except (ValueError, OverflowError):
        return None, i
    if char in "\\^~" or _NOT_XML.match(char):
        return None, i
    return char, i + 1


def _character(char, before):
    """\\unicode's character as a token: its control symbol where TeX
    gives the character a meaning, and set apart by a space from a
    control word just before it, which would otherwise take a letter in
    as its own (texmath's reader takes any Unicode letter)."""
    if char in ESCAPED:
        return ("symbol", char, ESCAPED[char])
    if before is not None and before[0] == "word" and before[2][-1:].isalpha():
        return ("char", char, " " + char)
    return ("char", char, char)


def _kern(items, i):
    """\\mkern's or \\kern's dimension as \\mspace, and where it ends, or
    (None, i)."""
    written = ""
    j = i
    while j < len(items) and items[j][0] == "char" and len(written) < 12:
        written += items[j][1]
        j += 1
        m = _KERN.match(written)
        if m and m.end() == len(written):
            mu = max(1, round(abs(float(m.group(1))) * MU[m.group(2)]))
            if m.group(1).startswith("-"):
                mu = -mu
            return ([("word", "mspace", "\\mspace"),
                     ("group", [("char", c, c) for c in f"{mu}mu"])], j)
    return None, i


def _fractions(items):
    """{a \\over b} as \\frac{a}{b}, in every group; a font switch whose
    reach the \\over stands in, which doesn't end it, switches b too."""
    out = [("group", _fractions(item[1])) if item[0] == "group" else item
           for item in items]
    for k, item in enumerate(out):
        if item[0] == "word" and item[1] in FRACTIONS:
            command = FRACTIONS[item[1]]
            numerator, denominator = out[:k], out[k + 1:]
            switch = _switch_reaching_end(numerator)
            if switch is not None:
                denominator = [switch] + denominator
            return [("word", command, "\\" + command),
                    ("group", numerator), ("group", denominator)]
    return out


def _switch_reaching_end(items):
    """The font switch of items whose reach runs to their end, or None."""
    found, depth = None, 0
    for item in items:
        if not depth and item[0] == "word" and item[1] in SWITCHES:
            found = item
            continue
        depth, ends = _reach_step(item, depth)
        if ends:
            found = None
    return found


def _ends_reach(item):
    """Whether item ends a font switch's reach short of its group's end:
    an alignment's cell or row, an environment, or a \\left's group."""
    return (item[0] == "char" and item[1] == "&"
            or item[0] == "symbol" and item[1] == "\\"
            or item[0] == "word" and item[1] in ("end", "right", "cr"))


def _rows_aligned_left(items):
    """An array of one column each row of which ends in \\hfill, as
    MathType writes rows aligned left, and as MathJax aligns them: its
    column aligned left (_fix then leaves each \\hfill out), in every
    group. MathJax 3.2.2 aligns an array's cell that ends in \\hfill left
    (ArrayItem.EndEntry), and not gathered's (EqnArrayItem's has no
    \\hfill), which is left centered."""
    out = [("group", _rows_aligned_left(item[1])) if item[0] == "group"
           else item for item in items]
    for i in range(len(out)):
        if _environment(out, i) != "array":
            continue
        spec = _next(out, i + 2)
        end = _environment_end(out, i)
        if spec is None or out[spec][0] != "group" or end is None:
            continue
        rows = _rows(out[spec + 1:end])
        if rows and all(len(row) == 1 and _ends_in_hfill(row[0])
                        for row in rows):
            out[spec] = ("group", _characters("l"))
    return out


def _environment(items, i):
    """The name of the environment items[i] begins, or None."""
    if (i + 1 < len(items) and items[i][0] == "word"
            and items[i][1] == "begin" and items[i + 1][0] == "group"):
        return _write(items[i + 1][1]).strip()
    return None


def _environment_end(items, i):
    """Where the environment begun at items[i] ends: its \\end's index."""
    depth = 0
    for j in range(i, len(items) - 1):
        if items[j][0] == "word" and items[j][1] == "begin":
            depth += 1
        elif items[j][0] == "word" and items[j][1] == "end":
            depth -= 1
            if depth == 0:
                return j if items[j + 1][0] == "group" else None
    return None


def _next(items, i):
    """The index of the first item from i on that isn't a space, or None."""
    while i < len(items) and items[i][0] == "char" and items[i][1].isspace():
        i += 1
    return i if i < len(items) else None


def _rows(items):
    """An environment's body as rows of cells, each a list of items,
    split at its own \\\\ and &, not an environment's inside it; a row of
    nothing but spaces (a break at the end) left out."""
    rows, cells, cell, depth = [], [], [], 0
    for item in items:
        if item[0] == "word" and item[1] == "begin":
            depth += 1
        elif item[0] == "word" and item[1] == "end":
            depth -= 1
        if depth == 0 and item[0] == "symbol" and item[1] == "\\":
            rows.append(cells + [cell])
            cells, cell = [], []
        elif depth == 0 and item[0] == "char" and item[1] == "&":
            cells.append(cell)
            cell = []
        else:
            cell.append(item)
    rows.append(cells + [cell])
    return [row for row in rows
            if any(not (i[0] == "char" and i[1].isspace())
                   for cell in row for i in cell)]


def _ends_in_hfill(cell):
    """Whether a cell's last item but spaces is \\hfill."""
    kept = [i for i in cell if not (i[0] == "char" and i[1].isspace())]
    return bool(kept) and kept[-1][0] == "word" and kept[-1][1] == "hfill"


def _breaks_outside(items):
    """Whether a \\\\ stands outside every environment and group."""
    depth = 0
    for item in items:
        if item[0] == "word" and item[1] == "begin":
            depth += 1
        elif item[0] == "word" and item[1] == "end":
            depth -= 1
        elif item[0] == "symbol" and item[1] == "\\" and depth == 0:
            return True
    return False


def mathjax_rows(tex):
    """tex without a line break just before an environment's end, which
    MathJax ends no row at and texmath reads as an empty row; tex as it is
    where its braces don't balance."""
    tree = _tree(_tokens(tex))
    return tex if tree is None else _write(_closing_breaks_dropped(tree))


def _closing_breaks_dropped(items):
    """items without the \\\\ that only spaces part from an \\end, in
    every group: the one row it would begin (a break before it ends a
    row, empty, as it does in MathJax)."""
    out = []
    for item in items:
        if item[0] == "group":
            item = ("group", _closing_breaks_dropped(item[1]))
        elif item[0] == "word" and item[1] == "end":
            k = len(out)
            while k and out[k - 1][0] == "char" and out[k - 1][1].isspace():
                k -= 1
            if k and out[k - 1][0] == "symbol" and out[k - 1][1] == "\\":
                del out[k - 1:]
        out.append(item)
    return out


def latex_forms(tex):
    """tex with MathJax's and plain TeX's forms written as LaTeX's, or
    None where its braces don't balance."""
    m = _CDATA.match(tex)
    if m:
        tex = m.group(1)
    tree = _tree(_tokens(tex))
    if tree is None:
        return None
    tree = _fix(_rows_aligned_left(_fractions(_closing_breaks_dropped(tree))))
    out = _write(tree).strip()
    if _breaks_outside(tree):
        out = re.sub(r"(\\\\\s*)+\Z", "", out)
        out = "\\begin{array}{l}" + out + "\\end{array}"
    return out
