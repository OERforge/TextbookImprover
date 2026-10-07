"""
latexsource.py -- a LaTeX book read as the pipeline's source.

A LaTeX book is a master file, the one with \\documentclass and
\\begin{document}, that \\include-s its chapters and \\input-s the rest.
Pandoc's reader takes the whole book through the master, so section
numbers, cross-references, and the preamble's macros come out as LaTeX
would have them, and the result is cut into pages where each \\include-d
file begins. A page is named after its file, as every other source's is.

Before Pandoc reads it, the book is copied and the copy put right where
Pandoc's reader (3.12) can't take it, each read from its source and
measured (PANDOC-NOTES.md, "The LaTeX reader"):

- ifthen's booleans become etoolbox's toggles, which the reader
  evaluates; it drops \\ifthenelse, both branches with it (#11008).
- \\input written without braces, TeX's own form, is braced; the reader
  stops on it.
- \\centerline is defined as a center environment; the reader takes its
  argument as inline text and stops on a table inside it.
- \\cline{2-3} and \\cmidrule{2-3} become whole rules; the reader leaves
  their column range in the next cell as text.
- a table's header declaration for LaTeX's tagging,
  \\tagpdfsetup{table/header-rows={1}} or table/header-columns={1} just
  before it, becomes the pipeline's own (latex-source.lua sets it on the
  table); the reader drops \\tagpdfsetup.
- a drawing (a picture, tikzpicture, or pspicture environment), which
  the reader drops whole, is rendered by LaTeX with the book's own
  preamble, one page each, and each page made an SVG the copy includes
  in its place.
- an \\includegraphics marked artifact is marked for the filter, which
  takes it as decorative; the reader ignores the key.
- an \\includegraphics of a PDF or EPS, which no browser shows, or of a
  name without its extension, which the reader resolves in the copy's
  directory and so never finds, is made an SVG from the file graphicx
  would take.

The author's files are never written. What the copy changed is counted
and the run says so.

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

import hashlib
import json
import os
import re
import shutil
import subprocess

# A page marker, a paragraph of its own the reader keeps as text, put
# before each \include in the copy and cut at afterwards.
MARKER = "TextbookImproverPageMarker"
MARKER_LINE = MARKER + "%04d"
MARKER_TEXT = re.compile(r"^" + MARKER + r"(\d{4})$")
ARTIFACT = "TextbookImproverArtifact"
DRAWINGS = ("picture", "tikzpicture", "pspicture")
VERBATIM = ("verbatim", "verbatim*", "Verbatim", "lstlisting", "minted",
            "comment")
DIVISIONS = {"frontmatter": "front", "mainmatter": "main",
             "appendix": "appendix", "backmatter": "back"}
# babel's language names for the languages a textbook is most often in;
# anything else is left for project.yaml.
BABEL = {"english": "en", "american": "en-US", "USenglish": "en-US",
         "british": "en-GB", "UKenglish": "en-GB", "canadian": "en-CA",
         "australian": "en-AU", "french": "fr", "francais": "fr",
         "german": "de", "ngerman": "de", "spanish": "es",
         "italian": "it", "portuguese": "pt", "brazilian": "pt-BR",
         "dutch": "nl", "polish": "pl", "russian": "ru", "greek": "el",
         "catalan": "ca", "swedish": "sv", "danish": "da",
         "norwegian": "no", "finnish": "fi", "czech": "cs",
         "turkish": "tr"}
RENDERED = "rendered"


# --------------------------------------------------------------------------
# reading the text: what is code, and what is comment or verbatim
# --------------------------------------------------------------------------

def skip_spans(text):
    """Spans of text no rewrite may touch, as (start, end) pairs, in
    order: comments, verbatim environments, and \\verb."""
    spans = []
    i, n = 0, len(text)
    verb_env = re.compile(r"\\begin\s*\{(" + "|".join(
        re.escape(v) for v in VERBATIM) + r")\}")
    while i < n:
        c = text[i]
        if c == "\\":
            m = verb_env.match(text, i)
            if m:
                end = text.find("\\end{" + m.group(1) + "}", m.end())
                end = n if end < 0 else end + len("\\end{" + m.group(1) + "}")
                spans.append((i, end))
                i = end
                continue
            m = re.compile(r"\\verb\*?([^a-zA-Z\s*])").match(text, i)
            if m:
                end = text.find(m.group(1), m.end())
                end = n if end < 0 else end + 1
                spans.append((i, end))
                i = end
                continue
            i += 2
            continue
        if c == "%":
            end = text.find("\n", i)
            end = n if end < 0 else end
            spans.append((i, end))
            i = end
            continue
        i += 1
    return spans


def in_spans(pos, spans):
    for start, end in spans:
        if start <= pos < end:
            return True
        if start > pos:
            return False
    return False


def code_matches(pattern, text, spans=None):
    """pattern's matches that begin in code, not in a comment or verbatim."""
    spans = skip_spans(text) if spans is None else spans
    return [m for m in pattern.finditer(text) if not in_spans(m.start(), spans)]


def matching_brace(text, start):
    """The index just past the group that opens at text[start] == '{'."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


# --------------------------------------------------------------------------
# the master and the files it reaches
# --------------------------------------------------------------------------

DOCUMENTCLASS = re.compile(r"\\documentclass\b")
BEGIN_DOCUMENT = re.compile(r"\\begin\s*\{document\}")
END_DOCUMENT = re.compile(r"\\end\s*\{document\}")
INCLUDE = re.compile(r"\\include\s*\{\s*([^}]+?)\s*\}")
INPUT = re.compile(r"\\(input|include|subfile)\s*\{\s*([^}]+?)\s*\}"
                   r"|\\input\s+([^\s{}%\\]+)")
UNBRACED_INPUT = re.compile(r"\\input\s+([^\s{}%\\]+)")


def read_text(path):
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        return fh.read()


def write_text(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(text)


def is_master(text):
    spans = skip_spans(text)
    return bool(code_matches(DOCUMENTCLASS, text, spans)
                and code_matches(BEGIN_DOCUMENT, text, spans))


def masters(base):
    """The .tex files directly in base that are whole documents."""
    found = []
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        if name.endswith(".tex") and os.path.isfile(path) \
                and is_master(read_text(path)):
            found.append(name)
    return found


INCLUDEPDF = re.compile(r"\\includepdf\s*(?:\[[^]]*\])?\s*\{\s*([^}]+?)\s*\}")


def binder(base, master):
    """The PDFs a master only gathers with \\includepdf, as the names it
    gives them, when it reaches no other LaTeX file: a binder of documents
    built on their own (FINC 308's "Combined" file, a PDF per topic), with
    nothing of its own to convert. [] for any other master."""
    text = read_text(os.path.join(base, master))
    if not is_master(text):
        return []
    found = [m.group(1) for m in code_matches(INCLUDEPDF, split_master(text)[1])]
    if not found or len(reached(base, master)[0]) > 1:
        return []
    return found


def binder_sources(base, pdfs, skip=()):
    """(found, missing): the whole LaTeX document named as each PDF a
    binder gathers is, anywhere in the book's directory but the folders in
    skip (absolute paths, a run's output), as paths relative to base in
    the binder's order; and the PDFs with none."""
    candidates = {}
    skip = {os.path.abspath(s) for s in skip}
    for folder, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != RENDERED
                         and os.path.abspath(os.path.join(folder, d)) not in skip)
        for name in sorted(names):
            if name.endswith(".tex"):
                candidates.setdefault(name[:-4], []).append(
                    os.path.relpath(os.path.join(folder, name), base))
    found, missing = [], []
    for pdf in pdfs:
        stem = os.path.splitext(os.path.basename(pdf.strip().strip('"')))[0]
        paths = [p for p in candidates.get(stem, [])
                 if is_master(read_text(os.path.join(base, p)))]
        if not paths:
            missing.append(pdf)
        elif paths[0] not in found:
            found.append(paths[0])
    return found, missing


def resolve(base, name, folder=""):
    """A name \\input or \\include gives, as a path relative to base, or
    None when no such file is there. TeX tries the name as written and
    with .tex added, from the folder it runs in: a master's own (folder,
    relative to base, for one below the book's directory), then the
    book's."""
    name = name.strip().strip('"')
    for where in dict.fromkeys((folder, "")):
        for candidate in (name, name + ".tex"):
            path = os.path.normpath(os.path.join(where, candidate))
            if os.path.isfile(os.path.join(base, path)):
                return path
    return None


def reached(base, master):
    """(files, missing): every .tex file the master reaches through
    \\input, \\include, and \\subfile, in the order first reached, and
    the names it gives that aren't there."""
    files, missing, queue = [], [], [master]
    folder = os.path.dirname(master)
    while queue:
        name = queue.pop(0)
        if name in files:
            continue
        files.append(name)
        text = read_text(os.path.join(base, name))
        for m in code_matches(INPUT, text):
            target = m.group(2) or m.group(3)
            path = resolve(base, target, folder)
            if path is None:
                if target not in missing:
                    missing.append(target)
            elif path not in files and path not in queue:
                queue.append(path)
    return files, missing


def inputs_from(base, text, folder, counter):
    """text with each \\input and \\include a master in folder reaches
    from there named from the book's directory, where the reader runs."""
    spans = skip_spans(text)
    out, last = [], 0
    for m in INPUT.finditer(text):
        if in_spans(m.start(), spans) or not m.group(2):
            continue
        target = m.group(2)
        path = resolve(base, target, folder)
        if path is None or path in (os.path.normpath(target),
                                    os.path.normpath(target + ".tex")):
            continue
        start, end = m.span(2)
        out.append(text[last:start] + path.replace(os.sep, "/"))
        last = end
        counter["inputs_from_folder"] = counter.get("inputs_from_folder", 0) + 1
    out.append(text[last:])
    return "".join(out)


def split_master(text):
    """(preamble, body, rest): the master's text before
    \\begin{document}, between it and \\end{document}, and after."""
    spans = skip_spans(text)
    begin = code_matches(BEGIN_DOCUMENT, text, spans)[0]
    ends = [m for m in code_matches(END_DOCUMENT, text, spans)
            if m.start() > begin.end()]
    end = ends[0].start() if ends else len(text)
    return text[:begin.end()], text[begin.end():end], text[end:]


def book_outline(body):
    """The master's body as the book's order: [(stem-path, role)], each
    \\include-d file with the role the division commands before it give
    it, and the role of what precedes the first \\include."""
    spans = skip_spans(body)
    events = []
    for m in code_matches(re.compile(r"\\(frontmatter|mainmatter|appendix|"
                                     r"backmatter)\b"), body, spans):
        events.append((m.start(), "division", DIVISIONS[m.group(1)]))
    for m in code_matches(INCLUDE, body, spans):
        events.append((m.start(), "include", m.group(1)))
    events.sort()
    role, front_role, order = "main", None, []
    for _, kind, value in events:
        if kind == "division":
            role = value
        else:
            if front_role is None:
                front_role = role
            order.append((value, role))
    if not order:
        # A master that \include-s nothing is one page, whose role is the
        # one it opens in: a division after its first words (FINC 308's
        # \appendix before its practice problems) is a part of the page.
        first = next((at for at, kind, _ in events if kind == "division"), None)
        text = re.sub(r"%[^\n]*", "", body[:first]) if first is not None else ""
        opening = first is not None and not re.sub(
            r"\\(?:maketitle|tableofcontents|clearpage|newpage)\b|\s", "", text)
        return order, events[0][2] if opening else "main"
    return order, front_role or role


def preamble_language(preamble):
    """The book's language, as the preamble declares it: \\DocumentMetadata's
    lang, polyglossia's main language, or babel's main (last) language."""
    m = re.search(r"\\DocumentMetadata\s*\{[^}]*?\blang\s*=\s*([A-Za-z-]+)",
                  preamble)
    if m:
        return m.group(1)
    m = re.search(r"\\set(?:default|main)language\s*(?:\[[^]]*\])?\s*\{(\w+)\}",
                  preamble)
    if m and m.group(1) in BABEL:
        return BABEL[m.group(1)]
    for m in re.finditer(r"\\usepackage\s*\[([^]]*)\]\s*\{babel\}", preamble):
        options = [o.strip() for o in m.group(1).split(",") if o.strip()]
        options = [o.split("=")[-1] for o in options]
        known = [o for o in options if o in BABEL]
        if known:
            return BABEL[known[-1]]
    return ""


# --------------------------------------------------------------------------
# what the copy changes
# --------------------------------------------------------------------------

BOOLEAN_IF = re.compile(r"\\ifthenelse\s*\{\s*\\boolean\s*\{\s*([A-Za-z@]+)"
                        r"\s*\}\s*\}")
BOOLEAN_NEW = re.compile(r"\\newboolean\s*\{\s*([A-Za-z@]+)\s*\}")
BOOLEAN_SET = re.compile(r"\\setboolean\s*\{\s*([A-Za-z@]+)\s*\}\s*"
                         r"\{\s*(true|false)\s*\}")
ANY_IFTHENELSE = re.compile(r"\\ifthenelse\b")
PARTIAL_RULE = re.compile(r"\\(cline|cmidrule)\s*(?:\([^)]*\))?\s*\{[^}]*\}")
GRAPHICS = re.compile(r"\\includegraphics\s*(\*)?\s*(\[([^]]*)\])?\s*\{")


def substitute(pattern, text, replace, counter, key):
    """Each match of pattern in code replaced, counted under key."""
    spans = skip_spans(text)
    out, last = [], 0
    for m in pattern.finditer(text):
        if in_spans(m.start(), spans):
            continue
        out.append(text[last:m.start()])
        out.append(replace(m))
        last = m.end()
        counter[key] = counter.get(key, 0) + 1
    out.append(text[last:])
    return "".join(out)


HEADER_SETUP = re.compile(r"(?:\\ifdefined\s*\\tagpdfsetup\s*)?"
                          r"\\tagpdfsetup\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}"
                          r"((?:\s|%[^\n]*\n|\\fi\b|\{\\def\\LTcaptype\{none\})*)"
                          r"\\begin\s*\{(tabular\*?|tabularx|"
                          r"longtable|array)\}")
DECLARATIONS = {(True, False): "FirstRow", (False, True): "FirstColumn",
                (True, True): "Both"}


def one_row_head(body):
    """Whether a longtable's head, the rows before \\endhead or
    \\endfirsthead, is one row."""
    head = re.search(r"\\end(?:first)?head\b", body)
    return bool(head) and len(re.findall(
        r"\\\\", re.sub(r"%[^\n]*", "", body[:head.start()]))) == 1


def longtable_heads(text, counter):
    """A longtable whose head is one row, the rows before \\endhead or
    \\endfirsthead, wrapped as a table declared to have a header row: the
    head is the author's own declaration, which Pandoc's LaTeX writer makes
    for a table with a header and the census would otherwise guess at. One
    the author declared for tagging already is left as declared."""
    spans = skip_spans(text)
    out, last = [], 0
    for m in re.finditer(r"\\begin\s*\{longtable\}", text):
        if in_spans(m.start(), spans) or m.start() < last:
            continue
        end = environment_end(text, "longtable", m.start())
        if end < 0:
            continue
        body = text[m.start():end]
        # The head repeated on each later page, between \\endfirsthead and
        # \\endhead, which the reader takes for a row of the body (it
        # reads both commands as rules, Readers/LaTeX/Table.hs).
        repeated = re.search(r"\\endfirsthead\b(.*?)\\endhead\b", body, re.S)
        if repeated:
            body = body[:repeated.start(1)] + body[repeated.end(1) + len("\\endhead"):]
            counter["repeated_head"] = counter.get("repeated_head", 0) + 1
        head = re.search(r"\\end(?:first)?head\b", body)
        declared = re.search(r"\\begin\{TextbookImproverHeaders\w+\}\s*$", text[:m.start()])
        rows = len(re.findall(r"\\\\", re.sub(r"%[^\n]*", "", body[:head.start()]))) \
            if head else 0
        if head and rows == 1 and not declared:
            body = ("\\begin{TextbookImproverHeadersFirstRow}" + body
                    + "\\end{TextbookImproverHeadersFirstRow}")
            counter["longtable_head"] = counter.get("longtable_head", 0) + 1
        elif head and rows > 1 and not declared:
            counter["longtable_head_rows"] = counter.get("longtable_head_rows", 0) + 1
        out.append(text[last:m.start()] + body)
        last = end
    out.append(text[last:])
    return "".join(out)


# A \\multicolumn whose column spec holds @{...}, as Pandoc's writer gives
# the last cell of a row that spans columns, to match the table's edges:
# the reader can't parse it, and the whole table is lost (read as a div of
# text). The edge spacing goes; the span stays.
MULTICOLUMN_EDGE = re.compile(r"(\\multicolumn\s*\{\d+\}\s*\{)([^{}]*@\{[^{}]*\}[^{}]*)\}")


def stacked_lines(text, counter):
    """\\vtop{\\hbox{\\strut A}\\hbox{\\strut B}}, which Pandoc's LaTeX writer
    gives a table cell's line breaks, as A\\newline B: the reader drops
    the boxes and every line in them (formulas too)."""
    spans = skip_spans(text)
    pattern = re.compile(r"\\vtop\s*\{")
    for m in reversed(list(pattern.finditer(text))):
        if in_spans(m.start(), spans):
            continue
        close = matching_brace(text, m.end() - 1)
        if close < 0:
            continue
        inner, lines, at = text[m.end():close - 1], [], 0
        while True:
            box = re.compile(r"\s*\\hbox\s*\{").match(inner, at)
            if not box:
                break
            end = matching_brace(inner, box.end() - 1)
            if end < 0:
                break
            lines.append(re.sub(r"^\s*\\strut\b\s*", "", inner[box.end():end - 1]))
            at = end
        if not lines or inner[at:].strip():
            continue
        text = text[:m.start()] + " \\newline ".join(lines) + text[close:]
        counter["stacked_lines"] = counter.get("stacked_lines", 0) + 1
    return text


def minipage_breaks(text, counter):
    """\\\\ in a minipage, not in an environment inside it, as \\newline,
    which in a minipage it is: Pandoc's LaTeX writer breaks a table cell's
    lines that way, and in a cell the reader takes \\\\ for the row's end."""
    spans = skip_spans(text)
    edits = []
    for m in re.finditer(r"\\begin\s*\{minipage\}", text):
        if in_spans(m.start(), spans):
            continue
        end = environment_end(text, "minipage", m.start())
        if end < 0:
            continue
        depth = 0
        for tok in re.finditer(r"\\begin\s*\{[^}]*\}|\\end\s*\{[^}]*\}|\\\\(?!\[)",
                               text[m.end():end - len("\\end{minipage}")]):
            word = tok.group(0)
            if word.startswith("\\begin"):
                depth += 1
            elif word.startswith("\\end"):
                depth -= 1
            elif depth == 0:
                at = m.end() + tok.start()
                if not in_spans(at, spans):
                    edits.append(at)
    for at in sorted(edits, reverse=True):
        text = text[:at] + "\\newline " + text[at + 2:]
    if edits:
        counter["minipage_breaks"] = counter.get("minipage_breaks", 0) + len(edits)
    return text


def drop(text, command, counter, key):
    """\\command{...} taken out, in code: the PDF target's own commands
    for a link's /Contents, which a reader that doesn't know
    \\NewDocumentCommand would print as text; the link holds its text."""
    spans = skip_spans(text)
    pattern = re.compile(r"\\%s(?![A-Za-z@])\s*\{" % re.escape(command))
    while True:
        found = [m for m in pattern.finditer(text) if not in_spans(m.start(), spans)]
        if not found:
            return text
        m = found[-1]
        close = matching_brace(text, m.end() - 1)
        if close < 0:
            return text
        text = text[:m.start()] + text[close:]
        counter[key] = counter.get(key, 0) + 1
        spans = skip_spans(text)


def unwrap(text, command, counter, key):
    """\\command{X} as X, in code: for a wrapper the reader doesn't know
    and drops with what it holds, as Pandoc's LaTeX writer's
    \\pandocbounded around an image is."""
    spans = skip_spans(text)
    pattern = re.compile(r"\\%s\s*\{" % re.escape(command))
    while True:
        found = [m for m in pattern.finditer(text) if not in_spans(m.start(), spans)]
        if not found:
            return text
        m = found[-1]
        close = matching_brace(text, m.end() - 1)
        if close < 0:
            return text
        text = text[:m.start()] + text[m.end():close - 1] + text[close:]
        counter[key] = counter.get(key, 0) + 1
        spans = skip_spans(text)


def declare_headers(text, counter):
    """A table preceded by its tagging's header declaration, wrapped in an
    environment the reader keeps as a div naming the declaration. Only a
    first row, a first column, or both: what the pipeline's declarations
    say (table-headers.csv's first-row, first-column, both)."""
    spans = skip_spans(text)
    out, last = [], 0
    for m in HEADER_SETUP.finditer(text):
        if in_spans(m.start(), spans) or m.start() < last:
            continue
        keys = m.group(1)
        rows = re.search(r"table/header-rows\s*=\s*\{?\s*([\d,\s]*)\}?", keys)
        cols = re.search(r"table/header-columns\s*=\s*\{?\s*([\d,\s]*)\}?",
                         keys)
        begin = text.rfind("\\begin", m.start(), m.start(3))
        end = environment_end(text, m.group(3), begin)
        if end < 0:
            continue
        # A longtable's head of one row is a header row of its own; the
        # declaration may add the column (the PDF target writes only that).
        head_row = m.group(3) == "longtable" and one_row_head(text[begin:end])
        key = (bool(rows and rows.group(1).strip() == "1") or head_row,
               bool(cols and cols.group(1).strip() == "1"))
        if key not in DECLARATIONS:
            if (rows and rows.group(1).strip()) or (cols and cols.group(1).strip()):
                counter["header_other"] = counter.get("header_other", 0) + 1
            continue
        name = "TextbookImproverHeaders" + DECLARATIONS[key]
        out.append(text[last:m.start()] + re.sub(r"\\fi\b", "", m.group(2))
                   + "\\begin{%s}" % name
                   + text[begin:end] + "\\end{%s}" % name)
        last = end
        counter["header_declared"] = counter.get("header_declared", 0) + 1
    out.append(text[last:])
    return "".join(out)


RULE_ANY = re.compile(r"\\rule\s*(?:\[[^]]*\])?\s*\{([^}]*)\}\s*\{([^}]*)\}")


def invisible_rule(m):
    """A rule with no height is a space, and one with no width a strut;
    the reader takes any rule with a width for a horizontal rule, a line
    across the page (rule, Readers/LaTeX.hs)."""
    width, height = points(m.group(1)), points(m.group(2))
    if width == 0:
        return ""
    if height == 0 and width is not None:
        return "\\hspace{%s}" % m.group(1).strip()
    return m.group(0)


def repair_text(text, counter):
    """The rewrites every file of the copy gets: booleans as toggles,
    \\input braced, artifact images marked."""
    text = substitute(BOOLEAN_IF, text, lambda m: "\\iftoggle{%s}" % m.group(1),
                      counter, "ifthenelse")
    text = substitute(BOOLEAN_NEW, text, lambda m: "\\newtoggle{%s}" % m.group(1),
                      counter, "newboolean")
    text = substitute(BOOLEAN_SET, text, lambda m: "\\toggle%s{%s}" % (
        m.group(2), m.group(1)), counter, "setboolean")
    counter["ifthenelse_left"] = counter.get("ifthenelse_left", 0) + len(
        code_matches(ANY_IFTHENELSE, text))
    text = substitute(UNBRACED_INPUT, text,
                      lambda m: "\\input{%s}" % m.group(1), counter,
                      "unbraced_input")
    # The reader takes \cline and \cmidrule as rules but leaves their
    # column range ({2-2}) in the next cell as text. A rule draws nothing
    # a page keeps, so a whole one stands for them.
    text = declare_headers(text, counter)
    text = longtable_heads(text, counter)
    text = unwrap(text, "pandocbounded", counter, "bounded")
    text = substitute(MULTICOLUMN_EDGE, text,
                      lambda m: m.group(1) + re.sub(r"@\{[^{}]*\}", "", m.group(2)) + "}",
                      counter, "multicolumn_edge")
    text = drop(text, "OERLinkContents", counter, "link_contents")
    text = stacked_lines(text, counter)
    text = minipage_breaks(text, counter)
    text = drop(text, "OERLinkContentsReset", counter, "link_contents_reset")
    text = substitute(RULE_ANY, text, invisible_rule, counter, "rule_seen")
    text = substitute(PARTIAL_RULE, text, lambda m: "\\" + (
        "midrule" if m.group(1) == "cmidrule" else "hline"), counter,
        "partial_rule")

    def graphics(m):
        options = m.group(3) or ""
        keys = [o.strip() for o in options.split(",")]
        if "artifact" in keys:
            counter["artifact"] = counter.get("artifact", 0) + 1
            kept = [k for k in keys if k and k != "artifact"
                    and not k.startswith("alt")]
            return "\\includegraphics[%s]{" % ",".join(
                kept + ["alt={%s}" % ARTIFACT])
        return m.group(0)
    spans = skip_spans(text)
    out, last = [], 0
    for m in GRAPHICS.finditer(text):
        if in_spans(m.start(), spans):
            continue
        out.append(text[last:m.start()] + graphics(m))
        last = m.end()
    out.append(text[last:])
    return "".join(out)


# A \ref to a label on an enumerated item, which the reader can't resolve:
# it writes the label's name in brackets ("[Topic2Q1]"), where LaTeX writes
# the item's number ("1b": FINC 308's answer keys, 70 of them). The number
# is worked out as LaTeX would: article's \theenumi..iv (arabic, alph,
# roman, Alph) after the \p@ prefixes (1, 1b, 1(b)iii, 1(b)iiiA), or a
# label enumitem sets (label=, ref=), which LaTeX's \ref gives without them.
LIST_TOKEN = re.compile(
    r"\\begin\s*\{(enumerate|itemize|description)\}(\s*\[(?:[^][]|\[[^]]*\])*\])?"
    r"|\\end\s*\{(enumerate|itemize|description)\}"
    r"|\\item(?![A-Za-z@])(\s*\[)?"
    r"|\\label\s*\{([^}]*)\}"
    r"|\\(?:part|chapter|section|subsection|subsubsection|paragraph|caption)\*?(?![A-Za-z@])"
    r"|\\begin\s*\{(?:equation|align|gather|multline|figure|table)\*?\}")
COUNTER_MACRO = re.compile(r"\\(arabic|alph|Alph|roman|Roman)\*")
ITEM_REF = re.compile(r"\\ref\*?\s*\{([^}]*)\}")


def counter_text(style, n):
    """n as LaTeX's \\arabic, \\alph, \\Alph, \\roman, or \\Roman writes it."""
    if style == "arabic" or n < 1:
        return str(n)
    if style in ("alph", "Alph"):
        text = chr(ord("a") + (n - 1) % 26) if n <= 26 else str(n)
        return text.upper() if style == "Alph" else text
    numerals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for value, numeral in numerals:
        while n >= value:
            out += numeral
            n -= value
    return out.upper() if style == "Roman" else out


def list_format(options, key):
    """The format an enumitem key (label or ref) gives a list, or None."""
    for item in re.split(r",(?![^{]*\})", options or ""):
        name, _, value = item.partition("=")
        if name.strip() == key and COUNTER_MACRO.search(value):
            value = value.strip()
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1]
            return value
    return None


def formatted(fmt, n):
    """A label format with its counter written in, and the font commands
    and braces around it left out."""
    text = COUNTER_MACRO.sub(lambda m: counter_text(m.group(1), n), fmt)
    text = re.sub(r"\\[A-Za-z@]+\s*", "", text)
    return text.replace("{", "").replace("}", "").strip()


def item_labels(text):
    """{label: what \\ref gives} for each \\label on an enumerated item in
    text, in code."""
    styles = ["arabic", "alph", "roman", "Alph"]
    stack, found, last_closed = [], {}, {}
    spans = skip_spans(text)
    for m in LIST_TOKEN.finditer(text):
        if in_spans(m.start(), spans):
            continue
        token = m.group(0)
        if m.group(1):
            options = (m.group(2) or "").strip()[1:-1] if m.group(2) else ""
            depth = sum(1 for e in stack if e["kind"] == "enumerate") + 1
            entry = {"kind": m.group(1), "value": 0, "item": False, "depth": depth,
                     "label": list_format(options, "label"), "ref": list_format(options, "ref")}
            if m.group(1) == "enumerate":
                start = re.search(r"(?:^|,)\s*start\s*=\s*(\d+)", options)
                if start:
                    entry["value"] = int(start.group(1)) - 1
                elif re.search(r"(?:^|,)\s*resume\*?\s*(?:,|$)", options):
                    entry["value"] = last_closed.get(depth, 0)
            stack.append(entry)
        elif m.group(3):
            if stack:
                closed = stack.pop()
                if closed["kind"] == "enumerate":
                    last_closed[closed["depth"]] = closed["value"]
        elif token.startswith("\\item"):
            if stack:
                top = stack[-1]
                if m.group(4):            # \item[...]: no number
                    top["item"] = False
                else:
                    top["value"] += 1
                    top["item"] = True
        elif m.group(5) is not None:
            if not stack or stack[-1]["kind"] != "enumerate" or not stack[-1]["item"]:
                continue
            levels = [e for e in stack if e["kind"] == "enumerate"]
            top = levels[-1]
            if top["ref"]:
                found[m.group(5).strip()] = formatted(top["ref"], top["value"])
                continue
            if top["label"]:
                found[m.group(5).strip()] = formatted(top["label"], top["value"])
                continue
            parts = []
            for level, e in enumerate(levels[:4]):
                the = formatted(e["label"], e["value"]) if e["label"] \
                    else counter_text(styles[level], e["value"])
                parts.append(the)
            # \p@enumiii is \theenumi(\theenumii), so the third level's
            # reference has the second in parentheses.
            if len(parts) >= 3:
                parts[1] = "(" + parts[1] + ")"
            found[m.group(5).strip()] = "".join(parts)
        elif stack:
            # A heading, caption, or numbered display takes the label
            # after it, not the item before.
            stack[-1]["item"] = False
    return found


def write_out_item_refs(texts, counter):
    """texts ({name: text}) with each \\ref to an enumerated item's label
    written as the number LaTeX gives it."""
    labels = {}
    for text in texts.values():
        labels.update(item_labels(text))
    if not labels:
        return texts
    for name, text in texts.items():
        spans = skip_spans(text)
        count = [0]

        def one(m):
            if in_spans(m.start(), spans) or m.group(1).strip() not in labels:
                return m.group(0)
            count[0] += 1
            return labels[m.group(1).strip()]
        texts[name] = ITEM_REF.sub(one, text)
        counter["item_refs"] = counter.get("item_refs", 0) + count[0]
    return texts


# A column type the book defines with array's \newcolumntype, which the
# reader doesn't know: it takes the table's column specification as text
# and the table falls apart (FINC 308's R{2.3in}, a right-aligned p
# column), and it stops on a \newcolumntype in the body ("unexpected #1").
NEWCOLUMNTYPE = re.compile(r"\\newcolumntype\s*\{\s*(\S)\s*\}\s*(?:\[(\d)\])?\s*\{")
SPEC_BEGIN = re.compile(r"\\begin\s*\{(tabular\*?|tabularx|longtable|array)\}\s*(?:\[[^]]*\]\s*)?")


def column_types(texts):
    """{letter: (arguments, definition)} for each \\newcolumntype in texts,
    and {text index: [(start, end)]} of the definitions."""
    found, places = {}, {}
    for index, text in enumerate(texts):
        spans = skip_spans(text)
        for m in NEWCOLUMNTYPE.finditer(text):
            if in_spans(m.start(), spans):
                continue
            close = matching_brace(text, m.end() - 1)
            if close < 0:
                continue
            found[m.group(1)] = (int(m.group(2) or 0), text[m.end():close - 1])
            places.setdefault(index, []).append((m.start(), close))
    return found, places


def expand_columns(spec, types):
    """A column specification with each column type in types written out,
    its arguments in place of #1..#9; a definition may use another."""
    for _ in range(10):
        out, i, changed = [], 0, False
        while i < len(spec):
            c = spec[i]
            if c == "\\":
                out.append(spec[i:i + 2])
                i += 2
            elif c == "{":
                close = matching_brace(spec, i)
                if close < 0:
                    out.append(spec[i:])
                    break
                out.append(spec[i:close])
                i = close
            elif c == "*":
                # *{3}{R{1in}}: the repeated columns written out too.
                m = re.compile(r"\*\s*\{[^}]*\}\s*\{").match(spec, i)
                close = matching_brace(spec, m.end() - 1) if m else -1
                if close < 0:
                    out.append(c)
                    i += 1
                    continue
                inner = expand_columns(spec[m.end():close - 1], types)
                changed |= inner != spec[m.end():close - 1]
                out.append(spec[i:m.end()] + inner + "}")
                i = close
            elif c in types:
                count, body = types[c]
                args, j = [], i + 1
                for _ in range(count):
                    while j < len(spec) and spec[j].isspace():
                        j += 1
                    if j >= len(spec) or spec[j] != "{":
                        break
                    close = matching_brace(spec, j)
                    if close < 0:
                        break
                    args.append(spec[j + 1:close - 1])
                    j = close
                if len(args) != count:
                    out.append(c)
                    i += 1
                    continue
                for number, arg in enumerate(args, start=1):
                    body = body.replace("#%d" % number, arg)
                out.append(body)
                i = j
                changed = True
            else:
                out.append(c)
                i += 1
        spec = "".join(out)
        if not changed:
            break
    return spec


def write_out_columns(texts, counter):
    """texts ({name: text}) with each column type the book defines written
    out where a table uses it, and the definitions taken out."""
    names = list(texts)
    types, places = column_types([texts[n] for n in names])
    if not types:
        return texts
    for index, name in enumerate(names):
        text = texts[name]
        for start, end in reversed(places.get(index, [])):
            text = text[:start] + text[end:]
        spans = skip_spans(text)
        edits = []
        for m in SPEC_BEGIN.finditer(text):
            if in_spans(m.start(), spans):
                continue
            pos = m.end()
            if m.group(1) in ("tabular*", "tabularx"):
                if text[pos:pos + 1] != "{":
                    continue
                pos = matching_brace(text, pos)
                while 0 < pos < len(text) and text[pos].isspace():
                    pos += 1
            if pos <= 0 or text[pos:pos + 1] != "{":
                continue
            close = matching_brace(text, pos)
            if close < 0:
                continue
            spec = text[pos + 1:close - 1]
            expanded = expand_columns(spec, types)
            if expanded != spec:
                edits.append((pos + 1, close - 1, expanded))
        for start, end, new in reversed(edits):
            text = text[:start] + new + text[end:]
        counter["column_types"] = counter.get("column_types", 0) + len(edits)
        texts[name] = text
    return texts


# --------------------------------------------------------------------------
# drawings
# --------------------------------------------------------------------------

UNITLENGTH = re.compile(r"\\setlength\s*\{\\unitlength\}\s*\{[^}]*\}")
GLUE = re.compile(r"(?:\s|%[^\n]*\n|\\setlength\s*\{\\unitlength\}\s*\{[^}]*\}"
                  r"|\\begingroup\\makeatletter.*?\\endgroup)*", re.S)


def environment_end(text, name, start):
    """The index just past the \\end{name} that closes the environment
    whose \\begin{name} is at start, counting nested ones."""
    pattern = re.compile(r"\\(begin|end)\s*\{" + re.escape(name) + r"\}")
    depth = 0
    for m in pattern.finditer(text, start):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.end()
    return -1


def drawings(text):
    """The drawings in a file's text, as (start, end, alt) spans. A run
    of them with nothing between but whitespace, comments, and a
    \\setlength{\\unitlength}, as fig2dev's pstex_t output writes its two
    picture environments, is one drawing; a \\setlength{\\unitlength}
    just before one belongs to it."""
    spans = skip_spans(text)
    begin = re.compile(r"\\begin\s*\{(" + "|".join(DRAWINGS) + r")\}")
    found = []
    pos = 0
    while True:
        m = begin.search(text, pos)
        if not m:
            break
        if in_spans(m.start(), spans):
            pos = m.end()
            continue
        end = environment_end(text, m.group(1), m.start())
        if end < 0:
            break
        alt = None
        options = re.match(r"\s*\[([^]]*)\]", text[m.end():])
        if options and re.search(r"\boverlay\b", options.group(1)):
            # Drawn on the page, not in the text: a rule down every page
            # from \AddToShipoutPictureBG, say.
            pos = end
            continue
        if options:
            a = re.search(r"\balt\s*=\s*\{([^}]*)\}", options.group(1))
            alt = a.group(1) if a else None
        start = m.start()
        before = list(UNITLENGTH.finditer(text, max(0, start - 200), start))
        if before and not text[before[-1].end():start].strip(" \t\n%"):
            start = before[-1].start()
        if found and GLUE.fullmatch(text[found[-1][1]:start]):
            prev = found.pop()
            start = prev[0]
            alt = alt or prev[2]
        found.append((start, end, alt))
        pos = end
    return found


def drawing_name(path, index, whole):
    """Where a drawing's SVG goes, relative to the book: beside a copy of
    its file's path under rendered/, named for the file when the drawing
    is all the file holds."""
    stem = os.path.splitext(path)[0].replace(os.sep, "/")
    return f"{RENDERED}/{stem}.svg" if whole else \
        f"{RENDERED}/{stem}-{index}.svg"


def pick_engine(preamble):
    """pdflatex unless the preamble needs LuaLaTeX or XeTeX's fonts."""
    if re.search(r"\\usepackage\s*(\[[^]]*\])?\s*\{[^}]*\b(fontspec|"
                 r"unicode-math|polyglossia|luacode|luatexbase)\b", preamble) \
            or "\\directlua" in preamble or "\\DocumentMetadata" in preamble:
        return "lualatex"
    return "pdflatex"


def render(base, work, preamble, items, say):
    """Each drawing, (name, source), as an SVG at base/name, by LaTeX
    with the book's preamble, one page a drawing, and pdftocairo. A
    drawing whose SVG is there and was made from the same source and
    preamble isn't made again. Returns the names made or kept."""
    record_path = os.path.join(base, RENDERED, ".rendered.json")
    try:
        with open(record_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        record = {}

    def key(source):
        return hashlib.sha256((preamble + "\n" + source).encode(
            "utf-8", "surrogateescape")).hexdigest()
    todo = [(n, s) for n, s in items
            if record.get(n) != key(s)
            or not os.path.isfile(os.path.join(base, n))]
    done = [n for n, s in items if (n, s) not in todo]
    if not todo:
        return done
    engine = pick_engine(preamble)
    if not shutil.which(engine) or not shutil.which("pdftocairo"):
        say(f"WARNING: {len(todo)} drawing(s) need {engine} and pdftocairo "
            "(poppler-utils) to become images, and one isn't installed; "
            "they're left out of the pages.")
        return done
    head, _, _ = preamble.rpartition("\\begin")
    rdir = os.path.join(work, "render")
    os.makedirs(rdir, exist_ok=True)

    def run_latex(batch, job):
        """The batch's drawings as pages of job.pdf, or None."""
        body = "".join("\\begin{preview}%s\\end{preview}\n\\clearpage\n" % s
                       for _, s in batch)
        write_text(os.path.join(rdir, job + ".tex"),
                   head + "\\usepackage[active,tightpage]{preview}\n"
                   "\\begin{document}\n" + body + "\\end{document}\n")
        result = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error",
             "-output-directory", rdir, os.path.join(rdir, job + ".tex")],
            cwd=base, capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL)
        pdf = os.path.join(rdir, job + ".pdf")
        if result.returncode != 0 or not os.path.isfile(pdf):
            return None, result.stdout[-800:]
        return pdf, ""

    def split(batch, pdf):
        for page, (name, source) in enumerate(batch, start=1):
            out = os.path.join(base, name)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            made = subprocess.run(["pdftocairo", "-svg", "-f", str(page), "-l",
                                   str(page), pdf, out], capture_output=True,
                                  text=True)
            if made.returncode == 0 and os.path.isfile(out):
                record[name] = key(source)
                done.append(name)

    # All at once; when that fails, one at a time, so a drawing LaTeX
    # can't make costs only itself.
    pdf, log = run_latex(todo, "drawings")
    if pdf:
        split(todo, pdf)
    else:
        failed = []
        for index, item in enumerate(todo):
            one, why = run_latex([item], "drawing-%d" % index)
            if one:
                split([item], one)
            else:
                failed.append(item[0])
                log = why
        if failed:
            say(f"WARNING: {engine} couldn't render {len(failed)} of the "
                f"book's {len(todo)} drawing(s) with its own preamble, so "
                "they're left out of the pages: " + ", ".join(failed[:5])
                + (", ..." if len(failed) > 5 else "")
                + ". The end of its output for the last:\n" + log)
    write_text(record_path, json.dumps(record, indent=1, sort_keys=True))
    return done


# --------------------------------------------------------------------------
# images a browser can't show
# --------------------------------------------------------------------------

# graphicx's own order for a name given without an extension, under
# pdfLaTeX and LuaLaTeX, then .eps, which latex and dvips take.
GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".mps", ".jpeg", ".jbig2",
                       ".jb2", ".PDF", ".PNG", ".JPG", ".JPEG", ".eps",
                       ".EPS")
CONVERT = (".pdf", ".eps", ".ps")


def graphics_paths(preamble):
    """The directories \\graphicspath names, as relative paths."""
    m = re.search(r"\\graphicspath\s*\{((?:\s*\{[^}]*\})*)\s*\}", preamble)
    return [d for d in re.findall(r"\{([^}]*)\}", m.group(1))] if m else []


def resolve_graphic(base, name, dirs):
    """The file graphicx would include for name, relative to base, or
    None."""
    name = name.strip()
    for d in [""] + dirs:
        for ext in ("",) + GRAPHICS_EXTENSIONS:
            candidate = os.path.normpath(os.path.join(d, name + ext))
            if os.path.isfile(os.path.join(base, candidate)) and (
                    ext or os.path.splitext(name)[1]):
                return candidate
    return None


def convert_graphic(base, work, path, record, say):
    """An SVG of a PDF's first page, or an EPS's, at base/rendered/<path>.svg,
    made again only when the file has changed. Returns its name, or None."""
    name = f"{RENDERED}/{os.path.splitext(path)[0]}.svg".replace(os.sep, "/")
    with open(os.path.join(base, path), "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    out = os.path.join(base, name)
    if record.get(name) == digest and os.path.isfile(out):
        return name
    if not shutil.which("pdftocairo"):
        return None
    source = os.path.join(base, path)
    if path.lower().endswith((".eps", ".ps")):
        if not shutil.which("epstopdf"):
            return None
        pdf = os.path.join(work, "render", os.path.basename(path) + ".pdf")
        os.makedirs(os.path.dirname(pdf), exist_ok=True)
        if subprocess.run(["epstopdf", source, "--outfile=" + pdf],
                          capture_output=True).returncode != 0:
            return None
        source = pdf
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if subprocess.run(["pdftocairo", "-svg", "-f", "1", "-l", "1", source,
                       out], capture_output=True).returncode != 0:
        return None
    record[name] = digest
    return name


def repair_graphics(base, work, text, dirs, record, counter, say):
    """Each \\includegraphics in code pointed at a file a browser shows:
    the extension graphicx would add written in, and a PDF or EPS made
    an SVG."""
    spans = skip_spans(text)
    out, last = [], 0
    for m in GRAPHICS.finditer(text):
        if in_spans(m.start(), spans):
            continue
        close = matching_brace(text, m.end() - 1)
        if close < 0:
            continue
        name = text[m.end():close - 1]
        path = resolve_graphic(base, name, dirs)
        if path is None:
            continue
        if path.lower().endswith(CONVERT):
            made = convert_graphic(base, work, path, record, say)
            counter["graphics_converted" if made else "graphics_failed"] = \
                counter.get("graphics_converted" if made
                            else "graphics_failed", 0) + 1
            path = made or path
        if path != name:
            out.append(text[last:m.end()] + path.replace(os.sep, "/"))
            last = close - 1
    out.append(text[last:])
    return "".join(out)


# --------------------------------------------------------------------------
# images behind the book's own macros
# --------------------------------------------------------------------------

MACRO_DEFINITION = re.compile(
    r"\\(?:(?:re)?newcommand|providecommand)\*?\s*(?:\{\s*\\([A-Za-z@]+)\s*\}|\\([A-Za-z@]+))"
    r"\s*(?:\[\s*(\d)\s*\])?\s*")
PLAIN_DEFINITION = re.compile(r"\\[gex]?def\s*\\([A-Za-z@]+)\s*((?:#\d\s*)*)\{")
BODY_GRAPHICS = re.compile(r"\\includegraphics\s*(\*)?\s*(\[[^]]*\])?\s*\{")
ALT_ARGUMENT = re.compile(r"(?:^\[|,)\s*alt\s*=\s*(?:\{\s*#(\d)\s*\}|#(\d))\s*(?=[,\]])")
OWN_KEY = re.compile(r"(?:^\[|,)\s*(?:alt\s*=|artifact\s*(?:=|(?=[,\]])))")
TABLE_OR_DRAWING = re.compile(r"\\begin\s*\{(?:tabular\*?|tabularx|longtable|picture"
                              r"|tikzpicture|pspicture)\}")


def closing_bracket(text, start):
    """The index of the ] closing the [ at text[start], braces kept whole."""
    depth, i = 0, start + 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "]" and depth == 0:
            return i
        i += 1
    return -1


def image_macro(body, arguments, default):
    """The macro, as image_macros describes one, if body holds one
    \\includegraphics whose file is made from one argument; else None."""
    if "##" in body:
        return None
    found = list(BODY_GRAPHICS.finditer(body))
    if len(found) != 1:
        return None
    m = found[0]
    close = matching_brace(body, m.end() - 1)
    if close < 0:
        return None
    path = body[m.end():close - 1]
    used = set(re.findall(r"#(\d)", path))
    if len(used) != 1 or int(next(iter(used))) > arguments:
        return None
    options = m.group(2) or ""
    alt = ALT_ARGUMENT.search(options)
    number = int(alt.group(1) or alt.group(2)) if alt else None
    # An argument that is a whole entry of the key list ([#1], [width=1cm,#1]):
    # a call's own keys, an alt among them, which win over one set before.
    entries = [e.strip() for e in re.split(r",(?![^{]*\})", options[1:-1])] if options else []
    whole = [int(e[1]) for e in entries if re.fullmatch(r"#\d", e)]
    return {"arguments": arguments, "default": default, "file": path, "body": body,
            "alt": number,
            # alt=#3, unbraced, takes a comma in the text for the next key.
            "alt_braced": bool(alt and alt.group(1)),
            # The alt argument used elsewhere too (\caption{#3}), so writing
            # the description there would change that.
            "alt_shared": bool(alt) and len(re.findall(r"#%d(?!\d)" % number, body)) > 1,
            "options": whole[0] if whole else None,
            "keyed": bool(OWN_KEY.search(options)) and not alt}


def image_macros(texts):
    """({name: macro}, {text's name: [(start, end)]}): each macro the book
    defines, with \\newcommand and its kin or \\def with plain arguments,
    whose body holds one \\includegraphics with its file made from one of
    its arguments, and the span of every definition in each text. A macro
    is a dict: arguments, how many; default, the first one's when it's
    optional, else None; file, the file as the body writes it, #1 and
    all; body, the whole body; alt, the argument the body's own alt key
    takes, or None; keyed, whether the body gives alt text or artifact of
    its own. texts is [(name, text)], the master first: the definitions
    are read in the order LaTeX reads them, each file where it's \\input,
    so a later definition replaces an earlier one, and \\providecommand
    defines only a name nothing has defined yet."""
    by_name = dict(texts)
    macros, defined, spans_by_text, visited = {}, set(), {}, set()

    def define(found, macro, provide=False):
        if provide and found in defined:
            return
        defined.add(found)
        if macro:
            macros[found] = macro
        else:
            macros.pop(found, None)

    def walk(name):
        if name in visited or name not in by_name:
            return
        visited.add(name)
        text = by_name[name]
        skip = skip_spans(text)
        here, events = [], []
        for kind, pattern in (("new", MACRO_DEFINITION), ("plain", PLAIN_DEFINITION),
                              ("input", INPUT)):
            events += [(m.start(), kind, m) for m in pattern.finditer(text)
                       if not in_spans(m.start(), skip)]
        for _, kind, m in sorted(events, key=lambda e: e[0]):
            if kind == "input":
                target = (m.group(2) or m.group(3) or "").strip().strip('"')
                folder = os.path.dirname(name)
                for candidate in (os.path.join(folder, target), os.path.join(folder, target + ".tex"),
                                  target, target + ".tex"):
                    if os.path.normpath(candidate) in by_name:
                        walk(os.path.normpath(candidate))
                        break
            elif kind == "new":
                pos, default = m.end(), None
                if text.startswith("[", pos):
                    close = closing_bracket(text, pos)
                    if close < 0:
                        continue
                    default = text[pos + 1:close]
                    pos = close + 1
                    while pos < len(text) and text[pos].isspace():
                        pos += 1
                if not text.startswith("{", pos):
                    continue
                close = matching_brace(text, pos)
                if close < 0:
                    continue
                here.append((m.start(), close))
                define(m.group(1) or m.group(2),
                       image_macro(text[pos + 1:close - 1], int(m.group(3) or 0), default),
                       provide=text.startswith("\\providecommand", m.start()))
            else:
                close = matching_brace(text, m.end() - 1)
                if close < 0:
                    continue
                here.append((m.start(), close))
                define(m.group(1), image_macro(text[m.end():close - 1],
                                               len(re.findall(r"#\d", m.group(2))), None))
        spans_by_text[name] = sorted(here)
    for name, _ in texts:
        walk(name)
    return macros, spans_by_text


def argument_space(text, pos):
    """Past the spaces TeX skips before an argument: blanks and at most
    one line end, since a blank line is a paragraph."""
    return re.compile(r"[ \t]*(?:\n[ \t]*)?").match(text, pos).end()


def macro_calls(text, macros, skip):
    """(start, end, name, arguments) for each call in text of one of
    macros, outside the spans in skip; each argument (text, start, end)
    as written, an optional one not given its default with no place. A
    call whose arguments aren't each braced is left out."""
    if not macros:
        return []
    pattern = re.compile(r"\\(" + "|".join(
        re.escape(n) for n in sorted(macros, key=len, reverse=True)) + r")(?![A-Za-z@])")
    calls = []
    for m in pattern.finditer(text):
        if in_spans(m.start(), skip):
            continue
        macro, pos, args = macros[m.group(1)], m.end(), []
        if macro["default"] is not None:
            p = argument_space(text, pos)
            if text.startswith("[", p):
                close = closing_bracket(text, p)
                if close < 0:
                    continue
                args.append((text[p + 1:close], p + 1, close))
                pos = close + 1
            else:
                args.append((macro["default"], None, None))
        while len(args) < macro["arguments"]:
            p = argument_space(text, pos)
            if not text.startswith("{", p):
                break
            close = matching_brace(text, p)
            if close < 0:
                break
            args.append((text[p + 1:close - 1], p + 1, close - 1))
            pos = close
        if len(args) == macro["arguments"]:
            calls.append((m.start(), pos, m.group(1), args))
    return calls


def expand_image_macros(texts, files, counter):
    """Each call of one of the book's macros for an image, outside any
    definition, replaced in the reading copy by the macro's body with its
    arguments, as Pandoc expands it, so the \\includegraphics in it is
    there for repair_graphics to point at a file a browser shows. A body
    holding a table or a drawing is left as it is, since its file's tables
    and drawings are counted in the author's text. texts: {name: text},
    changed in place."""
    macros, definitions = image_macros([(name, texts[name]) for name in files])
    macros = {n: m for n, m in macros.items() if not TABLE_OR_DRAWING.search(m["body"])}
    if not macros:
        return
    for name in files:
        text = texts[name]
        calls = macro_calls(text, macros, sorted(skip_spans(text) + definitions.get(name, [])))
        last = len(text) + 1
        for start, end, macro_name, args in reversed(calls):
            if end > last:              # one call inside another's arguments
                continue
            expanded = re.sub(
                r"#(\d)", lambda m: args[int(m.group(1)) - 1][0]
                if int(m.group(1)) <= len(args) else m.group(0),
                macros[macro_name]["body"])
            text = text[:start] + expanded + text[end:]
            last = start
            counter["image_macro_calls"] = counter.get("image_macro_calls", 0) + 1
        texts[name] = text


# --------------------------------------------------------------------------
# the copy, the reading, and the pages
# --------------------------------------------------------------------------

# A standalone document's title set as large type, not with \title.
SIZES = ("tiny", "scriptsize", "footnotesize", "small", "normalsize",
         "large", "Large", "LARGE", "huge", "Huge")
TITLE_COMMAND = re.compile(r"\\title\s*[\[{]")
DIVISION_COMMAND = re.compile(r"\\(?:part|chapter)\*?(?![A-Za-z@])")
TITLE_BLOCK = re.compile(r"\\begin\s*\{(center|titlepage)\}")
BEFORE_TITLE = re.compile(
    r"(?:\s+|%[^\n]*|\\(?:vspace|hspace)\*?\s*\{[^}]*\}"
    r"|\\(?:thispagestyle|pagestyle)\s*\{[^}]*\}"
    r"|\\(?:noindent|bigskip|medskip|smallskip|par|null|centering)(?![A-Za-z@]))*")
FONT_SWITCH = re.compile(r"\\(" + "|".join(SIZES) + r"|bfseries|mdseries|itshape|scshape"
                         r"|upshape|slshape|sffamily|rmfamily|ttfamily|normalfont|centering)"
                         r"(?![A-Za-z@])\s*")
TITLE_MARKER = "TextbookImproverPageTitle"


def visual_title(text):
    """A whole document's title set as large type rather than with \\title:
    the brace group in a center (or titlepage) environment opening its
    body, set larger than any other group there and at \\large or more
    ({\\LARGE Topic 1: ...} under {\\large FINC 308: ...}, as each of
    FINC 308's topics has it). Returns (start, end, environment, before,
    title, after) -- the environment's span in text, its content before
    and after the group, and the group's without its size and font
    switches -- or None: for a document with \\title or a \\chapter, one
    whose body opens with anything else, or two groups the same size."""
    spans = skip_spans(text)
    if code_matches(TITLE_COMMAND, text, spans) or code_matches(DIVISION_COMMAND, text, spans):
        return None
    begin = code_matches(BEGIN_DOCUMENT, text, spans)
    if not begin:
        return None
    opening = TITLE_BLOCK.match(text, BEFORE_TITLE.match(text, begin[0].end()).end())
    if not opening:
        return None
    end = environment_end(text, opening.group(1), opening.start())
    if end < 0:
        return None
    inner = text[opening.end():text.rfind("\\end", opening.end(), end)]
    groups, i = [], 0
    while i < len(inner):
        c = inner[i]
        if c == "\\":
            i += 2
        elif c == "%":
            line_end = inner.find("\n", i)
            i = len(inner) if line_end < 0 else line_end
        elif c == "{":
            stop = matching_brace(inner, i)
            if stop < 0:
                return None
            content, pos, rank = inner[i + 1:stop - 1], 0, -1
            while True:
                switch = FONT_SWITCH.match(content, pos)
                if not switch:
                    break
                if switch.group(1) in SIZES:
                    rank = max(rank, SIZES.index(switch.group(1)))
                pos = switch.end()
            groups.append((i, stop, rank, content[pos:].strip()))
            i = stop
        else:
            i += 1
    if not groups:
        return None
    top = max(g[2] for g in groups)
    largest = [g for g in groups if g[2] == top]
    if top < SIZES.index("large") or len(largest) != 1 or not largest[0][3]:
        return None
    start, stop, _, title = largest[0]
    # A command the group is the argument of (\textbf{\Large ...}) goes with it.
    before = re.sub(r"\\[A-Za-z@]+\s*$", "", inner[:start])
    return opening.start(), end, opening.group(1), before, title, inner[stop:]


def mark_title(text, counts):
    """text, a master's, with the title visual_title finds made a heading
    the reader keeps -- \\section*, after a marker paragraph that
    title_heading finds -- and what came before and after it in its
    environment left there."""
    found = visual_title(text)
    if not found:
        return text
    start, end, environment, before, title, after = found
    pieces = []
    if before.strip():
        pieces.append("\\begin{%s}%s\n\\end{%s}" % (environment, before, environment))
    pieces.append("\n\n%s\n\n\\section*{%s}\n\n" % (TITLE_MARKER, title))
    if after.strip():
        pieces.append("\\begin{%s}%s\\end{%s}" % (environment, after, environment))
    counts["visual_title"] = counts.get("visual_title", 0) + 1
    return text[:start] + "".join(pieces) + text[end:]


def _headers(blocks):
    """Every Header in blocks, nested ones too."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Header":
                found.append(node)
            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(blocks)
    return found


def title_heading(blocks):
    """A page's blocks with the title mark_title marked made its only
    heading at level 1, the page's title, as the pipeline takes one: the
    marker out, the heading numbered like any title, and every other
    heading moved down so the highest is at level 2, under it. Returns
    (blocks, whether there was one)."""
    for index, block in enumerate(blocks):
        if block.get("t") == "Para" and len(block["c"]) == 1 \
                and block["c"][0].get("t") == "Str" and block["c"][0]["c"] == TITLE_MARKER:
            break
    else:
        return blocks, False
    blocks = blocks[:index] + blocks[index + 1:]
    if index >= len(blocks) or blocks[index].get("t") != "Header":
        return blocks, False
    heading = blocks[index]
    heading["c"][0] = 1
    heading["c"][1][1] = [c for c in heading["c"][1][1] if c != "unnumbered"]
    others = [h for h in _headers(blocks) if h is not heading]
    if others:
        shift = 2 - min(h["c"][0] for h in others)
        if shift > 0:
            for h in others:
                h["c"][0] = min(h["c"][0] + shift, 6)
    return blocks, True


def prepare(base, work, master, say, macros=""):
    """The book copied into work/latex with what Pandoc can't read put
    right, its drawings rendered into base/rendered/. Returns a dict:
    master (the copy's path), order, front_role, files, missing,
    counts, preamble."""
    copy = os.path.join(work, "latex")
    if os.path.isdir(copy):
        shutil.rmtree(copy)
    files, missing = reached(base, master)
    counts = {}
    texts = {}
    for name in files:
        texts[name] = repair_text(read_text(os.path.join(base, name)), counts)
    write_out_columns(texts, counts)
    write_out_item_refs(texts, counts)
    folder = os.path.dirname(master)
    if folder:
        # A master below the book's directory is built from its own
        # folder; the reader runs from the book's, as the pages' paths are.
        for name in files:
            texts[name] = inputs_from(base, texts[name], folder, counts)
    preamble, body, rest = split_master(texts[master])
    order, front_role = book_outline(body)
    # A document that is one page, its title set as large type: the title
    # made its heading.
    if not order:
        texts[master] = mark_title(texts[master], counts)

    # Drawings, all rendered in one LaTeX run.
    places, items = {}, []
    for name in files:
        text = texts[name]
        offset = 0
        if name == master:
            # The master's drawings are in its body; the preamble defines.
            begin = code_matches(BEGIN_DOCUMENT, text)
            offset = begin[0].end() if begin else len(text)
        found = [(s + offset, e + offset, a)
                 for s, e, a in drawings(text[offset:])]
        for index, (start, end, alt) in enumerate(found, start=1):
            whole = len(found) == 1 and not re.sub(
                r"%[^\n]*", "", text[:start] + text[end:]).strip()
            dname = drawing_name(name, index, whole)
            places.setdefault(name, []).append((start, end, alt, dname))
            items.append((dname, text[start:end]))
    made = set(render(base, work, split_master(read_text(
        os.path.join(base, master)))[0], items, say)) if items else set()
    counts["drawings"] = len(items)
    counts["drawings_made"] = len(made)
    for name, found in places.items():
        text = texts[name]
        for start, end, alt, dname in reversed(found):
            if dname not in made:
                continue
            option = "[alt={%s}]" % alt if alt is not None else ""
            text = text[:start] + "\\includegraphics%s{%s}" % (option, dname) \
                + text[end:]
        texts[name] = text

    # Images behind the book's own macros, written out, then all of them
    # given the extension, PDF and EPS made SVG.
    expand_image_macros(texts, files, counts)
    record_path = os.path.join(base, RENDERED, ".rendered.json")
    try:
        with open(record_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        record = {}
    dirs = graphics_paths(preamble)
    if folder:
        dirs = [folder] + [os.path.join(folder, d) for d in dirs] + dirs
    for name in files:
        texts[name] = repair_graphics(base, work, texts[name], dirs, record,
                                      counts, say)
    if record:
        write_text(record_path, json.dumps(record, indent=1, sort_keys=True))
    for index, name in enumerate(files):
        texts[name] = mark_tables(texts[name], index)
        # After the places are marked, so a box keeps its number among the
        # file's tables, as a remediated copy counts them.
        texts[name] = read_boxes(texts[name], counts)

    # The master: \centerline as a center environment, and a marker
    # before each \include. Split again, since its drawings and images
    # may have been replaced.
    _, body, rest = split_master(texts[master])
    spans = skip_spans(body)
    pieces, last, index = [], 0, 0
    for m in INCLUDE.finditer(body):
        if in_spans(m.start(), spans):
            continue
        pieces.append(body[last:m.start()])
        pieces.append("\n\n" + MARKER_LINE % index + "\n\n" + m.group(0))
        last = m.end()
        index += 1
    pieces.append(body[last:])
    # A person's definitions for reading, after the book's own, so they
    # win: \suchthat as \mid, say, where the book draws a bar with a rule.
    extra = ""
    if macros and os.path.isfile(os.path.join(base, macros)):
        extra = read_text(os.path.join(base, macros)) + "\n"
        counts["macros_file"] = 1
    preamble_copy = re.sub(
        r"(\\begin\s*\{document\})$",
        lambda m: "\\renewcommand{\\centerline}[1]{\\begin{center}#1"
                  "\\end{center}}\n" + extra + m.group(1), preamble)
    texts[master] = preamble_copy + "".join(pieces) + rest
    for name, text in texts.items():
        write_text(os.path.join(copy, name), text)
    return {"master": os.path.join(copy, master), "order": order,
            "front_role": front_role, "files": files, "missing": missing,
            "counts": counts, "preamble": preamble, "copy": copy}


TABLE_BEGIN = re.compile(r"\\begin\s*\{(tabular\*?|tabularx|longtable)\}")


def table_spans(text):
    """(start, end) of each table environment in code, in order of its
    \\begin, nested ones too; none inside a drawing, which becomes an
    image. The order a remediated copy finds the same tables in."""
    spans = skip_spans(text)
    inside = [(s, e) for s, e, _ in drawings(text)]
    found = []
    for m in TABLE_BEGIN.finditer(text):
        if in_spans(m.start(), spans) or any(s <= m.start() < e for s, e in inside):
            continue
        end = environment_end(text, m.group(1), m.start())
        if end > 0:
            found.append((m.start(), end))
    return found


def table_place(file_index, ordinal):
    return "F%dN%d" % (file_index, ordinal)


# A box: a tabular of one paragraph column whose cells are prose, an
# author's frame around a passage (FINC 308's 30 "Example" boxes, a bold
# title row over a paragraph between booktabs rules), which a reader
# would hear announced as a table of one column.
BOX_WORDS = 12
RULES = re.compile(r"\\(?:toprule|midrule|bottomrule|hline|addlinespace|morecmidrules)"
                   r"(?![A-Za-z@])\s*(?:\[[^]]*\])?|\\(?:cmidrule|cline)\s*(?:\([^)]*\))?"
                   r"\s*\{[^}]*\}|\\specialrule\s*\{[^}]*\}\s*\{[^}]*\}\s*\{[^}]*\}")
ROW_END = re.compile(r"\\\\\*?\s*(?:\[[^]]*\])?|\\tabularnewline(?![A-Za-z@])")


def column_spec(text, start):
    """(spec, end): a tabular's column specification, the group after
    \\begin{tabular} at start (after its width, for tabular* and
    tabularx), and the index past it; None for longtable and the rest."""
    m = re.compile(r"\\begin\s*\{(tabular\*?|tabularx)\}\s*(?:\[[^]]*\]\s*)?").match(text, start)
    if not m:
        return None
    pos = m.end()
    if m.group(1) in ("tabular*", "tabularx"):
        if pos >= len(text) or text[pos] != "{":
            return None
        pos = matching_brace(text, pos)
        while pos > 0 and pos < len(text) and text[pos].isspace():
            pos += 1
    if pos <= 0 or pos >= len(text) or text[pos] != "{":
        return None
    end = matching_brace(text, pos)
    return (text[pos + 1:end - 1], end) if end > 0 else None


def one_paragraph_column(spec):
    """Whether a column specification is one paragraph column, p{}, m{},
    b{}, or X, with nothing around it but rules and decorations."""
    rest, i = spec, 0
    columns = []
    while i < len(rest):
        c = rest[i]
        if c.isspace() or c == "|":
            i += 1
        elif c in "@!<>" and rest[i + 1:i + 2] == "{":
            i = matching_brace(rest, i + 1)
            if i < 0:
                return False
        elif c in "pmb" and rest[i + 1:i + 2] == "{":
            columns.append(c)
            i = matching_brace(rest, i + 1)
            if i < 0:
                return False
        elif c == "X":
            columns.append(c)
            i += 1
        else:
            return False
    return len(columns) == 1


BEGIN_ANY = re.compile(r"\\begin\s*\{([^}]+)\}")


def box_rows(body):
    """A box's rows, each its text without rules, \\multicolumn{1}'s
    wrapper, and the space put before a title to center it; a table in
    one is part of its row."""
    rows, depth, last, i = [], 0, 0, 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            m = ROW_END.match(body, i)
            if m and depth == 0:
                rows.append(body[last:i])
                last = i = m.end()
                continue
            begin = BEGIN_ANY.match(body, i)
            if begin and depth == 0:
                end = environment_end(body, begin.group(1), i)
                if end > 0:
                    i = end
                    continue
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    rows.append(body[last:])
    out = []
    for row in rows:
        row = RULES.sub("", row)
        m = re.match(r"\s*\\multicolumn\s*\{\s*1\s*\}\s*\{[^}]*\}\s*\{", row)
        if m:
            close = matching_brace(row, m.end() - 1)
            if close > 0:
                row = row[m.end():close - 1] + row[close:]
        row = re.sub(r"^\s*\\hspace\*?\s*\{[^}]*\}", "", row)
        if row.strip():
            out.append(row.strip())
    return out


def box_tables(text):
    """(start, end) of each table in text that is a box: a tabular of one
    paragraph column, with a cell of BOX_WORDS words or more, and no table
    around it. A table in a box is a table of its own."""
    spans = table_spans(text)
    found = []
    for start, end in spans:
        if any(s < start and end <= e for s, e in spans):
            continue
        spec = column_spec(text, start)
        if not spec or not one_paragraph_column(spec[0]):
            continue
        close = text.rfind("\\end", start, end)
        rows = box_rows(text[spec[1]:close])
        words = [len(re.sub(r"\\[A-Za-z@]+|[{}$&]", " ", row).split()) for row in rows]
        if words and max(words) >= BOX_WORDS:
            found.append((start, end))
    return found


def read_boxes(text, counts):
    """text with each box (box_tables) made an environment the reader
    keeps as a div of its rows' paragraphs, which latex-source.lua names
    box: a passage, not a table."""
    for start, end in reversed(box_tables(text)):
        spec = column_spec(text, start)
        rows = box_rows(text[spec[1]:text.rfind("\\end", start, end)])
        text = (text[:start] + "\\begin{TextbookImproverBox}\n" + "\n\n".join(rows)
                + "\n\\end{TextbookImproverBox}" + text[end:])
        counts["boxes"] = counts.get("boxes", 0) + 1
    return text


def mark_tables(text, file_index):
    """Each table wrapped in an environment naming its place, the file's
    index among the files the master reaches and the table's among the
    file's (table_spans), which the reader keeps as a div and
    latex-source.lua puts on the table. Wrapped or not, the reader makes
    the same blocks of it (measured: an inline tabular, one in a figure,
    one nested in another)."""
    edits = []
    for ordinal, (start, end) in enumerate(table_spans(text), start=1):
        name = "TextbookImproverTable" + table_place(file_index, ordinal)
        edits.append((end, "\\end{%s}" % name))
        edits.append((start, "\\begin{%s}" % name))
    for at, piece in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:at] + piece + text[at:]
    return text


def stringify(inlines):
    out = []

    def walk(node):
        if isinstance(node, dict):
            kind = node.get("t")
            if kind == "Str":
                out.append(node["c"])
            elif kind in ("Space", "SoftBreak", "LineBreak"):
                out.append(" ")
            elif kind == "Math":
                out.append(node["c"][1])
            elif "c" in node:
                walk(node["c"])
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(inlines)
    return " ".join("".join(out).split())


def cut_pages(doc, order, master_stem, front_role):
    """The whole book's document cut into pages at the markers: a list of
    (stem, role, blocks). What comes before the first marker is the
    master's own page, named for it, when it holds anything."""
    pages = [[master_stem, front_role, []]]
    for block in doc["blocks"]:
        if block.get("t") == "Para" and len(block["c"]) == 1 \
                and block["c"][0].get("t") == "Str":
            m = MARKER_TEXT.match(block["c"][0]["c"])
            if m:
                path, role = order[int(m.group(1))]
                stem = os.path.splitext(os.path.basename(path))[0]
                pages.append([stem, role, []])
                continue
        pages[-1][2].append(block)
    if not pages[0][2]:
        pages.pop(0)
    return [tuple(p) for p in pages]


# --------------------------------------------------------------------------
# the definitions sample: the book's macros texmath can't read
# --------------------------------------------------------------------------

SAMPLE = "latex-conversion-macros-sample.tex"
NEWCOMMAND = re.compile(r"\\(?:(?:re)?newcommand|providecommand)\*?\s*\{?\s*\\([A-Za-z@]+)"
                        r"\s*\}?\s*(?:\[(\d)\])?\s*(?:\[[^]]*\])?\s*\{")
MATH_SPANS = re.compile(
    r"(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<!\\)\$(.+?)(?<!\\)\$|\\\((.+?)\\\)"
    r"|\\\[(.+?)\\\]|\\begin\{(equation|align|gather|multline|eqnarray|"
    r"displaymath|math)(\*?)\}(.+?)\\end\{\5\6\}", re.S)
RULE = re.compile(r"\\rule\s*(?:\[[^]]*\])?\s*\{([^}]*)\}\s*\{([^}]*)\}")
POINTS = {"pt": 1.0, "bp": 1.00375, "mm": 2.845, "cm": 28.45, "in": 72.27,
          "em": 10.0, "ex": 4.3, "pc": 12.0, "sp": 1 / 65536}


def points(length):
    m = re.match(r"\s*(-?[\d.]+)\s*([a-z]{2})\s*$", length or "")
    if not m or m.group(2) not in POINTS:
        return None
    try:
        return float(m.group(1)) * POINTS[m.group(2)]
    except ValueError:
        return None


def definitions(texts):
    """{name: (arguments, body, definition as written)} for every macro
    the book's files define with \\newcommand and its kin, in code."""
    found = {}
    for text in texts:
        spans = skip_spans(text)
        for m in NEWCOMMAND.finditer(text):
            if in_spans(m.start(), spans):
                continue
            close = matching_brace(text, m.end() - 1)
            if close < 0:
                continue
            found[m.group(1)] = (int(m.group(2) or 0), text[m.end():close - 1],
                                 text[m.start():close])
    return found


def math_uses(texts, names):
    """How often each macro is used inside a formula, in code."""
    uses = dict.fromkeys(names, 0)
    pattern = re.compile(r"\\(" + "|".join(re.escape(n) for n in names)
                         + r")(?![A-Za-z@])") if names else None
    for text in texts:
        spans = skip_spans(text)
        for m in MATH_SPANS.finditer(text):
            if in_spans(m.start(), spans):
                continue
            for u in pattern.finditer(m.group(0)):
                uses[u.group(1)] += 1
    return uses


def suggest(body):
    """A definition saying what a drawn symbol means, when its drawing has
    only one reading: rules no wider than a point and taller than six are
    a vertical bar (\\mid when spaces are all that's around it); rules no
    taller than a point and wider than they are tall, with nothing but
    ticks and spaces beside them, are a blank to fill in. None otherwise."""
    rules = list(RULE.finditer(body))
    if not rules:
        return None
    kinds = []
    for r in rules:
        w, h = points(r.group(1)), points(r.group(2))
        if w is None or h is None:
            return None
        if w == 0 or h == 0 or (w < 2 and h < 2):
            kinds.append("nothing")
        elif w <= 1 and h >= 6:
            kinds.append("bar")
        elif h <= 1 and w > h:
            kinds.append("line")
        else:
            return None
    rest = RULE.sub("", body)
    spacing = re.fullmatch(r"(?:\s|\\[,;:!]|\\quad|\\qquad|\\ )*", rest)
    if set(kinds) <= {"nothing", "line"} and "line" in kinds and spacing:
        return "\\underline{\\quad}"
    if set(kinds) <= {"nothing", "bar"} and kinds.count("bar") == 1:
        if spacing:
            return "\\mid"
        out = body
        for r, kind in reversed(list(zip(rules, kinds))):
            out = out[:r.start()] + ("|" if kind == "bar" else "") + out[r.end():]
        return " ".join(out.replace("\\,", " ").split())
    return None


def probe(copy, preamble, macros, filter_path, extra=""):
    """Which of macros [(name, arguments)] give a formula texmath can't
    make MathML of, read with the book's preamble (and extra definitions)
    and the read-time repairs."""
    if not macros:
        return set()
    head, _, _ = preamble.rpartition("\\begin")
    body = "".join("\n\n$\\%s%s$\n" % (n, "".join("{x}" for _ in range(a)))
                   for n, a in macros)
    path = os.path.join(copy, "TextbookImproverProbe.tex")
    write_text(path, head + extra + "\n\\begin{document}\n" + body
               + "\n\\end{document}\n")
    read = subprocess.run(["pandoc", "-f", "latex", "-t", "json",
                           "TextbookImproverProbe.tex",
                           "--lua-filter=" + filter_path],
                          cwd=copy, capture_output=True, text=True)
    if read.returncode != 0:
        return set()
    doc = json.loads(read.stdout)
    html = subprocess.run(["pandoc", "-f", "json", "-t", "html",
                           "--math-method=mathml"], input=read.stdout,
                          capture_output=True, text=True).stdout
    paragraphs = re.findall(r"<p>(.*?)</p>", html, re.S)
    failing = set()
    formulas = [b for b in doc["blocks"] if b.get("t") == "Para"]
    for (name, _), block, para in zip(macros, formulas, paragraphs):
        if "<math" not in para:
            failing.add(name)
    return failing


def macro_sample(base, preps, filter_path, macros_file, say):
    """Write latex-conversion-macros-sample.tex: the book's macros whose
    formulas texmath still can't read, a definition for each whose drawing
    has one reading, and the rest as written, for a person to define.
    preps: what prepare returned, for each of the book's documents, each
    probed with its own preamble. Returns (suggested, left)."""
    if isinstance(preps, dict):
        preps = [preps]
    defined, uses, failing, suggestions = {}, {}, set(), {}
    for prep in preps:
        copy = prep["copy"]
        texts = [read_text(os.path.join(copy, n)) for n in prep["files"]]
        own = definitions(texts)
        own_uses = math_uses(texts, sorted(own))
        used = [(n, own[n][0]) for n in sorted(own) if own_uses[n]]
        copy_preamble = split_master(read_text(prep["master"]))[0]
        own_failing = probe(copy, copy_preamble, used, filter_path)
        for name in own_failing:
            defined.setdefault(name, own[name])
            uses[name] = uses.get(name, 0) + own_uses[name]
        failing |= own_failing
        own_suggestions = {}
        for name in sorted(own_failing):
            s = suggest(own[name][1])
            if s is not None:
                own_suggestions[name] = s
        # Keep a suggestion only when texmath reads what it makes.
        extra = "".join("\\renewcommand{\\%s}%s{%s}\n" % (
            n, "[%d]" % own[n][0] if own[n][0] else "", s)
            for n, s in own_suggestions.items())
        still = probe(copy, copy_preamble, [(n, own[n][0]) for n in own_suggestions],
                      filter_path, extra) if own_suggestions else set()
        for name, s in own_suggestions.items():
            if name not in still:
                suggestions.setdefault(name, s)
    sample = os.path.join(base, SAMPLE)
    if not failing:
        if os.path.exists(sample):
            os.remove(sample)
        return 0, 0
    lines = [
        "% Written by convert.py: the book's macros whose formulas texmath",
        "% can't make MathML of, so they reach the pages as TeX. Check it,",
        "% then save it as " + macros_file + " (or merge it into yours).",
        "% Definitions there are read after the book's preamble, so they",
        "% win; the book's own files never change, and a source target",
        "% writes them into its copy unless its latex_definitions is off.", ""]
    for name in sorted(failing):
        args, body, written = defined[name]
        lines.append("%% \\%s is used in %d formula(s). The book has:" % (
            name, uses[name]))
        lines.extend("%   " + line for line in written.splitlines())
        if name in suggestions:
            lines.append("% Suggested: it draws what this says; check that it "
                         "means it.")
            lines.append("\\renewcommand{\\%s}%s{%s}" % (
                name, "[%d]" % args if args else "", suggestions[name]))
        else:
            lines.append("% Only a person can say what this draws:")
            lines.append("%% \\renewcommand{\\%s}%s{}" % (
                name, "[%d]" % args if args else ""))
        lines.append("")
    write_text(sample, "\n".join(lines))
    return len(suggestions), len(failing) - len(suggestions)
