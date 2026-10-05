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


def resolve(base, name):
    """A name \\input or \\include gives, as a path relative to base, or
    None when no such file is there. TeX tries the name as written and
    with .tex added."""
    name = name.strip().strip('"')
    for candidate in (name, name + ".tex"):
        if os.path.isfile(os.path.join(base, candidate)):
            return os.path.normpath(candidate)
    return None


def reached(base, master):
    """(files, missing): every .tex file the master reaches through
    \\input, \\include, and \\subfile, in the order first reached, and
    the names it gives that aren't there."""
    files, missing, queue = [], [], [master]
    while queue:
        name = queue.pop(0)
        if name in files:
            continue
        files.append(name)
        text = read_text(os.path.join(base, name))
        for m in code_matches(INPUT, text):
            target = m.group(2) or m.group(3)
            path = resolve(base, target)
            if path is None:
                if target not in missing:
                    missing.append(target)
            elif path not in files and path not in queue:
                queue.append(path)
    return files, missing


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
                          r"((?:\s|%[^\n]*\n|\\fi\b)*)\\begin\s*\{(tabular\*?|tabularx|"
                          r"longtable|array)\}")
DECLARATIONS = {(True, False): "FirstRow", (False, True): "FirstColumn",
                (True, True): "Both"}


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
        key = (bool(rows and rows.group(1).strip() == "1"),
               bool(cols and cols.group(1).strip() == "1"))
        if key not in DECLARATIONS:
            if rows or cols:
                counter["header_other"] = counter.get("header_other", 0) + 1
            continue
        begin = text.rfind("\\begin", m.start(), m.start(3))
        end = environment_end(text, m.group(3), begin)
        if end < 0:
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
# the copy, the reading, and the pages
# --------------------------------------------------------------------------

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
    preamble, body, rest = split_master(texts[master])
    order, front_role = book_outline(body)

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

    # Images: the extension written in, PDF and EPS made SVG.
    record_path = os.path.join(base, RENDERED, ".rendered.json")
    try:
        with open(record_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        record = {}
    dirs = graphics_paths(preamble)
    for name in files:
        texts[name] = repair_graphics(base, work, texts[name], dirs, record,
                                      counts, say)
    if record:
        write_text(record_path, json.dumps(record, indent=1, sort_keys=True))
    for index, name in enumerate(files):
        texts[name] = mark_tables(texts[name], index)

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
NEWCOMMAND = re.compile(r"\\(?:re|provide)?newcommand\*?\s*\{?\s*\\([A-Za-z@]+)"
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


def macro_sample(base, prep, filter_path, macros_file, say):
    """Write latex-conversion-macros-sample.tex: the book's macros whose
    formulas texmath still can't read, a definition for each whose drawing
    has one reading, and the rest as written, for a person to define.
    Returns (suggested, left)."""
    copy = prep["copy"]
    texts = [read_text(os.path.join(copy, n)) for n in prep["files"]]
    defined = definitions(texts)
    uses = math_uses(texts, sorted(defined))
    used = [(n, defined[n][0]) for n in sorted(defined) if uses[n]]
    copy_preamble = split_master(read_text(prep["master"]))[0]
    failing = probe(copy, copy_preamble, used, filter_path)
    sample = os.path.join(base, SAMPLE)
    if not failing:
        if os.path.exists(sample):
            os.remove(sample)
        return 0, 0
    suggestions = {}
    for name in sorted(failing):
        args, body, _ = defined[name]
        s = suggest(body)
        if s is not None:
            suggestions[name] = s
    # Keep a suggestion only when texmath reads what it makes.
    extra = "".join("\\renewcommand{\\%s}%s{%s}\n" % (
        n, "[%d]" % defined[n][0] if defined[n][0] else "", s)
        for n, s in suggestions.items())
    still = probe(copy, copy_preamble, [(n, defined[n][0]) for n in suggestions],
                  filter_path, extra) if suggestions else set()
    for name in still:
        suggestions.pop(name, None)
    lines = [
        "% Written by convert.py: the book's macros whose formulas texmath",
        "% can't make MathML of, so they reach the pages as TeX. Check it,",
        "% then save it as " + macros_file + " (or merge it into yours).",
        "% Definitions there are read after the book's own, by the",
        "% conversion only; the book itself never changes.", ""]
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
