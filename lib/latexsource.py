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
# before each \include in the copy and cut at afterwards; and one after
# each, where the master's own text begins again.
MARKER = "TextbookImproverPageMarker"
MARKER_LINE = MARKER + "%04d"
END_MARKER = "TextbookImproverPageEnd"
END_MARKER_LINE = END_MARKER + "%04d"
MARKER_TEXT = re.compile(r"^(%s|%s)(\d{4})$" % (MARKER, END_MARKER))
# Where the book's division commands stood (\frontmatter, \appendix, the
# appendix package's appendices), kept by the counting as an empty span
# for the cut, which takes them out.
DIVISION_CLASS = "textbookimprover-division"
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


def math_spans(text, spans=None):
    """The (start, end) of each formula in text's code, as MATH_SPANS finds
    them once comments and verbatim text are blanked, so a $ in a comment
    pairs with nothing."""
    spans = skip_spans(text) if spans is None else spans
    pieces, last = [], 0
    for start, end in spans:
        pieces.append(text[last:start])
        pieces.append(" " * (end - start))
        last = end
    pieces.append(text[last:])
    return [(m.start(), m.end()) for m in MATH_SPANS.finditer("".join(pieces))]


def escaped(text, pos):
    """Whether the character at pos follows an odd run of backslashes:
    \\\\noindent is a line break and a word, not \\noindent."""
    run = 0
    while pos - run - 1 >= 0 and text[pos - run - 1] == "\\":
        run += 1
    return run % 2 == 1


def unbalanced_braces(text):
    """(opened, closed): the position of each { in text's code that no }
    closes, and of each } that closes nothing, outside comments and
    verbatim text, \\{ and \\} not counted."""
    spans = skip_spans(text)
    opened, closed, i, s = [], [], 0, 0
    while i < len(text):
        while s < len(spans) and spans[s][1] <= i:
            s += 1
        if s < len(spans) and spans[s][0] <= i:
            i = spans[s][1]
            continue
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            opened.append(i)
        elif c == "}":
            if opened:
                opened.pop()
            else:
                closed.append(i)
        i += 1
    return opened, closed


def brace_problems(base, files):
    """["file:line", ...]: where a file the master reaches opens a { that
    it never closes, or closes a } it never opened, each file's first."""
    found = []
    for name in files:
        text = read_text(os.path.join(base, name))
        opened, closed = unbalanced_braces(text)
        for kind, at in (("a { that nothing in the file closes", opened[:1]),
                         ("a } that closes nothing", closed[:1])):
            for pos in at:
                found.append(f"{name}:{text.count(chr(10), 0, pos) + 1} ({kind})")
    return found


def package_names(value):
    """The names a \\usepackage{...} or \\RequirePackage{...} loads, its
    braces' content split at commas, a comment in it left out (OpenIntro's
    list of packages has a %tocloft, in it)."""
    return [n.strip() for n in re.sub(r"%[^\n]*", "", value).split(",") if n.strip()]


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
    \\input, \\include, and \\subfile, and through a call of one of the
    book's macros that does (include_macros), in the order first reached,
    and the names it gives that aren't there. A name inside a macro's
    definition made from its arguments (#2/TeX/#2) is the call's to make."""
    files, missing, texts, queue = [], [], {}, [master]
    folder = os.path.dirname(master)

    def add(target, waiting):
        path = resolve(base, target, folder)
        if path is None:
            if target not in missing:
                missing.append(target)
        elif path not in files and path not in waiting:
            waiting.append(path)
    while queue:
        while queue:
            name = queue.pop(0)
            if name in files:
                continue
            files.append(name)
            text = texts[name] = read_text(os.path.join(base, name))
            for m in code_matches(INPUT, text):
                target = m.group(2) or m.group(3)
                if not re.search(r"#\d", target):
                    add(target, queue)
        # The files the book's own macros reach, once their definitions
        # are read: OpenIntro's \includechapter{1}{ch_intro_to_data} in the
        # master, defined in a file the master \include-s later.
        macros = include_macros([(name, texts[name]) for name in files])
        for name in files:
            skip = sorted(skip_spans(texts[name])
                          + [(d[0], d[1]) for d in definitions_in(texts[name], ())])
            for _, _, targets in include_calls(texts[name], macros, skip):
                for target in targets:
                    add(target, queue)
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
    # The appendix package's environment, its files appendices.
    for m in code_matches(re.compile(r"\\(begin|end)\s*\{appendices\}"), body, spans):
        events.append((m.start(), "division", "appendix" if m.group(1) == "begin" else None))
    for m in code_matches(INCLUDE, body, spans):
        events.append((m.start(), "include", m.group(1)))
    events.sort()
    role, front_role, order, before = "main", None, [], "main"
    for _, kind, value in events:
        if kind == "division":
            # \\end{appendices} gives back the role before it.
            before, role = (role, value) if value else (before, before)
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


LAYOUT_COMMAND = re.compile(
    r"\\documentclass(?:\s|%[^\n]*)*(?:\[(?P<class_options>[^]]*)\])?(?:\s|%[^\n]*)*"
    r"\{\s*(?P<cls>[^}]*?)\s*\}"
    r"|\\usepackage(?:\s|%[^\n]*)*(?:\[(?P<package_options>[^]]*)\])?(?:\s|%[^\n]*)*"
    r"\{(?P<packages>[^}]*)\}"
    r"|\\PassOptionsToPackage\s*\{(?P<passed>[^{}]*)\}\s*\{\s*xcolor\s*\}"
    r"|\\geometry\s*\{(?P<geometry>(?:[^{}]|\{[^{}]*\})*)\}"
    r"|\\(?:setstretch|linespread)\s*\{\s*(?P<stretch>\d*\.?\d+)\s*\}"
    r"|\\(?P<spacing>singlespacing|onehalfspacing|doublespacing)(?![A-Za-z@])"
    r"|\\setlength\s*\{?\s*\\parindent\s*\}?\s*\{\s*(?P<parindent>[^{}]*?)\s*\}"
    r"|\\parindent\s*=?\s*(?P<assigned>\\z@|[+-]?\d*\.?\d+\s*(?:pt|em|ex|mm|cm|in|bp|pc|sp|dd|cc))")
SIZE_OPTION = re.compile(r"(?:fontsize=)?(1[012])pt")
PAPER_OPTION = re.compile(r"(?:(a[3-6]|b[4-6]|letter|legal|executive)paper"
                          r"|paper=(a[3-6]|b[4-6]|letter|legal|executive))")
SIDE_OPTIONS = ("oneside", "twoside", "openany", "openright")
# xcolor's sets of named colors, which a book's formulas can name and the
# PDF from its pages loads only when told: given as class options, which
# xcolor takes as its own (a starred set, defined as used, given whole).
XCOLOR_NAMES = ("dvipsnames", "svgnames", "x11names")
# setspace's spacing at 10pt, which \setstretch takes as Pandoc writes it.
SPACING = {"singlespacing": "1", "onehalfspacing": "1.25", "doublespacing": "1.667"}
ZERO_LENGTH = re.compile(r"\\z@|[+-]?0*\.?0*\s*(?:pt|em|ex|mm|cm|in|bp|pc|sp|dd|cc)?")


def option_list(value):
    """A comma list's items, split at the commas outside braces."""
    items, depth, current = [], 0, ""
    for ch in value:
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += ch
    items.append(current)
    return [" ".join(i.split()) for i in items if i.strip()]


# A command whose arguments hold code run somewhere else, in an
# environment or at a command, not where it's written: a setting in it isn't
# the book's page layout (\newenvironment{code}{\singlespacing...}). A hook
# that runs at \begin{document} is.
LOCAL_CODE = re.compile(
    r"\\(?:(?:re)?newenvironment|(?:New|Renew|Provide|Declare)Document(?:Environment|Command)"
    r"|(?:AtBegin|AtEnd|BeforeBegin|AfterEnd)Environment|AddToHook(?:Next)?|apptocmd"
    r"|pretocmd|patchcmd|(?:re)?newcommand|providecommand|DeclareRobustCommand|[gex]?def)"
    r"(?![A-Za-z@])\*?")
COMMENT = re.compile(r"(?<!\\)%[^\n]*")


def local_code_spans(text):
    """(start, end) of each LOCAL_CODE command with its arguments, braced,
    bracketed, or a control sequence named; a hook run at
    \\begin{document} left out."""
    spans = []
    for m in LOCAL_CODE.finditer(text):
        at, arguments, first = m.end(), 0, None
        while at < len(text) and arguments < 8:
            space = re.match(r"\s*", text[at:]).end()
            ch = text[at + space:at + space + 1]
            if ch == "{":
                end = matching_brace(text, at + space)
                if end < 0:
                    break
                if first is None:
                    first = text[at + space + 1:end - 1].strip()
            elif ch == "[":
                end = text.find("]", at + space)
                if end < 0:
                    break
                end += 1
            elif ch == "\\" and arguments == 0:
                name = re.match(r"\\(?:[A-Za-z@]+|.)", text[at + space:])
                end = at + space + len(name.group(0))
            elif ch == "#":
                end = at + space + 2
            else:
                break
            at, arguments = end, arguments + 1
        if m.group(0).startswith("\\AddToHook") and first is not None \
                and first.startswith("begindocument"):
            continue
        spans.append((m.start(), at))
    return spans


def page_layout(texts, includes=None):
    """What the book's preamble says of its pages that Pandoc's LaTeX
    writer has a variable for, under the names Pandoc gives them: fontsize
    and papersize from the class's options, the sides and chapter openings
    they choose (classoption), geometry's options, linestretch, and indent
    when the book's paragraphs are indented, as LaTeX's are unless the
    parskip package or a \\parindent of zero says otherwise, and xcolor's
    sets of named colors the book loads, as class options. For a PDF
    built from the pages, which would otherwise have Pandoc's 10pt type,
    its book class's margins, and parskip's spacing: FINC 308's 11pt and
    inch margins came out as 10pt in a narrower block. texts is [(name,
    text)], the master first; read in LaTeX's order (reading_order) up to
    the master's \\begin{document}, so a style file it \\input-s counts."""
    if not texts:
        return {}
    # Without comments, which may sit inside an option list (one per line,
    # each with its note), where the options are split at commas.
    texts = [(name, COMMENT.sub("", text)) for name, text in texts]
    master, text = texts[0]
    begin = code_matches(BEGIN_DOCUMENT, text)
    if not begin:
        return {}
    local = {name: local_code_spans(t) for name, t in texts}
    layout, geometry, indent = {}, [], True
    for kind, name, value in reading_order(texts, includes, at={master: [begin[0].start()]},
                                           watch=LAYOUT_COMMAND):
        if kind == "at":
            break
        if kind != "match" or in_spans(value.start(), local.get(name, [])):
            continue
        m = value
        if m.group("cls") is not None:
            for option in option_list(m.group("class_options") or ""):
                option = option.replace(" ", "")
                size, paper = SIZE_OPTION.fullmatch(option), PAPER_OPTION.fullmatch(option)
                if size:
                    layout["fontsize"] = size.group(1) + "pt"
                elif paper:
                    layout["papersize"] = paper.group(1) or paper.group(2)
                elif option.rstrip("*") in SIDE_OPTIONS + XCOLOR_NAMES \
                        and option.rstrip("*") not in layout.get("classoption", []):
                    layout.setdefault("classoption", []).append(option.rstrip("*"))
                elif option.startswith("parskip"):
                    # A KOMA class's own paragraph spacing.
                    indent = option in ("parskip=false", "parskip=off")
        elif m.group("packages") is not None or m.group("passed") is not None:
            names = package_names(m.group("packages")) if m.group("packages") is not None \
                else ["xcolor"]
            if "xcolor" in names:
                for option in option_list(m.group("package_options") or m.group("passed") or ""):
                    option = option.replace(" ", "").rstrip("*")
                    if option in XCOLOR_NAMES and option not in layout.get("classoption", []):
                        layout.setdefault("classoption", []).append(option)
            if "geometry" in names:
                geometry += option_list(m.group("package_options") or "")
            if "parskip" in names:
                indent = False
        elif m.group("geometry") is not None:
            geometry += option_list(m.group("geometry"))
        elif m.group("stretch") is not None:
            layout["linestretch"] = m.group("stretch")
        elif m.group("spacing") is not None:
            layout["linestretch"] = SPACING[m.group("spacing")]
        elif m.group("parindent") is not None or m.group("assigned") is not None:
            indent = not ZERO_LENGTH.fullmatch(m.group("parindent")
                                               if m.group("parindent") is not None
                                               else m.group("assigned"))
    # An option LaTeX's own commands would have to expand, which Pandoc's
    # writer would pass on as text, is left to the class's default.
    geometry = [o for o in geometry if "\\" not in o]
    if geometry:
        layout["geometry"] = geometry
    if layout.get("linestretch") in ("1", "1.0"):
        del layout["linestretch"]
    if indent:
        layout["indent"] = True
    return layout


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


def drop_command(text, command, signature, counter, key):
    """\\command taken out with its arguments, in code: signature gives
    them in order, o optional and m mandatory, each found as LaTeX finds
    it, past spaces, a comment, and one line end. For a layout command
    whose arguments the reader would print: Pandoc takes titlesec's
    \\titleformat only with its arguments on one line (getRawCommand's
    count 4 braced, Readers/LaTeX/Parsing.hs) and stops otherwise, and an
    unknown command's arguments on the next line become text."""
    pattern = re.compile(r"\\%s(?![A-Za-z@])\*?" % re.escape(command))
    spans = skip_spans(text)
    edits = []
    for m in pattern.finditer(text):
        if in_spans(m.start(), spans):
            continue
        pos = m.end()
        for kind in signature:
            at = argument_space(text, pos)
            if kind == "o":
                if text.startswith("[", at):
                    close = closing_bracket(text, at)
                    if close < 0:
                        break
                    pos = close + 1
                continue
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            pos = close
        else:
            edits.append((m.start(), pos))
    for start, end in reversed(edits):
        text = text[:start] + text[end:]
        counter[key] = counter.get(key, 0) + 1
    return text


def key_id(key):
    """A label's key as an id: no whitespace in it, and no {} a macro's end
    left in it."""
    return "-".join(key.replace("{}", "").split())


def normalize_keys(node):
    """Each id, link target, and reference the reader made of a label's key
    written as key_id has it, in place: LaTeX takes any text for a key
    (OpenIntro's \\label{US Airports}), and a macro in it expands
    (\\label{edwardSatBelow\\edwardsat{}}), but an id can't hold whitespace,
    nor a link's fragment a brace. After the reading, so a reference
    through the book's own macro, \\secref{US Airports} for Section~\\ref{#1},
    has been matched to its label, and numbered, as LaTeX matches it. A
    label with nothing in it is no id. Returns how many changed."""
    changed = 0
    if isinstance(node, list):
        for item in node:
            changed += normalize_keys(item)
    elif isinstance(node, dict):
        kind, c = node.get("t"), node.get("c")
        attr = c[1] if kind == "Header" else c[0] if kind in (
            "Div", "Span", "Figure", "Table", "CodeBlock", "Code", "Link", "Image") else None
        if attr is not None:
            if attr[0] != key_id(attr[0]):
                attr[0] = key_id(attr[0])
                changed += 1
            for pair in attr[2]:
                if pair[0] in ("label", "reference"):
                    pair[1] = key_id(pair[1])
        if kind == "Link" and c[2][0].startswith("#") and c[2][0] != "#" + key_id(c[2][0][1:]):
            c[2][0] = "#" + key_id(c[2][0][1:])
            changed += 1
        if c is not None:
            changed += normalize_keys(c)
    return changed


SUBFIGURE_COMMAND = re.compile(r"\\(?:subfigure|subfloat)(?![A-Za-z@])")
SUBCAPTIONBOX = re.compile(r"\\subcaptionbox(\*?)(?![A-Za-z@])")


def subfigures(text, counter):
    """The obsolete subfigure package's \\subfigure[caption]{...}, and
    subfig's \\subfloat, which Pandoc's reader doesn't know: its caption is
    dropped and the \\label in it is lost, so a reference to it goes
    nowhere (25 in OpenIntro Statistics), and a \\subfloat loses what it
    holds too. Written as subcaption's subfigure environment, which the
    reader makes a figure of its own, the label its id and the caption,
    when there is one, its caption."""
    spans = skip_spans(text)
    edits = []
    for m in SUBFIGURE_COMMAND.finditer(text):
        if in_spans(m.start(), spans) or (edits and m.start() < edits[-1][1]):
            continue
        pos, options = m.end(), []
        while len(options) < 2:
            at = argument_space(text, pos)
            if not text.startswith("[", at):
                break
            close = closing_bracket(text, at)
            if close < 0:
                break
            options.append(text[at + 1:close])
            pos = close + 1
        at = argument_space(text, pos)
        if not text.startswith("{", at):
            continue
        close = matching_brace(text, at)
        if close < 0:
            continue
        caption = options[-1].strip() if options else ""
        edits.append((m.start(), close, "\\begin{subfigure}{\\linewidth}%s%s\\end{subfigure}" % (
            text[at + 1:close - 1], "\\caption{%s}" % caption if caption else "")))
    # subcaption's \\subcaptionbox[list]{caption}[width][position]{contents}.
    for m in SUBCAPTIONBOX.finditer(text):
        if in_spans(m.start(), spans) or any(a <= m.start() < b for a, b, _ in edits):
            continue
        pos, groups = m.end(), []
        for shape in "[{[[{":
            at = argument_space(text, pos)
            if shape == "[":
                if text.startswith("[", at):
                    close = closing_bracket(text, at)
                    if close < 0:
                        break
                    pos = close + 1
                continue
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            groups.append(text[at + 1:close - 1])
            pos = close
        if len(groups) == 2:
            edits.append((m.start(), pos, "\\begin{subfigure}{\\linewidth}%s\\caption%s{%s}"
                          "\\end{subfigure}" % (groups[1], m.group(1), groups[0])))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
        counter["subfigures"] = counter.get("subfigures", 0) + 1
    return text


# floatrow's boxes, which the reader drops with the captions they hold (a
# \ref to one read its label's name): \ffigbox, \ttabbox, and \fcapside,
# [width][height][position]{caption}{object}, floatrow taking both into the
# box whichever holds the \caption. A floatrow of them is figures side by
# side, as minipages are; subfloatrow's subfigures are left as they are.
FLOATROW_BOX = re.compile(r"\\(ffigbox|ttabbox|fcapside)(?![A-Za-z@])")
FLOATROW_EDGE = re.compile(r"\\(begin|end)\s*\{floatrow\}")


def floatrow_boxes(text, counter):
    """Each of floatrow's boxes outside a subfloatrow written as a minipage
    of what it holds, and a floatrow's edges left out, so split_floats
    makes a float of each box with a caption."""
    spans = skip_spans(text)
    inner = []
    for m in re.finditer(r"\\begin\s*\{subfloatrow\}", text):
        stop = environment_end(text, "subfloatrow", m.start())
        if stop > 0 and not in_spans(m.start(), spans):
            inner.append((m.start(), stop))
    skip = sorted(spans + inner)
    edits = []
    for m in FLOATROW_BOX.finditer(text):
        if in_spans(m.start(), skip) or escaped(text, m.start()):
            continue
        pos, args = m.end(), []
        for _ in range(3):
            at = argument_space(text, pos)
            if not text.startswith("[", at):
                break
            close = closing_bracket(text, at)
            if close < 0:
                break
            pos = close + 1
        while len(args) < 2:
            at = argument_space(text, pos)
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            args.append(text[at + 1:close - 1])
            pos = close
        if len(args) == 2:
            edits.append((m.start(), pos, "\\begin{minipage}{\\linewidth}%s\n%s\\end{minipage}"
                          % tuple(args)))
    boxes = len(edits)
    if edits:
        for m in FLOATROW_EDGE.finditer(text):
            if in_spans(m.start(), skip) or escaped(text, m.start()):
                continue
            pos = m.end()
            at = argument_space(text, pos)
            if m.group(1) == "begin" and text.startswith("[", at):
                close = closing_bracket(text, at)
                pos = close + 1 if close > 0 else pos
            edits.append((m.start(), pos, ""))
    for start, end, words in sorted(edits, reverse=True):
        text = text[:start] + words + text[end:]
    if boxes:
        counter["floatrow_boxes"] = counter.get("floatrow_boxes", 0) + boxes
    return text


WRAP_EDGE = re.compile(r"\\(begin|end)\s*\{(wrapfigure|wraptable)\}")


def wrapped_floats(text, counter):
    """wrapfig's wrapfigure and wraptable, which the reader keeps as a
    division with their arguments shown as text ("r 0.4") and the caption
    and label dropped: written as a figure and a table, which the reader
    takes whole. That the text flows around it is the page's layout."""
    spans = skip_spans(text)
    edits = []
    for m in WRAP_EDGE.finditer(text):
        if in_spans(m.start(), spans):
            continue
        kind = "figure" if m.group(2) == "wrapfigure" else "table"
        if m.group(1) == "end":
            edits.append((m.start(), m.end(), "\\end{%s}" % kind))
            continue
        # [lines]{placement}[overhang]{width}
        pos = m.end()
        for opener in "[{[{":
            at = argument_space(text, pos)
            if not text.startswith(opener, at):
                if opener == "{":
                    break
                continue
            close = closing_bracket(text, at) + 1 if opener == "[" else matching_brace(text, at)
            if close <= 0:
                break
            pos = close
        edits.append((m.start(), pos, "\\begin{%s}" % kind))
        counter["wrapped_floats"] = counter.get("wrapped_floats", 0) + 1
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text


TABLE_FLOAT = re.compile(r"\\begin\s*\{(table\*?)\}")
TABLE_EDGE = re.compile(r"\\(begin|end)\s*\{(tabular\*?|tabularx|tabulary|longtable|supertabular"
                        r"|tabu|NiceTabular|tblr|longtblr)\}")
HOLDS_IMAGE = re.compile(r"\\(?:includegraphics|begin\s*\{(?:picture|tikzpicture)\})")
TABLE_INPUT = re.compile(r"\\(?:input|include|import|subimport)(?![A-Za-z@])")
# What a float holds a part of with a caption of its own: subfig's \subfloat,
# the subfigure package's \subfigure, and subcaption's environments.
SUBFLOAT = re.compile(r"\\(?:subfloat|subfigure|subcaptionbox)(?![A-Za-z@])"
                      r"|\\begin\s*\{(subtable|subfigure)\}")
SUBTABLE_EDGE = re.compile(r"\\(begin|end)\s*\{subtable\}")


FLOAT_BEGIN = re.compile(r"\\begin\s*\{(figure\*?|table\*?)\}")
CAPTION_COMMAND = re.compile(r"\\caption(?![A-Za-z@])\s*\*?")
SUBFLOAT_ENVIRONMENT = re.compile(r"\\begin\s*\{(subfigure|subtable)\}")
NESTING = re.compile(r"\\(begin|end)\s*\{\s*([A-Za-z@*]+)\s*\}|(?<!\\)[{}]")
# Environments a float's parts can be cut out of, closed and opened again.
CUT_WRAPPERS = ("center", "flushleft", "flushright")
# A tabular's text but for the minipages it lays out in a row, when it holds
# nothing else: its arguments, then cells' and rows' ends, rules, and
# spaces.
_GRID_CELLS = r"(?:\s|&|\\\\(?:\[[^\]]*\])?|\\(?:hline|centering|hfill|quad|qquad|noindent)" \
    r"(?![A-Za-z@])|%[^\n]*)*"
_GRID_GROUP = r"\s*\{(?:[^{}]|\{[^{}]*\})*\}"
_GRID_OPTION = r"(?:\s*\[[^\]]*\])?"
GRID_REST = {"tabular": re.compile(_GRID_OPTION + _GRID_GROUP + _GRID_CELLS),
             "tabular*": re.compile(_GRID_GROUP + _GRID_OPTION + _GRID_GROUP + _GRID_CELLS),
             "tabularx": re.compile(_GRID_GROUP + _GRID_GROUP + _GRID_CELLS)}


def nesting_at(text, start, pos, spans):
    """The environments open at pos, from start, as their \\begin matches,
    and how many braces are, or None when they don't nest."""
    stack, depth = [], 0
    for e in NESTING.finditer(text, start, pos):
        if in_spans(e.start(), spans) or escaped(text, e.start()):
            continue
        if e.group(1) == "begin":
            stack.append(e)
        elif e.group(1) == "end":
            if not stack or stack[-1].group(2) != e.group(2):
                return None
            stack.pop()
        else:
            depth += 1 if e.group(0) == "{" else -1
            if depth < 0:
                return None
    return stack, depth


def split_floats(text, counter):
    """A figure or table float holding two captions or more of its own (two
    figures side by side, each in a minipage with its caption), which LaTeX
    numbers apart and the reader makes one float of, the last caption's
    and label's: each caption's minipage, when it's the float's own,
    written as a float of the float's kind, or, outside any box, the float
    cut after each caption and the label after it (before each caption
    when the first comes before what it captions, as a table's often
    does), a center or a flush environment around them closed and opened
    again there. A layout of any other kind is left as it is. A
    subfigure's or a subtable's caption is the float's part's, not its
    own; the float's own above its parts goes after them, where the reader
    gives the float the last caption it meets."""
    spans = skip_spans(text)
    edits = []
    for m in FLOAT_BEGIN.finditer(text):
        if in_spans(m.start(), spans):
            continue
        kind = m.group(1)
        end = environment_end(text, kind, m.start())
        close = re.compile(r"\\end\s*\{" + re.escape(kind) + r"\}\Z").search(
            text, m.end(), end) if end > 0 else None
        if not close:
            continue
        # Its parts' spans: subcaption's environments, and \subfloat's and
        # \subfigure's arguments.
        parts = []
        for p in SUBFLOAT_ENVIRONMENT.finditer(text, m.end(), close.start()):
            stop = environment_end(text, p.group(1), p.start())
            if stop > 0:
                parts.append((p.start(), stop))
        for p in SUBFIGURE_COMMAND.finditer(text, m.end(), close.start()):
            parts.append((p.start(), _arguments_span(text, p.end())))
        for p in SUBCAPTIONBOX.finditer(text, m.end(), close.start()):
            parts.append((p.start(), _arguments_span(text, p.end())))
        skip = sorted(spans + parts)
        captions = [c for c in CAPTION_COMMAND.finditer(text, m.end(), close.start())
                    if not in_spans(c.start(), skip) and not escaped(text, c.start())]

        def caption_end(c):
            stop = _arguments_span(text, c.end())
            label = re.compile(r"(?:\s|%[^\n]*\n)*\\label\s*\{[^{}]*\}").match(text, stop)
            return label.end() if label else stop
        if len(captions) == 1 and parts and captions[0].start() < min(a for a, _ in parts):
            stop = caption_end(captions[0])
            found = nesting_at(text, m.end(), captions[0].start(), spans)
            if found and not found[0] and not found[1] and stop <= min(a for a, _ in parts):
                edits.append((captions[0].start(), stop, ""))
                edits.append((close.start(), close.start(), text[captions[0].start():stop]))
                counter["captions_moved"] = counter.get("captions_moved", 0) + 1
            continue
        if len(captions) < 2:
            continue
        nest = [nesting_at(text, m.end(), c.start(), spans) for c in captions]
        if any(n is None for n in nest):
            continue
        # Each caption in a minipage of the float's own, one each.
        boxes = [n[0][0] if len(n[0]) == 1 and n[0][0].group(2) == "minipage" else None
                 for n in nest]
        if all(boxes) and len({b.start() for b in boxes}) == len(boxes) \
                and all(nesting_at(text, b.end(), c.start(), spans) == ([], 0)
                        for b, c in zip(boxes, captions)):
            at = argument_space(text, m.end())
            bracket = closing_bracket(text, at) if text.startswith("[", at) else -1
            mine = [(m.start(), bracket + 1 if bracket > 0 else m.end(), ""),
                    (close.start(), close.end(), "")]
            for box in boxes:
                stop = environment_end(text, "minipage", box.start())
                inner = re.compile(r"\\end\s*\{minipage\}\Z").search(text, box.end(), stop) \
                    if stop > 0 else None
                # \begin{minipage}[pos][height][inner]{width}
                pos = box.end()
                for _ in range(3):
                    at = argument_space(text, pos)
                    bracket = closing_bracket(text, at) if text.startswith("[", at) else -1
                    if bracket < 0:
                        break
                    pos = bracket + 1
                at = argument_space(text, pos)
                width = matching_brace(text, at) if text.startswith("{", at) else -1
                if not inner or width < 0:
                    break
                mine += [(box.start(), width, "\\begin{%s}" % kind),
                         (inner.start(), stop, "\\end{%s}" % kind)]
            else:
                edits += mine
                counter["split_floats"] = counter.get("split_floats", 0) + 1
            continue
        # Each caption in a minipage of one tabular of the float's own that
        # holds nothing else, a row of figures: each minipage a float of its
        # own, the tabular left out.
        rows = [n[0] for n in nest]
        if all(len(r) == 2 and r[0].group(2) in GRID_REST and r[1].group(2) == "minipage"
               for r in rows) and len({r[0].start() for r in rows}) == 1 \
                and len({r[1].start() for r in rows}) == len(rows) \
                and nesting_at(text, m.end(), rows[0][0].start(), spans) == ([], 0) \
                and all(nesting_at(text, r[1].end(), c.start(), spans) == ([], 0)
                        for r, c in zip(rows, captions)):
            grid = rows[0][0]
            stop = environment_end(text, grid.group(2), grid.start())
            last = re.compile(r"\\end\s*\{" + re.escape(grid.group(2)) + r"\}\Z").search(
                text, grid.end(), stop) if stop > 0 else None
            made, rest, pos = [], [], grid.end()
            for box in [r[1] for r in rows] if last else []:
                end = environment_end(text, "minipage", box.start())
                inner = re.compile(r"\\end\s*\{minipage\}\Z").search(text, box.end(), end) \
                    if end > 0 else None
                at = box.end()
                for _ in range(3):
                    skip_to = argument_space(text, at)
                    bracket = closing_bracket(text, skip_to) if text.startswith("[", skip_to) \
                        else -1
                    if bracket < 0:
                        break
                    at = bracket + 1
                at = argument_space(text, at)
                width = matching_brace(text, at) if text.startswith("{", at) else -1
                if not inner or width < 0:
                    break
                rest.append(text[pos:box.start()])
                made.append("\\begin{%s}%s\\end{%s}" % (kind, text[width:inner.start()], kind))
                pos = end
            else:
                if last and GRID_REST[grid.group(2)].fullmatch(
                        "".join(rest) + text[pos:last.start()]):
                    at = argument_space(text, m.end())
                    bracket = closing_bracket(text, at) if text.startswith("[", at) else -1
                    edits += [(m.start(), bracket + 1 if bracket > 0 else m.end(), ""),
                              (close.start(), close.end(), ""),
                              (grid.start(), stop, "\n".join(made))]
                    counter["split_floats"] = counter.get("split_floats", 0) + 1
                    continue
        # Each caption in a \\parbox of the float's own, one each: the box's
        # text a float of its own.
        boxed = []
        for box in re.finditer(r"\\parbox(?![A-Za-z@])", text[:close.start()]):
            if box.start() < m.end() or in_spans(box.start(), spans):
                continue
            # \\parbox[pos][height][inner]{width}{text}
            pos, groups = box.end(), []
            while len(groups) < 2:
                at = argument_space(text, pos)
                if text.startswith("[", at) and not groups:
                    bracket = closing_bracket(text, at)
                    if bracket < 0:
                        break
                    pos = bracket + 1
                elif text.startswith("{", at):
                    stop = matching_brace(text, at)
                    if stop < 0:
                        break
                    groups.append((at, stop))
                    pos = stop
                else:
                    break
            if len(groups) == 2:
                boxed.append((box, groups[1][0], groups[1][1]))
        holders = []
        for c in captions:
            holder = next((b for b in boxed if b[1] < c.start() < b[2]), None)
            if holder is None or nesting_at(text, m.end(), holder[0].start(), spans) != ([], 0) \
                    or nesting_at(text, holder[1] + 1, c.start(), spans) != ([], 0):
                break
            holders.append(holder)
        else:
            if len({h[0].start() for h in holders}) == len(holders):
                at = argument_space(text, m.end())
                bracket = closing_bracket(text, at) if text.startswith("[", at) else -1
                edits.append((m.start(), bracket + 1 if bracket > 0 else m.end(), ""))
                edits.append((close.start(), close.end(), ""))
                for box, content, arguments in holders:
                    edits.append((box.start(), content + 1, "\\begin{%s}" % kind))
                    edits.append((arguments - 1, arguments, "\\end{%s}" % kind))
                counter["split_floats"] = counter.get("split_floats", 0) + 1
                continue
        # Outside any box: cut, a wrapper around the captions closed and
        # opened again at each cut.
        above = not (TABLE_EDGE.search(text, m.end(), captions[0].start())
                     or HOLDS_IMAGE.search(text, m.end(), captions[0].start()))
        cuts = []
        for at, c in enumerate(captions[:-1]):
            stop = captions[at + 1].start() if above else caption_end(c)
            found = nesting_at(text, m.end(), stop, spans)
            if found is None or found[1] or any(e.group(2) not in CUT_WRAPPERS
                                                for e in found[0]):
                break
            wrappers = list(found[0])
            # A wrapper with nothing left in it ends where it does, not
            # opened again empty.
            while wrappers:
                end = environment_end(text, wrappers[-1].group(2), wrappers[-1].start())
                tail = re.compile(r"\\end\s*\{" + re.escape(wrappers[-1].group(2))
                                  + r"\}\Z").search(text, stop, end) if end > 0 else None
                if not tail or text[stop:tail.start()].strip():
                    break
                stop = end
                wrappers.pop()
            cuts.append((stop, stop, "".join("\\end{%s}" % e.group(2)
                                             for e in reversed(wrappers))
                         + "\\end{%s}\\begin{%s}" % (kind, kind)
                         + "".join(text[e.start():e.end()] for e in wrappers)))
        else:
            edits += cuts
            counter["split_floats"] = counter.get("split_floats", 0) + 1
    for start, stop, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[stop:]
    return text


def top_tables(body, spans=()):
    """How many tables body holds, a table in another's cell not counted."""
    depth = count = 0
    for e in TABLE_EDGE.finditer(body):
        if in_spans(e.start(), spans):
            continue
        if e.group(1) == "begin":
            count += depth == 0
            depth += 1
        else:
            depth = max(depth - 1, 0)
    return count


def table_floats(text, counter):
    """A table float with a caption that isn't one table to the reader: one
    holding no table (an image of one, or a box), whose caption the reader
    drops, since it gives it only to a table; one holding two tables, each
    of which it gives the caption and the label; and one holding subtables
    (\\subfloat, subcaption's subtable), whose captions it gives way to the
    float's. Written as a figure, a subtable as a subfigure, with a mark
    that the counting numbers it as the table it is, and its subtables by
    letter (1.2a)."""
    spans = skip_spans(text)
    edits = []
    for m in TABLE_FLOAT.finditer(text):
        if in_spans(m.start(), spans):
            continue
        end = environment_end(text, m.group(1), m.start())
        if end < 0:
            continue
        body = text[m.end():end]
        body_spans = skip_spans(body)
        body_spans = sorted(body_spans + math_spans(body, body_spans))
        if not re.search(r"\\caption(?![A-Za-z@])", body):
            continue
        tables = top_tables(body, body_spans)
        subfloats = any(not in_spans(s.start(), body_spans) for s in SUBFLOAT.finditer(body))
        # One with no table the copy can see may hold one a macro or an
        # environment of the book's own makes: it's left to the reader
        # unless it holds an image or a drawing, or its only caption is a
        # \\caption*, a note (one under a table, which split_floats cut off).
        note = [c.group(0).rstrip().endswith("*") for c in CAPTION_COMMAND.finditer(body)
                if not in_spans(c.start(), body_spans)] == [True]
        if tables == 1 and not subfloats or tables == 0 and (
                TABLE_INPUT.search(body) or not (HOLDS_IMAGE.search(body) or note)):
            continue
        close = re.compile(r"\\end\s*\{" + re.escape(m.group(1)) + r"\}\Z").search(
            text, m.end(), end)
        if not close:
            continue
        # The mark after the placement, which the reader takes only first.
        at = argument_space(text, m.end())
        bracket = closing_bracket(text, at) if text.startswith("[", at) else -1
        after = bracket + 1 if bracket > 0 else m.end()
        edits.append((close.start(), end, "\\end{figure}"))
        for s in SUBTABLE_EDGE.finditer(text, m.end(), close.start()):
            if not in_spans(s.start(), spans):
                edits.append((s.start(), s.end(), "\\%s{subfigure}" % s.group(1)))
        edits.append((after, after, counter_mark("tablefloat")))
        edits.append((m.start(), m.end(), "\\begin{figure}"))
        counter["table_floats"] = counter.get("table_floats", 0) + 1
    for start, stop, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[stop:]
    return text


CAPTIONOF = re.compile(r"\\captionof\s*(\*?)\s*\{\s*(figure|table)\s*\}")
ANY_ENVIRONMENT_EDGE = re.compile(r"\\(begin|end)\s*\{\s*([A-Za-z@*]+)\s*\}")
PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
# What a paragraph doesn't run past: a heading, \par, an \item.
PARAGRAPH_EDGE = re.compile(r"\\(?:part|chapter|section|subsection|subsubsection|paragraph"
                            r"|subparagraph)\*?(?![A-Za-z@*])|\\par(?![A-Za-z@])"
                            r"|\\item(?![A-Za-z@])")
# The environments whose whole a \captionof in them captions.
CAPTION_BOXES = ("minipage", "center", "flushleft", "flushright", "varwidth",
                 "boxedminipage", "tcolorbox", "mdframed", "framed")
# Environments set in the line, which don't end a paragraph as a list, a
# center, or a theorem does.
INLINE_BOXES = ("tabular", "tabular*", "tabularx", "tabulary", "minipage", "varwidth",
                "tikzpicture", "picture", "pspicture", "array")


def captionof_floats(text, counter):
    """\\captionof{figure}{...}, a caption outside a float, which the reader
    drops with its text and label (a reference to it reads [key]):
    \\caption, and what it captions, the box it's in (a minipage, a center)
    or else its paragraph, set in a figure or a table, as LaTeX numbers and
    labels it. A paragraph begins after a blank line, \\par, an \\item, a
    heading and the label after it, or the end of an environment that ends
    a paragraph, and ends at the next of them or the next environment; an
    environment of that kind right before the caption, nothing but space
    between, is what it captions, and so is one right before that. One in
    a macro's definition is read inside the definition's body, as the
    macro sets it where it's used."""
    spans = skip_spans(text)
    found = [m for m in CAPTIONOF.finditer(text) if not in_spans(m.start(), spans)]
    if not found:
        return text
    # Each definition's body, a region of its own.
    bodies = [(d[1] - 1 - len(d[5]), d[1] - 1) for d in definitions_in(text, spans)]

    def region(pos):
        return next(((a, b) for a, b in bodies if a <= pos < b), None)

    def options_end(pos):
        """Past the [options] at pos, if any."""
        at = argument_space(text, pos)
        while text.startswith("[", at):
            close = closing_bracket(text, at)
            if close < 0:
                break
            pos, at = close + 1, argument_space(text, close + 1)
        return pos
    edges = [e for e in ANY_ENVIRONMENT_EDGE.finditer(text) if not in_spans(e.start(), spans)
             and not escaped(text, e.start())]
    bounds = [(e.start(), options_end(e.end()) if e.group(1) == "begin" else e.end())
              for e in edges if e.group(2) not in INLINE_BOXES]
    for e in PARAGRAPH_EDGE.finditer(text):
        if in_spans(e.start(), spans) or escaped(text, e.start()):
            continue
        name = re.match(r"\\([A-Za-z]+)", e.group(0)).group(1)
        if name == "par":
            end = e.end()
        elif name == "item":
            end = options_end(e.end())
        else:
            end = _arguments_span(text, e.end())
            label = re.compile(r"\s*\\label\s*\{[^{}]*\}").match(text, end)
            end = label.end() if label else end
        bounds.append((e.start(), end))

    def matching_begin(close):
        """The \\begin an \\end edge closes, or None."""
        depth = 0
        for e in reversed([e for e in edges if e.start() < close.start()]):
            if e.group(2) != close.group(2):
                continue
            if e.group(1) == "end":
                depth += 1
            elif depth:
                depth -= 1
            else:
                return e
        return None

    def paragraph(m, low, high):
        """The paragraph m is in, within low and high."""
        pos = m.start()
        while True:
            # An environment ending right before what's taken so far.
            before = len(text[low:pos].rstrip()) + low
            close = next((e for e in edges if e.group(1) == "end" and e.end() == before
                          and e.group(2) not in INLINE_BOXES), None)
            begin = matching_begin(close) if close else None
            if begin is None or begin.start() < low:
                break
            pos = begin.start()
        breaks = [b.end() for b in PARAGRAPH_BREAK.finditer(text, low, pos)]
        start = max([low] + breaks[-1:] + [stop for begin, stop in bounds
                                           if low <= stop <= pos])
        after = PARAGRAPH_BREAK.search(text, m.end(), high)
        end = min([after.start() if after else high]
                  + [begin for begin, _ in bounds if m.end() <= begin < high])
        return start, end

    def own(m):
        """The caption alone, with a \\label after it."""
        at = m.end()
        for opener in "[{":
            pos = argument_space(text, at)
            if text.startswith(opener, pos):
                close = closing_bracket(text, pos) + 1 if opener == "[" \
                    else matching_brace(text, pos)
                if close > 0:
                    at = close
        label = re.compile(r"\s*\\label\s*\{[^{}]*\}").match(text, at)
        return m.start(), label.end() if label else at
    places, edits = {}, []
    for m in found:
        low, high = region(m.start()) or (0, len(text))
        stack = []
        for e in edges:
            if e.start() >= m.start():
                break
            if not low <= e.start() < high:
                continue
            if e.group(1) == "begin":
                stack.append(e)
            elif stack and stack[-1].group(2) == e.group(2):
                stack.pop()
        env = stack[-1] if stack else None
        if env is not None and env.group(2) in ("figure", "figure*", "table", "table*"):
            # In a float already: its caption.
            edits.append((m.start(), m.end(), 1, "\\caption" + m.group(1)))
            continue
        if env is None or env.group(2) not in CAPTION_BOXES:
            place = paragraph(m, low, high)
        else:
            end = environment_end(text, env.group(2), env.start())
            if end < 0 or end > high:
                continue
            place = (env.start(), end)
        places.setdefault(place, []).append(m)

    def wrap(start, end, m):
        # Ranked so that where one float ends and the next begins, the
        # end comes first.
        edits.extend([(start, start, 2, "\\begin{%s}" % m.group(2)),
                      (m.start(), m.end(), 1, "\\caption" + m.group(1)),
                      (end, end, 0, "\\end{%s}" % m.group(2))])
    for (start, end), held in places.items():
        if len(held) > 1:
            # Two captions in one environment: each a figure of its own,
            # what it captions left before it.
            for m in held:
                wrap(*own(m), m)
        else:
            wrap(start, end, held[0])
    for start, end, _, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    counter["captionof"] = counter.get("captionof", 0) + len(found)
    return text


# hyperref's \autoref and cleveref's commands, which print a name before
# the number (Figure 1.2, fig. 1.2, figs. 1.1 to 1.3): the reader reads
# \autoref and \cref alike, as the number alone, \cref{a,b} as one link to
# a label named "a,b", and drops \crefrange and \namecref, text and all.
# Each is written as a \ref with the command in its key, which the
# counting reads and gives LaTeX's text.
REF_PREFIX = "TEXTBOOKIMPROVERREF"
REFERENCE_COMMAND = re.compile(r"\\(autoref|cref|Cref|crefrange|Crefrange|labelcref"
                               r"|namecref|nameCref|lcnamecref)\*?\s*\{")


def reference_commands(text, counter):
    # One in a formula is the counting's math_refs's, which texmath reads.
    spans = skip_spans(text)
    spans = sorted(spans + math_spans(text, spans))
    edits = []
    for m in REFERENCE_COMMAND.finditer(text):
        if in_spans(m.start(), spans) or escaped(text, m.start()):
            continue
        close = matching_brace(text, m.end() - 1)
        if close < 0:
            continue
        keys, end = text[m.end():close - 1], close
        if m.group(1) in ("crefrange", "Crefrange"):
            at = argument_space(text, close)
            second = matching_brace(text, at) if text.startswith("{", at) else -1
            if second < 0:
                continue
            keys, end = keys + "," + text[at + 1:second - 1], second
        edits.append((m.start(), end, "\\ref{%s:%s:%s}" % (REF_PREFIX, m.group(1), keys)))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    if edits:
        counter["named_refs"] = counter.get("named_refs", 0) + len(edits)
    return text


# The names hyperref's \autoref (English) and cleveref (English, abbrev
# on, capitalise off) print, by the counter or type a label is of, as
# measured with LaTeX 2026-06-01; and the types cleveref reads as another.
AUTOREF_NAMES = {"equation": "Equation", "footnote": "footnote", "item": "item",
                 "figure": "Figure", "subfigure": "Figure", "table": "Table",
                 "subtable": "Table", "part": "Part", "appendix": "Appendix",
                 "chapter": "chapter", "section": "section", "subsection": "subsection",
                 "subsubsection": "subsubsection", "paragraph": "paragraph",
                 "subparagraph": "subparagraph", "theorem": "Theorem", "page": "page",
                 "enumi": "item", "enumii": "item", "enumiii": "item", "enumiv": "item"}
CREF_NAMES = {"figure": ("fig.", "figs."), "equation": ("eq.", "eqs."),
              "table": ("table", "tables"), "page": ("page", "pages"),
              "part": ("part", "parts"), "chapter": ("chapter", "chapters"),
              "section": ("section", "sections"), "appendix": ("appendix", "appendices"),
              "enumi": ("item", "items"), "footnote": ("footnote", "footnotes"),
              "theorem": ("theorem", "theorems"), "lemma": ("lemma", "lemmas"),
              "corollary": ("corollary", "corollaries"),
              "proposition": ("proposition", "propositions"),
              "definition": ("definition", "definitions"), "result": ("result", "results"),
              "example": ("example", "examples"), "remark": ("remark", "remarks"),
              "note": ("note", "notes"), "algorithm": ("algorithm", "algorithms"),
              "listing": ("listing", "listings"), "line": ("line", "lines")}
CREF_FULL = {"figure": ("figure", "figures"), "equation": ("equation", "equations")}
CREF_ALIASES = {"subsection": "section", "subsubsection": "section", "subfigure": "figure",
                "subtable": "table", "enumii": "enumi", "enumiii": "enumi", "enumiv": "enumi"}
CREFNAME = re.compile(r"\\(c|C)refname\s*\{\s*([A-Za-z@*]+)\s*\}\s*\{([^{}]*)\}\s*\{([^{}]*)\}")


def _upper_first(words):
    return words[:1].upper() + words[1:]


def _lower_first(words):
    return words[:1].lower() + words[1:]


def reference_name(names, command, kind, plural=False):
    """The name a reference command prints before a label's number, or
    None: kind is (what the label is of, whether it's in the appendices,
    the counter a theorem counts with), names book_counters's ref_names.
    hyperref names a theorem by its environment, not the counter it
    shares (\\newtheorem{lemma}[theorem]{Lemma}: Lemma 2, by
    \\lemmaautorefname, measured with LaTeX 2026-06-01), and one with no
    name of its own by none."""
    what, appendix, _ = kind
    if command == "autoref":
        kind_name = what
        if appendix in ("top", "second"):
            kind_name = "appendix"
        name = names.get("autoref", {}).get(kind_name)
        if name is None and kind_name not in AUTOREF_NAMES:
            name = names.get("name", {}).get(kind_name)
        if name is None:
            name = AUTOREF_NAMES.get(kind_name)
        return name
    kind_name = CREF_ALIASES.get(what, what)
    capitalise = names.get("capitalise")
    own, own_capital = names.get("cref", {}).get(kind_name), names.get("Cref", {}).get(kind_name)
    if command in ("Cref", "Crefrange", "nameCref"):
        if own_capital:
            pair = own_capital
        elif own:
            pair = tuple(_upper_first(w) for w in own)
        elif kind_name in CREF_NAMES:
            pair = tuple(_upper_first(w) for w in CREF_FULL.get(kind_name, CREF_NAMES[kind_name]))
        else:
            return None
    else:
        if own:
            pair = own
        elif own_capital:
            pair = own_capital if capitalise else tuple(_lower_first(w) for w in own_capital)
        elif kind_name in CREF_NAMES:
            pair = (CREF_FULL if names.get("noabbrev") else {}).get(kind_name,
                                                                   CREF_NAMES[kind_name])
            if capitalise:
                pair = tuple(_upper_first(w) for w in pair)
        else:
            return None
        if command == "lcnamecref":
            pair = tuple(_lower_first(w) for w in pair)
    return pair[1] if plural else pair[0]


# \nameref, which prints the title of the section a label is in and which
# Pandoc's reader drops, text and all: a link to the label with this for
# its text, which convert.py's fill_namerefs gives the title once the pages
# are read.
NAMEREF = re.compile(r"\\[nN]ameref\*?\s*\{([^{}]*)\}")
NAMEREF_MARK = "TEXTBOOKIMPROVERNAMEREF"
GROUP_COMMAND = re.compile(r"\\(begingroup|endgroup)(?![A-Za-z@])")


def math_definitions(text, spans, names):
    """The (start, end) of each definition in text of a macro in names."""
    return [(d[0], d[1]) for d in definitions_in(text, spans) if d[2] in names]


def group_commands(text, counter, math_macros=()):
    """Each \\begingroup and the \\endgroup that closes it at the same
    depth of braces, written as \\/{ and }, outside formulas. Pandoc's
    reader takes \\endgroup for a }, but \\begingroup only where a group
    opens, at a group's start or in a paragraph; elsewhere it drops it as a
    command it doesn't know, so the \\endgroup closes the group around it
    (OpenIntro's chapter openings: {\\Large \\begingroup ... \\par
    \\endgroup} stops the reader). The \\/, an italic correction, which
    the reader reads as nothing, keeps the brace from a command before it:
    the reader takes every braced group after one it doesn't know as its
    arguments (keep_groups), so \\noindent{ lost the group's text. One left
    open, in a macro that another closes, is left as it is, and so is one
    in the definition of a macro in math_macros, which a formula uses."""
    spans = skip_spans(text)
    found = [m for m in GROUP_COMMAND.finditer(text) if not in_spans(m.start(), spans)]
    if not found:
        return text
    # The brace group each is in, by where it opens (-1 for none): a pair
    # must share one, not only a depth, or \begingroup in one macro's body
    # would pair with \endgroup in the next's.
    group_at, opened, s, i = {}, [-1], 0, 0
    marks = {m.start() for m in found}
    while i < len(text):
        while s < len(spans) and spans[s][1] <= i:
            s += 1
        if s < len(spans) and spans[s][0] <= i:
            i = spans[s][1]
            continue
        c = text[i]
        if i in marks:
            group_at[i] = opened[-1]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            opened.append(i)
        elif c == "}" and len(opened) > 1:
            opened.pop()
        i += 1
    # One the walk stepped over follows a backslash (\\begingroup is a
    # line break and a word); one in a formula is texmath's, which doesn't
    # read \/.
    math = sorted(math_spans(text, spans) + math_definitions(text, spans, math_macros))
    found = [m for m in found if m.start() in group_at and not in_spans(m.start(), math)]
    pairs, stack = [], []
    for m in found:
        if m.group(1) == "begingroup":
            stack.append(m)
        elif stack and group_at[stack[-1].start()] == group_at[m.start()]:
            pairs.append((stack.pop(), m))
        else:
            stack = []
    edits = sorted([(o.start(), o.end(), "\\/{") for o, _ in pairs]
                   + [(c.start(), c.end(), "}") for _, c in pairs], reverse=True)
    for start, end, brace in edits:
        text = text[:start] + brace + text[end:]
    if pairs:
        counter["group_commands"] = counter.get("group_commands", 0) + len(pairs)
    return text


# Environments of packages the reader (3.12) doesn't know, whose arguments
# it prints as text, measured: multicols's column count, a 2 before the
# columns' text. Each with its arguments as LaTeX takes them: o an optional
# argument, m a mandatory one, p an optional one LaTeX prints before the
# environment (multicols's preface, often a heading).
ENVIRONMENT_ARGUMENTS = {"multicols": "mpo", "multicols*": "mpo", "spacing": "m",
                         "Spacing": "m", "adjustwidth": "mm", "adjustwidth*": "mm",
                         "addmargin": "om", "addmargin*": "om", "paracol": "mp",
                         "parcolumns": "om", "boxedminipage": "om"}
ENVIRONMENT_BEGIN = re.compile(r"\\begin\s*\{(%s)\}" % "|".join(
    re.escape(n) for n in sorted(ENVIRONMENT_ARGUMENTS, key=len, reverse=True)))


def environment_arguments(text, counter):
    """Each of ENVIRONMENT_ARGUMENTS begun without the arguments the reader
    would print, a preface written before it, as LaTeX prints it."""
    spans = skip_spans(text)
    edits = []
    for m in ENVIRONMENT_BEGIN.finditer(text):
        if in_spans(m.start(), spans) or escaped(text, m.start()):
            continue
        pos, preface = m.end(), ""
        for kind in ENVIRONMENT_ARGUMENTS[m.group(1)]:
            at = argument_space(text, pos)
            if kind in "op":
                if text.startswith("[", at):
                    close = closing_bracket(text, at)
                    if close < 0:
                        break
                    preface = text[at + 1:close] if kind == "p" else preface
                    pos = close + 1
                continue
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            pos = close
        edits.append((m.start(), pos, ("\n\n" + preface.strip() + "\n\n" if preface.strip()
                                       else "") + "\\begin{%s}" % m.group(1)))
    for start, end, words in reversed(edits):
        text = text[:start] + words + text[end:]
    if edits:
        counter["environment_arguments"] = counter.get("environment_arguments", 0) + len(edits)
    return text


# Space between words a command sets, which the reader (3.12) drops in
# text, so the words on either side run together (measured: A\hspace{1cm}B,
# A\quad B, A\hfill B, and A\enspace B are all "AB"; the calculus notes'
# example label, \fbox{...}\hspace{2mm} before its title, read
# "ExCalculating" 111 times). A space before such a command keeps them
# apart; one of less than 2pt, a sliver inside a name (OpenIntro's
# sex\_\hspace{0.3mm}male), or less than none, is no space between words.
WORD_SPACING = re.compile(r"\\(hspace\*?|hfill|hfil|quad|qquad|enspace|enskip)(?![A-Za-z@])")
POINTS = {"pt": 1.0, "mm": 2.845, "cm": 28.45, "in": 72.27, "bp": 1.004, "pc": 12.0,
          "dd": 1.07, "cc": 12.84, "em": 10.0, "ex": 4.3, "sp": 1 / 65536}


def word_spaces(text, counter, math_macros=()):
    """A space before each of WORD_SPACING's commands in text that sets a
    space between words, where there's none before it, so the reader keeps
    the words apart; not in a formula, nor in the definition of a macro a
    formula uses (math_macros' names), which is left as the book wrote it."""
    spans = skip_spans(text)
    math = sorted(math_spans(text, spans) + math_definitions(text, spans, math_macros))
    edits = []
    for m in WORD_SPACING.finditer(text):
        if in_spans(m.start(), spans) or in_spans(m.start(), math) or escaped(text, m.start()) \
                or not m.start() or text[m.start() - 1].isspace():
            continue
        if m.group(1).startswith("hspace"):
            at = argument_space(text, m.end())
            close = matching_brace(text, at) if text.startswith("{", at) else -1
            if close < 0:
                continue
            length = text[at + 1:close - 1].strip()
            size = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([a-z]{2})", length)
            if length.startswith("-") or size and float(size.group(1)) * POINTS.get(
                    size.group(2), 0) < 2:
                continue
        edits.append(m.start())
    for pos in reversed(edits):
        text = text[:pos] + " " + text[pos:]
    if edits:
        counter["word_spaces"] = counter.get("word_spaces", 0) + len(edits)
    return text


# Boxes Pandoc's reader (3.12) drops with all they hold, as commands it
# doesn't know (measured): each with its arguments as LaTeX takes them, the
# last mandatory one what the box holds. A table in \resizebox, which a
# book sets to fit the page, was lost whole.
BOXES = {"makebox": "oom", "framebox": "oom", "fbox": "m", "raisebox": "moom",
         "smash": "om", "fcolorbox": "ommm", "scalebox": "mom", "resizebox": "smmm",
         "rotatebox": "omm", "boxed": "m", "shadowbox": "m", "ovalbox": "m",
         "Ovalbox": "m", "doublebox": "m", "text": "m", "adjustbox": "mm"}
BOX = re.compile(r"\\(%s)(?![A-Za-z@])" % "|".join(
    re.escape(n) for n in sorted(BOXES, key=len, reverse=True)))


def unwrap_boxes(text, counter, math_macros=()):
    """Each of BOXES outside formulas, and the definitions of macros
    formulas use, written as a group of what it holds, which the reader
    reads; the box itself, a frame or a size, is the page's layout. The
    innermost first, so a box in a box is read too."""
    while True:
        spans = skip_spans(text)
        math = sorted(math_spans(text, spans) + math_definitions(text, spans, math_macros))
        found = None
        for m in BOX.finditer(text):
            if in_spans(m.start(), spans) or in_spans(m.start(), math) \
                    or escaped(text, m.start()):
                continue
            pos, content = m.end(), None
            for kind in BOXES[m.group(1)]:
                if kind == "s":
                    star = re.compile(r"[ \t]*\*").match(text, pos)
                    if star:
                        pos = star.end()
                    continue
                at = argument_space(text, pos)
                if kind == "o":
                    if text.startswith("[", at):
                        close = closing_bracket(text, at)
                        if close < 0:
                            break
                        pos = close + 1
                    continue
                if not text.startswith("{", at):
                    break
                close = matching_brace(text, at)
                if close < 0:
                    break
                content, pos = (at, close), close
            else:
                if content:
                    found = (m.start(), pos, content)
        if not found:
            return text
        start, end, (at, close) = found
        text = text[:start] + text[at:close] + text[end:]
        counter["boxes_unwrapped"] = counter.get("boxes_unwrapped", 0) + 1


# Commands Pandoc's reader (3.12) doesn't know, or knows only to skip, and
# so takes with every braced group after them (getRawCommand's many
# braced, Readers/LaTeX/Parsing.hs), each with its arguments as LaTeX
# takes them: s a star, o an optional argument, m a mandatory one. Each was
# measured losing a group after its arguments.
RAW_COMMANDS = {
    "hspace": "sm", "vspace": "sm", "addvspace": "m", "enlargethispage": "sm",
    "noindent": "", "indent": "", "centering": "", "raggedleft": "", "RaggedRight": "",
    "bigskip": "", "medskip": "", "smallskip": "", "clearpage": "", "cleardoublepage": "",
    "newpage": "", "pagebreak": "o", "nopagebreak": "o", "linebreak": "o",
    "nolinebreak": "o", "selectfont": "", "normalfont": "", "fontfamily": "m",
    "fontseries": "m", "fontshape": "m", "fontsize": "mm", "usefont": "mmmm",
    "setlength": "mm", "addtolength": "mm", "settowidth": "mm", "setcounter": "mm",
    "addtocounter": "mm", "stepcounter": "m", "refstepcounter": "m", "index": "om",
    "glossary": "m", "pagestyle": "m", "thispagestyle": "m", "phantomsection": "",
    "leavevmode": "", "protect": "", "nointerlineskip": "", "relax": "", "null": "",
    "ignorespaces": "", "unskip": "", "sloppy": "", "fussy": "", "frenchspacing": "",
    "justifying": "", "onehalfspacing": "", "doublespacing": "", "singlespacing": "",
    "setstretch": "m", "hypersetup": "m", "pdfbookmark": "omm", "markboth": "mm",
    "markright": "m", "addcontentsline": "mmm", "tableofcontents": "",
    "captionsetup": "om", "color": "om", "definecolor": "ommm", "colorlet": "omm",
    "pageref": "sm", "makebox": "oom", "raisebox": "moom", "smash": "om",
    "phantom": "m", "hphantom": "m", "vphantom": "m",
}
RAW_COMMAND = re.compile(r"\\(%s)(?![A-Za-z@])" % "|".join(
    re.escape(n) for n in sorted(RAW_COMMANDS, key=len, reverse=True)))
# What the reader takes for a dimension after such a command before any
# braced group (dimenarg, Readers/LaTeX/Parsing.hs): past spaces, comments,
# and one line end, a number, a unit or not.
NUMBER_AFTER = re.compile(r"(?:[ \t]|%[^\n]*)*(?:\n(?![ \t]*\n)(?:[ \t]|%[^\n]*)*)?"
                          r"(?==?-?(?:\d|\.\d))")


def keep_groups(text, counter, math_macros=()):
    """A \\/ before a group that follows one of RAW_COMMANDS's arguments,
    and before a number that follows one with no argument, outside
    formulas, so the reader reads them. It takes every braced group after
    such a command as the command's and drops them, and a number right
    after it as its dimension, where LaTeX takes only the command's own
    arguments. OpenIntro Statistics's exercise solutions are
    \\hspace{2mm}{\\small#1}, after \\hypersetup{linkcolor=oiB}{...} around
    {\\fontfamily{phv}\\selectfont 1.1}, and its appendix of solutions came
    out with neither the solutions nor their numbers. The \\/, an italic
    correction, is nothing to the reader and ends the command's arguments.
    A command's own spaces, before a group, are its own to TeX and to the
    reader alike; a space after an argument ends them. Nothing goes in
    the definition of a macro in math_macros, which texmath reads in a
    formula, and it doesn't read \\/."""
    spans = skip_spans(text)
    math = sorted(math_spans(text, spans) + math_definitions(text, spans, math_macros))
    inserts = []
    for m in RAW_COMMAND.finditer(text):
        if in_spans(m.start(), spans) or in_spans(m.start(), math) \
                or escaped(text, m.start()):
            continue
        pos, took = m.end(), False
        for kind in RAW_COMMANDS[m.group(1)]:
            if kind == "s":
                star = re.compile(r"[ \t]*\*").match(text, pos)
                if star:
                    pos = star.end()
                continue
            at = argument_space(text, pos)
            if kind == "o":
                if text.startswith("[", at):
                    close = closing_bracket(text, at)
                    if close < 0:
                        break
                    pos, took = close + 1, True
                continue
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            pos, took = close, True
        else:
            if took:
                if text.startswith("{", pos):
                    inserts.append(pos)
                continue
            at = re.compile(r"[ \t]*").match(text, pos).end()
            if text.startswith("{", at):
                inserts.append(at)
                continue
            number = NUMBER_AFTER.match(text, pos)
            if number:
                inserts.append(number.end())
    for at in reversed(inserts):
        text = text[:at] + "\\/" + text[at:]
    if inserts:
        counter["kept_groups"] = counter.get("kept_groups", 0) + len(inserts)
    return text


# titlesec's commands, which say how headings look, with their arguments.
# The starred \titleformat, titlesec's easy form, takes only the
# command and its format, and goes first, before the full form's optional
# star would take it.
TITLESEC_COMMANDS = (("titleformat*", "mm"), ("titleformat", "mommmmo"),
                     ("titlespacing", "mmmmo"), ("titlelabel", "m"))


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


def repair_text(text, counter, math_macros=(), counters=()):
    """The rewrites every file of the copy gets: booleans as toggles,
    \\input braced, artifact images marked, and the rest. math_macros: the
    names of the macros formulas use (math_macros); counters, the book's
    counters' names (book_counters)."""
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
    for command, signature in TITLESEC_COMMANDS:
        text = drop_command(text, command, signature, counter, "titlesec")
    text = environment_arguments(text, counter)
    text = floatrow_boxes(text, counter)
    text = word_spaces(text, counter, math_macros)
    # Floats whose captions the reader drops, before the counting marks
    # what numbers them.
    text = wrapped_floats(text, counter)
    text = captionof_floats(text, counter)
    text = split_floats(text, counter)
    text = table_floats(text, counter)
    text = reference_commands(text, counter)
    text = unwrap_boxes(text, counter, math_macros)
    text = group_commands(text, counter, math_macros)
    text = counter_marks(text, counter, math_macros, counters)
    text = keep_groups(text, counter, math_macros)
    text = substitute(NAMEREF, text, lambda m: "\\hyperref[%s]{%s}" % (
        m.group(1).strip(), NAMEREF_MARK), counter, "nameref")
    text = subfigures(text, counter)
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


def write_out_item_refs(texts, counter, names=None):
    """texts ({name: text}) with each \\ref to an enumerated item's label
    written as the number LaTeX gives it, and an \\autoref's or cleveref's
    (as reference_commands wrote it) with the name it prints, item 1:
    names, book_counters's ref_names."""
    labels = {}
    for text in texts.values():
        labels.update(item_labels(text))
    if not labels:
        return texts
    for name, text in texts.items():
        spans = skip_spans(text)
        count = [0]

        def one(m):
            key = m.group(1).strip()
            if in_spans(m.start(), spans):
                return m.group(0)
            if key.startswith(REF_PREFIX + ":"):
                _, command, keys = key.split(":", 2)
                keys = [k.strip() for k in keys.split(",") if k.strip()]
                if not keys or not all(k in labels for k in keys):
                    return m.group(0)
                count[0] += 1
                numbers = [labels[k] for k in keys]
                if command in ("crefrange", "Crefrange") and len(numbers) == 2:
                    numbers = ["%s to~%s" % tuple(numbers)]
                joined = numbers[0] if len(numbers) == 1 else \
                    ", ".join(numbers[:-1]) + " and~" + numbers[-1]
                word = reference_name(names or {}, command, ("enumi", None, None),
                                      plural=len(keys) > 1)
                if command in ("namecref", "nameCref", "lcnamecref"):
                    return word or joined
                return "%s~%s" % (word, joined) if word and command != "labelcref" else joined
            if key not in labels:
                return m.group(0)
            count[0] += 1
            return labels[key]
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


def case_match(base, path):
    """path, relative to base, found as a file system that ignores case
    finds it, a part at a time, where exactly one entry matches each
    part; or None."""
    found, current = [], base
    for part in os.path.normpath(path).split(os.sep):
        if part in ("", "."):
            continue
        if part != "..":
            try:
                entries = os.listdir(current)
            except OSError:
                return None
            if part not in entries:
                matches = [e for e in entries if e.lower() == part.lower()]
                if len(matches) != 1:
                    return None
                part = matches[0]
        found.append(part)
        current = os.path.join(current, part)
    return os.path.join(*found) if found and os.path.isfile(current) else None


def resolve_graphic(base, name, dirs, counter=None):
    """The file graphicx would include for name, relative to base, or
    None. A name that differs from its file only in case is the file, as
    macOS and Windows find it, where the book was likely built (OpenIntro
    Statistics's solutions name GRE_intro.pdf, and the file is
    gre_intro.pdf); LaTeX on Linux doesn't find it, so it's counted."""
    name = name.strip()
    for exact in (True, False):
        for d in [""] + dirs:
            for ext in ("",) + GRAPHICS_EXTENSIONS:
                candidate = os.path.normpath(os.path.join(d, name + ext))
                if not (ext or os.path.splitext(name)[1]):
                    continue
                if exact and os.path.isfile(os.path.join(base, candidate)):
                    return candidate
                if not exact:
                    found = case_match(base, candidate)
                    if found:
                        if counter is not None:
                            counter["graphics_case"] = counter.get("graphics_case", 0) + 1
                        return found
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
        path = resolve_graphic(base, name, dirs, counter)
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
    \\includegraphics whose file is made from its arguments (one or more:
    OpenIntro's \\Figures puts a folder and a file in
    \\chapterfolder/figures/#3/#4); else None."""
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
    used = {int(n) for n in re.findall(r"#(\d)", path)}
    if not used or max(used) > arguments:
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


def definitions_in(text, skip):
    """Each definition in text outside the spans in skip, \\newcommand and
    its kin or \\def with plain arguments, in order: (start, end, name,
    arguments, default, body, provide), end just past the body's closing
    brace, default the first argument's when it's optional, else None, and
    provide whether it's \\providecommand."""
    found = []
    for m in MACRO_DEFINITION.finditer(text):
        if in_spans(m.start(), skip):
            continue
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
        found.append((m.start(), close, m.group(1) or m.group(2), int(m.group(3) or 0),
                      default, text[pos + 1:close - 1],
                      text.startswith("\\providecommand", m.start())))
    for m in PLAIN_DEFINITION.finditer(text):
        if in_spans(m.start(), skip):
            continue
        close = matching_brace(text, m.end() - 1)
        if close < 0:
            continue
        found.append((m.start(), close, m.group(1), len(re.findall(r"#\d", m.group(2))),
                      None, text[m.end():close - 1], False))
    return sorted(found)


def _input_target(by_name, name, target):
    """The text in by_name a file name's \\input of target reads, or None."""
    target = target.strip().strip('"')
    folder = os.path.dirname(name)
    for candidate in (os.path.join(folder, target), os.path.join(folder, target + ".tex"),
                      target, target + ".tex"):
        if os.path.normpath(candidate) in by_name:
            return os.path.normpath(candidate)
    return None


def reading_order(texts, includes=None, after_preamble=None, at=None, watch=None):
    """What LaTeX meets in the book's files, in the order it reads them:
    texts is [(name, text)], the master first, and each file is read where
    it's \\input or \\include-d, or where a call of one of includes
    (include_macros) puts it; after_preamble, a name in texts, is read at
    the master's \\begin{document}, as a person's definitions file is.
    Yields (kind, text's name, item): "spans" once for each text, with the
    (start, end) of every definition in it; "define", definitions_in's
    tuple; "at", for each position at gives the text, the position; and
    "match", each of watch's matches in code outside a definition."""
    by_name = dict(texts)
    master = texts[0][0] if texts else None
    visited = set()

    def walk(name):
        if name in visited or name not in by_name:
            return
        visited.add(name)
        text = by_name[name]
        skip = skip_spans(text)
        found = definitions_in(text, skip)
        yield "spans", name, [(d[0], d[1]) for d in found]
        inside = sorted(skip + [(d[0], d[1]) for d in found])
        events = [(d[0], 1, "define", d) for d in found]
        events += [(m.start(), 0, "input", m.group(2) or m.group(3) or "")
                   for m in INPUT.finditer(text) if not in_spans(m.start(), inside)]
        for start, _, targets in include_calls(text, includes or {}, inside):
            events += [(start, 0, "input", target) for target in targets]
        if name == master and after_preamble:
            begin = code_matches(BEGIN_DOCUMENT, text, skip)
            if begin:
                events.append((begin[0].start(), 0, "after preamble", after_preamble))
        events += [(pos, 2, "at", pos) for pos in (at or {}).get(name, ())]
        if watch is not None:
            events += [(m.start(), 1, "match", m) for m in watch.finditer(text)
                       if not in_spans(m.start(), inside)]
        for _, _, kind, value in sorted(events, key=lambda e: (e[0], e[1])):
            if kind == "input":
                target = _input_target(by_name, name, value)
                if target:
                    yield from walk(target)
            elif kind == "after preamble":
                yield from walk(value)
            else:
                yield kind, name, value
    for name, _ in texts:
        yield from walk(name)


def macro_walk(texts, describe, includes=None, after_preamble=None, at=None):
    """The book's definitions, read as LaTeX reads them (reading_order, which
    takes texts, includes, after_preamble, and at), so a later definition
    replaces an earlier one, and \\providecommand defines only a name
    nothing has defined yet. describe(body, arguments, default) is what a
    definition makes of its macro, or None for one of no interest.

    Returns (macros, spans, values): {name: description}; {text's name:
    [(start, end)]}, the span of every definition in each text; and for
    each (text's name, position) in at, a list of positions by text, the
    value there of each macro defined without arguments, {name: body}, as
    \\chapterfolder is set at each chapter's start (OpenIntro Statistics)."""
    macros, defined, values, spans_by_text, snapshots = {}, set(), {}, {}, {}

    def define(found, arguments, default, body, provide):
        if provide and found in defined:
            return
        defined.add(found)
        macro = describe(body, arguments, default)
        if macro:
            macros[found] = macro
        else:
            macros.pop(found, None)
        if arguments == 0 and default is None:
            values[found] = body
        else:
            values.pop(found, None)
    for kind, name, value in reading_order(texts, includes, after_preamble, at):
        if kind == "spans":
            spans_by_text[name] = value
        elif kind == "define":
            define(*value[2:])
        elif kind == "at":
            snapshots[(name, value)] = dict(values)
    return macros, spans_by_text, snapshots


def image_macros(texts, includes=None, after_preamble=None):
    """({name: macro}, {text's name: [(start, end)]}): each macro the book
    defines, with \\newcommand and its kin or \\def with plain arguments,
    whose body holds one \\includegraphics with its file made from one of
    its arguments, and the span of every definition in each text. A macro
    is a dict: arguments, how many; default, the first one's when it's
    optional, else None; file, the file as the body writes it, #1 and
    all; body, the whole body; alt, the argument the body's own alt key
    takes, or None; keyed, whether the body gives alt text or artifact of
    its own. texts, includes, and after_preamble are as macro_walk reads
    them."""
    return macro_walk(texts, image_macro, includes, after_preamble)[:2]


def include_macro(body, arguments, default):
    """The macro, if its body \\include-s or \\input-s a file whose name
    is made from one of its arguments, as OpenIntro Statistics's
    \\includechapter{1}{ch_intro_to_data} \\include-s
    ch_intro_to_data/TeX/ch_intro_to_data: a dict of arguments, default
    (as image_macros has them), body, and targets, the names as the body
    writes them, #2 and all. Else None."""
    if "##" in body:
        return None
    skip = skip_spans(body)
    targets = [m.group(2) or m.group(3) for m in INPUT.finditer(body)
               if not in_spans(m.start(), skip)]
    if not any(re.search(r"#\d", t) for t in targets):
        return None
    return {"arguments": arguments, "default": default, "body": body, "targets": targets}


def include_macros(texts):
    """{name: macro}: each macro the book defines that \\include-s or
    \\input-s a file named by its arguments (include_macro). texts is as
    macro_walk reads it."""
    return macro_walk(texts, include_macro)[0]


def with_arguments(body, args):
    """body with each #n the call's nth argument, as TeX expands it."""
    return re.sub(r"#(\d)", lambda m: args[int(m.group(1)) - 1][0]
                  if int(m.group(1)) <= len(args) else m.group(0), body)


def include_calls(text, macros, skip):
    """(start, end, targets) for each call in text, outside skip, of one
    of macros (include_macros): the names the call \\include-s or
    \\input-s, as it makes them."""
    return [(start, end, [with_arguments(t, args).strip() for t in macros[name]["targets"]])
            for start, end, name, args in macro_calls(text, macros, skip)]


ARGUMENT_SPACE = re.compile(r"(?:[ \t]*%[^\n]*\n)*[ \t]*(?:\n(?:[ \t]*%[^\n]*\n)*[ \t]*)?")


def argument_space(text, pos):
    """Past the spaces TeX skips before an argument: blanks, comments
    with the line end they take, and at most one line end of its own,
    since a blank line is a paragraph."""
    return ARGUMENT_SPACE.match(text, pos).end()


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


NEWENVIRONMENT = re.compile(r"\\(re)?newenvironment\s*\{\s*([A-Za-z@]+)\s*\}")
ENVIRONMENT_EDGE = re.compile(r"\\(begin|end)\s*\{\s*([A-Za-z@]+)\s*\}")


def environment_definitions_in(text, spans=None):
    """(start, stop, renew, name, spec, bodies) for each \\newenvironment and
    \\renewenvironment in text's code whose codes are both braced, spec its
    [n][default] as written and bodies its two codes, braces and all, and
    none made inside another's codes."""
    spans = skip_spans(text) if spans is None else spans
    found = []
    for m in NEWENVIRONMENT.finditer(text):
        if in_spans(m.start(), spans):
            continue
        pos, spec = m.end(), ""
        for _ in range(2):          # [n] and [default]
            at = argument_space(text, pos)
            if not text.startswith("[", at):
                break
            close = closing_bracket(text, at)
            if close < 0:
                break
            spec += text[at:close + 1]
            pos = close + 1
        bodies = []
        for _ in range(2):          # {opening} and {closing}
            at = argument_space(text, pos)
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            bodies.append(text[at:close])
            pos = close
        if len(bodies) == 2:
            found.append((m.start(), pos, bool(m.group(1)), m.group(2), spec, bodies))
    return [d for d in found if not any(o[0] < d[0] < o[1] for o in found)]


def environment_definitions(texts, files, counter):
    """Each environment the book defines with \\newenvironment written, in
    the reading copy, as LaTeX defines it: a command \\name for its opening
    code and \\endname for its closing, each \\begin{name} and \\end{name}
    as those commands. Pandoc's reader puts a group around the codes
    (Readers/LaTeX/Macro.hs, the \\bgroup newenvironment prepends), and
    stops where that group meets the book's own: on the opening command
    called alone, \\var{x}, as LaTeX allows and OpenIntro Statistics does
    about 1,700 times (\\var, \\resp, \\data, \\eoce), since nothing closes
    the group; and on {\\raggedright\\begin{parts}...\\end{parts}}, where
    the group's \\bgroup, after a command, is dropped as one the reader
    doesn't know and its \\egroup closes the braces (Readers/LaTeX.hs,
    blockCommand). Without the group the reader reads them as LaTeX does;
    a definition made inside the environment holds after it. One defined
    in another's codes, and LaTeX's own that the book redefines with
    \\renewenvironment (enumerate), are left to the reader: the commands
    would hold from the start of the book, where LaTeX's definitions do
    until the book's are made. texts: {name: text}, changed in place."""
    defined = set()
    for name in files:
        for d in environment_definitions_in(texts[name]):
            if not d[2]:
                defined.add(d[3])
    if not defined:
        return
    for name in files:
        text = texts[name]
        # \begin{name} and \end{name} first, in the definitions' codes too.
        spans = skip_spans(text)
        edges = []
        for m in ENVIRONMENT_EDGE.finditer(text):
            if m.group(2) in defined and not in_spans(m.start(), spans):
                # A space ends the command's name, as TeX takes it, so the
                # next letters aren't read as more of it.
                edges.append((m.start(), m.end(), "\\%s%s " % (
                    "" if m.group(1) == "begin" else "end", m.group(2))))
        for start, stop, replacement in reversed(edges):
            text = text[:start] + replacement + text[stop:]
        edits = []                      # (start, stop, replacement)
        for start, stop, renew, env, spec, bodies in environment_definitions_in(text):
            if env not in defined:
                continue
            command = "\\%snewcommand" % ("re" if renew else "")
            edits.append((start, stop, "%s{\\%s}%s%s%s{\\end%s}%s" % (
                command, env, spec, bodies[0], command, env, bodies[1])))
            counter["environment_definitions"] = counter.get("environment_definitions", 0) + 1
        for start, stop, replacement in reversed(edits):
            text = text[:start] + replacement + text[stop:]
        counter["environment_edges"] = counter.get("environment_edges", 0) + len(edges)
        texts[name] = text


DEFINECOLOR = re.compile(r"\\(definecolor|providecolor)\s*(?:\[[^]]*\])?\s*\{\s*([^{}]+?)\s*\}"
                         r"\s*\{\s*([A-Za-z]+)\s*\}\s*\{\s*([^{}]*?)\s*\}")
COLORLET = re.compile(r"\\colorlet\s*(?:\[[^]]*\])?\s*\{\s*([^{}]+?)\s*\}\s*(?:\[[^]]*\])?"
                      r"\s*\{\s*([^{}]*?)\s*\}")
COLOR_STATEMENT = re.compile("(?:%s)|(?:%s)" % (DEFINECOLOR.pattern, COLORLET.pattern))
COLOR_USE = re.compile(r"\\(textcolor|colorbox)\s*(?:\[\s*([A-Za-z]+)\s*\])?\s*\{\s*([^{}]*?)\s*\}")
# The colors xcolor defines itself, as it defines them (rgb), and the set
# its dvipsnames option loads (dvipsnam.def, in cmyk), for a color a book
# mixes (red!50!black) or names that CSS doesn't have (BrickRed): CSS knows
# some of the names, with values of its own, and none of the mixes.
XCOLOR_BASE = {"red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "cyan": (0, 1, 1),
               "magenta": (1, 0, 1), "yellow": (1, 1, 0), "black": (0, 0, 0),
               "white": (1, 1, 1), "gray": (.5, .5, .5), "darkgray": (.25, .25, .25),
               "lightgray": (.75, .75, .75), "brown": (.75, .5, .25), "lime": (.75, 1, 0),
               "olive": (.5, .5, 0), "orange": (1, .5, 0), "pink": (1, .75, .75),
               "purple": (.75, 0, .25), "teal": (0, .5, .5), "violet": (.5, 0, .5)}
DVIPSNAMES = {
    "GreenYellow": "0.15,0,0.69,0", "Yellow": "0,0,1,0", "Goldenrod": "0,0.10,0.84,0",
    "Dandelion": "0,0.29,0.84,0", "Apricot": "0,0.32,0.52,0", "Peach": "0,0.50,0.70,0",
    "Melon": "0,0.46,0.50,0", "YellowOrange": "0,0.42,1,0", "Orange": "0,0.61,0.87,0",
    "BurntOrange": "0,0.51,1,0", "Bittersweet": "0,0.75,1,0.24",
    "RedOrange": "0,0.77,0.87,0", "Mahogany": "0,0.85,0.87,0.35",
    "Maroon": "0,0.87,0.68,0.32", "BrickRed": "0,0.89,0.94,0.28", "Red": "0,1,1,0",
    "OrangeRed": "0,1,0.50,0", "RubineRed": "0,1,0.13,0",
    "WildStrawberry": "0,0.96,0.39,0", "Salmon": "0,0.53,0.38,0",
    "CarnationPink": "0,0.63,0,0", "Magenta": "0,1,0,0", "VioletRed": "0,0.81,0,0",
    "Rhodamine": "0,0.82,0,0", "Mulberry": "0.34,0.90,0,0.02",
    "RedViolet": "0.07,0.90,0,0.34", "Fuchsia": "0.47,0.91,0,0.08",
    "Lavender": "0,0.48,0,0", "Thistle": "0.12,0.59,0,0", "Orchid": "0.32,0.64,0,0",
    "DarkOrchid": "0.40,0.80,0.20,0", "Purple": "0.45,0.86,0,0", "Plum": "0.50,1,0,0",
    "Violet": "0.79,0.88,0,0", "RoyalPurple": "0.75,0.90,0,0",
    "BlueViolet": "0.86,0.91,0,0.04", "Periwinkle": "0.57,0.55,0,0",
    "CadetBlue": "0.62,0.57,0.23,0", "CornflowerBlue": "0.65,0.13,0,0",
    "MidnightBlue": "0.98,0.13,0,0.43", "NavyBlue": "0.94,0.54,0,0",
    "RoyalBlue": "1,0.50,0,0", "Blue": "1,1,0,0", "Cerulean": "0.94,0.11,0,0",
    "Cyan": "1,0,0,0", "ProcessBlue": "0.96,0,0,0", "SkyBlue": "0.62,0,0.12,0",
    "Turquoise": "0.85,0,0.20,0", "TealBlue": "0.86,0,0.34,0.02",
    "Aquamarine": "0.82,0,0.30,0", "BlueGreen": "0.85,0,0.33,0", "Emerald": "1,0,0.50,0",
    "JungleGreen": "0.99,0,0.52,0", "SeaGreen": "0.69,0,0.50,0", "Green": "1,0,1,0",
    "ForestGreen": "0.91,0,0.88,0.12", "PineGreen": "0.92,0,0.59,0.25",
    "LimeGreen": "0.50,0,1,0", "YellowGreen": "0.44,0,0.74,0",
    "SpringGreen": "0.26,0,0.76,0", "OliveGreen": "0.64,0,0.95,0.40",
    "RawSienna": "0,0.72,1,0.45", "Sepia": "0,0.83,1,0.70", "Brown": "0,0.81,1,0.60",
    "Tan": "0.14,0.42,0.56,0", "Gray": "0,0,0,0.50", "Black": "0,0,0,1",
    "White": "0,0,0,0"}
# CSS's color keywords (CSS Color 4), which a page may name as they are.
CSS_COLORS = frozenset("""
    aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
    blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk
    crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki
    darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
    darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue
    dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite
    gold goldenrod gray grey green greenyellow honeydew hotpink indianred indigo ivory khaki
    lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen
    lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen
    linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple
    mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred
    midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab
    orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip
    peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue
    saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue
    slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet
    wheat white whitesmoke yellow yellowgreen transparent currentcolor""".split())


def rgb_color(model, spec):
    """A color as xcolor gives it, in one of its models, as (r, g, b) from
    0 to 1, or None for a model or value this doesn't take."""
    parts = [p.strip() for p in spec.split(",")]
    try:
        if model == "rgb":
            rgb = [float(p) for p in parts]
        elif model == "RGB":
            rgb = [float(p) / 255 for p in parts]
        elif model == "HTML" and re.fullmatch(r"[0-9A-Fa-f]{6}", spec):
            rgb = [int(spec[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        elif model == "gray" and len(parts) == 1:
            rgb = [float(parts[0])] * 3
        elif model == "cmyk" and len(parts) == 4:
            c, m, y, k = (float(p) for p in parts)
            rgb = [(1 - v) * (1 - k) for v in (c, m, y)]
        else:
            return None
    except ValueError:
        return None
    if len(rgb) != 3:
        return None
    return tuple(max(0.0, min(1.0, v)) for v in rgb)


def css_rgb(rgb):
    return "rgb(%d, %d, %d)" % tuple(round(v * 255) for v in rgb)


def css_color(model, spec):
    """A color as xcolor gives it, in one of its models, as CSS: rgb(...),
    or None for a model or value this doesn't take."""
    rgb = rgb_color(model, spec)
    return css_rgb(rgb) if rgb else None


XCOLOR_SET_FILES = {"svgnames": "svgnam.def", "x11names": "x11nam.def"}
_XCOLOR_SETS = {}


def xcolor_sets(options):
    """{name: (r, g, b)} of xcolor's dvipsnames, svgnames, and x11names
    among options (the ones a book loads, page_layout's classoption), the
    last loaded winning a name two sets have (NavyBlue), as xcolor loads
    them in the order its options are given. svgnames's 151 and x11names's
    317 are read from the installed xcolor's own files, svgnam.def and
    x11nam.def, where kpsewhich finds them, too many to copy here as
    dvipsnames's 68 are; without TeX, those two are {}."""
    found = {}
    for option in options:
        if option == "dvipsnames":
            found.update((name, rgb_color("cmyk", spec)) for name, spec in DVIPSNAMES.items())
            continue
        file = XCOLOR_SET_FILES.get(option)
        if not file:
            continue
        if file not in _XCOLOR_SETS:
            values = {}
            try:
                path = subprocess.run(["kpsewhich", file], capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL).stdout.strip()
                text = read_text(path) if path else ""
            except OSError:
                text = ""
            body = re.search(r"\\preparecolorset\s*\{(\w+)\}\s*\{[^}]*\}\s*\{[^}]*\}\s*\{"
                             r"([^}]*)\}", text)
            if body:
                for entry in re.sub(r"%[^\n]*", "", body.group(2)).split(";"):
                    name, _, spec = entry.strip().partition(",")
                    rgb = rgb_color(body.group(1), spec) if name else None
                    if rgb:
                        values[name] = rgb
            _XCOLOR_SETS[file] = values
        found.update(_XCOLOR_SETS[file])
    return found


def color_rgb(expression, colors, sets=None):
    """A color as xcolor reads one, (r, g, b) or None: a name the book
    defines (colors, color_values's), xcolor's own, dvipsnames's, or one of
    sets's (xcolor_sets's, the svgnames and x11names a book loads); a mix,
    red!30 (with white), red!70!black, and on (oiB!50!white!80); and a
    complement, -red."""
    expression = expression.strip()
    complement = expression.startswith("-")
    parts = expression.lstrip("-").split("!")

    def named(name):
        name = name.strip()
        if name in colors:
            return colors[name]
        if name in XCOLOR_BASE:
            return XCOLOR_BASE[name]
        if sets and name in sets:
            return sets[name]
        if name in DVIPSNAMES:
            return rgb_color("cmyk", DVIPSNAMES[name])
        return None
    current = named(parts[0])
    index = 1
    while current is not None and index < len(parts):
        try:
            share = float(parts[index]) / 100
        except ValueError:
            return None
        other = named(parts[index + 1]) if index + 1 < len(parts) else (1, 1, 1)
        if other is None:
            return None
        current = tuple(share * a + (1 - share) * b for a, b in zip(current, other))
        index += 2
    if current is None:
        return None
    return tuple(1 - v for v in current) if complement else current


def environment_spans(text, names, spans=None):
    """The (start, end) of each environment of names in text's code."""
    spans = skip_spans(text) if spans is None else spans
    begin = re.compile(r"\\begin\s*\{(" + "|".join(map(re.escape, names)) + r")\}")
    found, pos = [], 0
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
        found.append((m.start(), end))
        pos = end
    return found


def book_colors(texts, includes=None):
    """The book's \\definecolor, \\providecolor, and \\colorlet statements,
    as matches, in the order LaTeX
    reads them (reading_order, which takes texts and includes), so a later
    one replaces an earlier, as OpenIntro's main.tex would set its blue to
    black after the file of colors it \\include-s. One in a definition
    defines nothing until the definition is used, and its #1 is nothing
    outside it."""
    return [m for kind, _, m in reading_order(texts, includes, watch=COLOR_STATEMENT)
            if kind == "match" and "#" not in m.group(0)]


def resolve_colors(texts, files, counter):
    """Each \\textcolor and \\colorbox given its color in one of xcolor's
    models ([rgb]{.5,.5,.5}) written with the color as CSS, rgb(...), outside
    formulas, drawings, and definitions, all of which LaTeX may read: the
    reader drops the model and writes the values as the span's CSS color
    (coloredInline, Readers/LaTeX.hs). A color the book names is made CSS
    after the reading (color_spans), so a formula, a drawing, or a macro
    either uses still names it, for LaTeX to draw. texts: {name: text},
    changed in place."""
    for name in files:
        text = texts[name]
        spans = skip_spans(text)
        latex = sorted(math_spans(text, spans) + environment_spans(text, DRAWINGS, spans)
                       + [(d[0], d[1]) for d in definitions_in(text, spans)])

        def write(m):
            if not m.group(2) or in_spans(m.start(), latex):
                return m.group(0)
            css = css_color(m.group(2), m.group(3))
            if not css:
                return m.group(0)
            counter["colors"] = counter.get("colors", 0) + 1
            return "\\%s{%s}" % (m.group(1), css)
        texts[name] = substitute(COLOR_USE, text, write, {}, "colors")


def color_values(statements, sets=None):
    """{name: (r, g, b)} for the book's color statements, in the order LaTeX
    reads them (book_colors), the last of a name's winning, as xcolor
    defines them: \\colorlet's from the colors defined before it (or
    sets's, xcolor_sets's), and \\providecolor's only for a name not yet
    defined; a name whose last definition this can't read has none."""
    values = {}
    for statement in statements:
        m = DEFINECOLOR.match(statement)
        if m:
            if m.group(1) == "providecolor" and m.group(2) in values:
                continue
            rgb = rgb_color(m.group(3), m.group(4))
            name = m.group(2)
        else:
            m = COLORLET.match(statement)
            if not m:
                continue
            rgb, name = color_rgb(m.group(2), values, sets), m.group(1)
        if rgb:
            values[name] = rgb
        else:
            values.pop(name, None)
    return values


COLOR_STYLE = re.compile(r"^((?:background-)?color): (.*)$", re.S)


def color_spans(node, values, sets=None):
    """Each span or division the reader made of \\textcolor or \\colorbox
    (a division when it held paragraphs) given its color as CSS, in place,
    when CSS can't read it as it is: a name the
    book defines (the Nu checker found 785 on OpenIntro Statistics's pages:
    "oiB" is not a color value), a mix (red!50!black), and a name of
    xcolor's that CSS lacks (BrickRed). A name CSS has (red, black) is left,
    and a color none of these is is taken out, since a browser ignores it
    anyway. values: color_values's; sets: xcolor_sets's, the svgnames and
    x11names the book loads. Returns how many changed."""
    changed = 0
    if isinstance(node, list):
        for item in node:
            changed += color_spans(item, values, sets)
    elif isinstance(node, dict):
        if node.get("t") in ("Span", "Div"):
            kept = []
            for pair in node["c"][0][2]:
                m = COLOR_STYLE.match(pair[1]) if pair[0] == "style" else None
                color = m.group(2).strip() if m else ""
                if not m or color.startswith(("rgb(", "#")) or (
                        color.lower() in CSS_COLORS and color not in values):
                    kept.append(pair)
                    continue
                rgb = color_rgb(color, values, sets)
                if rgb:
                    kept.append([pair[0], "%s: %s" % (m.group(1), css_rgb(rgb))])
                changed += 1
            node["c"][0][2] = kept
        if "c" in node:
            changed += color_spans(node["c"], values, sets)
    return changed


def expand_include_macros(texts, files, counter):
    """Each call of one of the book's macros that \\include-s a file
    (include_macros), outside any definition, replaced in the reading copy
    by the macro's body with its arguments, as Pandoc expands it, so the
    \\include in it is where the pages are cut and the book's order read.
    texts: {name: text}, changed in place."""
    macros = include_macros([(name, texts[name]) for name in files])
    if not macros:
        return
    for name in files:
        text = texts[name]
        skip = sorted(skip_spans(text) + [(d[0], d[1]) for d in definitions_in(text, ())])
        for start, end, macro_name, args in reversed(macro_calls(text, macros, skip)):
            text = text[:start] + with_arguments(macros[macro_name]["body"], args) + text[end:]
            counter["include_macro_calls"] = counter.get("include_macro_calls", 0) + 1
        texts[name] = text


def cite_macro(body, arguments, default):
    """The macro, if its body cites (\\cite, natbib's commands, biblatex's
    \\fullcite): a dict of arguments, default, and body. Else None."""
    if "##" in body:
        return None
    skip = skip_spans(body)
    if any(not in_spans(m.start(), skip) for pattern in (CITE_COMMAND, FULLCITE)
           for m in pattern.finditer(body)):
        return {"arguments": arguments, "default": default, "body": body}
    return None


def expand_cite_macros(texts, files, counter):
    """Each call of one of the book's macros that cites
    (\\newcommand{\\see}[1]{see \\cite{#1}}), outside any definition,
    replaced in the reading copy by the macro's body with its arguments, as
    Pandoc expands it, so its citation is among the book's for BibTeX, in
    LaTeX's order, and written out as the others are. texts: {name: text},
    changed in place."""
    macros = macro_walk([(name, texts[name]) for name in files], cite_macro)[0]
    if not macros:
        return
    for name in files:
        text = texts[name]
        skip = sorted(skip_spans(text) + [(d[0], d[1]) for d in definitions_in(text, ())])
        for start, end, macro_name, args in reversed(macro_calls(text, macros, skip)):
            text = text[:start] + with_arguments(macros[macro_name]["body"], args) + text[end:]
            counter["cite_macro_calls"] = counter.get("cite_macro_calls", 0) + 1
        texts[name] = text


SIMPLE_VALUE = re.compile(r"[^\\#{}%]*")


def with_values(text, values):
    """text with each macro of values, the book's macros without arguments
    as they're defined there (macro_walk), written as its value, when that
    is plain text: \\chapterfolder/figures/#3/#3 as
    ch_intro_to_data/figures/#3/#3."""
    def value(m):
        found = values.get(m.group(1))
        if found is not None and SIMPLE_VALUE.fullmatch(found):
            return found.strip()
        return m.group(0)
    for _ in range(3):
        changed = re.sub(r"\\([A-Za-z@]+)(?![A-Za-z@])(?:\{\})?", value, text)
        if changed == text:
            break
        text = changed
    return text


def expand_image_macros(texts, files, counter, definitions_file=None):
    """Each call of one of the book's macros for an image, outside any
    definition, replaced in the reading copy by the macro's body with its
    arguments, as Pandoc expands it, so the \\includegraphics in it is
    there for repair_graphics to point at a file a browser shows; a macro
    without arguments in the file's name is written as its value at the
    call (with_values). A body holding a table or a drawing is left as it
    is, since its file's tables and drawings are counted in the author's
    text. texts: {name: text}, changed in place; definitions_file, (name,
    text) of a person's definitions, read after the preamble, so they win
    over the book's (macro_walk's after_preamble)."""
    order = [(name, texts[name]) for name in files]
    after = None
    if definitions_file:
        order.append(definitions_file)
        after = definitions_file[0]
    macros, spans = image_macros(order, after_preamble=after)
    macros = {n: m for n, m in macros.items() if not TABLE_OR_DRAWING.search(m["body"])}
    if not macros:
        return
    calls = {name: macro_calls(texts[name], macros,
                               sorted(skip_spans(texts[name]) + spans.get(name, [])))
             for name in files}
    values = macro_walk(order, lambda *_: None, after_preamble=after,
                        at={name: [c[0] for c in found] for name, found in calls.items()})[2]
    for name in files:
        text = texts[name]
        last = len(text) + 1
        for start, end, macro_name, args in reversed(calls[name]):
            if end > last:              # one call inside another's arguments
                continue
            macro = macros[macro_name]
            body = macro["body"]
            # The file's name with the values its macros have at the call.
            m = BODY_GRAPHICS.search(body)
            close = matching_brace(body, m.end() - 1)
            body = (body[:m.end()] + with_values(body[m.end():close - 1],
                                                 values.get((name, start), {}))
                    + body[close - 1:])
            text = text[:start] + with_arguments(body, args) + text[end:]
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


def has_heading(blocks):
    """Whether blocks hold a heading anywhere."""
    return bool(_headers(blocks))


def has_title_heading(blocks):
    """Whether a page has one heading at its top level to be its title, as
    the filter takes one: a bibliography's heading beside another doesn't
    count, unless it's the only one."""
    tops = [b for b in blocks if b.get("t") == "Header" and b["c"][0] == 1]
    own = [b for b in tops if "bibliography" not in b["c"][1][1]]
    return len(own) == 1 or (not own and len(tops) == 1)


def numbered_title(blocks):
    """The id of a page's one numbered heading at its top level, when it's
    the first there and the others are unnumbered (a chapter and the
    \\chapter* of its exercises after it), the page's title; else None."""
    tops = [b for b in blocks if b.get("t") == "Header" and b["c"][0] == 1
            and "bibliography" not in b["c"][1][1]]
    numbered = [b for b in tops if "unnumbered" not in b["c"][1][1]]
    if len(tops) > 1 and len(numbered) == 1 and tops[0] is numbered[0] and tops[0]["c"][1][0]:
        return tops[0]["c"][1][0]
    return None


PDF_TITLE_VALUE = r"(\{(?:[^{}]|\{[^{}]*\})*\}|[^,{}\]]*)"
PDF_TITLE = re.compile(r"\\hypersetup\s*\{(?:[^{}]|\{[^{}]*\})*?\bpdftitle\s*=\s*"
                       + PDF_TITLE_VALUE + r"|\\usepackage\s*\[[^]]*?\bpdftitle\s*=\s*"
                       + PDF_TITLE_VALUE, re.S)


def pdf_title(preamble):
    """The title a preamble gives hyperref for the PDF (pdftitle, in
    \\hypersetup or the package's options), as text, its LaTeX read by
    Pandoc (\\& as &, \\"i as ï), or None."""
    found = code_matches(PDF_TITLE, preamble or "")
    if not found:
        return None
    title = (found[-1].group(1) or found[-1].group(2) or "").strip()
    if title.startswith("{"):
        title = title[1:-1]
    try:
        done = subprocess.run(["pandoc", "-f", "latex", "-t", "plain", "--wrap=none"],
                              input=title, capture_output=True, text=True, timeout=60)
        text = done.stdout if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        text = ""
    if not text.strip():
        text = re.sub(r"\\[A-Za-z@]+\s*|[{}]", "", title).replace("~", " ")
    return " ".join(text.split()) or None


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


# --------------------------------------------------------------------------
# LaTeX's counters, as the book steps them
# --------------------------------------------------------------------------

# A label or reference whose key LaTeX makes from counters, as OpenIntro
# Statistics links each exercise and its solution, \label{eoce_\arabic{
# chapter}_\arabic{eoce}}, and a counter the text shows (\thesection) are
# LaTeX's work at the moment it gets there, which the reader doesn't do:
# it keeps the key as written, every exercise's the same, and drops the
# rest. So the reading copy marks where the book's text steps, sets, and
# shows a counter, with a link the reader keeps in its place, through
# the book's macros as it expands them; and after the reading the marks
# are counted in the document's order, as LaTeX counts, and each such key
# and counter written as LaTeX would have it.
COUNTER_MARK = "TEXTBOOKIMPROVERCOUNTER"
COUNTER_COMMAND = re.compile(
    r"\\(refstepcounter|stepcounter|setcounter|addtocounter)\s*\{\s*([A-Za-z@]+)\s*\}")
COUNTER_SHOW = re.compile(r"\\(arabic|roman|Roman|alph|Alph)\s*\{\s*([A-Za-z@]+)\s*\}"
                          r"|\\the([A-Za-z@]+)(?![A-Za-z@])")
MATTER_COMMAND = re.compile(r"\\(appendix|frontmatter|mainmatter|backmatter)(?![A-Za-z@])")
KEY_COMMAND = re.compile(r"\\(?:label|ref|pageref|eqref|autoref|cref|Cref|nameref|Nameref"
                         r"|vref|hyperref|hyperlink|hypertarget|newcounter|counterwithin"
                         r"|counterwithout|numberwithin)\*?\s*[\[{]")
COUNTER_VALUE = re.compile(r"-?\d+|#\d|\\value\s*\{\s*[A-Za-z@]+\s*\}")
NEWCOUNTER = re.compile(r"\\newcounter\s*\{\s*([A-Za-z@]+)\s*\}(?:\s*\[\s*([A-Za-z@]+)\s*\])?")
COUNTER_WITHIN = re.compile(r"\\(counterwithin|numberwithin|counterwithout)\*?\s*\{\s*"
                            r"([A-Za-z@]+)\s*\}\s*\{\s*([A-Za-z@]+)\s*\}")
THE_DEFINITION = re.compile(r"\\(?:(?:re)?newcommand\*?\s*\{?\s*|def\s*)\\the([A-Za-z@]+)\s*\}?\s*\{")
NEWTHEOREM = re.compile(r"\\newtheorem(\*?)\s*\{\s*([A-Za-z@*]+)\s*\}")
# What \thefigure, \thetable, and \theequation begin with in the book and
# report classes: the chapter's number and a dot, inside a chapter.
CHAPTER_DOT = r"\TextbookImproverChapterDot"


def theorem_specs(text, spans=None):
    """Each \\newtheorem in text, as (name, starred, shared, within):
    \\newtheorem{lem}[thm]{Lemma} counts with thm's counter, and
    \\newtheorem{thm}{Theorem}[section] within the section's;
    \\newtheorem* numbers nothing."""
    found = []
    for m in code_matches(NEWTHEOREM, text, spans):
        starred, name, pos = m.group(1) == "*", m.group(2), m.end()
        shared = within = None
        at = argument_space(text, pos)
        if not starred and text.startswith("[", at):
            close = closing_bracket(text, at)
            if close < 0:
                continue
            shared, pos = text[at + 1:close].strip(), close + 1
        at = argument_space(text, pos)
        if text.startswith("{", at):
            close = matching_brace(text, at)
            if close < 0:
                continue
            pos = close
        at = argument_space(text, pos)
        if not starred and not shared and text.startswith("[", at):
            close = closing_bracket(text, at)
            if close > 0:
                within = text[at + 1:close].strip()
        found.append((name, starred, shared, within))
    return found
# What the reader keeps only the content of: subequations, and breqn's
# dmath (numbered; dmath* isn't).
SUBEQUATIONS = re.compile(r"\\begin\s*\{(subequations|dmath)\}")
APPENDICES = re.compile(r"\\(begin|end)\s*\{appendices\}")
FLOAT_EDGE = re.compile(r"\\(begin|end)\s*\{\s*(figure\*?|table\*?|subfigure|subtable"
                        r"|longtable\*?)\s*\}")
CAPTION_STAR = re.compile(r"\\caption\s*\*")
SECTION_LEVELS = (("part", -1), ("chapter", 0), ("section", 1), ("subsection", 2),
                  ("subsubsection", 3), ("paragraph", 4), ("subparagraph", 5))
DEPTHS = dict(SECTION_LEVELS)
DOCUMENT_CLASS = re.compile(r"\\documentclass(?:\s|%[^\n]*)*(?:\[[^]]*\])?(?:\s|%[^\n]*)*"
                            r"\{\s*([^}\s]+)\s*\}")
# memoir's depth, by a division's name.
SETSECNUMDEPTH = re.compile(r"\\(?:setsecnumdepth|maxsecnumdepth)\s*\{\s*([A-Za-z]+)\s*\}")
# LaTeX's own counters a book may show, and what the standard classes make
# of them; a class with chapters numbers sections, floats, equations, and
# footnotes within them.
STANDARD_COUNTERS = ("part", "chapter", "section", "subsection", "subsubsection",
                     "paragraph", "subparagraph", "figure", "table", "equation",
                     "footnote", "enumi", "enumii", "enumiii", "enumiv")


def _arguments_span(text, start):
    """The end of the [optional] and {mandatory} arguments that begin at
    start, as far as they go."""
    pos = start
    while True:
        at = argument_space(text, pos)
        if text.startswith("[", at):
            close = closing_bracket(text, at)
            if close < 0:
                return pos
            pos = close + 1
        elif text.startswith("{", at):
            close = matching_brace(text, at)
            if close < 0:
                return pos
            pos = close
        else:
            return pos


def counter_mark(*parts):
    """The link the reader keeps where the book steps, sets, or shows a
    counter: \\hyperref with the operation as its target and no text."""
    return "\\hyperref[%s:%s]{}" % (COUNTER_MARK, ":".join(parts))


def counter_marks(text, counter, math_macros=(), counters=()):
    """The marks counter_mark makes, outside formulas, drawings, comments,
    verbatim text, and the definitions of macros formulas use: after each
    \\refstepcounter, \\stepcounter, \\setcounter, and \\addtocounter (a
    value it can follow: a number, a macro's argument, or \\value), and
    after \\appendix and the other division commands; and in place of
    \\arabic{x} and its kin, and \\thex for x among counters, outside a
    label's or a reference's key, which is counted as written, after the
    reading."""
    spans = skip_spans(text)
    keep = sorted(spans + math_spans(text, spans) + math_definitions(text, spans, math_macros)
                  + environment_spans(text, DRAWINGS, spans)
                  + [(m.start(), _arguments_span(text, m.end() - 1))
                     for m in KEY_COMMAND.finditer(text)]
                  + [(m.start(), _arguments_span(text, m.end())) for m in
                     re.finditer(r"\\(?:(?:re)?newcommand\*?\s*\{?\s*|def\s*)\\the[A-Za-z@]+"
                                 r"\s*\}?", text)])
    edits = []                          # (start, end, replacement)
    for m in COUNTER_COMMAND.finditer(text):
        if in_spans(m.start(), keep) or escaped(text, m.start()):
            continue
        op, name, end = m.group(1), m.group(2), m.end()
        parts = [op, name]
        if op in ("setcounter", "addtocounter"):
            at = argument_space(text, end)
            if not text.startswith("{", at):
                continue
            close = matching_brace(text, at)
            value = text[at + 1:close - 1].strip() if close > 0 else ""
            if not COUNTER_VALUE.fullmatch(value):
                continue
            parts.append(re.sub(r"\s+", "", value))
            end = close
        edits.append((end, end, counter_mark(*parts)))
    for m in MATTER_COMMAND.finditer(text):
        if not in_spans(m.start(), keep) and not escaped(text, m.start()):
            edits.append((m.end(), m.end(), counter_mark("division", m.group(1))))
    # The reader keeps only what subequations holds, which numbers its
    # rows 2.4a, 2.4b; the mark says the formula after it is that.
    for m in SUBEQUATIONS.finditer(text):
        if not in_spans(m.start(), keep) and not escaped(text, m.start()):
            edits.append((m.start(), m.start(), counter_mark(m.group(1))))
    # \\caption*, which numbers nothing, and the reader can't tell from
    # \\caption: a mark in the figure it's in, or before the table, where
    # the counting finds it before it counts the table; and one where a
    # table float ends, for one with no table the reader counts, so the
    # next float is numbered.
    stack = []
    for m in sorted(list(FLOAT_EDGE.finditer(text)) + list(CAPTION_STAR.finditer(text)),
                    key=lambda m: m.start()):
        if in_spans(m.start(), keep) or escaped(text, m.start()):
            continue
        if m.re is FLOAT_EDGE:
            if m.group(1) == "begin":
                stack.append([m, False])
            elif stack:
                env, starred = stack.pop()
                if starred and env.group(2).startswith("longtable"):
                    edits.append((m.end(), m.end(), counter_mark("floatend")))
                elif starred and env.group(2).startswith("table"):
                    edits.append((m.start(), m.start(), counter_mark("floatend")))
        elif stack:
            env = stack[-1][0]
            stack[-1][1] = True
            if env.group(2).startswith("longtable"):
                at = env.start()
            elif env.group(2).startswith("table"):
                at = argument_space(text, env.end())
                close = closing_bracket(text, at) if text.startswith("[", at) else -1
                at = close + 1 if close > 0 else env.end()
            else:
                at = m.start()
            edits.append((at, at, counter_mark("unnumbered")))
    # The appendix package's environment begins the appendices as
    # \\appendix does, and its end gives back the numbering before them.
    for m in APPENDICES.finditer(text):
        if not in_spans(m.start(), keep) and not escaped(text, m.start()):
            edits.append((m.end(), m.end(), counter_mark(
                "division", "appendices" if m.group(1) == "begin" else "endappendices")))
    for m in COUNTER_SHOW.finditer(text):
        if in_spans(m.start(), keep) or escaped(text, m.start()):
            continue
        if m.group(3) is not None:
            if m.group(3) not in counters:
                continue
            edits.append((m.start(), m.end(), counter_mark("the", m.group(3))))
        else:
            edits.append((m.start(), m.end(), counter_mark("show", m.group(1), m.group(2))))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    if edits:
        counter["counter_marks"] = counter.get("counter_marks", 0) + len(edits)
    return text


def book_counters(texts, master_text):
    """What the counting after the reading needs to know of the book, from
    its files in LaTeX's order, [(name, text)], the master first: the
    counters it defines and the counters each is numbered within, how it
    shows each (\\renewcommand{\\theeoce}{\\arabic{chapter}.\\arabic{eoce}}),
    its theorems, whether it has chapters and parts, and each counter's
    value at \\begin{document}."""
    code = [t for _, t in texts]
    # A division command with its title, as the reader reads one: a
    # setting for how it looks (\titleformat{\part}) isn't one.
    chapters = any(code_matches(re.compile(r"\\chapter\s*\*?\s*[\[{]"), t) for t in code)
    parts = any(code_matches(re.compile(r"\\part\s*\*?\s*[\[{]"), t) for t in code)
    if chapters:
        resets = {"section": "chapter", "subsection": "section", "subsubsection": "subsection",
                  "paragraph": "subsubsection", "subparagraph": "paragraph",
                  "figure": "chapter", "table": "chapter", "equation": "chapter",
                  "footnote": "chapter", "enumii": "enumi", "enumiii": "enumii",
                  "enumiv": "enumiii"}
        # The book and report classes number a float or an equation
        # outside every chapter (in the front matter) without one:
        # \ifnum \c@chapter>\z@ \thechapter.\fi.
        formats = {"chapter": r"\arabic{chapter}", "section": r"\thechapter.\arabic{section}",
                   "figure": CHAPTER_DOT + r"\arabic{figure}",
                   "table": CHAPTER_DOT + r"\arabic{table}",
                   "equation": CHAPTER_DOT + r"\arabic{equation}"}
    else:
        resets = {"subsection": "section", "subsubsection": "subsection",
                  "paragraph": "subsubsection", "subparagraph": "paragraph",
                  "enumii": "enumi", "enumiii": "enumii", "enumiv": "enumiii"}
        formats = {"section": r"\arabic{section}"}
    formats.update({"part": r"\Roman{part}", "subsection": r"\thesection.\arabic{subsection}",
                    "subsubsection": r"\thesubsection.\arabic{subsubsection}",
                    "footnote": r"\arabic{footnote}", "enumi": r"\arabic{enumi}",
                    "enumii": r"\alph{enumii}", "enumiii": r"\roman{enumiii}",
                    "enumiv": r"\Alph{enumiv}"})
    # A class's own numbering, as measured with LaTeX 2026-06-01: amsbook
    # numbers sections, figures, tables, and equations without the
    # chapter's number (an equation not starting again in a chapter), and
    # memoir numbers to the section, to the depth \setsecnumdepth gives.
    found = code_matches(DOCUMENT_CLASS, master_text)
    class_name = found[0].group(1) if found else ""
    secnumdepth = {"memoir": 1, "amsbook": 3}.get(class_name, 2 if chapters else 3)
    if class_name == "amsbook":
        formats.update({"section": r"\arabic{section}", "figure": r"\arabic{figure}",
                        "table": r"\arabic{table}", "equation": r"\arabic{equation}"})
        resets.pop("equation", None)
    for t in code:
        for m in code_matches(SETSECNUMDEPTH, t):
            secnumdepth = {"all": 50, "none": -10}.get(m.group(1), DEPTHS.get(m.group(1),
                                                                             secnumdepth))
    # A subfigure counts within its figure (subcaption's and subfig's
    # 1.2a; the obsolete subfigure package's 1.2(a)).
    resets.update({"subfigure": "figure", "subtable": "table"})
    defined, theorems, theorem_counters = set(STANDARD_COUNTERS), set(), {}
    for t in code:
        spans = skip_spans(t)
        for m in code_matches(NEWCOUNTER, t, spans):
            defined.add(m.group(1))
            if m.group(2):
                resets[m.group(1)] = m.group(2)
        for name, starred, shared, within in theorem_specs(t, spans):
            theorems.add(name)
            if starred:
                theorem_counters[name] = None
            elif shared:
                theorem_counters[name] = theorem_counters.get(shared) or shared
            else:
                theorem_counters[name] = name
                defined.add(name)
                if within:
                    resets[name] = within
                    formats[name] = r"\the%s.\arabic{%s}" % (within, name)
    subfigure_package = any(code_matches(re.compile(
        r"\\usepackage\s*(?:\[[^]]*\])?\s*\{[^}]*\bsubfigure\b[^}]*\}"), t) for t in code)
    # Within, without, and \the definitions in LaTeX's order, the last
    # winning; and the values the preamble sets.
    begin = code_matches(BEGIN_DOCUMENT, master_text)
    at = {texts[0][0]: [begin[0].start()]} if begin and texts else {}
    pattern = re.compile("(?:%s)|(?:%s)" % (COUNTER_WITHIN.pattern, COUNTER_COMMAND.pattern))
    initial, in_body = {}, False
    # The names \autoref and cleveref print, as the book sets them.
    ref_names = {"autoref": {}, "name": {}, "cref": {}, "Cref": {}}
    for t in code:
        for m in code_matches(CREFNAME, t):
            ref_names["cref" if m.group(1) == "c" else "Cref"][m.group(2)] = (
                m.group(3).strip(), m.group(4).strip())
        for m in code_matches(re.compile(r"\\usepackage\s*\[([^]]*)\]\s*\{[^}]*\bcleveref\b"), t):
            options = option_list(m.group(1))
            ref_names["capitalise"] = ref_names.get("capitalise") or bool(
                {"capitalise", "capitalize"} & set(options))
            ref_names["noabbrev"] = ref_names.get("noabbrev") or "noabbrev" in options
    for kind, _, item in reading_order(texts, at=at, watch=pattern):
        if kind == "at":
            in_body = True
        elif kind == "define":
            if item[2].startswith("the") and len(item[2]) > 3 and item[3] == 0:
                formats[item[2][3:]] = item[5].strip()
            words = re.sub(r"\\S(?![A-Za-z@])\s*", "\u00a7", item[5]).replace("~", "\u00a0")
            words = re.sub(r"[{}]", "", words).strip()
            if item[3] == 0 and "\\" not in words and words:
                if item[2].endswith("autorefname") and len(item[2]) > 11:
                    ref_names["autoref"][item[2][:-11]] = words
                elif item[2].endswith("name") and len(item[2]) > 4:
                    ref_names["name"][item[2][:-4]] = words
        elif kind == "match":
            text = item.string
            within = COUNTER_WITHIN.match(text, item.start())
            step = COUNTER_COMMAND.match(text, item.start())
            if within:
                child, parent = within.group(2), within.group(3)
                if within.group(1) == "counterwithout":
                    resets.pop(child, None)
                    formats[child] = r"\arabic{%s}" % child
                else:
                    resets[child] = parent
                    formats[child] = r"\the%s.\arabic{%s}" % (parent, child)
            elif step and not in_body and step.group(1) in ("setcounter", "addtocounter"):
                at_value = argument_space(text, step.end())
                close = matching_brace(text, at_value) if text.startswith("{", at_value) else -1
                value = text[at_value + 1:close - 1].strip() if close > 0 else ""
                if re.fullmatch(r"-?\d+", value):
                    initial[step.group(2)] = int(value) + (
                        initial.get(step.group(2), 0) if step.group(1) == "addtocounter" else 0)
    shift = 1 - (-1 if parts else 0 if chapters else 1)
    levels = {depth + shift: name for name, depth in SECTION_LEVELS}
    return {"resets": resets, "formats": formats, "counters": sorted(defined),
            "theorems": sorted(theorems), "levels": levels, "initial": initial,
            "chapters": chapters, "theorem_counters": theorem_counters,
            "subfigure_parens": subfigure_package, "ref_names": ref_names,
            "class": class_name, "secnumdepth": secnumdepth}


def counter_style(style, n):
    """n as \\arabic, \\roman, \\Roman, \\alph, or \\Alph shows it."""
    if style in ("roman", "Roman"):
        out = ""
        for value, numeral in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
                               (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
                               (5, "v"), (4, "iv"), (1, "i")):
            while n >= value:
                out += numeral
                n -= value
        return out.upper() if style == "Roman" else out
    if style in ("alph", "Alph"):
        letter = chr(ord("a") + n - 1) if 1 <= n <= 26 else str(n)
        return letter.upper() if style == "Alph" else letter
    return str(n)


# A display formula's number. The reader keeps a numbered environment's
# TeX whole, starred or not (Readers/LaTeX/Math.hs, mathEnvWith), and
# texmath leaves its \label, \tag, and \nonumber out of the MathML: on the
# pages a formula had no number, and a reference to it read [key]. These
# are the environments LaTeX numbers once, and those numbering each row.
DISPLAY_NUMBERED = {"equation": False, "multline": False, "dmath": False,
                    "align": True, "gather": True, "eqnarray": True,
                    "alignat": True, "flalign": True}
DISPLAY_BEGIN = re.compile(r"\\begin\s*\{(%s)(\*?)\}" % "|".join(DISPLAY_NUMBERED))
ANY_EDGE = re.compile(r"\\(begin|end)\s*\{[^{}]*\}")
ROW_COMMAND = re.compile(r"\\(nonumber|notag|tag\*?|label)(?![A-Za-z@])")
DISPLAY_ROW_END = re.compile(r"\*?\s*(?:\[[^]]*\])?")
MATH_REF = re.compile(r"\\(eqref|ref|autoref|cref|Cref)\*?\s*\{([^{}]*)\}")


def display_rows(tex, at=0):
    """The numbered environment that begins at at in a display formula's
    TeX, read as LaTeX numbers it: (name, starred, rows, end), each row
    (start, end) in tex, an environment numbered once one row, end where
    its \\end ends; or None. A row ends at \\\\ outside braces and the
    environments inside, with its * and [length]; one after a last \\\\
    is a row, as LaTeX numbers it."""
    m = DISPLAY_BEGIN.match(tex, at)
    if not m:
        return None
    name, starred = m.group(1), bool(m.group(2))
    start = i = m.end()
    if name == "alignat":
        columns = re.compile(r"\s*\{[^{}]*\}").match(tex, start)
        if columns:
            start = i = columns.end()
    rows, row_start, depth, n = [], start, 0, len(tex)
    while i < n:
        ch = tex[i]
        if ch == "%":
            line = tex.find("\n", i)
            i = n if line < 0 else line + 1
        elif ch == "\\":
            edge = ANY_EDGE.match(tex, i)
            if edge and edge.group(1) == "end" and depth == 0:
                rows.append((row_start, i))
                return (name, starred, rows if DISPLAY_NUMBERED[name] else [(start, i)],
                        edge.end())
            if edge:
                depth += 1 if edge.group(1) == "begin" else -1
                i = edge.end()
            elif tex.startswith("\\\\", i) and depth == 0:
                rows.append((row_start, i))
                i = row_start = DISPLAY_ROW_END.match(tex, i + 2).end()
            else:
                i += 2
        else:
            depth += 1 if ch == "{" else -1 if ch == "}" else 0
            i += 1
    return None


def row_commands(tex, start, end):
    """What tex[start:end], a row of a display formula, says of its number:
    [(command, argument, start, end)] for \\nonumber, \\notag, \\tag,
    \\tag*, and \\label, outside comments, an argument's span its braces'."""
    found, spans = [], skip_spans(tex[start:end])
    for m in ROW_COMMAND.finditer(tex, start, end):
        if in_spans(m.start() - start, spans) or escaped(tex, m.start()):
            continue
        name, argument, stop = m.group(1), None, m.end()
        if name not in ("nonumber", "notag"):
            at = argument_space(tex, m.end())
            close = matching_brace(tex, at) if tex.startswith("{", at) else -1
            if close < 0 or close > end:
                continue
            argument, stop = tex[at + 1:close - 1], close
        found.append((name, argument, m.start(), stop))
    return found


def tag_inlines(text):
    """A number or tag as inlines: its $...$ a formula, the rest words."""
    out = []
    for index, part in enumerate(re.split(r"(?<!\\)\$(.*?)(?<!\\)\$", text)):
        if index % 2:
            out.append({"t": "Math", "c": [{"t": "InlineMath"}, part]})
            continue
        for word in re.split(r"(\s+)", part):
            if word:
                out.append({"t": "Space"} if word.isspace() else {"t": "Str", "c": word})
    return out


def link_text(inlines):
    """A title's inlines as a link's text, a copy: no note, no link in the
    link, and a label's empty span left out."""
    out = []
    for i in inlines:
        kind = i.get("t")
        if kind == "Note" or (kind == "Span" and not i["c"][1]):
            continue
        if kind == "Link":
            out.extend(link_text(i["c"][1]))
        elif kind == "Span":
            out.append({"t": "Span", "c": [["", i["c"][0][1], i["c"][0][2]],
                                           link_text(i["c"][1])]})
        else:
            out.append(json.loads(json.dumps(i)))
    return out


def resolve_counters(blocks, setup, counts=None):
    """The marks counter_marks made, counted in the document's order as
    LaTeX counts, in place: a numbered heading steps its counter and the
    ones within it; \\refstepcounter makes its counter's value the one a
    \\label after it records, as a heading does; a counter shown is its
    value as the book shows it (\\thesection, \\arabic{eocesolch}). Each
    label's and reference's key made of counters (\\arabic{chapter}) is
    written as LaTeX makes it, and a reference the reader couldn't
    resolve, to a label in running text, which it shows as [key], gets
    the value the label recorded. A display formula LaTeX numbers is
    numbered, its number shown beside it and its labels anchors before
    it, and each numbered row given its number as a \\tag, so a PDF from
    the pages numbers it so too; \\eqref's number is in parentheses.

    The reader numbers what a \\ref names itself, and not as LaTeX does: a
    \\chapter in the front matter counts, \\appendix doesn't letter, each
    \\part starts the chapters again and a reference to one is empty, a
    figure or table without a label isn't counted, a subfigure counts as a
    figure, and a theorem is numbered in its chapter whatever the book
    says (GIAM's Theorem 1.4.1 was 1.1). So each heading, figure, table,
    and theorem is counted here too, a theorem's own title given its
    number, and every reference to one of their labels, or to a formula's
    or a \\label's, gets LaTeX's number. The marks go; a division
    command's stays as a span for cut_pages. setup: book_counters's.
    Returns (keys, values): how many keys were written, and references and
    counters given a value; counts, if given, gets equation_numbers, the
    formulas numbered."""
    counters = dict(setup["initial"])
    formats, resets = dict(setup["formats"]), setup["resets"]
    levels, theorems = setup["levels"], set(setup["theorems"])
    theorem_counters = setup.get("theorem_counters", {})
    state = {"current": None, "numbered": True, "kind": None}
    labels, refs, written = {}, [], [0]
    # Each label numbered here, by what it's the label of: a heading's
    # level, figure, subfigure, table, equation, a theorem's environment;
    # and a heading's that LaTeX gives no number, with its title.
    ours, untitled = {}, {}
    numbered = [0]

    def reset(name):
        for child, parent in resets.items():
            if parent == name:
                counters[child] = 0
                reset(child)

    def step(name):
        counters[name] = counters.get(name, 0) + 1
        reset(name)

    def record(label, number, kind, appendix=None, counter=None):
        labels[label] = number
        ours[label] = (kind, appendix, counter)

    def expand(text, depth=0):
        if CHAPTER_DOT in text:
            text = text.replace(CHAPTER_DOT, the("chapter", depth + 1) + "."
                                if counters.get("chapter", 0) > 0 else "")
        text = re.sub(r"\\value\s*\{\s*([A-Za-z@]+)\s*\}",
                      lambda m: str(counters.get(m.group(1), 0)), text)
        text = re.sub(r"\\(arabic|roman|Roman|alph|Alph)\s*\{\s*([A-Za-z@]+)\s*\}",
                      lambda m: counter_style(m.group(1), counters.get(m.group(2), 0)), text)
        if depth < 8:
            text = re.sub(r"\\the([A-Za-z@]+)(?![A-Za-z@])",
                          lambda m: the(m.group(1), depth + 1) if m.group(1) in counters
                          or m.group(1) in formats else m.group(0), text)
        return text.replace("{}", "")

    def the(name, depth=0):
        return expand(formats.get(name, r"\arabic{%s}" % name), depth)

    def value(text):
        """A value counter_marks kept, as a number, or None."""
        try:
            return int(expand(text))
        except ValueError:
            return None

    def key(text):
        if "\\" not in text:
            return text
        new = expand(text)
        if new != text:
            written[0] += 1
        return new

    def equation(node):
        """A display formula numbered as LaTeX numbers it, in place: each
        numbered row without a \\tag of its own given one, each label
        recording its row's number (written as key_id has it, as the
        references will be), and node["equation"] noting the labels and
        what each row shows, for unmark. What subequations held, as the
        mark before it says, is numbered once, and each row of every
        environment in it by letter; breqn's dmath, whose environment the
        reader drops, once, as its mark says; and a display formula with a
        \\tag (\\[ x \\tag{1} \\]) by its tag. An eqnarray takes no \\tag
        ("\\tag not allowed here"), so the count before it and the number's
        form are noted instead, for a PDF built from the pages to set."""
        tex = node["c"][1]
        sub = state.pop("subequations", False)
        breqn = state.pop("dmath", False)
        edits, keys, shown, eqnarray = [], [], [], [None]
        last = [state["current"]]
        letters = [0]

        def label(argument, start, stop, number):
            new = key(argument)
            record(new, number if number is not None else last[0], "equation")
            keys.append(new)
            if key_id(new) != argument:
                edits.append((start, stop, "\\label{%s}" % key_id(new)))

        def number_rows(name, starred, rows, parent=None):
            for start, stop in rows:
                commands = row_commands(tex, start, stop)
                names = [c[0] for c in commands]
                tag = next((c for c in commands if c[0].startswith("tag")), None)
                if tag:
                    number = tag[1]
                    shown.append(number if tag[0] == "tag*" else "(%s)" % number)
                elif starred or "nonumber" in names or "notag" in names:
                    number = None
                    shown.append(None)
                else:
                    if parent is not None:
                        letters[0] += 1
                        number = parent + counter_style("alph", letters[0])
                    else:
                        before = counters.get("equation", 0)
                        step("equation")
                        number = the("equation")
                    shown.append("(%s)" % number)
                    if name != "eqnarray":
                        edits.append((stop, stop, " \\tag{%s}" % number))
                    elif parent is None and eqnarray[0] is None:
                        form = re.fullmatch(r"([A-Za-z0-9.\-]*?)(\d+)", number)
                        if form and int(form.group(2)) == before + 1:
                            eqnarray[0] = (before, form.group(1))
                if number is not None:
                    last[0] = number
                for command, argument, cstart, cstop in commands:
                    if command == "label":
                        label(argument, cstart, cstop, number)
        if sub:
            step("equation")
            parent = last[0] = the("equation")
            outside, pos = [], 0
            while True:
                inner = DISPLAY_BEGIN.search(tex, pos)
                found = display_rows(tex, inner.start()) if inner else None
                if not found:
                    outside.append((pos, len(tex)))
                    break
                outside.append((pos, inner.start()))
                number_rows(found[0], found[1], found[2], parent)
                pos = found[3]
            for start, stop in outside:
                for command, argument, cstart, cstop in row_commands(tex, start, stop):
                    if command == "label":
                        label(argument, cstart, cstop, parent)
        elif breqn:
            number_rows("dmath", False, [(0, len(tex))])
        else:
            found = display_rows(tex, re.compile(r"\s*").match(tex).end())
            if found:
                number_rows(found[0], found[1], found[2])
            elif any(c[0].startswith("tag") for c in row_commands(tex, 0, len(tex))):
                number_rows(None, True, [(0, len(tex))])
            else:
                return
        for start, stop, replacement in sorted(edits, reverse=True):
            tex = tex[:start] + replacement + tex[stop:]
        node["c"][1] = tex
        if keys or any(s is not None for s in shown) or sub:
            node["equation"] = {"labels": keys, "shown": shown, "sub": sub,
                                "eqnarray": eqnarray[0]}
            numbered[0] += 1

    top = "chapter" if setup["chapters"] else "section"

    def has_mark(node, op):
        """Whether node holds a mark for op, outside a figure inside it."""
        if isinstance(node, list):
            return any(has_mark(item, op) for item in node)
        if isinstance(node, dict):
            if node.get("t") == "Link" and node["c"][2][0] == "#%s:%s" % (COUNTER_MARK, op):
                return True
            if node.get("t") == "Figure" or not isinstance(node.get("c"), list):
                return False
            return has_mark(node["c"], op)
        return False

    def retitle(content, number):
        """A theorem's title as the reader writes it, **Theorem 1.1.**,
        given LaTeX's number, or none when number is None."""
        first = content[0] if content else None
        if not first or first.get("t") not in ("Para", "Plain") or not first["c"] \
                or first["c"][0].get("t") not in ("Strong", "Emph"):
            return
        title = first["c"][0]["c"]
        if len(title) >= 2 and title[-2].get("t") == "Space" and title[-1].get("t") == "Str" \
                and re.fullmatch(r"\d+(?:\.\d+)*", title[-1]["c"]):
            if number is None:
                title[-2:] = []
            else:
                title[-1:] = tag_inlines(number)

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        kind, c = node.get("t"), node.get("c")
        saved = state["current"], state["kind"]
        inside = None               # (number, kind) a float or theorem numbers
        if kind == "Header":
            name = levels.get(c[0])
            # A level below secnumdepth isn't numbered (the book class's
            # subsubsection), and its \label records the level above's. The
            # front and back matter number no chapter, but a section in
            # them is numbered still (0.1 before the first chapter), except
            # in memoir, which numbers nothing there; KOMA's scrbook and
            # amsbook start the sections again at a chapter there, and
            # number them without it (1, 1.1), as measured.
            if name == top and not state["numbered"] and "unnumbered" not in c[1][1] \
                    and setup.get("class") in ("scrbook", "amsbook"):
                reset(name)
            if "unnumbered" not in c[1][1] and name and (
                    state["numbered"] or name != top and setup.get("class") != "memoir") \
                    and DEPTHS[name] <= counters.get("secnumdepth", setup.get(
                        "secnumdepth", 2 if setup["chapters"] else 3)):
                step(name)
                state["current"] = the(name)
                state["kind"] = name
                # hyperref names a chapter and a book's section in the
                # appendices Appendix, an article's section too.
                state["appendix"] = state.get("appendix") and (
                    "top" if name == top else "second"
                    if setup["chapters"] and name == "section" else "deep")
            # Its label records what LaTeX's would: its number, or the
            # last one set when it has none. With nothing set yet (a
            # chapter in the front matter), LaTeX prints nothing, and a
            # reference to it is its title, as \nameref would print it.
            if c[1][0] and state["current"] is not None:
                record(c[1][0], state["current"], state["kind"],
                       state.get("appendix") if state["kind"] in DEPTHS else None)
            elif c[1][0]:
                untitled[c[1][0]] = c[2]
        elif kind == "Link" and c[2][0].startswith("#%s:" % COUNTER_MARK):
            parts = c[2][0][len(COUNTER_MARK) + 2:].split(":")
            op = parts[0]
            if op in ("refstepcounter", "stepcounter") and len(parts) > 1:
                step(parts[1])
                if op == "refstepcounter":
                    state["current"] = the(parts[1])
                    state["kind"] = parts[1]
            elif op == "unnumbered":
                # \caption* in the float that follows, or that this is in.
                state["unnumbered"] = True
            elif op == "floatend":
                # The table float it was in ended, with no table counted.
                state.pop("unnumbered", None)
            elif op in ("setcounter", "addtocounter") and len(parts) > 2:
                number = value(":".join(parts[2:]))
                if number is not None:
                    counters[parts[1]] = number + (
                        counters.get(parts[1], 0) if op == "addtocounter" else 0)
            elif op == "division" and len(parts) > 1:
                name = parts[1]
                if name == "endappendices":
                    # The appendix package gives back the count and the
                    # numbers' form it found.
                    saved = state.pop("appendices", None)
                    if saved:
                        state["numbered"], counters[top] = saved[0], saved[1]
                        if saved[2] is None:
                            formats.pop(top, None)
                        else:
                            formats[top] = saved[2]
                else:
                    if name == "appendices":
                        state["appendices"] = (state["numbered"], counters.get(top, 0),
                                               formats.get(top))
                    state["numbered"] = name in ("mainmatter", "appendix", "appendices")
                    if name in ("appendix", "appendices"):
                        counters[top] = 0
                        formats[top] = r"\Alph{%s}" % top
                    if setup.get("class") == "scrbook":
                        # KOMA numbers a section, a float, and an equation
                        # without the chapter's number outside the main
                        # matter (measured: 1, Figure 1).
                        for counted in ("section", "figure", "table", "equation"):
                            if counted in setup["formats"]:
                                formats[counted] = setup["formats"][counted] \
                                    if state["numbered"] else r"\arabic{%s}" % counted
                state["appendix"] = name in ("appendix", "appendices") or (
                    state.get("appendix") and name not in ("endappendices", "mainmatter"))
                # Kept where it stood, for the cut.
                node["division"] = name
            elif op == "show" and len(parts) > 2:
                node["shown"] = counter_style(parts[1], counters.get(parts[2], 0))
            elif op == "the" and len(parts) > 1:
                node["shown"] = the(parts[1])
            elif op in ("subequations", "dmath"):
                state[op] = True
            node["mark"] = True
            return
        elif kind == "Math" and c[0].get("t") == "DisplayMath":
            equation(node)
        elif kind == "Span" and any(k == "label" for k, _ in c[0][2]):
            new = key(c[0][0])
            c[0][0] = new
            for pair in c[0][2]:
                if pair[0] == "label":
                    pair[1] = new
            labels[new] = state["current"]
            if state["current"] is not None:
                ours[new] = (state["kind"], state.get("appendix")
                             if state["kind"] in DEPTHS else None,
                             theorem_counters.get(state["kind"]))
        elif kind == "Link" and any(k == "reference" for k, _ in c[0][2]):
            reference = dict((k, v) for k, v in c[0][2])["reference"]
            # \autoref's and cleveref's command, which the copy wrote in
            # the key.
            command = None
            if reference.startswith(REF_PREFIX + ":"):
                _, command, reference = reference.split(":", 2)
            # A key made of counters is what they are here.
            news = [key(k.strip()) for k in reference.split(",") if k.strip()] \
                if command else [key(reference)]
            refs.append((node, reference, command, news))
        elif kind == "Figure":
            # A figure with a caption counts, a subfigure within the figure
            # it's in, whose number is stepped first, as LaTeX shows it.
            unnumbered = state.pop("unnumbered", False) or has_mark(c[2], "unnumbered")
            if c[1][1] and not unnumbered:
                parent = state.get("figure")
                if has_mark(c[2], "tablefloat"):
                    # A table float the reader can't take as one table, a
                    # figure to it.
                    step("table")
                    inside = (the("table"), "table")
                elif parent is not None:
                    # A subfigure, or a subtable in a table float.
                    sub = "subtable" if parent[1] == "table" else "subfigure"
                    step(sub)
                    letter = counter_style("alph", counters[sub])
                    inside = (parent[0] + ("(%s)" % letter if setup.get("subfigure_parens")
                                           else letter), sub)
                else:
                    step("figure")
                    inside = (the("figure"), "figure")
                if c[0][0]:
                    record(c[0][0], *inside)
        elif kind == "Table":
            if c[1][1] and not state.pop("unnumbered", False):
                step("table")
                inside = (the("table"), "table")
                if c[0][0]:
                    record(c[0][0], *inside)
        elif kind == "Div" and set(c[0][1]) & theorems:
            name = next(n for n in c[0][1] if n in theorems)
            counter = theorem_counters.get(name)
            if counter:
                step(counter)
                inside = (the(counter), name)
                retitle(c[1], inside[0])
                if c[0][0]:
                    record(c[0][0], inside[0], name, None, counter)
            elif name in theorem_counters:
                # \newtheorem*'s, which the reader numbers: it takes the
                # star for the command's, not the theorem's.
                retitle(c[1], None)
        if kind in ("OrderedList", "Note"):
            # An item's and a note's own counters aren't counted here: a
            # label in one records nothing.
            state["current"], state["kind"] = None, None
        elif inside:
            state["current"], state["kind"] = inside
        figure = state.get("figure")
        if kind == "Figure" and inside and inside[1] in ("figure", "table"):
            state["figure"] = inside
        if c is not None and kind not in ("Math", "Code", "CodeBlock", "RawInline", "RawBlock"):
            walk(c)
        if kind == "Figure":
            state["figure"] = figure
            state.pop("unnumbered", None)
        if kind in ("OrderedList", "Note", "Div", "Figure", "Table"):
            # What a float, an environment, or a list sets is its own.
            state["current"], state["kind"] = saved

    walk(blocks)
    given = 0
    names = setup.get("ref_names", {})

    def words(text):
        return [{"t": "Space"} if w == " " else {"t": "Str", "c": w}
                for w in re.split(r"( )", text) if w]

    def number_inlines(new, parens=False):
        """A label's number as inlines, or its key in brackets, as the
        reader shows a label it has no number for."""
        number = labels.get(new)
        if not number:
            return [{"t": "Str", "c": "[%s]" % new}]
        number = "(%s)" % number if parens else number
        return tag_inlines(number) if "$" in number else [{"t": "Str", "c": number}]

    def ref_link(new, inlines):
        return {"t": "Link", "c": [["", [], [["reference-type", "ref"], ["reference", new]]],
                                   inlines, ["#" + new, ""]]}

    def sort_key(new):
        parts = re.split(r"[.\-]", labels.get(new) or "")
        return [int(p) for p in parts] if all(p.isdigit() for p in parts) else None

    def named(command, news):
        """What \\autoref and cleveref's commands print: the
        name in the link, for \\autoref; for cleveref, outside it, each
        type's labels in order, a run of three or more a range, and an
        equation's number in parentheses."""
        kind = {new: ours.get(new, (None, None, None)) for new in news}
        if command == "autoref":
            name = reference_name(names, command, kind[news[0]])
            return [ref_link(news[0], ([{"t": "Str", "c": name + "\u00a0"}] if name else [])
                             + number_inlines(news[0]))]
        if command in ("namecref", "nameCref", "lcnamecref"):
            name = reference_name(names, command, kind[news[0]])
            return [{"t": "Str", "c": name}] if name else number_inlines(news[0])
        groups = []
        for new in news:
            what = CREF_ALIASES.get(kind[new][0], kind[new][0])
            group = next((g for g in groups if g[0] == what and what is not None), None)
            if group is None:
                group = [what, []]
                groups.append(group)
            group[1].append(new)
        out = []
        for index, (what, members) in enumerate(groups):
            if command in ("crefrange", "Crefrange") and len(news) == 2 and len(groups) == 1:
                segments = [tuple(news)]
            else:
                if all(sort_key(m) is not None for m in members):
                    members = sorted(members, key=sort_key)
                runs = []
                for m in members:
                    now = sort_key(m)
                    last = sort_key(runs[-1][-1]) if runs else None
                    if now and last and len(now) == len(last) and now[:-1] == last[:-1] \
                            and now[-1] == last[-1] + 1:
                        runs[-1].append(m)
                    else:
                        runs.append([m])
                segments = [s for run in runs for s in (
                    [(run[0], run[-1])] if len(run) >= 3 else [(r,) for r in run])]
            if index:
                out += words(" and\u00a0" if len(groups) == 2 else ", and\u00a0"
                             if index == len(groups) - 1 else ", ")
            name = None if command == "labelcref" else reference_name(
                names, command, kind[members[0]],
                plural=len(segments) > 1 or len(segments[0]) > 1)
            if name:
                out.append({"t": "Str", "c": name + "\u00a0"})
            parens = what == "equation"
            for at, segment in enumerate(segments):
                if at:
                    out += words(" and\u00a0" if at == len(segments) - 1 else ", ")
                out.append(ref_link(segment[0], number_inlines(segment[0], parens)))
                if len(segment) > 1:
                    out += words(" to\u00a0")
                    out.append(ref_link(segment[1], number_inlines(segment[1], parens)))
        return out

    for node, reference, command, news in refs:
        if command:
            if not news:
                continue
            inlines = named(command, news)
            if len(inlines) == 1 and inlines[0]["t"] == "Link":
                node["c"] = inlines[0]["c"]
            else:
                node["t"], node["c"] = "Span", [["", [], []], inlines]
            given += 1
            continue
        new = news[0]
        attrs = node["c"][0][2]
        for pair in attrs:
            if pair[0] == "reference":
                pair[1] = new
        if node["c"][2][0] == "#" + reference:
            node["c"][2][0] = "#" + new
        # The reader's text, its own number or [key] when it had none.
        text = node["c"][1]
        if not labels.get(new) and new in untitled and len(text) == 1 \
                and text[0].get("t") == "Str":
            node["c"][1] = link_text(untitled[new])
            given += 1
        elif labels.get(new) and len(text) == 1 and text[0].get("t") == "Str":
            # \eqref, amsmath's, sets the number in parentheses, whatever
            # the label numbers; a \tag's text may hold a formula.
            shown = labels[new]
            if dict((k, v) for k, v in attrs).get("reference-type") == "eqref":
                shown = "(%s)" % shown
            shown = tag_inlines(shown) if "$" in shown else [{"t": "Str", "c": shown}]
            if shown != text:
                node["c"][1] = shown
                given += 1

    def math_refs(node):
        """A reference inside a formula, \\text{by \\eqref{eq:def}}, written as
        the number its label recorded: texmath stops on \\eqref, and the
        formula was left as TeX."""
        nonlocal given
        if isinstance(node, list):
            for item in node:
                math_refs(item)
        elif isinstance(node, dict):
            if node.get("t") == "Math":
                def one(m):
                    found = labels.get(expand(m.group(2)) if "\\" in m.group(2) else m.group(2))
                    if not found or "$" in found:
                        return m.group(0)
                    return "(%s)" % found if m.group(1) == "eqref" else found
                new = MATH_REF.sub(one, node["c"][1])
                if new != node["c"][1]:
                    node["c"][1] = new
                    given += 1
            elif node.get("c") is not None:
                math_refs(node["c"])
    math_refs(blocks)

    def unmark(node):
        nonlocal given
        if isinstance(node, list):
            out = []
            for item in node:
                if isinstance(item, dict) and item.get("mark"):
                    if item.get("shown"):
                        out.append({"t": "Str", "c": item["shown"]})
                        given += 1
                    elif item.get("division"):
                        out.append({"t": "Span", "c": [
                            ["", [DIVISION_CLASS], [["division", item["division"]]]], []]})
                    continue
                if isinstance(item, dict) and item.get("equation"):
                    # The labels' anchors, the formula, and its numbers, a
                    # row's under the row before's, in a span the pages'
                    # style sets the numbers at the right of.
                    info = item.pop("equation")
                    inner = [{"t": "Span", "c": [[k, [], [["label", k]]], []]}
                             for k in info["labels"]]
                    inner.append(item)
                    shown = list(info["shown"])
                    while shown and shown[-1] is None:
                        shown.pop()
                    if shown:
                        numbers = []
                        for index, number in enumerate(shown):
                            if index:
                                numbers.append({"t": "LineBreak"})
                            if number is not None:
                                numbers.extend(tag_inlines(number))
                        inner.append({"t": "Span", "c": [["", ["equation-number"], []],
                                                         numbers]})
                    # An eqnarray's count and form, for a PDF from the pages.
                    count = [["eqnarray-counter", str(info["eqnarray"][0])],
                             ["eqnarray-prefix", info["eqnarray"][1]]] \
                        if info["eqnarray"] else []
                    out.append({"t": "Span", "c": [
                        ["", ["equation"] + (["subequations"] if info["sub"] else []), count],
                        inner]})
                    continue
                marked = isinstance(item, dict) and item.get("t") in ("Para", "Plain") \
                    and any(isinstance(i, dict) and i.get("mark") for i in item["c"])
                unmark(item)
                # A paragraph that held only marks goes with them.
                if marked and not [i for i in item["c"] if i.get("t") not in (
                        "Space", "SoftBreak", "LineBreak")]:
                    continue
                out.append(item)
            node[:] = out
        elif isinstance(node, dict) and node.get("c") is not None:
            unmark(node["c"])
    unmark(blocks)
    if counts is not None and numbered[0]:
        counts["equation_numbers"] = counts.get("equation_numbers", 0) + numbered[0]
    return written[0], given


# --------------------------------------------------------------------------
# the bibliography: BibTeX's, written out, and the citations to it
# --------------------------------------------------------------------------

# The reader keeps a \cite as a citation whose text is the raw command,
# which no writer but LaTeX's prints, so each was empty on the pages
# (GIAM's 16, "projective plane of order 10[10]" read "order 10"); it
# drops \bibliography, and runs a thebibliography's entries together in
# one paragraph, their \bibitem-s and some of their text lost. So the copy
# has the bibliography written out as LaTeX sets it, from BibTeX's .bbl
# with the book's own style, and each citation as the label it prints,
# linked to its entry.
BIBLIOGRAPHY = re.compile(r"\\bibliography\s*\{([^}]*)\}")
BIBLIOGRAPHYSTYLE = re.compile(r"\\bibliographystyle\s*\{\s*([^}]*?)\s*\}")
THEBIBLIOGRAPHY = re.compile(r"\\begin\s*\{thebibliography\}\s*\{[^{}]*\}")
CITE_COMMAND = re.compile(r"\\(cite|citep|citet|Citet|Citep|citealt|Citealt|citealp|Citealp|"
                          r"citeauthor|Citeauthor|citeyear|citeyearpar|citenum|nocite)(\*?)"
                          r"(?![A-Za-z@])")
BIBITEM = re.compile(r"\\bibitem(?![A-Za-z@])\s*")
BIBLATEX = re.compile(r"\\usepackage\s*(?:\[[^]]*\])?\s*\{[^}]*\bbiblatex\b")
NATBIB = re.compile(r"\\usepackage\s*(?:\[([^]]*)\])?\s*\{[^}]*\bnatbib\b")
BIB_ID = "bib-"
AUTHOR_YEAR = re.compile(r"^(?P<short>.*?)\((?P<year>[^()]*)\)(?P<long>.*)$", re.S)


def citation_at(text, m):
    """The \\cite-like command at m: (command, star, options, keys, end),
    its optional arguments as given, or None when it has no key."""
    pos, options = m.end(), []
    while len(options) < 2:
        at = argument_space(text, pos)
        if not text.startswith("[", at):
            break
        close = closing_bracket(text, at)
        if close < 0:
            return None
        options.append(text[at + 1:close])
        pos = close + 1
    at = argument_space(text, pos)
    if not text.startswith("{", at):
        return None
    close = matching_brace(text, at)
    if close < 0:
        return None
    keys = [k.strip() for k in text[at + 1:close - 1].split(",") if k.strip()]
    return m.group(1), m.group(2), options, keys, close


# What a style's .bbl defines for its entries, which the reader doesn't
# know: (command, arguments, what it prints), #1 and #2 its arguments.
BBL_COMMANDS = (("natexlab", 1, "#1"), ("doi", 1, "doi: \\href{https://doi.org/#1}{#1}"),
                ("urlprefix", 0, "URL "), ("bibinfo", 2, "#2"), ("bibfield", 2, "#2"),
                ("bibnamefont", 1, "#1"), ("bibfnamefont", 1, "#1"),
                ("citenamefont", 1, "#1"), ("BibitemOpen", 0, ""), ("BibitemShut", 1, ""),
                ("mn@doi", 1, "\\href{https://doi.org/#1}{doi:#1}"),
                ("mn@eprint", 2, "#1:#2"))
BBL_ITEM = re.compile(r"\\(bibitem|harvarditem)(?![A-Za-z@])\s*")


def bbl_words(words, letters=True):
    """An entry's text with what its style's .bbl defines (BBL_COMMANDS)
    written as what it prints: natbib's \\natexlab{a} as a, or as nothing
    when letters is false, as natbib prints it with numbers; \\doi{...} as
    doi: and a link."""
    words = re.sub(r"\{\\natexlab\s*\{([^{}]*)\}\}", r"\1" if letters else "", words)
    for name, count, template in BBL_COMMANDS:
        pattern = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z@])\s*")
        out, pos = [], 0
        for m in pattern.finditer(words):
            if m.start() < pos:
                continue
            at, args = m.end(), []
            if words.startswith("[", at) and name == "mn@doi":
                close = closing_bracket(words, at)
                at = close + 1 if close > 0 else at
            while len(args) < count:
                at = argument_space(words, at)
                if not words.startswith("{", at):
                    break
                close = matching_brace(words, at)
                if close < 0:
                    break
                args.append(words[at + 1:close - 1].strip())
                at = close
            if len(args) < count:
                continue
            out.append(words[pos:m.start()] + ("" if name == "natexlab" and not letters
                                               else re.sub(r"#(\d)",
                                                           lambda a: args[int(a.group(1)) - 1],
                                                           template)))
            pos = at
        words = "".join(out) + words[pos:]
    return words


def bbl_entries(text, letters=True):
    """A thebibliography's entries, [(label, key, text)], label the one
    \\bibitem gives ([Str87], natbib's {Lam(1989)}), or None; a
    \\harvarditem[Short]{Long}{Year}{key} has natbib's Short(Year)Long.
    letters: a year's \\natexlab letter is printed (bbl_words)."""
    begin = THEBIBLIOGRAPHY.search(text)
    if not begin:
        return []
    end = re.search(r"\\end\s*\{thebibliography\}", text[begin.end():])
    body = text[begin.end():begin.end() + end.start()] if end else text[begin.end():]
    entries = []
    starts = [m for m in BBL_ITEM.finditer(body)]
    for index, m in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        pos, label, args = m.end(), None, []
        if body.startswith("[", pos):
            close = closing_bracket(body, pos)
            if close < 0:
                continue
            label, pos = body[pos + 1:close], close + 1
        for _ in range(3 if m.group(1) == "harvarditem" else 1):
            pos = argument_space(body, pos)
            close = matching_brace(body, pos) if body.startswith("{", pos) else -1
            if close < 0:
                break
            args.append(body[pos + 1:close - 1])
            pos = close
        if len(args) < (3 if m.group(1) == "harvarditem" else 1):
            continue
        if m.group(1) == "harvarditem":
            label = "%s(%s)%s" % (label, args[1], args[0]) if label \
                else "%s(%s)" % (args[0], args[1])
        # A comment ends at its line's end, before the lines are run
        # together, as TeX reads it; \\protect, which a database puts before
        # a brace (\\protect{G}oldbach), is no command to the reader.
        words = re.sub(r"(?<!\\)%[^\n]*(?:\n[ \t]*)?", "", body[pos:stop])
        words = re.sub(r"\\protect(?![A-Za-z@])\s*", "", words)
        words = re.sub(r"\\newblock(?![A-Za-z@])\s*", " ", words)
        entries.append((label, args[-1].strip(), bbl_words(" ".join(words.split()), letters)))
    return entries


def run_bibtex(base, work, folder, keys, style, databases):
    """BibTeX's .bbl for keys with style and databases, from an .aux written
    for it in work/bibtex, or None when there's no BibTeX or it fails (why,
    BIBTEX_PROBLEM[0]). Each database the book has, and a style of its
    own, is copied there first, since BibTeX finds a name with a folder in
    it (\\bibliography{../refs}, from a master in src/) only from where it
    runs, as LaTeX's build does from the master's folder. A .bbl with
    entries BibTeX wrote despite an error (a repeated entry, which it
    skips) is BibTeX's, as LaTeX's build reads it, the error in
    BIBTEX_PROBLEM[0] all the same."""
    BIBTEX_PROBLEM[0] = None
    where = os.path.join(work, "bibtex")
    os.makedirs(where, exist_ok=True)

    def own(name, extension):
        for candidate in (os.path.join(base, folder, name), os.path.join(base, name)):
            for path in (candidate, candidate + extension):
                if path.endswith(extension) and os.path.isfile(path):
                    return path
        return None
    names = []
    for index, database in enumerate(databases, start=1):
        found = own(database, ".bib")
        if found:
            shutil.copyfile(found, os.path.join(where, "database%d.bib" % index))
            names.append("database%d" % index)
        else:
            names.append(database)
    found = own(style, ".bst")
    if found:
        shutil.copyfile(found, os.path.join(where, "book-style.bst"))
        style = "book-style"
    lines = ["\\citation{%s}" % k for k in keys] + [
        "\\bibstyle{%s}" % style, "\\bibdata{%s}" % ",".join(names)]
    write_text(os.path.join(where, "book.aux"), "\n".join(lines) + "\n")
    bbl = os.path.join(where, "book.bbl")
    if os.path.exists(bbl):
        os.remove(bbl)
    paths = os.pathsep.join(os.path.abspath(p) for p in (base, os.path.join(base, folder))) \
        + os.pathsep
    # Lines broken at 79 characters, as TeX Live's and MiKTeX's BibTeX
    # break them by default (TinyTeX sets 10000): where a database ends a
    # line with a comment, what follows it is printed only when the line
    # breaks there (GIAM's Wikipedia entries' URLs).
    env = dict(os.environ, BIBINPUTS=paths, BSTINPUTS=paths, max_print_line="79")
    try:
        done = subprocess.run(["bibtex", "-terse", "book"], cwd=where, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except OSError:
        return None
    if done.returncode > 1 or not os.path.exists(bbl):
        said = [line.strip() for line in (done.stdout + "\n" + done.stderr).splitlines()
                if line.strip() and not line.startswith("(")]
        # The databases by the names the book gives them, not the copies'.
        problem = said[0] if said else "it stopped (exit %d)" % done.returncode
        for index, database in enumerate(databases, start=1):
            problem = problem.replace("database%d.bib" % index, database
                                      + ("" if database.endswith(".bib") else ".bib"))
        BIBTEX_PROBLEM[0] = problem
        text = read_text(bbl) if done.returncode == 2 and os.path.exists(bbl) else None
        return text if text and BBL_ITEM.search(text) else None
    return read_text(bbl)


# Why run_bibtex last failed, with BibTeX there.
BIBTEX_PROBLEM = [None]


def bibliography_block(entries, author_year, heading):
    """The written-out bibliography: its heading as LaTeX sets one, and its
    entries as a list, each with its label (a numeric or alpha style's) and
    an anchor its citations link to."""
    if author_year:
        items = ["\\item \\label{%s%s}%s" % (BIB_ID, key, text) for _, key, text in entries]
        body = "\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}"
    else:
        items = ["\\item[{[%s]}] \\label{%s%s}%s" % (label, BIB_ID, key, text)
                 for label, key, text in entries]
        body = "\\begin{description}\n" + "\n".join(items) + "\n\\end{description}"
    return "\n\n%s\n\n%s\n\n" % (heading, body)


# How citations are printed, as natbib.sty sets it: its defaults, and the
# preset for each bibliography style it has one for (\bibstyle@plainnat and
# the rest), which applies only when no option, \bibpunct, \setcitestyle,
# or \citestyle has set anything: (open, close, sep, mode, aysep, yysep),
# mode "a" author and year, "n" numbers, "s" superscript numbers. LaTeX's
# own \cite and the cite package's, as LaTeX prints them.
NATBIB_DEFAULT = {"open": "(", "close": ")", "sep": ";", "mode": "a", "aysep": ",",
                  "yysep": ",", "cmt": ", ", "sort": False, "compress": False}
NATBIB_PRESETS = {
    "chicago": ("(", ")", ";", "a", ",", ","), "named": ("[", "]", ";", "a", ",", ","),
    "agu": ("[", "]", ";", "a", ",", ",~"), "copernicus": ("(", ")", ";", "a", ",", ","),
    "egu": ("(", ")", ";", "a", ",", ","), "egs": ("(", ")", ";", "a", ",", ","),
    "agsm": ("(", ")", ",", "a", "", ","), "kluwer": ("(", ")", ",", "a", "", ","),
    "dcu": ("(", ")", ";", "a", ";", ","), "aa": ("(", ")", ";", "a", "", ","),
    "pass": ("(", ")", ";", "a", ",", ","), "anngeo": ("(", ")", ";", "a", ",", ","),
    "nlinproc": ("(", ")", ";", "a", ",", ","), "cospar": ("/", "/", ",", "n", "", ""),
    "esa": ("(Ref.~", ")", ",", "n", "", ""), "nature": ("", "", ",", "s", "", ","),
    "plain": ("[", "]", ",", "n", "", ","), "alpha": ("[", "]", ",", "n", "", ","),
    "abbrv": ("[", "]", ",", "n", "", ","), "unsrt": ("[", "]", ",", "n", "", ","),
    "plainnat": ("[", "]", ",", "a", ",", ","), "abbrvnat": ("[", "]", ",", "a", ",", ","),
    "unsrtnat": ("[", "]", ",", "a", ",", ",")}
# natbib's options in the order it declares them, the order \ProcessOptions
# takes them in, whatever order the book gives them.
NATBIB_OPTIONS = ("numbers", "super", "authoryear", "round", "square", "angle", "curly",
                  "comma", "semicolon", "colon", "nobibstyle", "bibstyle", "sort", "compress",
                  "sort&compress")
NATBIB_BRACKETS = {"round": ("(", ")"), "square": ("[", "]"), "angle": ("<", ">"),
                   "curly": ("\\{", "\\}")}
NATBIB_COMMAND = re.compile(r"\\(bibpunct|setcitestyle|citestyle)(?![A-Za-z@])")
LATEX_CITE = {"open": "[", "close": "]", "sep": ",", "mode": "n", "aysep": "", "yysep": ",",
              "cmt": ", ", "sort": False, "compress": False, "natbib": False}
CITE_PACKAGE = re.compile(r"\\usepackage\s*(?:\[([^]]*)\])?\s*\{[^}]*\bcite\b[^}]*\}")
NDASH = "\u2013"


def natbib_keyword(word, style):
    """Sets style as one of \\setcitestyle's keywords sets natbib's
    punctuation (one of its options without what the option also does)."""
    if word == "numbers":
        style.update(mode="n")
    elif word == "super":
        style.update(mode="s")
    elif word == "authoryear":
        style.update(mode="a")
    elif word in NATBIB_BRACKETS:
        style["open"], style["close"] = NATBIB_BRACKETS[word]
    elif word == "comma":
        style["sep"] = ","
    elif word in ("semicolon", "colon"):
        style["sep"] = ";"


def natbib_command(m, style):
    """Sets style as one \\bibpunct, \\setcitestyle, or \\citestyle (m, a
    match of NATBIB_COMMAND) sets natbib's punctuation. Returns whether it
    was one natbib reads, which keeps the style's preset from applying."""
    text, pos, args = m.string, m.end(), []
    optional = None
    at = argument_space(text, pos)
    if m.group(1) == "bibpunct" and text.startswith("[", at):
        close = closing_bracket(text, at)
        if close > 0:
            optional, pos = text[at + 1:close], close + 1
    while len(args) < (6 if m.group(1) == "bibpunct" else 1):
        at = argument_space(text, pos)
        if not text.startswith("{", at):
            break
        close = matching_brace(text, at)
        if close < 0:
            break
        args.append(text[at + 1:close - 1])
        pos = close
    if m.group(1) == "bibpunct" and len(args) == 6:
        mode = {"n": "n", "s": "s"}.get(args[3].strip(), "a")
        style.update(open=args[0], close=args[1], sep=args[2], mode=mode, aysep=args[4],
                     yysep=args[5])
        if optional is not None:
            style["cmt"] = optional
        return True
    if m.group(1) == "setcitestyle" and args:
        for item in option_list(args[0]):
            name, _, value = item.partition("=")
            name, value = name.strip(), value.strip()
            if value.startswith("{") and value.endswith("}"):
                value = value[1:-1]
            if not _:
                natbib_keyword(name, style)
            elif name in ("open", "close", "aysep", "yysep"):
                style[name] = value
            elif name == "notesep":
                style["cmt"] = value
            elif name == "citesep":
                style["sep"] = value
        return True
    if m.group(1) == "citestyle" and args:
        # An unknown style sets nothing, but still keeps the preset off.
        if args[0].strip() in NATBIB_PRESETS:
            style.update(zip(("open", "close", "sep", "mode", "aysep", "yysep"),
                             NATBIB_PRESETS[args[0].strip()]))
        return True
    return False


def citation_style(joined, bst, preamble=None):
    """How the book prints its citations (natbib's punctuation, above), from
    the book's code, joined, and its bibliography style, bst: LaTeX's own
    \\cite's, the cite package's, sorted and compressed, or natbib's, from
    its defaults, its options (and \\PassOptionsToPackage's), \\bibpunct,
    \\setcitestyle, and \\citestyle in the book's order, and the style's
    preset, as natbib.sty sets them at \\begin{document}. preamble: the
    matches of NATBIB_COMMAND LaTeX reads before \\begin{document}, all of
    joined's when None; one after it sets the punctuation from where it
    stands (natbib_command)."""
    natbib = code_matches(NATBIB, joined)
    if not natbib:
        style = dict(LATEX_CITE)
        cite = code_matches(CITE_PACKAGE, joined)
        if cite:
            # The cite package's: sorted, an unknown key first, and
            # compressed, unless its options say not.
            options = option_list(cite[0].group(1) or "")
            style.update(sort="nosort" not in options, compress="nocompress" not in options,
                         unknown_first=True)
        return style
    style = dict(NATBIB_DEFAULT, natbib=True)
    preset = True
    given = set()
    for m in natbib:
        given |= {o.replace(" ", "") for o in option_list(m.group(1) or "")}
    for m in code_matches(re.compile(r"\\PassOptionsToPackage\s*\{([^{}]*)\}\s*\{\s*natbib\s*\}"),
                          joined):
        given |= {o.replace(" ", "") for o in option_list(m.group(1))}
    for option in NATBIB_OPTIONS:
        if option not in given:
            continue
        if option == "numbers":
            style.update(mode="n", open="[", close="]", sep=",")
        elif option == "super":
            style.update(mode="s", open="", close="")
        elif option == "authoryear":
            style.update(mode="a", open="(", close=")", sep=";")
        elif option in ("sort", "compress"):
            style[option] = True
        elif option == "sort&compress":
            style.update(sort=True, compress=True)
        elif option not in ("nobibstyle", "bibstyle"):
            natbib_keyword(option, style)
        preset = option in ("authoryear", "bibstyle") or (
            preset and option in ("sort", "compress", "sort&compress"))
    for m in code_matches(NATBIB_COMMAND, joined) if preamble is None else preamble:
        if natbib_command(m, style):
            preset = False
    if preset and bst in NATBIB_PRESETS:
        style.update(zip(("open", "close", "sep", "mode", "aysep", "yysep"), NATBIB_PRESETS[bst]))
    return style


def natbib_label(label):
    """A .bbl label natbib reads as author and year, as (short names, year,
    extra letter, long names), or None (a number, alpha's Str87):
    Short(Year)Long and Short(Year), \\citeauthoryear{Long}{Short}{Year} and
    {Short}{Year}, \\astroncite{Short}{Year}, \\citename{Short, }Year, and
    apalike's Short, Year; the year's extra letter natbib's \\natexlab gives
    (1986{\\natexlab{a}}), or one after the year's digits (1986a)."""
    if label is None:
        return None
    text = bbl_words(re.sub(r"\\protect(?![A-Za-z@])\s*", "", label)).strip()
    command = re.match(r"\\(citeauthoryear|astroncite|citename)(?![A-Za-z@])", text)
    if command:
        pos, args = command.end(), []
        while True:
            at = argument_space(text, pos)
            if not text.startswith("{", at):
                break
            close = matching_brace(text, at)
            if close < 0:
                break
            args.append(text[at + 1:close - 1])
            pos = close
        if command.group(1) == "citeauthoryear" and len(args) >= 3 and args[2].strip():
            long, short, date = args[:3]
        elif command.group(1) in ("citeauthoryear", "astroncite") and len(args) >= 2:
            long, short, date = "", args[0], args[1]
        elif command.group(1) == "citename" and args:
            long, short, date = "", re.sub(r",\s*$", "", args[0].strip()), text[pos:]
        else:
            return None
    else:
        found = AUTHOR_YEAR.match(text)
        if found:
            short, date, long = found.group("short"), found.group("year"), found.group("long")
        else:
            # apalike's, as natbib splits it: at its commas.
            parts = (text + ", ").split(", ")
            if len(parts) < 3 or not parts[1].strip():
                return None
            long, short, date = "", parts[0], parts[1]
    date, extra = date.strip(), ""
    letter = re.search(r"\{?\\natexlab\s*\{([^{}]*)\}\}?", date)
    if letter:
        extra = letter.group(1)
        date = (date[:letter.start()] + date[letter.end():]).strip()
    else:
        tail = re.fullmatch(r"(.*\d)([a-z]{1,2})", date)
        if tail:
            date, extra = tail.group(1), tail.group(2)
    if not date and not extra:
        return None

    def balanced(words):
        """words without a brace at an end that nothing in them matches
        ({Knuth} as revtex's labels brace a name, split at its year)."""
        words = words.strip()
        while words.count("}") > words.count("{") and words.endswith("}"):
            words = words[:-1].rstrip()
        while words.count("{") > words.count("}") and words.startswith("{"):
            words = words[1:].lstrip()
        if words.startswith("{") and words.endswith("}") and matching_brace(words, 0) == len(words):
            words = words[1:-1].strip()
        return words
    return balanced(short), balanced(date), extra, balanced(long)


# A citation's first piece when it takes away the space before it, as
# natbib's superscripts do (\unskip).
UNSKIP = "\x00"


def citation_pieces(command, star, options, keys, found, style):
    """What a citation prints, as [(words, key, superscript)], key the entry
    the words link to or None, as LaTeX prints it, measured with LaTeX
    2026-06-01: LaTeX's own, [1, 2, p. 3], or a style's own labels (alpha's
    [Str87]); the cite package's, sorted and compressed, [1–3, 5]; and
    natbib's, and a command of natbib's a class or a package of the book's
    loads it for (elsarticle's), as natbib prints it (natbib_pieces).
    found: {key: entry}, an entry a dict of number, short, year, extra,
    long. A key with no entry is ?, as LaTeX prints it."""
    if command == "nocite":
        return []
    if style.get("natbib") or command != "cite":
        return natbib_pieces(command, star, options, keys, found, style)
    out = []

    def add(words, key=None):
        if words:
            out.append((words, key if key in found else None, False))
    post = options[-1] if options else ""

    def number(key):
        return found[key]["number"] if key in found else "?"
    order = list(keys)
    if style["sort"]:
        last = 0 if style.get("unknown_first") else 2
        order.sort(key=lambda k: (1, int(number(k))) if str(number(k)).isdigit() else (last, 0))
    runs = []
    for key in order:
        value = number(key)
        previous = number(runs[-1][-1]) if runs else None
        if style["compress"] and runs and str(value).isdigit() and str(previous).isdigit() \
                and int(value) == int(previous) + 1:
            runs[-1].append(key)
        else:
            runs.append([key])
    add(style["open"])
    for index, run in enumerate(runs):
        if index:
            add(style["sep"] + " ")
        if len(run) >= 3:
            add(number(run[0]), run[0])
            add(NDASH)
            add(number(run[-1]), run[-1])
        else:
            for at, key in enumerate(run):
                if at:
                    add(style["sep"] + " ")
                add(number(key), key)
    add((style["cmt"] + post if post else "") + style["close"])
    return out


def natbib_pieces(command, star, options, keys, found, style):
    """What a citation prints under natbib, as citation_pieces gives it, as
    natbib.sty prints it, its \\NAT@citex for author and year and its
    \\NAT@citexnum for numbers, superscripts, and \\citenum, in the book's
    punctuation (citation_style), measured with LaTeX 2026-06-01. Author
    and year: Knuth [1984] and [Knuth, 1984, 1986a,b], an author cited
    again in a row named once, a year again given its letter alone, or ?
    without one; \\cite as \\citet, or \\citep with a note; the long names
    for a starred command; each name capitalized by \\Citet and the rest.
    Numbers: Knuth [2] for \\citet, a year without its letter, a name as
    the entry gives it; the keys sorted when the book says so (one with no
    entry last) and compressed, a run's end printed where natbib prints it,
    after a key with no entry it took in; superscripts in their own boxes,
    the space before one taken away (a first piece UNSKIP when it's the
    space before the citation), \\citeyearpar the same as \\citeyear. A key
    with no entry is ?, which natbib prints without the separator before
    it with numbers, and without the one after it."""
    pre, post = (options + ["", ""])[:2] if len(options) == 2 else ("", options[0]) \
        if options else ("", "")
    base = command[:1].lower() + command[1:]
    mode = style["mode"]
    if base == "cite":
        base = "citep" if options or mode != "a" else "citet"
    if base == "citeyearpar" and mode == "s":
        base = "citeyear"
    # natbib's switches: \NAT@swa (the citation in brackets of its own,
    # \NAT@cite's), \NAT@ctype (names and years, names, years), \NAT@par
    # (brackets at all).
    swa = base in ("citep", "citealp", "citeyearpar", "citenum")
    ctype = {"citeauthor": 1, "citeyear": 2, "citeyearpar": 2}.get(base, 0)
    numeric = mode in ("n", "s") or base == "citenum"
    superscript = mode == "s"
    opening, closing = (style["open"], style["close"]) \
        if base in ("citet", "citep", "citeyearpar") else ("", "")
    sep, cmt, yysep = style["sep"], style["cmt"], style["yysep"]
    space = "" if superscript else " "                # \NAT@space
    upper = command[:1].isupper() and not numeric     # \NAT@up, for author and year
    order = list(keys)
    if style["sort"]:
        order.sort(key=lambda k: (0, int(found[k]["number"]))
                   if k in found and str(found[k]["number"]).isdigit() else (1, 0))
    body = []

    def put(words, key=None, sup=False):
        if words:
            body.append((words, key if key in found else None, sup))

    def unskip():
        """\\unskip: the space before taken away."""
        if body and body[-1][0][-1:] in (" ", "~"):
            words, key, sup = body.pop()
            put(words[:-1], key, sup)

    def mbox(words, key=None):
        """\\NAT@mbox: words in a box, raised with superscripts, the space
        before them taken away."""
        if superscript:
            unskip()
        put(words, key, superscript)

    def emit(actions):
        for kind, words, key in actions:
            (mbox if kind == "mbox" else put)(words, key)

    def name(entry):
        words = entry["long"] if star and entry["long"] else entry["short"]
        return words[:1].upper() + words[1:] if upper else words

    def wrapped():
        """\\NAT@cite's brackets and notes around the citation."""
        lead = opening + (pre + " " if pre else "")
        tail = (cmt + post if post else "") + closing
        return ([(lead, None, False)] if lead else []) + body \
            + ([(tail, None, False)] if tail else [])
    citea = []                          # \@citea, the separator before the next key
    if numeric:
        num = last_num = None
        nm, pending = "", None          # \NAT@nm, \NAT@last@yr
        for key in order:
            entry = found.get(key)
            if entry is None:
                put("?")
                continue
            last_num, last_nm = num, nm
            num, nm = str(entry["number"]), name(entry)
            if swa and ctype:
                emit(citea)
                put(entry["year"] or "(year?)", key)
                citea = [("put", sep + space, None)]
            elif swa:
                this = int(num) if num.isdigit() else -2
                last = int(last_num) if last_num is not None and last_num.isdigit() else -1
                if style["compress"] and this != last and this == last + 1:
                    pending = (citea if pending is None else [("put", NDASH, None)]) \
                        + [("put", num, key)]
                else:
                    if style["compress"]:
                        emit(pending or [])
                        pending = None
                    emit(citea)
                    put(num, key)
                citea = [("put", sep + space, None)]
            elif ctype == 0:
                if last_nm == nm:
                    put(yysep + space)
                else:
                    emit(citea)
                    put(nm + " ")
                    mbox(opening)
                if pre:
                    put(pre + " ")
                mbox(num, key)
                citea = [("mbox", closing, None), ("put", sep + " ", None)]
            else:
                emit(citea)
                put(nm if ctype == 1 else entry["year"] or "(year?)", key)
                citea = [("put", sep + " ", None)]
        if style["compress"]:
            emit(pending or [])
        if not swa:
            if ctype == 0 and post:
                put(cmt + post)
            mbox(closing)
            return body
        if base == "citenum":
            # \citenum makes natbib's superscript a space.
            return ([(UNSKIP, None, False), (" ", None, False)] if superscript else []) + body
        if not superscript:
            return wrapped()
        raised = [(w, k, True) for w, k, _ in [(opening, None, False)] + body
                  + [(closing, None, False)] if w]
        return [(pre, None, False) if pre else (UNSKIP, None, False)] + raised \
            + ([(" " + post, None, False)] if post else [])
    nm = year = date = ""
    for key in order:
        entry = found.get(key)
        if entry is None:
            emit(citea)
            put("?")
            date = ""
            continue
        last_nm, last_year = nm, year
        nm = entry["long"] if star and entry["long"] else entry["short"]
        year, date = entry["year"], entry["year"] + entry["extra"]
        if ctype == 0 and date and last_nm == nm:
            put(yysep)
            if last_year == year:
                put(entry["extra"] or "?", key)
            else:
                unskip()
                put(" " + date, key)
        elif ctype == 0 and date and not swa:
            emit(citea)
            put(name(entry) + " " + opening + (pre + " " if pre else ""))
            put(date, key)
        else:
            emit(citea)
            put(name(entry) + style["aysep"] + " " + date if ctype == 0 and date
                else name(entry) if ctype < 2 else date, key)
        citea = [("put", (closing if date and not swa else "") + sep + " ", None)]
    if swa:
        return wrapped()
    put(cmt + post if post else "")
    put(closing if date else "")
    return body


def citation_latex(pieces):
    """A citation's pieces as LaTeX the reader reads: a bracket braced, so it
    ends no optional argument the citation is in, each label a link, and a
    superscript one \\textsuperscript."""
    out = []
    for words, key, sup in pieces:
        if words == UNSKIP:
            continue
        words = "\\hyperref[%s%s]{%s}" % (BIB_ID, key, words) if key \
            else words.replace("[", "{[}").replace("]", "{]}")
        out.append("\\textsuperscript{%s}" % words if sup else words)
    return "".join(out)


def citation_inlines(pieces):
    """A citation's pieces as inlines, for one the book's own macro made,
    which the reader keeps as a citation: each label a link."""
    out = []
    for words, key, sup in pieces:
        if words == UNSKIP:
            continue
        words = re.sub(r"[{}]|\\[A-Za-z@]+\s*", "", words).replace("~", "\u00a0")
        inlines = [{"t": "Space"} if w == " " else {"t": "Str", "c": w}
                   for w in re.split(r"( )", words) if w]
        inlines = [{"t": "Link", "c": [["", [], []], inlines, ["#" + BIB_ID + key, ""]]}] \
            if key else inlines
        out += [{"t": "Superscript", "c": inlines}] if sup else inlines
    return out


def resolve_citations(blocks, setup):
    """Each citation the reader kept, which a macro of the book's own made
    after the copy wrote out the book's own (\\newcommand{\\see}[1]{\\cite{#1}}),
    written as the label LaTeX prints, in place, from its raw command; the
    reader's citation has nothing a writer but LaTeX's prints, and a
    superscript takes away the space before it, as natbib's does. setup:
    bibliographies's. Returns how many."""
    if not setup:
        return 0
    done = [0]

    def walk(node):
        if isinstance(node, list):
            for index, item in enumerate(node):
                if isinstance(item, dict) and item.get("t") == "Cite":
                    raw = "".join(i["c"][1] for i in item["c"][1]
                                  if i.get("t") == "RawInline" and i["c"][0] == "latex")
                    m = CITE_COMMAND.match(raw)
                    cited = citation_at(raw, m) if m else None
                    if cited:
                        pieces = citation_pieces(*cited[:4], setup["found"], setup["style"])
                        node[index] = {"t": "Span", "c": [["", ["citation"], []],
                                                          citation_inlines(pieces)]}
                        before = node[index - 1] if index else None
                        if pieces and pieces[0][0] == UNSKIP and isinstance(before, dict):
                            if before.get("t") in ("Space", "SoftBreak"):
                                node[index - 1] = {"t": "Str", "c": ""}
                            elif before.get("t") == "Str" and before["c"].endswith(" "):
                                before["c"] = before["c"][:-1]
                        done[0] += 1
                        continue
                walk(item)
        elif isinstance(node, dict) and isinstance(node.get("c"), list):
            walk(node["c"])
    walk(blocks)
    return done[0]


BIB_MARKER = "TextbookImproverBibliography"
BIB_HEADING = "TEXTBOOKIMPROVERBIBLIOGRAPHY"
ADDBIBRESOURCE = re.compile(r"\\addbibresource\s*(?:\[[^]]*\])?\s*\{\s*([^}]*?)\s*\}")
PRINTBIBLIOGRAPHY = re.compile(r"\\printbibliography(?![A-Za-z@])\s*(?:\[[^]]*\])?")
# biblatex's full citations, which Pandoc's reader drops with their keys:
# OpenIntro gives each data set's source so, 111 times.
FULLCITE = re.compile(r"\\((?:foot)?fullcite)(\*?)(?![A-Za-z@])")
FULL_STYLE = "textbookimprover-plain"


def database_paths(base, master, resources):
    """The files of a book's bibliography databases, each as given or with
    .bib, beside the book or its master; one not found (a remote resource)
    is left out."""
    found = []
    for resource in resources:
        for candidate in (resource, resource + ".bib",
                          os.path.join(os.path.dirname(master), resource),
                          os.path.join(os.path.dirname(master), resource + ".bib")):
            if os.path.isfile(os.path.join(base, candidate)):
                found.append(os.path.join(base, candidate))
                break
    return found


def full_style(where):
    """plain.bst without its change of a title's case, written in where as
    FULL_STYLE (its license asks a changed copy be renamed): biblatex prints
    a title as the database gives it, and plain's lowercasing changes a
    macro in one (\\oiRedirect, OpenIntro's, to \\oiredirect). Returns the
    style's name, or plain's when there's no plain.bst to copy."""
    try:
        done = subprocess.run(["kpsewhich", "plain.bst"], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
    except OSError:
        return "plain"
    path = done.stdout.strip()
    if done.returncode or not os.path.isfile(path):
        return "plain"
    text = read_text(path)
    if '{ title "t" change.case$ }' not in text:
        return "plain"
    os.makedirs(where, exist_ok=True)
    write_text(os.path.join(where, FULL_STYLE + ".bst"),
               text.replace('{ title "t" change.case$ }', "{ title }"))
    return FULL_STYLE


def full_citations(base, work, texts, files, master, originals, resources, counts, say,
                   printed=False):
    """biblatex's \\fullcite and \\footfullcite in texts written out as the
    entry in full, which the reader drops, keys and all: from BibTeX's .bbl
    in plain's style, which is close to biblatex's standard one, a title's
    case as the database gives it; \\footfullcite a footnote, ended with a
    period as biblatex ends one, several entries joined by semicolons, a
    note before and after (a page's number, p. 5) as biblatex sets them.
    The entry is read with the book's macros, so one of the book's own in a
    database is what the book makes it. printed: the book prints its
    bibliography (\\printbibliography), which lists them, so each is also a
    \\nocite for citeproc. Without BibTeX, each is a \\cite or \\footcite,
    for Pandoc's citeproc. Returns how many were written."""
    keys = []
    for _, _, item in reading_order([(n, texts[n]) for n in files], watch=FULLCITE):
        if isinstance(item, re.Match):
            cited = citation_at(item.string, item)
            if cited:
                keys += [k for k in cited[3] if k not in keys]
    if not keys:
        return 0
    databases = [re.sub(r"\.bib$", "", r) for r in resources
                 if database_paths(base, master, [r])]
    where = os.path.join(work, "bibtex")
    bbl = run_bibtex(base, work, os.path.dirname(master), keys, full_style(where),
                     databases) if databases else None
    entries = {key: words for _, key, words in bbl_entries(bbl)} if bbl else None
    written, missing = 0, []

    def note(post):
        """A postnote as biblatex sets it: a page's number or range with its
        prefix."""
        if re.fullmatch(r"\d+", post.strip()):
            return "p.~" + post.strip()
        if re.fullmatch(r"\d+\s*(?:-{1,2}|–)\s*\d+", post.strip()):
            return "pp.~" + post.strip()
        return post
    for name in files:
        text = texts[name]
        spans = skip_spans(text)
        skip = sorted(spans + [(d[0], d[1]) for d in definitions_in(text, spans)])
        edits = []
        for m in FULLCITE.finditer(text):
            if in_spans(m.start(), skip) or escaped(text, m.start()):
                continue
            cited = citation_at(text, m)
            if not cited:
                continue
            command, _, options, cited_keys, end = cited
            footnote = command == "footfullcite"
            if entries is None:
                edits.append((m.start(), m.end(), "\\footcite" if footnote else "\\cite"))
                continue
            pre, post = options if len(options) == 2 else ("", options[0]) if options \
                else ("", "")
            missing += [k for k in cited_keys if k not in entries and k not in missing]
            words = "; ".join(re.sub(r"\.\s*$", "", entries.get(k, k)) for k in cited_keys)
            words = (pre + " " if pre else "") + words + (", " + note(post) if post else "")
            if footnote:
                words = "\\footnote{%s%s}" % (words, "" if words.rstrip().endswith(".") else ".")
            if printed:
                words += "\\nocite{%s}" % ",".join(cited_keys)
            edits.append((m.start(), end, words))
            written += 1
        for start, stop, words in reversed(edits):
            text = text[:start] + words + text[stop:]
        texts[name] = text
    if entries is None:
        say(("BibTeX couldn't write out biblatex's full citations (\\fullcite, "
             "\\footfullcite): %s. So " % BIBTEX_PROBLEM[0] if BIBTEX_PROBLEM[0] and databases
             else "No BibTeX here to write out biblatex's full citations (\\fullcite, "
             "\\footfullcite), so " if databases else "biblatex's full citations (\\fullcite, "
             "\\footfullcite) have no database here to write them out from, so ")
            + "each is a citation of Pandoc's citeproc, in its style, not the entry in full.")
    elif missing:
        say(f"{len(missing)} key(s) of biblatex's full citations have no entry in "
            + ", ".join(databases) + ", so each is its key, as biblatex prints it: "
            + ", ".join(missing[:10]) + ".")
    if written:
        counts["full_citations"] = counts.get("full_citations", 0) + written
    return written


def unskipped(text, pos):
    """Where the space before pos begins, which \\unskip takes away: spaces,
    a tie (~), or a line's end, unless a comment ends the line, which
    leaves no space, or the line is blank, a paragraph's end."""
    at = pos
    while at > 0 and text[at - 1] in " \t":
        at -= 1
    if at > 0 and text[at - 1] == "~" and not escaped(text, at - 1):
        return at - 1
    if at > 0 and text[at - 1] == "\n":
        line_start = text.rfind("\n", 0, at - 1) + 1
        line = text[line_start:at - 1]
        if line.strip() and not re.search(r"(?<!\\)(?:\\\\)*%", line):
            at -= 1
            while at > line_start and text[at - 1] in " \t":
                at -= 1
    return at


def bibliographies(base, work, texts, files, master, originals, counts, say):
    """texts ({name: text}) with the book's bibliography written out where
    \\bibliography stands, from BibTeX's .bbl with the book's style (BibTeX
    run on the book's citations, else the .bbl a build of the book left), or
    where a thebibliography the book writes itself stands, and each citation
    as the label it prints, linked to its entry. A book under biblatex, or
    with no BibTeX here and no .bbl, has a marker where its bibliography
    goes, and its citations are left to Pandoc's citeproc, after the
    reading (cite_with_citeproc). Returns what resolve_citations or
    cite_with_citeproc needs, or None when there's no bibliography."""
    joined = "\n".join(t for _, t in originals)
    chapters = any(code_matches(re.compile(r"\\chapter\s*\*?\s*[\[{]"), t) for _, t in originals)
    heading = ("\\chapter*{Bibliography}" if chapters else "\\section*{References}") \
        + "\\label{%s}" % BIB_HEADING
    begin = code_matches(BEGIN_DOCUMENT, texts[master])
    body_start = {master: begin[0].end() if begin else 0}

    def first(pattern):
        for name in files:
            text = texts[name]
            for m in code_matches(pattern, text, skip_spans(text)):
                if m.start() >= body_start.get(name, 0):
                    return name, m
        return None

    def citeproc(place, resources):
        """A marker for the bibliography where place is, for citeproc."""
        found_paths = database_paths(base, master, resources)
        if place:
            name, m = place
            texts[name] = texts[name][:m.start()] + "\n\n%s\n\n%s\n\n" % (heading, BIB_MARKER) \
                + texts[name][m.end():]
        return {"citeproc": found_paths, "printed": place is not None} if found_paths else None
    if code_matches(BIBLATEX, joined):
        resources = [r for m in code_matches(ADDBIBRESOURCE, joined) for r in [m.group(1)]]
        resources += [d.strip() for m in code_matches(BIBLIOGRAPHY, joined)
                      for d in m.group(1).split(",") if d.strip()]
        full_citations(base, work, texts, files, master, originals, resources, counts, say,
                       first(PRINTBIBLIOGRAPHY) is not None)
        if not resources or not code_matches(re.compile(
                r"\\[A-Za-z]*cite[a-z]*\*?\s*[\[{]"), "\n".join(texts.values())):
            return None
        setup = citeproc(first(PRINTBIBLIOGRAPHY), resources)
        if setup:
            # Said once citeproc has citations to make (a definition's may
            # be all the book has left).
            setup["said"] = ("The book cites with biblatex, which Pandoc's citeproc reads from "
                             "its databases: its citations and bibliography are in Pandoc's "
                             "own style (author and date), not the book's.")
        return setup
    place, own = first(BIBLIOGRAPHY), first(THEBIBLIOGRAPHY)
    if place is None and own is None:
        return None
    keys = []
    for _, _, item in reading_order([(n, texts[n]) for n in files], watch=CITE_COMMAND):
        if isinstance(item, re.Match):
            cited = citation_at(item.string, item)
            if cited:
                keys += [k for k in cited[3] if k not in keys]
    styles = [m.group(1) for m in code_matches(BIBLIOGRAPHYSTYLE, joined)]
    if own is not None:
        name, m = own
        text = texts[name]
        end = re.search(r"\\end\s*\{thebibliography\}", text[m.end():])
        stop = m.end() + end.end() if end else len(text)
        source = text[m.start():stop]
        entries = bbl_entries(source)
        span = (m.start(), stop)
    else:
        name, m = place
        databases = [d.strip() for d in m.group(1).split(",") if d.strip()]
        bbl = run_bibtex(base, work, os.path.dirname(master), keys or ["*"],
                         styles[-1] if styles else "plain", databases)
        if bbl is not None and BIBTEX_PROBLEM[0]:
            say(f"BibTeX made the bibliography with an error, as LaTeX's build would read it: "
                f"{BIBTEX_PROBLEM[0]}.")
        built = os.path.join(base, os.path.splitext(master)[0] + ".bbl")
        cannot = ("BibTeX couldn't make the bibliography (%s)" % BIBTEX_PROBLEM[0]
                  if BIBTEX_PROBLEM[0] else "No BibTeX here to make the bibliography")
        if bbl is None and os.path.exists(built):
            bbl = read_text(built)
            say(f"{cannot}, so it's the one the book's own build left, "
                f"{os.path.relpath(built, base)}.")
        if bbl is None:
            setup = citeproc(place, databases)
            say(cannot + ", and the book's own build left no .bbl, so "
                + ("Pandoc's citeproc makes it, in its own style (author and date), not the "
                   "book's." if setup else
                   f"its {len(keys)} citation(s) are empty: its database, "
                   + ", ".join(databases) + ", isn't here either."))
            return setup
        source = bbl
        entries = bbl_entries(bbl)
        span = (m.start(), m.end())
    # How the book prints a citation at \begin{document}, and each entry's
    # label: its number, the one BibTeX's style gives (alpha's Str87), or
    # natbib's author and year, which natbib takes for numbers when any
    # entry has none.
    preamble, timeline = [], []
    at = {n: [m.start() for m in CITE_COMMAND.finditer(texts[n])] for n in files}
    at.setdefault(master, []).append(body_start[master])
    body = False
    for kind, where, item in reading_order([(n, texts[n]) for n in files], watch=NATBIB_COMMAND,
                                           at=at):
        if kind == "match":
            (timeline if body else preamble).append(item)
        elif kind == "at" and body:
            timeline.append((where, item))
        elif kind == "at" and where == master and item == body_start[master]:
            body = True
    style = citation_style(joined, styles[-1] if styles else None, preamble)
    parsed = [natbib_label(label) for label, _, _ in entries]

    def numbers(style):
        if style.get("natbib") and style["mode"] == "a" and not (entries and all(parsed)):
            style["mode"] = "n"
        return style
    numbers(style)
    author_year = style.get("natbib") and style["mode"] == "a"
    if style.get("natbib") and not author_year:
        # natbib's \natexlab prints nothing with numbers.
        entries = bbl_entries(source, letters=False)
    # A \setcitestyle, \bibpunct, or \citestyle after \begin{document} sets
    # natbib's punctuation from where it stands.
    style_at, current = {}, style
    for item in timeline:
        if isinstance(item, re.Match):
            if style.get("natbib"):
                current = dict(current)
                natbib_command(item, current)
                numbers(current)
        else:
            style_at[item] = current
    found = {}
    for index, ((label, key, _), p) in enumerate(zip(entries, parsed), start=1):
        number = str(index) if author_year or (style.get("natbib") and p) or not label \
            else label.strip()
        short, year, extra, long = p if p else ("(author?)", "(year?)", "", "")
        found[key] = {"number": number, "short": short, "year": year, "extra": extra,
                      "long": long}
    labeled = [(found[key]["number"], key, words) for _, key, words in entries]
    block = bibliography_block(labeled, author_year, heading) if entries else ""
    missing = [k for k in keys if k not in found and k != "*"]
    if missing and entries:
        say(f"{len(missing)} citation key(s) have no entry in the bibliography, so each is "
            "printed ?, as LaTeX prints it: " + ", ".join(missing[:10])
            + (", and more" if len(missing) > 10 else "") + ".")
    text = texts[name]
    texts[name] = text[:span[0]] + block + text[span[1]:]
    written = 0
    for name in files:
        text = texts[name]
        spans = skip_spans(text)
        # A citation in a definition is the reader's, which resolve_citations
        # writes once the macro's made it.
        skip = sorted(spans + [(d[0], d[1]) for d in definitions_in(text, spans)])
        edits = []
        for m in CITE_COMMAND.finditer(text):
            if in_spans(m.start(), skip) or escaped(text, m.start()):
                continue
            cited = citation_at(text, m)
            if not cited:
                continue
            pieces = citation_pieces(*cited[:4], found, style_at.get((name, m.start()), style))
            start = unskipped(text, m.start()) if pieces and pieces[0][0] == UNSKIP \
                else m.start()
            edits.append((start, cited[4], citation_latex(pieces)))
            written += cited[0] != "nocite"
        for start, end, words in reversed(edits):
            text = text[:start] + words + text[end:]
        texts[name] = text
    if written:
        counts["citations"] = counts.get("citations", 0) + written
    if entries:
        which = "bibliography_own" if own is not None else "bibliography"
        counts[which] = counts.get(which, 0) + len(entries)
    return {"found": found, "style": style}


def bibliography_heading(blocks):
    """The bibliography's heading, which the copy labels, given the id the
    reader would give it (references, bibliography, unless the book has
    one) and the class bibliography, so a page's title isn't taken for two
    headings when an article's References is the second. Returns whether
    there was one."""
    ids, found = set(), []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kind, c = node.get("t"), node.get("c")
            attr = c[1] if kind == "Header" else c[0] if kind in (
                "Div", "Span", "Figure", "Table", "CodeBlock", "Code", "Link", "Image") else None
            if attr and isinstance(attr[0], str):
                ids.add(attr[0])
                if kind == "Header" and attr[0] == BIB_HEADING:
                    found.append(node)
            if isinstance(c, list):
                walk(c)
    walk(blocks)
    for header in found:
        attr = header["c"][1]
        stem = re.sub(r"[^a-z0-9]+", "-", stringify(header["c"][2]).lower()).strip("-") \
            or "bibliography"
        new, n = stem, 0
        while new in ids:
            n += 1
            new = "%s-%d" % (stem, n)
        ids.add(new)
        attr[0] = new
        if "bibliography" not in attr[1]:
            attr[1].append("bibliography")
    return bool(found)


def cite_with_citeproc(doc_path, setup, env, cwd):
    """The book's citations made by Pandoc's citeproc from its databases,
    its bibliography where the marker bibliographies left is, or none when
    the book prints none (biblatex without \\printbibliography): the JSON at
    doc_path rewritten. Returns whether citeproc ran."""
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    changed = [False]

    def place(blocks):
        for index, block in enumerate(blocks):
            if block.get("t") == "Para" and block["c"] == [{"t": "Str", "c": BIB_MARKER}]:
                blocks[index] = {"t": "Div", "c": [["refs", [], []], []]}
                changed[0] = True
            elif block.get("t") == "Div":
                place(block["c"][1])
    place(doc["blocks"])
    with open(doc_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    command = ["pandoc", "-f", "json", "-t", "json", "--citeproc", doc_path, "-o", doc_path,
               "-M", "link-citations=true"] + [x for path in setup["citeproc"]
                                                for x in ("--bibliography", path)]
    if not changed[0]:
        command += ["-M", "suppress-bibliography=true"]
    done = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    return done.returncode == 0


def prepare(base, work, master, say, macros=""):
    """The book copied into work/latex with what Pandoc can't read put
    right, its drawings rendered into base/rendered/. Returns a dict:
    master (the copy's path), order, front_role, files, missing,
    counts, preamble, copy, colors, counters, citations (bibliographies's),
    and layout (page_layout)."""
    copy = os.path.join(work, "latex")
    if os.path.isdir(copy):
        shutil.rmtree(copy)
    files, missing = reached(base, master)
    counts = {}
    texts = {}
    originals = [(name, read_text(os.path.join(base, name))) for name in files]
    in_math = math_macros([t for _, t in originals])
    counting = book_counters(originals, originals[0][1] if originals else "")
    for name, text in originals:
        texts[name] = repair_text(text, counts, in_math, counting["counters"])
    # A chapter \include-d by the book's own macro, written out, so the
    # pages are cut where it begins; the book's environments as the
    # commands LaTeX makes of them, which Pandoc's reader can balance; its
    # colors as CSS.
    expand_include_macros(texts, files, counts)
    expand_cite_macros(texts, files, counts)
    environment_definitions(texts, files, counts)
    resolve_colors(texts, files, counts)
    write_out_columns(texts, counts)
    write_out_item_refs(texts, counts, counting["ref_names"])
    citations = bibliographies(base, work, texts, files, master, originals, counts, say)
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
    # given the extension, PDF and EPS made SVG. A person's definitions
    # win over the book's, as they do in the reading.
    definitions_file = None
    if macros and os.path.isfile(os.path.join(base, macros)):
        definitions_file = (macros, read_text(os.path.join(base, macros)))
    expand_image_macros(texts, files, counts, definitions_file)
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
    # before each \include and after it. Split again, since its drawings
    # and images may have been replaced.
    _, body, rest = split_master(texts[master])
    spans = skip_spans(body)
    pieces, last, index = [], 0, 0
    for m in INCLUDE.finditer(body):
        if in_spans(m.start(), spans):
            continue
        pieces.append(body[last:m.start()])
        pieces.append("\n\n" + MARKER_LINE % index + "\n\n" + m.group(0)
                      + "\n\n" + END_MARKER_LINE % index + "\n\n")
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
    # The book's colors, for a PDF built from its pages, whose formulas
    # can still name one: the reader keeps a formula's TeX as written.
    colors = [m.group(0) for m in book_colors(originals, include_macros(originals))]
    return {"master": os.path.join(copy, master), "order": order,
            "front_role": front_role, "files": files, "missing": missing,
            "counts": counts, "preamble": preamble, "copy": copy, "colors": colors,
            "counters": counting, "citations": citations,
            "layout": page_layout(originals, include_macros(originals))}


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
        edits.append((end, 0, "\\end{%s}" % name))
        edits.append((start, 1, "\\begin{%s}" % name))
    # Where one table ends and the next begins (\end{tabular}\begin{tabular}),
    # the end goes first: of two pieces put at one place, the later is first.
    for at, _, piece in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:at] + piece + text[at:]
    return text


def stringify(inlines):
    """The text of a title or a name, without a \\thanks's note."""
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
            elif kind == "Note":
                return
            elif "c" in node:
                walk(node["c"])
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(inlines)
    return " ".join("".join(out).split())


SET_APART = {"Emph", "Strong", "SmallCaps", "Underline", "Span"}


def author_names(inlines):
    """The names in one \\author, as Pandoc reads it, its lines split at
    \\\\: a line set as the first line is (plain, or all in italics, say)
    is a name, and one set differently is the affiliation under a name.
    OpenIntro Statistics names three authors in one \\author with no
    \\and, each with an employer in italics beneath; read whole, they
    were one author of 20 words. With every line set alike, each is
    given, an affiliation as a name, so no author is left out."""
    lines, line = [], []
    for node in inlines:
        if node.get("t") == "LineBreak":
            lines.append(line)
            line = []
        else:
            line.append(node)
    lines.append(line)
    lines = [l for l in lines if stringify(l)]

    def apart(l):
        return all(n.get("t") in SET_APART for n in l
                   if n.get("t") not in ("Space", "SoftBreak", "Note"))
    if not lines:
        return []
    first = apart(lines[0])
    return [stringify(l) for l in lines if apart(l) == first]


def _is_marker(block):
    return block.get("t") == "Para" and len(block["c"]) == 1 \
        and block["c"][0].get("t") == "Str" and MARKER_TEXT.match(block["c"][0]["c"])


def _holds_marker(blocks):
    return any(_is_marker(b) or (b.get("t") == "Div" and _holds_marker(b["c"][1]))
               for b in blocks)


def lift_markers(blocks):
    """A division holding a page's marker given up, its blocks in its place:
    an \\include inside an environment the reader keeps as a division (the
    appendix package's appendices) put the marker inside it, where the cut
    didn't find it, so the file's page was the page before's, the marker's
    text shown in it."""
    out = []
    for block in blocks:
        if block.get("t") == "Div" and _holds_marker(block["c"][1]):
            out.extend(lift_markers(block["c"][1]))
        else:
            out.append(block)
    return out


ROLES_AT = {"frontmatter": "front", "mainmatter": "main", "appendix": "appendix",
            "appendices": "appendix", "backmatter": "back"}


def _holds_split(blocks, levels):
    return any((b.get("t") == "Header" and b["c"][0] in levels)
               or (b.get("t") == "Div" and _holds_split(b["c"][1], levels)) for b in blocks)


GONE = object()


def take_divisions(node, found):
    """node with the spans the counting left where a division command
    stood taken out, wherever they are, each one's name appended to found
    in the document's order. Returns node, or GONE for a paragraph that
    held nothing else."""
    if isinstance(node, list):
        out = []
        for item in node:
            if isinstance(item, dict) and item.get("t") == "Span" \
                    and DIVISION_CLASS in item["c"][0][1]:
                found.append(dict(item["c"][0][2]).get("division"))
                continue
            kept = take_divisions(item, found)
            if kept is not GONE:
                out.append(kept)
        node[:] = out
        return node
    if isinstance(node, dict) and node.get("c") is not None and node.get("t") not in (
            "Math", "Code", "CodeBlock", "RawInline", "RawBlock", "Str"):
        before = len(found)
        take_divisions(node["c"], found)
        if len(found) > before and node.get("t") in ("Para", "Plain") and not [
                i for i in node["c"] if i.get("t") not in ("Space", "SoftBreak", "LineBreak")]:
            return GONE
    return node


def cut_pages(doc, order, master_stem, front_role, split_levels=()):
    """The whole book's document cut into pages at the markers: a list of
    (stem, role, blocks, own), own true for a page of the master's own
    text. What comes before the first \\include is the master's own page,
    named for it, when it holds anything. Where the master's text begins
    again after an \\include, it goes on with that file's page (the review
    exercises OpenIntro Statistics \\input-s after each chapter), until a
    heading at one of split_levels, a part's or a chapter's: from there
    it's a page of its own, named for the master and numbered (book-1),
    with the role the division commands before it give it. A \\part set
    between two \\include-s had landed at the end of the chapter before,
    and titled its page. A master that \\include-s nothing is one page."""
    taken = {master_stem} | {os.path.splitext(os.path.basename(p))[0] for p, _ in order}
    pages = [[master_stem, front_role, [], True]]
    role, before_appendices, own, count = "main", "main", True, 0
    queue, at = lift_markers(doc["blocks"]), 0
    while at < len(queue):
        block = queue[at]
        at += 1
        if own and order and block.get("t") == "Div" and _holds_split(block["c"][1],
                                                                      split_levels):
            # A part or a chapter the master sets inside an environment
            # the reader keeps as a division (the appendix package's
            # appendices): the division given up, its blocks in its place.
            queue[at:at] = block["c"][1]
            continue
        found = []
        block = take_divisions(block, found)
        for name in found:
            if name == "endappendices":
                role = before_appendices
            elif name in ROLES_AT:
                if name == "appendices":
                    before_appendices = role
                role = ROLES_AT[name]
        if block is GONE:
            continue
        if block.get("t") == "Para" and len(block["c"]) == 1 \
                and block["c"][0].get("t") == "Str":
            m = MARKER_TEXT.match(block["c"][0]["c"])
            if m:
                if m.group(1) == MARKER:
                    path, file_role = order[int(m.group(2))]
                    stem = os.path.splitext(os.path.basename(path))[0]
                    pages.append([stem, file_role, [], False])
                    own = False
                else:
                    own = True
                continue
        if own and order and block.get("t") == "Header" and block["c"][0] in split_levels:
            while True:
                count += 1
                name = "%s-%d" % (master_stem, count)
                if name not in taken:
                    break
            taken.add(name)
            pages.append([name, role, [], True])
        pages[-1][2].append(block)
    return [tuple(p) for p in pages if p[2] or not p[3]]


def hoist_headings(blocks, keep=()):
    """Each heading inside a division taken out to the page's own level,
    the division split around it, its id kept by its first part: a page's
    title and its sections are found only there. OpenIntro Statistics sets
    each chapter's title in a framed box (its chapterpage, mdframed in a
    minipage), which the reader gives as two divisions with the heading
    inside, and every chapter's page was titled with its file's name, its
    EPUB chapter cut before the heading, and its sections out of the
    chapter's nesting. A heading taken out of a division in another
    language (babel's otherlanguage) takes its lang and dir with it; one in
    a division of keep's classes, a theorem's or a proof's (an example's
    \\paragraph{Solution.}), stays there. Returns (blocks, the headings
    taken out)."""
    moved = [0]
    keep = set(keep)

    def split(div, depth):
        attr, content = div["c"]
        if keep & set(attr[1]):
            return [div]
        language = [[k, v] for k, v in attr[2] if k in ("lang", "dir")]
        out, current, first = [], [], True

        def part():
            nonlocal first
            if current or (first and attr[0]):
                out.append({"t": "Div", "c": [[attr[0] if first else "", attr[1], attr[2]],
                                              list(current)]})
                first = False
            current.clear()
        for block in content:
            for item in split(block, depth + 1) if block.get("t") == "Div" else [block]:
                if item.get("t") == "Header":
                    part()
                    own = {k for k, _ in item["c"][1][2]}
                    item["c"][1][2].extend(pair for pair in language if pair[0] not in own)
                    out.append(item)
                    if depth == 0:
                        moved[0] += 1
                else:
                    current.append(item)
        part()
        return out
    out = []
    for block in blocks:
        if block.get("t") == "Div" and any(b.get("t") == "Header" for b in split(
                json.loads(json.dumps(block)), 1)):
            out.extend(split(block, 0))
        else:
            out.append(block)
    return out, moved[0]


def promote_headings(blocks):
    """A page whose headings all sit below the top level, one of the files
    that continue a chapter (OpenIntro Statistics's t-table and chi-square
    table, each a section of its distribution tables' chapter), has them
    raised until its first is H1, its title: it had none, and its title
    was its file's name. Returns the levels raised, 0 when none."""
    levels = []

    def walk(node, change=0):
        if isinstance(node, list):
            for item in node:
                walk(item, change)
        elif isinstance(node, dict):
            if node.get("t") == "Header":
                if change:
                    node["c"][0] -= change
                else:
                    levels.append(node["c"][0])
            elif node.get("c") is not None and node.get("t") not in (
                    "Math", "Code", "CodeBlock", "RawInline", "RawBlock", "Str"):
                walk(node["c"], change)
    walk(blocks)
    if not levels or min(levels) <= 1:
        return 0
    walk(blocks, min(levels) - 1)
    return min(levels) - 1


# --------------------------------------------------------------------------
# the definitions sample: the book's macros texmath can't read
# --------------------------------------------------------------------------

SAMPLE = "latex-conversion-macros-sample.tex"
NEWCOMMAND = re.compile(r"\\(?:(?:re)?newcommand|providecommand)\*?\s*\{?\s*\\([A-Za-z@]+)"
                        r"\s*\}?\s*(?:\[(\d)\])?\s*(?:\[[^]]*\])?\s*\{")
# A formula's delimiters; \\[6mm], a line break with its space, isn't \[.
MATH_SPANS = re.compile(
    r"(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<!\\)\$(.+?)(?<!\\)\$|(?<!\\)\\\((.+?)\\\)"
    r"|(?<!\\)\\\[(.+?)\\\]|\\begin\{(equation|align|alignat|flalign|gather|multline"
    r"|eqnarray|displaymath|math)(\*?)\}(.+?)\\end\{\5\6\}", re.S)
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


def math_macros(texts):
    """The names of the book's macros a formula uses, and of those their
    bodies use in turn: texmath reads each body there, as Pandoc expands
    it, so a rewrite for the reader of text mustn't touch them."""
    found_defs = definitions(texts)
    uses = math_uses(texts, sorted(found_defs))
    found = {n for n, k in uses.items() if k}
    queue = sorted(found)
    while queue:
        for m in re.finditer(r"\\([A-Za-z@]+)", found_defs[queue.pop()][1]):
            if m.group(1) in found_defs and m.group(1) not in found:
                found.add(m.group(1))
                queue.append(m.group(1))
    return found


def math_uses(texts, names):
    """How often each macro is used inside a formula, in code."""
    uses = dict.fromkeys(names, 0)
    if not names:
        return uses
    pattern = re.compile(r"\\(" + "|".join(re.escape(n) for n in names)
                         + r")(?![A-Za-z@])")
    for text in texts:
        # math_spans, so a $ in a comment pairs with nothing: OpenIntro's
        # sample listed \section and three others as used in formulas.
        for start, end in math_spans(text):
            for u in pattern.finditer(text, start, end):
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


PROBE_MARK = "TEXTBOOKIMPROVERPROBE"


def probe(copy, preamble, macros, filter_path, extra=""):
    """Which of macros [(name, arguments)] give a formula texmath can't
    make MathML of, read with the book's preamble (and extra definitions)
    and the read-time repairs."""
    if not macros:
        return set()
    head, _, _ = preamble.rpartition("\\begin")
    # Each formula after a mark of its own: a macro whose expansion ends a
    # paragraph, or makes a block, would otherwise put every formula after
    # it against the wrong macro.
    body = "".join("\n\n%s%d $\\%s%s$\n" % (PROBE_MARK, i, n, "".join("{x}" for _ in range(a)))
                   for i, (n, a) in enumerate(macros))
    path = os.path.join(copy, "TextbookImproverProbe.tex")
    write_text(path, head + extra + "\n\\begin{document}\n" + body
               + "\n\\end{document}\n")
    read = subprocess.run(["pandoc", "-f", "latex", "-t", "json",
                           "TextbookImproverProbe.tex",
                           "--lua-filter=" + filter_path],
                          cwd=copy, capture_output=True, text=True)
    if read.returncode != 0:
        return set()
    html = subprocess.run(["pandoc", "-f", "json", "-t", "html",
                           "--math-method=mathml"], input=read.stdout,
                          capture_output=True, text=True).stdout
    parts = re.split(PROBE_MARK + r"(\d+)", html)
    after = {int(parts[k]): parts[k + 1] for k in range(1, len(parts) - 1, 2)}
    return {name for i, (name, _) in enumerate(macros) if "<math" not in after.get(i, "")}


def alt_arguments(texts, definitions_text=""):
    """[(name, argument, given, calls, example, definition)]: each of the
    book's macros for an image (image_macros) taking an argument its body
    never uses, which at least half of its calls give a phrase in, as an
    author writes alt text there for another build: OpenIntro Statistics's
    \\Figure[alt]{width}{name}, whose first argument reaches only its
    screen-reader build (style_simple.tex, as \\pdftooltip's text), in 293
    of its 318 calls. definition passes the argument on as the image's alt
    text; it's a person's to adopt, since only a person can say that the
    phrase is that. A macro definitions_text, a person's definitions file,
    redefines already is left out."""
    macros, spans = image_macros(texts)
    found = []
    for name, macro in sorted(macros.items()):
        if macro["alt"] is not None or macro["keyed"] or re.search(
                r"\\renewcommand\s*\{?\s*\\%s(?![A-Za-z@])" % re.escape(name), definitions_text):
            continue
        body = macro["body"]
        unused = [k for k in range(1, macro["arguments"] + 1)
                  if not re.search(r"#%d(?!\d)" % k, body)]
        calls = []
        for text_name, text in texts if unused else ():
            calls += macro_calls(text, {name: macro},
                                 sorted(skip_spans(text) + spans.get(text_name, [])))
        for k in unused if calls else ():
            given = [args[k - 1][0].strip() for _, _, _, args in calls
                     if args[k - 1][1] is not None and len(args[k - 1][0].strip()) >= 10
                     and " " in args[k - 1][0].strip()]
            if len(given) * 2 < len(calls):
                continue
            m = BODY_GRAPHICS.search(body)
            if m.group(2):
                passed = body[:m.start(2) + 1] + "alt={#%d}," % k + body[m.start(2) + 1:]
            else:
                passed = body[:m.end() - 1] + "[alt={#%d}]" % k + body[m.end() - 1:]
            spec = ("[%d]" % macro["arguments"] if macro["arguments"] else "") + (
                "[%s]" % macro["default"] if macro["default"] is not None else "")
            found.append((name, k, len(given), len(calls), given[0],
                          "\\renewcommand{\\%s}%s{%s}" % (name, spec, passed)))
            break
    return found


def macro_sample(base, preps, filter_path, macros_file, say):
    """Write latex-conversion-macros-sample.tex: the book's macros whose
    formulas texmath still can't read, a definition for each whose drawing
    has one reading, and the rest as written, for a person to define; and
    the book's macros for an image with an argument that may be alt text
    (alt_arguments), each with the definition that would pass it on.
    preps: what prepare returned, for each of the book's documents, each
    probed with its own preamble. Returns (suggested, left, alt), alt the
    names of those image macros."""
    if isinstance(preps, dict):
        preps = [preps]
    defined, uses, failing, suggestions = {}, {}, set(), {}
    person = read_text(os.path.join(base, macros_file)) \
        if macros_file and os.path.isfile(os.path.join(base, macros_file)) else ""
    alt = {}
    for prep in preps:
        for found in alt_arguments([(n, read_text(os.path.join(base, n)))
                                    for n in prep["files"]], person):
            alt.setdefault(found[0], found)
    for prep in preps:
        copy = prep["copy"]
        texts = [read_text(os.path.join(copy, n)) for n in prep["files"]]
        originals = [read_text(os.path.join(base, n)) for n in prep["files"]]
        # The commands the reading copy makes of the book's environments
        # are the copy's, not the book's macros, and a person's definition
        # goes by the book's own text, not the copy's.
        environments = {d[3] for t in originals for d in environment_definitions_in(t)}
        made = environments | {"end" + e for e in environments}
        own = {n: d for n, d in definitions(texts).items() if n not in made}
        authors = definitions(originals)
        own_uses = math_uses(texts, sorted(own))
        used = [(n, own[n][0]) for n in sorted(own) if own_uses[n]]
        copy_preamble = split_master(read_text(prep["master"]))[0]
        # A macro the book defines in its text, where it's used (OpenIntro
        # sets \actmean to 21 in the section that uses it): the probe, which
        # has only the preamble, gets the definition too, or its formula
        # would fail for the macro being unknown.
        in_text = "".join(own[n][2] + "\n" for n, _ in used if own[n][2] not in copy_preamble)
        own_failing = probe(copy, copy_preamble, used, filter_path, in_text)
        for name in own_failing:
            defined.setdefault(name, own[name][:2] + (authors.get(name, own[name])[2],))
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
                      filter_path, in_text + extra) if own_suggestions else set()
        for name, s in own_suggestions.items():
            if name not in still:
                suggestions.setdefault(name, s)
    sample = os.path.join(base, SAMPLE)
    if not failing and not alt:
        if os.path.exists(sample):
            os.remove(sample)
        return 0, 0, []
    lines = [
        "% Written by convert.py: the book's macros whose formulas texmath",
        "% can't make MathML of, so they reach the pages as TeX, and its",
        "% macros for an image with an argument that may be alt text. Check",
        "% it, then save it as " + macros_file + " (or merge it into yours).",
        "% Definitions there are read after the book's preamble, so they",
        "% win; the book's own files never change, and a source target",
        "% writes them into its copy unless its latex_definitions is off.", ""]
    for name, k, given, calls, example, definition in (alt[n] for n in sorted(alt)):
        shown = re.sub(r"\s+", " ", example)
        lines.append("%% \\%s is the book's macro for an image, and it doesn't use its "
                     "argument %d," % (name, k))
        lines.append("%% which %d of its %d calls give a phrase in, as alt text might be:"
                     % (given, calls))
        lines.append("%%   \"%s\"" % (shown if len(shown) <= 70 else shown[:67] + "..."))
        lines.append("% If that is each image's alt text, this passes it on, to the pages")
        lines.append("% and to a source target's copy, and so to its PDF; a call that")
        lines.append("% gives none leaves its image without, as before:")
        lines.extend("% " + line for line in definition.splitlines())
        lines.append("")
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
    return len(suggestions), len(failing) - len(suggestions), sorted(alt)
