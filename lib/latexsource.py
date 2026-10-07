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


SUBFIGURE_COMMAND = re.compile(r"\\subfigure(?![A-Za-z@])")


def subfigures(text, counter):
    """The obsolete subfigure package's \\subfigure[caption]{...}, which
    Pandoc's reader doesn't know: its caption is dropped and the \\label in
    it is lost, so a reference to it goes nowhere (25 in OpenIntro
    Statistics). Written as subcaption's subfigure environment, which the
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
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
        counter["subfigures"] = counter.get("subfigures", 0) + 1
    return text


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


def color_rgb(expression, colors):
    """A color as xcolor reads one, (r, g, b) or None: a name the book
    defines (colors, color_values's), xcolor's own, or dvipsnames's; a mix,
    red!30 (with white), red!70!black, and on (oiB!50!white!80); and a
    complement, -red. A name of svgnames's or x11names's isn't known here,
    so a mix with one is None."""
    expression = expression.strip()
    complement = expression.startswith("-")
    parts = expression.lstrip("-").split("!")

    def named(name):
        name = name.strip()
        if name in colors:
            return colors[name]
        if name in XCOLOR_BASE:
            return XCOLOR_BASE[name]
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


def color_values(statements):
    """{name: (r, g, b)} for the book's color statements, in the order LaTeX
    reads them (book_colors), the last of a name's winning, as xcolor
    defines them: \\colorlet's from the colors defined before it, and
    \\providecolor's only for a name not yet defined; a name whose last
    definition this can't read has none."""
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
            rgb, name = color_rgb(m.group(2), values), m.group(1)
        if rgb:
            values[name] = rgb
        else:
            values.pop(name, None)
    return values


COLOR_STYLE = re.compile(r"^((?:background-)?color): (.*)$", re.S)


def color_spans(node, values):
    """Each span or division the reader made of \\textcolor or \\colorbox
    (a division when it held paragraphs) given its color as CSS, in place,
    when CSS can't read it as it is: a name the
    book defines (the Nu checker found 785 on OpenIntro Statistics's pages:
    "oiB" is not a color value), a mix (red!50!black), and a name of
    xcolor's that CSS lacks (BrickRed). A name CSS has (red, black) is left,
    and a color none of these is is taken out, since a browser ignores it
    anyway. values: color_values's. Returns how many changed."""
    changed = 0
    if isinstance(node, list):
        for item in node:
            changed += color_spans(item, values)
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
                rgb = color_rgb(color, values)
                if rgb:
                    kept.append([pair[0], "%s: %s" % (m.group(1), css_rgb(rgb))])
                changed += 1
            node["c"][0][2] = kept
        if "c" in node:
            changed += color_spans(node["c"], values)
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
NEWTHEOREM = re.compile(r"\\newtheorem\*?\s*\{\s*([A-Za-z@]+)\s*\}")
# What the reader keeps only the content of: subequations, and breqn's
# dmath (numbered; dmath* isn't).
SUBEQUATIONS = re.compile(r"\\begin\s*\{(subequations|dmath)\}")
APPENDICES = re.compile(r"\\begin\s*\{appendices\}")
SECTION_LEVELS = (("part", -1), ("chapter", 0), ("section", 1), ("subsection", 2),
                  ("subsubsection", 3), ("paragraph", 4), ("subparagraph", 5))
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
    # The appendix package's environment begins the appendices as
    # \\appendix does.
    for m in APPENDICES.finditer(text):
        if not in_spans(m.start(), keep) and not escaped(text, m.start()):
            edits.append((m.end(), m.end(), counter_mark("division", "appendix")))
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
    chapters = any(code_matches(re.compile(r"\\chapter(?![A-Za-z@])"), t) for t in code)
    parts = any(code_matches(re.compile(r"\\part(?![A-Za-z@])"), t) for t in code)
    if chapters:
        resets = {"section": "chapter", "subsection": "section", "subsubsection": "subsection",
                  "paragraph": "subsubsection", "subparagraph": "paragraph",
                  "figure": "chapter", "table": "chapter", "equation": "chapter",
                  "footnote": "chapter", "enumii": "enumi", "enumiii": "enumii",
                  "enumiv": "enumiii"}
        formats = {"chapter": r"\arabic{chapter}", "section": r"\thechapter.\arabic{section}",
                   "figure": r"\thechapter.\arabic{figure}", "table": r"\thechapter.\arabic{table}",
                   "equation": r"\thechapter.\arabic{equation}"}
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
    defined, theorems = set(STANDARD_COUNTERS), set()
    for t in code:
        spans = skip_spans(t)
        for m in code_matches(NEWCOUNTER, t, spans):
            defined.add(m.group(1))
            if m.group(2):
                resets[m.group(1)] = m.group(2)
        for m in code_matches(NEWTHEOREM, t, spans):
            theorems.add(m.group(1))
    # Within, without, and \the definitions in LaTeX's order, the last
    # winning; and the values the preamble sets.
    begin = code_matches(BEGIN_DOCUMENT, master_text)
    at = {texts[0][0]: [begin[0].start()]} if begin and texts else {}
    pattern = re.compile("(?:%s)|(?:%s)" % (COUNTER_WITHIN.pattern, COUNTER_COMMAND.pattern))
    initial, in_body = {}, False
    for kind, _, item in reading_order(texts, at=at, watch=pattern):
        if kind == "at":
            in_body = True
        elif kind == "define":
            if item[2].startswith("the") and len(item[2]) > 3 and item[3] == 0:
                formats[item[2][3:]] = item[5].strip()
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
            "chapters": chapters}


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
    the pages numbers it so too; \\eqref's number is in parentheses. The
    marks go. setup: book_counters's. Returns (keys, values): how many
    keys were written, and references and counters given a value;
    counts, if given, gets equation_numbers, the formulas numbered."""
    counters = dict(setup["initial"])
    formats, resets = dict(setup["formats"]), setup["resets"]
    levels, theorems = setup["levels"], set(setup["theorems"])
    state = {"current": None, "numbered": True}
    labels, refs, written = {}, [], [0]
    numbered = [0]

    def reset(name):
        for child, parent in resets.items():
            if parent == name:
                counters[child] = 0
                reset(child)

    def step(name):
        counters[name] = counters.get(name, 0) + 1
        reset(name)

    def expand(text, depth=0):
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
            labels[new] = number if number is not None else last[0]
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

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        kind, c = node.get("t"), node.get("c")
        if kind == "Header" and "unnumbered" not in c[1][1] and state["numbered"] \
                and levels.get(c[0]):
            step(levels[c[0]])
            state["current"] = the(levels[c[0]])
        elif kind == "Link" and c[2][0].startswith("#%s:" % COUNTER_MARK):
            parts = c[2][0][len(COUNTER_MARK) + 2:].split(":")
            op = parts[0]
            if op in ("refstepcounter", "stepcounter") and len(parts) > 1:
                step(parts[1])
                if op == "refstepcounter":
                    state["current"] = the(parts[1])
            elif op in ("setcounter", "addtocounter") and len(parts) > 2:
                number = value(":".join(parts[2:]))
                if number is not None:
                    counters[parts[1]] = number + (
                        counters.get(parts[1], 0) if op == "addtocounter" else 0)
            elif op == "division" and len(parts) > 1:
                state["numbered"] = parts[1] in ("mainmatter", "appendix")
                if parts[1] == "appendix":
                    top = "chapter" if setup["chapters"] else "section"
                    counters[top] = 0
                    formats[top] = r"\Alph{%s}" % top
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
        elif kind == "Link" and any(k == "reference" for k, _ in c[0][2]):
            reference = dict((k, v) for k, v in c[0][2])["reference"]
            refs.append((node, reference, key(reference)))
        saved = state["current"]
        if kind in ("OrderedList", "Note") or (kind == "Div" and set(c[0][1]) & theorems):
            # An item's, a note's, and a theorem's own counters aren't
            # counted here: a label in one records nothing.
            state["current"] = None
        if c is not None and kind not in ("Math", "Code", "CodeBlock", "RawInline", "RawBlock"):
            walk(c)
        if kind in ("OrderedList", "Note", "Div"):
            state["current"] = saved

    walk(blocks)
    given = 0
    for node, reference, new in refs:
        attrs = node["c"][0][2]
        for pair in attrs:
            if pair[0] == "reference":
                pair[1] = new
        if node["c"][2][0] == "#" + reference:
            node["c"][2][0] = "#" + new
        placeholder = [{"t": "Str", "c": "[%s]" % reference}]
        if node["c"][1] == placeholder and labels.get(new):
            # \eqref, amsmath's, sets the number in parentheses, whatever
            # the label numbers; a \tag's text may hold a formula.
            shown = labels[new]
            if dict((k, v) for k, v in attrs).get("reference-type") == "eqref":
                shown = "(%s)" % shown
            node["c"][1] = tag_inlines(shown) if "$" in shown \
                else [{"t": "Str", "c": shown}]
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


def prepare(base, work, master, say, macros=""):
    """The book copied into work/latex with what Pandoc can't read put
    right, its drawings rendered into base/rendered/. Returns a dict:
    master (the copy's path), order, front_role, files, missing,
    counts, preamble, copy, colors, counters, and layout (page_layout)."""
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
    environment_definitions(texts, files, counts)
    resolve_colors(texts, files, counts)
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
    # The book's colors, for a PDF built from its pages, whose formulas
    # can still name one: the reader keeps a formula's TeX as written.
    colors = [m.group(0) for m in book_colors(originals, include_macros(originals))]
    return {"master": os.path.join(copy, master), "order": order,
            "front_role": front_role, "files": files, "missing": missing,
            "counts": counts, "preamble": preamble, "copy": copy, "colors": colors,
            "counters": counting,
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
        edits.append((end, "\\end{%s}" % name))
        edits.append((start, "\\begin{%s}" % name))
    for at, piece in sorted(edits, key=lambda e: e[0], reverse=True):
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


def cut_pages(doc, order, master_stem, front_role):
    """The whole book's document cut into pages at the markers: a list of
    (stem, role, blocks). What comes before the first marker is the
    master's own page, named for it, when it holds anything."""
    pages = [[master_stem, front_role, []]]
    for block in lift_markers(doc["blocks"]):
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
