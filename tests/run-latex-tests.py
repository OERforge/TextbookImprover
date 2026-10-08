#!/usr/bin/env python3
"""
run-latex-tests.py -- check LaTeX as a source, end to end through convert.py.

    python3 tests/run-latex-tests.py           # run every case
    python3 tests/run-latex-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later. The drawing and the PDF image need a LaTeX
engine and pdftocairo; without them those checks are skipped and say so.

WHAT IS LOAD-BEARING HERE

The book is written by this script: a master that \\include-s four
chapters, two of them in folders, with the constructs Pandoc's reader
(3.12) can't take, each put right on a copy before reading
(lib/latexsource.py): an ifthen boolean, \\input without braces, a table
inside \\centerline, a picture environment, an image named without its
extension, a PDF image, an artifact, alt text holding LaTeX, and a
formula with \\mbox{\\tiny ...}. Each check would fail without the repair
it names; the author's files are checked unchanged afterwards, since
everything happens on a copy.

The page cut is checked against the master's \\include-s, the roles
against its division commands, and a \\ref into another chapter against
the page the label is on.

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

import argparse
import csv
import hashlib
import html as html_module
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")

MASTER = r"""\documentclass{book}
\usepackage[english]{babel}
\usepackage{ifthen}
\usepackage{graphicx}
\usepackage{amssymb}
\usepackage{tikz}
\newboolean{Solutions}
\setboolean{Solutions}{false}
\newcommand{\Znoneg}{{\mathbb Z}^{\mbox{\tiny noneg}}}
\newcommand{\relR}{\mbox{\textsf R}}
\newcommand{\suchthat}{\; \rule[-3pt]{.5pt}{13pt} \;}
\newcommand{\weird}{\mbox{\rotatebox{90}{$\star$}}}
\title{A Test Book}
\author{A. Author}
\begin{document}
\AddToShipoutPictureBG{\begin{tikzpicture}[remember picture,overlay]
\draw (0,0) -- (1,1);\end{tikzpicture}}
\maketitle
\frontmatter
Copyright 2026 A. Author. This front matter is the master's own.

\include{preface}
\mainmatter
\include{ch1/one}
\include{ch2/two}
\appendix
\include{answers}
\end{document}
"""

PREFACE = r"""\chapter*{Preface}
A preface.
"""

ONE = r"""\chapter{One}
\label{ch:one}
\section{First}
\label{sec:first}
\ifthenelse{\boolean{Solutions}}{SOLUTION TEXT}{EXERCISE TEXT}

\input ch1/table

\begin{figure}
\begin{center}
\begin{picture}(40,20)
\put(0,0){\line(1,0){40}}
\put(5,5){$x$}
\end{picture}
\end{center}
\caption{A line}
\label{fig:line}
\end{figure}

Images: \includegraphics[alt={50\% shaded}]{img/square.png}
and \includegraphics[alt={A square
  over two lines}]{img/square.png}
and \includegraphics{img/square} and
\includegraphics[artifact]{img/rule.png} and
\includegraphics{img/diagram.pdf}.

Sets: $\Znoneg$ and $a \relR b$ and $\{x \suchthat x > 0\}$, and
$a\hspace{10mm}b$, and $a \weird b$.
Stacked: \vtop{\hbox{\strut First line}\hbox{\strut Second $y$}} done.
Over a line: $p +
q$ ends. Pseudocode: \texttt{Let }$q = 0$\texttt{.}

\begin{tabular}{cc}
\begin{minipage}{3cm}Converses.

Inverses.\end{minipage} & \begin{tabular}{ccc}
 & & \\
 & $A \implies B$ & \\
 & & $B \implies A$ \\
\end{tabular} \\
\end{tabular}
Laws: $A \cong A \mbox{\hspace{12pt} and\hspace{4pt}also \hspace{12pt}} A \lor c$;
a blank: $2, 9, \rule{12pt}{.5pt}, 37$; raised: $x = \mbox{\raisebox{-2pt}{$\emptyset$}}$.

\begin{enumerate}
\item An item with a formula:
\[ x^2 + 1 \]
and more after it.
\item An item with a table:

\begin{tabular}{cc}
p & q \\
\end{tabular}

and text after it.
\item A blank to fill in:

\hrule

\item Nested:
\begin{enumerate}
\item A nested blank:

\hrule

\item Another nested item, with a blank too:

\hrule

\end{enumerate}
\item A quotation in an item:
\begin{quote}
Let $x$ be odd. Then
\[ x = 2k + 1 \]
for some integer $k$.
\end{quote}
\item The next item.
\end{enumerate}

\begin{figure}
\begin{tabular}{cc}
1 & 2 \\
\end{tabular}
\caption{A table set as a figure}
\end{figure}

\begin{quote}
Proof: a table follows.

\begin{tabular}{ccl}
 & $A \cup B$ & \rule{36pt}{0pt} Given \\
$=$ & $U \cap (A \cup B)$ & Identity law \\
 & \begin{minipage}{2in}A boxed aside.\end{minipage} & \\
\end{tabular}

Q.E.D.
\end{quote}

\tagpdfsetup{table/header-rows={1}}
\begin{tabular}{cc}
Head one & Head two \\
x & y \\
\end{tabular}
% \input{ch1/never}
\begin{verbatim}
\input ch1/never
\end{verbatim}
"""

TABLE = r"""\centerline{\begin{tabular}{cc}
alpha & beta \\ \cline{2-2}
gamma & delta \\
\end{tabular}}
"""

TWO = r"""\chapter{Two}
\begin{picture}(10,10)\undefinedcommandhere\end{picture}

See Section~\ref{sec:first} and Figure~\ref{fig:line}, in
Chapter~\ref{ch:one}.
"""

ANSWERS = r"""\chapter{Answers}
Answers.
"""

MACROS = r"""% For reading only: "such that" is drawn with \rule.
\renewcommand{\suchthat}{\mid}
"""


def png(path, rgb):
    """A 4x4 PNG of one color, written without an imaging library."""
    raw = b"".join(b"\x00" + bytes(rgb) * 4 for _ in range(4))

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw))
                 + chunk(b"IEND", b""))


def pdf(path, word=None):
    """A one-page PDF holding a blue rectangle, written by hand; with word,
    the word drawn beside it in Helvetica, which the PDF doesn't embed, as
    R's pdf() device writes a plot's labels."""
    stream = b"0 0 1 rg 5 5 30 10 re f\n"
    resources = b""
    if word:
        stream += b"0 g BT /F1 8 Tf 2 2 Td (%s) Tj ET\n" % word.encode("ascii")
        resources = b" /Resources << /Font << /F1 5 0 R >> >>"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 20] "
               b"/Contents 4 0 R" + resources + b" >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream
               + b"endstream"]
    if word:
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                       b"/Encoding /WinAnsiEncoding >>")
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(out)


def raster_pdf(path, word="Map", size=128):
    """A one-page PDF holding a smooth raster of size by size pixels, stored
    losslessly (Flate), and a word drawn in Helvetica, which the PDF
    doesn't embed: a heat map R draws. Returns the raster's bytes."""
    import math
    raw = bytes(int(255 * ((math.sin(x / 9.0) * math.cos(y / 7.0) + 1) / 2) ** (1 + c))
                for y in range(size) for x in range(size) for c in range(3))
    data = zlib.compress(raw)
    stream = b"q 32 0 0 32 4 4 cm /Im1 Do Q 0 g BT /F1 8 Tf 2 38 Td (%s) Tj ET\n" % (
        word.encode("ascii"))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 48] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
               b"/Encoding /WinAnsiEncoding >>",
               b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
               b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
               % (size, size, len(data)) + data + b"\nendstream"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    with open(path, "wb") as fh:
        fh.write(out)
    return raw


def write_book(work, macros=False, second_master=False, readme=True,
               epub=False):
    os.makedirs(os.path.join(work, "ch1"))
    os.makedirs(os.path.join(work, "ch2"))
    os.makedirs(os.path.join(work, "img"))
    files = {"book.tex": MASTER, "preface.tex": PREFACE, "ch1/one.tex": ONE,
             "ch1/table.tex": TABLE, "ch2/two.tex": TWO,
             "answers.tex": ANSWERS}
    if macros:
        files["latex-conversion-macros.tex"] = MACROS
    if second_master:
        files["workbook.tex"] = MASTER.replace("{false}", "{true}")
    if readme:
        files["README.md"] = "# The repository\n\nNot a page.\n"
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    png(os.path.join(work, "img", "square.png"), (90, 90, 90))
    png(os.path.join(work, "img", "rule.png"), (0, 0, 0))
    pdf(os.path.join(work, "img", "diagram.pdf"))
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 + ("  epub:\n    format: epub3\n  word:\n    format: docx\n"
                    "  md:\n    format: markdown\n  adoc:\n    format: asciidoc\n"
                    if epub else ""))


def fingerprint(work, skip_dirs=()):
    """The author's files, by content: everything but what a run writes,
    and the folders named in skip_dirs."""
    found = {}
    for top, _, names in os.walk(work):
        rel = os.path.relpath(top, work).split(os.sep)
        if any(rel[0].startswith(d) for d in skip_dirs):
            continue
        for name in names:
            path = os.path.join(top, name)
            if name.endswith((".tex", ".png", ".pdf", ".md")) and \
                    not name.endswith("-sample.tex") and \
                    "rendered" not in path and "html" not in path \
                    and os.sep + "back" + os.sep not in path \
                    and os.sep + "md-back" + os.sep not in path \
                    and os.sep + "md" + os.sep not in path \
                    and os.sep + "adoc" + os.sep not in path \
                    and os.sep + "adoc-back" + os.sep not in path:
                with open(path, "rb") as fh:
                    found[os.path.relpath(path, work)] = \
                        hashlib.sha256(fh.read()).hexdigest()
    return found


def convert(work, env=None):
    return subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"], cwd=work,
        capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)


def without_tagging_status(work):
    """The environment with kpsewhich unable to find LaTeX's tagging status
    data, installed or not: a kpsewhich ahead of the real one on PATH that
    finds nothing for that file and passes everything else on. LaTeX
    itself looks files up without the program, so its runs are as before."""
    real = shutil.which("kpsewhich")
    shim = os.path.join(work, "..", os.path.basename(work) + "-kpsewhich")
    os.makedirs(shim, exist_ok=True)
    with open(os.path.join(shim, "kpsewhich"), "w") as fh:
        fh.write("#!/bin/sh\n"
                 "case \"$1\" in latex-tagging-status.ltx) exit 1;; esac\n"
                 "exec %s \"$@\"\n" % (real or "false"))
    os.chmod(os.path.join(shim, "kpsewhich"), 0o755)
    return dict(os.environ, PATH=os.path.abspath(shim) + os.pathsep + os.environ["PATH"])


def latexsource_mark():
    """The text the reading copy gives a \\nameref until it's filled."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexsource
    return latexsource.NAMEREF_MARK


def read(work, *parts):
    with open(os.path.join(work, *parts), encoding="utf-8") as fh:
        return fh.read()


def epub_links_resolve(work):
    """Every #fragment link in the EPUB goes to a file that has the id:
    the file it names, or its own when it names none."""
    import posixpath
    import zipfile
    with zipfile.ZipFile(os.path.join(work, "epub", "book.epub")) as z:
        texts = {n: z.read(n).decode("utf-8") for n in z.namelist()
                 if n.endswith(".xhtml")}
    ids = {n: set(re.findall(r'\sid="([^"]+)"', t)) for n, t in texts.items()}
    links = [(n, posixpath.normpath(posixpath.join(posixpath.dirname(n), f)) if f else n, i)
             for n, t in texts.items()
             for f, i in re.findall(r'href="([^"#]*)#([^"]+)"', t)]
    return any("page-one" in held for held in ids.values()) and links \
        and all(i in ids.get(target, ()) for _, target, i in links)


def word_list_reads_back(work):
    """one.docx, read back as a source, gives the list whole: the table
    and the rule inside their items, and every item in one list."""
    back = os.path.join(work, "back")
    os.makedirs(back, exist_ok=True)
    shutil.copy(os.path.join(work, "word", "one.docx"), back)
    with open(os.path.join(back, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    convert(back)
    page = read(back, "html", "one.html")
    lists = re.findall(r"<ol[^>]*>(.*?)</ol>", page, re.S)
    whole = [l for l in lists if "An item with a formula" in l]
    outer = page[page.find("An item with a formula"):]
    outer = outer[:outer.find("The next item") + 1]
    return whole and "The next item" in page and "<table" in outer \
        and outer.count("<hr") >= 3 and "and text after it" in outer \
        and "Another nested item" in outer and "for some integer" in outer \
        and len(re.findall(r"<ol", page[page.find("An item with a formula"):
                                       page.find("The next item")])) == 1


def word_quote_reads_back(work):
    """The quotation holding a table, read back from one.docx (which
    word_list_reads_back converted), is one quotation with the table in it,
    and no cell is a quotation."""
    page = read(work, "back", "html", "one.html")
    quotes = re.findall(r"<blockquote>(.*?)</blockquote>", page, re.S)
    proof = [q for q in quotes if "Proof: a table follows" in q]
    return proof and "<table" in proof[0] and "Q.E.D." in proof[0] \
        and not any(("Given" in q or "boxed aside" in q) and "<table" not in q
                    for q in quotes)


def asciidoc_math_reads_back(work):
    """adoc/, the AsciiDoc target, read back as a source: one.html has
    as many formulas as the page it was written from."""
    back = os.path.join(work, "adoc-back")
    if not os.path.exists(back):
        shutil.copytree(os.path.join(work, "adoc"), back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        convert(back)
    page = os.path.join(back, "html", "one.html")
    return os.path.exists(page) and \
        read(work, "html", "one.html").count("<math") == read(back, "html", "one.html").count("<math")


def markdown_reads_back(work):
    """md/, the Markdown target, read back as a source: one.html has the
    same figures, a centered drawing's figure among them."""
    back = os.path.join(work, "md-back")
    shutil.copytree(os.path.join(work, "md"), back)
    with open(os.path.join(back, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    convert(back)
    def figures(page):
        return [" ".join(re.sub(r"<[^>]+>", " ", c).split())
                for c in re.findall(r"<figcaption>(.*?)</figcaption>", page, re.S)]
    before = figures(read(work, "html", "one.html"))
    after = figures(read(back, "html", "one.html")) \
        if os.path.exists(os.path.join(back, "html", "one.html")) else []
    return before and before == after


def word_math_in_list(work):
    """The Word file's display formula in a list item is numbered as the
    item's other paragraphs are, so reading it keeps the item whole."""
    import zipfile
    with zipfile.ZipFile(os.path.join(work, "word", "one.docx")) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paragraphs = re.findall(r"<w:p>.*?</w:p>", xml, re.S)
    formula = [p for p in paragraphs if "oMathPara" in p and "x" in p]
    return formula and all('<w:numId w:val="1000"' in p for p in formula) \
        and "tiqMath" not in xml


def can_draw():
    return bool((shutil.which("pdflatex") or shutil.which("lualatex"))
                and shutil.which("pdftocairo"))


# What the suite's books need from TeX beyond what LaTeX's tagging and
# Pandoc's template do (docs/installation.md): each TeX Live package, by a
# file it holds. Found on TinyTeX's smaller bundle (TinyTeX-1), from every
# file TeX read in a run of the suite that passed (-recorder) and then by
# what each build that still failed couldn't find; a package a copy is
# made without, and so never reads, can still be one LaTeX needs found
# (2026-10-08). And the one other tool the LaTeX target's SVG needs.
SUITE_TEX = [("babel-english", "english.ldf"), ("caption", "caption.sty"),
             ("fancyhdr", "fancyhdr.sty"), ("grfext", "grfext.sty"),
             ("luatex85", "luatex85.sty"), ("mdframed", "mdframed.sty"),
             ("pgf", "tikz.sty"), ("preview", "preview.sty"), ("soul", "soul.sty"),
             ("tabto-ltx", "tabto.sty"), ("tex-gyre", "texgyreheros-regular.otf"),
             ("titlesec", "titlesec.sty"), ("ulem", "ulem.sty"),
             ("wasysym", "wasysym.sty"), ("wrapfig", "wrapfig.sty")]


def tex_ready():
    """Where there's a TeX, the packages and tools the suite's books need
    that it lacks, as the check that names them and what installs them;
    None where it has them all or there's no TeX, whose checks skip."""
    if not (shutil.which("lualatex") or shutil.which("pdflatex")) \
            or not shutil.which("kpsewhich"):
        return None
    missing = [package for package, name in SUITE_TEX
               if not subprocess.run(["kpsewhich", name], capture_output=True,
                                     text=True, stdin=subprocess.DEVNULL).stdout.strip()]
    tools = [] if shutil.which("rsvg-convert") else ["rsvg-convert"]
    if not missing and not tools:
        return None
    return ("TeX has what the suite's books load, or the checks that build them "
            "fail: missing " + ", ".join(missing + tools) + " ("
            + "; ".join(([f"tlmgr install {' '.join(missing)}"] if missing else [])
                        + (["sudo apt install librsvg2-bin"] if tools else [])) + ")")


SKIPPED = []


def skip(reason):
    """A check that can't run here: reported, and passing."""
    if reason not in SKIPPED:
        SKIPPED.append(reason)
        print(f"  skip  {reason}")
    return True


def case_book(work):
    """The whole book: pages, roles, repairs, references."""
    write_book(work, macros=True, epub=True)
    before = fingerprint(work)
    result = convert(work)
    log = result.stdout + result.stderr
    one = read(work, "html", "one.html") \
        if os.path.exists(os.path.join(work, "html", "one.html")) else ""
    two = read(work, "html", "two.html") \
        if os.path.exists(os.path.join(work, "html", "two.html")) else ""
    import yaml
    sample = yaml.safe_load(read(work, "contents-sample.yaml")) \
        if os.path.exists(os.path.join(work, "contents-sample.yaml")) else {}
    project = (sample or {}).get("project", {})
    sample_text = read(work, "latex-conversion-macros-sample.tex") \
        if os.path.exists(os.path.join(work,
                                       "latex-conversion-macros-sample.tex")) else ""
    missing_alt = read(work, "image-alt-missing.csv") \
        if os.path.exists(os.path.join(work, "image-alt-missing.csv")) else ""
    return [
        ("the master's \\include-s are the pages, the master's own text one more",
         lambda: all(os.path.exists(os.path.join(work, "html", n + ".html"))
                     for n in ("book", "preface", "one", "two", "answers"))),
        ("a README beside the master is the repository's, not a page",
         lambda: not os.path.exists(os.path.join(work, "html", "README.html"))),
        ("the contents sample follows the master, roles from its divisions",
         lambda: project.get("contents") == [
             {"page": "book", "role": "front"},
             {"page": "preface", "role": "front"}, "one", "two",
             {"page": "answers", "role": "appendix"}]),
        ("and takes the title, author, and babel's language from the preamble",
         lambda: project.get("title") == "A Test Book"
         and project.get("authors") == ["A. Author"]
         and project.get("language") == "en"),
        ("an ifthen boolean is evaluated: one branch, not both or neither",
         lambda: "EXERCISE TEXT" in one and "SOLUTION TEXT" not in one),
        ("\\input without braces is read, and a table inside \\centerline",
         lambda: "<table" in one and "delta" in one),
        ("\\cline's column range is a rule, not a cell's text",
         lambda: "delta" in one and "2-2" not in one),
        ("a rule with no height is a space, not a line across the page",
         lambda: "<hr" not in re.sub(r"(?s)A blank to fill in.*?The next item", "", one)),
        ("an \\input in a comment or verbatim is left alone",
         lambda: "\\input ch1/never" in one
         and "reaches ch1/never" not in log),
        ("alt text holding LaTeX is read as LaTeX, and one over two lines, as Pandoc's "
         "writer wraps it (3.12.1), as one",
         lambda: 'alt="50% shaded"' in one and 'alt="A square over two lines"' in one),
        ("an image named without its extension is found",
         lambda: 'src="img/square.png"' in one),
        ("and, with no alt key, is reported rather than described as \"image\"",
         lambda: "img/square.png" in missing_alt and 'alt="image"' not in one),
        ("an artifact is decorative",
         lambda: re.search(r'<img\s+src="img/rule\.png"[^>]*alt=""', one)
         and 'aria-hidden="true"' in one),
        ("a drawing LaTeX can't make costs only itself",
         lambda: "1 of the book's 2 drawing(s)" in log
         and os.path.exists(os.path.join(work, "rendered", "ch1", "one-1.svg"))
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("a drawing is rendered whole and keeps its figure's caption",
         lambda: re.search(r'<figure[^>]*>\s*(<div class="center">\s*)?'
                           r'<img\s+src="rendered/ch1/one-1\.svg"', one) and "A line" in one
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("a PDF image is made an SVG",
         lambda: 'src="rendered/img/diagram.svg"' in one
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("\\mbox{\\tiny ...} and \\mbox{\\textsf R} reach MathML",
         lambda: all("rotatebox" in line for line in log.splitlines()
                     if "Could not convert TeX math" in line)
         and "noneg" in one and "<math" in one),
        ("the definitions sample lists what's left for a person, not what's defined",
         lambda: "\\weird" in sample_text and "\\renewcommand{\\suchthat}"
         not in sample_text),
        ("\\hspace inside \\mbox, a blank drawn as a rule, and \\raisebox reach MathML",
         lambda: not any(s in line for line in log.splitlines()
                         if "Could not convert TeX math" in line
                         for s in ("and \\hspace", "rule{12pt}", "emptyset"))
         and "<munder>" in one),
        ("lines stacked in \\vtop, as the writer stacks a table cell's, are read as lines",
         lambda: re.search(r"First line\s*<br\s*/?>\s*Second", one) is not None),
        ("a length in mm inside a formula reaches MathML",
         lambda: "10mm" not in one),
        ("the author's tagging header declaration is the table's",
         lambda: re.search(r'<th[^>]*scope="col"[^>]*>Head one', one)),
        ("an overlay drawn on every page isn't a drawing of the text",
         lambda: not os.path.exists(os.path.join(work, "rendered", "book.svg"))
         and not os.path.exists(os.path.join(work, "rendered", "book-1.svg"))),
        ("latex-conversion-macros.tex is read after the preamble: \\suchthat as \\mid",
         lambda: "∣" in one or "&#x2223;" in one or "|</mo>" in one),
        ("a \\ref into another chapter goes to the page the label is on",
         lambda: 'href="one.html#sec:first"' in two
         and 'href="one.html#fig:line"' in two),
        ("with the numbers LaTeX would give",
         lambda: re.search(r'href="one.html#sec:first"[^>]*>1\.1<', two)),
        ("in the EPUB, a \\ref to a chapter's own \\label goes to the chapter",
         lambda: epub_links_resolve(work)),
        ("in AsciiDoc, code beside a formula is unconstrained, so the reader takes both",
         lambda: re.search(r"``\+Let ?\+``latexmath:\[q = 0\]",
                           read(work, "adoc", "one.adoc")
                           if os.path.exists(os.path.join(work, "adoc", "one.adoc")) else "")
         is not None and asciidoc_math_reads_back(work)),
        ("read back from AsciiDoc, a table in a table keeps every cell, formulas in them too",
         lambda: asciidoc_math_reads_back(work)
         and len(re.findall(r"<t[dh]\b", read(work, "html", "one.html"))) ==
         len(re.findall(r"<t[dh]\b", read(work, "adoc-back", "html", "one.html")))),
        ("read back from AsciiDoc, the rules stay in their list items, the lists whole",
         lambda: asciidoc_math_reads_back(work)
         and read(work, "html", "one.html").count("<ol") ==
         read(work, "adoc-back", "html", "one.html").count("<ol")
         and read(work, "html", "one.html").count("<hr") ==
         read(work, "adoc-back", "html", "one.html").count("<hr")),
        ("in AsciiDoc, a formula that ran over a line is on one, where the reader takes it",
         lambda: "latexmath:[p + q]" in (read(work, "adoc", "one.adoc")
                                         if os.path.exists(os.path.join(work, "adoc", "one.adoc")) else "")),
        ("read back from Markdown, every figure is a figure, a centered drawing's too",
         lambda: markdown_reads_back(work)),
        ("in Word, a formula inside a list item stays in the item",
         lambda: word_math_in_list(work)),
        ("read back from Word, a list with a formula, a table, and a rule in its items is whole",
         lambda: word_list_reads_back(work)),
        ("read back from Word, a quotation holding a table is whole, its cells not quotations",
         lambda: word_quote_reads_back(work)),
        ("a figure holding a table is reported as a Word loss",
         lambda: "figure-table" in (read(work, "fidelity.csv")
                                    if os.path.exists(os.path.join(work, "fidelity.csv")) else "")),
        ("the author's files are untouched",
         lambda: fingerprint(work) == before),
    ]


def case_masters(work):
    """Two masters: latex.main decides, and without it the run stops."""
    write_book(work, second_master=True, readme=False)
    stopped = convert(work)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main: workbook.tex\n"
                 "targets:\n  html:\n    format: html\n")
    chosen = convert(work)
    sample = read(work, "latex-conversion-macros-sample.tex") \
        if os.path.exists(os.path.join(work,
                                       "latex-conversion-macros-sample.tex")) else ""
    one = read(work, "html", "one.html") \
        if os.path.exists(os.path.join(work, "html", "one.html")) else ""
    return [
        ("two masters and no latex.main stop the run, naming both",
         lambda: stopped.returncode != 0
         and "book.tex" in stopped.stderr + stopped.stdout
         and "workbook.tex" in stopped.stderr + stopped.stdout
         and "latex.main" in stopped.stderr + stopped.stdout),
        ("with no definitions file, a drawn bar is suggested as \\mid",
         lambda: "\\renewcommand{\\suchthat}{\\mid}" in sample
         and "% \\renewcommand{\\weird}{}" in sample),
        ("latex.main picks the master, and its boolean holds",
         lambda: "SOLUTION TEXT" in one and "EXERCISE TEXT" not in one),
    ]


def case_single(work):
    """A document that \\include-s nothing is one page."""
    os.makedirs(work)
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\begin{document}\n"
                 "\\section*{1.0 Review}\nText.\n\\section*{1.1 Parts}\n"
                 "More.\n\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    page = os.path.join(work, "html", "notes.html")
    return [
        ("a document that includes nothing is one page, its sections in it",
         lambda: os.path.exists(page) and "1.1 Parts" in read(work, "html",
                                                               "notes.html")
         and "one page" in result.stdout + result.stderr),
    ]


def case_unbuilt(work):
    """A file the book's own build makes, not made yet: the run stops."""
    os.makedirs(os.path.join(work, "figures"))
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\begin{document}\nText.\n"
                 "\\input{figures/venn.tex}\n\\end{document}\n")
    with open(os.path.join(work, "figures", "Makefile"), "w") as fh:
        fh.write("all:\n\tfig2dev -L pstex_t venn.fig > venn.tex\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    said = result.stdout + result.stderr
    return [
        ("a file the book's own build makes, missing, stops the run",
         lambda: result.returncode != 0 and "figures/venn.tex" in said
         and "figures/Makefile" in said and "Nothing was converted" in said
         and not os.path.exists(os.path.join(work, "html"))),
    ]


# An author's macros for an image: one the copy can give a key at each
# call, one whose own alt text would win over a key set before it, one
# that calls the first, which the copy doesn't follow, and one whose alt
# text is its optional argument.
IMAGE_MACROS = ("\\newcommand{\\fig}[2]{\\includegraphics[width=#2]{#1}}\n"
                "\\newcommand{\\figkeyed}[1]{\\includegraphics[width=1cm,alt={Fixed}]{#1}}\n"
                "\\newcommand{\\twofigs}[2]{\\fig{#1}{2mm}\\fig{#2}{2mm}}\n"
                "\\newcommand{\\figalt}[2][]{\\includegraphics[alt={#1},width=1cm]{#2}}\n")
FIG2DEV_PAIR = ("\\begin{picture}(0,0)%\n\\includegraphics{figures/f.png}%\n"
                "\\end{picture}%\n\\setlength{\\unitlength}{3947sp}%\n"
                "\\begin{picture}(600,300)(0,0)\n\\put(0,0){label}\n\\end{picture}%\n")


def case_source(work):
    """The source target: alt text from the sidecar written into the
    author's own files, as keys LaTeX's tagging reads."""
    os.makedirs(os.path.join(work, "figures"))
    png(os.path.join(work, "sq.png"), (128, 128, 128))
    png(os.path.join(work, "sq2.png"), (64, 64, 64))
    png(os.path.join(work, "sq3.png"), (32, 32, 32))
    png(os.path.join(work, "sq4.png"), (16, 16, 16))
    png(os.path.join(work, "sq5.png"), (8, 8, 8))
    png(os.path.join(work, "figures", "f.png"), (0, 0, 0))
    with open(os.path.join(work, "figures", "f.fig"), "w") as fh:
        fh.write("#FIG 3.2\n")
    with open(os.path.join(work, "figures", "f.tex"), "w") as fh:
        fh.write(FIG2DEV_PAIR)
    source = ("\\documentclass[pdftex,12pt]{article}\n\\usepackage{graphicx}\n"
              "\\usepackage{amsthm}\n\\usepackage[english]{babel}\n\\pdfcompresslevel=9\n"
              "\\newtheorem{thm}{Theorem}\n\\newtheorem*{thm*}{Theorem}\n"
              "\\newcommand{\\suchthat}{\\; \\rule[-3pt]{.5pt}{13pt} \\;}\n"
              + IMAGE_MACROS +
              "\\begin{document}\n"
              "\\begin{thm*} Unnumbered. \\end{thm*}\n\n"
              "The set $\\{ x \\suchthat x > 0 \\}$.\n\n"
              "\\centerline{\\begin{tabular}{c} a \\\\ \\end{tabular}}\n\n"
              "Inline \\centerline{x} \\newline more.\n\n"
              "\\begin{center}\n\\[ 1! = 1 \\]\net cetera\n\\end{center}\n\n"
              "A square: \\includegraphics[width=1cm]{sq}.\n\n"
              "Behind the book's macro: \\fig{sq2}{1cm}\\fig{sq2}{5mm}.\n\n"
              "Behind one with its own alt text: \\figkeyed{sq3}.\n\n"
              "Behind a macro that calls the macro: \\twofigs{sq4.png}{sq4.png}.\n\n"
              "Behind one whose alt text is an argument: \\figalt[Old alt]{sq5} "
              "and \\figalt{sq5}.\n\n"
              "\\begin{figure}\\fig{sq2}{1cm}\\caption{Small: \\fig{sq2}{2mm}}\\end{figure}\n\n"
              "\\begin{picture}(40,20)\\put(0,0){\\framebox(40,20){two}}\\end{picture}\n\n"
              "A rule: \\includegraphics[height=2pt]{figures/f.png}\n\n"
              "\\begin{figure}\\input{figures/f.tex}\\caption{F}\\end{figure}\n"
              "\\begin{tabular}{cc}\nName & Value \\\\\na & 1 \\\\\nb & 2 \\\\\n\\end{tabular}\n\n"
              "\\begin{tabular}{cc}\nItem & Count \\\\\nx & 3 \\\\\ny & 4 \\\\\n\\end{tabular}\n\n"
              "% \\includegraphics{sq} in a comment\n"
              "\\end{document}\n")
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write(source)
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nsq.png,A gray square: 50% shaded\n"
                 "rendered/notes-1.svg,Two boxes\nfigures/f.png,[decorative]\n"
                 "rendered/figures/f.svg,A figure from xfig\n"
                 "sq2.png,A darker square\nsq3.png,A third square\n"
                 "sq4.png,A fourth square\nsq5.png,A fifth [square]\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  fixed:\n    format: source\n"
                 "  tagged:\n    format: source\n    tagging: \"on\"\n"
                 "  kept:\n    format: source\n    latex_definitions: \"off\"\n"
                 "  plainmath:\n    format: source\n    tagging: \"on\"\n"
                 "    latex_mathml: \"off\"\n")
    with open(os.path.join(work, "latex-conversion-macros.tex"), "w", encoding="utf-8") as fh:
        fh.write("% For reading.\n\\renewcommand{\\suchthat}{\\mid}\n")
    before = fingerprint(work)
    first = convert(work, without_tagging_status(work))
    first_said = first.stdout + first.stderr
    # LaTeX's tagging status data, as the distribution's package has it,
    # beside the book, where kpsewhich looks first: dated before any LaTeX
    # this runs on, amsthm rated currently incompatible, babel unchecked,
    # and graphicx not in it.
    with open(os.path.join(work, "latex-tagging-status.ltx"), "w") as fh:
        fh.write("\\ProvidesFile{latex-tagging-status.ltx}[2020-01-01]\n"
                 "\\@kernel@tagging@status{article}{cls}{4}\n"
                 "\\@kernel@tagging@status{amsthm}{sty}{2}\n"
                 "\\@kernel@tagging@status{babel}{sty}{0}\n")
    # A person's header decision for the table, from the census's row.
    new = os.path.join(work, "table-headers-new.csv")
    rows = list(csv.DictReader(open(new, encoding="utf-8-sig"))) if os.path.exists(new) else []
    with open(os.path.join(work, "table-headers.csv"), "w", encoding="utf-8") as fh:
        fh.write("key,headers\n" + "".join("%s,first-row\n" % r["key"] for r in rows
                                            if "Name" in r.get("preview", "")))
    before = fingerprint(work, skip_dirs=("fixed", "tagged", "kept", "plainmath", "build"))
    result = convert(work)
    said = result.stdout + result.stderr
    fixed = os.path.join(work, "fixed")
    notes = read(work, "fixed", "notes.tex") \
        if os.path.exists(os.path.join(fixed, "notes.tex")) else ""
    pair = read(work, "fixed", "figures", "f.tex") \
        if os.path.exists(os.path.join(fixed, "figures", "f.tex")) else ""

    tagged = read(work, "tagged", "notes.tex") \
        if os.path.exists(os.path.join(work, "tagged", "notes.tex")) else ""

    def build(tree, engine, text=None, passes=1):
        """The author's tree with tree laid over it (and notes.tex as text,
        if given), built with engine, passes times: (exit status, log) of
        the last. A formula's MathML is attached on the pass after the one
        that makes it."""
        build = os.path.join(work, "build-" + os.path.basename(tree) + "-" + engine)
        shutil.copytree(work, build, ignore=shutil.ignore_patterns(
            "fixed", "tagged", "kept", "plainmath", "html", "build*", "rendered"))
        shutil.copytree(tree, build, dirs_exist_ok=True)
        if text is not None:
            with open(os.path.join(build, "notes.tex"), "w", encoding="utf-8") as fh:
                fh.write(text)
        for _ in range(passes):
            done = subprocess.run([engine, "-interaction=nonstopmode", "notes.tex"],
                                  cwd=build, capture_output=True, text=True, timeout=300)
        return done.returncode, done.stdout

    def builds_tagged():
        if not shutil.which("lualatex"):
            return skip("no lualatex to build the tagged copy")
        status, log = build(os.path.join(work, "tagged"), "lualatex", passes=2)
        return status == 0 and "para hooks differ" not in log \
            and "Parent-Child" not in log and "already defined" not in log

    def alt_in_tagged_pdf():
        """The tagged build's figures carry the macro's image's alt text."""
        try:
            import pikepdf
        except ImportError:
            return skip("no pikepdf to read the tagged PDF's structure")
        path = os.path.join(work, "build-tagged-lualatex", "notes.pdf")
        if not os.path.exists(path):
            return False
        alts = []

        def walk(node):
            if isinstance(node, pikepdf.Dictionary):
                if str(node.get("/S", "")) == "/Figure":
                    alts.append(str(node.get("/Alt", "")))
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(path) as pdf:
            walk(pdf.Root.StructTreeRoot)
        return alts.count("A darker square") == 3 and "Fixed" in alts \
            and alts.count("A fifth [square]") == 2

    def mathml_in_tagged_pdf():
        """The tagged build's formula carries its MathML, from unicode-math:
        the set-builder bar the definitions file makes \\mid is U+2223."""
        try:
            import pikepdf
        except ImportError:
            return skip("no pikepdf to read the tagged PDF's structure")
        path = os.path.join(work, "build-tagged-lualatex", "notes.pdf")
        if not os.path.exists(path):
            return False
        found = []

        def walk(node):
            if isinstance(node, pikepdf.Dictionary):
                if str(node.get("/S", "")) == "/Formula" and "/AF" in node:
                    files = node.AF if isinstance(node.AF, pikepdf.Array) else [node.AF]
                    for f in files:
                        if str(f.get("/AFRelationship")) == "/Supplement":
                            found.append(f.EF.F.read_bytes().decode("utf-8"))
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(path) as pdf:
            walk(pdf.Root.StructTreeRoot)
        return any("\u2223" in m and "<math" in m for m in found)

    def figure_in_place():
        """The tagged build's figure is tagged where the text has it, not in
        the container tagging gathers floats into at the document's end."""
        try:
            import pikepdf
        except ImportError:
            return skip("no pikepdf to read the tagged PDF's structure")
        path = os.path.join(work, "build-tagged-lualatex", "notes.pdf")
        if not os.path.exists(path):
            return False
        names = []

        def walk(node):
            if isinstance(node, pikepdf.Dictionary):
                names.append(str(node.get("/S", "")))
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(path) as pdf:
            walk(pdf.Root.StructTreeRoot)
        return "/Figure" in names and "/figures" not in names

    def builds_untagged():
        if not shutil.which("pdflatex"):
            return skip("no pdflatex to build the tagged copy untagged")
        status, _ = build(os.path.join(work, "tagged"), "pdflatex",
                          re.sub(r"\\DocumentMetadata\{[^}]*\}\n", "", tagged))
        return status == 0

    def builds():
        engine = shutil.which("pdflatex")
        if not engine:
            return skip("no pdflatex to build the remediated copy")
        build = os.path.join(work, "build")
        shutil.copytree(work, build, ignore=shutil.ignore_patterns(
            "fixed", "html", "build", "rendered"))
        shutil.copytree(fixed, build, dirs_exist_ok=True)
        done = subprocess.run([engine, "-interaction=nonstopmode", "notes.tex"],
                              cwd=build, capture_output=True, text=True, timeout=120)
        return done.returncode == 0
    return [
        ("an image's alt text joins its own keys, escaped",
         lambda: "\\includegraphics[alt={A gray square: 50\\% shaded},width=1cm]{sq}"
         in notes),
        ("a drawing in the text gets its alt text",
         lambda: "\\begin{picture}[alt={Two boxes}](40,20)" in notes),
        ("decorative is the artifact key",
         lambda: "\\includegraphics[artifact,height=2pt]{figures/f.png}" in notes),
        ("fig2dev's pair: alt text on the first picture, the labels an artifact",
         lambda: pair.startswith("\\begin{picture}[alt={A figure from xfig}](0,0)")
         and "\\begin{picture}[artifact](600,300)" in pair
         and "\\includegraphics{figures/f.png}" in pair),
        ("the read writes out the book's macro for an image, so the page has its file",
         lambda: len(re.findall(r'<img\s+src="sq2\.png"[^>]*alt="A darker square"',
                                read(work, "html", "notes.html"))) == 4
         and "macro for an image written out" in said),
        ("an image behind the book's own macro gets its key at each call, the macro left",
         lambda: "\\setkeys{Gin}{alt={A darker square}}\\fig{sq2}{1cm}\\setkeys{Gin}{alt={}}"
         "\\setkeys{Gin}{alt={A darker square}}\\fig{sq2}{5mm}\\setkeys{Gin}{alt={}}" in notes
         and IMAGE_MACROS in notes and "own macros for an image" in said),
        ("a macro whose alt text is an argument gets it there, braced, given or not",
         lambda: "\\figalt[{A fifth [square]}]{sq5} and \\figalt[{A fifth [square]}]{sq5}."
         in notes),
        ("decisions the copy can't write are named: in a caption, behind a macro "
         "with its own alt text, behind one it doesn't follow",
         lambda: "didn't get it in the copy: sq2, sq3, sq4." in said
         and "\\caption{Small: \\fig{sq2}{2mm}}" in notes
         and "\\figkeyed{sq3}" in notes and "\\twofigs{sq4.png}{sq4.png}" in notes),
        ("a comment is left alone",
         lambda: "% \\includegraphics{sq} in a comment" in notes),
        ("the run says which are in files the book's own build makes",
         lambda: "own build" in said and "writes over them" in said),
        ("the author's files are untouched by the source target",
         lambda: fingerprint(work, skip_dirs=("fixed", "tagged", "kept", "plainmath", "build")) == before),
        ("the remediated copy builds with pdfLaTeX, as the author's does", builds),
        ("tagging: \\DocumentMetadata, the book's language, pdfTeX's option and setting out",
         lambda: tagged.startswith("\\DocumentMetadata{lang=en, pdfstandard=ua-2, tagging=on}\n"
                                   "\\documentclass[12pt]{article}")
         and "\\pdfcompresslevel" not in tagged),
        ("tagging: the starred theorem defined only when tagging hasn't",
         lambda: "\\ifcsname thm*\\endcsname\\else\\newtheorem*{thm*}{Theorem}\\fi" in tagged),
        ("tagging: \\centerline redefined, and \\leavevmode before the formula",
         lambda: "\\renewcommand{\\centerline}" in tagged
         and "\\begin{center}\n\\leavevmode\\[" in tagged),
        ("tagging: a person's header row declared for the table, in a group of its own",
         lambda: "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/header-rows={1}}\\fi"
         "\\begin{tabular}{cc}" in tagged and tagged.count("\\tagpdfsetup{table/") == 1),
        ("untagged, the decision isn't written, and the run says why",
         lambda: "\\tagpdfsetup" not in notes and "need" in said and "tagging" in said),
        ("the definitions file is written after the copy's preamble, as it's read",
         lambda: re.search(r"latex-conversion-macros\.tex, which a person wrote.*\n.*\n"
                           r"% For reading\.\n\\renewcommand\{\\suchthat\}\{\\mid\}\n"
                           r"(?:.*\n)*?\\begin\{document\}", notes) is not None
         and "definition(s) from latex-conversion-macros.tex" in said),
        ("latex_definitions off keeps them to the conversion",
         lambda: os.path.exists(os.path.join(work, "kept", "notes.tex"))
         and "\\mid" not in read(work, "kept", "notes.tex")),
        ("without the tagging status data, the run says how to install it",
         lambda: "tlmgr install latex-tagging-status" in first_said),
        ("with it, the book's packages are named by status, and the list's age",
         lambda: "currently incompatible: amsthm" in said and "unchecked: babel" in said
         and "not in the list: graphicx" in said and "older than the LaTeX it checks" in said),
        ("tagging off leaves the book's build alone",
         lambda: "\\DocumentMetadata" not in notes and "pdftex" in notes),
        ("the tagged copy builds with LuaLaTeX, no tagging error or warning", builds_tagged),
        ("and the image behind the macro has its alt text in the PDF", alt_in_tagged_pdf),
        ("tagging: unicode-math for the formulas' MathML, LuaLaTeX only, with a fallback font",
         lambda: re.search(r"\\ifdefined\\directlua\n  \\usepackage\{unicode-math\}\n"
                           r"(?:.*\n)*?.*RawFeature=\{fallback=textbookimprover\}(?:.*\n)*?"
                           r".*math/setup=\{mathml-SE,mathml-AF\}(?:.*\n)*?\\fi\n", tagged)
         is not None and "unicode-math loaded" in said),
        ("and the tagged PDF's formula carries its MathML", mathml_in_tagged_pdf),
        ("tagging: floats tagged where the text has them, not gathered at the end",
         lambda: "\\keys_if_exist:nnT {__tag/setup} {float/here}\n  {\\tagpdfsetup{float/here}}"
         in tagged
         and "tagged where the text has them" in said),
        ("and the tagged PDF's figure is where the text has it", figure_in_place),
        ("latex_mathml off: tagged, the book's fonts kept, and the run says so",
         lambda: os.path.exists(os.path.join(work, "plainmath", "notes.tex"))
         and "\\DocumentMetadata" in read(work, "plainmath", "notes.tex")
         and "unicode-math" not in read(work, "plainmath", "notes.tex")
         and "latex_mathml is \"off\"" in said),
        ("and without \\DocumentMetadata it builds with pdfLaTeX", builds_untagged),
    ]


def case_own_fonts(work):
    """A tagged copy of a book whose fonts are its own: they're kept, and
    the run says its formulas get no MathML, which unicode-math would."""
    os.makedirs(work)
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\input{fonts}\n\\begin{document}\n"
                 "A formula: $x^2 + 1$.\n\\end{document}\n")
    # In a file the preamble inputs, as GIAM keeps its definitions.
    with open(os.path.join(work, "fonts.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\usepackage{mathptmx}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n")
    result = convert(work)
    said = result.stdout + result.stderr
    copy = os.path.join(work, "tagged", "notes.tex")
    # Fonts set in a style of the book's own, beside it: the same.
    styled = os.path.join(work, "styled")
    os.makedirs(styled)
    with open(os.path.join(styled, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{bookstyle}\n\\begin{document}\n"
                 "A formula: $x^2 + 1$.\n\\end{document}\n")
    with open(os.path.join(styled, "bookstyle.sty"), "w", encoding="utf-8") as fh:
        fh.write("\\ProvidesPackage{bookstyle}\n\\RequirePackage{newtxtext}\n"
                 "\\RequirePackage{newtxmath}\n")
    with open(os.path.join(styled, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n")
    styled_said = convert(styled)
    styled_said = styled_said.stdout + styled_said.stderr
    styled_copy = os.path.join(styled, "tagged", "notes.tex")
    # bm's bold, whose letters TeX's own fonts lack under unicode-math.
    bold = os.path.join(work, "bold")
    os.makedirs(bold)
    with open(os.path.join(bold, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{amsmath}\n\\usepackage{bm}\n"
                 "\\begin{document}\nBold: $\\bm{x} + \\boldsymbol{\\alpha}$, and a poor man's: "
                 "$\\pmb{\\hat{p}_1 - b}$.\n\\end{document}\n")
    with open(os.path.join(bold, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n")
    bold_said = convert(bold)
    bold_said = bold_said.stdout + bold_said.stderr
    bold_copy = os.path.join(bold, "tagged", "notes.tex")

    def bold_builds():
        if not shutil.which("lualatex"):
            return skip("no lualatex to build the copy")
        tree = os.path.join(bold, "build")
        os.makedirs(tree)
        shutil.copy(bold_copy, os.path.join(tree, "notes.tex"))
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "notes.tex"], cwd=tree, capture_output=True, text=True,
                              timeout=300)
        log = read(tree, "notes.log") if os.path.exists(os.path.join(tree, "notes.log")) else ""
        return done.returncode == 0 and "Missing character" not in log
    return [
        ("a book whose fonts are its own keeps them, and the run says its formulas get no MathML",
         lambda: os.path.exists(copy) and "unicode-math" not in read(work, "tagged", "notes.tex")
         and "\\input{fonts}" in read(work, "tagged", "notes.tex")
         and "get no MathML" in said and "with mathptmx" in said),
        ("so does one that sets them in a style file of its own, beside it",
         lambda: os.path.exists(styled_copy)
         and "unicode-math" not in read(styled, "tagged", "notes.tex")
         and "with newtxmath, newtxtext" in styled_said),
        ("bm's, \\boldsymbol's, and \\pmb's bold is unicode-math's bold italic, and the copy "
         "builds with no glyph missing",
         lambda: os.path.exists(bold_copy)
         and "\\renewcommand{\\bm}[1]{\\symbfit{#1}}" in read(bold, "tagged", "notes.tex")
         and "\\renewcommand{\\boldsymbol}[1]{\\symbfit{#1}}" in read(bold, "tagged", "notes.tex")
         and "\\renewcommand{\\pmb}[1]{\\symbfit{#1}}" in read(bold, "tagged", "notes.tex")
         and "bold italic" in bold_said and bold_builds()),
    ]


BOOK_MASTER = ("\\documentclass{book}\n\\usepackage{graphicx}\n\\usepackage{amsmath,amssymb}\n"
               "\\usepackage{makeidx}\n\\makeindex\n\\title{A Small Book}\n\\author{An Author}\n"
               "\\begin{document}\n\\maketitle\n\\include{one}\n\\printindex\n\\end{document}\n")
BOOK_CHAPTER = ("\\chapter{One}\nSome text about sets\\index{sets}, where "
                "$\\mathbb{N} \\subseteq \\mathbb{Z}$ and $x \\neq y$.\n"
                "\\begin{figure}[t]\\centering\\includegraphics[width=2cm]{sq}"
                "\\caption{A square}\\label{fig:sq}\\end{figure}\n"
                "After the figure in the source, Figure~\\ref{fig:sq}.\n\n"
                "\\begin{tabular}{cc}\nName & Value \\\\\na & 1 \\\\\nb & 2 \\\\\n"
                "\\end{tabular}\n\n"
                "\\[ \\sum_{i=1}^n i = \\frac{n(n+1)}{2} \\]\n\n"
                "A drawing with no description: "
                "\\begin{picture}(20,10)\\put(0,0){x}\\end{picture}\n")


def case_book_pdf(work):
    """A LaTeX book's PDF, built from the book's own LaTeX (pdf.from: book):
    its index, which the pages don't have, its figure's alt text from the
    sidecar, its formulas' MathML, and its figure tagged in place; built
    from the pages instead with pdf.from: pages; and a book that won't
    build with tagging stops the run with LaTeX's error and the way out."""
    if not shutil.which("lualatex") or not shutil.which("latexmk"):
        return [("a LaTeX book's PDF is built from its own LaTeX",
                 lambda: skip("no lualatex or latexmk for the PDF target"))]
    books = {}
    for name, extra, targets in (
            ("book", "", "  pdf:\n    format: pdf\n"),
            ("pages", "", "  pdf:\n    format: pdf\n    pdf:\n      from: pages\n"),
            # Builds with pdfLaTeX, as the conversion reads it, and stops
            # with LuaLaTeX, as the PDF target builds it.
            ("broken", "\\ifdefined\\directlua\\TIQundefined\\fi\n", "  pdf:\n    format: pdf\n")):
        book = os.path.join(work, name)
        os.makedirs(book)
        png(os.path.join(book, "sq.png"), (128, 128, 128))
        with open(os.path.join(book, "book.tex"), "w", encoding="utf-8") as fh:
            fh.write(BOOK_MASTER.replace("\\begin{document}", extra + "\\begin{document}"))
        with open(os.path.join(book, "one.tex"), "w", encoding="utf-8") as fh:
            fh.write(BOOK_CHAPTER)
        with open(os.path.join(book, "image-alt.csv"), "w", encoding="utf-8") as fh:
            fh.write("Image,Alt\nsq.png,A gray square\n")
        with open(os.path.join(book, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n" + targets)
        result = convert(book)
        books[name] = (book, result.returncode, result.stdout + result.stderr)

    def text(name):
        path = os.path.join(books[name][0], "pdf", "book.pdf")
        if not os.path.exists(path) or not shutil.which("pdftotext"):
            return None
        return subprocess.run(["pdftotext", path, "-"], capture_output=True,
                              text=True).stdout

    def structure():
        """(figure alt texts, formula MathML count, gathered-float containers,
        header cells)."""
        import pikepdf
        alts, mathml, containers, heads = [], 0, 0, 0
        path = os.path.join(books["book"][0], "pdf", "book.pdf")

        def walk(node):
            nonlocal mathml, containers, heads
            if isinstance(node, pikepdf.Dictionary):
                kind = str(node.get("/S", ""))
                heads += kind == "/TH"
                if kind == "/Figure":
                    alts.append(str(node.get("/Alt", "")))
                if kind in ("/figures", "/tables"):
                    containers += 1
                if kind == "/Formula" and "/AF" in node:
                    files = node.AF if isinstance(node.AF, pikepdf.Array) else [node.AF]
                    mathml += any(str(f.get("/AFRelationship")) == "/Supplement" for f in files)
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(path) as pdf:
            walk(pdf.Root.StructTreeRoot)
        return alts, mathml, containers, heads

    def built_from_book():
        found = text("book")
        if found is None:
            return skip("no pdftotext to read the PDF")
        return "built by LaTeX from the book's own files" in books["book"][2] \
            and "Index" in found and "sets, " in found

    def tagged_from_book():
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return skip("no pikepdf to read the PDF's structure")
        alts, mathml, containers, heads = structure()
        return alts[:1] == ["A gray square"] and mathml >= 3 and containers == 0 and heads >= 2

    def placeholder_reported():
        """The drawing with no description has LaTeX's placeholder, which a
        validator accepts and the output check reports."""
        report = os.path.join(books["book"][0], "output-check.csv")
        if not os.path.exists(report):
            return False
        with open(report, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        return any(len(r) > 2 and r[1] == "pdf-figure-alt-is-placeholder"
                   and r[2] == "picture environment" for r in rows)

    def passes_ua2():
        verapdf = os.environ.get("VERAPDF") or shutil.which("verapdf")
        if not verapdf:
            return skip("no veraPDF to check the PDF")
        done = subprocess.run([verapdf, "-f", "ua2", "--format", "text",
                               os.path.join(books["book"][0], "pdf", "book.pdf")],
                              capture_output=True, text=True)
        return done.stdout.strip().startswith("PASS")

    def built_from_pages():
        found = text("pages")
        if found is None:
            return skip("no pdftotext to read the PDF")
        return books["pages"][1] == 0 and "built by LaTeX from the book's own files" \
            not in books["pages"][2] and "sets" in found and "Index" not in found
    return [
        ("a LaTeX book's PDF is built from its own LaTeX: its index is there", built_from_book),
        ("its figure has the sidecar's alt text, its formulas MathML, its figure in place, "
         "its table the census's header row",
         tagged_from_book),
        ("and it passes veraPDF's PDF/UA-2 profile", passes_ua2),
        ("the output check reports LaTeX's placeholder alt text for a drawing with none",
         placeholder_reported),
        ("pdf.from: pages builds it from the pages, which have no index", built_from_pages),
        ("a book that won't build with tagging stops the run, with LaTeX's error and the way out",
         lambda: books["broken"][1] != 0 and "TIQundefined" in books["broken"][2]
         and "wasn't built" in books["broken"][2] and "pdf.from: pages" in books["broken"][2]),
    ]


def case_pdf_copy(work):
    """The PDF target's copy of the book's folder: a link the book makes
    to a folder beside it still finds it, the book's .latexmkrc is kept
    and doesn't move the PDF, and what LaTeX couldn't resolve is named."""
    if not shutil.which("lualatex") or not shutil.which("latexmk"):
        return [("the PDF build's copy of the book keeps its links and .latexmkrc",
                 lambda: skip("no lualatex or latexmk for the PDF target"))]
    book = os.path.join(work, "book")
    os.makedirs(os.path.join(work, "shared", "figs"))
    os.makedirs(book)
    png(os.path.join(work, "shared", "figs", "a.png"), (0, 0, 128))
    os.symlink(os.path.join("..", "shared", "figs"), os.path.join(book, "figs"))
    # A package of the book's own in a folder its .latexmkrc adds to
    # TEXINPUTS, so the book builds only with its .latexmkrc.
    os.makedirs(os.path.join(book, "tex"))
    with open(os.path.join(book, "tex", "notestyle.sty"), "w") as fh:
        fh.write("\\ProvidesPackage{notestyle}\n\\newcommand{\\notemark}{FROM THE STYLE}\n")
    with open(os.path.join(book, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{graphicx}\n\\usepackage{notestyle}\n"
                 "\\title{Notes}\n\\begin{document}\n\\notemark. A linked figure: "
                 "\\includegraphics[width=1cm]{figs/a}.\n"
                 "See \\ref{nope} and \\cite{nobody}.\n\\end{document}\n")
    with open(os.path.join(book, ".latexmkrc"), "w") as fh:
        fh.write("$out_dir = 'elsewhere';\n$pdf_mode = 1;\nensure_path('TEXINPUTS', './tex//');\n")
    with open(os.path.join(book, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nfigs/a.png,A blue square\n")
    with open(os.path.join(book, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  pdf:\n    format: pdf\n")
    result = convert(book)
    said = result.stdout + result.stderr
    pdf = os.path.join(book, "pdf", "book.pdf")

    def figure():
        try:
            import pikepdf
        except ImportError:
            return skip("no pikepdf to read the PDF")
        if not os.path.exists(pdf):
            return False
        alts = []

        def walk(node):
            if isinstance(node, pikepdf.Dictionary):
                if str(node.get("/S", "")) == "/Figure":
                    alts.append(str(node.get("/Alt", "")))
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(pdf) as doc:
            walk(doc.Root.StructTreeRoot)
        return alts == ["A blue square"]
    return [
        ("the book's .latexmkrc is kept, and the PDF is built where it's looked for, "
         "whatever that says",
         lambda: result.returncode == 0 and os.path.exists(pdf)
         and (not shutil.which("pdftotext") or "FROM THE STYLE" in subprocess.run(
             ["pdftotext", pdf, "-"], capture_output=True, text=True).stdout)),
        ("a link the book makes to a folder beside it finds it from the copy",
         figure),
        ("what LaTeX couldn't resolve is named",
         lambda: "couldn't resolve 1 reference(s) and 1 citation(s)" in said
         and "nope" in said and "cited nobody" in said),
    ]


def case_other_masters(work):
    """The book's other masters go into the copy too: each with the files
    only it reaches, and, tagged, made to build with LuaLaTeX: luatex85
    loaded, so an old test for pdfTeX (\\ifx\\pdfoutput\\undefined, which
    LuaTeX doesn't define) takes it for pdfTeX, and the pdfTeX commands in
    that branch (\\ifnum\\pdfoutput, \\pdfinfo) work."""
    os.makedirs(work)
    png(os.path.join(work, "sq.png"), (128, 128, 128))
    png(os.path.join(work, "sq2.png"), (64, 64, 64))
    files = {
        "book.tex": "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n"
                    "\\input{shared}\n\\end{document}\n",
        "workbook.tex": "\\newif\\ifpdf\n\\ifx\\pdfoutput\\undefined\\pdffalse\\else\n"
                        "  \\ifnum\\pdfoutput>0 \\pdftrue\\else\\pdffalse\\fi\n\\fi\n"
                        "\\ifx\\pdfoutput\\undefined % not pdfTeX\n"
                        "\\documentclass[dvips]{article}\n\\else\n"
                        "\\documentclass[pdftex]{article}\n\\pdfinfo{/Author (Someone)}\n"
                        "\\fi\n\\usepackage{graphicx}\n"
                        "\\begin{document}\n\\ifpdf PDF MODE\\else DVI MODE\\fi\n"
                        "\\input{shared}\n\\input{only}\n\\end{document}\n",
        "shared.tex": "Shared text: \\includegraphics[width=1cm]{sq}\n",
        "only.tex": "Only the workbook's: \\includegraphics[width=1cm]{sq2}\n",
        "image-alt.csv": "Image,Alt\nsq.png,A square\nsq2.png,Another square\n",
        "conversion.yaml": "defaults:\n  latex:\n    main: book.tex\n"
                           "targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n",
    }
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    # Executable, as many of GIAM's files are: the copy keeps the mode.
    os.chmod(os.path.join(work, "only.tex"), 0o755)
    result = convert(work)
    said = result.stdout + result.stderr
    tagged = os.path.join(work, "tagged")

    def copied(name):
        path = os.path.join(tagged, name)
        return read(work, "tagged", name) if os.path.exists(path) else ""

    def build(engine, metadata=True):
        """The tree with the copy laid over it, the workbook built with engine."""
        tree = os.path.join(work, "build-" + engine)
        shutil.copytree(work, tree, ignore=shutil.ignore_patterns("tagged", "build-*"))
        shutil.copytree(tagged, tree, dirs_exist_ok=True)
        if not metadata:
            path = os.path.join(tree, "workbook.tex")
            text = read(tree, "workbook.tex")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(re.sub(r"\\DocumentMetadata\{[^}]*\}\n", "", text))
        done = subprocess.run([engine, "-interaction=nonstopmode", "workbook.tex"],
                              cwd=tree, capture_output=True, text=True, timeout=300)
        return done.returncode, os.path.join(tree, "workbook.pdf")

    def builds_tagged():
        if not shutil.which("lualatex"):
            return skip("no lualatex to build the workbook")
        status, pdf = build("lualatex")
        if status != 0 or not os.path.exists(pdf):
            return False
        try:
            import pikepdf
        except ImportError:
            return skip("no pikepdf to read the workbook's structure")
        alts = []

        def walk(node):
            if isinstance(node, pikepdf.Dictionary):
                if str(node.get("/S", "")) == "/Figure":
                    alts.append(str(node.get("/Alt", "")))
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(pdf) as doc:
            walk(doc.Root.StructTreeRoot)
            author = str(doc.docinfo.get("/Author", ""))
        text = subprocess.run(["pdftotext", pdf, "-"], capture_output=True,
                              text=True).stdout if shutil.which("pdftotext") else "PDF MODE"
        return alts == ["A square", "Another square"] and "PDF MODE" in text \
            and author == "Someone"

    def builds_untagged():
        if not shutil.which("pdflatex"):
            return skip("no pdflatex to build the workbook untagged")
        status, pdf = build("pdflatex", metadata=False)
        return status == 0 and os.path.exists(pdf)
    return [
        ("the other master and the file only it reaches are in the copy, with alt text",
         lambda: copied("workbook.tex") != "" and "alt={Another square}" in copied("only.tex")
         and "workbook.tex with 1 file(s) only it reaches" in said),
        ("a file written into the copy keeps the author's mode",
         lambda: os.path.exists(os.path.join(tagged, "only.tex"))
         and os.stat(os.path.join(tagged, "only.tex")).st_mode & 0o777 == 0o755
         and os.stat(os.path.join(tagged, "shared.tex")).st_mode & 0o777
         == os.stat(os.path.join(work, "shared.tex")).st_mode & 0o777),
        ("tagged, the other master gets \\DocumentMetadata first, then luatex85 for its "
         "pdfTeX test, which is left as it was",
         lambda: copied("workbook.tex").startswith("\\DocumentMetadata{")
         and 0 < copied("workbook.tex").find("\\ifdefined\\directlua\\RequirePackage{luatex85}\\fi")
         < copied("workbook.tex").find("\\newif\\ifpdf")
         and copied("workbook.tex").count("\\ifx\\pdfoutput\\undefined") == 2),
        ("it builds with LuaLaTeX, tagged, its figures with their alt text, the pdfTeX "
         "branch taken and its \\pdfinfo written", builds_tagged),
        ("and without \\DocumentMetadata it builds with pdfLaTeX", builds_untagged),
    ]


# Calls of the book's macros for an image, as a review found them going
# wrong: a body holding \caption, whose label a group around the call
# undid, and one holding \centering, whose paragraph it undid; alt=#3 bare,
# which a comma in the text ended; a call whose own keys hold alt, which
# won over one set before it; an alt argument the body also uses as the
# caption; a call in \captionof's caption, which LaTeX writes to a file.
REVIEW_MACROS = r"""\DocumentMetadata{lang=en, pdfstandard=ua-2, tagging=on}
\documentclass{article}
\usepackage{graphicx}
\usepackage{caption}
\newcommand{\fig}[2]{\includegraphics[width=#2]{#1}}
\newcommand{\figa}[3]{\includegraphics[width=#2,alt=#3]{#1}}
\newcommand{\figc}[2]{\includegraphics[width=2cm]{#1}\caption{#2}}
\newcommand{\figd}[1]{\centering\includegraphics[width=2cm]{#1}}
\newcommand{\figo}[2][]{\includegraphics[#1]{#2}}
\newcommand{\figcap}[2]{\includegraphics[width=1cm,alt={#2}]{#1}\caption{#2}}
\newcommand{\figk}[2][alt={Default text}]{\includegraphics[#1]{#2}}
\newcommand{\figw}[2][width=1cm]{\includegraphics[#1]{#2}}
\title{Macros}
\begin{document}
\section{One}
\section{Two}
\fig{sq}{2cm}

\figa{circ}{2cm}{Old alt}

\figo[width=2cm,alt={Old keys}]{tri}

\figo{bare} \figk{key} \figw{wide}

\begin{figure}[h]
\figc{star}{A star}\label{fig:star}
\end{figure}
See Figure~\ref{fig:star}.

\begin{figure}[h]
\figd{dot}
\caption{Centered}
\end{figure}

\begin{figure}[h]
\figcap{mark}{The caption}
\end{figure}

\begin{minipage}{\linewidth}
\captionof{figure}{An icon \fig{icon}{1em} inline}
\end{minipage}

\includegraphics[width=1cm]{plain}
\end{document}
"""


def case_review_macros(work):
    """Calls of the book's macros for an image, each written so the call
    does what it did: no group around it, a bare alt argument braced, a
    call's own keys holding the description, and what can't be written
    without changing something else named."""
    os.makedirs(work)
    for name, rgb in (("sq", (128, 0, 0)), ("circ", (0, 0, 128)), ("tri", (0, 128, 0)),
                      ("star", (128, 128, 0)), ("dot", (0, 0, 0)), ("mark", (64, 64, 64)),
                      ("icon", (32, 32, 32)), ("plain", (200, 200, 200)),
                      ("bare", (16, 16, 16)), ("key", (48, 48, 48)), ("wide", (96, 96, 96))):
        png(os.path.join(work, name + ".png"), rgb)
    with open(os.path.join(work, "book.tex"), "w", encoding="utf-8") as fh:
        fh.write(REVIEW_MACROS)
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nsq.png,\"A square, red\"\ncirc.png,\"A circle, blue\"\n"
                 "tri.png,A triangle from the sidecar\nstar.png,A star\n"
                 "dot.png,A centered dot\nmark.png,A mark\nicon.png,An icon\n"
                 "bare.png,A bare one\nkey.png,A key\nwide.png,A wide one\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n")
    result = convert(work)
    said = result.stdout + result.stderr
    path = os.path.join(work, "tagged", "book.tex")
    copy = read(work, "tagged", "book.tex") if os.path.exists(path) else ""

    def built():
        """(figures' alt texts in order, the text) of the copy built with
        LuaLaTeX, tagged, or None."""
        if not shutil.which("lualatex"):
            return None
        tree = os.path.join(work, "build")
        shutil.copytree(work, tree, ignore=shutil.ignore_patterns("tagged", "build"))
        shutil.copy(path, os.path.join(tree, "book.tex"))
        for _ in range(2):
            done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                                   "book.tex"], cwd=tree, capture_output=True, text=True,
                                  timeout=300)
        if done.returncode != 0:
            return [], ""
        import pikepdf
        alts = []

        def walk(node):
            if isinstance(node, pikepdf.Dictionary):
                if str(node.get("/S", "")) == "/Figure":
                    alts.append(str(node.get("/Alt", "")))
                kids = node.get("/K")
                if kids is not None:
                    for kid in (kids if isinstance(kids, pikepdf.Array) else [kids]):
                        walk(kid)
        with pikepdf.open(os.path.join(tree, "book.pdf")) as doc:
            walk(doc.Root.StructTreeRoot)
        text = subprocess.run(["pdftotext", os.path.join(tree, "book.pdf"), "-"],
                              capture_output=True, text=True).stdout \
            if shutil.which("pdftotext") else "See Figure 1."
        return alts, text
    found = {}

    def build():
        if "result" not in found:
            found["result"] = built()
        return found["result"]

    def as_built(check):
        def run():
            result = build()
            if result is None:
                return skip("no lualatex to build the copy")
            return check(*result)
        return run
    return [
        ("a call gets its key before it and alt={} after it, no group around it, so a "
         "\\caption's label and a \\centering keep",
         lambda: "\\setkeys{Gin}{alt={A star}}\\figc{star}{A star}\\setkeys{Gin}{alt={}}"
         "\\label{fig:star}" in copy
         and "\\setkeys{Gin}{alt={A centered dot}}\\figd{dot}\\setkeys{Gin}{alt={}}" in copy
         and "{\\setkeys" not in copy),
        ("a bare alt=#3 argument is braced, so its comma stays in the text",
         lambda: "\\figa{circ}{2cm}{{A circle, blue}}" in copy),
        ("a call whose own keys hold alt gets the description among them",
         lambda: "\\figo[alt={A triangle from the sidecar},width=2cm]{tri}" in copy),
        ("a call without its keys gets them when the default is empty or has alt "
         "text of its own, and a key before it otherwise",
         lambda: "\\figo[alt={A bare one}]{bare}" in copy
         and "\\figk[alt={A key}]{key}" in copy
         and "\\setkeys{Gin}{alt={A wide one}}\\figw{wide}\\setkeys{Gin}{alt={}}" in copy),
        ("an alt argument the body also uses as the caption, and a call in \\captionof's "
         "caption, are named, not written",
         lambda: "\\figcap{mark}{The caption}" in copy
         and "\\captionof{figure}{An icon \\fig{icon}{1em} inline}" in copy
         and re.search(r"didn't get it in the copy: icon, mark\.", said)),
        ("built tagged, each figure has its own description, the label its figure's "
         "number, and the image after them none of theirs",
         as_built(lambda alts, text: "See Figure 1." in text
                  and alts[:3] == ["A square, red", "A circle, blue", "A triangle from the sidecar"]
                  and "A star" in alts and "A centered dot" in alts
                  and all(a in alts for a in ("A bare one", "A key", "A wide one"))
                  and "Default text" not in alts and "plain.png" in alts)),
    ]


def case_latex_target(work):
    """The latex target: a Markdown book written as LaTeX, a master and a
    file per chapter, read back as a LaTeX source to the same pages."""
    os.makedirs(os.path.join(work, "img"))
    png(os.path.join(work, "img", "square.png"), (90, 90, 90))
    png(os.path.join(work, "img", "a+b.png"), (30, 30, 30))
    with open(os.path.join(work, "img", "circle.svg"), "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                 '<circle cx="20" cy="20" r="15" fill="black"/></svg>\n')
    with open(os.path.join(work, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("# Shapes\n\nA square:\n\n![A gray square.](img/square.png)\n\n"
                 "The area is $s^2$, and the next chapter has [circles](two.md#circles).\n\n"
                 "| Shape | Sides |\n|---|---|\n| Square | 4 |\n| Triangle | 3 |\n")
    with open(os.path.join(work, "two.md"), "w", encoding="utf-8") as fh:
        fh.write("# Circles {#circles}\n\n![A black circle.](img/circle.svg)\n\n"
                 "Its area is $\\pi r^2$.\n\n1. Draw it.\n2. Measure it.\n\n"
                 "So $$A = \\pi r^2.$$\\\nQ.E.D.\n\n"
                 "**Theorem.** *$$C = 2 \\pi r$$*\n\nCompare [[compare]](#circles).\n\n"
                 "A sum: ![A plus.](img/a+b.png)\n\n"
                 "*A rule for $x$ with a note[^euler] and more.*\n\n"
                 "[^euler]: *Euler's $f(x)$.*\n\n"
                 "<table><tbody><tr><td><p>Outer</p><p>cell</p></td><td><table><thead><tr>"
                 "<th>Rule</th></tr></thead><tbody><tr><td>x</td></tr></tbody><tbody><tr>"
                 "<td>zeta</td></tr></tbody></table></td></tr></tbody></table>\n\n"
                 "<table><caption>Two statements</caption>"
                 "<thead><tr><th>Statement</th><th>Truth table</th></tr></thead>"
                 "<tbody><tr><td>A and B</td><td><table><thead><tr><th>A</th><th>B</th>"
                 "<th>A and B</th></tr></thead><tbody><tr><td>T</td><td>T</td><td>T</td>"
                 "</tr><tr><td>T</td><td>F</td><td>F</td></tr></tbody></table></td></tr>"
                 "</tbody></table>\n\n"
                 "<table><thead><tr><th>Name</th><th colspan=\"2\">Values</th></tr></thead>"
                 "<tbody><tr><td>a</td><td>1</td><td>2</td></tr></tbody></table>\n\n"
                 "<table><thead><tr><th>Proof: first,<br>then second.<br>Q.E.D.</th></tr>"
                 "</thead></table>\n")
    with open(os.path.join(work, "three.md"), "w", encoding="utf-8") as fh:
        fh.write("# Figures\n\nSee [the triangle](#pascal).\n\n"
                 "<figure id=\"pascal\"><table><tbody><tr><td>1</td></tr><tr><td>1</td>"
                 "<td>1</td></tr></tbody></table><figcaption>The first rows of Pascal's "
                 "triangle</figcaption></figure>\n\n<figure id=\"outer\"><figure>"
                 "<img src=\"img/square.png\" alt=\"A flowchart.\"></figure>"
                 "<figcaption>A small example</figcaption></figure>\n")
    with open(os.path.join(work, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: shapes\n  title: Shapes\n  language: en\n"
                 "  contents:\n  - one\n  - two\n  - three\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  latex:\n    format: latex\n"
                 "  adoc:\n    format: asciidoc\n")
    result = convert(work)
    said = result.stdout + result.stderr
    out = os.path.join(work, "latex")
    master = read(work, "latex", "shapes.tex") \
        if os.path.exists(os.path.join(out, "shapes.tex")) else ""
    one = read(work, "latex", "one.tex") if os.path.exists(os.path.join(out, "one.tex")) else ""
    two = read(work, "latex", "two.tex") if os.path.exists(os.path.join(out, "two.tex")) else ""
    three = read(work, "latex", "three.tex") \
        if os.path.exists(os.path.join(out, "three.tex")) else ""

    def round_trip():
        back = os.path.join(work, "back")
        shutil.copytree(out, back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("defaults:\n  latex:\n    main: shapes.tex\n"
                     "targets:\n  html:\n    format: html\n")
        convert(back)
        compare = os.path.join(HERE, "..", "util", "compare-output.py")
        same = []
        for stem in ("one", "two"):
            a, b = os.path.join(work, "cmp-a-" + stem), os.path.join(work, "cmp-b-" + stem)
            os.makedirs(a)
            os.makedirs(b)
            shutil.copy(os.path.join(work, "html", stem + ".html"), a)
            if not os.path.exists(os.path.join(back, "html", stem + ".html")):
                return False
            shutil.copy(os.path.join(back, "html", stem + ".html"), b)
            done = subprocess.run([sys.executable, compare, a, b],
                                  capture_output=True, text=True)
            same.append("1 identical" in done.stdout)
        return all(same)

    def builds():
        engine = shutil.which("latexmk")
        if not engine or not shutil.which("lualatex"):
            return skip("no latexmk and lualatex to build the latex target")
        done = subprocess.run([engine, "-lualatex", "-interaction=nonstopmode",
                               "shapes.tex"], cwd=out, capture_output=True,
                              text=True, timeout=600)
        return done.returncode == 0 and os.path.exists(os.path.join(out, "shapes.pdf"))
    return [
        ("the master starts with \\DocumentMetadata and \\include-s each chapter",
         lambda: master.startswith("\\DocumentMetadata")
         and "\\include{one}" in master and "\\include{two}" in master
         and master.index("\\include{one}") < master.index("\\include{two}")),
        ("each chapter is a file of its own, the master's division commands not in it",
         lambda: "Shapes" in one and "Circles" in two and "\\mainmatter" not in one
         and "\\begin{document}" not in one + two),
        ("the images are beside them, the SVG made PDF, each with its alt text",
         lambda: os.path.exists(os.path.join(out, "img", "square.png"))
         and os.path.exists(os.path.join(out, "img", "circle.pdf"))
         and re.search(r"alt=\{A\s+gray\s+square\.\}", one)
         and re.search(r"alt=\{A\s+black\s+circle\.\}", two)
         and "includesvg" not in two),
        ("the run says what it wrote", lambda: "shapes.tex and 3 file(s)" in said),
        ("in AsciiDoc, italics close before a footnote, whose own italics then can't end them",
         lambda: re.search(r"__footnote:\[__Euler", read(work, "adoc", "two.adoc")
                           if os.path.exists(os.path.join(work, "adoc", "two.adoc")) else "")
         is not None),
        ("in AsciiDoc, a + in an image's name is percent-encoded, which the reader takes",
         lambda: "image:img/a%2Bb.png[" in (read(work, "adoc", "two.adoc")
                                            if os.path.exists(os.path.join(work, "adoc", "two.adoc")) else "")),
        ("in AsciiDoc, a bracket in a link's text is a character reference the reader takes",
         lambda: "[&#91;compare&#93;]" in (read(work, "adoc", "two.adoc")
                                           if os.path.exists(os.path.join(work, "adoc", "two.adoc")) else "")),
        ("in AsciiDoc, a table written as HTML inside another keeps its cells",
         lambda: "<td>zeta</td>" in (read(work, "adoc", "two.adoc")
                                     if os.path.exists(os.path.join(work, "adoc", "two.adoc")) else "")),
        ("a figure holding only a table: its caption is the table's, not lost",
         lambda: "\\caption{The first rows of Pascal" in three
         and three.count("\\begin{longtable}") == 1),
        ("in AsciiDoc, a figure holding only a table gives the table its caption and id",
         lambda: re.search(r"\[\[pascal\]\]\n\.The first rows of Pascal",
                           read(work, "adoc", "three.adoc")
                           if os.path.exists(os.path.join(work, "adoc", "three.adoc")) else "")
         is not None and "adoc,three,figure-table," in (read(work, "fidelity.csv")
                         if os.path.exists(os.path.join(work, "fidelity.csv")) else "")),
        ("a figure in a figure: one figure, one caption",
         lambda: three.count("\\begin{figure}") == 1
         and three.count("\\caption{A small example}") == 1 and "\\caption{}" not in three),
        ("a head cell's lines are broken in a minipage, as the writer breaks them",
         lambda: "\\begin{minipage}[b]{\\linewidth}\\raggedright\nProof: first,\\\\\n" in two),
        ("the writer's \\multicolumn at a table's edge is there to read back",
         lambda: re.search(r"\\multicolumn\{2\}\{[^}]*@\{\}\}", two) is not None),
        ("a display formula comes out of the emphasis around it, which tagging can't take",
         lambda: "C = 2 \\pi r" in two and "\\emph{\\[" not in two),
        ("a table in a table's cell is a tabular, its head declared for tagging and ruled off",
         lambda: "{\\tagpdfsetup{table/header-rows={1}}\\begin{tabular}[t]{" in two
         and "A & B & A and B \\\\\n\\hline\n" in two and "T & F & F \\\\" in two),
        ("what the PDF target's filter writes is there too: a link's /Contents",
         lambda: "\\OERLinkContents{" in one and "\\OERLinkContents" in master),
        ("read back as a LaTeX source, each chapter gives the same page", round_trip),
        ("it builds with latexmk and LuaLaTeX", builds),
    ]


# A course's notes, a document per topic, each built on its own (FINC 308's
# layout): a title set as large type under the course's name, a table whose
# column type the document defines, a box (a table of one paragraph column)
# holding a display formula, an answer key of \ref-s to enumerated items,
# enumitem's leftmargin=*, an unused titlesec, and an \appendix before its
# last section. A binder gathers the topics' PDFs with \includepdf.
TOPIC_A = r"""\documentclass[11pt]{article}
\usepackage{amsmath}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage{booktabs}
\usepackage{array}
\newcolumntype{R}[1]{>{\raggedleft\arraybackslash}p{#1}}
\begin{document}
\begin{center}
    {\large \textrm{COURSE 101: Testing}}

    \vspace{0.3cm}
    {\LARGE \textrm{Topic A: The First Topic}}
\end{center}

Opening words.

\section*{Learning Objectives}
\begin{itemize}[leftmargin=*]
    \item Learn the first thing
\end{itemize}

\section{Balances}
\begin{center}
\begin{tabular}{p{2in}R{1in}}
\toprule
\textbf{Item} & \textbf{Amount}\\
\midrule
Cash & \$5\\
Loans & \$2\\
\bottomrule
\end{tabular}
\end{center}

\begin{center}
\begin{tabular}{p{4in}}
\toprule
\multicolumn{1}{c}{\textbf{Example: A Boxed Passage}}\\

A box is a frame around a passage of prose that runs on for a sentence or two.

\[
x = 1 + 2
\]
And the passage closes here.\\
\bottomrule
\end{tabular}
\end{center}

\section{Practice Questions}
\begin{enumerate}[leftmargin=18pt]
    \item Which comes first?
    \begin{enumerate}
        \item The second
        \item\label{QA1} The first
    \end{enumerate}
\end{enumerate}

\section{Answer Key}
\ref{QA1}

\appendix
\section{More Practice}
Extra work.
\end{document}
"""
TOPIC_B = r"""\documentclass[11pt]{article}
\usepackage{graphicx}
\begin{document}
\begin{center}
    {\large COURSE 101: Testing}

    {\LARGE Topic B: The Second Topic}
\end{center}

\section{Only}
Second words.
\input{shared/note}

\includegraphics[width=1cm]{img/dot}
\end{document}
"""
BINDER = r"""\documentclass{article}
\usepackage{pdfpages}
\begin{document}
\tableofcontents
\section{Topic A}
\includepdf[pages=-]{Topic A One/Topic A One.pdf}
\section{Topic B}
\includepdf[pages=-]{Topic B Two/Topic B Two.pdf}
\section{Topic C}
\includepdf[pages=-]{Topic C Three/Topic C Three.pdf}
\end{document}
"""


def case_documents(work):
    """A book of documents each built on its own: a binder that only
    gathers their PDFs stops the run, naming them; latex.main lists them,
    each a page in the order given, its large-type title the page's; the
    copy writes each, made to build with tagging; the PDF target builds a
    PDF of each."""
    os.makedirs(os.path.join(work, "src"))
    # Topic B reaches a file and an image from its own folder, src/, as its
    # author builds it there.
    os.makedirs(os.path.join(work, "src", "shared"))
    os.makedirs(os.path.join(work, "src", "img"))
    png(os.path.join(work, "src", "img", "dot.png"), (0, 0, 0))
    for name, text in (("src/Topic A One.tex", TOPIC_A), ("src/Topic B Two.tex", TOPIC_B),
                       ("src/shared/note.tex", "A NOTE FROM ITS FOLDER.\n"),
                       ("Combined.tex", BINDER)):
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nsrc/img/dot.png,A black dot\n")
    with open(os.path.join(work, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.course\n  title: Course 101\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    stopped = convert(work)
    told = stopped.stdout + stopped.stderr
    pdf = bool(shutil.which("lualatex") and shutil.which("latexmk"))
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main:\n      - src/Topic B Two.tex\n"
                 "      - src/Topic A One.tex\n"
                 "targets:\n  html:\n    format: html\n"
                 "  tagged:\n    format: source\n    tagging: \"on\"\n"
                 + ("  pdf:\n    format: pdf\n" if pdf else ""))
    listed = convert(work)
    said = listed.stdout + listed.stderr

    def page(name):
        path = os.path.join(work, "html", name)
        return read(work, "html", name) if os.path.exists(path) else ""

    def copy(name):
        path = os.path.join(work, "tagged", "src", name)
        return read(work, "tagged", "src", name) if os.path.exists(path) else ""
    a, b = page("Topic-A-One.html"), page("Topic-B-Two.html")
    sample = read(work, "contents-sample.yaml") \
        if os.path.exists(os.path.join(work, "contents-sample.yaml")) else ""
    tagged = copy("Topic A One.tex")
    # A pattern names them too, in sorted order.
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main: src/*.tex\n"
                 "targets:\n  html:\n    format: html\n")
    pattern = convert(work)
    sorted_sample = read(work, "contents-sample.yaml") \
        if os.path.exists(os.path.join(work, "contents-sample.yaml")) else ""
    # The documents grouped under one entry, and a Word target merging the
    # group: one file, opening at the group's Heading 1, each document a
    # Heading 2 titled as its page is, its title's \textrm and all.
    with open(os.path.join(work, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: org.example.course\n  title: Course 101\n"
                 "  contents:\n  - title: The Topics\n    items:\n    - Topic-A-One\n"
                 "    - Topic-B-Two\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main: src/*.tex\n"
                 "targets:\n  docx:\n    format: docx\n    merge: groups\n")
    merged = convert(work)
    # The book's own cartridge, built beside it, with no master at the top
    # (the binder gone): latex.main says it's a book, and the cartridge
    # isn't taken for one to unpack.
    import zipfile
    os.remove(os.path.join(work, "Combined.tex"))
    with zipfile.ZipFile(os.path.join(work, "org.example.course.imscc"), "w") as z:
        z.writestr("imsmanifest.xml", '<?xml version="1.0"?><manifest identifier="m" '
                   'xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"/>')
    rerun = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quiet",
                            "--check-only"], cwd=work, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
    rerun_said = rerun.stdout + rerun.stderr
    # A page of the book's, as HTML, beside its masters (as that cartridge
    # unpacked halfway left FINC 308's): an earlier run's, not a source, so
    # the page is still the document's.
    with open(os.path.join(work, "Topic-A-One.html"), "w", encoding="utf-8") as fh:
        fh.write("<html><head><title>Old</title></head><body><h1>Old</h1>"
                 "<p>AN OLD PAGE WRITTEN BESIDE THE BOOK.</p></body></html>")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main: src/*.tex\n"
                 "targets:\n  html:\n    format: html\n")
    beside = convert(work)
    beside_said = beside.stdout + beside.stderr
    beside_page = page("Topic-A-One.html")

    def word_headings():
        import zipfile
        path = os.path.join(work, "docx", "The-Topics.docx")
        if not os.path.exists(path):
            return []
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        found = []
        for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
            style = re.search(r'<w:pStyle w:val="([^"]+)"', p)
            if style and style.group(1).startswith(("Heading", "Title")):
                found.append((style.group(1), "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))))
        return found

    def pdfs_titled():
        if not pdf:
            return skip("no lualatex or latexmk for the PDF target")
        try:
            import pikepdf
        except ImportError:
            return skip("no pikepdf to read the PDFs")
        titles = []
        for name in ("Topic-A-One.pdf", "Topic-B-Two.pdf"):
            path = os.path.join(work, "pdf", name)
            if not os.path.exists(path):
                return False
            with pikepdf.open(path) as found, found.open_metadata() as meta:
                titles.append(meta.get("dc:title"))
        return titles == ["Topic A: The First Topic", "Topic B: The Second Topic"]

    def pdfs_pass():
        if not pdf:
            return skip("no lualatex or latexmk for the PDF target")
        verapdf = os.environ.get("VERAPDF") or shutil.which("verapdf")
        if not verapdf:
            return skip("no veraPDF to check the PDFs")
        for name in ("Topic-A-One.pdf", "Topic-B-Two.pdf"):
            done = subprocess.run([verapdf, "-f", "ua2", "--format", "text",
                                   os.path.join(work, "pdf", name)],
                                  capture_output=True, text=True)
            if not done.stdout.strip().startswith("PASS"):
                return False
        return True
    return [
        ("a binder that only gathers PDFs stops the run, naming the documents of "
         "their names in its order, and the one with none",
         lambda: stopped.returncode != 0 and "\\includepdf" in told
         and 0 < told.find('- "src/Topic A One.tex"') < told.find('- "src/Topic B Two.tex"')
         and "defaults:" in told and "Topic C Three.pdf" in told
         and "Nothing was converted" in told),
        ("latex.main lists the documents, each a page, in the order it gives",
         lambda: listed.returncode == 0 and a and b
         and "2 LaTeX documents are the book" in said
         and 0 < sample.find("Topic-B-Two") < sample.find("Topic-A-One")),
        ("a document below the book's directory reaches a file and an image from its "
         "own folder, as its author builds it there",
         lambda: "A NOTE FROM ITS FOLDER." in b and re.search(r'<img[^>]*alt="A black dot"', b)
         and os.path.exists(os.path.join(work, "tagged", "src", "shared", "note.tex"))
         and "\\includegraphics[alt={A black dot},width=1cm]{img/dot}" in copy("Topic B Two.tex")),
        ("a pattern in latex.main names them in sorted order",
         lambda: pattern.returncode == 0
         and 0 < sorted_sample.find("Topic-A-One") < sorted_sample.find("Topic-B-Two")),
        ("a title set as large type is the page's title, its sections under it, the "
         "course's name kept",
         lambda: "<title>Topic A: The First Topic</title>" in a and a.count("<h1") == 1
         and re.search(r"<h2[^>]*>Balances</h2>", a) and "COURSE 101: Testing" in a
         and "<title>Topic B: The Second Topic</title>" in b),
        ("an \\appendix before a document's last section doesn't make the page an appendix",
         lambda: sample and "appendix" not in sample and 'name="page-role"' not in a),
        ("a \\ref to an enumerated item is the item's number, as LaTeX gives it",
         lambda: re.search(r"<p>1b</p>", a) and "[QA1]" not in a),
        ("a table whose column type the document defines is read as a table",
         lambda: re.search(r"<th[^>]*>(<strong>)?Item", a) and "2inR" not in a),
        ("a table of one paragraph column holding prose is a box, not a table",
         lambda: re.search(r'<div class="box">\s*<p><strong>Example: A Boxed Passage', a)
         and "A box is a frame" in a and "<td" not in a.split("Example: A Boxed")[1][:400]),
        ("the copy writes each document, made to build with tagging: its title for the "
         "PDF's, hyperref for its bookmarks, titlesec not loaded, enumitem's settings "
         "taken, the box a division, and \\leavevmode before its formula",
         lambda: "\\DocumentMetadata" in copy("Topic B Two.tex")
         and "\\title{\\textrm{Topic A: The First Topic}}" in tagged
         and "\\usepackage[hidelinks]{hyperref}" in tagged
         and "\\disable@package@load{titlesec}" in tagged
         and "ver@latex-lab-enumitem.sty" in tagged
         and "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi\\begin{tabular}{p{4in}}"
         in tagged and "\\leavevmode\\[" in tagged
         and "\\begin{tabular}{p{2in}R{1in}}" in tagged),
        ("a Word file merging the documents' group opens at the group's Heading 1, each "
         "document a Heading 2 titled as its page is",
         lambda: merged.returncode == 0 and word_headings()[:3] == [
             ("Heading1", "The Topics"), ("Heading2", "Topic A: The First Topic"),
             ("Heading3", "Learning Objectives")]),
        ("the PDF target builds a PDF of each, named as its page is, its title the "
         "document's", pdfs_titled),
        ("and each passes veraPDF's PDF/UA-2 profile", pdfs_pass),
        ("the book's own cartridge beside its documents isn't taken for a book to unpack, "
         "with latex.main naming them and no master at the top",
         lambda: rerun.returncode == 0
         and "org.example.course.imscc: not read, since this directory has sources" in rerun_said),
        ("an .html file named as one of the book's pages is an earlier run's, not read, "
         "so the page is still the document's",
         lambda: beside.returncode == 0 and "Topic A: The First Topic" in beside_page
         and "AN OLD PAGE" not in beside_page
         and "have the names of the LaTeX book's pages (Topic-A-One.html)" in beside_said),
    ]


def case_pieces(work):
    """The pieces the LaTeX copies take, each on its own."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild
    import latexsource
    import texremediate
    log = ("(./Topic 03 Financial Statements.tex\n"
           "./Topic 03 Financial Statements.tex:65: Package titlesec Error: No format for "
           "this command.\n\nSee the titlesec package documentation.\n l.65 \\section*{Goals}\n")
    nested = r"""
\begin{enumerate}
\item A \label{a}
\item B
  \begin{enumerate}
  \item x
  \item y \label{b}
    \begin{enumerate}
    \item p
    \item q
    \item r \label{c}
    \end{enumerate}
  \end{enumerate}
\end{enumerate}
\begin{enumerate}[label=(\alph*)]
\item one
\item two \label{d}
\end{enumerate}
\begin{enumerate}[resume]
\item three \label{e}
\end{enumerate}
\begin{enumerate}[label=\Roman*.,start=4]
\item \label{f} four
\end{enumerate}
\section{X}\label{g}
"""
    types = {"R": (1, ">{\\raggedleft\\arraybackslash}p{#1}"), "Y": (0, "R{1cm}")}
    ordered = ("\\newcommand{\\fig}[1]{\\includegraphics{#1}}\n\\input{defs}\n"
               "\\renewcommand{\\fig}[3]{\\includegraphics[width=#2]{#1}}\n"
               "\\def\\pic#1{\\includegraphics{#1}}\n"
               "\\renewcommand{\\pic}[1]{\\textbf{no image}}\n"
               "\\providecommand{\\fig}[1]{\\textbf{not taken}}\n"
               "\\providecommand{\\newfig}[1]{\\includegraphics[width=1cm]{#1}}\n")
    metadata = {"o.tex": "\\DocumentMetadata{pdfversion=2.0, lang=en}\n\\documentclass{article}\n"
                         "\\begin{document}\nx\n\\end{document}\n"}
    texremediate.tag(metadata, "o.tex", "en", mathml=False)
    own_metadata = metadata["o.tex"]
    moving = ("\\captionof{figure}[Short]{Long} \\addcontentsline{toc}{section}{T} "
              "\\index{i}")
    # A data table in a box, its header declaration before it: tagging set
    # back to a table before the declaration, so it reads as it applies.
    boxed = {"b.tex": "\\documentclass{article}\n\\begin{document}\n\\begin{tabular}{p{4in}}\n"
                      "\\textbf{Example: A box.} A box is a frame around a passage of prose, "
                      "which runs on for a while here.\n\n"
                      "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/header-rows={1}}\\fi"
                      "\\begin{tabular}{lr}\nA & B \\\\\n1 & 2 \\\\\n\\end{tabular}}\n"
                      "\\end{tabular}\n\\end{document}\n"}
    texremediate.tag(boxed, "b.tex", "en", mathml=False)
    # What the reading copy makes of a book made its own way (OpenIntro).
    envs = {"a.tex": "\\newenvironment{var}[1]{\\texttt{#1}}{}\n"
                     "\\begin{var}{x}\\end{var} and \\var{y}.\n"}
    latexsource.environment_definitions(envs, ["a.tex"], {})
    grouped = latexsource.group_commands(
        "{\\Large \\begingroup A\\par \\endgroup}\n"
        "\\newcommand{\\s}{\\begingroup}\\newcommand{\\e}{\\endgroup}\n"
        "$\\begingroup x\\endgroup$ A\\\\begingroup B \\endgroup", {})
    # A group or a number after a command the reader takes whole, with its
    # arguments as LaTeX takes them; in a formula, a comment, or after \\
    # (a line break), and after a space that follows an argument, nothing.
    kept = latexsource.keep_groups(
        "\\noindent {A}\\hspace*{1em}{B}\\raisebox{1pt}[2pt]{R}{C}\\selectfont 1.1 "
        "\\noindent\n42 \\vspace{1em} {D} $\\hspace{1em}{x}$ \\\\noindent{E} % \\noindent{F}\n"
        "\\noindent\n\n7", {})
    titled = latexsource.drop_command(
        "A\\titleformat{\\chapter}\n  {}\n  {Chapter}% #1}\n  {1em}\n  {}\n  []\nB", "titleformat",
        "mommmmo", {}, "titlesec")
    # An environment defined in another's codes, and LaTeX's own redefined:
    # the reader's to read; the book's own, redefined, is a command still.
    nested_envs = {"a.tex": "\\newenvironment{exercises}{\\par\\newenvironment{hint}{(Hint: }{)}"
                       "\\begin{enumerate}}{\\end{enumerate}}\n"
                       "\\renewenvironment{enumerate}{\\begin{itemize}}{\\end{itemize}}\n"
                       "\\newenvironment{var}[1]{\\texttt{#1}}{}\n"
                       "\\renewenvironment{var}[1]{\\textbf{#1}}{}\n"
                       "\\begin{exercises}\\item Do it. \\begin{hint}think\\end{hint}"
                       "\\end{exercises}\n\\begin{enumerate}\\item x\\end{enumerate}\n\\var{y}\n"}
    latexsource.environment_definitions(nested_envs, ["a.tex"], {})
    nested_read = subprocess.run(
        ["pandoc", "-f", "latex", "-t", "plain"], capture_output=True, text=True,
        input="\\documentclass{book}\n\\begin{document}\n" + nested_envs["a.tex"]
        + "\\end{document}\n").stdout
    colored = {"main.tex": "\\documentclass{book}\n\\input{colors}\n\\definecolor{oiB}{rgb}{0,0,0}\n"
                           "\\newcommand{\\hl}[2]{\\definecolor{hl}{rgb}{#1}\\textcolor{hl}{#2}}\n"
                           "\\newcommand{\\blue}[1]{\\textcolor[rgb]{0,0,1}{#1}}\n"
                           "\\begin{document}\n\\textcolor{oiB}{A} \\textcolor[rgb]{0,0,1}{M} "
                           "$\\textcolor[rgb]{0,0,1}{x}$ \\begin{tikzpicture}\\node "
                           "{\\textcolor[rgb]{0,0,1}{G}};\\end{tikzpicture}\n\\end{document}\n",
               "colors.tex": "\\definecolor{oiB}{rgb}{.337,.608,.741}\n"}
    latexsource.resolve_colors(colored, ["main.tex", "colors.tex"], {})
    color_order = [m.group(0) for m in latexsource.book_colors(
        [("main.tex", colored["main.tex"]), ("colors.tex", colored["colors.tex"])])]
    spans = [{"t": "Span", "c": [["", [], [["style", "color: oiB"]]], []]},
             {"t": "Span", "c": [["", [], [["style", "background-color: oiB"]]], []]},
             {"t": "Span", "c": [["", [], [["style", "color: red"]]], []]}]
    recolored = latexsource.color_spans(
        [{"t": "Para", "c": spans}], latexsource.color_values(color_order))
    # Colors CSS can't read as the book writes them: a \\colorlet, a mix, a
    # name xcolor's dvipsnames has and CSS hasn't, a [named] definition; one
    # \\providecolor doesn't change, a name CSS has, and one nothing defines.
    mixed_values = latexsource.color_values([
        "\\definecolor{oiB}{rgb}{.337,.608,.741}", "\\colorlet{light}{oiB!50}",
        "\\definecolor[named]{named}{HTML}{FF0000}", "\\providecolor{oiB}{rgb}{0,0,0}"])
    mixed = [{"t": "Span", "c": [["", [], [["style", "color: " + c]]], []]}
             for c in ("light", "red!50!black", "BrickRed", "named", "oiB", "Orchid", "nosuch")]
    # \\textcolor around paragraphs is a division.
    mixed.append({"t": "Div", "c": [["", [], [["style", "color: light"]]], []]})
    remixed = latexsource.color_spans([{"t": "Para", "c": mixed}], mixed_values)
    mixed_styles = [dict(map(tuple, p["c"][0][2])).get("style") for p in mixed]
    # Label keys with whitespace and a macro's {} in them, read and written
    # as ids, a reference through the book's own macro matched first.
    keyed_doc = json.loads(subprocess.run(
        ["pandoc", "-f", "latex", "-t", "json"], capture_output=True, text=True,
        input="\\documentclass{book}\n\\newcommand{\\secref}[1]{Section~\\ref{#1}}\n"
        "\\newcommand{\\edwardsat}{1300}\n\\begin{document}\n\\section{Airports}\\label{US Airports}\n"
        "See \\ref{US Airports}, \\secref{US Airports}, \\ref{edwardSatBelow\\edwardsat{}}.\n\n"
        "Below\\label{edwardSatBelow\\edwardsat{}} and\\label{\n}.\n\\end{document}\n").stdout)
    latexsource.normalize_keys(keyed_doc["blocks"])
    keyed_links, keyed_ids = [], []

    def keyed_walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Link":
                keyed_links.append(node)
            if node.get("t") == "Span" and any(k == "label" for k, _ in node["c"][0][2]):
                keyed_ids.append(node["c"][0][0])
            if node.get("t") == "Header":
                keyed_ids.insert(0, node["c"][1][0])
            for v in node.values():
                keyed_walk(v)
        elif isinstance(node, list):
            for v in node:
                keyed_walk(v)
    keyed_walk(keyed_doc["blocks"])
    keyed_read = [link["c"][2][0] for link in keyed_links]
    keyed_numbers = [latexsource.stringify(link["c"][1]) for link in keyed_links[:2]]
    # The sample's probe, each formula found by its mark: a macro whose
    # expansion breaks its paragraph doesn't shift the rest onto the wrong
    # macros.
    probe_dir = os.path.join(work, "probe")
    os.makedirs(probe_dir, exist_ok=True)
    probed = latexsource.probe(
        probe_dir, "\\documentclass{article}\n\\newcommand{\\bad}{a$\\par$b}\n"
        "\\newcommand{\\good}{x}\n\\newcommand{\\worse}{\\leavevmode}\n\\begin{document}\n",
        [("bad", 0), ("good", 0), ("worse", 0)], os.path.join(ROOT, "bin", "latex-source.lua"))
    # The marks where the book steps, sets, and shows a counter: not in a
    # key, a formula, a comment, a drawing, or a \\the definition.
    marked = latexsource.counter_marks(
        "\\refstepcounter{eoce}\\setcounter{chapter}{#1}\\addtocounter{x}{\\value{y}}"
        "\\setcounter{z}{\\numexpr1}\\label{e_\\arabic{eoce}} \\thesection\\thepage "
        "\\arabic{x}$\\arabic{x}$ % \\arabic{x}\n\\begin{tikzpicture}\\stepcounter{x}"
        "\\end{tikzpicture}\\renewcommand{\\theeoce}{\\arabic{eoce}}\\appendix", {}, (),
        ("section", "eoce"))
    in_math = ("\\newcommand{\\grp}[1]{\\begingroup #1\\endgroup}\n"
               "\\newcommand{\\hl}[1]{\\grp{#1}\\hspace{1em}{z}}\n"
               "\\newcommand{\\remark}[1]{\\noindent\\begingroup #1\\endgroup}\n"
               "Text $\\hl{x}$ and \\remark{y}.\n")
    math_kept = latexsource.repair_text(in_math, {}, latexsource.math_macros([in_math]))
    no_macros = latexsource.math_macros(["A formula: $x + 1$, and no macro.\n"])
    line_break = "A\\\\[6mm] B \\[ y \\] C"
    starred = "A\\titleformat*{\\section}{\\bfseries}B\\titlespacing*{\\section}{0pt}{1em}{1em}C"
    for command, signature in latexsource.TITLESEC_COMMANDS:
        starred = latexsource.drop_command(starred, command, signature, {}, "titlesec")
    commented = latexsource.macro_calls("\\two{a}% between\n{b}",
                                        {"two": {"arguments": 2, "default": None}}, [])
    alt_calls = {"s.tex": "\\newcommand{\\fig}[2][]{\\includegraphics{#2}}\n"
                          "\\fig[A phrase that may be alt text]{a}\\fig{b}\\fig[x]{c}\n"}
    def authors(source):
        """The names the contents sample gives for an \\author."""
        out = subprocess.run(["pandoc", "-f", "latex", "-t", "json"], capture_output=True,
                             text=True, input="\\documentclass{book}\n\\author{%s}\n"
                             "\\begin{document}\nx\n\\end{document}\n" % source).stdout
        meta = json.loads(out)["meta"].get("author", {})
        items = meta.get("c", []) if meta.get("t") == "MetaList" else [meta]
        return [n for a in items for n in latexsource.author_names(a.get("c", []))]
    settings = texremediate.enumitem_settings(
        {"a": "\\begin{itemize}[leftmargin=*,labelindent=0pt]\n\\item x\n\\end{itemize}\n"
              "\\begin{enumerate}[resume,label={(\\alph*)}]\n\\item y\n\\end{enumerate}\n"
              "\\setlist[itemize]{leftmargin=*}\n"})
    # The layout a preamble gives its pages, as Pandoc's variables: FINC
    # 308's, OpenIntro's class line with a comment in it, parskip and a
    # \parindent of zero, a KOMA class's own keys, and geometry's braces.
    layouts = [latexsource.page_layout([("m.tex", text)]) for text in (
        "\\documentclass[11pt]{article}\n\\usepackage[margin=1in]{geometry}\n"
        "\\usepackage{parskip}\n\\setstretch{1}\n\\begin{document}\nx\n\\end{document}\n",
        "\\documentclass[10pt,openany]%,oneside]\n{book}\n\\begin{document}\nx\n"
        "\\end{document}\n",
        "\\documentclass[fontsize=12pt,paper=a4,parskip=half]{scrbook}\n"
        "\\usepackage{geometry}\n\\geometry{total={6in,8in}, top=1in}\n\\onehalfspacing\n"
        "\\begin{document}\n\\geometry{left=2in}\nx\n\\end{document}\n",
        "\\documentclass[a4paper,twoside]{report}\n\\setlength{\\parindent}{0pt}\n"
        "% \\usepackage[margin=3in]{geometry}\n\\begin{document}\nx\n\\end{document}\n",
        # Options a line each, with their notes; settings an environment or a
        # command makes, and one a hook makes at \begin{document}.
        "\\documentclass[%\n  12pt, % type size\n  twoside]{book}\n"
        "\\usepackage[left=1in, % inner\n  right=1in]{geometry}\n\\onehalfspacing\n"
        "\\newenvironment{code}{\\singlespacing\\setlength{\\parindent}{0pt}}{}\n"
        "\\AddToHook{env/quote/begin}{\\setlength{\\parindent}{0pt}}\n"
        "\\newcommand\\tight{\\setstretch{0.9}}\n\\begin{document}\nx\n\\end{document}\n",
        "\\documentclass{article}\n\\AtBeginDocument{\\setlength{\\parindent}{0pt}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        "\\documentclass{article}\n\\AddToHook{begindocument}{\\setlength{\\parindent}{0pt}}\n"
        "\\begin{document}\nx\n\\end{document}\n")]
    # wasysym in a book with no formula: its symbols as Unicode all the same,
    # with the fonts and fallback that draw them; with formulas, unicode-math.
    no_math_block, no_math = texremediate.math_block(
        {"m.tex": "\\documentclass{article}\n\\usepackage{wasysym}\n\\begin{document}\n"
                  "\\Square\\ unchecked\n\\end{document}\n"}, "m.tex")
    math_block, with_math = texremediate.math_block(
        {"m.tex": "\\documentclass{article}\n\\usepackage{amsmath,wasysym}\n"
                  "\\begin{document}\n$x \\lhd y$\n\\end{document}\n"}, "m.tex")
    shims = texremediate.shimmed_packages({"titlesec", "soulutf8", "amsmath", "enumerate"})
    shim_block = texremediate.shim_block(shims)
    flat_alt, flat_counts = texremediate.remediate_file(
        "/nonexistent", "a.tex",
        "\\fig[A first paragraph.\n\nA second one,\\par a third]{sq}\\fig[One]{sq}\n", {},
        [], macros={"fig": {"file": "#2", "arguments": 2, "default": "", "alt": 1,
                            "keyed": False, "options": None}})
    def lossless():
        """A raster stored losslessly stays so when its figure's fonts are
        embedded, where Ghostscript's own choice made it JPEG."""
        import latexbuild
        if latexbuild.embedding_tool() != "gs":
            return skip("no Ghostscript to embed a figure's fonts")
        try:
            from pypdf import PdfReader
        except ImportError:
            return skip("no pypdf to read the figure")
        source, dest = os.path.join(work, "heat.pdf"), os.path.join(work, "heat-embedded.pdf")
        os.makedirs(work, exist_ok=True)
        raw = raster_pdf(source)
        if not latexbuild.embed_fonts(source, dest, "gs"):
            return False
        image = list(PdfReader(dest).pages[0]["/Resources"]["/XObject"].values())[0].get_object()
        return str(image.get("/Filter")) == "/FlateDecode" and image.get_data() == raw
    def titlesec_with_fancyhdr():
        """titlesec's stand-in beside fancyhdr's page styles builds tagged:
        titleps, loaded for titlesec's own styles, clashed with fancyhdr's
        \\headrule when it was loaded at once (OpenIntro Statistics)."""
        if not shutil.which("lualatex"):
            return skip("no lualatex for the copies' builds")
        folder = os.path.join(work, "fancy")
        os.makedirs(folder, exist_ok=True)
        texts = {"f.tex": "\\documentclass{book}\n\\usepackage{fancyhdr}\n"
                          "\\usepackage[explicit]{titlesec}\n\\pagestyle{fancy}\n"
                          "\\fancyhead[L]{Left}\n\\titleformat{\\section}{\\bfseries}"
                          "{\\thesection\\quad #1}{1em}{}\n\\begin{document}\n"
                          "\\chapter{One}\n\\section{A}\nText.\n\\end{document}\n"}
        texremediate.tag(texts, "f.tex", "en", True, ("ua-2",), None)
        with open(os.path.join(folder, "f.tex"), "w", encoding="utf-8") as fh:
            fh.write(texts["f.tex"])
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "f.tex"], cwd=folder, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        return done.returncode == 0
    # Display formulas' rows, as LaTeX numbers them: a last \\\\ makes a row, a
    # length after one is no row's, a nested environment's and a group's
    # rows aren't the formula's, alignat's columns aren't text, multline is
    # numbered once.
    rows = []
    for tex in ("\\begin{align} a &= b \\\\ c &= d \\\\ \\end{align}",
                "\\begin{gather} p \\\\[2pt] [q] \\end{gather}",
                "\\begin{align} \\begin{cases} a \\\\ b \\end{cases} \\\\ {x \\\\ y} "
                "\\label{k} \\end{align}",
                "\\begin{alignat}{2} a &= b \\nonumber \\end{alignat}",
                "\\begin{multline*} m \\\\ n \\tag{q} \\end{multline*}"):
        _, is_starred, row_spans, _ = latexsource.display_rows(tex)
        rows.append((is_starred, [(tex[a:b].strip(), [c[:2] for c in latexsource.row_commands(
            tex, a, b)]) for a, b in row_spans]))
    # The counting on its own: a chapter's align, its first row numbered and
    # tagged, its second not, and \\eqref's number in parentheses.
    eq_doc = json.loads(subprocess.run(
        ["pandoc", "-f", "latex", "-t", "json"], capture_output=True, text=True,
        input="\\documentclass{book}\n\\begin{document}\n\\chapter{A}\n\\begin{align}\n"
              "a \\label{p}\\\\\nb \\nonumber\n\\end{align}\nSee \\eqref{p}.\n"
              "\\end{document}\n").stdout)
    eq_book = "\\documentclass{book}\n\\begin{document}\n\\chapter{A}\n\\end{document}\n"
    eq_counts = {}
    latexsource.resolve_counters(eq_doc["blocks"],
                                 latexsource.book_counters([("m.tex", eq_book)], eq_book),
                                 eq_counts)
    eq_text = json.dumps(eq_doc)
    # An EPUB chapter titled by a heading with a backslash in its text and a
    # formula, its TeX in the MathML's annotation.
    import importlib.util
    import zipfile
    epub_spec = importlib.util.spec_from_file_location("build_epub", os.path.join(BIN, "build-epub.py"))
    build_epub = importlib.util.module_from_spec(epub_spec)
    epub_spec.loader.exec_module(build_epub)
    titled_epub = os.path.join(work, "titled.epub")
    with zipfile.ZipFile(titled_epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("EPUB/text/ch001.xhtml", "<html><head><title>ch001</title></head><body>"
                   "<h1>The \\pmb key and <math><semantics><mi>t</mi><annotation encoding="
                   "\"application/x-tex\">\\pmb{t}</annotation></semantics></math></h1>"
                   "</body></html>")
    build_epub.retitle_chapters(titled_epub)
    with zipfile.ZipFile(titled_epub) as z:
        epub_title = re.search(r"<title>(.*?)</title>",
                               z.read("EPUB/text/ch001.xhtml").decode("utf-8")).group(1)
    # Headings out of divisions: one in another language takes the language
    # with it; one in a theorem's division stays.
    hoisted, hoisted_count = latexsource.hoist_headings([
        {"t": "Div", "c": [["", [], [["lang", "fr"]]], [
            {"t": "Header", "c": [2, ["resume", [], []], [{"t": "Str", "c": "Le"}]]},
            {"t": "Para", "c": [{"t": "Str", "c": "Un"}]}]]},
        {"t": "Div", "c": [["ex", ["example"], []], [
            {"t": "Header", "c": [5, ["setup", [], []], [{"t": "Str", "c": "Setup."}]]},
            {"t": "Para", "c": [{"t": "Str", "c": "x"}]}]]}], {"example"})

    def elements(node, kind):
        found = [node] if isinstance(node, dict) and node.get("t") == kind else []
        for value in (node.values() if isinstance(node, dict) else
                      node if isinstance(node, list) else []):
            found += elements(value, kind)
        return found
    eq_links = [link["c"][1] for link in elements(eq_doc["blocks"], "Link")]
    # The PDF filter on such a formula: its number set by LaTeX, by the tag,
    # its label the anchor before it, none left in its TeX nor a blank line
    # where one was; what subequations held put back in it.
    eq_spans = []
    for classes, tex, attributes in (
            (["equation"], "\\begin{equation}\n\\label{x}\nE\n \\tag{1.1}\\end{equation}", []),
            (["equation", "subequations"], "\\label{s}\n\\begin{align}\nu \\label{s-a} "
             "\\tag{1.2a}\n\\end{align}\n", []),
            (["equation"], "\\begin{eqnarray}\na &=& b \\label{e}\n\\end{eqnarray}",
             [["eqnarray-counter", "4"], ["eqnarray-prefix", "2."]])):
        anchors = [{"t": "Span", "c": [[k, [], [["label", k]]], []]}
                   for k in re.findall(r"\\label\{([^}]*)\}", tex)]
        eq_spans.append({"t": "Span", "c": [["", classes, attributes], anchors + [
            {"t": "Math", "c": [{"t": "DisplayMath"}, tex]},
            {"t": "Span", "c": [["", ["equation-number"], []], [{"t": "Str", "c": "(9.9)"}]]}]]})
    eq_latex = subprocess.run(
        ["pandoc", "-f", "json", "-t", "latex", "--lua-filter",
         os.path.join(BIN, "pdf-target.lua")], capture_output=True, text=True,
        input=json.dumps({"pandoc-api-version": eq_doc["pandoc-api-version"], "meta": {},
                          "blocks": [{"t": "Para", "c": eq_spans}]})).stdout
    def titlesec_pagestyles():
        """titlesec's pagestyles option loads titleps at once, as titlesec
        does, so a command of titleps's the preamble uses before its first
        page style (\\settitlemarks) is defined in the copy too."""
        if not shutil.which("lualatex"):
            return skip("no lualatex for the copies' builds")
        folder = os.path.join(work, "pagestyles")
        os.makedirs(folder, exist_ok=True)
        texts = {"p.tex": "\\documentclass{book}\n\\usepackage[pagestyles]{titlesec}\n"
                          "\\settitlemarks{chapter,section}\n"
                          "\\newpagestyle{main}{\\sethead{}{\\chaptertitle}{}}\n"
                          "\\pagestyle{main}\n\\begin{document}\n\\chapter{One}\nText.\n"
                          "\\end{document}\n"}
        texremediate.tag(texts, "p.tex", "en", True, ("ua-2",), None)
        with open(os.path.join(folder, "p.tex"), "w", encoding="utf-8") as fh:
            fh.write(texts["p.tex"])
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "p.tex"], cwd=folder, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
        return done.returncode == 0 and "\\bool_gset_true:N \\g__oer_titlesec_pagestyles_bool" \
            in texts["p.tex"]
    # The cut: what the master sets itself after an \include goes on with
    # that file's page until a part's or a chapter's heading, which begins
    # a page of its own with the role the division commands before it give,
    # one inside appendices too; a page name an \include-d file has is
    # skipped; a figure's empty short caption is kept.
    def cut_heading(level, words):
        return {"t": "Header", "c": [level, ["", [], []], [{"t": "Str", "c": words}]]}

    def cut_para(words):
        return {"t": "Para", "c": [{"t": "Str", "c": words}]}

    def cut_division(name):
        return {"t": "Para", "c": [{"t": "Span", "c": [
            ["", [latexsource.DIVISION_CLASS], [["division", name]]], []]}]}
    cut_figure = {"t": "Figure", "c": [["f", [], []], [None, [cut_para("Cap")]], []]}
    cut = latexsource.cut_pages({"blocks": [
        cut_division("frontmatter"), cut_heading(2, "Preface"), cut_para("Front."),
        cut_para(latexsource.MARKER_LINE % 0), cut_heading(2, "One"), cut_figure,
        cut_para(latexsource.END_MARKER_LINE % 0), cut_division("mainmatter"),
        cut_heading(1, "Part A"), cut_para("Intro."),
        cut_para(latexsource.MARKER_LINE % 1), cut_heading(2, "Two"),
        cut_para(latexsource.END_MARKER_LINE % 1), cut_para("Exercises after two."),
        {"t": "Div", "c": [["", ["appendices"], []], [
            cut_division("appendices"), cut_heading(2, "Inline appendix"), cut_para("A.")]]},
        cut_division("endappendices"), cut_heading(2, "Back in the main matter")]},
        [("one.tex", "front"), ("ch/book-1.tex", "main")], "book", "main", {1, 2})
    cut_shape = [(stem, role, own, [b["c"][2][0]["c"] if b["t"] == "Header" else b["t"]
                                    for b in blocks]) for stem, role, blocks, own in cut]
    # Floats whose captions the reader drops, as the copy writes them.
    captioned = latexsource.captionof_floats(
        "\\begin{minipage}{2in}\\includegraphics{a}\\captionof{figure}{A}\\label{a}"
        "\\end{minipage}\\begin{minipage}{2in}\\includegraphics{b}\\captionof{figure}{B}"
        "\\end{minipage}\n\nText \\captionof{table}{C}\n\n\\begin{center}X "
        "\\captionof{figure}{D}\n\nY \\captionof{figure}{E}\\label{e}\\end{center}\n"
        "\\begin{figure}\\captionof{figure}{F}\\end{figure}\n", {})
    wrapped = latexsource.wrapped_floats(
        "\\begin{wrapfigure}[10]{r}[2pt]{0.4\\textwidth}X\\caption{W}\\end{wrapfigure} "
        "\\begin{wraptable}{l}{3cm}T\\end{wraptable}", {})
    image_tables = latexsource.table_floats(
        "\\begin{table}[h]\\includegraphics{t}\\caption{T}\\end{table} \\begin{table}"
        "\\caption{U}\\input{u}\\end{table}", {})
    # Two tables, subtables, and a table in a table's cell, which is one.
    table_shapes = latexsource.table_floats(
        "\\begin{table}\\begin{tabular}{l}a\\end{tabular}\\begin{tabular}{l}b\\end{tabular}"
        "\\caption{Two}\\end{table}\n\\begin{table}\\begin{subtable}{2in}\\begin{tabular}{l}"
        "c\\end{tabular}\\caption{S}\\end{subtable}\\caption{Sub}\\end{table}\n\\begin{table}"
        "\\subfloat[L]{\\begin{tabular}{l}d\\end{tabular}}\\caption{F}\\end{table}\n"
        "\\begin{table}\\begin{tabular}{l}\\begin{tabular}{l}e\\end{tabular}\\end{tabular}"
        "\\caption{Nested}\\end{table}\n", {})
    # The counting on its own: the appendix package's appendices lettered
    # and given back, a subfigure by the obsolete subfigure package's
    # 1.1(a), a theorem retitled.
    def count_mark(*parts):
        return {"t": "Para", "c": [{"t": "Link", "c": [["", [], []], [], [
            "#%s:%s" % (latexsource.COUNTER_MARK, ":".join(parts)), ""]]}]}

    def count_ref(key):
        return {"t": "Link", "c": [["", [], [["reference-type", "ref"], ["reference", key]]],
                                   [{"t": "Str", "c": "[%s]" % key}], ["#" + key, ""]]}
    count_setup = latexsource.book_counters(
        [("m.tex", "\\documentclass{book}\n\\usepackage{subfigure}\n\\newtheorem{thm}{Theorem}\n"
                   "\\begin{document}\n\\chapter{A}\n\\end{document}\n")],
        "\\documentclass{book}\n\\begin{document}\n")
    count_blocks = [
        {"t": "Header", "c": [1, ["ch1", [], []], [{"t": "Str", "c": "One"}]]},
        {"t": "Figure", "c": [["whole", [], []], [None, [cut_para("Whole")]], [
            {"t": "Figure", "c": [["part", [], []], [None, [cut_para("Part")]], []]}]]},
        {"t": "Div", "c": [["thm", ["thm"], []], [{"t": "Para", "c": [
            {"t": "Strong", "c": [{"t": "Str", "c": "Theorem"}, {"t": "Space"},
                                  {"t": "Str", "c": "9.9"}]}, {"t": "Str", "c": "."}]}]]},
        count_mark("division", "appendices"),
        {"t": "Header", "c": [1, ["app", [], []], [{"t": "Str", "c": "App"}]]},
        {"t": "Header", "c": [1, ["app2", [], []], [{"t": "Str", "c": "App two"}]]},
        count_mark("division", "endappendices"),
        {"t": "Header", "c": [1, ["ch2", [], []], [{"t": "Str", "c": "Two"}]]},
        {"t": "Para", "c": [count_ref("ch1"), count_ref("part"), count_ref("app"),
                            count_ref("ch2")]}]
    latexsource.resolve_counters(count_blocks, count_setup)
    counted = [i["c"][1][0]["c"] for i in count_blocks[-1]["c"]]
    theorem_title = count_blocks[2]["c"][1][0]["c"][0]["c"][-1]["c"]
    subfloat = latexsource.subfigures("\\subfloat[Cap]{X\\label{a}}", {})
    # The names \autoref and cleveref print, the book's own and options too.
    own_names = {"cref": {"thm": ("thm.", "thms.")}, "Cref": {"lem": ("Lemma", "Lemmata")},
                 "capitalise": True, "noabbrev": True, "autoref": {"section": "Section"},
                 "name": {"thm": "Thm"}}
    name = latexsource.reference_name
    names_given = [
        name(own_names, "cref", ("figure", None, None)), name(own_names, "cref", ("thm", None, None)),
        name(own_names, "Cref", ("thm", None, None)), name(own_names, "cref", ("lem", None, None)),
        name(own_names, "cref", ("lem", None, None), plural=True),
        name({}, "cref", ("subsection", None, None)), name({}, "cref", ("equation", None, None), True),
        name(own_names, "autoref", ("section", None, None)),
        name(own_names, "autoref", ("thm", None, "thm")),
        name({}, "autoref", ("section", "second", None)),
        name({}, "autoref", ("subsection", "deep", None)), name({}, "autoref", ("lem", None, "thm")),
        # A theorem sharing another's counter is named by its own environment.
        name({"autoref": {"lemma": "Lemma"}}, "autoref", ("lemma", None, "theorem")),
        name({}, "autoref", ("lemma", None, "theorem"))]
    commands = latexsource.reference_commands(
        "\\cref{a, b} \\crefrange{c}{d} $\\cref{e}$ % \\cref{f}\n", {})
    # xcolor's svgnames and x11names in a mix, the last set loaded winning
    # a name two have, as xcolor has it.
    set_mixes = [tuple(round(v, 3) for v in latexsource.color_rgb(
        color, {}, latexsource.xcolor_sets(options)) or ())
        for color, options in (("NavyBlue!50", ["dvipsnames", "svgnames"]),
                               ("NavyBlue!50", ["svgnames", "dvipsnames"]),
                               ("AntiqueWhite1!50!black", ["x11names"]))] \
        if shutil.which("kpsewhich") else None
    book_names = latexsource.book_counters(
        [("m.tex", "\\documentclass{book}\n\\usepackage[capitalise,noabbrev]{cleveref}\n"
                   "\\crefname{thm}{thm.}{thms.}\n\\Crefname{lem}{Lemma}{Lemmata}\n"
                   "\\renewcommand{\\sectionautorefname}{\\S}\n\\def\\thmname{Thm}\n"
                   "\\begin{document}\n\\end{document}\n")],
        "\\documentclass{book}\n\\begin{document}\n")["ref_names"]
    theorem_setup = latexsource.book_counters(
        [("m.tex", "\\documentclass{article}\n\\titleformat{\\chapter}{}{}{}{}\n"
                   "\\newtheorem{thm}{Theorem}[section]\n\\newtheorem{lem}[thm]{Lemma}\n"
                   "\\newtheorem*{rem}{Remark}\n\\begin{document}\n\\section{A}\n"
                   "\\end{document}\n")], "\\documentclass{article}\n\\begin{document}\n")
    # natbib's punctuation as natbib.sty sets it: options in its order of
    # declaring them, the preset only when nothing else set any, \\bibpunct.
    nat_styles = [latexsource.citation_style(code, bst) for code, bst in (
        ("\\usepackage{natbib}", "plainnat"), ("\\usepackage[round]{natbib}", "plainnat"),
        ("\\usepackage{natbib}", "econ"), ("\\usepackage[super]{natbib}", "plainnat"),
        ("\\usepackage[authoryear]{natbib}", "plainnat"),
        ("\\usepackage{natbib}\n\\bibpunct[; ]{(}{)}{,}{a}{}{,}", "plainnat"),
        ("\\usepackage{natbib}\n\\setcitestyle{square,citesep={/}}", "plainnat"),
        ("\\usepackage{natbib}\n\\citestyle{nature}", "plainnat"), ("", "plain"),
        ("\\usepackage[round,super]{natbib}", "plainnat"))]
    nat_shapes = [(n["open"], n["close"], n["sep"], n["mode"], n["aysep"], n.get("natbib"))
                  for n in nat_styles]
    found_nat = {"a": {"number": "1", "short": "Knuth", "year": "1984", "extra": "", "long": ""},
                 "b": {"number": "2", "short": "Lamport", "year": "1994", "extra": "",
                       "long": ""}}
    nat_super = "".join(w for w, _, _ in latexsource.citation_pieces(
        "citep", "", ["see", "p. 3"], ["a", "b"], found_nat, nat_styles[3]))
    nat_super_marked = [(w == latexsource.UNSKIP, sup) for w, _, sup in
                        latexsource.citation_pieces("citep", "", [], ["a", "b"], found_nat,
                                                    nat_styles[3])]
    nat_labels = [latexsource.natbib_label(label) for label in (
        "Knuth(1986{\\natexlab{a}})", "\\protect\\citeauthoryear{Knuth and Lamport}{Knuth"
        " et~al.}{1990}", "\\protect\\citeauthoryear{Jones}{1991b}",
        "\\protect\\citename{Smith, }1992", "Doe, 1993", "Knu84")]
    # A table float with no table the reader counts ends its \\caption*.
    def float_mark(op):
        return {"t": "Para", "c": [{"t": "Link", "c": [["", [], []], [], [
            "#%s:%s" % (latexsource.COUNTER_MARK, op), ""]]}]}
    float_blocks = [float_mark("unnumbered"), float_mark("floatend"),
                    {"t": "Figure", "c": [["fig:after", [], []], [None, [{"t": "Plain", "c": [
                        {"t": "Str", "c": "After"}]}]], []]},
                    {"t": "Para", "c": [{"t": "Link", "c": [
                        ["", [], [["reference-type", "ref"], ["reference", "fig:after"]]],
                        [{"t": "Str", "c": "[fig:after]"}], ["#fig:after", ""]]}]}]
    latexsource.resolve_counters(float_blocks, latexsource.book_counters(
        [("m.tex", "\\documentclass{article}\n\\begin{document}\n\\end{document}\n")],
        "\\documentclass{article}\n\\begin{document}\n"))
    float_after = float_blocks[-1]["c"][0]["c"][1]
    commented_alt, _ = texremediate.remediate_file(
        "/nonexistent", "a.tex", "\\fig[A first. % to reword\n\nA second.]{sq}\n", {}, [],
        macros={"fig": {"file": "#2", "arguments": 2, "default": "", "alt": 1,
                        "keyed": False, "options": None}})
    return [
        ("natbib's punctuation is natbib.sty's: plainnat's preset, its own defaults for a "
         "style it has none for or once an option has set any, \\bibpunct, \\setcitestyle, "
         "and \\citestyle, its options in the order it declares them; LaTeX's own \\cite "
         "without natbib",
         lambda: nat_shapes == [
             ("[", "]", ",", "a", ",", True), ("(", ")", ";", "a", ",", True),
             ("(", ")", ";", "a", ",", True), ("", "", ";", "s", ",", True),
             ("[", "]", ",", "a", ",", True), ("(", ")", ",", "a", "", True),
             ("[", "]", "/", "a", ",", True), ("", "", ",", "s", "", True),
             ("[", "]", ",", "n", "", False), ("(", ")", ";", "s", ",", True)]
         and nat_styles[5]["cmt"] == "; "),
        ("natbib's superscripts: the numbers raised, the space before them taken away, a "
         "note before and after them in the line",
         lambda: nat_super == "see1;2 p. 3" and nat_super_marked == [
             (True, False), (False, True), (False, True), (False, True)]),
        ("natbib's labels: Name(Year) with \\natexlab's letter, \\citeauthoryear's three "
         "and two arguments, \\citename, apalike's, and alpha's, which isn't author and year",
         lambda: nat_labels == [("Knuth", "1986", "a", ""),
                                ("Knuth et~al.", "1990", "", "Knuth and Lamport"),
                                ("Jones", "1991", "b", ""), ("Smith", "1992", "", ""),
                                ("Doe", "1993", "", ""), None]),
        ("a table float's end ends its \\caption*, so the next float is numbered",
         lambda: float_after == [{"t": "Str", "c": "1"}]),
        ("the cut gives a part or a chapter the master sets itself a page of its own, with "
         "the role before it, one in appendices too, skipping a file's name, the master's "
         "text after an \\include going on with that file's page",
         lambda: cut_shape == [
             ("book-2", "front", True, ["Preface", "Para"]),
             ("one", "front", False, ["One", "Figure"]),
             ("book-3", "main", True, ["Part A", "Para"]),
             ("book-1", "main", False, ["Two", "Para"]),
             ("book-4", "appendix", True, ["Inline appendix", "Para"]),
             ("book-5", "main", True, ["Back in the main matter"])]),
        ("and keeps a caption's empty short form, which the division spans' removal took "
         "for an emptied paragraph",
         lambda: cut[1][2][1]["c"][1][0] is None and len(cut[1][2][1]["c"][1]) == 2),
        ("\\captionof's environment, or its paragraph, is a figure or a table, two in one "
         "environment each their own, one in a float only its caption, one float's end "
         "before the next one's beginning",
         lambda: captioned == (
             "\\begin{figure}\\begin{minipage}{2in}\\includegraphics{a}\\caption{A}\\label{a}"
             "\\end{minipage}\\end{figure}\\begin{figure}\\begin{minipage}{2in}"
             "\\includegraphics{b}\\caption{B}\\end{minipage}\\end{figure}\n\n"
             "\\begin{table}Text \\caption{C}\\end{table}\n\n\\begin{center}X "
             "\\begin{figure}\\caption{D}\\end{figure}\n\nY \\begin{figure}\\caption{E}"
             "\\label{e}\\end{figure}\\end{center}\n\\begin{figure}\\caption{F}\\end{figure}\n")),
        ("wrapfig's floats are a figure and a table, their arguments gone",
         lambda: wrapped == "\\begin{figure}X\\caption{W}\\end{figure} \\begin{table}T"
                            "\\end{table}"),
        ("a table float holding an image and no table is a figure marked a table, after "
         "its placement; one that \\input-s its table is left",
         lambda: image_tables.startswith(
             "\\begin{figure}[h]\\hyperref[TEXTBOOKIMPROVERCOUNTER:tablefloat]{}"
             "\\includegraphics{t}\\caption{T}\\end{figure}")
         and "\\begin{table}\\caption{U}\\input{u}\\end{table}" in image_tables),
        ("so is one holding two tables or subtables, a subtable a subfigure; one holding a "
         "table in a table's cell is left",
         lambda: table_shapes.count("\\begin{figure}\\hyperref[TEXTBOOKIMPROVERCOUNTER:"
                                    "tablefloat]{}") == 3
         and "\\begin{subfigure}{2in}" in table_shapes and "subtable" not in table_shapes
         and "\\begin{table}\\begin{tabular}{l}\\begin{tabular}" in table_shapes),
        ("the counting letters the appendix package's appendices and gives the numbers back "
         "after them, numbers a subfigure the obsolete subfigure package's way, and gives "
         "a theorem's title its number",
         lambda: counted == ["1", "1.1(a)", "A", "2"] and theorem_title == "1"),
        ("subfig's \\subfloat is a subfigure, its caption kept",
         lambda: subfloat == "\\begin{subfigure}{\\linewidth}X\\label{a}\\caption{Cap}"
                             "\\end{subfigure}"),
        ("a reference command's name is cleveref's or hyperref's, the book's own and "
         "cleveref's options first, a name hyperref falls back to too, and an appendix's; "
         "a theorem sharing another's counter has its own environment's name",
         lambda: names_given == ["Figure", "thm.", "Thm.", "Lemma", "Lemmata", "section",
                                 "eqs.", "Section", "Thm", "Appendix", "subsection", None,
                                 "Lemma", None]),
        ("a mix of a color of xcolor's svgnames or x11names is read, xcolor's own files "
         "giving the values, the last set the book loads winning a name two sets have",
         lambda: set_mixes == [(0.5, 0.5, 0.75), (0.53, 0.73, 1.0), (0.5, 0.468, 0.43)]
         if set_mixes is not None else skip("no kpsewhich to find xcolor's files")),
        ("the names a book sets are read: cleveref's options, \\crefname and \\Crefname, "
         "an \\autoref name, \\S as the character, and a name hyperref falls back to",
         lambda: book_names.get("capitalise") and book_names.get("noabbrev")
         and book_names["cref"] == {"thm": ("thm.", "thms.")}
         and book_names["Cref"] == {"lem": ("Lemma", "Lemmata")}
         and book_names["autoref"] == {"section": "\u00a7"}
         and book_names["name"].get("thm") == "Thm"),
        ("\\autoref and cleveref's commands are \\ref-s with the command in the key, outside "
         "formulas and comments, \\crefrange's two keys as one list",
         lambda: commands == "\\ref{TEXTBOOKIMPROVERREF:cref:a, b} "
         "\\ref{TEXTBOOKIMPROVERREF:crefrange:c,d} $\\cref{e}$ % \\cref{f}\n"),
        ("a theorem counts with the counter \\newtheorem gives it, within a section or a "
         "shared one, a starred one with none; a chapter's look isn't a chapter",
         lambda: theorem_setup["theorem_counters"] == {"thm": "thm", "lem": "thm", "rem": None}
         and theorem_setup["formats"]["thm"] == "\\thesection.\\arabic{thm}"
         and theorem_setup["resets"]["thm"] == "section" and not theorem_setup["chapters"]),
        ("the PDF filter leaves a numbered formula's number to LaTeX, its labels in its TeX "
         "for a reference in a formula and before it for the links, puts back the "
         "subequations a formula was in, and sets an eqnarray's count and form before it",
         lambda: "\\begin{equation}\n\\label{x}\nE\n \\tag{1.1}\\end{equation}" in eq_latex
         and eq_latex.count("\\label{x}") == 2 and "(9.9)" not in eq_latex
         and "\\begin{subequations}\\label{s}\n\\begin{align}" in eq_latex
         and "\\gdef\\theequation{2.\\arabic{equation}}\\setcounter{equation}{4}"
             "\\begin{eqnarray}" in eq_latex
         and "\\end{eqnarray}\\global\\let\\theequation\\oerTheEquation" in eq_latex),
        ("an EPUB chapter's title is its heading's text, a backslash in it as it is and a "
         "formula without its TeX", lambda: epub_title == "The \\pmb key and t"),
        ("a heading out of a division in another language takes its language; one in a "
         "theorem's division stays there",
         lambda: hoisted_count == 1 and [b["t"] for b in hoisted] == ["Header", "Div", "Div"]
         and hoisted[0]["c"][1][2] == [["lang", "fr"]]
         and hoisted[1]["c"][0][2] == [["lang", "fr"]]
         and hoisted[2]["c"][1][0]["t"] == "Header"),
        ("the counting numbers a formula's rows as LaTeX does, writes each number as the "
         "row's \\tag, and gives \\eqref the number in parentheses",
         lambda: "a \\\\label{p} \\\\tag{1.1}\\\\\\\\" in eq_text
         and "\\\\tag{1.2}" not in eq_text and eq_links == [[{"t": "Str", "c": "(1.1)"}]]
         and eq_counts == {"equation_numbers": 1}),
        ("a display formula's rows are as LaTeX numbers them: a last \\\\ makes one, a "
         "length after one is no row, though a bracket after it is, a nested "
         "environment's rows and a group's aren't "
         "the formula's, alignat's columns aren't its text, and multline is one",
         lambda: rows == [
             (False, [("a &= b", []), ("c &= d", []), ("", [])]),
             (False, [("p", []), ("[q]", [])]),
             (False, [("\\begin{cases} a \\\\ b \\end{cases}", []),
                      ("{x \\\\ y} \\label{k}", [("label", "k")])]),
             (False, [("a &= b \\nonumber", [("nonumber", None)])]),
             (True, [("m \\\\ n \\tag{q}", [("tag", "q")])])]),
        ("a preamble's layout is Pandoc's variables: its class's type size and paper, the "
         "sides it chooses, geometry's options, its line spacing, and indented paragraphs "
         "unless parskip or a \\parindent of zero says otherwise; an option's comment is "
         "no part of it, and a setting an environment, a command, or a hook makes isn't the "
         "page's, but one at \\begin{document} is",
         lambda: layouts == [
             {"fontsize": "11pt", "geometry": ["margin=1in"]},
             {"fontsize": "10pt", "classoption": ["openany"], "indent": True},
             {"fontsize": "12pt", "papersize": "a4", "geometry": ["total={6in,8in}", "top=1in"],
              "linestretch": "1.25"},
             {"papersize": "a4", "classoption": ["twoside"]},
             {"fontsize": "12pt", "classoption": ["twoside"], "geometry": ["left=1in", "right=1in"],
              "linestretch": "1.25", "indent": True},
             {}, {}]),
        ("wasysym's symbols are Unicode in a book with no formula too, drawn by the "
         "OpenType fonts and their fallback; with formulas, unicode-math is loaded",
         lambda: no_math == {"math_stand_in": "wasysym", "text_fonts": 1}
         and "\\usepackage{fontspec}" in no_math_block
         and "unicode-math" not in no_math_block and "fallback" in no_math_block
         and with_math.get("math_stand_in") == "wasysym" and with_math.get("math") == 1
         and "\\usepackage{unicode-math}" in math_block),
        ("a figure's lossless raster stays lossless when its fonts are embedded", lossless),
        ("titlesec's stand-in builds beside fancyhdr's page styles", titlesec_with_fancyhdr),
        ("and with titlesec's pagestyles option, titleps is loaded at once, as titlesec "
         "loads it", titlesec_pagestyles),
        ("a package tagging can't take is replaced, the one another's stand-in serves too, "
         "each load made to define its commands",
         lambda: shims == ["titlesec", "enumerate", "soulutf8"]
         and "\\disable@package@load{titlesec}{\\csname __oer_shim_titlesec:\\endcsname}" in shim_block
         and "\\disable@package@load{soulutf8}{\\csname __oer_shim_soul:\\endcsname}" in shim_block
         and shim_block.count("\\cs_new_protected:Npn \\__oer_shim_soul:") == 1
         and "mdframed" not in shim_block and "% titlesec, enumerate, soulutf8. None is" in shim_block),
        ("an image macro's alt-text argument of paragraphs runs them on, which "
         "\\includegraphics can take, a comment before a break ending where it did; one "
         "paragraph is left",
         lambda: flat_alt == "\\fig[A first paragraph.\nA second one,\na third]{sq}\\fig[One]{sq}\n"
         and commented_alt == "\\fig[A first. % to reword\nA second.]{sq}\n"
         and flat_counts.get("alt_paragraphs") == 1),
        ("LaTeX's first error is found when its file's name has spaces",
         lambda: latexbuild.first_errors(log)
         and "titlesec Error" in latexbuild.first_errors(log)[0]
         and "titlesec can't build" in " ".join(latexbuild.failure_advice(log))),
        ("an enumerated item's number is worked out as LaTeX would",
         lambda: latexsource.item_labels(nested) == {
             "a": "1", "b": "2b", "c": "2(b)iii", "d": "(b)", "e": "3", "f": "IV."}),
        ("a column type is written out, inside a repeat and inside another type",
         lambda: latexsource.expand_columns("lY*{2}{R{1in}}", types)
         == "l>{\\raggedleft\\arraybackslash}p{1cm}*{2}{>{\\raggedleft\\arraybackslash}p{1in}}"),
        ("enumitem's settings the emulation lacks are counted",
         lambda: settings == {"leftmargin=*": 2, "labelindent": 1, "resume": 1}),
        ("a document that includes nothing opens in the main matter, whatever follows",
         lambda: latexsource.book_outline("Text.\n\\appendix\n\\section{A}")[1] == "main"
         and latexsource.book_outline("\\appendix\n\\section{A}")[1] == "appendix"),
        ("the book's definitions are read in LaTeX's order: a file where it's \\input, "
         "\\def and \\newcommand as they come, \\providecommand only for a name not "
         "yet defined",
         lambda: {n: m["arguments"] for n, m in latexsource.image_macros(
             [("m.tex", ordered), ("defs.tex", "\\renewcommand{\\fig}[2]{\\includegraphics"
                                              "[width=#2]{#1}}\n")])[0].items()}
         == {"fig": 3, "newfig": 1}),
        ("a book's own \\DocumentMetadata without tagging gets it, and the standard",
         lambda: own_metadata.startswith("\\DocumentMetadata{pdfversion=2.0, lang=en, "
                                         "tagging=on, pdfstandard=ua-2}\n")),
        ("a moving argument is found by each command's arguments: \\captionof's caption, "
         "not its type, and a caption's short form",
         lambda: [moving[a:b] for a, b in texremediate._moving_spans(moving, [])]
         == ["Short", "Long", "T", "i"]),
        ("an environment the book defines is the commands LaTeX makes of it, called "
         "alone as LaTeX allows", lambda: envs["a.tex"].startswith(
             "\\newcommand{\\var}[1]{\\texttt{#1}}\\newcommand{\\endvar}{}")
         and "\\var {x}\\endvar  and \\var{y}." in envs["a.tex"]),
        ("\\begingroup and the \\endgroup at its depth are braces, after an italic "
         "correction; a pair macros split, one in a formula, and one after \\\\ are left",
         lambda: grouped.startswith("{\\Large \\/{ A\\par }}")
         and grouped.endswith("{\\begingroup}\\newcommand{\\e}{\\endgroup}\n"
                              "$\\begingroup x\\endgroup$ A\\\\begingroup B \\endgroup")),
        ("a group or a number after a command the reader takes whole is kept apart from "
         "it, and nothing in a formula, a comment, or after a line break or a space",
         lambda: kept == "\\noindent \\/{A}\\hspace*{1em}\\/{B}\\raisebox{1pt}[2pt]{R}\\/{C}"
         "\\selectfont \\/1.1 \\noindent\n\\/42 \\vspace{1em} {D} $\\hspace{1em}{x}$ "
         "\\\\noindent{E} % \\noindent{F}\n\\noindent\n\n7"),
        ("titlesec's \\titleformat over several lines, a comment among them, is left out "
         "whole", lambda: titled == "A\nB"),
        ("an environment defined in another's codes, and LaTeX's own the book redefines, "
         "are left as they are, and read; the book's own redefined is a command",
         lambda: "\\begin{hint}think\\end{hint}\\endexercises" in nested_envs["a.tex"]
         and "\\begin{enumerate}\\item x\\end{enumerate}" in nested_envs["a.tex"]
         and "\\renewcommand{\\var}[1]{\\textbf{#1}}\\renewcommand{\\endvar}{}" in nested_envs["a.tex"]
         and re.search(r"Do it\. \(Hint: think\)\s+- x\s+y", nested_read) is not None),
        ("the book's colors are read in LaTeX's order, the last definition winning, one "
         "in a macro's body not at all, and its spans given them as CSS; a color in a "
         "model is CSS in the copy, but in a formula, a drawing, or a definition",
         lambda: "\\textcolor{oiB}{A} \\textcolor{rgb(0, 0, 255)}{M} $\\textcolor[rgb]{0,0,1}{x}$ "
         "\\begin{tikzpicture}\\node {\\textcolor[rgb]{0,0,1}{G}};" in colored["main.tex"]
         and "\\newcommand{\\blue}[1]{\\textcolor[rgb]{0,0,1}{#1}}" in colored["main.tex"]
         and color_order == ["\\definecolor{oiB}{rgb}{.337,.608,.741}",
                             "\\definecolor{oiB}{rgb}{0,0,0}"]
         and recolored == 2 and [p["c"][0][2][0][1] for p in spans]
         == ["color: rgb(0, 0, 0)", "background-color: rgb(0, 0, 0)", "color: red"]),
        ("a color CSS can't read as the book writes it is CSS: a \\colorlet's, a mix, a "
         "name of dvipsnames's, and a [named] definition; \\providecolor changes nothing "
         "defined, a name CSS has is left, and a color nothing defines is taken out",
         lambda: mixed_styles == ["color: rgb(170, 205, 222)", "color: rgb(128, 0, 0)",
                                  "color: rgb(184, 20, 11)", "color: rgb(255, 0, 0)",
                                  "color: rgb(86, 155, 189)", "color: Orchid", None,
                                  "color: rgb(170, 205, 222)"]
         and remixed == 7),
        ("the sample's probe finds each macro's formula by its mark, past one whose "
         "expansion breaks its paragraph", lambda: probed == {"worse"}),
        ("a counter stepped, set, or shown is marked where the reader keeps it, but not in "
         "a key, a formula, a comment, a drawing, or a \\the definition, nor a value it "
         "can't follow; and each style shows a counter as LaTeX does",
         lambda: marked == (
             "\\refstepcounter{eoce}\\hyperref[TEXTBOOKIMPROVERCOUNTER:refstepcounter:eoce]{}"
             "\\setcounter{chapter}{#1}\\hyperref[TEXTBOOKIMPROVERCOUNTER:setcounter:chapter:#1]{}"
             "\\addtocounter{x}{\\value{y}}"
             "\\hyperref[TEXTBOOKIMPROVERCOUNTER:addtocounter:x:\\value{y}]{}"
             "\\setcounter{z}{\\numexpr1}\\label{e_\\arabic{eoce}} "
             "\\hyperref[TEXTBOOKIMPROVERCOUNTER:the:section]{}\\thepage "
             "\\hyperref[TEXTBOOKIMPROVERCOUNTER:show:arabic:x]{}$\\arabic{x}$ % \\arabic{x}\n"
             "\\begin{tikzpicture}\\stepcounter{x}\\end{tikzpicture}"
             "\\renewcommand{\\theeoce}{\\arabic{eoce}}\\appendix"
             "\\hyperref[TEXTBOOKIMPROVERCOUNTER:division:appendix]{}")
         and [latexsource.counter_style(st, 14) for st in ("arabic", "roman", "Roman", "alph",
                                                            "Alph")]
         == ["14", "xiv", "XIV", "n", "N"]),
        ("a $ in a comment pairs with nothing, so a macro after it isn't counted as a "
         "formula's", lambda: latexsource.math_uses(
             ["Cost % 5$ more\n\\section{A} and $x$.\n"], ["section"]) == {"section": 0}),
        ("a line break with its space, \\\\[6mm], isn't taken for a display formula",
         lambda: [line_break[a:b] for a, b in latexsource.math_spans(line_break)]
         == ["\\[ y \\]"]),
        ("a book with formulas and no macro of its own has none a formula uses",
         lambda: no_macros == set()),
        ("a definition a formula uses is left as it is, and those its body uses: texmath "
         "reads them; one only text uses gets the groups' repairs",
         lambda: math_kept.startswith("\\newcommand{\\grp}[1]{\\begingroup #1\\endgroup}\n"
                                      "\\newcommand{\\hl}[1]{\\grp{#1}\\hspace{1em}{z}}\n"
                                      "\\newcommand{\\remark}[1]{\\noindent\\/{ #1}}")),
        ("titlesec's starred forms are left out with their own arguments",
         lambda: starred == "ABC"),
        ("a call's arguments are found past a comment between them, as TeX finds them",
         lambda: [a[0] for a in commented[0][3]] == ["a", "b"] if commented else False),
        ("a color in each of xcolor's models is CSS",
         lambda: latexsource.css_color("rgb", ".5,.5,.5") == "rgb(128, 128, 128)"
         and latexsource.css_color("HTML", "1E5F8C") == "rgb(30, 95, 140)"
         and latexsource.css_color("gray", "0") == "rgb(0, 0, 0)"
         and latexsource.css_color("cmyk", "0,1,1,0") == "rgb(255, 0, 0)"
         and latexsource.css_color("named", "x") is None),
        ("a key with a space, or a macro's {} in it, is an id without, read through the "
         "book's own macro too, numbered and linked; an empty label is no id",
         lambda: keyed_read == ["#US-Airports", "#US-Airports", "#edwardSatBelow1300"]
         and keyed_ids == ["US-Airports", "edwardSatBelow1300", ""]
         and keyed_numbers == ["1", "1"]),
        ("\\subfigure is subcaption's environment, its caption the environment's",
         lambda: latexsource.subfigures("\\subfigure[Left]{X\\label{a}}", {})
         == "\\begin{subfigure}{\\linewidth}X\\label{a}\\caption{Left}\\end{subfigure}"),
        ("an \\author's names: a line set apart under a name is its affiliation, a "
         "\\thanks no part of it, and with every line set alike each is given",
         lambda: authors("David Diez \\\\ \\small\\emph{Data Scientist} \\\\[6mm]\n"
                         "Mine Rundel \\\\ \\small\\emph{Duke University} \\\\")
         == ["David Diez", "Mine Rundel"]
         and authors("A \\and B") == ["A", "B"]
         and authors("\\textbf{Ann Lee} \\\\ State University") == ["Ann Lee"]
         and authors("Ann Lee\\thanks{Funded by a grant.} \\\\ State University")
         == ["Ann Lee", "State University"]),
        ("a brace nothing closes, and one that closes nothing, are found, a \\{ and a "
         "comment's not counted", lambda: latexsource.unbalanced_braces("a{b}{c \\{ % {\n} }")
         == ([], [16]) and latexsource.unbalanced_braces("x{ {y}") == ([1], [])),
        ("a macro without arguments in a file's name is its value at the call, when that "
         "is plain text", lambda: latexsource.with_values(
             "\\chapterfolder/figures/#3", {"chapterfolder": "ch_one"}) == "ch_one/figures/#3"
         and latexsource.with_values("\\d/x", {"d": "\\textbf{y}"}) == "\\d/x"),
        ("an unused argument fewer than half the calls give a phrase in isn't offered as "
         "alt text", lambda: latexsource.alt_arguments(list(alt_calls.items())) == []),
        ("a comment in a package list isn't a package",
         lambda: latexsource.package_names("amsmath,\n %tocloft,\n hyperref")
         == ["amsmath", "hyperref"]),
        ("a data table in a box is set back to a table before its header declaration",
         lambda: texremediate.DATA_OPEN + "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/"
         "header-rows={1}}\\fi\\begin{tabular}{lr}" in boxed["b.tex"]
         and "\\end{tabular}}}\n\\end{tabular}}" in boxed["b.tex"]),
    ]


# A book made the way OpenIntro Statistics is: its chapters \include-d by a
# macro of its own, defined in a style file the preamble \include-s after
# the master calls it; its images behind macros whose file is
# \chapterfolder/figures/#3/#3, \chapterfolder set at each chapter's start,
# and whose first argument, which the macros don't use, is the alt text;
# environments called as commands and wrapping a list in braces; titlesec's
# settings over several lines; \begingroup after a size command; a color of
# its own; \nameref; \subfigure; a label with a space; a definitions-only
# file \include-d in the body; an empty \chapter*{} to start a page.
CUSTOM_FILES = {
    "main.tex": r"""\documentclass[11pt]{book}
\usepackage[margin=1in]{geometry}
\usepackage{graphicx}
\usepackage[dvipsnames]{xcolor}
\usepackage{bookcolors}
\usepackage{
  amsmath,
  %tocloft,
  hyperref}
\include{style/style}
\author{Ann Lee \\
\small\emph{Statistician}\\
\small\emph{A College} \\[6mm]
Bo Chen \\
\small\emph{A University} \\
}
\begin{document}
\include{front/copyright}
\begingroup
\include{style/headers}
\includechapter{1}{ch_one}
\includechapter{2}{ch_two}
\include{ch_two/TeX/more}
\endgroup
\include{front/solutions}
\begin{appendices}
\include{front/tables}
\end{appendices}
\end{document}
""",
    "style/style.tex": r"""\definecolor{oiB}{rgb}{.337,.608,.741}
\newcommand\includechapter[2]{
  \setcounter{chapter}{#1}
  \addtocounter{chapter}{-1}
  \include{#2/TeX/#2}
  \newpage\input{#2/TeX/review}
  }
\newcommand{\Figure}[3][]{\includegraphics[width=#2\textwidth]{\chapterfolder/figures/#3/#3}}
\newcommand{\Figures}[4][]{\includegraphics[width=#2\textwidth]{\chapterfolder/figures/#3/#4}}
\newcommand{\chapterfolder}{}
\newenvironment{var}[1]{\texttt{#1}}{}
\newenvironment{parts}{
\begin{enumerate}
\setlength{\itemsep}{0mm}}
{\end{enumerate}}
\newcommand{\qt}[1]{\textcolor{oiB}{\textbf{#1}}}
\newcommand{\remark}[1]{\par\noindent\begingroup\small\textbf{Remark.} #1\endgroup\par}
\newcommand{\highlightwith}[2]{\definecolor{hl}{rgb}{#1}\textcolor{hl}{#2}}
\newcommand{\hlx}[1]{\textcolor{oiB}{#1}}
\newcommand{\gap}[1]{#1\hspace{1em}{}}
\newcommand{\grp}[1]{\begingroup #1\endgroup}
\colorlet{brandlight}{brand!20}
\newcommand{\secref}[1]{Section~\ref{#1}}
\newcounter{eoce}[chapter]
\renewcommand{\theeoce}
    {\arabic{chapter}.\arabic{eoce}}
\newcounter{alwaysTwo}
\setcounter{alwaysTwo}{2}
\newcounter{eocesolch}
\setcounter{eocesolch}{0}
\newcounter{eocesol}[eocesolch]
\renewcommand{\theeocesol}{\arabic{eocesolch}.\arabic{eocesol}}
\newcommand{\eoce}[1]{\refstepcounter{eoce}\noindent\textbf{\ref{eoce_sol_\arabic{chapter}_\arabic{eoce}}\label{eoce_\arabic{chapter}_\arabic{eoce}}}\hspace{2mm}#1}
\newcommand{\eocesolch}[1]{\refstepcounter{eocesolch}\noindent\textbf{\arabic{eocesolch}\hspace{2mm}#1}}
\newcommand{\eocesolution}[1]{\refstepcounter{eocesol}\noindent\textbf{\ref{eoce_\arabic{eocesolch}_\arabic{eocesol}}\label{eoce_sol_\arabic{eocesolch}_\arabic{eocesol}}}\hspace{2mm}{\small#1}\makebox[0pt]{\refstepcounter{eocesol}\label{eoce_sol_\arabic{eocesolch}_\arabic{eocesol}}}}
\newcommand{\strutx}[1]{\rule{0pt}{2ex}#1\leavevmode}
\newenvironment{wrap}{\leavevmode}{\leavevmode}
\newcommand{\Figuress}[4][]{%
  \includegraphics[width=#2]{\chapterfolder/figures/#3/#4}%
}
\newcommand{\eocesol}[1]{\noindent\textbf{\color{oiB}{\hypersetup{linkcolor=oiB}{\fontfamily{phv}\selectfont 1.1}}}\hspace{2mm}{\small#1}}
""",
    "style/headers.tex": r"""\titleformat{\chapter}
    {}
    {Chapter~\thechapter}% \quad #1}
    {1em}
    {}
    []
\titlespacing{\chapter}
   {0pt}% left
   {0pt}% before sep
   {\baselineskip}% after sep
\newcommand{\chapterintro}[1]{
  {\Large
  \begingroup
  \noindent #1\vspace{7mm}\par
  \endgroup}}
""",
    "front/copyright.tex": "\\chapter*{}\nCopyright 2026, the authors.\n",
    "ch_one/TeX/ch_one.tex": r"""\chapter{First chapter}\label{ch_one}
\renewcommand{\chapterfolder}{ch_one}
\chapterintro{An introduction to the first chapter.}
\section{Data basics}\label{sec:data}
A variable \var{height} is measured. \qt{A question}.

\subsection{Spread\label{sec:spread}}
The spread.

\Figure[A red square standing for the data]{0.5}{square}

\begin{figure}
\subfigure[]{\Figures[A blue circle, the first panel]{0.4}{panels}{circle}
\label{panel_a}}
\caption{Panels}\label{fig:panels}
\end{figure}
See Figure~\ref{panel_a} and Section~\nameref{sec:data}.

\noindent\begin{minipage}{0.4\textwidth}
{\raggedright\begin{parts}
\item The first part
\end{parts}\vspace{7mm}}
\end{minipage}


{\input{ch_one/TeX/extra.tex}}

The airports\label{US Airports} are in Section~\ref{US Airports}, as \secref{US Airports} says.
\newcommand{\actmean}{21}
The mean is $\actmean$, and a formula in the book's color: ${\color{oiB} x + y}$,
and another: $\textcolor{oiB}{\bar{x}} = 21$, one by a macro: $\hlx{y} = 2$, and a
formula whose macro a repair for text mustn't touch: $\gap{x} = 1$. A strut texmath
can't read: $\strutx{z}$, and an environment in a formula: $\begin{wrap}w\end{wrap}$.
Formulas as OpenIntro writes them: $P(\text{rolling a \texttt{1}})$,
$\texttt{income\_\hspace{0.03cm}{}ver}_{\texttt{verified}}$,
$P(\text{\underline{\color{black}mammogram$^+$} and has BC})$,
$s = 5.5 \hfill R^2 = 70\%$, $\pmb{\MakeLowercase{t}}$, and
\begin{align*}
x = 1 \index{x}\vspace{2mm}
\end{align*}
and one whose index entry has a line of its own, after a comment, which a PDF
mustn't take for a paragraph's end once the entry's gone:
\begin{align*}
y = 2
%z = 3
\index{y}
\end{align*}
A formula the next chapter numbers: \eqref{eq:energy}.
A \colorbox{oiB!20}{tinted} word, a \textcolor{BrickRed}{brick red} one, and a formula
in it: ${\color{BrickRed} z}$. A group in a formula's macro: $\grp{x} + 1$.
Struts texmath doesn't know: \fbox{$\mathstrut$Ex} and $\vphantom{(}x\smash{y}\hphantom{z}$.
Space between words: \fbox{Ex}\hspace{2mm}apart, Bee\quad Cee, Dee\hfill Eee, and a
sliver in a name, \texttt{sex\_\hspace{0.3mm}male}, and less than none: Gee\hspace{-1pt}Hee.
""",
    "ch_one/TeX/extra.tex": "\\begin{parts}\n\\item An extra part\n\\end{parts}\n",
    "ch_one/TeX/review.tex": "\\section{Review}\nThe review of chapter one.\n\n"
                             "\\Figure[A green triangle for the review]{0.3}{triangle}\n\n"
                             "\\remark{The variance is never negative.}\n"
                             "\\centering \\begingroup\\itshape A centered italic line.\\endgroup\n\n"
                             "\\eocesol{The solution to the first exercise.}\n\n"
                             "\\noindent{\\large \\bf Exercises --- \\thesection\\ }\n\n"
                             "\\eoce{The first exercise.}\n\n\\eoce{The second exercise.}\n",
    # An alt text too long for the pages' liking, of two paragraphs, as
    # OpenIntro writes some.
    # Its chapter's title set in a framed box, as OpenIntro sets each.
    "ch_two/TeX/ch_two.tex": "\\begin{mdframed}\n\\chapter{Second chapter}\nIn a frame.\n"
                             "\\end{mdframed}\n\\renewcommand{\\chapterfolder}{ch_two}\n"
                             "\\Figure[A gray star in chapter two, drawn with five points of equal "
                             "length.\n\nIts center filled, the one sample this chapter comes "
                             "back to]{0.5}{star}\n\n"
                             "\\Figuress[A purple hexagon with six equal sides]{2cm}{hexagon}{hexagon}\n\n"
                             "\\includegraphics[alt={The hexagon again, named in capitals}]"
                             "{ch_two/figures/hexagon/HEXAGON.png}\n\n"
                             # Formulas LaTeX numbers, and references to them.
                             "Energy:\n\\begin{equation}\\label{eq:energy}\nE = mc^2\n"
                             "\\end{equation}\nthree rows, the second unnumbered:\n"
                             "\\begin{align}\na &= b \\label{eq:row-one}\\\\\n"
                             "c &= d \\nonumber \\\\\ne &= f \\label{eq:row-three}\n"
                             "\\end{align}\none starred:\n\\begin{equation*}\nx = 0\n"
                             "\\end{equation*}\none tagged:\n\\begin{equation}\n"
                             "y = 1 \\tag{$\\star$}\\label{eq:star}\n\\end{equation}\n"
                             "and a system:\n\\begin{subequations}\\label{eq:system}\n"
                             "\\begin{align}\nu &= v \\label{eq:system-a}\\\\\n"
                             "w &= z \\label{eq:system-b}\n\\end{align}\n\\end{subequations}\n"
                             "See \\eqref{eq:energy}, row \\ref{eq:row-three}, "
                             "\\eqref{eq:star}, the system \\eqref{eq:system}, and its "
                             "second line \\ref{eq:system-b}.\n\n"
                             # An eqnarray, which takes no \\tag; subequations holding two
                             # environments and a label after them; breqn's dmath, whose
                             # environment the reader drops; a display formula with a tag;
                             # and a reference inside a formula.
                             "Rows of an eqnarray:\n\\begin{eqnarray}\na &=& b \\label{eq:ea}"
                             "\\\\\nc &=& d \\nonumber\\\\\ne &=& f \\label{eq:ef}\n"
                             "\\end{eqnarray}\nTwo in a system:\n\\begin{subequations}"
                             "\\label{eq:pair}\n\\begin{equation} p = q \\label{eq:pair-a}"
                             "\\end{equation}\nand\n\\begin{equation} r = s \\label{eq:pair-b}"
                             "\\end{equation}\\label{eq:pair-after}\n\\end{subequations}\n"
                             "A long one:\n\\begin{dmath}\\label{eq:long} y = mx + b"
                             "\\end{dmath}\nTagged alone: \\[ w = 1 \\tag{$\\dagger$}"
                             "\\label{eq:dagger} \\]\nIn a formula: $\\text{by \\eqref{eq:energy}}$.\n"
                             "See \\eqref{eq:ea}, \\eqref{eq:ef}, \\eqref{eq:pair-b}, "
                             "\\eqref{eq:pair-after}, \\eqref{eq:long}, \\eqref{eq:dagger}, and "
                             "\\eqref{eq:app}.\n\n"
                             # A color made from one a style file of the book's own defines.
                             "A \\textcolor{brandlight}{branded} word.\n",
    "ch_two/TeX/review.tex": "\\section{Review two}\nAs \\nameref{ch_one} said, and Figure~"
                             "\\ref{fig:panels} there shows.\n\n\\section{The $t$ distribution}\n"
                             "A heading with a formula in it. See \\nameref{sec:named}, "
                             "\\nameref{fig:panels}, and \\nameref{sec:spread}.\n\n"
                             "\\section{\\nameref{sec:data}}\\label{sec:named}\nNamed.\n\n"
                             "\\eoce{An exercise of chapter two.}\n\n"
                             "A \\fbox{framed phrase} and a table sized to fit, and two "
                             "is \\arabic{alwaysTwo}:\n\n"
                             "\\resizebox{0.5\\textwidth}{!}{\\begin{tabular}{|l|l|}\\hline "
                             "Fitted & Cells \\\\ \\hline\\end{tabular}}\n",
    # A file continuing chapter two, as OpenIntro's t-table continues its
    # tables' chapter: a section with no chapter of its own.
    "ch_two/TeX/more.tex": "\\section{More of chapter two}\nMore.\n\n\\subsection{A part of it}\n"
                           "Its part.\n",
    "front/solutions.tex": "\\chapter*{Solutions}\n\\eocesolch{First chapter}\n\n"
                           "\\eocesolution{The first exercise's solution.}\n\n"
                           "\\eocesolch{Second chapter}\n\n"
                           "\\eocesolution{Chapter two's exercise's solution.}\n",
    "front/tables.tex": "\\chapter{Tables of $\\pmb{t}$}\n\\begin{equation}\\label{eq:app} t = 1"
                        "\\end{equation}\n",
    "bookcolors.sty": "\\ProvidesPackage{bookcolors}\n\\definecolor{brand}{rgb}{.1,.3,.6}\n",
    "LICENSE.md": "# License\n\nCC BY-SA 3.0.\n",
    "project.yaml": "project:\n  identifier: org.example.custom\n  title: A Custom Book\n",
    "conversion.yaml": "targets:\n  html:\n    format: html\n",
}


def word_formulas(path):
    """In the customized book's Word file, each of chapter two's numbered
    formulas is a paragraph of its own, a display formula, and the next
    paragraph begins with its number."""
    import zipfile
    if not os.path.exists(path):
        return False
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paragraphs = [(p, "".join(re.findall(r"<(?:w|m):t[^>]*>([^<]*)</(?:w|m):t>", p)))
                  for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
    formulas = [i for i, (p, _) in enumerate(paragraphs) if "<m:oMathPara" in p]
    after = [paragraphs[i + 1][1] for i in formulas if i + 1 < len(paragraphs)]
    return len(formulas) >= 5 and all(not re.search(r"<w:r>|<w:r ", paragraphs[i][0])
                                      for i in formulas) \
        and any(a.startswith("(2.1)") for a in after) \
        and any(a.startswith("(2.2) (2.3)") for a in after) \
        and any(a.startswith("(2.4a) (2.4b)") for a in after)


def pdf_numbers(work, said):
    """The customized book's PDF from the pages sets the numbers the pages
    give its formulas, by their \\tag, subequations' rows by letter, and
    the references' text, each label found."""
    try:
        import pypdf
    except ImportError:
        return skip("no pypdf to read the PDF")
    text = " ".join(" ".join((p.extract_text() or "").split()) for p in pypdf.PdfReader(
        os.path.join(work, "pdf", "org.example.custom.pdf")).pages)
    # An eqnarray's numbers twice: beside its rows, and in the references to
    # them, which alone would hold them whatever LaTeX numbered the rows.
    return all(n in text for n in ("(2.1)", "(2.2)", "(2.3)", "(2.4a)", "(2.4b)", "(2.5)",
                                   "(2.6)", "(2.7a)", "(2.7b)", "(2.8)", "(A.1)", "by (2.1)")) \
        and text.count("(2.5)") >= 2 and text.count("(2.6)") >= 2 \
        and re.search(r"See \(2\.1\), row 2\.3, \(.{1,3}\), the system \(2\.4\), and its "
                      r"second line 2\.4b", text) and "multiply defined" not in said \
        and "Hyper reference" not in said


def page_layout_kept(work, said):
    """The PDF from the pages has the 11pt type and inch margins the
    customized book's preamble gives, its paragraphs indented: the run says
    so, and a paragraph's words are drawn at 11pt's 10.95pt (10.91 of the
    PDF's points), beginning an inch from the edge."""
    if "The LaTeX book's own layout, from its preamble: 11pt type; geometry's " \
            "margin=1in; xcolor's dvipsnames colors; indented paragraphs." not in said:
        return False
    try:
        import pypdf
    except ImportError:
        return skip("no pypdf to read the PDF")
    import math
    found = []
    for page in pypdf.PdfReader(os.path.join(work, "pdf", "org.example.custom.pdf")).pages:
        def visit(text, cm, tm, font, size):
            if "The spread" in text:
                found.append((size * math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1]),
                              tm[4] * cm[0] + cm[4]))
        page.extract_text(visitor_text=visit)
    return bool(found) and all(abs(size - 10.91) < 0.05 and abs(x - 72) < 1
                               for size, x in found)


def case_customized(work):
    """A book made its own way, as OpenIntro Statistics is: read whole, a
    page per chapter, its images found and its constructs read; the sample
    suggesting its alt-text argument be passed on, and, adopted, the pages
    and the source target's copy carrying it; a stray brace named."""
    for name, text in CUSTOM_FILES.items():
        os.makedirs(os.path.join(work, os.path.dirname(name)), exist_ok=True)
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    for path, rgb in (("ch_one/figures/square/square.png", (200, 0, 0)),
                      ("ch_one/figures/panels/circle.png", (0, 0, 200)),
                      ("ch_one/figures/triangle/triangle.png", (0, 150, 0)),
                      ("ch_two/figures/star/star.png", (90, 90, 90)),
                      ("ch_two/figures/hexagon/hexagon.png", (120, 0, 120))):
        os.makedirs(os.path.dirname(os.path.join(work, path)), exist_ok=True)
        png(os.path.join(work, path), rgb)
    first = convert(work)
    first_said = first.stdout + first.stderr
    contents_sample = read(work, "contents-sample.yaml") \
        if os.path.exists(os.path.join(work, "contents-sample.yaml")) else ""
    sample_path = os.path.join(work, "latex-conversion-macros-sample.tex")
    sample = read(work, "latex-conversion-macros-sample.tex") \
        if os.path.exists(sample_path) else ""
    first_one = read(work, "html", "ch_one.html") \
        if os.path.exists(os.path.join(work, "html", "ch_one.html")) else ""
    # The sample's definitions adopted, as a person would, a decision made
    # for the review's image, and a source target with tagging on.
    adopted, taking = [], False
    for line in sample.splitlines():
        taking = taking or line.startswith("% \\renewcommand{\\Figure")
        if taking and not line.strip():
            taking = False
        elif taking:
            adopted.append(line[2:])
    adopted = "\n".join(adopted)
    with open(os.path.join(work, "latex-conversion-macros.tex"), "w") as fh:
        fh.write(adopted + "\n")
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nch_one/figures/triangle/triangle.png,\"A triangle, from the sidecar\"\n")
    pdf = bool(shutil.which("lualatex"))
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  tagged:\n    format: source\n    tagging: \"on\"\n"
                 + "  epub:\n    format: epub3\n  docx:\n    format: docx\n"
                 + ("  pdf:\n    format: pdf\n    pdf:\n      from: pages\n" if pdf else ""))
    second = convert(work)
    said = second.stdout + second.stderr

    def page(name):
        path = os.path.join(work, "html", name)
        return read(work, "html", name) if os.path.exists(path) else ""
    one, two = page("ch_one.html"), page("ch_two.html")
    copyright_page = page("copyright.html")
    copy_path = os.path.join(work, "tagged", "ch_one", "TeX", "review.tex")
    review_copy = read(work, "tagged", "ch_one", "TeX", "review.tex") \
        if os.path.exists(copy_path) else ""
    main_copy = read(work, "tagged", "main.tex") \
        if os.path.exists(os.path.join(work, "tagged", "main.tex")) else ""
    # A brace the book never closes, in a style file the preamble reads.
    broken = os.path.join(work, "..", os.path.basename(work) + "-brace")
    os.makedirs(os.path.join(broken, "style"))
    with open(os.path.join(broken, "main.tex"), "w") as fh:
        fh.write("\\documentclass{book}\n\\input{style/style}\n\\begin{document}\n"
                 "Text.\n\\end{document}\n")
    with open(os.path.join(broken, "style", "style.tex"), "w") as fh:
        fh.write("\\newcommand{\\a}{A}\n{\n\\newcommand{\\b}{B}\n")
    with open(os.path.join(broken, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    stopped = convert(broken)
    told = stopped.stdout + stopped.stderr

    def epub_links():
        import zipfile
        path = os.path.join(work, "epub", "org.example.custom.epub")
        if not os.path.exists(path):
            return False
        with zipfile.ZipFile(path) as z:
            texts = {n: z.read(n).decode("utf-8") for n in z.namelist()
                     if n.endswith((".xhtml", ".opf"))}
        holder = [n for n, t in texts.items() if '<figure id="page-ch_one--fig:panels"' in t]
        linking = [t for n, t in texts.items() if "fig:panels" in t and n not in holder]
        opf = next((t for n, t in texts.items() if n.endswith(".opf")), "")
        return holder and linking and all(
            re.search(r'href="%s#page-ch_one--fig:panels"' % re.escape(os.path.basename(holder[0])), t)
            for t in linking) and re.search(r'properties="nav mathml"', opf)

    def epub_titles():
        """Each of the EPUB's chapter files is titled by its heading's text, a
        formula's as text, not its TeX (the appendix's title holds one)."""
        import zipfile
        path = os.path.join(work, "epub", "org.example.custom.epub")
        if not os.path.exists(path):
            return False
        with zipfile.ZipFile(path) as z:
            titles = [m.group(1) for n in z.namelist() if n.endswith(".xhtml")
                      for m in re.finditer(r"<title>(.*?)</title>", z.read(n).decode("utf-8"),
                                           re.S)]
        return any(t.startswith("Tables of") for t in titles) \
            and not any("\\" in t for t in titles)

    def ids_valid():
        ids = re.findall(r'\sid="([^"]*)"', one)
        return ids and all(i and not re.search(r"[\s{}]", i) for i in ids) \
            and 'id="US-Airports"' in one
    return [
        ("chapters \\include-d by the book's own macro are pages, each with its review, "
         "and a file of definitions \\include-d in the body is none",
         lambda: "The review of chapter one." in one and "Review two" in two
         and not os.path.exists(os.path.join(work, "html", "headers.html"))
         and "have nothing to read" in said and "headers" in said),
        ("an image behind a macro whose file is \\chapterfolder/figures/#3/#3, the folder "
         "set at each chapter's start, or made of two arguments, is found",
         lambda: first.returncode == 0
         and re.search(r'<img[^>]*src="ch_one/figures/square/square\.png"', first_one)
         and re.search(r'<img[^>]*src="ch_one/figures/panels/circle\.png"', first_one)
         and re.search(r'<img[^>]*src="ch_one/figures/triangle/triangle\.png"', first_one)
         and re.search(r'<img[^>]*src="ch_two/figures/star/star\.png"', two)),
        ("the sample suggests passing on the argument the image macros don't use, which "
         "their calls give a phrase in",
         lambda: "% \\renewcommand{\\Figure}[3][]{\\includegraphics[alt={#1},width=#2\\textwidth]"
         "{\\chapterfolder/figures/#3/#3}}" in sample
         and "% \\renewcommand{\\Figures}[4][]" in sample
         and "as alt text might be" in first_said),
        ("a macro the book defines in its text, a formula uses, and texmath reads isn't in "
         "the sample", lambda: sample and "\\actmean" not in sample),
        ("adopted, each image has its alt text on the pages",
         lambda: re.search(r'<img[^>]*alt="A red square standing for the data"', one)
         and re.search(r'<img[^>]*alt="A blue circle, the first panel"', one)
         and re.search(r'<img[^>]*alt="A gray star in chapter two, drawn', two)),
        ("a row of the alt text report whose current alt text is two paragraphs is one "
         "row, the paragraphs run on as LaTeX reads them, its image named, and every row "
         "names an image", lambda: (lambda rows: any(
             row.get("Image") == "ch_two/figures/star/star.png"
             and row.get("Reason", "").startswith("too long")
             and "equal length. Its center filled" in row.get("CurrentAlt", "")
             for row in rows) and all(re.search(r"\.(png|jpe?g|svg|pdf)$", row.get("Image") or "")
                                      for row in rows))(
             list(csv.DictReader(open(os.path.join(work, "image-alt-missing.csv"),
                                      encoding="utf-8", newline=""))))),
        ("and the source target's copy writes a decision in the argument the adopted "
         "definition passes on, and the definitions after the preamble",
         lambda: "\\Figure[{A triangle, from the sidecar}]{0.3}{triangle}" in review_copy
         and "\\renewcommand{\\Figure}[3][]{\\includegraphics[alt={#1}," in main_copy),
        ("an environment called as a command, and one wrapping a list in braces or an "
         "\\input-ed file in braces, are read",
         lambda: re.search(r"<code>height</code>", one)
         and "The first part" in one and "An extra part" in one),
        ("titlesec's settings over several lines are left out, nothing of them read as "
         "text, and \\begingroup after a size command is a group",
         lambda: "An introduction to the first chapter." in one
         and "0pt" not in one + page("headers.html") and "Chapter~" not in one),
        ("a color the book defines is CSS, and so are a mix and a name of dvipsnames's",
         lambda: re.search(r'<span\s+style="color: rgb\(86, 155, 189\)"><strong>A\s+question', one)
         and re.search(r'<span\s+style="background-color: rgb\(221, 235, 242\)">tinted</span>',
                       one)
         and re.search(r'<span\s+style="color: rgb\(184, 20, 11\)">brick\s+red</span>', one)),
        ("\\nameref is a link to the label, its text the section's title, on another page "
         "too", lambda: re.search(r'<a\s+href="#sec:data"[^>]*>Data\s+basics</a>', one)
         and re.search(r'<a\s+href="ch_one\.html#ch_one"[^>]*>First\s+chapter</a>', two)),
        ("\\nameref to a figure's label is its caption, to one in a heading's braces the "
         "heading's title, its id not repeated, and to a heading that is itself a \\nameref, "
         "that heading's title, before the heading too",
         lambda: re.search(r'<a\s+href="#sec:named"[^>]*>Data\s+basics</a>', two)
         and re.search(r'<a\s+href="ch_one\.html#fig:panels"[^>]*>Panels</a>', two)
         and re.search(r'<a\s+href="ch_one\.html#sec:spread"[^>]*>Spread</a>', two)
         and latexsource_mark() not in two and one.count('id="sec:spread"') == 1),
        ("a \\subfigure is a figure of its own, its label in it, so a reference to it goes "
         "there", lambda: re.search(r'<figure\s+id="panel_a(-1)?"', one)
         and re.search(r'\sid="panel_a"', one) and 'href="#panel_a"' in one),
        ("a label with a space in it is an id without one", ids_valid),
        ("and a reference to it through the book's own macro is matched, as LaTeX matches it",
         lambda: len(re.findall(r'href="#US-Airports"', one)) == 2),
        ("an empty \\chapter*{} starting a page is left out",
         lambda: copyright_page and "Copyright 2026" in copyright_page
         and not re.search(r"<h1[^>]*>\s*</h1>", copyright_page)),
        ("and the page, with no heading of its own, is titled by its file's name as words, "
         "its title and its H1, and the run says so",
         lambda: "<title>Copyright</title>" in copyright_page
         and re.search(r"<h1[^>]*>Copyright</h1>", copyright_page)
         and 'copyright as "Copyright"' in said),
        ("a LICENSE.md beside a LaTeX book isn't a page, and a comment in a package list "
         "isn't a package", lambda: not os.path.exists(os.path.join(work, "html", "LICENSE.html"))
         and "%tocloft" not in said),
        ("the PDF built from the pages takes an alt text of two paragraphs, and a formula "
         "in a color the book defines",
         lambda: os.path.exists(os.path.join(work, "pdf", "org.example.custom.pdf"))
         if pdf else skip("no lualatex for the PDF")),
        ("and the type size and margins the book's preamble gives, not Pandoc's 10pt in "
         "the book class's margins", lambda: page_layout_kept(work, said)
         if pdf else skip("no lualatex for the PDF")),
        ("the copy runs on the paragraphs of an alt-text argument, which "
         "\\includegraphics can't take", lambda: "\\Figure[A gray star in chapter two, drawn "
         "with five points of equal length.\nIts center filled," in read(
             work, "tagged", "ch_two", "TeX", "ch_two.tex")),
        ("a group after a command the reader takes whole is read: \\begingroup after "
         "\\noindent, in a macro and in the text, and an exercise solution's number and "
         "text after \\hypersetup's argument and \\hspace's, as OpenIntro sets them",
         lambda: re.search(r"Remark\.</strong>\s*The variance is never\s+negative", one)
         and re.search(r"<em>\s*A\s+centered\s+italic\s+line\.\s*</em>", one)
         and re.search(r"1\.1</span>.*?The\s+solution\s+to\s+the\s+first\s+exercise\.",
                       one, re.S)),
        ("an image named in a different case from its file is the file, as macOS finds it, "
         "and the run says so",
         lambda: re.search(r'src="ch_two/figures/hexagon/hexagon\.png"[^>]*\s+alt="The hexagon '
                           r'again, named in capitals"', two)
         and "image named in a different case from its file" in said),
        ("the sample's definition of a macro over several lines is a comment, every line "
         "of it; adopted, its image has its alt text",
         lambda: "% \\renewcommand{\\Figuress}[4][]{%\n%   \\includegraphics[alt={#1},width=#2]"
         in sample and all(not l.strip() or l.startswith(("%", "\\renewcommand"))
                           for l in sample.splitlines())
         and 'alt="A purple hexagon with six equal sides"' in two),
        ("the sample lists no command the copy makes of an environment, and shows a macro "
         "as the book defines it, not as the copy has it",
         lambda: "\\wrap" not in sample and "\\endwrap" not in sample
         and "%   \\newcommand{\\strutx}[1]{\\rule{0pt}{2ex}#1\\leavevmode}" in sample),
        ("a text command inside \\text, a sliver of space in a name, a color and an "
         "underline in text, \\textcolor, \\MakeLowercase, \\hfill, \\index, and \\vspace in a "
         "formula are put so texmath reads it, as OpenIntro writes them",
         lambda: all(a + "</annotation>" in one for a in (
             "P(\\text{rolling a }\\texttt{1})",
             "\\texttt{income\\_ver}_{\\texttt{verified}}",
             "P(\\underline{{\\color{black}{\\text{mammogram$^+$}}}}\\text{ and has BC})",
             "s = 5.5 \\quad R^2 = 70\\%", "{\\color{oiB}{\\bar{x}}} = 21", "\\pmb{{t}}"))
         and re.search(r'<math display="block"[^>]*>(?:(?!</math>).)*<annotation '
                       r'encoding="application/x-tex">\\begin\{align\*\}\s*x = 1\s*'
                       r'\\end\{align\*\}</annotation>', one, re.S)),
        ("a label and a reference whose key LaTeX makes of its counters, as OpenIntro links "
         "each exercise and its solution, are counted as LaTeX counts: each exercise is "
         "numbered and links to its solution, and each solution back",
         lambda: re.search(r'<a\s+href="solutions\.html#eoce_sol_1_1"[^>]*>1\.1</a>', one)
         and re.search(r'<a\s+href="solutions\.html#eoce_sol_1_2"[^>]*>1\.2</a>', one)
         and 'id="eoce_1_2"' in one
         and re.search(r'<a\s+href="solutions\.html#eoce_sol_2_1"[^>]*>2\.1</a>', two)
         and re.search(r'<a\s+href="ch_one\.html#eoce_1_1"[^>]*>1\.1</a>',
                       page("solutions.html"))
         and re.search(r'<a\s+href="ch_two\.html#eoce_2_1"[^>]*>2\.1</a>',
                       page("solutions.html"))
         and re.search(r">\s*2\s*Second\s+chapter", page("solutions.html"))
         and "\\arabic" not in one + two + page("solutions.html")),
        ("a box the reader drops whole is read as what it holds: a framed phrase, and a "
         "table sized to fit the page",
         lambda: "framed phrase" in two and re.search(r"<t[dh][^>]*>\s*Fitted\s*</t[dh]>", two)),
        ("a counter the text shows is its value, the preamble's setting counted, and a "
         "reference to a label in running text the section's number LaTeX gives it; the "
         "marks leave no paragraph of their own",
         lambda: re.search(r"Exercises\s+&#x2014;\s+1\.2", one)
         and re.search(r"two\s+is\s+2:", two)
         and not re.search(r"<p>\s*</p>", one + two + page("solutions.html"))
         and len(re.findall(r'href="#US-Airports"[^>]*>1\.1\.1</a>', one)) == 2),
        ("a formula's macro is as the book defines it, so texmath reads it",
         lambda: "x\\hspace{1em}{} = 1</annotation>" in one),
        ("a space between words a command sets is a space, a sliver in a name and less "
         "than none not",
         lambda: all(w in re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", one)) for w in (
             "Ex apart", "Bee Cee", "Dee Eee", "sex_male", "GeeHee"))),
        ("a strut and a phantom of height alone are gone from a formula, one that was only "
         "a strut with it, \\hphantom is \\phantom, and \\smash what it holds",
         lambda: "mathstrut" not in one and re.search(r">\s*Ex\b", one)
         and '"application/x-tex">{}</annotation>' not in one
         and "{}x{y}\\phantom{z}</annotation>" in one),
        ("a group a formula's macro opens with \\begingroup is braces, which texmath reads",
         lambda: re.search(r"<math[^>]*>(?:(?!</math>).)*<annotation[^>]*>\{x\} \+ 1</annotation>",
                           one, re.S) and "\\begingroup x" not in one),
        ("the contents sample names the authors, not the affiliations under each name",
         lambda: __import__("yaml").safe_load(contents_sample or "{}").get(
             "project", {}).get("authors") == ["Ann Lee", "Bo Chen"]),
        ("and every link in it has its target: a label in a heading's braces is a label "
         "LaTeX finds", lambda: "Hyper reference" not in said
         if pdf else skip("no lualatex for the PDF")),
        ("in the EPUB, a link to a figure in another chapter's file names the file, and "
         "a formula in a heading has the navigation document declare MathML", epub_links),
        ("and each chapter file's title is its heading's text, a formula's as text", epub_titles),
        ("a brace a style file never closes stops the run, which names the file and line",
         lambda: stopped.returncode != 0
         and "style/style.tex:2 (a { that nothing in the file closes)" in told),
        ("a display formula LaTeX numbers is numbered beside it, each row its own, a tag "
         "as tagged, and subequations' rows by letter; each label is an anchor, and a "
         "reference to it, on its page or another, its number, \\eqref's in parentheses",
         lambda: re.search(r'<span\s+class="equation"><span\s+id="eq:energy"[^>]*></span>\s*'
                           r'<math(?:(?!</math>).)*</math>\s*<span\s+class="equation-number">'
                           r'\(2\.1\)</span></span>', two, re.S)
         and re.search(r'class="equation-number">\(2\.2\)<br />\s*<br />\s*\(2\.3\)</span>',
                       two)
         and re.search(r'class="equation-number">\(<math', two)
         and re.search(r'class="equation-number">\(2\.4a\)<br />\s*\(2\.4b\)</span>', two)
         and re.search(r'href="#eq:energy"[^>]*>\(2\.1\)</a>', two)
         and re.search(r'href="#eq:row-three"[^>]*>2\.3</a>', two)
         and re.search(r'href="#eq:system"[^>]*>\(2\.4\)</a>', two)
         and re.search(r'href="#eq:system-b"[^>]*>2\.4b</a>', two)
         and re.search(r'href="ch_two\.html#eq:energy"[^>]*>\(2\.1\)</a>', one)
         and "[eq:" not in one + two and "9 display formula numbered" in said),
        ("an eqnarray, every environment subequations holds and a label after them, breqn's "
         "dmath, a display formula with a tag, and a reference inside a formula are numbered "
         "as LaTeX numbers them, an appendix's by its letter",
         lambda: re.search(r'class="equation-number">\(2\.5\)<br />\s*<br />\s*\(2\.6\)</span>', two)
         and re.search(r'class="equation-number">\(2\.7a\)<br />\s*\(2\.7b\)</span>', two)
         and re.search(r'class="equation-number">\(2\.8\)</span>', two)
         and re.search(r'class="equation-number">\(<math', two.split("Tagged alone")[1])
         and all(re.search(r'data-reference="%s">%s</a>' % (k, re.escape(v)), two) for k, v in (
             ("eq:ea", "(2.5)"), ("eq:ef", "(2.6)"), ("eq:pair-b", "(2.7b)"),
             ("eq:pair-after", "(2.7)"), ("eq:long", "(2.8)"), ("eq:app", "(A.1)")))
         and "\\text{by (2.1)}</annotation>" in two
         and re.search(r'class="equation-number">\(A\.1\)</span>', page("tables.html"))),
        ("a file the appendix package's environment \\include-s is a page of its own, an "
         "appendix, no marker of the cut left on the page before, its title's formula as text",
         lambda: re.search(r"<title>Tables of [^<\\\\$]{1,3}</title>", page("tables.html"))
         and "TextbookImproverPageMarker" not in page("solutions.html") + page("tables.html")
         and "role: appendix" in re.sub(r"\s+", " ", contents_sample).split("tables")[-1][:40]
         if contents_sample else False),
        ("and the PDF from the pages numbers them as the pages do, its references to them "
         "found", lambda: pdf_numbers(work, said) if pdf else skip("no lualatex for the PDF")),
        ("and the Word file sets each as a display formula of its own, its number after it",
         lambda: word_formulas(os.path.join(work, "docx", "ch_two.docx"))),
        ("a chapter's title in a framed box is the page's H1 and title, out of the box, "
         "the box's text after it",
         lambda: "<title>Second chapter</title>" in two
         and re.search(r'<h1[^>]*>Second chapter</h1>\s*<div class="mdframed">\s*<p>In a frame',
                       two) and "<h2" not in two.split("<h1")[0]),
        ("a file continuing a chapter, a section with no chapter of its own, has its "
         "headings raised, its section its H1 and title",
         lambda: "<title>More of chapter two</title>" in page("more.html")
         and re.search(r"<h1[^>]*>More of chapter two</h1>", page("more.html"))
         and re.search(r"<h2[^>]*>A part of it</h2>", page("more.html"))
         and "1 heading set inside a box" in said and "1 page continuing a chapter" in said),
    ]


def case_capacity(work):
    """A book that outgrows one of TeX's tables, and one whose macro calls
    itself without end: the PDF target names each for what it is."""
    if not shutil.which("lualatex"):
        return [("a book too big for TeX's tables is named as that",
                 lambda: skip("no lualatex for the PDF target"))]
    said = {}
    for name, tex in (
            # A million and more names: LuaTeX's strings, a table of fixed
            # size, fill in a few seconds.
            ("strings", "\\newcount\\n \\loop \\expandafter\\def\\csname x\\the\\n"
                        "\\endcsname{} \\advance\\n1 \\ifnum\\n<3000000 \\repeat"),
            # Each \a leaves a \relax to come back to: the input stack.
            ("recursion", "\\def\\a{\\a\\relax}\\a")):
        book = os.path.join(work, name)
        os.makedirs(book, exist_ok=True)
        with open(os.path.join(book, "page.md"), "w", encoding="utf-8") as fh:
            fh.write("# Page\n\nText.\n\n```{=latex}\n" + tex + "\n```\n")
        with open(os.path.join(book, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  pdf:\n    format: pdf\n")
        result = convert(book)
        said[name] = result.stdout + result.stderr
    return [
        ("a book too big for TeX's tables is named as that, with the way to raise them",
         lambda: "LaTeX ran out of number of strings" in said["strings"]
         and "max_strings" in said["strings"]),
        ("a macro that calls itself without end is named as that, not as size",
         lambda: "LaTeX ran out of input stack size" in said["recursion"]
         and "calls itself without end" in said["recursion"]
         and "max_strings" not in said["recursion"]),
    ]


# A book set with packages LaTeX's tagging can't build or tag with: its
# headings by titlesec, framed passages by mdframed and framed, marked
# words by soul and ulem, a tab stop by tabto, a figure beside the text by
# wrapfig, a list labeled by the enumerate package's pattern; its figure a
# PDF whose word is drawn in Helvetica, not embedded.
UNSUPPORTED_MASTER = r"""\documentclass[11pt]{book}
\usepackage[margin=1in]{geometry}
\usepackage{graphicx,amsmath,amssymb}
\renewcommand{\lozenge}{\ensuremath{\diamond}}
\usepackage[explicit]{titlesec}
\usepackage{mdframed,framed,soul,tabto,wrapfig,enumerate,wasysym}
\usepackage[normalem]{ulem}
\usepackage{shapestyle}
\titleformat{\section}{\bfseries\Large}{\thesection\quad #1}{1em}{}
\titlespacing*{\section}{0pt}{2ex}{1ex}
\newpagestyle{shapes}{\sethead{}{Shapes}{}\setfoot{}{\thepage}{}}
\pagestyle{shapes}
\newmdenv[frametitle={Key idea}]{keyidea}
\mdtheorem{prop}{Proposition}
\newcommand\myul{\bgroup\markoverwith{\rule[-0.5ex]{2pt}{0.4pt}}\ULon}
\capsdef{T1/ppl/m/n/}{\scshape}{.16em}{.4em}{.2em}
\newenvironment{steps}[1][(i)]{\begin{enumerate}[#1]}{\end{enumerate}}
\title{Shapes Set Their Own Way}
\begin{document}
\maketitle
\chapter{Shapes}
\section{Squares}
A square has four sides.\tabto{3cm}Tabbed words.

\begin{mdframed}[frametitle={Definition}]
A square is a rectangle with equal sides.
\mdfsubsubtitle{A small heading}
\end{mdframed}

\begin{keyidea}
Every square is a rhombus.
\end{keyidea}

\begin{prop}
A proposition in a frame.
\end{prop}

\begin{framed}
A framed remark.
\end{framed}

Some \hl{highlighted words}, \ul{underlined words}, \st{struck words}, and \sout{struck out},
\so{spaced \soulomit{kept} out}, and \sloppyword{sloppy words}.

\begin{itemize}
\item \myul{a style of its own}
\end{itemize}

{\fontfamily{phv}\selectfont A line set in Helvetica.}

A filled circle, \CIRCLE, and a formula with wasysym's triangle: $x \lhd y$, and
amssymb's squares, $\square$ and $\blacksquare$, and its own lozenge, $\lozenge$.

\begin{enumerate}[(a)]
\item First part
\item Second part
\end{enumerate}

\begin{steps}
\item One step
\end{steps}

\begin{steps}[{Task} 1a]
\item Mixed counters
\end{steps}

\begin{shapeparts}
\item A part from the style file
\end{shapeparts}

\begin{wrapfigure}{r}{0.4\textwidth}
\centering
\includegraphics[width=0.3\textwidth]{plot.pdf}
\caption{A plot}
\end{wrapfigure}
Words beside the plot.

\noindent\begin{minipage}{0.6\textwidth}
\begin{wrapfigure}{l}{0.3\textwidth}
\includegraphics[width=0.25\textwidth]{shared/linked.pdf}
\caption{In a minipage}
\end{wrapfigure}
Words in a minipage.
\end{minipage}
\end{document}
"""
# A style file of the book's own: the enumerate package, and a pattern.
UNSUPPORTED_STYLE = r"""\ProvidesPackage{shapestyle}
\RequirePackage{enumerate}
\newenvironment{shapeparts}{\begin{enumerate}[i.]}{\end{enumerate}}
"""


def case_unsupported(work):
    """A book set with packages LaTeX's tagging can't take: the copy loads
    none of them and defines their commands, the run says what that
    changes, and the PDF from the book's own LaTeX builds tagged with every
    word, its figure's font embedded, and passes PDF/UA-2."""
    if not shutil.which("lualatex") or not shutil.which("latexmk"):
        return [("a book set with packages tagging can't take builds tagged",
                 lambda: skip("no lualatex or latexmk for the PDF target"))]
    os.makedirs(work)
    with open(os.path.join(work, "book.tex"), "w", encoding="utf-8") as fh:
        fh.write(UNSUPPORTED_MASTER)
    with open(os.path.join(work, "shapestyle.sty"), "w", encoding="utf-8") as fh:
        fh.write(UNSUPPORTED_STYLE)
    pdf(os.path.join(work, "plot.pdf"), word="Plot")
    # A figure in a folder beside the book, which it links to.
    shared = os.path.abspath(os.path.join(work, "..", os.path.basename(work) + "-shared"))
    os.makedirs(shared)
    pdf(os.path.join(shared, "linked.pdf"), word="Link")
    os.symlink(shared, os.path.join(work, "shared"))
    with open(os.path.join(shared, "linked.pdf"), "rb") as fh:
        linked_original = fh.read()
    with open(os.path.join(work, "image-alt.csv"), "w", encoding="utf-8") as fh:
        fh.write("Image,Alt\nrendered/plot.svg,A blue bar labeled Plot\n"
                 "rendered/shared/linked.svg,A blue bar labeled Link\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  tagged:\n    format: source\n    tagging: \"on\"\n"
                 "  pdf:\n    format: pdf\n")
    with open(os.path.join(work, "plot.pdf"), "rb") as fh:
        original = fh.read()
    result = convert(work)
    said = result.stdout + result.stderr
    built = os.path.join(work, "pdf", "book.pdf")
    copy = read(work, "tagged", "book.tex") \
        if os.path.exists(os.path.join(work, "tagged", "book.tex")) else ""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild

    def every_word():
        if not shutil.which("pdftotext"):
            return skip("no pdftotext to read the PDF")
        found = subprocess.run(["pdftotext", built, "-"], capture_output=True,
                               text=True).stdout if os.path.exists(built) else ""
        found = " ".join(found.split())
        missing = [phrase for phrase in (
            "1.1 Squares", "Tabbed words", "Definition", "A square is a rectangle with equal sides",
            "A small heading", "Key idea", "Every square is a rhombus",
            "Proposition 1. A proposition in a frame", "A framed remark",
            "highlighted words", "underlined words", "struck words", "struck out",
            "a style of its own", "spaced kept out", "sloppy words", "(a) First part",
            "(b) Second part", "(i) One step", "Task aa Mixed counters",
            "i. A part from the style file", "Figure 1.1: A plot", "Words beside the plot",
            "Figure 1.2: In a minipage", "Words in a minipage", "A filled circle, ●,", "⊲",
            "squares, □ and ■,", "its own lozenge, ⋄.", "A line set in Helvetica.")
            if phrase not in found]
        if missing:
            print("    missing from the PDF:", missing)
        return not missing

    def passes_ua2():
        verapdf = os.environ.get("VERAPDF") or shutil.which("verapdf")
        if not verapdf:
            return skip("no veraPDF to check the PDF")
        done = subprocess.run([verapdf, "-f", "ua2", "--format", "text", built],
                              capture_output=True, text=True)
        return done.stdout.strip().startswith("PASS")

    def helvetica():
        """The line the book sets in Helvetica by its NFSS family is in TeX
        Gyre Heros, its clone, not Latin Modern."""
        if not shutil.which("pdffonts"):
            return skip("no pdffonts to read the PDF's fonts")
        fonts = subprocess.run(["pdffonts", built], capture_output=True,
                               text=True).stdout if os.path.exists(built) else ""
        return "TeXGyreHeros" in fonts and "the PostScript font families the book names " \
            "(phv)" in said

    def figure_embedded():
        try:
            import pypdf  # noqa: F401
        except ImportError:
            return skip("no pypdf to read the figure's fonts")
        fixed = os.path.join(work, "tagged", "plot.pdf")
        fixed_linked = os.path.join(work, "tagged", "shared", "linked.pdf")
        with open(os.path.join(work, "plot.pdf"), "rb") as fh:
            unchanged = fh.read() == original
        with open(os.path.join(shared, "linked.pdf"), "rb") as fh:
            unchanged = unchanged and fh.read() == linked_original
        return latexbuild.unembedded_fonts(os.path.join(work, "plot.pdf")) == {"Helvetica"} \
            and os.path.exists(fixed) and latexbuild.unembedded_fonts(fixed) == set() \
            and latexbuild.unembedded_fonts(fixed_linked) == set() and unchanged \
            and "2 of the book's PDF figures written in the copy with their fonts embedded" \
            in said and "written in the copy LaTeX builds with their fonts embedded" in said
    return [
        ("the run says the copy loads none of the packages tagging can't take, and what "
         "replacing each changes, for the source target and for the PDF it builds",
         lambda: "WARNING: tagged: the copy loads none of titlesec, mdframed, framed, soul, "
         "ulem, tabto, wrapfig, enumerate," in said
         and "WARNING: pdf: the copy LaTeX builds loads none of titlesec," in said
         and "titlesec: headings are set as the class sets them" in said
         and "enumerate: a list's label pattern" in said),
        ("wasysym's symbols are the Unicode characters they draw, so unicode-math gives "
         "the formulas MathML, and the run says so",
         lambda: "wasysym's symbols drawn as the Unicode characters they are" in said
         and "unicode-math loaded" in said
         and "\\ifdefined\\directlua\\disable@package@load{wasysym}" in copy
         and "wasysym" not in said.split("the copy loads none of", 1)[-1].split(".")[0]),
        ("the copy disables each before the class and defines its commands, the book's "
         "own text as it was",
         lambda: copy.index("\\disable@package@load{titlesec}") < copy.index("\\documentclass")
         and "\\disable@package@load{wrapfig}{\\csname __oer_shim_wrapfig:\\endcsname}" in copy
         and "\\begin{enumerate}[(a)]" in copy and "\\begin{enumerate}[#1]" in copy
         and "\\usepackage[explicit]{titlesec}" in copy),
        ("the PDF from the book's own LaTeX builds tagged", lambda: os.path.exists(built)
         and "built by LaTeX from the book's own files" in said),
        ("with every word the packages set, the frames' titles too, and each list's labels "
         "as the enumerate package makes them, from a pattern a macro passes or a style file "
         "holds as well; a wrapped figure in a minipage", every_word),
        ("its figures written with their fonts embedded, in the copy and in the build, one "
         "in a folder the book links to as well, the book's own left as they were",
         figure_embedded),
        ("a line the book sets in Helvetica by its NFSS family is in TeX Gyre Heros, its "
         "clone, and the run says so", helvetica),
        ("and it passes veraPDF's PDF/UA-2 profile", passes_ua2),
    ]


PARTS_FILES = {
    # Parts set between the \include-s, a chapter in the front matter and
    # one in the back matter set in the master itself, an appendix; and
    # what the reader numbers its own way or drops, each number checked
    # against LaTeX's own build of it.
    "book.tex": r"""\documentclass{book}
\usepackage{amsmath}
\usepackage{amsthm}
\usepackage{graphicx}
\usepackage{caption}
\usepackage{subcaption}
\usepackage{wrapfig}
\usepackage{hyperref}
\usepackage{cleveref}
\crefname{thm}{theorem}{theorems}
\renewcommand{\sectionautorefname}{Section}
\newtheorem{thm}{Theorem}[section]
\newtheorem{lem}[thm]{Lemma}
\newtheorem{cor}{Corollary}
\title{A Book in Parts}
\author{A. Author}
\begin{document}
\maketitle
\frontmatter
\chapter{Preface}\label{ch:pref}
A preface the master sets itself.
\begin{figure}\centering\includegraphics{sq.png}\caption{A figure before the chapters}\label{fig:front}\end{figure}
\mainmatter
\part{Foundations}\label{part:found}
Words introducing the first part.
\include{one}
\include{two}
\part{Applications}
\include{three}
\appendix
\include{answers}
\backmatter
\chapter{Afterword}\label{ch:after}
Words after: Part~\ref{part:found}, Chapter~\ref{ch:three}, Appendix~\ref{app:ans}, and the \ref{ch:pref}.
\end{document}
""",
    "one.tex": r"""\chapter{One}\label{ch:one}
\section{First}\label{sec:first}
\begin{thm}\label{thm:a} A theorem.\end{thm}
\begin{lem}\label{lem:b} A lemma.\end{lem}
\begin{cor}\label{cor:c} A corollary.\end{cor}
\begin{equation}x = 1\label{eq:x}\end{equation}
\subsection{Sub}\label{sec:sub}
\subsubsection{Deep}\label{sec:deep}
\begin{figure}\centering\includegraphics{sq.png}\caption{Unlabeled}\end{figure}
\begin{figure}\centering\includegraphics{sq.png}\caption{Labeled}\label{fig:b}\end{figure}
\begin{figure}\centering\includegraphics{sq.png}\caption*{Not numbered}\end{figure}
\begin{figure}
\begin{subfigure}{0.4\textwidth}\includegraphics{sq.png}\caption{Left}\label{fig:sa}\end{subfigure}
\begin{subfigure}{0.4\textwidth}\includegraphics{sq.png}\caption{Right}\label{fig:sb}\end{subfigure}
\caption{Both}\label{fig:both}
\end{figure}
\begin{minipage}{0.45\textwidth}\centering\includegraphics{sq.png}\captionof{figure}{Set in a minipage}\label{fig:mini}\end{minipage}

\begin{wrapfigure}{r}{0.4\textwidth}\centering\includegraphics{sq.png}\caption{Wrapped}\label{fig:wrap}\end{wrapfigure}
Text beside it.

\begin{table}\centering\caption*{Not numbered either}\begin{tabular}{l}a\\\end{tabular}\end{table}
\begin{table}\centering\begin{tabular}{l}b\\\end{tabular}\caption{A table}\label{tab:a}\end{table}
\begin{table}\centering\includegraphics{sq.png}\caption{A table as an image}\label{tab:img}\end{table}
""",
    "two.tex": r"""\chapter{Two}
\section{Second}
See Theorem~\ref{thm:a}, Lemma~\ref{lem:b}, Corollary~\ref{cor:c}, Section~\ref{sec:sub}, \ref{sec:deep}, Figures~\ref{fig:b}, \ref{fig:sa}, \ref{fig:sb}, \ref{fig:both}, \ref{fig:mini}, \ref{fig:wrap}, Tables~\ref{tab:a} and \ref{tab:img}, and Figure~\ref{fig:front}.
""",
    "three.tex": r"""\chapter{Three}\label{ch:three}
\section{Third}\label{sec:third}
\begin{thm}\label{thm:d} Another.\end{thm}
See Theorem~\ref{thm:d}.
\begin{enumerate}\item First\label{it:first}\end{enumerate}
Names: \autoref{fig:b}; \autoref{sec:first}; \autoref{ch:one}; \autoref{thm:a}; \cref{fig:b}; \Cref{eq:x}; \cref{thm:a}; \cref{fig:b,fig:both,fig:mini,fig:wrap}; \cref{fig:b,tab:a}; \crefrange{fig:b}{fig:wrap}; \namecref{tab:a}; \labelcref{eq:x}; \cref{it:first}; \autoref{app:ans}.
""",
    "answers.tex": r"""\chapter{Answers}\label{app:ans}
\section{More}\label{sec:more}
\begin{figure}\centering\includegraphics{sq.png}\caption{In the appendix}\label{fig:app}\end{figure}
See Section~\ref{sec:more} and Figure~\ref{fig:app}.
""",
    "conversion.yaml": "targets:\n  html:\n    format: html\n",
}


def case_parts(work):
    """A book in parts: each part the master sets between its \\include-s a
    page of its own, as is a chapter it sets itself, its chapters grouped
    under it in the contents; and every reference given LaTeX's number,
    where the reader numbers its own way, with the captions it drops."""
    for name, text in PARTS_FILES.items():
        os.makedirs(os.path.join(work, os.path.dirname(name)), exist_ok=True)
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    png(os.path.join(work, "sq.png"), (90, 90, 90))
    result = convert(work)
    said = result.stdout + result.stderr
    import yaml
    sample = yaml.safe_load(read(work, "contents-sample.yaml")) \
        if os.path.exists(os.path.join(work, "contents-sample.yaml")) else {}
    contents = ((sample or {}).get("project") or {}).get("contents")

    def page(name):
        path = os.path.join(work, "html", name + ".html")
        return read(work, "html", name + ".html") if os.path.exists(path) else ""

    def text(name):
        return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", page(name).split(
            "<body", 1)[-1])).split())

    def title(name):
        found = re.search(r"<title>(.*?)</title>", page(name))
        return found.group(1) if found else None
    captions = re.findall(r"<figcaption>(.*?)</figcaption>", page("one"), re.S)

    def epub_nested():
        """With the sample's contents adopted, the EPUB's contents hold each
        part's chapters under it, the part's page opening it once."""
        import zipfile
        with open(os.path.join(work, "project.yaml"), "w") as fh:
            yaml.safe_dump({"project": sample["project"]}, fh)
        with open(os.path.join(work, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  epub:\n    format: epub3\n")
        convert(work)
        path = os.path.join(work, "epub", "book.epub")
        if not os.path.exists(path):
            return False
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            nav = next(z.read(n).decode("utf-8") for n in names if n.endswith("nav.xhtml"))
            chapters = [z.read(n).decode("utf-8") for n in names
                        if n.endswith(".xhtml") and not n.endswith("nav.xhtml")]
        return re.search(r'<a[^>]*>Foundations</a>\s*<ol[^>]*>\s*<li[^>]*><a[^>]*>One</a>',
                         nav) is not None \
            and sum(len(re.findall(r">Foundations</h\d>", c)) for c in chapters) == 1
    return [
        ("a part the master sets between two \\include-s is a page of its own, titled by it, "
         "where it had ended the chapter before and titled its page",
         lambda: title("book-2") == "Foundations" and title("book-3") == "Applications"
         and "Foundations" not in text("one") and "Applications" not in text("two")
         and title("two") == "Two" and "Words introducing the first part." in text("book-2")),
        ("a chapter the master sets itself is a page of its own too, in the front or back "
         "matter as the division commands before it say, and the run counts them",
         lambda: title("book-1") == "Preface" and title("book-4") == "Afterword"
         and "4 for what it holds itself" in said),
        ("a chapter's page in a book with parts opens a level down, which isn't reported as "
         "a page continuing a chapter", lambda: "Read from a copy of the LaTeX" in said
         and "page continuing a chapter" not in said and title("one") == "One"),
        ("the contents sample groups each part's chapters under it, its page first",
         lambda: contents == [{"page": "book-1", "role": "front"},
                              {"title": "Foundations", "items": ["book-2", "one", "two"]},
                              {"title": "Applications", "items": ["book-3", "three"]},
                              {"page": "answers", "role": "appendix"},
                              {"page": "book-4", "role": "back"}]),
        ("a reference to a part, to a chapter after one, and to an appendix has LaTeX's "
         "number, and one to a front-matter chapter, which LaTeX numbers nothing, its title",
         lambda: "Words after: Part I , Chapter 3 , Appendix A , and the Preface ." in
         text("book-4")),
        ("a theorem is numbered as the book defines it, within its section, a lemma with "
         "the theorem's counter, a corollary on its own, in its title and its references",
         lambda: re.search(r"<strong>Theorem 1\.1\.1</strong>", page("one"))
         and re.search(r"<strong>Lemma 1\.1\.2</strong>", page("one"))
         and re.search(r"<strong>Corollary 1</strong>", page("one"))
         and re.search(r"<strong>Theorem 3\.1\.1</strong>", page("three"))
         and "See Theorem 3.1.1 ." in text("three")),
        ("figures and tables are numbered as LaTeX numbers them: one without a label counted, "
         "\\caption* not, subfigures by letter, \\captionof, a wrapped figure, a table set "
         "as an image, a figure in the front matter, and a subsubsection by its subsection",
         lambda: "See Theorem 1.1.1 , Lemma 1.1.2 , Corollary 1 , Section 1.1.1 , 1.1.1 , "
         "Figures 1.2 , 1.3a , 1.3b , 1.3 , 1.4 , 1.5 , Tables 1.1 and 1.2 , and Figure 1 ."
         in text("two")),
        ("and lettered in an appendix",
         lambda: "See Section A.1 and Figure A.1 ." in text("answers")),
        ("\\autoref and cleveref's references have the names LaTeX prints, the book's own "
         "among them, \\autoref's in its link and cleveref's before it, several labels a "
         "range or each its link, an item's too",
         lambda: "Names: Figure 1.2 ; Section 1.1 ; chapter 1 ; 1.1.1 ; fig. 1.2 ; "
         "Equation (1.1) ; theorem 1.1.1 ; figs. 1.2 to 1.5 ; fig. 1.2 and table 1.1 ; "
         "figs. 1.2 to 1.5 ; table ; (1.1) ; item 1; Appendix A ." in text("three")
         and re.search(r'<a\s+href="one\.html#fig:b"[^>]*>Figure&#xA0;1\.2</a>', page("three"))
         and re.search(r'figs\.&#xA0;<a\s+href="one\.html#fig:b"[^>]*>1\.2</a>\s+to&#xA0;'
                       r'<a\s+href="one\.html#fig:wrap"[^>]*>1\.5</a>', page("three"))),
        ("\\captionof's caption, a wrapped figure's, and a table set as an image's are kept, "
         "and wrapfig's arguments aren't text",
         lambda: "Set in a minipage" in captions and "Wrapped" in captions
         and "A table as an image" in captions and "0.4" not in text("one")
         and "Text beside it." in text("one")),
        ("in the EPUB, each part's chapters are under it in the contents", epub_nested),
    ]


REFS_BIB = r"""@book{knuth,
  author = "Donald E. Knuth",
  title = "The \protect{T}eXbook",
  publisher = "Addison-Wesley",
  year = 1984,
}
@book{lamport,
  author = "Leslie Lamport",
  title = "{\LaTeX}: A Document Preparation System",
  publisher = "Addison-Wesley",
  year = 1994,
  note = "Second edition. %
\url{https://www.latex-project.org/a/long/path/that/runs/past/the/end/of/the/line}",
}
@misc{unused,
  author = "Nobody",
  title = "Never cited",
  year = 2000,
}
"""
NAT_BIB = r"""@book{k84, author = "Donald E. Knuth", title = "The TeXbook", publisher = "AW", year = 1984}
@book{k86, author = "Donald E. Knuth", title = "TeX: The Program", publisher = "AW", year = 1986}
@book{k86b, author = "Donald E. Knuth", title = "METAFONT: The Program", publisher = "AW", year = 1986}
@book{lamport, author = "Leslie Lamport", title = "LaTeX", publisher = "AW", year = 1994,
  doi = "10.1000/xyz123"}
@book{gms, author = "Michel Goossens and Frank Mittelbach and Alexander Samarin",
  title = "The LaTeX Companion", publisher = "AW", year = 1994}
"""
VD_BIB = '@book{vd, author = "Anne van Dyke", title = "Dykes", publisher = "AW", year = 2005}\n'
BIB_FILES = {
    # BibTeX's plain style, a citation a macro of the book's own makes.
    "plain/book.tex": "\\documentclass{book}\n\\newcommand{\\see}[1]{see \\cite{#1}}\n"
                      "\\begin{document}\n\\include{one}\n\\bibliographystyle{plain}\n"
                      "\\bibliography{refs}\n\\end{document}\n",
    "plain/one.tex": "\\chapter{One}\nAs \\cite{lamport} says, and \\cite[p. 3]{knuth,lamport}, "
                     "and \\see{knuth}.\n",
    "plain/refs.bib": REFS_BIB,
    # natbib's author and year, in its square brackets.
    "natbib/book.tex": "\\documentclass{book}\n\\usepackage{natbib}\n\\begin{document}\n"
                       "\\chapter{One}\nAs \\citet{knuth} says, and \\citep{knuth,lamport}, and "
                       "\\citep[see][p. 3]{lamport}.\n\\bibliographystyle{plainnat}\n"
                       "\\bibliography{refs}\n\\end{document}\n",
    "natbib/refs.bib": REFS_BIB,
    # biblatex, which Pandoc's citeproc reads.
    "biblatex/book.tex": "\\documentclass{book}\n\\usepackage[style=authoryear]{biblatex}\n"
                         "\\addbibresource{refs.bib}\n\\begin{document}\n\\include{one}\n"
                         "\\printbibliography\n\\end{document}\n",
    "biblatex/one.tex": "\\chapter{One}\nAs \\textcite{knuth} says, and \\parencite{lamport}.\n",
    "biblatex/refs.bib": REFS_BIB,
    # biblatex's full citations, a macro of the book's own in its database,
    # as OpenIntro gives its data sets' sources.
    "fullcite/book.tex": "\\documentclass{book}\n\\usepackage[style=authortitle,backend=bibtex]"
                         "{biblatex}\n\\usepackage{hyperref}\n\\newcommand{\\oiSite}[2]{\\href{"
                         "https://example.org/#1}{#2}}\n\\addbibresource{data.bib}\n"
                         "\\newcommand{\\datasource}[1]{Data from \\fullcite{#1}.}\n"
                         "\\begin{document}\n\\chapter{One}\nHeights.\\footfullcite{heights} "
                         "Weights.\\footfullcite[see][5]{heights,survey} As \\fullcite{survey} "
                         "has it. \\datasource{heights}\n\\end{document}\n",
    "fullcite/data.bib": "@misc{heights,\n  note = {Source: \\oiSite{heights}{Heights Data Set}},"
                         "\n}\n@article{survey,\n  author = {Ada Lovelace},\n  title = {A Survey of "
                         "the \\oiSite{tug}{TeX Users Group}},\n  journal = {Journal},\n"
                         "  year = 2001,\n}\n",
    # natbib's round option, which turns its preset for plainnat off, so
    # its default semicolon separates; year suffixes; a key with no entry.
    "natround/book.tex": "\\documentclass{book}\n\\usepackage[round]{natbib}\n\\begin{document}\n"
                         "\\chapter{One}\nA: \\citep{k84,lamport}. B: \\citep{k86,k86b}. C: "
                         "\\citet{k84,k86}. D: \\citep{nokey}. Z.\n\\bibliographystyle{plainnat}\n"
                         "\\bibliography{refs}\n\\end{document}\n",
    "natround/refs.bib": NAT_BIB,
    # natbib's numbers, sorted and compressed.
    "natnum/book.tex": "\\documentclass{book}\n\\usepackage[numbers,sort&compress]{natbib}\n"
                       "\\begin{document}\n\\chapter{One}\nA: \\citep{k86,k84,k86b}. B: "
                       "\\citet{k84}. Z.\n\\bibliographystyle{plainnat}\n\\bibliography{refs}\n"
                       "\\end{document}\n",
    "natnum/refs.bib": NAT_BIB,
    # Labels natbib reads besides Name(Year): \citeauthoryear, \harvarditem.
    "harvard/paper.tex": "\\documentclass{article}\n\\usepackage{natbib}\n\\begin{document}\n"
                         "\\section{Intro}\nA: \\citep{k84,lam}. Z.\n\\begin{thebibliography}{}\n"
                         "\\bibitem[\\protect\\citeauthoryear{Knuth}{Knuth}{1984}]{k84} D. Knuth. "
                         "\\newblock The TeXbook.\n\\harvarditem[Lamport]{Lamport, L.}{1994}{lam} "
                         "L. Lamport. \\newblock LaTeX.\n\\end{thebibliography}\n\\end{document}\n",
    # A citation only a macro of the book's own makes, in unsrt's order.
    "macro/book.tex": "\\documentclass{book}\n\\newcommand{\\see}[1]{see \\cite{#1}}\n"
                      "\\begin{document}\n\\chapter{One}\nA: \\cite{k84}, \\see{lamport}, "
                      "\\cite{gms}. Z.\n\\bibliographystyle{unsrt}\n\\bibliography{refs}\n"
                      "\\end{document}\n",
    "macro/refs.bib": NAT_BIB,
    # LaTeX's own \\cite with the cite package, sorted and compressed.
    "citepkg/book.tex": "\\documentclass{article}\n\\usepackage{cite}\n\\begin{document}\n"
                        "\\section{One}\nA: \\cite{k86,k84,k86b}. Z.\n\\bibliographystyle{plain}\n"
                        "\\bibliography{refs}\n\\end{document}\n",
    "citepkg/refs.bib": NAT_BIB,
    # A database that isn't there, which BibTeX says.
    "nodb/book.tex": "\\documentclass{article}\n\\begin{document}\n\\section{One}\nA: "
                     "\\cite{k84}. Z.\n\\bibliographystyle{plain}\n\\bibliography{missing}\n"
                     "\\end{document}\n",
    # A database with an entry twice, which BibTeX skips with an error, as
    # LaTeX's build reads the .bbl all the same.
    "dupkey/book.tex": "\\documentclass{article}\n\\begin{document}\n\\section{One}\nA: "
                       "\\cite{k84}, \\cite{lamport}. Z.\n\\bibliographystyle{plain}\n"
                       "\\bibliography{refs}\n\\end{document}\n",
    "dupkey/refs.bib": NAT_BIB + '@book{k84, author = "Donald E. Knuth", title = "Again", '
                                 'publisher = "AW", year = 1984}\n',
    # A master in a folder of its own, its database a folder up.
    "sub/src/topic.tex": "\\documentclass{article}\n\\begin{document}\n\\section{Topic}\nA: "
                         "\\cite{k84}. Z.\n\\bibliographystyle{plain}\n\\bibliography{../refs}\n"
                         "\\end{document}\n",
    "sub/refs.bib": NAT_BIB,
    # natbib's superscripts, sorted and compressed: the space before each
    # taken away, a tie's and a line end's too; \citeyearpar the same as
    # \citeyear. Measured with LaTeX 2026-06-01, as the next two are.
    "natsuper/paper.tex": "\\documentclass{article}\n\\usepackage[super,sort&compress]{natbib}\n"
                          "\\begin{document}\n\\section{One}\nA: word \\citep{k84,k86,k86b}, tie~"
                          "\\citep{lamport}, line\n\\citep{gms}, see \\citep[see][]{k86}, yp "
                          "\\citeyearpar{k86}. Z.\n\n\\bibliographystyle{plainnat}\n"
                          "\\bibliography{refs}\n\\end{document}\n",
    "natsuper/refs.bib": NAT_BIB,
    # natbib's numbers: a key with no entry ? with no separator before it,
    # \citet's bracket closed after it all the same; \citealt's note before
    # each number; \Citet's name as the entry gives it; a year without its
    # letter, in the bibliography too; \setcitestyle from where it stands.
    "natmiss/paper.tex": "\\documentclass{article}\n\\usepackage[numbers]{natbib}\n"
                         "\\begin{document}\n\\section{One}\nA: \\citep{k84,nokey,lamport}; "
                         "\\citet{nokey}; \\citealt[see][p.~4]{k84,lamport}; \\Citet{vd}; "
                         "\\citeyear{k86,k86b}. \\setcitestyle{round} B: \\citep{k84}. Z.\n\n"
                         "\\bibliographystyle{plainnat}\n\\bibliography{refs}\n\\end{document}\n",
    "natmiss/refs.bib": NAT_BIB + VD_BIB,
    # natbib's author and year: a key with no entry first, the one after it
    # without a separator; a key twice, its year again ?; \Citep's every
    # name capitalized; \citet's bracket after a key with no entry.
    "natay/paper.tex": "\\documentclass{article}\n\\usepackage{natbib}\n\\begin{document}\n"
                       "\\section{One}\nA: \\citep{nokey,k84}; \\citep{k84,k84}; "
                       "\\Citep{lamport,vd}; \\citet{k84,nokey,lamport}; \\Citealp{vd}; "
                       "\\Citealt[see][]{vd}. Z.\n\n"
                       "\\bibliographystyle{plainnat}\n\\bibliography{refs}\n\\end{document}\n",
    "natay/refs.bib": NAT_BIB + VD_BIB,
    # The cite package's options: nosort and nocompress.
    "citenosort/paper.tex": "\\documentclass{article}\n\\usepackage[nosort]{cite}\n"
                            "\\begin{document}\n\\section{One}\nA: \\cite{k86,k84,k86b,lamport}; "
                            "\\cite{nokey,k84}. Z.\n\n\\bibliographystyle{plain}\n"
                            "\\bibliography{refs}\n\\end{document}\n",
    "citenosort/refs.bib": NAT_BIB,
    "citenocomp/paper.tex": "\\documentclass{article}\n\\usepackage[nocompress]{cite}\n"
                            "\\begin{document}\n\\section{One}\nA: \\cite{k86,k84,k86b,lamport}; "
                            "\\cite{nokey,k84}. Z.\n\n\\bibliographystyle{plain}\n"
                            "\\bibliography{refs}\n\\end{document}\n",
    "citenocomp/refs.bib": NAT_BIB,
    # Labels of author and year in a bibliography the paper writes itself,
    # without natbib: LaTeX's \cite prints them as they are.
    "authyear/paper.tex": "\\documentclass{article}\n\\begin{document}\n\\section{One}\nA: As "
                          "shown by \\cite{knuth} and \\cite[p.~2]{lamport}. Z.\n"
                          "\\begin{thebibliography}{99}\n\\bibitem[Knuth, 1984]{knuth} D. E. Knuth. "
                          "The TeXbook. 1984.\n\\bibitem[Lamport, 1994]{lamport} L. Lamport. LaTeX. "
                          "1994.\n\\end{thebibliography}\n\\end{document}\n",
    # A bibliography the paper writes itself, alpha's labels.
    "own/paper.tex": "\\documentclass{article}\n\\begin{document}\n\\section{Intro}\n"
                     "See \\cite{Str87} and \\cite{Knu84}.\n\\begin{thebibliography}{Str87}\n"
                     "\\bibitem[Knu84]{Knu84} D. Knuth. \\newblock \\emph{The TeXbook}. "
                     "\\newblock 1984.\n\\bibitem[Str87]{Str87} D. Struik. \\newblock History. "
                     "% a comment\n\\newblock 1987.\n\\end{thebibliography}\n\\end{document}\n",
}


def case_bibliography(work):
    """A book's citations and its bibliography: BibTeX's, in the book's own
    style, its citations each the label LaTeX prints linked to its entry;
    natbib's author and year; a bibliography the book writes itself;
    biblatex's, made by Pandoc's citeproc; and biblatex's full citations."""
    said = {}
    for name, text in BIB_FILES.items():
        os.makedirs(os.path.join(work, os.path.dirname(name)), exist_ok=True)
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    for book in ("plain", "natbib", "biblatex", "own", "fullcite", "natround", "natnum",
                 "harvard", "macro", "sub", "citepkg", "nodb", "natsuper", "natmiss", "natay",
                 "citenosort", "citenocomp", "authyear", "dupkey"):
        with open(os.path.join(work, book, "conversion.yaml"), "w") as fh:
            fh.write(("defaults:\n  latex:\n    main: src/topic.tex\n" if book == "sub"
                      else "") + "targets:\n  html:\n    format: html\n")
        done = convert(os.path.join(work, book))
        said[book] = done.stdout + done.stderr

    def page(book, name):
        path = os.path.join(work, book, "html", name + ".html")
        return read(work, book, "html", name + ".html") if os.path.exists(path) else ""

    def flat(book, name):
        """A page's text with no tags and no space, a citation's brackets
        beside its link's label."""
        body = page(book, name).split("<body", 1)[-1]
        return re.sub(r"\s+", "", html_module.unescape(re.sub(r"<[^>]+>", "", body)))

    def has(book, name, words):
        return re.sub(r"\s+", "", words) in flat(book, name)
    bibtex = bool(shutil.which("bibtex"))
    return [
        ("BibTeX makes the bibliography in the book's own style, a page of its own where "
         "\\bibliography stands, the entries cited and no others, a database's \\protect "
         "no command and a URL after a comment printed where BibTeX breaks the line before it",
         lambda: has("plain", "book-1", "Bibliography [1] Donald E. Knuth. The TeXbook. "
                     "Addison-Wesley, 1984. [2] Leslie Lamport.")
         and "https://www.latex-project.org/a/long/path" in flat("plain", "book-1")
         and "Never cited" not in flat("plain", "book-1")
         and "<title>Bibliography</title>" in page("plain", "book-1")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("each citation is the label LaTeX prints, linked to its entry, a note after it, "
         "and one a macro of the book's own makes too",
         lambda: has("plain", "one", "As [2] says, and [1, 2, p. 3], and see [1].")
         and re.search(r'<a\s+href="book-1\.html#bib-lamport"[^>]*>2</a>', page("plain", "one"))
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("natbib's author and year, in its square brackets and with its commas",
         lambda: has("natbib", "book", "As Knuth [1984] says, and [Knuth, 1984, Lamport, "
                     "1994], and [see Lamport, 1994, p. 3].")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("a bibliography the book writes itself is its entries, with their labels, and its "
         "citations link to them; a comment in an entry ends at its line",
         lambda: has("own", "paper", "See [Str87] and [Knu84].")
         and has("own", "paper", "References [Knu84] D. Knuth. The TeXbook. 1984. "
                 "[Str87] D. Struik. History. 1987.")
         and re.search(r'<a\s+href="#bib-Str87"[^>]*>Str87</a>', page("own", "paper"))),
        ("biblatex's citations and bibliography are Pandoc's citeproc's, in its own style, "
         "and the run says so",
         lambda: has("biblatex", "one", "As Knuth (1984) says, and (Lamport 1994).")
         and has("biblatex", "book-1", "Bibliography Knuth, Donald E. 1984.")
         and re.search(r'href="book-1\.html#ref-knuth"', page("biblatex", "one"))
         and "Pandoc's own style" in said["biblatex"]),
        ("biblatex's full citations are their entries in full, a footnote's ended with a "
         "period, several joined by semicolons, notes before and after, a page's number with "
         "its prefix, a macro of the book's own in the database made as the book makes it, "
         "and a title's case as the database gives it",
         lambda: has("fullcite", "book", "Source: Heights Data Set.")
         and has("fullcite", "book", "see Source: Heights Data Set; Ada Lovelace. A Survey of "
                 "the TeX Users Group. Journal, 2001, p. 5.")
         and has("fullcite", "book", "As Ada Lovelace. A Survey of the TeX Users Group. "
                 "Journal, 2001 has it.")
         and 'href="https://example.org/tug"' in page("fullcite", "book")
         and "full citation" in said["fullcite"]
         if bibtex else skip("no BibTeX to write out a full citation")),
        ("and one a macro of the book's own makes, with no word of citeproc's style, which "
         "made nothing",
         lambda: has("fullcite", "book", "Data from Source: Heights Data Set.")
         and "Pandoc's own style" not in said["fullcite"]
         if bibtex else skip("no BibTeX to write out a full citation")),
        ("natbib's options turn its style's preset off, as natbib does: round brackets with "
         "its own semicolon; a year twice given its letter alone, an author cited again named "
         "once, the letter in the entry too, a DOI linked, and a key with no entry ?, which "
         "the run names",
         lambda: has("natround", "book", "A: (Knuth, 1984; Lamport, 1994). B: (Knuth, "
                     "1986a,b). C: Knuth (1984, 1986a). D: (?). Z.")
         and has("natround", "book", "TeX: The Program. AW, 1986a.")
         and 'href="https://doi.org/10.1000/xyz123"' in page("natround", "book")
         and "have no entry in the bibliography" in said["natround"] and "nokey" in
         said["natround"]
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("natbib's numbers, sorted and compressed, \\citet's with the author",
         lambda: has("natnum", "book", "A: [1\u20133]. B: Knuth [1]. Z.")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("natbib reads \\citeauthoryear's and \\harvarditem's labels, and its own "
         "punctuation without a style's preset",
         lambda: has("harvard", "paper", "A: (Knuth, 1984; Lamport, 1994). Z.")),
        ("a citation only a macro of the book's own makes is BibTeX's too, in LaTeX's order",
         lambda: has("macro", "book", "A: [1], see [2], [3]. Z.")
         and has("macro", "book", "[2] Leslie Lamport.")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("LaTeX's own \\cite with the cite package is sorted and compressed",
         lambda: has("citepkg", "book", "A: [1\u20133]. Z.")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("when BibTeX can't make the bibliography, the run says why",
         lambda: "BibTeX couldn't make the bibliography" in said["nodb"]
         and "missing" in said["nodb"]
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("natbib's superscripts take away the space before them, a tie's and a line end's "
         "too, \\citeyearpar is \\citeyear, and a year has no letter, in the bibliography too",
         lambda: has("natsuper", "paper", "A: word2\u20134, tie5, line1, see see3, yp 1986. Z.")
         and all(re.search(w + r"<sup>", page("natsuper", "paper")) for w in ("word", "tie",
                                                                               "line", "see"))
         and re.search(r"yp\s+(?:<a [^>]*>)?1986(?:</a>)?\.", page("natsuper", "paper"))
         and has("natsuper", "paper", "[3] Donald E. Knuth. TeX: The Program. AW, 1986. [4]")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("natbib's numbers as natbib prints them: a key with no entry, \\citealt's notes, "
         "\\Citet's name, \\citeyear's year, and \\setcitestyle from where it stands",
         lambda: has("natmiss", "paper", "A: [1?, 4]; ?]; Knuth see 1, Lamport see 4, p. 4; van "
                     "Dyke [5]; 1986, 1986. B: (1). Z.")
         and has("natmiss", "paper", "[2] Donald E. Knuth. TeX: The Program. AW, 1986. [3] "
                 "Donald E. Knuth. METAFONT: The Program. AW, 1986. [4]")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("natbib's author and year as natbib prints them: a key with no entry first or "
         "between, a key twice, \\Citep's, \\Citealp's, and \\Citealt's names",
         lambda: has("natay", "paper", "A: [?Knuth, 1984]; [Knuth, 1984,?]; [Lamport, 1994, Van "
                     "Dyke, 2005]; Knuth [1984], ?], Lamport [1994]; Van Dyke, 2005; Van Dyke see "
                     "2005. Z.")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("the cite package's nosort keeps the keys' order, still compressed, and its "
         "nocompress sorts them without compressing; a key with no entry first",
         lambda: has("citenosort", "paper", "A: [3, 1, 2, 4]; [?, 1]. Z.")
         and has("citenocomp", "paper", "A: [1, 2, 3, 4]; [?, 1]. Z.")
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("LaTeX's own \\cite prints a label of author and year as it is, without natbib",
         lambda: has("authyear", "paper", "A: As shown by [Knuth, 1984] and [Lamport, 1994, p. "
                     "2]. Z.")),
        ("a .bbl BibTeX writes despite an error (an entry twice) is read, as LaTeX's build "
         "reads it, and the run gives BibTeX's error, naming the book's database",
         lambda: has("dupkey", "book", "A: [1], [2]. Z.")
         and has("dupkey", "book", "References [1] Donald E. Knuth. The TeXbook. AW, 1984.")
         and "Repeated entry" in said["dupkey"] and "refs.bib" in said["dupkey"]
         and "database1" not in said["dupkey"]
         if bibtex else skip("no BibTeX to make a bibliography")),
        ("a master in a folder of its own finds its database a folder up, as LaTeX does "
         "from the master's folder",
         lambda: has("sub", "topic", "A: [1]. Z.")
         and has("sub", "topic", "References [1] Donald E. Knuth.")
         and "No BibTeX here" not in said["sub"]
         if bibtex else skip("no BibTeX to make a bibliography")),
    ]


FLOAT_FILES = {
    # Floats the reader can't take as LaTeX numbers them, the front and
    # back matter, and theorems, each number checked against LaTeX's own
    # build of it (2026-10-07).
    "floats/book.tex": r"""\documentclass{book}
\usepackage{graphicx}
\usepackage{caption}
\usepackage{subfig}
\usepackage{amsthm}
\usepackage{hyperref}
\newtheorem{theorem}{Theorem}[chapter]
\newtheorem{lemma}[theorem]{Lemma}
\newcommand{\lemmaautorefname}{Lemma}
\newtheorem*{remark}{Remark}
\begin{document}
\frontmatter
\chapter{Preface}
\section{How to read it}\label{sec:how}
\mainmatter
\include{floats}
\backmatter
\chapter{Afterword}
\section{Last words}\label{sec:last}
Back: \ref{sec:how}, \ref{sec:last}.
\end{document}
""",
    "floats/floats.tex": r"""\chapter{Floats}\label{ch:floats}
\section{Intro}
Text before the image.
\includegraphics{sq.png}
\captionof{figure}{In a paragraph}\label{fig:para}

\begin{table}
\subfloat[Left]{\begin{tabular}{l}c\end{tabular}\label{tab:left}}
\subfloat[Right]{\begin{tabular}{l}d\end{tabular}}
\caption{Subtables}\label{tab:sub}
\end{table}
\begin{table}\centering\caption*{Key to symbols}\fbox{x: a variable}\end{table}
\begin{figure}\centering
\begin{minipage}{0.45\textwidth}\includegraphics{sq.png}\caption{Side A}\label{fig:sa}\end{minipage}\hfill
\begin{minipage}{0.45\textwidth}\includegraphics{sq.png}\caption{Side B}\label{fig:sb}\end{minipage}
\end{figure}
\begin{table}\centering\begin{tabular}{l}e\end{tabular}\begin{tabular}{l}f\end{tabular}\caption{Two in one}\label{tab:two}\end{table}
\begin{table}\centering\caption{Above one}\label{tab:aboveone}\begin{tabular}{l}g\end{tabular}
\caption{Above two}\label{tab:abovetwo}\begin{tabular}{l}h\end{tabular}\end{table}
\begin{figure}\centering\includegraphics{sq.png}\caption{Last}\label{fig:last}\end{figure}
\begin{table}\begin{center}\begin{tabular}{c|c}
Name & Form \\ \hline
Modus ponens & \begin{tabular}{cl} & $A$ \\ \hline $\therefore$ & $B$ \\ \end{tabular} \\
\end{tabular}\end{center}\caption{Rules}\label{tab:rules}\end{table}
\begin{theorem}\label{th:a}A.\end{theorem}
\begin{lemma}\label{lem:b}B.\end{lemma}
\begin{remark}Unnumbered.\end{remark}
Refs: \ref{fig:para}, \ref{tab:left}, \ref{tab:sub}, \ref{fig:sa}, \ref{fig:sb}, \ref{tab:two}, \ref{tab:aboveone}, \ref{tab:abovetwo}, \ref{fig:last}, \ref{tab:rules}; \autoref{lem:b}; \autoref{th:a}.
""",
    # memoir numbers to the section, and nothing in the front or back
    # matter; amsbook numbers sections, figures, and equations without the
    # chapter's number.
    "memoir/book.tex": r"""\documentclass{memoir}
\begin{document}
\frontmatter
\chapter{Pre}
\section{PS}\label{ps}
\mainmatter
\chapter{One}
\section{S}\label{s1}
\subsection{SS}\label{ss1}
\backmatter
\chapter{Back}
\section{BS}\label{bs}
X: ps=\ref{ps} s1=\ref{s1} ss1=\ref{ss1} bs=\ref{bs}.
\end{document}
""",
    "amsbook/book.tex": r"""\documentclass{amsbook}
\begin{document}
\chapter{One}
\begin{equation}x\label{e1}\end{equation}
\begin{figure}\caption{F}\label{f1}\end{figure}
\chapter{Two}\label{c2}
\section{S}\label{s2}
\begin{equation}x\label{e2}\end{equation}
\begin{figure}\caption{F}\label{f2}\end{figure}
\appendix
\chapter{App}\label{a1}
\section{AS}\label{as1}
X: e1=\ref{e1} f1=\ref{f1} c2=\ref{c2} s2=\ref{s2} e2=\ref{e2} f2=\ref{f2} a1=\ref{a1} as1=\ref{as1}.
\end{document}
""",
    # A page's title: an article whose bibliography is a second heading, a
    # document whose sections are all at the top with a PDF title for
    # hyperref, and one without.
    "article/paper.tex": r"""\documentclass{article}
\begin{document}
\section{Topic a}
As \cite{k} says.
\begin{thebibliography}{1}
\bibitem{k} D. Knuth. \newblock The TeXbook. \newblock 1984.
\end{thebibliography}
\end{document}
""",
    "notes/class-notes.tex": r"""\documentclass{article}
\usepackage{hyperref}
\hypersetup{pdftitle={Calculus 2 Notes}}
\begin{document}
\section*{1.1 Integration by Parts}
Words.
\section*{1.2 Trigonometric Integrals}
Words.
\end{document}
""",
    # The second review's floats, each number checked against LaTeX's own
    # build of it (2026-10-07): \captionof after a tabular or a center, in
    # a macro of the book's own, in a box and in a paragraph; two captions in
    # centers, in one center, in parboxes, in minipages laid out in a
    # tabular; subcaptionbox's; subtables under their float's caption, and
    # one subtable alone; a \caption* note; a table in an environment of the
    # book's own.
    "review/book.tex": r"""\documentclass{book}
\usepackage{graphicx,caption,subcaption}
\newcommand{\fig}[3]{\begin{center}\includegraphics[width=2cm]{#1}\captionof{figure}{#2}\label{#3}\end{center}}
\newcommand{\pfig}[3]{\includegraphics[width=2cm]{#1}\captionof{figure}{#2}\label{#3}}
\newenvironment{payoff}{\begin{tabular}{c|cc}}{\end{tabular}}
\begin{document}
\chapter{One}
Text before.

\begin{tabular}{cc} a & b \\ c & d \\ \end{tabular}
\captionof{table}{Tabular then captionof}\label{t:a}

\begin{center}
\includegraphics[width=2cm]{sq.png}
\end{center}
\captionof{figure}{Center then captionof}\label{f:a}

\fig{sq.png}{Macro figure}{f:m}

\pfig{sq.png}{Paragraph macro figure}{f:pm}

\begin{figure}[htbp]
\begin{center}\includegraphics[width=2cm]{sq.png}\caption{Center one}\label{f:c1}\end{center}
\begin{center}\includegraphics[width=2cm]{sq.png}\caption{Center two}\label{f:c2}\end{center}
\end{figure}

\begin{figure}[htbp]
\begin{center}
\includegraphics[width=2cm]{sq.png}\caption{First}\label{f:1}
\includegraphics[width=2cm]{sq.png}\caption{Second}\label{f:2}
\end{center}
\end{figure}

\begin{figure}[htbp]
\parbox{0.45\textwidth}{\centering\includegraphics[width=2cm]{sq.png}\caption{Parbox one}\label{f:p1}}\hfill
\parbox{0.45\textwidth}{\centering\includegraphics[width=2cm]{sq.png}\caption{Parbox two}\label{f:p2}}
\end{figure}

\begin{figure}[htbp]\centering
\begin{tabular}{cc}
\begin{minipage}{0.4\textwidth}\centering\includegraphics[width=2cm]{sq.png}\caption{Grid one}\label{f:t1}\end{minipage} &
\begin{minipage}{0.4\textwidth}\centering\includegraphics[width=2cm]{sq.png}\caption{Grid two}\label{f:t2}\end{minipage}
\end{tabular}
\end{figure}

\begin{figure}[htbp]\centering
\subcaptionbox{Sub box A\label{f:sa}}{\includegraphics[width=2cm]{sq.png}}\quad
\subcaptionbox{Sub box B\label{f:sb}}{\includegraphics[width=2cm]{sq.png}}
\caption{Has subcaptionboxes}\label{f:scb}
\end{figure}

\begin{table}[htbp]\centering
\caption{Has subtables}\label{t:st}
\begin{subtable}{0.45\textwidth}\centering\begin{tabular}{cc} a & b \\ \end{tabular}\caption{Sub one}\label{t:st1}\end{subtable}\hfill
\begin{subtable}{0.45\textwidth}\centering\begin{tabular}{cc} c & d \\ \end{tabular}\caption{Sub two}\label{t:st2}\end{subtable}
\end{table}

\begin{table}[htbp]\centering
\caption{Results}\label{t:res}
\begin{tabular}{cc} e & f \\ \end{tabular}
\caption*{Note: standard errors in parentheses.}
\end{table}

\begin{table}[htbp]\centering
\caption{Prisoner's dilemma}\label{t:pd}
\begin{payoff} & C & D \\ \hline C & 3,3 & 0,5 \\ D & 5,0 & 1,1 \\ \end{payoff}
\end{table}

\begin{table}[htbp]\centering
\caption{After}\label{t:after}
\begin{tabular}{c} g \\ \end{tabular}
\end{table}

\begin{table}[htbp]\centering
\begin{subtable}{0.45\textwidth}\centering\begin{tabular}{c} i \\ \end{tabular}\caption{Only}\label{t:only}\end{subtable}
\caption{One subtable}\label{t:one}
\end{table}

Refs: ta \ref{t:a}, fa \ref{f:a}, fm \ref{f:m}, pm \ref{f:pm}, c1 \ref{f:c1}, c2 \ref{f:c2}, f1 \ref{f:1}, f2 \ref{f:2}, p1 \ref{f:p1}, p2 \ref{f:p2}, t1 \ref{f:t1}, t2 \ref{f:t2}, sa \ref{f:sa}, sb \ref{f:sb}, scb \ref{f:scb}, st \ref{t:st}, st1 \ref{t:st1}, st2 \ref{t:st2}, res \ref{t:res}, pd \ref{t:pd}, after \ref{t:after}, one \ref{t:one}, only \ref{t:only}.
\end{document}
""",
    # floatrow's boxes, and multicols's column count and preface.
    "floatrow/book.tex": r"""\documentclass{book}
\usepackage{graphicx,floatrow,multicol}
\begin{document}
\chapter{One}
\begin{multicols}{2}[Before the columns.]
Text in the columns.
\end{multicols}
\begin{figure}[htbp]
\begin{floatrow}
\ffigbox{\includegraphics[width=2cm]{sq.png}}{\caption{Floatrow one}\label{f:fr1}}
\ffigbox{\caption{Floatrow two}\label{f:fr2}}{\includegraphics[width=2cm]{sq.png}}
\end{floatrow}
\end{figure}
\begin{table}[htbp]
\ttabbox{\caption{A table box}\label{t:tb}}{\begin{tabular}{cc} a & b \\ \end{tabular}}
\end{table}
Refs: fr1 \ref{f:fr1}, fr2 \ref{f:fr2}, tb \ref{t:tb}.
\end{document}
""",
    # KOMA's and amsbook's front and back matter.
    "koma/book.tex": r"""\documentclass{scrbook}
\begin{document}
\frontmatter
\chapter{Preface}
\section{About}\label{s:about}
\begin{figure}\caption{FF}\label{f:ff}\end{figure}
\mainmatter
\chapter{One}
\section{Intro}\label{s:intro}
\backmatter
\chapter{Notes}
\section{Extra}\label{s:extra}
\begin{figure}\caption{BF}\label{f:bf}\end{figure}
Refs: about \ref{s:about}; ff \ref{f:ff}; intro \ref{s:intro}; extra \ref{s:extra}; bf \ref{f:bf}.
\end{document}
""",
    "amsfront/book.tex": r"""\documentclass{amsbook}
\begin{document}
\frontmatter
\chapter{Preface}
\section{About}\label{s:about}
\begin{figure}\caption{FF}\label{f:ff}\end{figure}
\mainmatter
\chapter{One}
\section{Intro}\label{s:intro}
\backmatter
\chapter{Notes}
\section{Extra}\label{s:extra}
\begin{figure}\caption{BF}\label{f:bf}\end{figure}
Refs: about \ref{s:about}; ff \ref{f:ff}; intro \ref{s:intro}; extra \ref{s:extra}; bf \ref{f:bf}.
\end{document}
""",
    # A chapter's page with a \chapter* after its chapter, and one with a
    # bibliography, titled by the chapter; a PDF title with escapes.
    "titled/book.tex": r"""\documentclass{book}
\usepackage[pdftitle={Algebra \& Geometry}]{hyperref}
\begin{document}
\frontmatter
\chapter{Preface}
Pre.
\mainmatter
\include{ch1}
\include{ch2}
\end{document}
""",
    "titled/ch1.tex": r"""\chapter{Alpha}
\section{A1}
Text.
\chapter*{Alpha Exercises}
Ex.
""",
    "titled/ch2.tex": r"""\chapter{Beta}
\section{B1}
Text.
\begin{thebibliography}{9}
\bibitem{x} X. Book, 2000.
\end{thebibliography}
""",
    "escaped/notes.tex": r"""\documentclass{article}
\usepackage{hyperref}
\hypersetup{pdftitle={Algebra \& Geometry: Na\"ive Notes},pdfauthor={Me}}
\begin{document}
\section{First}
Text.
\section{Second}
Text.
\end{document}
""",
    "untitled/class-notes.tex": r"""\documentclass{article}
\begin{document}
\section*{1.1 Integration by Parts}
Words.
\section*{1.2 Trigonometric Integrals}
Words.
\end{document}
""",
}


def case_floats(work):
    """Floats, classes, and titles: a \\captionof in a paragraph after its
    headings, subtables, a \\caption* table with no table, two figures in
    one float, a table float of two tables, captions above their tables, a
    table in a table's cell, the front and back matter's sections, a starred
    theorem, \\autoref to a theorem sharing a counter; memoir's and amsbook's
    numbers; and a page's title with no one heading to be it."""
    said = {}
    for name, text in FLOAT_FILES.items():
        os.makedirs(os.path.join(work, os.path.dirname(name)), exist_ok=True)
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    for book in ("floats", "review", "floatrow"):
        png(os.path.join(work, book, "sq.png"), (90, 90, 90))
    for book in ("floats", "memoir", "amsbook", "article", "notes", "untitled", "review",
                 "floatrow", "koma", "amsfront", "titled", "escaped"):
        with open(os.path.join(work, book, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        done = convert(os.path.join(work, book))
        said[book] = done.stdout + done.stderr

    def page(book, name):
        path = os.path.join(work, book, "html", name + ".html")
        return read(work, book, "html", name + ".html") if os.path.exists(path) else ""

    def text(book, name):
        return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", page(book, name).split(
            "<body", 1)[-1])).split())

    def title(book, name):
        found = re.search(r"<title>(.*?)</title>", page(book, name))
        return found.group(1) if found else None
    return [
        ("a \\captionof in a paragraph after its chapter's headings captions that paragraph, "
         "the headings left out of the figure",
         lambda: title("floats", "floats") == "Floats"
         and not re.search(r"<figure[^>]*>\s*<h1", page("floats", "floats"))),
        ("subtables, a \\caption* table with no table, two figures in one float, a table "
         "float of two tables, captions above their tables, and a table in a table's cell "
         "are numbered as LaTeX numbers them, each caption kept once",
         lambda: "Refs: 1.1 , 1.1a , 1.1 , 1.2 , 1.3 , 1.2 , 1.3 , 1.4 , 1.4 , 1.5 ;"
         in text("floats", "floats")
         and text("floats", "floats").count("Subtables") == 1
         and "Key to symbols" in text("floats", "floats")
         and all(re.search(r'<table id="tab:above%s">\s*<caption>Above %s</caption>\s*<tbody>'
                           r'\s*<tr>\s*<td[^>]*>%s</td>' % (n, n, c), page("floats", "floats"))
                 for n, c in (("one", "g"), ("two", "h")))),
        ("a table in a table's cell doesn't take its table's id",
         lambda: page("floats", "floats").count('id="tab:rules"') == 1
         and re.search(r'<table id="tab:rules">\s*<caption>Rules</caption>',
                       page("floats", "floats"))),
        ("a theorem sharing another's counter is named by its own environment, and a "
         "starred one has no number",
         lambda: "; Lemma 1.2 ; Theorem 1.1 ." in text("floats", "floats")
         and re.search(r"<strong>Remark</strong>", page("floats", "floats"))),
        ("a section in the front and back matter is numbered as the book class numbers it",
         lambda: "Back: 0.1 , 1.2 ." in text("floats", "book-2")),
        ("memoir numbers to the section and nothing in the front or back matter, and "
         "amsbook numbers without the chapter's number",
         lambda: "X: ps= PS s1= 1.1 ss1= 1.1 bs= 1.1 ." in text("memoir", "book")
         and "X: e1= 1 f1= 1 c2= 2 s2= 1 e2= 2 f2= 1 a1= A as1= 1 ." in text("amsbook", "book")),
        ("an article's bibliography, a second heading, leaves its section the page's title",
         lambda: title("article", "paper") == "Topic a"
         and re.search(r'<h1[^>]*class="[^"]*bibliography', page("article", "paper"))),
        ("\\captionof after a tabular or a center, or in a macro of the book's own; two "
         "captions in centers, in one center, in parboxes, in minipages laid out in a tabular; "
         "subcaptionbox's; subtables under their float's caption; a \\caption* note; and a "
         "table in an environment of the book's own are numbered as LaTeX numbers them",
         lambda: "Refs: ta 1.1 , fa 1.1 , fm 1.2 , pm 1.3 , c1 1.4 , c2 1.5 , f1 1.6 , f2 1.7 , "
         "p1 1.8 , p2 1.9 , t1 1.10 , t2 1.11 , sa 1.12a , sb 1.12b , scb 1.12 , st 1.2 , "
         "st1 1.2a , st2 1.2b , res 1.3 , pd 1.4 , after 1.5 , one 1.6 , only 1.6a ."
         in text("review", "book")
         and "Note: standard errors in parentheses." in text("review", "book")
         and re.search(r'<table[^>]*\sid="t:pd"', page("review", "book"))
         and re.search(r'<table[^>]*\sid="t:a"', page("review", "book"))
         and re.search(r'<figure id="f:a">\s*<div class="center">\s*<img', page("review",
                                                                                "book"))),
        ("a float cut between captions opens no wrapper again with nothing in it, and a "
         "label in a caption leaves its float's id as it is",
         lambda: not re.search(r'<div class="center">\s*</div>', page("review", "book"))
         and 'id="f:sa"' in page("review", "book") and 'f:sa-1' not in page("review", "book")),
        ("floatrow's boxes are figures and tables with their captions, and multicols's "
         "column count isn't printed, its preface before the columns",
         lambda: "Refs: fr1 1.1 , fr2 1.2 , tb 1.1 ." in text("floatrow", "book")
         and "One Before the columns. Text in the columns." in text("floatrow", "book")),
        ("KOMA and amsbook number the front and back matter as they do",
         lambda: "Refs: about 1 ; ff 1 ; intro 1.1 ; extra 1 ; bf 1 ." in text("koma", "book")
         and "Refs: about 1 ; ff 1 ; intro 1 ; extra 1 ; bf 1 ." in text("amsfront", "book")),
        ("a chapter's page is titled by its chapter, not a \\chapter* after it or its "
         "bibliography, and a PDF title's escapes are the characters they make",
         lambda: title("titled", "ch1") == "Alpha" and title("titled", "ch2") == "Beta"
         and html_module.unescape(title("escaped", "notes") or "")
         == "Algebra & Geometry: Na\u00efve Notes"),
        ("a page whose headings are all at the top is titled by the PDF title the document "
         "gives hyperref, or by its file's name as words, and the run says which",
         lambda: title("notes", "class-notes") == "Calculus 2 Notes"
         and title("untitled", "class-notes") == "Class Notes"
         and "titled by the PDF title" in said["notes"]
         and 'class-notes as "Class Notes"' in said["untitled"]),
    ]


CASES = [("a LaTeX book", case_book), ("two masters", case_masters),
         ("one file", case_single), ("an unbuilt book", case_unbuilt),
         ("the source target", case_source), ("a book with fonts of its own", case_own_fonts),
         ("a LaTeX book's PDF, from its own LaTeX", case_book_pdf),
         ("the PDF build's copy of the book", case_pdf_copy),
         ("the book's other masters", case_other_masters),
         ("calls of the book's macros for an image, as the review found them",
          case_review_macros),
         ("the latex target", case_latex_target),
         ("a book of documents built on their own", case_documents),
         ("the pieces the copies take", case_pieces),
         ("a book made its own way, as OpenIntro is", case_customized),
         ("a book in parts, numbered as LaTeX numbers it", case_parts),
         ("a book's citations and its bibliography", case_bibliography),
         ("floats, classes, and titles as LaTeX has them", case_floats),
         ("a book set with packages tagging can't take", case_unsupported),
         ("a book too big for TeX", case_capacity)]


def main():
    parser = argparse.ArgumentParser(
        description="Check LaTeX as a source, end to end.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    parser.add_argument("--case", action="append", default=[],
                        help="run only the cases whose label holds this "
                        "(\"source target\", say); may be given again")
    arguments = parser.parse_args()
    cases = [(label, case) for label, case in CASES
             if not arguments.case or any(c in label for c in arguments.case)]
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    work = tempfile.mkdtemp(prefix="latex-tests-")
    failed = 0
    lacking = tex_ready()
    if lacking:
        print(f"  FAIL  {lacking}")
        failed += 1
    try:
        for label, case in cases:
            directory = os.path.join(work, re.sub(r"[^\w-]+", "-", label))
            try:
                checks = case(directory)
            except Exception as exc:
                print(f"  ERROR {label}: {exc}")
                failed += 1
                continue
            for name, predicate in checks:
                try:
                    passed = bool(predicate())
                except Exception as exc:
                    passed, name = False, f"{name}  ({exc})"
                print(("  ok    " if passed else "  FAIL  ") + name)
                failed += not passed
    finally:
        if arguments.keep:
            print(f"\nOutput left in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n{failed} check(s) failed across {len(cases)} case(s)"
          if failed else "\nall LaTeX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
