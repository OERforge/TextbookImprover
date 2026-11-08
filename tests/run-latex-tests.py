#!/usr/bin/env python3
"""
run-latex-tests.py -- check LaTeX as a source, end to end through convert.py.

    python3 tests/run-latex-tests.py           # run every case
    python3 tests/run-latex-tests.py --keep    # leave the output in place

Needs Pandoc 3.9 or later. The drawing and the PDF image need a LaTeX
engine and pdftocairo; without them those checks are skipped and say so.
So are the checks that build with TeX where its LaTeX is too old for the
PDF target or it lacks a package the books or their PDFs load
(tex_unready), and those of an SVG picture made a PDF without
rsvg-convert (why_no_svg), each said first with what installs it: a
machine to set up, not the code failing. The cases of images that can't
be made SVG or PDF run with Pandoc, Python, and file alone on their PATH
(tools_alone), so they check the same everywhere.

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
import contextlib
import csv
import hashlib
import html as html_module
import io
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
sys.path.insert(0, HERE)
import parallel  # noqa: E402

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


def type3_pdf(path, glyph="minus.case"):
    """A one-page PDF whose text is a Type 3 font's glyph known by its name
    alone, glyph, in its encoding's Differences, with no ToUnicode entry, as
    Ghostscript writes matplotlib's EPS's minus sign, written by hand."""
    stream = b"BT /F1 12 Tf 4 4 Td (\\000) Tj ET\n"
    proc = b"500 0 0 0 400 600 d1 0 250 400 100 re f\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 20 20] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
               b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 500 600] "
               b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << /%s 6 0 R >> "
               b"/Encoding << /Type /Encoding /Differences [0 /%s] >> /FirstChar 0 "
               b"/LastChar 0 /Widths [500] >>" % (glyph.encode(), glyph.encode()),
               b"<< /Length %d >>\nstream\n" % len(proc) + proc + b"endstream"]
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
        ["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet"], cwd=work,
        capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)



def sample_text(work):
    """project-sample.yaml's values as YAML, without the description above
    each setting, which a check reading the text would otherwise see."""
    path = os.path.join(work, "project-sample.yaml")
    if not os.path.exists(path):
        return ""
    import yaml
    return yaml.safe_dump(yaml.safe_load(read(work, "project-sample.yaml")),
                          sort_keys=False, allow_unicode=True)

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
    """The Word file's display formula in a list item is set as the
    item's other later paragraphs are, so reading it keeps the item whole:
    numbered with no marker, as Pandoc's writer numbers them before 3.13,
    or unnumbered and lined up with the item's text, as it sets them from
    3.13 on, the first formula's item's at the list's first level (720), the
    second's in a quotation inside it a quote step further (1200)."""
    import zipfile
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import docxtarget
    with zipfile.ZipFile(os.path.join(work, "word", "one.docx")) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    paragraphs = re.findall(r"<w:p>.*?</w:p>", xml, re.S)
    formula = [p for p in paragraphs if "oMathPara" in p and "x" in p]
    if docxtarget.continuations_indented():
        return [docxtarget.continuation_left(p) for p in formula] == [720, 1200] \
            and "tiqMath" not in xml
    return formula and all('<w:numId w:val="1000"' in p for p in formula) \
        and "tiqMath" not in xml


# What the suite's books need from TeX beyond what LaTeX's tagging and
# Pandoc's template do (docs/installation.md): each TeX Live package, by a
# file it holds. Found on TinyTeX's smaller bundle (TinyTeX-1), from every
# file TeX read in a run of the suite that passed (-recorder) and then by
# what each build that still failed couldn't find; a package a copy is
# made without, and so never reads, can still be one LaTeX needs found
# (2026-10-08). With the packages a fuller TeX Live has that its smaller
# schemes may not, which the books load too (amsfonts to tools), named
# after a TeX Live install lacked some; and cancel and pict2e, for the
# terms the book and the struck-out case strike out, which neither TinyTeX
# nor TeX Live's medium scheme has.
SUITE_TEX = [("amsfonts", "amssymb.sty"), ("amsmath", "amsmath.sty"),
             ("babel-english", "english.ldf"), ("caption", "caption.sty"),
             ("framed", "framed.sty"), ("geometry", "geometry.sty"), ("tools", "enumerate.sty"),
             ("fancyhdr", "fancyhdr.sty"), ("grfext", "grfext.sty"),
             ("luatex85", "luatex85.sty"), ("mdframed", "mdframed.sty"),
             ("pgf", "tikz.sty"), ("preview", "preview.sty"), ("soul", "soul.sty"),
             ("tabto-ltx", "tabto.sty"), ("tex-gyre", "texgyreheros-regular.otf"),
             ("titlesec", "titlesec.sty"), ("ulem", "ulem.sty"),
             ("wasysym", "wasysym.sty"), ("wrapfig", "wrapfig.sty"),
             ("cancel", "cancel.sty"), ("pict2e", "pict2e.sty")]
# What every tagged PDF loads, the suite's from the book's own LaTeX and
# from its pages, which TinyTeX lacks (docs/installation.md's first tlmgr
# line), by a file each holds: LaTeX's tagging code, latex-lab's, which
# \DocumentMetadata reads, and tagpdf; luamml, for the formulas' MathML;
# and selnolig, which Pandoc's template loads under LuaLaTeX for a book
# with a language, and luatexbase, which selnolig loads.
PDF_TEX = [("latex-lab", "documentmetadata-support.ltx"), ("tagpdf", "tagpdf.sty"),
           ("luamml", "luamml.sty"), ("luatexbase", "luatexbase.sty"),
           ("selnolig", "selnolig.sty")]
TEX_UNREADY = []


def tex_unready():
    """Why the checks that build with TeX skip on this one, or None: its
    LaTeX too old for the PDF target to build with
    (latexbuild.MINIMUM_LATEX), which the run refuses, or a package the
    suite's books or their PDFs load (SUITE_TEX, PDF_TEX) missing, on which
    LaTeX stops. That's a
    machine to set up, not the code failing, as a machine without TeX is,
    whose checks skip for the program each runs. None where there's no
    TeX, or no kpsewhich to ask. Asked once a run: the cases run side by
    side are told in LATEX_TESTS_TEX (main)."""
    if TEX_UNREADY:
        return TEX_UNREADY[0]
    if "LATEX_TESTS_TEX" in os.environ:
        TEX_UNREADY.append(json.loads(os.environ["LATEX_TESTS_TEX"]))
        return TEX_UNREADY[0]
    why = None
    if (shutil.which("lualatex") or shutil.which("pdflatex")) and shutil.which("kpsewhich"):
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import latexbuild
        if shutil.which(latexbuild.ENGINE):
            why = latexbuild.latex_problem(lambda message: None)
        missing = [package for package, name in SUITE_TEX + PDF_TEX
                   if not subprocess.run(["kpsewhich", name], capture_output=True, text=True,
                                         stdin=subprocess.DEVNULL).stdout.strip()]
        if missing and not why:
            why = ("TeX lacks " + ", ".join(missing) + ", which the suite's books and their "
                   "PDFs load (" + latexbuild.tlmgr_command("install " + " ".join(missing))
                   + ")")
    TEX_UNREADY.append(why)
    return why


def why_no_tex(missing, *programs):
    """Why a check that runs programs, TeX's, skips here, or None: missing,
    where one of them isn't installed, or TeX not ready (tex_unready)."""
    if not all(shutil.which(program) for program in programs):
        return missing
    return tex_unready()


def ran(done):
    """Whether a run with a PDF target went through: its exit status 0, or
    any where TeX can't build the PDF here (why_no_tex), the run's source
    target's copy and words checked apart."""
    return done.returncode == 0 or why_no_tex("", "lualatex", "latexmk") is not None


def why_no_drawings():
    """Why the book's drawings aren't made here, or None: they need pdfLaTeX
    or LuaLaTeX, pdftocairo, and TeX ready (tex_unready)."""
    if not ((shutil.which("pdflatex") or shutil.which("lualatex"))
            and shutil.which("pdftocairo")):
        return "no LaTeX or pdftocairo: drawings not rendered"
    return tex_unready()


def why_no_status():
    """Why the run can't check a book's packages against LaTeX's tagging
    status list here, or None: the case writes the list beside its book,
    and the run finds it with TeX's kpsewhich."""
    return None if shutil.which("kpsewhich") \
        else "no kpsewhich, which TeX has, to find the tagging status list with"


def why_no_svg():
    """Why an SVG picture isn't made a PDF here, or None: the latex target
    and a PDF make it one with rsvg-convert."""
    return None if shutil.which("rsvg-convert") \
        else "no rsvg-convert to make an SVG picture a PDF (sudo apt install librsvg2-bin)"


def built_or_why(ok, said):
    """ok, and when it isn't, the run's own words on why its LaTeX build
    stopped, so a failing check says what to do about it."""
    if not ok:
        # LaTeX's error, "! ..." or, with -file-line-error, "./book.tex:518:
        # ...", and the "l.518 ..." line that shows where.
        error = re.compile(r"^(?:! |[^:\s][^:]*\.\w+:\d+: |l\.\d+ )")
        why = [line.strip() for line in said.splitlines()
               if error.match(line) or "can't find" in line or "wasn't built" in line]
        for line in why[:8]:
            print("    " + line[:300])
    return ok


SKIPPED = []
SKIPS = [0]


def skip(reason):
    """A check that can't run here: reported, and passing. The check's line
    says skip, and the first check skipped for a reason says it."""
    SKIPS[0] += 1
    if reason not in SKIPPED:
        SKIPPED.append(reason)
        print(f"        {reason}")
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
    sample = yaml.safe_load(read(work, "project-sample.yaml")) \
        if os.path.exists(os.path.join(work, "project-sample.yaml")) else {}
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
         if not why_no_drawings() else skip(why_no_drawings())),
        ("a drawing is rendered whole and keeps its figure's caption",
         lambda: re.search(r'<figure[^>]*>\s*(<div class="center">\s*)?'
                           r'<img\s+src="rendered/ch1/one-1\.svg"', one) and "A line" in one
         if not why_no_drawings() else skip(why_no_drawings())),
        ("a PDF image is made an SVG",
         lambda: 'src="rendered/img/diagram.svg"' in one
         if shutil.which("pdftocairo") else skip("no pdftocairo to make a PDF image an SVG "
                                                 "(sudo apt install poppler-utils)")),
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


def case_layout_tables(work):
    """A table tagged as a division of paragraphs (table/tagging=div), as
    the PDF target and the latex target tag a layout table, is read as a
    layout table; a box tagged so, as a source copy writes one, is still a
    box, and a table tagged nothing is a data table."""
    os.makedirs(work)
    with open(os.path.join(work, "steps.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{longtable}\n\\begin{document}\n"
                 "Steps:\n\n"
                 "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi\n\n"
                 "{\\def\\LTcaptype{none} % do not increment counter\n"
                 "\\begin{longtable}[]{@{}ll@{}}\n\\toprule\\noalign{}\n\\endhead\n"
                 "\\bottomrule\\noalign{}\n\\endlastfoot\n"
                 "Subtract 3 from each side. & $x = 4$ \\\\\n"
                 "Divide each side by 2. & $x = 2$ \\\\\n\\end{longtable}\n}\n\n}\n\n"
                 "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi"
                 "\\begin{tabular}{p{4in}}\n\\textbf{Example} \\\\\n"
                 "A box around a passage, long enough that it reads as a passage of prose. \\\\\n"
                 "\\end{tabular}}\n\n"
                 "\\begin{tabular}{ll}\nMultiply each side by 4. & $x = 8$ \\\\\n"
                 "Subtract 1 from each side. & $x = 7$ \\\\\n\\end{tabular}\n"
                 "\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    said = result.stdout + result.stderr
    page = read(work, "html", "steps.html") \
        if os.path.exists(os.path.join(work, "html", "steps.html")) else ""
    missing = read(work, "table-captions-missing.csv") \
        if os.path.exists(os.path.join(work, "table-captions-missing.csv")) else ""
    tables = re.findall(r"(<div class=\"table-wrapper\"[^>]*>\s*)?<table([^>]*)>(.*?)</table>",
                        page, re.S)
    return [
        ("a table tagged as a division of paragraphs is a layout table: role "
         "presentation, no scroll region, no caption asked of it, and the run says so",
         lambda: [(bool(w), a, "Subtract 3" in t) for w, a, t in tables]
         == [(False, ' role="presentation"', True), (True, "", False)]
         and "Subtract 3" not in missing and "Multiply" in missing
         and "1 table tagged as a division of paragraphs read as a layout table" in said),
        ("a box tagged so, as a source copy writes one, is still a box",
         lambda: re.search(r'<div class="box">\s*<p><strong>Example</strong>', page)
         is not None),
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


def case_language(work):
    """A LaTeX book's pages are in the language its preamble gives, babel's
    main language here, in a project in another."""
    os.makedirs(work)
    with open(os.path.join(work, "notas.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage[english,spanish]{babel}\n"
                 "\\begin{document}\n\\section*{Repaso}\nUn texto.\n\\end{document}\n")
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.notas\n  title: Notas\n"
                 "  language: en\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    page = os.path.join(work, "html", "notas.html")
    drafted = os.path.join(work, "languages-new.csv")
    return [
        ("a LaTeX book's page is in babel's main language, its last",
         lambda: os.path.exists(page)
         and re.search(r'<html\b[^>]*\slang="es"', read(work, "html", "notas.html"))),
        ("and the run drafts its row, found in its preamble",
         lambda: os.path.exists(drafted)
         and "notas,es,notas.tex: its preamble,TI," in read(work, "languages-new.csv")
         and "notas in es (its file)" in result.stdout + result.stderr),
    ]


def case_inline_code(work):
    """Inline code, listings' \\lstinline, minted's \\mintinline, and
    fancyvrb's \\Verb, as written in the pages, which the reading's repairs
    took for LaTeX: an environment the book defines in it and a boolean,
    and \\input, which stopped the reader once the copy braced it, the
    brace form's too, to its first }, as the reader reads it; each code to
    its end on its line for every repair (skip_spans), its options and
    minted's language with it, but not a command of another name, nor the
    command's name in a definition's code, nor \\verb or inline code its
    line doesn't close; and the author's files as they were."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexsource
    os.makedirs(work)
    files = {
        "book.tex": "\\documentclass{book}\n\\usepackage{listings,minted,fancyvrb,ifthen}\n"
                    "\\newboolean{x}\n\\newenvironment{rouge}{}{}\n"
                    "\\begin{document}\n\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\n"
                   "A \\lstinline|\\begin{rouge}x\\end{rouge}| fin.\n\n"
                   "B \\lstinline[columns=fixed]|\\setboolean{x}{true}| fin.\n\n"
                   "C \\lstinline|\\input chapitre| fin.\n\n"
                   "D \\lstinline{\\input chapitre} fin.\n\n"
                   "E \\mintinline{text}|\\begin{rouge}x\\end{rouge}| fin.\n\n"
                   "F \\Verb|\\begin{rouge}x\\end{rouge}| fin.\n",
    }
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.code\n  title: Code\n"
                 "  language: fr\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    page = read(work, "html", "one.html") if os.path.exists(
        os.path.join(work, "html", "one.html")) else ""
    text = re.sub(r"\s+", " ", page)

    def code(letter, words, attributes=""):
        """Whether the page has the paragraph of letter's code, as words."""
        return re.search(r"<p>\s*%s <code%s>%s</code> fin\.\s*</p>" % (
            letter, attributes, re.escape(words)), text) is not None

    def spans(words):
        return [words[start:end] for start, end in latexsource.skip_spans(words)]
    return [
        ("a LaTeX book is read whose inline code holds \\input, which stopped the reader",
         lambda: result.returncode == 0 and bool(page)),
        ("inline code is as written in the pages, an environment of the book's and a "
         "boolean in it, and \\input, its brace form too",
         lambda: code("A", "\\begin{rouge}x\\end{rouge}")
         and code("B", "\\setboolean{x}{true}")
         and code("C", "\\input chapitre") and code("D", "\\input chapitre")
         and code("E", "\\begin{rouge}x\\end{rouge}", ' class="text"')
         and code("F", "\\begin{rouge}x\\end{rouge}")),
        ("each is code to its end on its line, as the reader reads it, its options and "
         "minted's language with it, but not a command of another name, nor the command's "
         "name in a definition's code, nor \\verb or inline code its line doesn't close",
         lambda: spans("a \\lstinline[language=C]|x| b") == ["\\lstinline[language=C]|x|"]
         and spans("a \\lstinline {x{y} b") == ["\\lstinline {x{y}"]
         and spans("a \\mintinline[o]{py}{x} b") == ["\\mintinline[o]{py}{x}"]
         and spans("a \\Verb[frame=single]|x| b [c]") == ["\\Verb[frame=single]|x|"]
         and spans("a \\Verb*|x| b") == ["\\Verb*|x|"]
         and spans("a \\lstinline|x") == []
         and spans("\\lstinlinex|y|x \\Verbatim|z|a") == []
         and spans("\\newcommand{\\code}{\\lstinline}\\newcommand{\\v}[1]{\\Verb#1}") == []
         and spans("a \\Verb. b\n\nc. d") == [] and spans("a \\verb|x\ny| b") == []),
        ("and the author's files are as they were",
         lambda: all(read(work, name) == text for name, text in files.items())),
    ]


def case_babel_main(work):
    """A LaTeX book's tagged copy keeps babel's main language the book's, which
    babel takes from \\DocumentMetadata's lang where the book names none
    with main=: main= passed before the class, babel's last language, else
    the class's, so built with LuaLaTeX it's hyphenated as the author's
    build hyphenates it; none where the book names its main language
    itself, with main= or \\babelprovide[main], or its own
    \\DocumentMetadata names the lang, nor once again in a copy made from
    the copy; the run saying so, and naming a book whose main language its
    options don't say. And a book whose main= names French is in French."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexsource
    import texremediate
    tagged = "  copy:\n    format: source\n    tagging: \"on\"\n"

    def book_at(name, master, language=None, targets=tagged):
        path = os.path.join(work, name)
        os.makedirs(path)
        with open(os.path.join(path, "book.tex"), "w", encoding="utf-8") as fh:
            fh.write(master)
        with open(os.path.join(path, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.main\n  title: A Main Language\n"
                     + (f"  language: {language}\n" if language else ""))
        with open(os.path.join(path, "conversion.yaml"), "w", encoding="utf-8") as fh:
            fh.write("targets:\n" + targets)
        done = convert(path)
        copy = os.path.join(path, "copy", "book.tex")
        return (read(path, "copy", "book.tex") if done.returncode == 0
                and os.path.exists(copy) else ""), done.stdout + done.stderr

    body = "\\begin{document}\nZucker, an organization.\n\\end{document}\n"
    german, german_said = book_at(
        "german", "\\documentclass{article}\n\\usepackage[english,ngerman]{babel}\n" + body)
    british, _ = book_at(
        "british", "\\documentclass{article}\n\\usepackage[english,british,silent]{babel}\n"
        + body, language="en-US")
    french, _ = book_at(
        "french", "\\documentclass{article}\n\\usepackage[main=french,english]{babel}\n" + body,
        targets=tagged + "  html:\n    format: html\n")
    unknown, unknown_said = book_at(
        "unknown", "\\documentclass[ngerman,latin]{article}\n\\usepackage{babel}\n" + body,
        language="de")
    again = ""
    if german:
        again, _ = book_at("again", german)
    passed = "\\PassOptionsToPackage{main=%s}{babel}\n\\documentclass"

    def head(text):
        return text[:text.find("\\documentclass")] if "\\documentclass" in text else ""

    def tagged_copy(master, language, said=None):
        """The master as a tagged copy has it; said, given, gets the counts."""
        texts = {"book.tex": master}
        counts = texremediate.tag(texts, "book.tex", language, mathml=False)
        if said is not None:
            said.update(counts)
        return texts["book.tex"]

    def left(master, language, unknown=False):
        """Whether a tagged copy of master passes babel nothing more than the
        book does, and its run says nothing of babel's main language, or,
        unknown, that the lang sets it."""
        said = {}
        return tagged_copy(master, language, said).count("PassOptionsToPackage") \
            == master.count("PassOptionsToPackage") \
            and [key for key in said if key.startswith("babel_main")] \
            == (["babel_main_unknown"] if unknown else [])

    def built(text, wanted):
        """The copy built with LuaLaTeX, as a person builds it, with lines
        that have LaTeX's log name babel's language and hyphenate the words:
        wanted, babel's main language and the words' hyphens (None for any)."""
        why = why_no_tex("no lualatex to build the copy", "lualatex")
        if why:
            return skip(why)
        if not text:
            return False
        tree = os.path.join(work, "build-" + wanted[0])
        os.makedirs(tree, exist_ok=True)
        with open(os.path.join(tree, "book.tex"), "w", encoding="utf-8") as fh:
            fh.write(text.replace("\\begin{document}\n", "\\begin{document}\n"
                                  "\\typeout{MAIN=\\languagename}\n"
                                  "\\showhyphens{Zucker organization}\n"))
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "book.tex"], cwd=tree, capture_output=True, text=True,
                              timeout=300, stdin=subprocess.DEVNULL)
        log = read(tree, "book.log") if os.path.exists(os.path.join(tree, "book.log")) else ""
        return done.returncode == 0 and "MAIN=%s\n" % wanted[0] in log \
            and (wanted[1] is None
                 or re.search(r"\\TU/\S+ %s\b" % re.escape(wanted[1]), log) is not None)

    page = os.path.join(work, "french", "html", "book.html")
    return [
        ("a tagged copy of a book in ngerman, given lang=de, names babel's main language "
         "the book's: main=ngerman passed before its class, its babel line as written",
         lambda: "\\DocumentMetadata{lang=de," in german
         and head(german).endswith("\\PassOptionsToPackage{main=ngerman}{babel}\n")
         and "\\usepackage[english,ngerman]{babel}\n" in german),
        ("and the run says so",
         lambda: "babel given main=ngerman, so its main language is the book's" in german_said),
        ("built with LuaLaTeX, it's set as the author's build sets it: in ngerman, "
         "\"Zucker\" hyphenated Zu-cker, where german, by the 1901 rules, leaves it whole",
         lambda: built(german, ("ngerman", "Zu-cker"))),
        ("a book in British English, in a project in en-US, keeps british, not an option of "
         "babel's own after it, and is hyphenated the British way",
         lambda: head(british).endswith("\\PassOptionsToPackage{main=british}{babel}\n")
         and built(british, ("british", "Zucker or-gan-iz-a-tion"))),
        ("a book whose class names its language, a size, a paper, and an AMS class's option "
         "beside it, gets the class's; one whose language has a modifier, the language; one "
         "whose own \\DocumentMetadata names no language, main= after it",
         lambda: passed % "ngerman" in tagged_copy(
             "\\documentclass[a4paper, % the paper\n  ngerman, 12pt, reqno]{article}\n"
             "\\usepackage{babel}\n" + body, "de")
         and passed % "ngerman" in tagged_copy(
             "\\documentclass{article}\n\\usepackage[english,ngerman.foo]{babel}\n" + body, "de")
         and "\\DocumentMetadata{pdfversion=2.0, tagging=on, lang=de, pdfstandard=ua-2}\n"
         + texremediate.STATIC_FONTS + texremediate.BABEL_MAIN % "ngerman"
         + "\\documentclass" in tagged_copy(
             "\\DocumentMetadata{pdfversion=2.0}\n\\documentclass{article}\n"
             "\\usepackage[ngerman]{babel}\n" + body, "de")),
        ("none where the book names its main language itself, with main=, passed to babel "
         "too, or \\babelprovide[main], or its own \\DocumentMetadata names the lang",
         lambda: french and "PassOptionsToPackage" not in french
         and left("\\PassOptionsToPackage{main=ngerman}{babel}\n\\documentclass{article}\n"
                  "\\usepackage[english,ngerman]{babel}\n" + body, "de")
         and left("\\documentclass{article}\n\\usepackage[english]{babel}\n"
                  "\\babelprovide[import, main]{british}\n" + body, "en-US")
         and left("\\documentclass{article}\n\\usepackage{babel}\n"
                  "\\babelprovide[import, main]{british}\n" + body, "en-US")
         and left("\\DocumentMetadata{lang=de}\n\\documentclass{article}\n"
                  "\\usepackage[ngerman]{babel}\n" + body, "de")),
        ("a book whose main= names French is in French, its copy's lang too, and builds; "
         "and one whose last language has a modifier is in that language, but not one whose "
         "main= has one, a language babel doesn't load",
         lambda: latexsource.preamble_language(
             "\\usepackage[english,spanish.mexico]{babel}") == "es"
         and latexsource.preamble_language(
             "\\usepackage[main=ngerman.foo,english]{babel}") == ""
         and "\\DocumentMetadata{lang=fr," in french and os.path.exists(page)
         and re.search(r'<html\b[^>]*\slang="fr"', read(work, "french", "html", "book.html"))
         and built(french, ("french", None))),
        ("where the class's language can't be told, one the reading doesn't know after it, "
         "nothing is passed, and the run says the lang sets babel's main language; nor where "
         "babel's is a macro, which isn't defined before the class",
         lambda: unknown and "PassOptionsToPackage" not in unknown
         and "babel's main language left to \\DocumentMetadata's lang=de, which may not be "
         "the book's" in unknown_said
         and left("\\documentclass{article}\n\\newcommand\\mainlang{ngerman}\n"
                  "\\usepackage[english,\\mainlang]{babel}\n" + body, "de", unknown=True)),
        ("a copy made from the copy has main= once",
         lambda: again and again.count("\\PassOptionsToPackage{main=ngerman}{babel}") == 1),
    ]


def case_babel_reading(work):
    """A LaTeX book's passages in another language by babel's commands the
    reader stopped on, or dropped, read into its pages in their language:
    \\foreignlanguage with babel's option, \\foreignlanguage whose words
    hold a paragraph break, a blank line or \\par, the paragraphs as LaTeX
    sets them, the words before and after in them, or a list, as a
    division, the book's own list environment too; a note's paragraph
    break, a blank line after \\\\, a formula, breqn's among them, an
    environment in a formula, and environments the book defines as text,
    each way it defines them, in them, as the reader read them; a
    paragraph that ends in a comment; and babeltags' \\textfr, which the
    master's preamble declares, but not a tag whose command the book
    defines again, each way the reader reads; the run saying what it read
    so, the author's files as they were, and a \\captionof's paragraph
    found as before."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexsource
    os.makedirs(work)
    files = {
        "book.tex": "\\documentclass{book}\n\\usepackage[ngerman,french,english]{babel}\n"
                    "\\usepackage{amsmath}\n\\usepackage{breqn}\n"
                    "\\babeltags{fr = french, de = ngerman, en = english, fra = french, "
                    "deu = ngerman, allem = ngerman, franc = french}\n"
                    "\\renewcommand{\\textde}[1]{\\emph{\\foreignlanguage{ngerman}{#1}}}\n"
                    "\\def\\texten#1{\\emph{\\foreignlanguage{english}{#1}}}\n"
                    "\\RenewDocumentCommand{\\textfra}{m}{\\emph{\\foreignlanguage{french}{#1}}}\n"
                    "\\DeclareRobustCommand{\\textdeu}[1]{\\emph{\\foreignlanguage{ngerman}{#1}}}\n"
                    "\\newcommand{\\myallem}[1]{\\emph{\\foreignlanguage{ngerman}{#1}}}\n"
                    "\\RenewCommandCopy\\textallem\\myallem\n"
                    "\\RenewCommandCopy{\\textfranc}{\\myallem}\n"
                    "\\newenvironment{rouge}{}{}\n\\NewEnvironmentCopy{rose}{rouge}\n"
                    "\\NewEnvironmentCopy{myeq}{equation}\n"
                    "\\newenvironment{eqn}{\\begin{equation}}{\\end{equation}}\n"
                    "\\newenvironment{eqnn}{\\begin{eqn}}{\\end{eqn}}\n"
                    "\\newenvironment{enmath}{$}{$}\n\\newenvironment{etoile}{$\\star$ }{}\n"
                    "\\newenvironment{prix}{\\$ }{}\n"
                    "\\newenvironment{gris}{}{}\n\\RenewEnvironmentCopy{gris}{itemize}\n"
                    "\\NewEnvironmentCopy{beige}{itemize}\n\\renewenvironment{beige}{}{}\n"
                    "\\newenvironment{ensuite}{\\\\par la suite, }{}\n"
                    "\\newenvironment*{verte}{}{}\n"
                    "\\NewDocumentEnvironment{bleue}{}{}{}\n\\newenvironment{step2}{}{}\n"
                    "\\newenvironment{points}{\\begin{itemize}}{\\end{itemize}}\n"
                    "\\newenvironment{morepoints}{\\begin{points}}{\\end{points}}\n"
                    "\\newenvironment{remarque}[1][Note]{\\par\\textbf{#1} }{\\par}\n"
                    "\\begin{document}\n\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nA date: \\foreignlanguage[date]{ngerman}{das Wort} here.\n\n"
                   "Words before \\foreignlanguage{french}{la fin du paragraphe.\n\n"
                   "Le d\\'ebut du suivant} and words after.\n\n"
                   "Again \\foreignlanguage{french}{un.\\par Deux} after.\n\n"
                   "A list \\foreignlanguage{french}{pour commencer\n"
                   "\\begin{itemize}\n\\item un point\n\\end{itemize}\npour finir} last.\n\n"
                   "A tag: \\textfr{court} and \\textfr{bref}.\n\n"
                   "A note: \\foreignlanguage{french}{un mot\\footnote{Une note.\n\n"
                   "Son second paragraphe.}} after.\n\n"
                   "A formula: \\foreignlanguage{french}{la formule \\begin{dmath*}x = "
                   "\\begin{cases}0\\\\1\\end{cases}\\end{dmath*} suit} here.\n\n"
                   "A copied formula: \\foreignlanguage{french}{la formule \\begin{myeq}y = "
                   "\\begin{cases}1\\\\2\\end{cases}\\end{myeq} suit} here.\n\n"
                   "A wrapped formula: \\foreignlanguage{french}{la formule \\begin{eqn}z = "
                   "\\begin{cases}3\\\\4\\end{cases}\\end{eqn} suit} here.\n\n"
                   "Wrapped twice: \\foreignlanguage{french}{la formule \\begin{eqnn}w = "
                   "\\begin{cases}5\\\\6\\end{cases}\\end{eqnn} suit} here.\n\n"
                   "A priced list \\foreignlanguage{french}{pour \\begin{prix}\n"
                   "\\begin{itemize}\n\\item cher\n\\end{itemize}\n\\end{prix}\nfin} last.\n\n"
                   "A wrapped matrix: \\foreignlanguage{french}{la matrice \\begin{enmath}"
                   "\\begin{pmatrix} 2 & 0 \\end{pmatrix}\\end{enmath} suit} here.\n\n"
                   "A starred list \\foreignlanguage{french}{pour \\begin{etoile}\n"
                   "\\begin{itemize}\n\\item une\n\\end{itemize}\n\\end{etoile}\nfin} last.\n\n"
                   "A grey list \\foreignlanguage{french}{pour \\begin{gris}\n\\item gris\n"
                   "\\end{gris}\nfin} last.\n\n"
                   "Copied tags: \\textallem{ein Wort} and \\textfranc{un mot}.\n\n"
                   "A matrix: \\foreignlanguage{french}{la matrice $\\begin{pmatrix} 1 & 0 "
                   "\\end{pmatrix}$ suit} here.\n\n"
                   "Its own: \\foreignlanguage{french}{un \\begin{rouge}mot\\end{rouge}, rouge} "
                   "here.\n\n"
                   "Others of its own: \\foreignlanguage{french}{un \\begin{verte}vert"
                   "\\end{verte} \\begin{bleue}bleu\\end{bleue} \\begin{step2}deux"
                   "\\end{step2} \\begin{rose}rose\\end{rose} \\begin{beige}beige"
                   "\\end{beige}} here.\n\n"
                   "A list of its own \\foreignlanguage{french}{pour ouvrir\n"
                   "\\begin{points}\n\\item un autre point\n\\end{points}\npour fermer} last.\n\n"
                   "Its list in its own \\foreignlanguage{french}{pour lancer\n"
                   "\\begin{morepoints}\n\\item un dernier point\n\\end{morepoints}\npour clore} "
                   "last.\n\n"
                   "A remark \\foreignlanguage{french}{avant \\begin{remarque}une remarque"
                   "\\end{remarque} puis} last.\n\n"
                   "A tag of its own: \\textde{das Wort}.\n\n"
                   "Tags of their own: \\texten{a word}, \\textfra{un mot}, and "
                   "\\textdeu{ein Wort}.\n\n"
                   "A poem: \\foreignlanguage{french}{vers un\\\\\n\nvers deux\\\\[1ex]\n\n"
                   "vers trois} after.\n\n"
                   "A space: \\foreignlanguage{french}{vers un\\\\\\\n\nvers deux} after.\n\n"
                   "A turn: \\foreignlanguage{french}{vers un\\\\par la suite} after.\n\n"
                   "Then: \\foreignlanguage{french}{vers un\\begin{ensuite}ici\\end{ensuite}} "
                   "after.\n\n"
                   "A line's note: \\foreignlanguage{french}{vers un\\\\% une note\n\n"
                   "vers deux} after.\n\n"
                   "A comment: \\foreignlanguage{french}{avant.% une note\n\n"
                   "Apr\\`es} after.\n",
    }
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.read\n  title: Read in Languages\n"
                 "  language: en\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    said = result.stdout + result.stderr
    page = read(work, "html", "one.html") if os.path.exists(
        os.path.join(work, "html", "one.html")) else ""
    text = re.sub(r"\s+", " ", page)

    def paragraph(*parts):
        """Whether the page has a paragraph of parts (patterns), in order,
        nothing else."""
        return re.search(r"<p>\s*" + r"\s*".join(parts) + r"\s*</p>", text) is not None

    return [
        ("a LaTeX book is read whose \\foreignlanguage has babel's option, or words that "
         "hold a paragraph break or a list, which stopped the reader",
         lambda: result.returncode == 0 and bool(page)),
        ("\\foreignlanguage[date]'s words are in its language, in their paragraph",
         lambda: paragraph("A date:", '<span lang="de-DE">das Wort</span>', "here.")),
        ("words holding a blank line are a passage in each paragraph LaTeX sets, the words "
         "before and after in them",
         lambda: paragraph("Words before", '<span lang="fr">la fin du paragraphe.</span>')
         and paragraph('<span lang="fr">Le d(?:\u00e9|&#xE9;)but du suivant</span>',
                       "and words after.")),
        ("and so are words holding \\par",
         lambda: paragraph("Again", '<span lang="fr">un.</span>')
         and paragraph('<span lang="fr">Deux</span>', "after.")),
        ("words holding a list are a division in their language, the list in it, and so "
         "are words holding a list environment the book defines, one defined with it, one "
         "whose code ends a paragraph, one copied from itemize over the book's own, or one "
         "whose code holds a formula it closes, or a dollar sign",
         lambda: re.search(r'<div lang="fr">\s*<p>pour commencer</p>\s*<ul>\s*<li>\s*'
                           r'(?:<p>)?un point(?:</p>)?\s*</li>\s*</ul>\s*<p>pour finir</p>\s*'
                           r'</div>', text) is not None
         and re.search(r'<p>A list of its own</p>\s*<div lang="fr">\s*<p>pour ouvrir</p>\s*'
                       r'<ul>\s*<li>\s*(?:<p>)?un autre point(?:</p>)?\s*</li>\s*</ul>\s*'
                       r'<p>pour fermer</p>\s*</div>', text) is not None
         and re.search(r'<p>Its list in its own</p>\s*<div lang="fr">\s*<p>pour lancer</p>\s*'
                       r'<ul>\s*<li>\s*(?:<p>)?un dernier point(?:</p>)?\s*</li>\s*</ul>\s*'
                       r'<p>pour clore</p>\s*</div>', text) is not None
         and re.search(r'<p>A remark</p>\s*<div lang="fr">\s*<p>avant</p>\s*<p><strong>Note'
                       r'</strong> une remarque</p>\s*<p>puis</p>\s*</div>', text) is not None
         and re.search(r'<p>A grey list</p>\s*<div lang="fr">\s*<p>pour</p>\s*<ul>\s*<li>\s*'
                       r'(?:<p>)?gris(?:</p>)?\s*</li>\s*</ul>\s*<p>fin</p>\s*</div>', text)
         is not None
         and re.search(r'<p>A starred list</p>\s*<div lang="fr">\s*<p>pour <math .*?</math></p>'
                       r'\s*<ul>\s*<li>\s*(?:<p>)?une(?:</p>)?\s*</li>\s*</ul>\s*<p>fin</p>\s*'
                       r'</div>', text) is not None
         and re.search(r'<p>A priced list</p>\s*<div lang="fr">\s*<p>pour \$</p>\s*<ul>\s*<li>'
                       r'\s*(?:<p>)?cher(?:</p>)?\s*</li>\s*</ul>\s*<p>fin</p>\s*</div>', text)
         is not None),
        ("babeltags' \\textfr, declared in the master, is a passage in French, where the "
         "reader dropped it with its words",
         lambda: paragraph("A tag:", '<span lang="fr">court</span>', "and",
                           '<span lang="fr">bref</span>.')),
        ("a paragraph break in a note in the words is the note's, and a formula in them, "
         "breqn's, the book's copy of equation, or one the book's own environment opens, "
         "with an environment in it, is in their passage, as the reader read them",
         lambda: re.search(r'<p>\s*A note: <span lang="fr">un mot<a [^>]*>.*?</a></span> '
                           r'after\.</p>', text) is not None
         and re.search(r"<p>Son second paragraphe\.", text) is not None
         and re.search(r'<p>\s*A formula: <span lang="fr">la formule <math .*?<mtable>.*? '
                       r'suit</span> here\.</p>', text) is not None
         and re.search(r'<p>\s*A copied formula: <span lang="fr">la formule .*?<mtable>.*? '
                       r'suit</span> here\.</p>', text) is not None
         and re.search(r'<p>\s*A wrapped formula: <span lang="fr">la formule .*?<mtable>.*? '
                       r'suit</span> here\.</p>', text) is not None
         and re.search(r'<p>\s*A wrapped matrix: <span lang="fr">la matrice <math .*?<mtable>.*? '
                       r'suit</span> here\.</p>', text) is not None
         and re.search(r'<p>\s*Wrapped twice: <span lang="fr">la formule .*?<mtable>.*? '
                       r'suit</span> here\.</p>', text) is not None),
        ("a blank line after \\\\, which the reader reads as a line break, is left to it, "
         "with an option or a comment between too, and so is \\\\par, a line break and a "
         "word; after a control space, a blank line is a paragraph break, the backslash kept "
         "from the brace",
         lambda: paragraph("A poem:", '<span lang="fr">vers un<br />', "vers deux<br />",
                           "vers trois</span>", "after.")
         and paragraph("A line(?:\u2019|&#x2019;)s note:", '<span lang="fr">vers un<br />',
                       "vers deux</span>", "after.")
         and paragraph("A space:", '<span lang="fr">vers un<br />', "(?:\u00a0|&#xA0;)</span>")
         and paragraph('<span lang="fr">vers deux</span>', "after.")
         and paragraph("A turn:", '<span lang="fr">vers un<br />', "par la suite</span>",
                       "after.")
         and paragraph("Then:", '<span lang="fr">vers un<br />', "par la suite, ici</span>",
                       "after.")),
        ("a formula's environment in the words, and those the book defines as text, each "
         "way it defines them, a copy of one, and one defined as text after it was copied "
         "from a list's, are read in the paragraph, as the reader read them",
         lambda: re.search(r'<p>\s*A matrix: <span lang="fr">la matrice .*? suit</span> '
                           r'here\.</p>', text) is not None
         and paragraph("Its own:", '<span lang="fr">un mot, rouge</span>', "here.")
         and paragraph("Others of its own:", '<span lang="fr">un <span>vert</span>',
                       "<span>bleu</span>", "<span>deux</span>", "(?:<span>)?rose(?:</span>)?",
                       "(?:<span>)?beige(?:</span>)?</span>",
                       "here.")),
        ("and a tag whose command the book defines again, each way the reader reads, as "
         "it defines it, one copied from a command written in braces, which the reader drops, "
         "read as \\foreignlanguage",
         lambda: paragraph("A tag of its own:", '<em><span lang="de-DE">das Wort</span></em>.')
         and paragraph("Tags of their own:", '<em><span lang="en">a word</span></em>,',
                       '<em><span lang="fr">un mot</span></em>,', "and",
                       '<em><span lang="de-DE">ein Wort</span></em>.')
         and paragraph("Copied tags:", '<em><span lang="de-DE">ein Wort</span></em>', "and",
                       '<span lang="fr">un mot</span>.')),
        ("a paragraph that ends in a comment, the break after it, is a passage of its own",
         lambda: paragraph("A comment:", '<span lang="fr">avant.</span>')
         and paragraph('<span lang="fr">Apr(?:\u00e8|&#xE8;)s</span>', "after.")),
        ("the run says what it read so",
         lambda: "3 babeltags' command(s) (\\textfr) read as \\foreignlanguage" in said
         and "1 \\foreignlanguage's option(s) ([date]) left out" in said
         and "4 \\foreignlanguage's words holding a paragraph break read" in said
         and "7 \\foreignlanguage's words holding a list or another environment read as "
             "otherlanguage" in said),
        ("and the author's files are as they were",
         lambda: all(read(work, name) == text for name, text in files.items())),
        ("and a \\captionof's paragraph is found as before, its blank line its start",
         lambda: latexsource.captionof_floats(
             "Before.\n\n\n  A picture \\includegraphics{x}\\captionof{figure}{Cap}\n\nAfter.\n",
             {}) == "Before.\n\n\\begin{figure}\n  A picture \\includegraphics{x}"
                   "\\caption{Cap}\\end{figure}\n\nAfter.\n"),
    ]


# A book in en-US whose second chapter, \include-d as ch02.tex, is French by
# languages.csv and defines a macro the fourth uses, and is followed by an
# English file of sections only, in its chapter; whose third, in a folder,
# is Spanish, \input-s a file of the same name, and goes on in the master's
# text after its file, as the pages take it; whose fourth, after a French
# file that opens a part and an English chapter the master sets in it, is
# English, in the part, \input-ing another file of the third's name; and
# whose master's own text, a preface and a chapter it sets between the
# files, is Italian and German.
LANGUAGES_MASTER = (
    "\\documentclass{book}\n\\title{Two Languages}\n\\author{An Author}\n"
    "\\begin{document}\n\\maketitle\nA preface the master sets itself.\n\n"
    "\\include{ch01}\n\\include{ch02.tex}\n\\include{ch02-glossary}\n"
    "\\include{parts/ch03}\nExercises for the third chapter, set in the master.\n\n"
    "\\chapter{Notes}\nNotes the master sets itself.\n\n\\include{part2}\n"
    "\\chapter{Interlude}\nAn interlude the master sets, in English.\n\n"
    "\\include{ch04}\n\\end{document}\n")
LANGUAGES_FILES = {
    "ch01.tex": "\\chapter{Prices}\nPrices rise when demand grows.\n",
    "ch02.tex": "\\chapter{Les prix}\n\\newcommand\\carried{a macro the fourth chapter uses}\n"
                "Les prix montent quand la demande cro\u00eet.\n",
    "ch02-glossary.tex": "\\section{Glossary}\nA glossary in English, after the French "
                         "chapter.\n",
    "part2.tex": "\\part{Deuxi\u00e8me partie}\nUne partie en fran\u00e7ais.\n",
    "parts/ch03.tex": "\\chapter{Los costos}\nLos costos suben.\n\n\\input{exercises/ch03}\n\n"
                      "M\u00e1s costos.\n",
    "exercises/ch03.tex": "Ejercicios.\n",
    "ch04.tex": "\\chapter{Costs}\nCosts come back in English, with \\carried.\n\n"
                "\\input{solutions/ch03}\n",
    "solutions/ch03.tex": "Solutions to the third chapter, in English.\n",
}



def case_inline_breaks(work):
    """A paragraph break in the words of a command the reader reads as
    inlines, which stopped it, read as LaTeX sets it: in a box's (\\mbox,
    \\hbox, \\underline, ulem's \\uline and \\sout), on one line, a blank
    line as a space and \\par as nothing; in a quotation's (\\enquote,
    starred, \\foreignquote, \\hyphenquote), a quotation in each paragraph,
    one inside another's too, but in a box's words as the box's, one
    quotation on its line, and a paragraph of what the reader reads as
    nothing, a vertical space or a page break, no quotation of its own, a
    brace in a comment, \\verb, verbatim, or inline code none of the
    words'; a blank
    line after \\\\ left to the reader, which reads a line break; the run
    saying what it read so, and the author's files as they were."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexsource
    os.makedirs(work)
    files = {
        "book.tex": "\\documentclass{book}\n\\usepackage[normalem]{ulem}\n"
                    "\\usepackage[english,french]{babel}\n\\usepackage{csquotes}\n"
                    "\\begin{document}\n\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\n"
                   "One \\mbox{un.\\par deux.} end.\n\n"
                   "Two \\mbox{un. \\par deux.} end.\n\n"
                   "Three \\hbox{un.\n\ndeux.} end.\n\n"
                   "Four \\underline{un.\\par deux.} end.\n\n"
                   "Five \\uline{un.\n\ndeux.} end.\n\n"
                   "Six \\sout{un.\\par deux.} end.\n\n"
                   "Seven \\enquote{un.\\par deux.} end.\n\n"
                   "Eight \\enquote*{un.\n\ndeux.} end.\n\n"
                   "Nine \\foreignquote{english}{one\n\ntwo} end.\n\n"
                   "Ten \\hyphenquote*{english}{one\n\ntwo} end.\n\n"
                   "Eleven \\enquote{a \\enquote{b\n\nc} d} end.\n\n"
                   "Twelve \\enquote{vers\\\\\n\nun} end.\n\n"
                   "Thirteen \\mbox{\\enquote{un\n\ndeux}} end.\n\n"
                   "Fourteen \\enquote{un.\n\n\\vspace{1ex}\n\ndeux.} end.\n\n"
                   "Fifteen \\enquote{un % }\n\ndeux} end.\n\n"
                   "Sixteen \\enquote{un.\n\n\\pagebreak[4]\n\n\\medbreak\n\ndeux.} end.\n",
    }
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w", encoding="utf-8") as fh:
        fh.write("project:\n  identifier: org.example.breaks\n  title: Breaks\n"
                 "  language: fr\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    said = result.stdout + result.stderr
    page = read(work, "html", "one.html") if os.path.exists(
        os.path.join(work, "html", "one.html")) else ""
    text = re.sub(r"\s+", " ", page)

    def paragraph(*parts):
        """Whether the page has a paragraph of parts (patterns), in order,
        nothing else."""
        return re.search(r"<p>\s*" + r"\s*".join(parts) + r"\s*</p>", text) is not None

    def mark(c):
        """A quotation mark as the page may write it."""
        return "(?:%s|&#x%X;)" % (c, ord(c))

    underline = (r"(?:<u>|<span class=\"underline\">)", r"(?:</u>|</span>)")
    return [
        ("a LaTeX book is read whose box or quotation holds a paragraph break, which "
         "stopped the reader",
         lambda: result.returncode == 0 and bool(page)),
        ("a box's words are on one line, a blank line in them a space and \\par nothing, "
         "the spaces after it TeX's",
         lambda: paragraph("One un\\.deux\\. end\\.")
         and paragraph("Two un\\.(?:\u00a0|&#xA0;)deux\\. end\\.")
         and paragraph("Three un\\.(?:\u00a0|&#xA0;)deux\\. end\\.")
         and paragraph("Four", underline[0] + "un\\.deux\\." + underline[1], "end\\.")
         and paragraph("Five", underline[0] + "un\\. deux\\." + underline[1], "end\\.")
         and paragraph("Six <del>un\\.deux\\.</del> end\\.")),
        ("a quotation's words holding a paragraph break are a quotation in each paragraph, "
         "starred, in another language, and inside another quotation too",
         lambda: paragraph("Seven", mark("\u201c") + "un\\." + mark("\u201d"))
         and paragraph(mark("\u201c") + "deux\\." + mark("\u201d"), "end\\.")
         and paragraph("Eight", mark("\u2018") + "un\\." + mark("\u2019"))
         and paragraph(mark("\u2018") + "deux\\." + mark("\u2019"), "end\\.")
         and paragraph("Nine", mark("\u201c") + '<span lang="en">one</span>' + mark("\u201d"))
         and paragraph(mark("\u201c") + '<span lang="en">two</span>' + mark("\u201d"),
                       "end\\.")
         and paragraph("Ten", mark("\u2018") + '<span lang="en">one</span>' + mark("\u2019"))
         and paragraph("Eleven", mark("\u201c") + "a", mark("\u2018") + "b" + mark("\u2019")
                       + mark("\u201d"))
         and paragraph(mark("\u201c") + mark("\u2018") + "c" + mark("\u2019"), "d"
                       + mark("\u201d"), "end\\.")),
        ("a blank line after \\\\ in a quotation is the reader's line break",
         lambda: paragraph("Twelve", mark("\u201c") + "vers<br />", "un" + mark("\u201d"),
                           "end\\.")),
        ("a quotation's in a box is the box's, one quotation on its line, and a paragraph of "
         "what the reader reads as nothing no quotation",
         lambda: paragraph("Thirteen", mark("\u201c") + "un(?:\u00a0|&#xA0;)deux"
                           + mark("\u201d"), "end\\.")
         and paragraph("Fourteen", mark("\u201c") + "un\\." + mark("\u201d"))
         and re.search(r"</p>\s*<p>\s*" + mark("\u201c") + "deux\\." + mark("\u201d")
                       + r"\s*end\.\s*</p>", text) is not None
         and paragraph("Sixteen", mark("\u201c") + "un\\." + mark("\u201d"))
         and paragraph(mark("\u201c") + "deux\\." + mark("\u201d"), "end\\.")
         and not re.search("<p>" + mark("\u201c") + mark("\u201d") + "</p>", text)),
        ("a brace in a comment in the words isn't one of theirs, nor one in \\verb, verbatim, "
         "or inline code",
         lambda: paragraph("Fifteen", mark("\u201c") + "un ?" + mark("\u201d"))
         and paragraph(mark("\u201c") + "deux" + mark("\u201d"), "end\\.")
         and latexsource.code_brace("{a % }\nb} c", 0) == 9
         and latexsource.code_brace("{a \\verb|}| b} c", 0) == 14
         and latexsource.code_brace("{\\begin{verbatim}}\\end{verbatim}} c", 0) == 33
         and latexsource.code_brace("{a \\lstinline|}| b} c", 0) == 19
         and latexsource.code_brace("{a \\verb|x\n} b", 0) == 12),
        ("the run says what it read so",
         lambda: "7 paragraph break in a box's words (\\mbox, \\underline) read as LaTeX "
                 "sets it" in said
         and "9 quotation's words holding a paragraph break (\\enquote) read as a "
             "quotation in each paragraph" in said),
        ("and the author's files are as they were",
         lambda: all(read(work, name) == text for name, text in files.items())),
    ]

def case_page_languages(work):
    """A LaTeX book's pages in another language than the book's, in its copy
    and in its PDF built from its own files: each \\include-d file's page
    tagged in its language by hooks around reading the file and set back
    after it, in no group, so what a file defines reaches the files after
    it, a file of the same name it \\input-s in it, one another chapter
    \\input-s not; every other file's page in the book's, so an English
    file of sections after a French chapter, or an English chapter after a
    French file that opens a part, isn't French from what's around it; what
    the master sets after the file in the chapter's section in it too, as
    the pages take it, but a chapter the master sets itself in the book's,
    in a French part too; each file as the reading took it, one a master
    in a folder \\include-s with a dot in its name, and of a conditional's
    two the one it took; a document that \\include-s nothing in its
    page's language whole, its \\DocumentMetadata's; a page of the
    master's own text named, since no file of its own holds it; the same
    in a copy without tagging, which builds; none in a book that declares
    no language for pages in the default, nor for pages in its files'
    language, which its copy is in, or in its preamble's region of the
    default's language; the run's note on them naming no PDF of the whole
    book where it's built from the book's own files; and a copy made from
    a copy given the languages decided now, its block replaced."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import texremediate
    why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")

    def book_at(path, files, rows, targets, language="en-US", exists_ok=False):
        os.makedirs(path, exist_ok=exists_ok)
        for name, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(path, name)), exist_ok=True)
            with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(path, "languages.csv"), "w", encoding="utf-8") as fh:
            fh.write("source,language,found,drafted-by,reviewed\n" + rows)
        with open(os.path.join(path, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.languages\n  title: Two Languages\n"
                     + (f"  language: {language}\n" if language else ""))
        with open(os.path.join(path, "conversion.yaml"), "a", encoding="utf-8") as fh:
            fh.write("targets:\n" + targets)
        done = convert(path)
        return done.returncode, done.stdout + done.stderr

    copies = ("  copy:\n    format: source\n    tagging: \"on\"\n"
              "  plain:\n    format: source\n    tagging: \"off\"\n")
    files = dict(LANGUAGES_FILES, **{"book.tex": LANGUAGES_MASTER})
    rows = "ch02,fr,,,\nch03,es,,,\nbook-1,de,,,\nbook,it,,,\npart2,fr,,,\n"
    book = os.path.join(work, "book")
    status, said = book_at(book, files, rows, copies)
    master = read(book, "copy", "book.tex") if status == 0 else ""
    plain = read(book, "plain", "book.tex") if status == 0 else ""
    hooks = ("\\ExplSyntaxOff\n\\TIQbooklanguage{en-US}\n\\TIQfilelanguage{/ch01.tex}{en-US}\n"
             "\\TIQfilelanguage{/ch02.tex}{fr}\n\\TIQfilelanguage{/ch02-glossary.tex}{en-US}\n"
             "\\TIQfilelanguage{parts/ch03.tex}{es}\n\\TIQfilelanguage{/part2.tex}{fr}\n"
             "\\TIQfilelanguage{/ch04.tex}{en-US}\n")

    # The copy made from the copy, laid over the author's tree, with ch02 in
    # Canadian French and no row for ch03.
    again = os.path.join(work, "again")
    laid = dict(files)
    if status == 0:
        laid.update({name: read(book, "copy", name) for name in files})
    again_status, again_said = book_at(again, laid, "ch02,fr-CA,,,\n",
                                       "  copy:\n    format: source\n    tagging: \"on\"\n")
    again_master = read(again, "copy", "book.tex") if again_status == 0 else ""

    # A book that declares no language, its pages in the default.
    plainly = os.path.join(work, "undeclared")
    plainly_status, _ = book_at(plainly, files, "",
                                "  copy:\n    format: source\n    tagging: \"on\"\n", None)
    plainly_master = read(plainly, "copy", "book.tex") if plainly_status == 0 else ""

    # One that declares no language whose files say French: its copy in
    # French, every page with it.
    french = os.path.join(work, "french")
    french_status, french_said = book_at(
        french, dict(files, **{"book.tex": LANGUAGES_MASTER.replace(
            "\\documentclass{book}\n", "\\documentclass{book}\n\\usepackage[french]{babel}\n")}),
        "", "  copy:\n    format: source\n    tagging: \"on\"\n", None)
    french_master = read(french, "copy", "book.tex") if french_status == 0 else ""

    # One in American English by babel, in the default's English: none either.
    american = os.path.join(work, "american")
    american_status, american_said = book_at(
        american, dict(files, **{"book.tex": LANGUAGES_MASTER.replace(
            "\\documentclass{book}\n", "\\documentclass{book}\n\\usepackage[american]{babel}\n")}),
        "", copies, None)
    american_copies = [read(american, target, "book.tex") if american_status == 0 else ""
                       for target in ("copy", "plain")]

    # Editions: a master in a folder that \include-s a file with a dot in
    # its name, and the instructor's answers or the student's by a
    # conditional, the reading taking the instructor's, Spanish, and then
    # an index, in the book's language, LaTeX's back matter closing the
    # answers' section.
    editions = os.path.join(work, "editions")
    os.makedirs(editions)
    with open(os.path.join(editions, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  latex:\n    main: src/book.tex\n")
    editions_status, editions_said = book_at(editions, {
        "src/book.tex": "\\documentclass{book}\n\\usepackage{ifthen}\n\\newboolean{instructor}\n"
                        "\\setboolean{instructor}{true}\n\\title{Editions}\n\\author{An Author}\n"
                        "\\begin{document}\n\\maketitle\n\\include{week1}\n\\include{week1.5}\n"
                        "\\ifthenelse{\\boolean{instructor}}{\\include{instructor/answers}}"
                        "{\\include{student/answers}}\n\\backmatter\n\\begin{theindex}\n"
                        "\\item apple, 1\n\\end{theindex}\n\\end{document}\n",
        "src/week1.tex": "\\chapter{Week one}\nThe first week.\n",
        "src/week1.5.tex": "\\chapter{Semaine un et demi}\nUne semaine en fran\u00e7ais.\n",
        "src/instructor/answers.tex": "\\chapter{Respuestas}\nLas respuestas del profesor.\n",
        "src/student/answers.tex": "\\chapter{Answers}\nThe student's answers.\n"},
        "week1.5,fr,,,\nanswers,es,,,\n",
        "  copy:\n    format: source\n    tagging: \"on\"\n"
        + ("" if why else "  pdf:\n    format: pdf\n"), exists_ok=True)
    editions_master = read(editions, "copy", "src", "book.tex") if editions_status == 0 else ""

    # The PDF from the book's own files, and a document that \include-s
    # nothing, Spanish whole.
    built = {}
    if not why:
        built["pdf-book"] = book_at(os.path.join(work, "pdf-book"), files, rows,
                                    "  pdf:\n    format: pdf\n")
        built["notes"] = book_at(
            os.path.join(work, "notes"),
            {"notes.tex": "\\documentclass{book}\n\\begin{document}\n\\chapter{Repaso}\n"
                          "Un texto.\n\\end{document}\n"},
            "notes,es,,,\n", "  pdf:\n    format: pdf\n" + copies)

    def tags(name, pdf, path=None):
        """[(H1, H2, or P, its /Lang or the nearest element's around it, or
        the catalog's)] in the structure's order, from the first heading on
        (an article's section is an H1), of the PDF at path, else name's
        pdf; None where pikepdf isn't installed."""
        try:
            import pikepdf
        except ImportError:
            return None
        path = path or os.path.join(work, name, "pdf", pdf)
        if not os.path.exists(path):
            return []
        out = []
        with pikepdf.open(path) as done:
            tree = done.Root.StructTreeRoot
            roles = {str(k): str(v) for k, v in dict(tree.get("/RoleMap", {})).items()}

            def walk(node, around):
                kids = node.get("/K")
                for kid in (kids if isinstance(kids, pikepdf.Array) else
                            [] if kids is None else [kids]):
                    if isinstance(kid, pikepdf.Dictionary) and "/S" in kid:
                        lang = str(kid.Lang) if "/Lang" in kid else around
                        kind = roles.get(str(kid.S), str(kid.S))
                        if kind in ("/H1", "/H2", "/P"):
                            out.append((kind[1:], lang))
                        walk(kid, lang)
            walk(tree, str(done.Root.get("/Lang")))
        first = next((i for i, (kind, _) in enumerate(out) if kind != "P"), len(out))
        return out[first:]

    def pdf_check(name, pdf, expected, status=None):
        if why:
            return skip(why)
        found = tags(name, pdf)
        if found is None:
            return skip("no pikepdf to read the PDF's structure")
        return (built[name][0] if status is None else status) == 0 and found == expected

    def text_of(name, pdf):
        if why:
            return None
        if not shutil.which("pdftotext"):
            return None
        path = os.path.join(work, name, "pdf", pdf)
        return subprocess.run(["pdftotext", path, "-"], capture_output=True,
                              text=True).stdout if os.path.exists(path) else ""

    def builds(folder, name):
        """Whether a copy without tagging, the languages in it, builds as
        the author's own does, with pdfLaTeX."""
        if not os.path.exists(os.path.join(folder, name)):
            return False
        done = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode",
                               "-halt-on-error", name], cwd=folder,
                              capture_output=True, text=True, timeout=300,
                              stdin=subprocess.DEVNULL)
        return done.returncode == 0

    def guarded():
        if why:
            return skip(why)
        notes = os.path.join(work, "notes", "plain")
        text = read(notes, "notes.tex") if os.path.exists(os.path.join(notes, "notes.tex")) \
            else ""
        return "\\AddToHook{begindocument/end}[TIQ/language]{\\TIQpagelanguage{es}}" in text \
            and "\\DocumentMetadata" not in text and texremediate.LANGUAGES_BEGIN in plain \
            and builds(notes, "notes.tex") and builds(os.path.join(book, "plain"), "book.tex")

    def tagged_later():
        """The one-page document's copy without tagging, built with it, as a
        person may: Spanish throughout, its chapter too, where the hook for
        the master's own chapters had set it back to the book's (the third
        review)."""
        if why:
            return skip(why)
        notes = os.path.join(work, "notes", "plain")
        if not os.path.exists(os.path.join(notes, "notes.tex")):
            return False
        with open(os.path.join(notes, "later.tex"), "w", encoding="utf-8") as fh:
            fh.write("\\DocumentMetadata{tagging=on}\n" + read(notes, "notes.tex"))
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "later.tex"], cwd=notes, capture_output=True, text=True,
                              timeout=300, stdin=subprocess.DEVNULL)
        found = tags(None, None, os.path.join(notes, "later.pdf"))
        if found is None:
            return skip("no pikepdf to read the PDF's structure")
        return done.returncode == 0 and [lang for _, lang in found] == ["es", "es"]

    notes_said = built.get("notes", (1, ""))[1]
    return [
        ("each file's page in another language is tagged in it by hooks around reading "
         "the file, and every other file's page in the book's, the file named as "
         "\\include gives it, its folder too, with .tex once",
         lambda: status == 0 and master.count(texremediate.LANGUAGES_BEGIN) == 1
         and hooks + texremediate.LANGUAGES_END in master
         and master.count("\\TIQfilelanguage{") == 6
         and master.index(texremediate.LANGUAGES_END) < master.index("\n\\begin{document}")),
        ("and nothing else of the author's changes for it: the chapters as written",
         lambda: status == 0 and all(read(book, "copy", name) == text
                                     for name, text in LANGUAGES_FILES.items())),
        ("the run says which pages it tagged, and names the master's own pages it can't, "
         "with what would tag the first",
         lambda: "3 page(s) tagged in their own language as LaTeX reads them (ch02 fr, "
                 "ch03 es, part2 fr)" in said
         and "WARNING: copy: 2 page(s) in a language of their own (book it, book-1 de) are "
             "the master's own text" in said
         and "the copy tags one in its own once it's a file the master \\include-s, its row "
             "in languages.csv named for that file" in said),
        ("a copy without tagging gets them too, to be tagged where it's built with its "
         "tagging, and the run says so",
         lambda: status == 0 and plain.count(texremediate.LANGUAGES_BEGIN) == 1
         and hooks + texremediate.LANGUAGES_END in plain and "\\DocumentMetadata" not in plain
         and "3 page(s) marked in their own language (ch02 fr, ch03 es, part2 fr), which "
             "LaTeX tags where the copy is built with its tagging" in said
         and "WARNING: plain: 2 page(s) in a language of their own (book it, book-1 de)"
             in said and "and the copy marks one in its own once it's a file" in said),
        ("a book that declares no language has none for its pages in the default",
         lambda: plainly_status == 0 and "\\DocumentMetadata" in plainly_master
         and texremediate.LANGUAGES_BEGIN not in plainly_master),
        ("nor one in its files' language throughout, which its copy is in, no page of the "
         "master's own text named",
         lambda: french_status == 0 and "\\DocumentMetadata{lang=fr," in french_master
         and texremediate.LANGUAGES_BEGIN not in french_master
         and "the master's own text" not in french_said),
        ("nor one whose preamble is in another region of the default's language, tagged "
         "or not",
         lambda: american_status == 0 and "\\DocumentMetadata{lang=en-US," in american_copies[0]
         and not any(texremediate.LANGUAGES_BEGIN in copy for copy in american_copies)
         and "in their own language" not in american_said
         and "the master's own text" not in american_said),
        ("each file as the reading took it: one a master in a folder \\include-s with a dot "
         "in its name, and of a conditional's two the one the reading took, the other in "
         "the book's",
         lambda: editions_status == 0
         and "\\TIQbooklanguage{en-US}\n\\TIQfilelanguage{/week1.tex}{en-US}\n"
             "\\TIQfilelanguage{/week1.5.tex}{fr}\n"
             "\\TIQfilelanguage{instructor/answers.tex}{es}\n"
             "\\TIQfilelanguage{student/answers.tex}{en-US}\n" in editions_master
         and "2 page(s) tagged in their own language as LaTeX reads them (answers es, "
             "week1.5 fr)" in editions_said
         and "WARNING" not in editions_said),
        ("and in its PDF, the index after the answers in the book's, set back as their file "
         "ends",
         lambda: pdf_check("editions", "org.example.languages.pdf", [
             ("H1", "en-US"), ("P", "en-US"), ("H1", "fr"), ("P", "fr"), ("H1", "es"),
             ("P", "es"), ("P", "en-US"), ("P", "en-US")], editions_status)),
        ("a copy made from a copy has the languages decided now, its old ones gone",
         lambda: again_status == 0
         and again_master.count(texremediate.LANGUAGES_BEGIN) == 1
         and "\\TIQfilelanguage{/ch02.tex}{fr-CA}\n" in again_master
         and "\\TIQfilelanguage{parts/ch03.tex}{en-US}\n" in again_master
         and "\\TIQfilelanguage{/part2.tex}{en-US}\n" in again_master
         and "}{fr}" not in again_master and "}{es}" not in again_master),
        ("the PDF from the book's own files has each file's page in its language, the "
         "file of that name it \\inputs and the master's text after it too, every other "
         "file's in the book's, after a French chapter or in a French part, its file of "
         "the third's name too, a chapter the master sets in the book's, in the French "
         "part too, and what the second defines reaches the fourth",
         lambda: pdf_check("pdf-book", "org.example.languages.pdf", [
             ("H1", "en-US"), ("P", "en-US"), ("H1", "fr"), ("P", "fr"),
             ("H2", "en-US"), ("P", "en-US"),
             ("H1", "es"), ("P", "es"), ("P", "es"), ("P", "es"), ("P", "es"),
             ("H1", "en-US"), ("P", "en-US"), ("P", "fr"), ("P", "fr"),
             ("H1", "en-US"), ("P", "en-US"),
             ("H1", "en-US"), ("P", "en-US"), ("P", "en-US")])
         and (text_of("pdf-book", "org.example.languages.pdf") is None or
              "a macro the fourth chapter uses" in text_of(
                  "pdf-book", "org.example.languages.pdf"))),
        ("and its run says so, and names what it can't reach in the PDF",
         lambda: skip(why) if why else
         "3 page(s) tagged in their own language (ch02 fr, ch03 es, part2 fr)"
         in built["pdf-book"][1]
         and "WARNING: pdf: 2 page(s) in a language of their own (book it, book-1 de) are "
             "the master's own text" in built["pdf-book"][1]
         and "so the PDF has them in the book's language" in built["pdf-book"][1]
         and "and the PDF tags one in its own once it's a file" in built["pdf-book"][1]),
        ("and its note on the pages names no PDF of the whole book, which is built from "
         "its own files, nor anything else the run doesn't make",
         lambda: skip(why) if why else
         re.search(r"5 pages are in a different language than the book \(en-US\): .*\. "
                   r"Every output marks each in its own language\.$",
                   built["pdf-book"][1], re.M)),
        ("a document that \\include-s nothing is in its page's language whole, its "
         "\\DocumentMetadata's, in its PDF and its copy, and from \\begin{document} in its "
         "copy without tagging",
         lambda: pdf_check("notes", "org.example.languages.pdf", [("H1", "es"), ("P", "es")])
         and "1 page(s) tagged in their own language as LaTeX reads them (notes es)"
             in notes_said
         and read(work, "notes", "copy", "notes.tex").startswith(
             "\\DocumentMetadata{lang=es, pdfstandard=ua-2, tagging=on}\n")
         and texremediate.LANGUAGES_BEGIN not in read(work, "notes", "copy", "notes.tex")),
        ("and a copy without tagging builds with them", guarded),
        ("and the document's built with tagging later is in its page's language, its "
         "chapter too", tagged_later),
        ("a file named with a macro gets no hook, nor a book whose only page in another "
         "language is one, and of two files of one page's name the later is the page",
         lambda: texremediate.page_languages_block(
             "book.tex", [("\\chapters/ch05", "main"), ("ch06", "main")],
             {"ch05": "fr", "ch06": "de"}, "de") == ("", [], [("ch05", "fr", "named")])
         and texremediate.page_languages_block(
             "book.tex", [("a/intro", "main"), ("b/intro", "main")], {"intro": "fr"}, "en")[0]
         .endswith("\\TIQfilelanguage{a/intro.tex}{en}\n\\TIQfilelanguage{b/intro.tex}{fr}\n"
                   + texremediate.LANGUAGES_END)),
        ("a file is named as LaTeX's hooks see it: its folder as written, .tex once, no "
         "quotes, and its spaces",
         lambda: texremediate.included_file_key("ch02.tex") == "/ch02.tex"
         and texremediate.included_file_key("parts/ch03") == "parts/ch03.tex"
         and texremediate.included_file_key("./ch04") == "./ch04.tex"
         and texremediate.included_file_key('"two words"') == "/two words.tex"
         and texremediate.included_file_key("\\chapters/ch05") is None
         and texremediate.included_file_key("ch{05}") is None),
        ("a copy is tagged where its master's \\DocumentMetadata says tagging=on or names a "
         "testphase that turns it on, not one that says off or draft, sets only the PDF's "
         "version, or is a comment",
         lambda: texremediate.tags_itself("\\DocumentMetadata{lang=en, tagging = {on}}\n")
         and texremediate.tags_itself("\\DocumentMetadata{testphase=latest}\n")
         and texremediate.tags_itself("\\DocumentMetadata{testphase={phase-III,math}}\n")
         and not texremediate.tags_itself("\\DocumentMetadata{testphase=math}\n")
         and not texremediate.tags_itself("\\DocumentMetadata{tagging=draft}\n")
         and not texremediate.tags_itself("\\DocumentMetadata{tagging=off}\n")
         and not texremediate.tags_itself("\\DocumentMetadata{pdfversion=2.0}\n")
         and not texremediate.tags_itself("% \\DocumentMetadata{tagging=on}\n")
         and texremediate.tags_itself("\\DocumentMetadata{\n  tagging=on % LuaLaTeX\n}\n")),
        ("a document's language goes into its \\DocumentMetadata as the author wrote it, "
         "its lines and comments kept",
         lambda: texremediate.with_document_language(
             "\\DocumentMetadata{\n  lang=en-US,\n  tagging=on % LuaLaTeX\n}\n", "es")
         == "\\DocumentMetadata{\n  lang=es,\n  tagging=on % LuaLaTeX\n}\n"
         and texremediate.with_document_language(
             "\\DocumentMetadata{pdfversion=2.0 % two\n}\n", "es")
         == "\\DocumentMetadata{lang=es, pdfversion=2.0 % two\n}\n"
         and texremediate.with_document_language("\\documentclass{book}\n", "es") is None),
    ]



# A book whose own babel commands set its passages' languages: in its first
# chapter, French words opening a paragraph and inside it, by
# \foreignlanguage, babeltags' \textfr, and babel's alias francais, Latin,
# a locale \babelprovide imports, a language with no locale of its own,
# a German paragraph by otherlanguage, French words in a section's
# heading, \selectlanguage's French and English after it, and a page with
# the section's title in its running head; a second
# chapter whose file selects French before its heading; a third that
# languages.csv puts in Spanish, babel's English throughout, with an
# English quotation and an English word; and a fourth the master selects
# French for before its \include, and a chapter of its own after it.
BABEL_MASTER = (
    "\\documentclass{book}\n\\usepackage[french,ngerman,english]{babel}\n"
    "\\babelprovide[import]{latin}\n\\babelprovide{klingon}\n\\babeltags{fr = french}\n"
    "\\title{Languages by Babel}\n\\author{An Author}\n\\begin{document}\n\\maketitle\n"
    "\\tableofcontents\n\\include{ch01}\n\\include{ch02}\n\\include{ch03}\n"
    "\\selectlanguage{french}\n\\include{ch04}\n\\chapter{Annexe}\nUne annexe que le "
    "ma\\^itre pose.\n\\selectlanguage{english}\n\\end{document}\n")
BABEL_FILES = {
    "ch01.tex": "\\chapter{One}\n\\foreignlanguage{french}{Bonjour}, she said, and went on in "
                "English, with \\textfr{un mot}, \\foreignlanguage{francais}{un autre}, "
                "\\foreignlanguage{latin}{et cetera}, and \\foreignlanguage{klingon}{Qapla'}.\n\n"
                "\\begin{otherlanguage}{ngerman}\nEin Absatz auf Deutsch.\n"
                "\\end{otherlanguage}\n\nAfter the German passage, English again.\n\n"
                "\\section{Le \\foreignlanguage{french}{titre}}\n\\selectlanguage{french}\n"
                "Texte apr\\`es selectlanguage.\n\n\\selectlanguage{english}\nBack in English.\n"
                "% \\foreignlanguage{ngerman}{in a comment}\n\n\\newpage\nAnother page.\n\n"
                "\\newpage\nA page with the section's title over it.\n",
    "ch02.tex": "\\selectlanguage{french}\n\\chapter{Deux}\nUn chapitre en fran\\c{c}ais.\n"
                "\\selectlanguage{english}\n",
    "ch03.tex": "\\chapter{Tres}\nUn cap\\'itulo en espa\\~nol.\n\n"
                "\\begin{otherlanguage}{english}\nAn English quotation.\n\\end{otherlanguage}\n\n"
                "Otra vez en espa\\~nol, con una \\foreignlanguage{english}{word}.\n",
    "ch04.tex": "\\chapter{Quatre}\nUn chapitre que le ma\\^itre met en fran\\c{c}ais.\n",
}

def structure_tree(path):
    """Each structure element of the tagged PDF at path but its Spans, in
    order, as its role with its ancestors' ("/Document/Sect/Part/P"), a
    Span's own left out too, so a Span in one PDF and not another changes
    nothing, and a paragraph left inside one does; None where pikepdf isn't
    installed, [] for no PDF."""
    try:
        import pikepdf
    except ImportError:
        return None
    if not os.path.exists(path):
        return []
    found = []
    with pikepdf.open(path) as done:
        root = done.Root.get("/StructTreeRoot")
        if root is None:
            return []
        roles = {str(k): str(v) for k, v in dict(root.get("/RoleMap", {})).items()}

        def walk(node, chain):
            kids = node.get("/K")
            for kid in (kids if isinstance(kids, pikepdf.Array) else
                        [] if kids is None else [kids]):
                if isinstance(kid, pikepdf.Dictionary) and "/S" in kid:
                    kind = roles.get(str(kid.S), str(kid.S))
                    here = chain if kind == "/Span" else chain + kind
                    if kind != "/Span":
                        found.append(here)
                    walk(kid, here)
        walk(root, "")
    return found


# The Spans the inline book's PDF has in another language than what's
# around them (case_babel_languages).
INLINE_SPANS = [("fr", "un mot"), ("de", "ein Wort"), ("fr", "Un paragraphe qui continue."),
                ("fr", "un mot11Une note mit Wort. encore"), ("de", "mit Wort"),
                ("fr", "deux mots zwei Worte"), ("de", "zwei Worte"), ("fr", "une formule"),
                ("fr", "une autre"), ("fr", "maison Haus"), ("de", "Haus"), ("fr", "chat"),
                ("fr", "d\u00e9j\u00e0 vu"), ("fr", "un tableau ")]


def pdf_structure(path):
    """[(role, its own /Lang or None, its language, its text, the language
    around it)] for each structure element of the tagged PDF at path, in
    order, the catalog's language around the first, from poppler's
    pdfinfo -struct-text and pikepdf; None where either is missing, [] for
    no PDF."""
    try:
        import pikepdf
    except ImportError:
        return None
    if not shutil.which("pdfinfo"):
        return None
    if not os.path.exists(path):
        return []
    own = {}
    with pikepdf.open(path) as done:
        catalog = str(done.Root.get("/Lang") or "")

        def walk(node):
            kids = node.get("/K")
            for kid in (kids if isinstance(kids, pikepdf.Array) else
                        [] if kids is None else [kids]):
                if isinstance(kid, pikepdf.Dictionary) and "/S" in kid:
                    if "/ID" in kid and "/Lang" in kid:
                        own[str(kid.ID)] = str(kid.Lang)
                    walk(kid)
        walk(done.Root.StructTreeRoot)
    out = subprocess.run(["pdfinfo", "-struct-text", path], capture_output=True,
                         timeout=120).stdout.decode("utf-8", "replace")
    elements, open_ones = [], []
    for line in out.splitlines():
        indent = len(line) - len(line.lstrip())
        element = re.match(r"\s*(\w+) <(ID\.\d+)>", line)
        text = re.match(r'\s*"(.*)"\s*$', line)
        if not element and not text:
            continue
        while open_ones and open_ones[-1][0] >= indent:
            open_ones.pop()
        if element:
            around = elements[open_ones[-1][1]][2] if open_ones else catalog
            lang = own.get(element.group(2))
            elements.append([element.group(1), lang, lang or around, "", around])
            open_ones.append((indent, len(elements) - 1))
        else:
            for _, at in open_ones:
                elements[at][3] += text.group(1)
    return [tuple(e) for e in elements]


def case_babel_languages(work):
    """A LaTeX book's passages its own babel commands set the language of,
    in its copy and its PDF built from its own files: in the master's
    preamble, hooks babel runs as it selects a language, so nothing else
    of the author's changes; tagged in it as LaTeX reads them, a paragraph
    or more by LaTeX's key for a language, a heading or a whole chapter
    too, and \\foreignlanguage's words a Span of their own, the paragraph
    they open keeping its own; each language's tag the table's, babel's
    alias's too, else babel's own, and one with neither named; the
    language babel restores after a passage not set, so a page
    languages.csv puts in Spanish is Spanish after an English quotation
    in it; every word where it was without them; the same in a copy
    without tagging, which builds with pdfLaTeX; none where every command
    names the copy's language and every page is in it, nor in a book that
    doesn't load babel, but in a page in another language, a passage in
    the copy's; the run counting them by language; and a copy made from a
    copy given them once."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import texremediate
    why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")

    def book_at(path, files, rows, targets, exists_ok=False, language=None):
        os.makedirs(path, exist_ok=exists_ok)
        for name, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(path, name)), exist_ok=True)
            with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(path, "languages.csv"), "w", encoding="utf-8") as fh:
            fh.write("source,language,found,drafted-by,reviewed\n" + rows)
        with open(os.path.join(path, "project.yaml"), "w", encoding="utf-8") as fh:
            fh.write("project:\n  identifier: org.example.babel\n  title: Languages by Babel\n"
                     + (f"  language: {language}\n" if language else ""))
        with open(os.path.join(path, "conversion.yaml"), "a", encoding="utf-8") as fh:
            fh.write("targets:\n" + targets)
        done = convert(path)
        return done.returncode, done.stdout + done.stderr

    copies = ("  copy:\n    format: source\n    tagging: \"on\"\n"
              "  plain:\n    format: source\n    tagging: \"off\"\n")
    files = dict(BABEL_FILES, **{"book.tex": BABEL_MASTER})
    book = os.path.join(work, "book")
    status, said = book_at(book, files, "ch03,es,,,\n",
                           copies + ("" if why else "  pdf:\n    format: pdf\n"))
    master = read(book, "copy", "book.tex") if status == 0 else ""
    plain = read(book, "plain", "book.tex") if status == 0 else ""
    counted = ("15 of babel's commands for a passage's language (french 6, english 5, "
               "francais 1, klingon 1, latin 1, ngerman 1), each passage")

    # The copy made from the copy, laid over the author's tree.
    again = os.path.join(work, "again")
    laid = dict(files)
    if status == 0:
        laid.update({name: read(book, "copy", name) for name in files})
    again_status, _ = book_at(again, laid, "ch03,es,,,\n",
                              "  copy:\n    format: source\n    tagging: \"on\"\n")
    again_master = read(again, "copy", "book.tex") if again_status == 0 else ""

    # A book in English whose babel commands name only English, with no
    # page in another language; and one with a page languages.csv puts in
    # Spanish, which opens with babel's \selectlanguage{english}, the
    # language babel is in already, and holds an English quotation, in
    # another language than the page's. Each project declares American
    # English, where the books' option is english: the first's tagged copy
    # keeps babel's main language english (case_babel_main), and the
    # second's own \DocumentMetadata names en-US, which babel takes its
    # main language from, american, as it did in a tagged copy (the fifth
    # review).
    english_status, english_said = book_at(os.path.join(work, "english"), {
        "book.tex": "\\documentclass{book}\n\\usepackage[english]{babel}\n\\begin{document}\n"
                    "\\include{one}\n\\include{two}\n\\end{document}\n",
        "one.tex": "\\selectlanguage{english}\n\\chapter{One}\nIn English.\n",
        "two.tex": "\\selectlanguage{english}\n\\chapter{Two}\nIn English too.\n"}, "",
        "  copy:\n    format: source\n    tagging: \"on\"\n", language="en-US")
    english_master = read(work, "english", "copy", "book.tex") if english_status == 0 else ""
    paged = os.path.join(work, "english-page")
    paged_status, paged_said = book_at(paged, {
        "book.tex": "\\DocumentMetadata{lang=en-US}\n\\documentclass{book}\n"
                    "\\usepackage[english]{babel}\n"
                    "\\begin{document}\n\\include{one}\n\\include{two}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nIn English.\n",
        "two.tex": "\\selectlanguage{english}\n\\chapter{Dos}\nEn espa\\~nol.\n\n"
                   "\\begin{otherlanguage}{english}\nA quotation.\n\\end{otherlanguage}\n\n"
                   "M\\'as espa\\~nol.\n"}, "two,es,,,\n",
        "  copy:\n    format: source\n    tagging: \"on\"\n"
        + ("" if why else "  pdf:\n    format: pdf\n"), language="en-US")
    paged_master = read(paged, "copy", "book.tex") if paged_status == 0 else ""

    # One in Canadian French by its \DocumentMetadata, babel's French, a
    # language of the table's without the region, whose first chapter's
    # file ends in English, the master setting text after it, and a page
    # languages.csv puts in English.
    canadian = os.path.join(work, "canadian")
    canadian_status, _ = (1, "") if why else book_at(canadian, {
        "book.tex": "\\DocumentMetadata{lang=fr-CA}\n\\documentclass{book}\n"
                    "\\usepackage[english,french]{babel}\n\\begin{document}\n\\include{un}\n"
                    "Text the master sets after the file.\n\n\\include{two}\n\\end{document}\n",
        "un.tex": "\\chapter{Un}\nEn fran\\c{c}ais du Canada.\n\n\\selectlanguage{english}\n"
                  "In English at the chapter's end.\n",
        "two.tex": "\\chapter{Two}\nIn English, with a \\foreignlanguage{french}{mot}.\n"},
        "two,en,,,\n", "  pdf:\n    format: pdf\n")

    # One whose babel doesn't begin a paragraph before it selects the
    # language of \foreignlanguage's words, as babel does where LaTeX has
    # no \GetDocumentProperties.
    older = os.path.join(work, "older")
    older_status, _ = (1, "") if why else book_at(older, {
        "book.tex": "\\documentclass{book}\n\\usepackage[french,english]{babel}\n"
                    "\\makeatletter\n\\let\\bbl@beforeforeign\\@empty\n\\makeatother\n"
                    "\\begin{document}\n\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nA first paragraph.\n\n"
                   "\\foreignlanguage{french}{Bonjour}, she said.\n"}, "",
        "  pdf:\n    format: pdf\n")

    # One whose babel commands select a language inside a paragraph:
    # babeltags' declaration in a group, otherlanguage* in a paragraph, an
    # otherlanguage begun on a paragraph's last line that holds a
    # paragraph break, a \selectlanguage in the middle of a paragraph and
    # another after one, a declaration around a note's mark, whose note
    # holds one of its own, two declarations in one group, a declaration
    # and \foreignlanguage's words around a display, two declarations in a
    # table's cell and one in another, one in a list's label, and a
    # tabular begun inside a declaration's paragraph, each of the last four
    # a structure LaTeX's tagging ends before the group, the last by its
    # name, which tagpdf's debug code checks.
    inline = os.path.join(work, "inline")
    inline_status, _ = (1, "") if why else book_at(inline, {
        "book.tex": "\\documentclass{book}\n\\usepackage[french,ngerman,english]{babel}\n"
                    "\\babeltags{fr = french, de = ngerman}\n\\begin{document}\n"
                    "\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nA {\\fr un mot} here.\n\n"
                   "B \\begin{otherlanguage*}{ngerman}ein Wort\\end{otherlanguage*} there.\n\n"
                   "C text\n\\begin{otherlanguage}{french}\nUn paragraphe qui continue.\n\n"
                   "Un second.\n\\end{otherlanguage}\n\nD after.\n\n"
                   "E mid \\selectlanguage{french}suite en fran\\c{c}ais.\n\n"
                   "F le paragraphe suivant.\n\n\\selectlanguage{english}\nG back.\n\n"
                   "H {\\fr un mot\\footnote{Une note {\\de mit Wort}.} encore} end.\n\n"
                   "I {\\fr deux mots \\de zwei Worte} after.\n\n"
                   "J {\\fr une formule\n\\[ x = y \\]\net la suite} and English.\n\n"
                   "K \\foreignlanguage{french}{une autre\n\\[ x = z \\]\net encore} and English.\n\n"
                   "\\begin{tabular}{ll}\nhouse & \\fr maison \\de Haus\\\\\ncat & \\fr chat\\\\\n"
                   "\\end{tabular}\n\n"
                   "\\begin{description}\n\\item[\\fr d\\'ej\\`a vu] the feeling\n"
                   "\\end{description}\n\n"
                   "M {\\fr un tableau \\begin{tabular}{l} x \\\\ \\end{tabular} la suite} after.\n\n"
                   "N last.\n"}, "",
        "  copy:\n    format: source\n    tagging: \"on\"\n  pdf:\n    format: pdf\n")

    # A book with another master beside its own, which latex.main doesn't
    # name, whose copy is written too.
    masters = os.path.join(work, "masters")
    os.makedirs(masters)
    with open(os.path.join(masters, "conversion.yaml"), "w", encoding="utf-8") as fh:
        fh.write("defaults:\n  latex:\n    main: book.tex\n")
    masters_status, masters_said = book_at(masters, {
        "book.tex": "\\documentclass{book}\n\\usepackage[french,english]{babel}\n"
                    "\\begin{document}\n\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nA \\foreignlanguage{french}{mot}.\n",
        "answers.tex": "\\documentclass{book}\n\\usepackage[french,english]{babel}\n"
                       "\\begin{document}\n\\include{two}\n\\end{document}\n",
        "two.tex": "\\chapter{Answers}\nAn \\foreignlanguage{french}{r\\'eponse} and "
                   "\\foreignlanguage{french}{une autre}.\n\n\\foreignlanguage{french}{Premier "
                   "paragraphe.\n\nSecond paragraphe.}\n"}, "",
        "  copy:\n    format: source\n    tagging: \"on\"\n", exists_ok=True)
    answers = read(masters, "copy", "answers.tex") if masters_status == 0 else ""

    # A book that marks its passages with polyglossia, not babel.
    poly_status, poly_said = book_at(os.path.join(work, "polyglossia"), {
        "book.tex": "\\documentclass{book}\n\\usepackage{polyglossia}\n"
                    "\\setmainlanguage{english}\n\\setotherlanguage{french}\n"
                    "\\begin{document}\n\\include{one}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nA \\foreignlanguage{french}{mot} in French.\n"}, "",
        "  copy:\n    format: source\n    tagging: \"on\"\n")
    poly_master = read(work, "polyglossia", "copy", "book.tex") if poly_status == 0 else ""

    pdf = os.path.join(book, "pdf", "org.example.babel.pdf")

    def found():
        """The PDF's structure (pdf_structure), or a reason to skip."""
        if why:
            return why
        structure = pdf_structure(pdf)
        if structure is None:
            return "no pikepdf or pdfinfo to read the PDF's structure"
        return structure

    def spans():
        """[(language, text)] of the Spans in another language than what's
        around them."""
        structure = found()
        if isinstance(structure, str):
            return skip(structure)
        return status == 0 and [(lang, text) for role, own, lang, text, around in structure
                                if role == "Span" and own and own != around] == [
            ("fr", "titre"), ("fr", "Bonjour"), ("fr", "un mot"), ("fr", "un autre"),
            ("la", "et cetera"), ("fr", "titre"), ("en", "word")]

    def paragraphs():
        """[(language, first word)] of the paragraphs from the first
        chapter's on, and the language of the headings of the chapters
        babel selects French for."""
        structure = found()
        if isinstance(structure, str):
            return skip(structure)
        texts = [(lang, text.split()[0]) for role, _, lang, text, _ in structure
                 if role == "P" and text.split()]
        first = next((i for i, (_, word) in enumerate(texts) if word == "Bonjour,"), len(texts))
        return status == 0 and texts[first:] == [
            ("en", "Bonjour,"), ("de", "Ein"), ("en", "After"), ("fr", "Texte"),
            ("en", "Back"), ("en", "Another"), ("en", "A"), ("fr", "Un"), ("es", "Un"),
            ("en", "An"), ("es", "Otra"), ("fr", "Un"), ("fr", "Une")] \
            and [(lang, text.split()[-1]) for role, _, lang, text, _ in structure
                 if role == "H1" and re.search(r"Deux|Quatre|Annexe", text)] == [
                ("fr", "Deux"), ("fr", "Quatre"), ("fr", "Annexe")]

    def unmoved(folder, done, engines=("lualatex",)):
        """Every word of the copy of the book at folder, built with each of
        engines' tagging (latexmk's -lualatex, -pdf; lualatex+debug with
        tagpdf's debug code), where the copy built without the block has
        it, its structure that one's but for the Spans (structure_tree), to
        the paragraph each element is in, and no more of tagpdf's warnings,
        which name content left outside its structure ("Relation is not
        allowed"), or in debug a structure ended by another's name."""
        if why:
            return skip(why)
        if not shutil.which("pdftotext"):
            return skip("no pdftotext to place the PDF's words")
        if done != 0 or not os.path.exists(os.path.join(folder, "copy", "book.tex")):
            return False

        def words(path):
            out = subprocess.run(["pdftotext", "-bbox", path, "-"], capture_output=True,
                                 timeout=120).stdout.decode("utf-8", "replace")
            return re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" '
                              r'yMax="([\d.]+)">([^<]*)</word>', out)
        for engine in engines:
            built = {}
            program, _, debug = engine.partition("+")
            for name, block_out in (("with", False), ("bare", True)):
                there = os.path.join(folder, "%s-%s" % (name, engine))
                if not os.path.exists(os.path.join(there, "book.pdf")):
                    shutil.copytree(os.path.join(folder, "copy"), there, dirs_exist_ok=True)
                    text = read(folder, "copy", "book.tex")
                    if block_out:
                        text = texremediate.BABEL_BLOCK.sub("", text)
                    if debug:
                        text = re.sub(r"\A(\\DocumentMetadata\{[^}\n]*)\}\n",
                                      r"\1, debug={tagpdf}}\n"
                                      r"\\AtBeginDocument{\\tagpdfsetup{debug/log=v}}\n", text)
                        if "debug={tagpdf}" not in text:
                            return False
                    with open(os.path.join(there, "book.tex"), "w", encoding="utf-8") as fh:
                        fh.write(text)
                    subprocess.run(["latexmk", "-" + program, "-interaction=nonstopmode",
                                    "-halt-on-error", "book.tex"], cwd=there,
                                   capture_output=True, text=True, timeout=600,
                                   stdin=subprocess.DEVNULL)
                if not os.path.exists(os.path.join(there, "book.pdf")):
                    return False
                built[name] = (os.path.join(there, "book.pdf"), [
                    re.sub(r"\s*\[on line \d+\]|\s*on input line \d+", "", warning)
                    for warning in re.findall(r"tagpdf(?: DEBUG)? Warning: [^\n]*",
                                              read(there, "book.log"))])
            one, other = words(built["with"][0]), words(built["bare"][0])
            with_block = structure_tree(built["with"][0])
            if with_block is None:
                return skip("no pikepdf to read the PDF's structure")
            if not (len(one) == len(other) > 20
                    and [w[4] for w in one] == [w[4] for w in other]
                    and max(abs(float(a) - float(b)) for p, q in zip(one, other)
                            for a, b in zip(p[:4], q[:4])) < 0.02
                    and len(with_block) > 10
                    and with_block == structure_tree(built["bare"][0])
                    and built["with"][1] == built["bare"][1]):
                return False
        return True

    def page_check(path, expected, done, words=None):
        """Whether a PDF's headings and paragraphs, from its first heading
        on, are in the languages expected, [(role, language)], and its
        Spans in another language than what's around them, words."""
        if why:
            return skip(why)
        structure = pdf_structure(path)
        if structure is None:
            return skip("no pikepdf or pdfinfo to read the PDF's structure")
        found = [(role, lang) for role, _, lang, _, _ in structure
                 if role in ("H1", "H2", "P")]
        first = next((i for i, (role, _) in enumerate(found) if role != "P"), len(found))
        return done == 0 and found[first:] == expected and (words is None or [
            (lang, text) for role, own, lang, text, around in structure
            if role == "Span" and own and own != around] == words)

    def other_built():
        """The other master's copy, built with LuaLaTeX: it builds, and its
        \\foreignlanguage of two paragraphs has its first in a Span, closed
        before LaTeX's tagging ends the paragraph, which tagpdf warns of
        otherwise ("Parent-Child 'pdf2:Sect' --> 'MC (realcontent)'.
        Relation is not allowed!"), and its second a paragraph in French."""
        if why:
            return skip(why)
        folder = os.path.join(masters, "copy")
        if masters_status != 0 or not os.path.exists(os.path.join(folder, "answers.tex")):
            return False
        done = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode",
                               "-halt-on-error", "answers.tex"], cwd=folder,
                              capture_output=True, text=True, timeout=600,
                              stdin=subprocess.DEVNULL)
        log = read(folder, "answers.log") if os.path.exists(
            os.path.join(folder, "answers.log")) else ""
        return done.returncode == 0 and "Relation is not allowed" not in log and page_check(
            os.path.join(folder, "answers.pdf"),
            [("H1", "en"), ("P", "en"), ("P", "en"), ("P", "fr")], 0,
            [("fr", "r\u00e9ponse"), ("fr", "une autre"), ("fr", "Premier paragraphe.")])

    def item_body():
        """Whether the inline book's list item's body, after a declaration
        in its label, is in the language around the label, as babel has it."""
        if why:
            return skip(why)
        structure = pdf_structure(os.path.join(inline, "pdf", "org.example.babel.pdf"))
        if structure is None:
            return skip("no pikepdf or pdfinfo to read the PDF's structure")
        return inline_status == 0 and [
            lang for role, _, lang, _, _ in structure if role == "LBody"] == ["en"]

    def builds(folder):
        """Whether the copy without tagging builds, as the author's own
        does, with pdfLaTeX."""
        if why:
            return skip(why)
        if not os.path.exists(os.path.join(folder, "book.tex")):
            return False
        done = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode",
                               "-halt-on-error", "book.tex"], cwd=folder,
                              capture_output=True, text=True, timeout=300,
                              stdin=subprocess.DEVNULL)
        return done.returncode == 0

    block = texremediate.BABEL_BEGIN + texremediate.BABEL_SETUP + texremediate.babel_table() \
        + texremediate.BABEL_END
    return [
        ("a book whose babel commands set a passage's language gets hooks babel runs as it "
         "selects one, once, in its master's preamble",
         lambda: status == 0 and master.count(texremediate.BABEL_BEGIN) == 1
         and block + "\\begin{document}" in master
         and "\\AddToHook { babel / * / afterextras } [ TIQ / babel ]" in master
         and "\\TIQbabeltags{francais=fr, german=de, ngerman=de, spanish=es}\n" in master),
        ("and nothing else of the author's changes for them: the chapters as written",
         lambda: status == 0 and all(read(book, "copy", name) == text
                                     for name, text in BABEL_FILES.items())),
        ("the run counts them by language, babel's commands for the copy's language in a "
         "page in another among them, a comment's not",
         lambda: counted + " tagged in its language as LaTeX reads it, where babel or the "
         "table has a tag for it, and a \\selectlanguage's inside a paragraph from the next "
         "paragraph on." in said),
        ("a copy without tagging gets them too, to be tagged where it's built with its "
         "tagging, the run says so, and it builds with pdfLaTeX",
         lambda: status == 0 and block + "\\begin{document}" in plain
         and "\\DocumentMetadata" not in plain
         and counted + " marked to be tagged in its language, which LaTeX does where the copy "
             "is built with its tagging" in said and builds(os.path.join(book, "plain"))),
        ("in the PDF from the book's own files, \\foreignlanguage's words are each a Span in "
         "its language, in a paragraph, a heading, and its contents entry, babeltags' and "
         "babel's alias's French, Latin by babel's own tag, and an English word in the "
         "Spanish page; a language with no tag has none, nor has the running head over the "
         "French heading, which babel sets in \\foreignlanguage too", spans),
        ("a passage of a paragraph is in its language, the paragraph \\foreignlanguage's "
         "words open keeps its own, what follows a passage is in what's around it, and the "
         "Spanish page is Spanish after its English quotation; a chapter whose file selects "
         "French is French, its heading too, and so are a chapter's file the master selects "
         "French for before its \\include and a chapter the master sets after it",
         paragraphs),
        ("the run names the language babel has no tag for",
         lambda: skip(why) if why else
         "WARNING: pdf: babel has no language tag for klingon, so the PDF has the passages "
         "the book's babel commands put in it in the language around them" in said
         and "Wrote " + pdf + ": " in said
         and counted + " tagged in its language where babel or the table has a tag for it, "
             "and a \\selectlanguage's inside a paragraph from the next paragraph on, " in said),
        ("every word is where the book built without them has it, the structure is the same "
         "but for the Spans, and tagpdf warns of nothing more", lambda: unmoved(book, status)),
        ("a copy made from a copy has them once",
         lambda: again_status == 0 and again_master.count(texremediate.BABEL_BEGIN) == 1
         and again_master.count(texremediate.BABEL_END) == 1),
        ("a book whose babel commands name only its language, every page in it, gets none",
         lambda: english_status == 0 and "\\DocumentMetadata" in english_master
         and texremediate.BABEL_BEGIN not in english_master
         and "babel's commands" not in english_said),
        ("but one with a page in another language gets them, its passage in the book's "
         "language another than the page's",
         lambda: paged_status == 0 and paged_master.count(texremediate.BABEL_BEGIN) == 1
         and "2 of babel's commands for a passage's language (english 2), each passage tagged "
             "in its language as LaTeX reads it" in paged_said),
        ("and in its PDF, the Spanish page is Spanish though it opens with babel's "
         "English, which babel was in already, and its English quotation English",
         lambda: page_check(os.path.join(paged, "pdf", "org.example.babel.pdf"), [
             ("H1", "en-US"), ("P", "en-US"), ("H1", "es"), ("P", "es"), ("P", "en"),
             ("P", "es")], paged_status)),
        ("a page with no language of its own is in the book's, its region too, where "
         "babel's commands haven't selected another than babel's main language, and the "
         "master's text after a file in the one babel is left in there",
         lambda: page_check(os.path.join(canadian, "pdf", "org.example.babel.pdf"), [
             ("H1", "fr-CA"), ("P", "fr-CA"), ("P", "en"), ("P", "en"), ("H1", "en"),
             ("P", "en")], canadian_status, [("fr", "mot")])),
        ("and where babel doesn't begin a paragraph before it selects the language of "
         "\\foreignlanguage's words, the paragraph they open keeps its own",
         lambda: page_check(os.path.join(older, "pdf", "org.example.babel.pdf"), [
             ("H1", "en"), ("P", "en"), ("P", "en")], older_status, [("fr", "Bonjour")])),
        ("the book's other master gets them too, and the run counts its own",
         lambda: masters_status == 0 and answers.count(texremediate.BABEL_BEGIN) == 1
         and "1 of babel's commands for a passage's language (french 1), each passage tagged "
             "in its language as LaTeX reads it, where babel or the table has a tag for it, "
             "and a \\selectlanguage's inside a paragraph from the next paragraph on."
             in masters_said
         and "answers.tex with 1 file(s) only it reaches, 0 image(s) and drawing(s) given "
             "alt text and 0 marked artifact, 3 of babel's commands for a passage's language, "
             "each passage tagged in its language" in masters_said),
        ("and that master's copy builds with tagging, a \\foreignlanguage of two paragraphs "
         "tagged in its language, its Span closed before the paragraph", other_built),
        ("a passage babel's otherlanguage or babeltags begin inside a paragraph is a Span to "
         "its group's end, or to where LaTeX's tagging ends the paragraph, a table's cell, or "
         "a list's label around it, a second its group begins ending there with it; what "
         "begins after that inside it is in its language, a note's paragraph, the paragraph "
         "after a display, \\foreignlanguage's words' too, the last paragraph whole, but not "
         "a list item's body; a \\selectlanguage there sets what begins after the paragraph",
         lambda: page_check(os.path.join(inline, "pdf", "org.example.babel.pdf"), [
             ("H1", "en"), ("P", "en"), ("P", "en"), ("P", "en"), ("P", "fr"), ("P", "en"),
             ("P", "en"), ("P", "fr"), ("P", "en"), ("P", "en"), ("P", "fr"), ("P", "en"),
             ("P", "en"), ("P", "fr"), ("P", "en"), ("P", "fr"), ("P", "en"), ("P", "en"),
             ("P", "en"), ("P", "en"), ("P", "fr"), ("P", "en")],
             inline_status, INLINE_SPANS) and item_body()),
        ("and that book's copy, built with LuaLaTeX and with pdfLaTeX's tagging, has every "
         "word and its structure as without them, but for the Spans, and tagpdf warns of "
         "nothing more, in its debug code too",
         lambda: unmoved(inline, inline_status, ("lualatex", "pdf", "lualatex+debug"))),
        ("nor does a book that marks its passages with polyglossia",
         lambda: poly_status == 0 and texremediate.BABEL_BEGIN not in poly_master
         and "babel's commands" not in poly_said),
        ("the commands are counted as babel reads them: an option before the name, a name "
         "in capitals, babeltags' three, and selectlanguage as an environment; not one in a "
         "comment, verbatim, named by a macro, or by a macro's parameter",
         lambda: texremediate.babel_passages({
             "a.tex": "\\babeltags{fr = french, de=ngerman}\n"
                      "\\foreignlanguage[date]{ngerman}{vier} \\selectlanguage{French}\n"
                      "\\textfr{a} \\begin{fr}b\\end{fr} {\\de c} \\textde{d}\n"
                      "\\begin{selectlanguage}{english}e\\end{selectlanguage}\n"
                      "% \\foreignlanguage{latin}{in a comment}\n"
                      "\\verb|\\foreignlanguage{latin}{x}| \\foreignlanguage{\\mylang}{m}\n"
                      "\\begin{otherlanguage*}{latin}z\\end{otherlanguage*} \\textit{i}\n"
                      "\\newcommand{\\lang}[2]{\\foreignlanguage{#1}{#2}}\n"},
             ["a.tex"]) == {"ngerman": 3, "french": 3, "english": 1, "latin": 1}
         and texremediate.babel_tag("French") == "fr"
         and texremediate.babel_tag("klingon") is None),
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


def tools_alone(work, *programs):
    """An environment whose PATH holds Pandoc, file, Python, and programs
    alone, in a folder beside work, so a case runs alike wherever it runs.
    Python is a script that runs this one (sys.executable): a venv's
    python run through a link starts without the venv's packages, and a
    pyenv shim is a script that needs the PATH it's taken from."""
    tools = work + "-bin"
    os.makedirs(tools, exist_ok=True)
    for program in ("pandoc", "file") + programs:
        found = shutil.which(program)
        if found:
            os.symlink(found, os.path.join(tools, program))
    with open(os.path.join(tools, "python3"), "w") as fh:
        fh.write("#!/bin/sh\nexec %s \"$@\"\n" % shlex.quote(sys.executable))
    os.chmod(os.path.join(tools, "python3"), 0o755)
    return tools, dict(os.environ, PATH=tools)


def case_unmade_images(work):
    """A book's PDF and EPS images where they can't be made SVG: left out
    of the pages, and the run says so, once for each image. Kept, the page
    embedded the PDF and the Word file held an image Word can't show,
    which stopped the Word file read back as a source, and nothing was
    said. One is in the master's preamble, in \\title and in a macro, which
    the copy had kept as the book wrote it; one has a ] in its alt text,
    which the copy had passed over; and one is a macro's that calls the
    book's own macro for an image, which the copy had left as the call
    wrote it, the page showing the PDF, unnamed. The runs' PATH holds Pandoc, Python,
    and file alone (tools_alone), then a pdftocairo that fails as well, so
    the case runs alike wherever it runs, and then, where poppler-utils is
    installed, its pdftocairo."""
    os.makedirs(os.path.join(work, "img"))
    pdf(os.path.join(work, "img", "diagram.pdf"))
    pdf(os.path.join(work, "img", "logo.pdf"))
    pdf(os.path.join(work, "img", "chart.pdf"))
    with open(os.path.join(work, "img", "shape.eps"), "w") as fh:
        fh.write("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n"
                 "newpath 0 0 moveto 10 10 lineto stroke\nshowpage\n")
    png(os.path.join(work, "img", "square.png"), (90, 90, 90))
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{graphicx}\n"
                 "\\newcommand{\\logo}{\\includegraphics[height=1em,alt={A logo.}]{img/logo.pdf}}\n"
                 "\\newcommand{\\Image}[2]{\\includegraphics[width=#1,alt={A chart.}]{#2}}\n"
                 "\\newcommand{\\Fig}[1]{\\Image{2cm}{img/#1}}\n"
                 "\\title{Notes \\includegraphics[height=1cm,alt={A crest.}]{img/logo}}\n"
                 "\\begin{document}\n\\maketitle\n"
                 "\\section{Shapes}\nA plot: \\includegraphics[alt={A diagram.}]{img/diagram}, "
                 "and again: \\includegraphics[width=1cm]{img/diagram.pdf}, and once more: "
                 "\\includegraphics[alt={A [bracketed] plot.}]{img/diagram.pdf}. Ours: \\logo. "
                 "A graph: \\Fig{chart}.\n\n"
                 "\\begin{figure}\\centering\n\\includegraphics[width=2cm]{img/shape.eps}\n"
                 "\\caption{A shape}\\label{fig:shape}\n\\end{figure}\n\n"
                 "A square: \\includegraphics[alt={A square.}]{img/square}.\n"
                 "\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  word:\n    format: docx\n")
    tools, lacking = tools_alone(work)
    result = convert(work, env=lacking)
    said = result.stdout + result.stderr

    def page_of(folder):
        path = os.path.join(folder, "html", "notes.html")
        return read(folder, "html", "notes.html") if os.path.exists(path) else ""
    page = page_of(work)

    def word_reads_back():
        """The Word file holds the square alone, and read back as a source,
        it gives the page its square and the figure's caption."""
        import zipfile
        docx = os.path.join(work, "word", "notes.docx")
        if not os.path.exists(docx):
            return False
        with zipfile.ZipFile(docx) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        back = os.path.join(work, "back")
        os.makedirs(back)
        shutil.copy(docx, back)
        with open(os.path.join(back, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  html:\n    format: html\n")
        convert(back, env=lacking)
        again = page_of(back)
        return len(media) == 1 and media[0].endswith(".png") \
            and 'alt="A square."' in again and "A shape" in again

    # A pdftocairo that fails on every file, as on a PDF it can't read,
    # saying so after a warning and before another error, as pdftocairo
    # does; each run noted.
    runs = work + "-runs.txt"
    with open(os.path.join(tools, "pdftocairo"), "w") as fh:
        fh.write("#!/bin/sh\necho \"$@\" >> %s\n"
                 "echo 'Syntax Warning: May not be a PDF file (continuing anyway)' >&2\n"
                 "echo 'Syntax Error: Couldn'\"'\"'t find trailer dictionary' >&2\n"
                 "echo 'Syntax Error: Couldn'\"'\"'t read xref table' >&2\n"
                 "exit 1\n" % shlex.quote(runs))
    os.chmod(os.path.join(tools, "pdftocairo"), 0o755)
    again = work + "-failing"
    shutil.copytree(work, again, ignore=shutil.ignore_patterns("html", "word", "back"))
    failing = convert(again, env=lacking)
    failed_said = failing.stdout + failing.stderr
    failed_page = page_of(again)
    tried = open(runs).read().splitlines() if os.path.exists(runs) else []

    # poppler-utils' own pdftocairo, where it's installed.
    real = shutil.which("pdftocairo")
    made = work + "-made"
    made_page = []

    def made_svg():
        if not real:
            return skip("no pdftocairo to make a PDF image an SVG (sudo apt install "
                        "poppler-utils)")
        if not made_page:
            shutil.copytree(work, made, ignore=shutil.ignore_patterns("html", "word", "back"))
            os.remove(os.path.join(tools, "pdftocairo"))
            os.symlink(real, os.path.join(tools, "pdftocairo"))
            convert(made, env=lacking)
            made_page.append(page_of(made))
        sources = dict((alt, src) for src, alt in re.findall(
            r'<img\b[^>]*?src="([^"]*)"[^>]*?alt="([^"]*)"', made_page[0]))
        svg = os.path.join(made, "rendered", "img", "diagram.svg")
        root = re.search(r"<svg\b[^>]*>", open(svg, encoding="utf-8").read()).group(0) \
            if os.path.exists(svg) else ""
        return "<embed" not in made_page[0] \
            and 'width="40pt"' in root and 'height="20pt"' in root \
            and os.path.isfile(os.path.join(made, "rendered", "img", "diagram.pdf")) \
            and sources.get("A logo.", "").endswith("rendered/img/logo.svg") \
            and sources.get("A crest.", "").endswith("rendered/img/logo.svg") \
            and sources.get("A diagram.", "").endswith("rendered/img/diagram.svg") \
            and sources.get("A [bracketed] plot.", "").endswith("rendered/img/diagram.svg") \
            and sources.get("A chart.", "").endswith("rendered/img/chart.svg")
    return [
        ("without pdftocairo, a PDF or EPS image is left out of the pages, a figure's caption "
         "kept, and the run says so, naming each once and what installs what it needs",
         lambda: "WARNING: 4 PDF or EPS image(s) need epstopdf (TeX Live's epstopdf package), "
         "Ghostscript (ghostscript), and pdftocairo (poppler-utils) to become SVG images a "
         "page can show, and they aren't installed; they're left out of the pages: "
         "img/logo.pdf, img/diagram.pdf, img/chart.pdf, img/shape.eps." in said
         and "<embed" not in page and "<img" in page
         and not any(word in page for word in ("diagram", "bracketed", "logo", "crest",
                                               "chart", "shape.eps"))
         and "A shape" in page and 'alt="A square."' in page),
        ("and the Word file holds no image Word can't show, so read back it gives the page "
         "again", word_reads_back),
        ("one pdftocairo fails on is left out too, and the run says what pdftocairo said, "
         "one whose programs are missing named apart",
         lambda: re.search(
             r"^WARNING: 3 PDF or EPS image\(s\) couldn't be made SVG images a page can show, "
             r"so they're left out of the pages: img/logo\.pdf, img/diagram\.pdf, "
             r"img/chart\.pdf\. Of img/chart\.pdf, pdftocairo said: Syntax Error: Couldn't "
             r"find trailer dictionary$", failed_said, re.M) is not None
         and "WARNING: 1 PDF or EPS image(s) need epstopdf (TeX Live's epstopdf package) and "
         "Ghostscript (ghostscript) to become SVG images a page can show, and they aren't "
         "installed; they're left out of the pages: img/shape.eps." in failed_said
         and "<embed" not in failed_page and "diagram" not in failed_page
         and "logo" not in failed_page and "chart" not in failed_page
         and 'alt="A square."' in failed_page),
        ("pdftocairo is tried once for each image, not at each place the book includes it",
         lambda: len(tried) == 3),
        ("with pdftocairo, each is made an SVG, its size in points, the PDF a LaTeX build "
         "includes kept beside it, in the preamble's \\title and macro too, and a macro's "
         "that calls the book's own macro for its image",
         made_svg),
    ]


def case_scaled_images(work):
    """An image graphicx scales (scale=), which Pandoc's LaTeX reader drops
    (mkImage keeps width and height alone, Readers/LaTeX.hs, 3.13), so the
    pages showed it at its natural size: written as the width graphicx
    gives it, in inches, a PNG's pixels at its resolution (144 to the
    inch, by its pHYs) and a PDF's page (pdfinfo's crop box), as LuaLaTeX
    sets them; one with a width of its own too left as the reader reads
    it; and the run says how many."""
    os.makedirs(os.path.join(work, "img"))
    raw = b"".join(b"\x00" + bytes((90, 90, 90)) * 144 for _ in range(72))

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xffffffff))
    with open(os.path.join(work, "img", "wide.png"), "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", 144, 72, 8, 2, 0, 0, 0))
                 + chunk(b"pHYs", struct.pack(">IIB", 5669, 5669, 1))
                 + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    pdf(os.path.join(work, "img", "plot.pdf"))
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n"
                 "\\section{Scaled}\nHalf: \\includegraphics[scale=.5,alt={A half square.}]"
                 "{img/wide}. Doubled: \\includegraphics[scale=2, alt={A doubled plot.}]"
                 "{img/plot.pdf}. Sized: \\includegraphics[width=3cm,scale=.5,"
                 "alt={A sized square.}]{img/wide.png}.\n\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n")
    result = convert(work)
    said = result.stdout + result.stderr
    path = os.path.join(work, "html", "notes.html")
    page = read(work, "html", "notes.html") if os.path.exists(path) else ""

    def style(alt):
        """The style of the page's image described alt, or None."""
        for tag in re.findall(r"<img\b[^>]*>", page):
            if 'alt="%s"' % alt in tag:
                m = re.search(r'style="([^"]*)"', tag)
                return m.group(1) if m else ""
        return None
    pdfs = shutil.which("pdftocairo") and shutil.which("pdfinfo")
    return [
        ("a PNG scaled is as wide as graphicx sets it, its pixels at its resolution, in inches",
         lambda: style("A half square.") == "width:0.5in"),
        ("a PDF scaled is as wide as graphicx sets its page, in inches",
         lambda: style("A doubled plot.") == "width:1.1111in" if pdfs
         else skip("no pdftocairo or pdfinfo to make a PDF image an SVG and read its page "
                   "(sudo apt install poppler-utils)")),
        ("one given a width too is as the reader reads it, and the run counts those scaled",
         lambda: style("A sized square.") == "width:3cm"
         and re.search(r"\b%d image's scale written as the width it gives the image"
                       % (2 if pdfs else 1), said) is not None),
    ]


def case_kept_images(work):
    """A PDF image's PDF kept beside its SVG (latexsource.convert_graphic),
    read again: one whose fonts couldn't be embedded when it was kept, as
    without Ghostscript, is tried again and counted, where it had been kept
    as it was without a word; and a drawing that has taken a PDF image's
    name, its SVG made before a drawing's PDF was kept, has the image's PDF
    beside its SVG taken away, which a PDF from the pages had included in
    the drawing's place (a review), and is made again, its own PDF beside
    its SVG, where LaTeX can make it (why_no_drawings), or else its SVG
    kept as it was, alone. latexsource's own functions: the drawing as a
    reading before kept it."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild
    import latexsource
    if not shutil.which("pdftocairo"):
        return [("a kept PDF image is read again",
                 lambda: skip("no pdftocairo to make a PDF image an SVG (sudo apt install "
                              "poppler-utils)"))]
    os.makedirs(os.path.join(work, "figures"))
    image = os.path.join(work, "figures", "plot.pdf")
    pdf(image, word="Plotword")
    record, first, again = {}, {}, {}
    name, why = latexsource.convert_graphic(work, work, "figures/plot.pdf", record, first)
    beside = os.path.join(work, "rendered", "figures", "plot.pdf")
    shutil.copyfile(image, beside)
    latexsource.convert_graphic(work, work, "figures/plot.pdf", record, again)
    embedded = latexbuild.unembedded_fonts(beside) == set()
    tool = latexbuild.embedding_tool()
    preamble = "\\documentclass{article}\n\\usepackage{tikz}\n\\begin{document}\n"
    source = "\\begin{tikzpicture}\\draw (0,0) -- (1,1);\\end{tikzpicture}"
    with open(os.path.join(work, "rendered", ".rendered.json"), "w", encoding="utf-8") as fh:
        json.dump({name: hashlib.sha256((preamble + "\n" + source).encode()).hexdigest()}, fh)
    kept = latexsource.render(work, work, preamble, [(name, source)], lambda said: None)
    drawn = why_no_drawings() is None
    def mapped(path):
        """Each font's ToUnicode entries in the PDF at path, read with
        pikepdf, those of a form XObject's fonts too; None without pikepdf,
        found or not: one that can't be imported is none (the setup that
        hides it, Round 34)."""
        try:
            import pikepdf
        except ImportError:
            return None
        import pdfglyphs
        with pikepdf.open(path) as done:
            return [pdfglyphs.cmap_entries(font.ToUnicode.read_bytes())
                    if "/ToUnicode" in font else None for font in pdfglyphs.fonts(done)]
    # A PDF image whose Type 3 font names its glyph minus.case and maps it
    # to nothing, as Ghostscript leaves matplotlib's EPS.
    type3_pdf(os.path.join(work, "figures", "minus.pdf"))
    glyphs = {}
    latexsource.convert_graphic(work, work, "figures/minus.pdf", record, glyphs)
    minus = os.path.join(work, "rendered", "figures", "minus.pdf")
    first_mapped = mapped(minus)
    # Read again, its PDF one kept before glyphs were given their text, as
    # a book read before this was: given them now.
    shutil.copyfile(os.path.join(work, "figures", "minus.pdf"), minus)
    glyphs_again = {}
    latexsource.convert_graphic(work, work, "figures/minus.pdf", record, glyphs_again)
    # A drawing that includes it, as a figure's drawing may: the page LaTeX
    # makes of it has the image's font, its glyph given its text too.
    holding = "\\begin{tikzpicture}\\node{\\includegraphics{figures/minus.pdf}};\\end{tikzpicture}"
    drew = {}
    latexsource.render(work, work, preamble, [("rendered/figures/holding.svg", holding)],
                       lambda said: None, drew)
    # And a drawing LaTeX can't make, its SVG made before and recorded, a
    # PDF image's PDF beside it under its name: its SVG kept, alone.
    broken = "\\begin{tikzpicture}\\undefinedcommandhere\\end{tikzpicture}"
    old_svg = os.path.join(work, "rendered", "figures", "broken.svg")
    shutil.copyfile(os.path.join(work, "rendered", "figures", "minus.svg"), old_svg)
    stale = os.path.join(work, "rendered", "figures", "broken.pdf")
    shutil.copyfile(image, stale)
    with open(os.path.join(work, "rendered", ".rendered.json"), encoding="utf-8") as fh:
        recorded = json.load(fh)
    recorded["rendered/figures/broken.svg"] = hashlib.sha256(
        (preamble + "\n" + broken).encode()).hexdigest()
    with open(os.path.join(work, "rendered", ".rendered.json"), "w", encoding="utf-8") as fh:
        json.dump(recorded, fh)
    said = []
    kept_svg = latexsource.render(work, work, preamble, [("rendered/figures/broken.svg", broken)],
                                  said.append)
    # Without pdfseparate: a drawing whose SVG is current isn't made again
    # for a PDF it can't have, which had made every drawing again on every
    # run (a review), a PDF image's PDF under its name taken away all the
    # same, and the run says so; and where pdfseparate fails, having
    # written part of a page, the drawing is its SVG alone, the part gone.
    plain = "\\begin{tikzpicture}\\draw (0,0) circle (1);\\end{tikzpicture}"
    circle = "rendered/figures/circle.svg"
    shutil.copyfile(os.path.join(work, "rendered", "figures", "minus.svg"),
                    os.path.join(work, circle))
    with open(os.path.join(work, "rendered", ".rendered.json"), encoding="utf-8") as fh:
        recorded = json.load(fh)
    recorded[circle] = hashlib.sha256((preamble + "\n" + plain).encode()).hexdigest()
    with open(os.path.join(work, "rendered", ".rendered.json"), "w", encoding="utf-8") as fh:
        json.dump(recorded, fh)
    taken = os.path.join(work, "rendered", "figures", "circle.pdf")
    shutil.copyfile(image, taken)
    before = os.path.getmtime(os.path.join(work, circle))
    which, run = latexsource.shutil.which, latexsource.subprocess.run
    unseparated = []
    try:
        latexsource.shutil.which = lambda name: None if name == "pdfseparate" else which(name)
        alone = latexsource.render(work, work, preamble, [(circle, plain)], unseparated.append)
    finally:
        latexsource.shutil.which = which
    unmade = os.path.getmtime(os.path.join(work, circle)) == before
    gone = not os.path.exists(taken)

    def failing(command, *args, **kwargs):
        """pdfseparate writing part of the first page, and failing."""
        if command[0] == "pdfseparate":
            with open(command[2] % 1, "wb") as fh:
                fh.write(b"%PDF-1.7\n")
            return subprocess.CompletedProcess(command, 1, "", "Syntax Error")
        return run(command, *args, **kwargs)
    square = "\\begin{tikzpicture}\\draw (0,0) rectangle (1,1);\\end{tikzpicture}"
    try:
        latexsource.subprocess.run = failing
        partly = latexsource.render(work, work, preamble, [("rendered/figures/square.svg",
                                                           square)], lambda said: None)
    finally:
        latexsource.subprocess.run = run
    leftovers = [f for f in os.listdir(os.path.join(work, "render")) if "-page-" in f] \
        if os.path.isdir(os.path.join(work, "render")) else []

    def own_pdf():
        if not os.path.exists(beside):
            return False
        text = subprocess.run(["pdftotext", beside, "-"], capture_output=True, text=True).stdout
        with open(os.path.join(work, "rendered", ".rendered.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        return "Plotword" not in text and record.get("rendered/figures/plot.pdf") == record.get(name)
    return [
        ("a PDF image kept with fonts it couldn't embed, read again, is tried again, and "
         "counted",
         lambda: name == "rendered/figures/plot.svg" and why is None
         and (again == {"graphics_embedded": 1} and embedded if tool
              else again == {"graphics_unembedded": 1})),
        ("a drawing that has taken a PDF image's name has the drawing's own PDF beside its "
         "SVG, made again, where LaTeX can make it, and else no PDF, its SVG kept as it was",
         # A LaTeX too old for the suite's builds (tex_unready) may draw it
         # all the same: its own PDF then, and never the image's.
         lambda: kept == [name] and (own_pdf() if drawn
                                     else own_pdf() or not os.path.exists(beside))),
        ("a drawing LaTeX can't make again has its SVG made before kept, alone, the PDF "
         "beside it under its name taken away, and the run says so",
         lambda: kept_svg == ["rendered/figures/broken.svg"] and not os.path.exists(stale)
         and (not drawn or any("kept as the SVGs made of them before, without their PDFs"
                               in line for line in said))),
        ("a PDF image whose Type 3 font names its glyph minus.case, mapped to nothing, is "
         "kept with the glyph given its text, U+2212, and counted",
         lambda: (glyphs.get("graphics_glyphs") == 1 and first_mapped == [{0: "2212"}])
         if first_mapped is not None else skip("no pikepdf to read the PDF")),
        ("and read again, its PDF kept before glyphs were given their text, is given them now",
         lambda: (glyphs_again == {"graphics_glyphs": 1} and mapped(minus) == [{0: "2212"}])
         if first_mapped is not None else skip("no pikepdf to read the PDF")),
        ("without pdfseparate, a drawing whose SVG is current isn't made again, a PDF image's "
         "PDF under its name is taken away all the same, and the run says the drawings are "
         "SVGs alone",
         lambda: alone == [circle] and unmade and gone
         and any("pdfseparate (poppler-utils) isn't installed" in line for line in unseparated)),
        ("where pdfseparate fails, having written part of a page, the drawing is its SVG alone, "
         "and no part of a page is left",
         lambda: skip("no LaTeX to make drawings") if not drawn
         else partly == ["rendered/figures/square.svg"] and not leftovers
         and not os.path.exists(os.path.join(work, "rendered", "figures", "square.pdf"))),
        ("a drawing that includes it has the image's glyph given its text in the page LaTeX "
         "made of it",
         lambda: skip("no pikepdf to read the PDF") if first_mapped is None
         else skip("no LaTeX to make drawings") if not drawn
         else drew.get("graphics_glyphs") == 1 and {0: "2212"} in mapped(
             os.path.join(work, "rendered", "figures", "holding.pdf"))),
    ]


def case_unmade_svg(work):
    """The latex target without rsvg-convert, on a PATH holding Pandoc,
    Python, and file alone (tools_alone): its SVG picture left as LaTeX's
    \\includesvg, which needs Inkscape and takes no alt text, and the run
    says so, the one way the suite's other cases can't take where it
    runs."""
    os.makedirs(os.path.join(work, "img"))
    with open(os.path.join(work, "img", "circle.svg"), "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                 '<circle cx="20" cy="20" r="15" fill="black"/></svg>\n')
    with open(os.path.join(work, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("# Circles\n\nA circle:\n\n![A black circle.](img/circle.svg)\n")
    with open(os.path.join(work, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: circles\n  title: Circles\n  language: en\n"
                 "  contents:\n  - one\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  latex:\n    format: latex\n")
    _, lacking = tools_alone(work)
    result = convert(work, env=lacking)
    said = result.stdout + result.stderr
    one = read(work, "latex", "one.tex") \
        if os.path.exists(os.path.join(work, "latex", "one.tex")) else ""
    return [
        ("without rsvg-convert, the latex target leaves its SVG picture to LaTeX's "
         "\\includesvg, beside it, and the run says so",
         lambda: result.returncode == 0 and re.search(r"\\includesvg(\[[^]]*\])?\{img/circle",
                                                      one) is not None
         and os.path.exists(os.path.join(work, "latex", "img", "circle.svg"))
         and not os.path.exists(os.path.join(work, "latex", "img", "circle.pdf"))
         and "WARNING: 1 SVG image(s) weren't made PDF (img/circle.svg first): rsvg-convert "
         "is needed (sudo apt install librsvg2-bin)" in said),
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
              "\\usepackage{tikz}\n\\usepackage{amsthm}\n\\usepackage[english]{babel}\n"
              "\\pdfcompresslevel=9\n"
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
              "A line: \\begin{tikzpicture}\\draw (0,0) -- (2,1);\\end{tikzpicture}.\n\n"
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
                 "rendered/notes-1.svg,Two boxes\nrendered/notes-2.svg,A rising line\n"
                 "figures/f.png,[decorative]\n"
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
                                            if "Name" in r.get("preview", ""))
                 + "".join("%s,layout\n" % r["key"] for r in rows
                           if "Item" in r.get("preview", "")))
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
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import texremediate

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
        why = why_no_tex("no lualatex to build the tagged copy", "lualatex")
        if why:
            return skip(why)
        status, log = build(os.path.join(work, "tagged"), "lualatex", passes=2)
        return status == 0 and "para hooks differ" not in log \
            and "Parent-Child" not in log and "already defined" not in log

    def alt_in_tagged_pdf():
        """The tagged build's figures carry the macro's image's alt text."""
        why = why_no_tex("no lualatex to build the tagged copy", "lualatex")
        if why:
            return skip(why)
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
            and alts.count("A fifth [square]") == 2 and "Two boxes" in alts \
            and "A rising line" in alts

    def mathml_in_tagged_pdf():
        """The tagged build's formula carries its MathML, from unicode-math:
        the set-builder bar the definitions file makes \\mid is U+2223."""
        why = why_no_tex("no lualatex to build the tagged copy", "lualatex")
        if why:
            return skip(why)
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
        why = why_no_tex("no lualatex to build the tagged copy", "lualatex")
        if why:
            return skip(why)
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
        why = why_no_tex("no pdflatex to build the tagged copy untagged", "pdflatex")
        if why:
            return skip(why)
        status, _ = build(os.path.join(work, "tagged"), "pdflatex",
                          re.sub(r"\\DocumentMetadata\{[^}]*\}\n", "", tagged))
        return status == 0

    def builds():
        engine = shutil.which("pdflatex")
        why = why_no_tex("no pdflatex to build the remediated copy", "pdflatex")
        if why:
            return skip(why)
        build = os.path.join(work, "build")
        shutil.copytree(work, build, ignore=shutil.ignore_patterns(
            "fixed", "html", "build", "rendered"))
        shutil.copytree(fixed, build, dirs_exist_ok=True)
        done = subprocess.run([engine, "-interaction=nonstopmode", "notes.tex"],
                              cwd=build, capture_output=True, text=True, timeout=120)
        return done.returncode == 0

    def keys_skipped_against_older():
        """The block on its own, with the keys and \\picture defined as older
        releases have them: \\picture taking no options (LaTeX before
        2026-06-01), TikZ's alt and artifact undefined (pgf before 3.1.12),
        and graphicx's too (before 1.2e). A document using every key the
        copy writes, and a picture without them, builds with the block and
        stops without it, whatever the TeX: an up-to-date TeX Live 2026
        needs the block for none of them, so the book's copy can't show it."""
        engine = shutil.which("pdflatex")
        why = why_no_tex("no pdflatex to build the block against older definitions", "pdflatex")
        if why:
            return skip(why)
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import texremediate
        here = os.path.join(work, "keys-older")
        os.makedirs(here, exist_ok=True)
        shutil.copy(os.path.join(work, "sq.png"), here)
        older = ("\\makeatletter\n"
                 "\\long\\def\\picture#1{\\pictur@#1}\n"
                 "\\expandafter\\let\\csname pgfk@/tikz/alt/.@cmd\\endcsname\\@undefined\n"
                 "\\expandafter\\let\\csname pgfk@/tikz/artifact/.@cmd\\endcsname\\@undefined\n"
                 "\\expandafter\\let\\csname KV@Gin@alt\\endcsname\\@undefined\n"
                 "\\expandafter\\let\\csname KV@Gin@artifact\\endcsname\\@undefined\n"
                 "\\makeatother\n")
        body = ("\\begin{document}\n"
                "\\includegraphics[alt={A square},width=1cm]{sq.png}\n"
                "\\includegraphics[artifact,width=1cm]{sq.png}\n"
                "\\begin{picture}[alt={Two boxes}](40,20)\\put(0,0){\\framebox(40,20){two}}"
                "\\end{picture}\n"
                "\\begin{picture}(40,20)\\put(0,0){\\framebox(40,20){plain}}\\end{picture}\n"
                "\\begin{tikzpicture}[alt={A rising line}]\\draw (0,0) -- (2,1);"
                "\\end{tikzpicture}\n"
                "\\begin{tikzpicture}[artifact]\\draw (0,0) -- (1,1);\\end{tikzpicture}\n"
                "\\end{document}\n")
        built = {}
        for name, block in (("with", texremediate.KEYS_SKIPPED), ("without", "")):
            with open(os.path.join(here, name + ".tex"), "w", encoding="utf-8") as fh:
                fh.write("\\documentclass{article}\n\\usepackage{graphicx}\n"
                         "\\usepackage{tikz}\n" + older + block + body)
            done = subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error",
                                   name + ".tex"], cwd=here, capture_output=True,
                                  text=True, timeout=120, stdin=subprocess.DEVNULL)
            built[name] = done.returncode == 0
            if name == "with":
                built_or_why(built[name], done.stdout)
        return built["with"] and not built["without"]
    return [
        ("an image's alt text joins its own keys, escaped",
         lambda: "\\includegraphics[alt={A gray square: 50\\% shaded},width=1cm]{sq}"
         in notes),
        ("a drawing in the text gets its alt text",
         lambda: "\\begin{picture}[alt={Two boxes}](40,20)" in notes),
        # pdfLaTeX stops on a tikzpicture's key without tagging with pgf
        # before 3.1.12, and on a picture's before LaTeX 2026-06-01; builds()
        # below builds the copy, and the block is built against those older
        # definitions on its own.
        ("a tikzpicture too, and a block before \\begin{document} skips a key the "
         "LaTeX building the copy doesn't know, and the run says so",
         lambda: "\\begin{tikzpicture}[alt={A rising line}]" in notes
         and 0 < notes.find("\\long\\def\\TIQkernelpicture") < notes.find("\\begin{document}")
         and notes.count("\\TIQatcode") == 2 and "skips any key" in said),
        ("against the keys and \\picture as older releases define them, a document "
         "using every key builds with the block and stops without it",
         keys_skipped_against_older),
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
         lambda: fingerprint(work, skip_dirs=("fixed", "tagged", "kept", "plainmath", "build",
                                           "keys-older")) == before),
        ("the remediated copy builds with pdfLaTeX, as the author's does", builds),
        ("tagging: \\DocumentMetadata, the book's language, the font setting just after it, "
         "babel's main language the book's, pdfTeX's option and setting out",
         lambda: tagged.startswith("\\DocumentMetadata{lang=en, pdfstandard=ua-2, tagging=on}\n"
                                   + texremediate.STATIC_FONTS
                                   + texremediate.BABEL_MAIN % "english"
                                   + "\\documentclass[12pt]{article}")
         and "\\pdfcompresslevel" not in tagged),
        ("tagging: the starred theorem defined only when tagging hasn't",
         lambda: "\\ifcsname thm*\\endcsname\\else\\newtheorem*{thm*}{Theorem}\\fi" in tagged),
        ("tagging: \\centerline redefined, and \\leavevmode before the formula",
         lambda: "\\renewcommand{\\centerline}" in tagged
         and "\\begin{center}\n\\leavevmode\\[" in tagged),
        ("tagging: a person's header row declared for the table, in a group of its own",
         lambda: "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/header-rows={1}}\\fi"
         "\\begin{tabular}{cc}" in tagged and tagged.count("\\tagpdfsetup{table/header") == 1),
        ("tagging: a person's layout table declared as a division of paragraphs, in a "
         "group of its own, and the run says so",
         lambda: "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi"
         "\\begin{tabular}{cc}\nItem" in tagged
         and tagged.count("\\tagpdfsetup{table/tagging=div}") == 1
         and "1 table(s) declared a layout table" in said),
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
         lambda: skip(why_no_status()) if why_no_status()
         else "currently incompatible: amsthm" in said and "unchecked: babel" in said
         and "not in the list: graphicx" in said and "older than the LaTeX it checks" in said),
        ("tagging off leaves the book's build alone",
         lambda: "\\DocumentMetadata" not in notes and "pdftex" in notes),
        ("the tagged copy builds with LuaLaTeX, no tagging error or warning", builds_tagged),
        ("and the image behind the macro has its alt text in the PDF, the drawings theirs",
         alt_in_tagged_pdf),
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
        why = why_no_tex("no lualatex to build the copy", "lualatex")
        if why:
            return skip(why)
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


def case_static_face(work):
    """A tagged copy of a book that sets its face with fontspec, Josefin
    Sans, which has a STAT table and isn't a variable font: built with
    LuaLaTeX, the face is embedded from its file, as in a book's PDF from
    its pages (latexbuild.STATIC_FONTS, which the copy reads just after
    \\DocumentMetadata), not as luaotfload embeds a variable font, whose
    accented letters have no parts. Skipped where TeX hasn't Josefin Sans
    (TeX Live's josefin)."""
    os.makedirs(work)
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{fontspec}\n"
                 "\\setmainfont{JosefinSans}[Extension=.ttf, UprightFont=*-Regular, "
                 "BoldFont=*-Bold]\n\\begin{document}\n"
                 "Accented letters, \u0177 and \u012b, and in bold, \\textbf{\u0177}.\n"
                 "\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n")
    result = convert(work)
    copy = os.path.join(work, "tagged", "notes.tex")

    def embedded():
        why = why_no_tex("no lualatex to build the copy", "lualatex")
        if why:
            return skip(why)
        found = shutil.which("kpsewhich") and subprocess.run(
            ["kpsewhich", "JosefinSans-Regular.ttf"], capture_output=True, text=True,
            stdin=subprocess.DEVNULL).stdout.strip()
        if not found:
            return skip("Josefin Sans isn't installed (TeX Live's josefin); a face with a STAT "
                        "table that isn't a variable font isn't checked")
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return skip("no pikepdf to read the PDF's fonts")
        import pdftext
        tree = os.path.join(work, "build")
        os.makedirs(tree)
        shutil.copy(copy, os.path.join(tree, "notes.tex"))
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "notes.tex"], cwd=tree, capture_output=True, text=True,
                              timeout=300)
        path = os.path.join(tree, "notes.pdf")
        if not built_or_why(done.returncode == 0 and os.path.exists(path), done.stdout):
            return False
        glyphs = pdftext.truetype_glyphs(path)

        def accented(face):
            """Whether the face, as the PDF embeds it, draws a letter from
            its parts, each part drawn."""
            drawn = {number for number, _parts in glyphs.get(face, [])}
            whole = [parts for _number, parts in glyphs.get(face, []) if parts]
            return bool(whole) and all(part in drawn for parts in whole for part in parts)
        return accented("JosefinSans-Regular") and accented("JosefinSans-Bold")
    return [
        ("a tagged copy of a book that sets a face with a STAT table that isn't a variable "
         "font, Josefin Sans, embeds it from its file under LuaLaTeX, an accented letter "
         "drawn from its parts, each part drawn, in its regular and its bold",
         lambda: result.returncode == 0 and os.path.exists(copy) and embedded()),
    ]


BOOK_MASTER = ("\\documentclass{book}\n\\usepackage{graphicx}\n\\usepackage{amsmath,amssymb}\n"
               "\\usepackage{cancel}\n\\newcommand{\\arc}[1]{\\overset{\\frown}{#1}}\n"
               "\\usepackage{makeidx}\n\\makeindex\n\\title{A Small Book}\n\\author{An Author}\n"
               "\\begin{document}\n\\maketitle\n\\include{one}\n\\printindex\n\\end{document}\n")
BOOK_CHAPTER = ("\\chapter{One}\nSome text about sets\\index{sets}, where "
                "$\\mathbb{N} \\subseteq \\mathbb{Z}$ and $x \\neq y$.\n"
                "Terms struck out, $\\frac{\\cancel{3}x}{\\cancel{3}} = x$, and an arc, "
                "$\\arc{AB}$, by a command of the book's own named as one of pict2e's.\n"
                "\\begin{figure}[t]\\centering\\includegraphics[width=2cm]{sq}"
                "\\caption{A square}\\label{fig:sq}\\end{figure}\n"
                "After the figure in the source, Figure~\\ref{fig:sq}.\n\n"
                "\\begin{tabular}{cc}\nName & Value \\\\\na & 1 \\\\\nb & 2 \\\\\n"
                "\\end{tabular}\n\n"
                "\\[ \\sum_{i=1}^n i = \\frac{n(n+1)}{2} \\]\n\n"
                "A drawing with no description: "
                "\\begin{picture}(60,12)\\put(0,0){Drawword}\\end{picture}\n")


# A figure the pages book (case_book_pdf) adds to BOOK_CHAPTER: a PDF R's
# pdf() device could have drawn, a heat map and a word in Helvetica, which
# it doesn't embed (raster_pdf).
PLOT_FIGURE = ("\\begin{figure}[h]\\centering\\includegraphics{plot}"
               "\\caption{A plot}\\end{figure}\n")


def case_book_pdf(work):
    """A LaTeX book's PDF, built from the book's own LaTeX (pdf.from: book):
    its index, which the pages don't have, its figure's alt text from the
    sidecar, its formulas' MathML, and its figure tagged in place; built
    from the pages instead with pdf.from: pages; and a book that won't
    build with tagging stops the run with LaTeX's error and the way out."""
    why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
    if why:
        return [("a LaTeX book's PDF is built from its own LaTeX",
                 lambda: skip(why))]
    books = {}
    for name, extra, targets in (
            ("book", "", "  pdf:\n    format: pdf\n"),
            # Its preamble gives no layout: parskip's paragraphs, not
            # indented ones, and no size, paper, or margins.
            # And a PDF figure of R's kind (raster_pdf), set from the PDF
            # the book's own build includes, in the PDF and the latex
            # target, where the pages show its SVG.
            ("pages", "\\usepackage{parskip}\n",
             "  pdf:\n    format: pdf\n    pdf:\n      from: pages\n"
             "  latex:\n    format: latex\n"),
            # Builds with pdfLaTeX, as the conversion reads it, and stops
            # with LuaLaTeX, as the PDF target builds it.
            ("broken", "\\ifdefined\\directlua\\TIQundefined\\fi\n", "  pdf:\n    format: pdf\n")):
        book = os.path.join(work, name)
        os.makedirs(book)
        png(os.path.join(book, "sq.png"), (128, 128, 128))
        with open(os.path.join(book, "book.tex"), "w", encoding="utf-8") as fh:
            fh.write(BOOK_MASTER.replace("\\begin{document}", extra + "\\begin{document}"))
        with open(os.path.join(book, "one.tex"), "w", encoding="utf-8") as fh:
            fh.write(BOOK_CHAPTER + (PLOT_FIGURE if name == "pages" else ""))
        if name == "pages":
            raster_pdf(os.path.join(book, "plot.pdf"), word="Plotword")
        with open(os.path.join(book, "image-alt.csv"), "w", encoding="utf-8") as fh:
            fh.write("Image,Alt\nsq.png,A gray square\nrendered/plot.svg,A heat map\n")
        with open(os.path.join(book, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n" + targets)
        result = convert(book)
        books[name] = (book, result.returncode, result.stdout + result.stderr)

    def text(name):
        """The PDF's text: nothing for a PDF that wasn't built, whose checks
        fail, and None for one with no pdftotext to read it, whose checks
        skip."""
        path = os.path.join(books[name][0], "pdf", "book.pdf")
        if not os.path.exists(path):
            return ""
        if not shutil.which("pdftotext"):
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
        validator accepts and the output check reports, reading the PDF with
        pypdf."""
        try:
            import pypdf  # noqa: F401
        except ImportError:
            return skip("no pypdf for the output check to read the PDF")
        report = os.path.join(books["book"][0], "output-check.csv")
        if not os.path.exists(report):
            return False
        with open(report, encoding="utf-8-sig") as fh:
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

    def pages_unbuilt():
        """Why there's no PDF from the pages here, or None: the pages hold
        the drawing as an SVG, which a PDF needs rsvg-convert to make a PDF
        of, and the run stopped, saying so (why_no_svg)."""
        if why_no_svg() and "needs rsvg-convert" in books["pages"][2]:
            return why_no_svg()
        return None

    def built_from_pages():
        if pages_unbuilt():
            return skip(pages_unbuilt())
        found = text("pages")
        if found is None:
            return skip("no pdftotext to read the PDF")
        return books["pages"][1] == 0 and "built by LaTeX from the book's own files" \
            not in books["pages"][2] and "sets" in found and "Index" not in found

    def class_page_kept():
        """The book's preamble gives no layout, so its PDF from the pages
        has the book class's own page, not the PDF target's default: its
        words in 10pt type (9.96 of the PDF's points), not 12pt, as much
        as 3% either way where microtype's font expansion justifies a
        line. convert.py passes on the empty layout, as it does any."""
        if pages_unbuilt():
            return skip(pages_unbuilt())
        try:
            import pypdf
        except ImportError:
            return skip("no pypdf to read the PDF")
        import math
        path = os.path.join(books["pages"][0], "pdf", "book.pdf")
        if not os.path.exists(path):
            return False
        found = []
        for page in pypdf.PdfReader(path).pages:
            def visit(text, cm, tm, font, size):
                if "Some text about" in text:
                    found.append(size * math.hypot(tm[0], tm[1]) * math.hypot(cm[0], cm[1]))
            page.extract_text(visitor_text=visit)
        return bool(found) and all(abs(size / 9.96 - 1) < 0.03 for size in found)

    def plot_kept():
        """The PDF figure, set in the PDF from the pages and the latex target
        as the PDF the book's own build includes, rendered/plot.pdf, its
        font embedded: its word text, and its picture the figure's own, 128
        pixels square, stored losslessly and, where Ghostscript embedded the
        font, not interpolated, where the SVG made the word outlines, and
        pdftocairo and rsvg-convert make a picture in it a copy, resampled
        and interpolated; pdftocairo, which embeds it without Ghostscript,
        marks the picture to be interpolated too (poppler 24.02). The SVG the
        pages show is the figure's size, 40 points by 48, where poppler 24.02
        wrote it in pixels, three quarters of it."""
        if pages_unbuilt():
            return skip(pages_unbuilt())
        if not shutil.which("pdftocairo"):
            return skip("no pdftocairo to make the PDF figure an SVG (sudo apt install "
                        "poppler-utils)")
        found = text("pages")
        if found is None:
            return skip("no pdftotext to read the PDF")
        try:
            import pypdf
        except ImportError:
            return skip("no pypdf to read the PDF's images and fonts")
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import latexbuild
        folder = books["pages"][0]
        kept = os.path.join(folder, "rendered", "plot.pdf")
        latex = os.path.join(folder, "latex")
        tex = "".join(read(folder, "latex", f) for f in os.listdir(latex)
                      if f.endswith(".tex")) if os.path.isdir(latex) else ""
        with open(os.path.join(folder, "rendered", "plot.svg"), encoding="utf-8") as fh:
            root = re.search(r"<svg\b[^>]*>", fh.read()).group(0)
        images = []
        for page in pypdf.PdfReader(os.path.join(folder, "pdf", "book.pdf")).pages:
            for image in page.images:
                obj = image.indirect_reference.get_object() if image.indirect_reference else {}
                images.append((obj.get("/Width"), obj.get("/Height"), obj.get("/Filter"),
                               bool(obj.get("/Interpolate", False))))
        smoothed = latexbuild.embedding_tool() != "gs"
        return "Plotword" in found and (128, 128, "/FlateDecode", smoothed) in images \
            and latexbuild.unembedded_fonts(kept) == set() \
            and os.path.isfile(os.path.join(latex, "rendered", "plot.pdf")) \
            and "rendered/plot.pdf" in tex and "plot.svg" not in tex \
            and 'width="40pt"' in root and 'height="48pt"' in root

    def drawing_kept():
        """The drawing, set in the PDF from the pages and the latex target
        as the page LaTeX made of it, rendered/one-1.pdf beside the SVG its
        pages show: its word text, where the SVG made it outlines, as it
        made a PDF image's before Round 33 and a drawing's before Round 34."""
        if pages_unbuilt():
            return skip(pages_unbuilt())
        if why_no_drawings():
            return skip(why_no_drawings())
        found = text("pages")
        if found is None:
            return skip("no pdftotext to read the PDF")
        folder = books["pages"][0]
        latex = os.path.join(folder, "latex")
        tex = "".join(read(folder, "latex", f) for f in os.listdir(latex)
                      if f.endswith(".tex")) if os.path.isdir(latex) else ""
        kept = os.path.join(folder, "rendered", "one-1.pdf")
        own = subprocess.run(["pdftotext", kept, "-"], capture_output=True,
                             text=True).stdout if os.path.isfile(kept) else ""
        return "Drawword" in own and "Drawword" in found \
            and os.path.isfile(os.path.join(folder, "rendered", "one-1.svg")) \
            and os.path.isfile(os.path.join(latex, "rendered", "one-1.pdf")) \
            and "rendered/one-1.pdf" in tex and "one-1.svg" not in tex

    def pages_pass_ua2():
        verapdf = os.environ.get("VERAPDF") or shutil.which("verapdf")
        if not verapdf:
            return skip("no veraPDF to check the PDF")
        if pages_unbuilt():
            return skip(pages_unbuilt())
        done = subprocess.run([verapdf, "-f", "ua2", "--format", "text",
                               os.path.join(books["pages"][0], "pdf", "book.pdf")],
                              capture_output=True, text=True)
        return done.stdout.strip().startswith("PASS")

    def struck_out():
        """A term the book strikes out with cancel, in its PDF from its own
        LaTeX and from its pages: two strokes drawn as paths, no glyph of
        the line10 font, and the book's own \\arc, a name pict2e has.
        texremediate adds latexbuild.PICTURE_PATHS to the copy."""
        if pages_unbuilt():
            return skip(pages_unbuilt())
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return skip("no pikepdf to read the PDF")
        import pdftext
        for name in ("book", "pages"):
            path = os.path.join(books[name][0], "pdf", "book.pdf")
            if not os.path.exists(path):
                return False
            found = text(name)
            if found is None:
                return skip("no pdftotext to read the PDF")
            if len(pdftext.diagonal_strokes(path)) != 2 or "\u2322" not in found \
                    or {"LINE10", "LINEW10"} & pdftext.base_fonts(path):
                return False
        return "cancel set to draw with pict2e" in books["book"][2]
    return [
        ("a LaTeX book's PDF is built from its own LaTeX: its index is there", built_from_book),
        ("its figure has the sidecar's alt text, its formulas MathML, its figure in place, "
         "its table the census's header row",
         tagged_from_book),
        ("and it passes veraPDF's PDF/UA-2 profile", passes_ua2),
        ("a term it strikes out with cancel is drawn as lines, from its own LaTeX and from "
         "its pages, with no glyph of LaTeX's line10 font, and pict2e, loaded for it, "
         "leaves the book its own \\arc; the run says so", struck_out),
        ("the output check reports LaTeX's placeholder alt text for a drawing with none",
         placeholder_reported),
        ("pdf.from: pages builds it from the pages, which have no index", built_from_pages),
        ("and, its preamble giving no layout, on the book class's own page, not the PDF "
         "target's default: 10pt type", class_page_kept),
        ("and a PDF figure in it, and in the latex target, is the PDF the book's own build "
         "includes, its font embedded: its word text and its picture its own, not the "
         "outlines and the resampled picture of the SVG its pages show, which is the "
         "figure's size in points", plot_kept),
        ("and its drawing, in both, the page LaTeX made of it, its word text, not the outlines "
         "of the SVG its pages show", drawing_kept),
        ("and the PDF from the pages passes veraPDF's PDF/UA-2 profile", pages_pass_ua2),
        ("a book that won't build with tagging stops the run, with LaTeX's error and the way out",
         lambda: books["broken"][1] != 0 and "TIQundefined" in books["broken"][2]
         and "wasn't built" in books["broken"][2] and "pdf.from: pages" in books["broken"][2]),
    ]


def case_struck_out(work):
    """A term struck out with cancel, in the pieces no other book here
    reaches: a tagged copy's report, a copy made from a copy, a book that
    loads pict2e itself, a command of a pict2e name made at \\begin{document};
    and a picture with no cancel, drawn with paths unless picture_paths is
    off (latexbuild.PICTURE_PATHS)."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild
    import texremediate
    os.makedirs(work)
    master = ("\\documentclass{article}\n\\usepackage{amsmath}\n\\usepackage{cancel}\n"
              "\\newcommand{\\cbezier}{a curve of the book's own}\n\\begin{document}\n"
              "A term struck out, $\\cancel{3}x$, and \\cbezier.\n\\end{document}\n")
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write(master)
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n")
    result = convert(work)
    said = result.stdout + result.stderr
    copy = os.path.join(work, "tagged", "notes.tex")
    # A book with a picture and no cancel, copied with picture_paths as it
    # is by default and off: pict2e in the first copy, the run saying so,
    # and none in the second.
    pictures = os.path.join(work, "pictures")
    os.makedirs(pictures)
    with open(os.path.join(pictures, "drawn.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\begin{document}\nA circle, "
                 "\\begin{picture}(9,9)\\put(4,4){\\circle{8}}\\end{picture}.\n"
                 "\\end{document}\n")
    with open(os.path.join(pictures, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  paths:\n    format: source\n    tagging: \"on\"\n"
                 "  fonts:\n    format: source\n    tagging: \"on\"\n"
                 "    picture_paths: \"off\"\n")
    drawn = convert(pictures)
    drawn_said = drawn.stdout + drawn.stderr

    def build(name, text):
        """(LaTeX's exit status, the PDF's path, its text) for text, built
        untagged or as it says, in a folder of its own."""
        folder = os.path.join(work, name)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "page.tex"), "w", encoding="utf-8") as fh:
            fh.write(text)
        done = subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error",
                               "page.tex"], cwd=folder, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=300)
        pdf = os.path.join(folder, "page.pdf")
        found = subprocess.run(["pdftotext", pdf, "-"], capture_output=True,
                               text=True).stdout if os.path.exists(pdf) else ""
        return done.returncode, pdf, found

    def tools():
        why = why_no_tex("no lualatex or pdftotext to build and read the page", "lualatex",
                         "pdftotext")
        if why:
            return why
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return "no pikepdf to read the PDF"
        return None

    def copy_of_copy():
        """The tagged copy made again from itself, as a copy laid over the
        book's folder is: PICTURE_PATHS once, and it builds, its term
        struck out a path and the book's own \\cbezier its own."""
        missing = tools()
        if missing:
            return skip(missing)
        import pdftext
        if not os.path.exists(copy):
            return False
        texts = {"notes.tex": read(work, "tagged", "notes.tex")}
        texremediate.tag(texts, "notes.tex", "en", True, ("ua-2",), None)
        status, pdf, found = build("again", texts["notes.tex"])
        return texts["notes.tex"].count("\\clist_const:Nn \\c__oer_pictiie_names_clist") == 1 \
            and status == 0 and len(pdftext.diagonal_strokes(pdf)) == 1 \
            and "a curve of the book" in found

    def own_pict2e():
        """A book that loads pict2e itself keeps all of it: its \\cbezier,
        which pict2e makes at \\begin{document}, draws."""
        missing = tools()
        if missing:
            return skip(missing)
        import pdftext
        status, pdf, _ = build("own", (
            "\\documentclass{article}\n\\usepackage{cancel}\n\\usepackage{pict2e}\n"
            + latexbuild.PICTURE_PATHS + "\\begin{document}\n$\\cancel{3}$\n"
            "\\begin{picture}(40,20)\\cbezier(0,0)(10,20)(30,20)(40,0)\\end{picture}\n"
            "\\end{document}\n"))
        return status == 0 and len(pdftext.diagonal_strokes(pdf)) == 1

    def own_names():
        """A document's own \\buttcap and \\maxovalrad, which pict2e makes
        too, kept beside it: its \\circle, \\oval, and \\circle* drawn
        with pict2e's \\buttcap all the same, as paths, four curves each,
        the \\oval reading the document's \\maxovalrad. A \\buttcap of
        the document's own had been replaced by pict2e's, and a
        \\maxovalrad had stopped LaTeX ("already defined")."""
        missing = tools()
        if missing:
            return skip(missing)
        import pdftext
        status, pdf, found = build("own-names", (
            "\\documentclass{article}\n\\newcommand{\\buttcap}{BUTT}\n"
            "\\newcommand{\\maxovalrad}{5pt}\n" + latexbuild.PICTURE_PATHS
            + "\\begin{document}\nOwn: \\buttcap, \\maxovalrad.\n\n"
            "\\setlength{\\unitlength}{1pt}\\begin{picture}(100,60)\\put(30,30){\\circle{40}}"
            "\\put(70,30){\\oval(30,20)}\\put(90,30){\\circle*{6}}\\end{picture}\n"
            "\\end{document}\n"))
        return status == 0 and "Own: BUTT, 5pt." in found and pdftext.curves(pdf) == {0: 12}

    # A circle asked for at 80 points, which LaTeX's lcircle10 draws at
    # 40, its largest, and pict2e at 80, as a path; \\maxovalrad, which
    # pict2e defines and leaves, says whether it's loaded.
    picture = ("\\begin{document}\n\\ifdefined\\maxovalrad pict2e loaded\\else no pict2e"
               "\\fi\n\n\\setlength{\\unitlength}{1pt}\\begin{picture}(90,90)"
               "\\put(45,45){\\circle{80}}\\end{picture}\n\\end{document}\n")

    def without_cancel(paths):
        """A document with no cancel loads pict2e, which draws its circle
        with a path, and none with PICTURE_FONTS before it (picture_paths
        off), LaTeX drawing the circle with lcircle10's glyphs."""
        missing = tools()
        if missing:
            return skip(missing)
        import pdftext
        status, pdf, found = build("paths" if paths else "fonts", (
            "\\documentclass{article}\n" + ("" if paths else latexbuild.PICTURE_FONTS)
            + latexbuild.PICTURE_PATHS + picture))
        fonts = pdftext.base_fonts(pdf) if status == 0 else set()
        return status == 0 and (("pict2e loaded" in found and "LCIRCLE10" not in fonts)
                                if paths else
                                ("no pict2e" in found and "LCIRCLE10" in fonts))

    def fonts_with_cancel():
        """With PICTURE_FONTS and cancel, pict2e is loaded for the struck-out
        term, as before, and draws the picture too."""
        missing = tools()
        if missing:
            return skip(missing)
        import pdftext
        status, pdf, found = build("fonts-cancel", (
            "\\documentclass{article}\n\\usepackage{cancel}\n" + latexbuild.PICTURE_FONTS
            + latexbuild.PICTURE_PATHS + picture.replace(
                "\\end{document}", "$\\cancel{3}$\n\\end{document}")))
        return status == 0 and "pict2e loaded" in found \
            and len(pdftext.diagonal_strokes(pdf)) == 1 and "LCIRCLE10" not in pdftext.base_fonts(pdf)

    def tagged_copies():
        """What a tagged copy of a book gets (texremediate.tag): pict2e for
        a picture, counted to say so, with picture_paths, and for cancel
        alone without it, LaTeX's own picture mode named first (PICTURE_FONTS);
        nothing for a picture without it."""
        def tagged(text, paths):
            texts = {"b.tex": "\\documentclass{article}\n" + text
                     + "\\begin{document}\n\\begin{picture}(9,9)\\end{picture}\n\\end{document}\n"}
            counts = texremediate.tag(texts, "b.tex", "en", False, ("ua-2",), None, paths)
            return texts["b.tex"], counts
        on, on_counts = tagged("", True)
        off, off_counts = tagged("", False)
        cancel, cancel_counts = tagged("\\usepackage{cancel}\n", False)
        return latexbuild.PICTURE_PATHS in on and latexbuild.PICTURE_FONTS not in on \
            and on_counts.get("picture") == 1 and not on_counts.get("cancel") \
            and latexbuild.PICTURE_PATHS not in off and not off_counts.get("picture") \
            and latexbuild.PICTURE_FONTS + latexbuild.PICTURE_PATHS in cancel \
            and cancel_counts.get("cancel") == 1 and not cancel_counts.get("picture")
    return [
        ("a tagged copy of a book that strikes a term out with cancel has pict2e drawing it, "
         "and the run says so",
         lambda: os.path.exists(copy) and "c__oer_pictiie_names_clist" in read(work, "tagged",
                                                                              "notes.tex")
         and "cancel set to draw with pict2e" in said),
        ("a copy made again from such a copy has it once, and builds, its term struck out a "
         "path and a command of the book's own named as pict2e's \\cbezier its own",
         copy_of_copy),
        ("a book that loads pict2e itself keeps pict2e's \\cbezier, which pict2e makes at "
         "\\begin{document}", own_pict2e),
        ("a book's own \\buttcap and \\maxovalrad are kept, its circles, oval, and dot drawn "
         "by pict2e all the same, the oval reading its \\maxovalrad", own_names),
        ("a document with no cancel loads pict2e, its circle asked for at 80 points a "
         "path, no glyph of lcircle10", lambda: without_cancel(True)),
        ("and with picture_paths off it loads none, LaTeX drawing the circle with "
         "lcircle10's glyphs", lambda: without_cancel(False)),
        ("and with picture_paths off and cancel, pict2e is loaded for the struck-out term, "
         "as before, and draws the picture too", fonts_with_cancel),
        ("a tagged copy of a book gets pict2e for its picture, counted to say so, and with "
         "picture_paths off, only for cancel, LaTeX's own picture mode named first",
         tagged_copies),
        ("and so does a book's tagged copy as the run makes it, which says so, and with the "
         "target's picture_paths off it gets none",
         lambda: drawn.returncode == 0
         and "c__oer_pictiie_names_clist" in read(pictures, "paths", "drawn.tex")
         and "its drawings in picture mode drawn with paths by pict2e" in drawn_said
         and "c__oer_pictiie_names_clist" not in read(pictures, "fonts", "drawn.tex")),
    ]


def case_code_label(work):
    """A book that loads fancyvrb, a list's item opening with its Verbatim,
    whose label LaTeX's tagging sets over the next item's (latexbuild's
    CODE_ITEM_LABEL, as a book's PDF from its pages has it): its tagged
    copy keeps the label beside the code's first line, and the run says
    so; its PDF, built from its own LaTeX, has it there, the next item's
    label alone; a copy made from the copy has the fix once; a book that
    loads fvextra, which loads fancyvrb, gets it, and one that loads
    neither doesn't."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild
    import texremediate
    os.makedirs(work)
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\usepackage{fancyvrb}\n\\begin{document}\n"
                 "\\begin{enumerate}\n\\item Labelfirst.\n\\item\n\\begin{Verbatim}\n"
                 "Labelcode\n\\end{Verbatim}\n\\item Labelthird.\n\\end{enumerate}\n"
                 "\\end{document}\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n"
                 "  pdf:\n    format: pdf\n")
    result = convert(work)
    said = result.stdout + result.stderr
    copy = os.path.join(work, "tagged", "notes.tex")
    hook = "cmd / FV@ListVSpace / before"

    def labels():
        """The PDF's rows that hold the code and the third item, squeezed:
        each item's label its own, the second's beside the code."""
        why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
        if why:
            return skip(why)
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return skip("no pikepdf to read the PDF")
        import pdftext
        path = os.path.join(work, "pdf", "book.pdf")
        if not os.path.exists(path):
            return False
        rows = {}
        for page, baseline, _left, _right, char in pdftext.glyph_boxes(path):
            rows.setdefault((page, round(baseline, 1)), []).append(char)
        texts = ["".join(chars).replace(" ", "") for chars in rows.values()]
        return "2.Labelcode" in texts and "3.Labelthird." in texts \
            and "a list's item's label kept beside the code that opens the item" in said

    def tagged(preamble):
        texts = {"b.tex": "\\documentclass{article}\n" + preamble
                 + "\\begin{document}\nA line.\n\\end{document}\n"}
        counts = texremediate.tag(texts, "b.tex", "en", False, ("ua-2",), None)
        return texts["b.tex"], counts
    again = {"notes.tex": read(work, "tagged", "notes.tex")} if os.path.exists(copy) else {}
    if again:
        texremediate.tag(again, "notes.tex", "en", True, ("ua-2",), None)
    fvextra, fvextra_counts = tagged("\\usepackage{fvextra}\n")
    plain, plain_counts = tagged("\\usepackage{verbatim}\n")
    return [
        ("a tagged copy of a book that loads fancyvrb keeps a list's item's label beside the "
         "code that opens it, and the run says so",
         lambda: os.path.exists(copy) and read(work, "tagged", "notes.tex").count(hook) == 1
         and "fancyvrb's lists told to keep a list's item's label beside the code that opens "
         "the item" in said),
        ("its PDF, built from its own LaTeX, has the item's label beside the code's first "
         "line, and the next item's label alone", labels),
        ("a copy made again from such a copy has it once",
         lambda: again and again["notes.tex"].count(hook) == 1),
        ("a book that loads fvextra, which loads fancyvrb, gets it too, counted, and one "
         "that loads neither doesn't",
         lambda: latexbuild.CODE_ITEM_LABEL in fvextra and fvextra_counts.get("code_label") == 1
         and hook not in plain and not plain_counts.get("code_label")),
    ]


def case_line_breaks(work):
    r"""A book that breaks lines with \\, \newline, \linebreak, and \break,
    which leave no space between their lines in a tagged PDF's text, the
    words on either side run together (NVDA 2026.3 in Acrobat read an
    address's lines as "OpenStaxRice University6100 Main Street"), and
    whose numbered part's, chapter's, and section's headings have line
    breaks of their own: its tagged copy gets latexbuild's
    LINE_BREAK_SPACE, as a book's PDF from its pages has it, and the run
    says so; its PDF, built from its own LaTeX, has a space at each break,
    \hfill\break's and a \linebreak[2] TeX breaks at among them, but none
    inside a word, nor after a hyphen, nor for an empty line or at a
    paragraph's end, and its table's rows as they were; its headings read
    their number, a space, and their lines with a space between them, and
    so do their bookmarks and titles; its short caption is two lines on
    the page, broken at its \\ and centered, one that ends with its \\
    one line, and a term's and an \mbox's \\ a space there, but a box
    unpacked into a paragraph is set as it was; its contents' entries read
    their number, title, and page number a space apart, and its \enspace,
    a kern, is a space, in a heading's title and its bookmark too, as is
    amsbook's in "CHAPTER 1", and a line still breaks at it; built with
    pdfLaTeX, as a DVI or untagged, it's as before; a copy made from the
    copy has it once; a book whose \\ end only a table's rows or a
    formula's lines, or that breaks no line and numbers no chapter,
    doesn't get it, and one that numbers its chapters and breaks no line
    does, as do one that sets a list of contents, but not memoir's, and
    one that writes an \enspace in text; a book whose own
    preamble defines \@gnewline and \@no@lnbk keeps its own, and its lines
    get their space; and ragged2e's \justifying keeps the space."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild
    import texremediate
    os.makedirs(work)
    with open(os.path.join(work, "notes.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{book}\n\\begin{document}\n\\tableofcontents\n"
                 "\\part{Partone}\n\\chapter{Alphaone\\\\Alphatwo}\n"
                 "\\section{Gammaone\\\\\nGammatwo}\n"
                 "OpenStax\\\\Rice University\\\\6100 Main Street\n\n"
                 "Breakfirst \\newline breaksecond, and justified words before "
                 "\\linebreak after it, words kept \\nolinebreak together, a self-\\linebreak "
                 "contained word, the rest of the paragraph running on to fill another line "
                 "of text here.\n\n"
                 "Breakthird\\break breakfourth, breakfifth\\hfill\\break breaksixth, "
                 "wordfirst\\linebreak wordsecond, self-\\\\contained, co\u2010\\\\operate, "
                 "anti\\discretionary{-}{}{-}\\\\inflammatory, "
                 "and an empty line\\\\\n\\strut\\\\\nafter it.\\\\\n\n"
                 "\\parbox{10cm}{\\raggedright Ragone ragtwo ragthree \\linebreak[2] ragfour "
                 "ragfive.}\n\n"
                 "\\begin{center}\nCenterone\\\\Centertwo\n\\end{center}\n\n"
                 "\\parbox{3cm}{Aformula $aaaa + bbbb + cccc + dddd + eeee + ffff$ here.}\n\n"
                 "\\mbox{\\hspace{1cm}}\\\\Boxafter\n\n"
                 "\\mbox{Mboxone\\\\Mboxtwo} and Paris -\\\\London.\n\n"
                 "\\mbox{Tildeone\\\\~Tildetwo}\n\n"
                 "Enone\\enspace Entwo, an en space.\n\n"
                 "\\begin{description}\n\\item[Termone\\\\Termtwo] Definition.\n"
                 "\\end{description}\n\n"
                 "\\begin{figure}\n\\centering\n\\rule{1cm}{1cm}\n\\caption{Capone\\\\Captwo}\n"
                 "\\end{figure}\n\n"
                 "\\begin{figure}\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Nestone \\mbox{Nestbox\\\\Nestboxtwo}\\\\Nesttwo}\n\\end{figure}\n\n"
                 "\\begin{figure}\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Longone longer words that run on past the width of a line, so "
                 "that LaTeX sets the caption as a paragraph of its own\\\\Longtwo}\n"
                 "\\end{figure}\n\n"
                 "\\makebox[6cm][l]{Fillone\\hfill\\break Filltwo}\n\n"
                 "A formula with an en space, $a\\enspace b$.\n\n"
                 "\\newlength\\Enwidth\\settowidth\\Enwidth{Enpre Ensplitone\\enspace}"
                 "\\parbox{\\Enwidth}{\\raggedright Enpre Ensplitone\\enspace{} Ensplittwo}\n\n"
                 "Unboxlead \\setbox0\\hbox{Unboxone unboxtwo\\\\Unboxthree}\\unhbox0\\ "
                 "unboxtail.\n\n"
                 "\\begin{tabular}{ll}\nCellone & Celltwo\\\\\nCellthree & Cellfour\\\\\n"
                 "\\end{tabular}\n\n\\section{Ensec\\enspace Entitle}\nEnsection words.\n\n"
                 "\\chapter{Self-\\\\contained}\nAfter the hyphen.\n\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n\\caption{Trailone\\\\}\n"
                 "Belowtrail\n\\end{figure}\n\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n\\caption{Plainone}\n"
                 "Belowplain\n\\end{figure}\n\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Longer words that run on past the width of a line, so that LaTeX "
                 "sets the caption as a paragraph, trailend\\\\}\nBelowlongtrail\n"
                 "\\end{figure}\n\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Longer words that run on past the width of a line, so that LaTeX "
                 "sets the caption as a paragraph, plainend}\nBelowlongplain\n\\end{figure}\n\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Noteone\\protect\\footnotemark}\n\\end{figure}\n"
                 "\\footnotetext{Notetexta.}\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Notecap\\\\Notetwo\\protect\\footnotemark}\n\\end{figure}\n"
                 "\\footnotetext{Notetextb.}\n"
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption{Notethree\\protect\\footnotemark}\n\\end{figure}\n"
                 "\\footnotetext{Notetextc.}Afternote words.\n\n"
                 # A caption with two marks, a \\settowidth between them, which
                 # resumes tagging under its own label, \\@settodim.
                 "\\begin{figure}[h]\n\\centering\n\\rule{1cm}{1cm}\n"
                 "\\caption[Notefour]{Notefour\\protect\\footnotemark{} \\protect\\settowidth"
                 "{\\dimen0}{x}Notefive\\protect\\footnotemark}\n\\end{figure}\n"
                 "\\addtocounter{footnote}{-1}\\footnotetext{Notetextd.}"
                 "\\stepcounter{footnote}\\footnotetext{Notetexte.}\n\n"
                 "\\parbox{1cm}{\\hyphenpenalty=10000 Ennoone\\enspace Ennotwo}\n"
                 "\\end{document}\n")
    own = work + "-own"
    os.makedirs(own)
    # A \@gnewline of the book's own, which puts a slash before the break,
    # and a \@no@lnbk, \linebreak's, which puts a bar there.
    with open(os.path.join(own, "own.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n\\makeatletter\n"
                 "\\def\\@gnewline#1{\\ifvmode\\@nolnerr\\else\\unskip\\ /\\nobreak\\hfil"
                 "\\break\\fi}\n"
                 "\\def\\@no@lnbk#1[#2]{\\ifvmode\\@nolnerr\\else\\unskip\\ |"
                 "\\penalty#1\\@getpen{#2}\\fi}\n\\makeatother\n"
                 "\\DeclareRobustCommand\\enspace{\\kern.5em/}\n\\begin{document}\n"
                 "Ownfirst\\\\Ownsecond\n\nOwnthird \\linebreak Ownfourth\n\n"
                 "Enown\\enspace Entwoown.\n\\end{document}\n")
    config = ("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n"
              "  pdf:\n    format: pdf\n")
    for folder in (work, own):
        with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
            fh.write(config)
    result = convert(work)
    said = result.stdout + result.stderr
    convert(own)
    copy = os.path.join(work, "tagged", "notes.tex")
    pdf_path = os.path.join(work, "pdf", "book.pdf")

    def why_not():
        """A reason to skip reading the PDF, or None."""
        why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
        if why:
            return why
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return "no pikepdf to read the PDF"
        return None

    def pdf_said(*messages):
        """Whether the PDF target's run said each of messages, where TeX
        could build its PDF; where it couldn't, the run built none and said
        nothing of it, which a check's other parts don't wait on."""
        if why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk"):
            return True
        return all(message in said for message in messages)

    def contents_said():
        """The contents' entries apart, and the runs saying so."""
        got = contents()
        if got is not True:
            return got
        return "its lists of contents, figures, or tables told to leave a space between an " \
            "entry's number, its title, and its page number" in said \
            and pdf_said("a space between a contents entry's number, its title, and its page "
                         "number in the text a screen reader gets")

    def texts(folder, name="book.pdf"):
        """The PDF's text, each marked content sequence's, or a reason to
        skip."""
        why = why_not()
        if why:
            return skip(why)
        import pdftext
        path = os.path.join(folder, "pdf", name) if os.path.isdir(os.path.join(folder, "pdf")) \
            else os.path.join(folder, name)
        return list(pdftext.marked_text(path).values()) if os.path.exists(path) else []

    def spaced():
        found = texts(work)
        if not isinstance(found, list):
            return found
        return ("OpenStax Rice University 6100 Main Street" in found
                and any("Breakfirst breaksecond," in t and "before after it" in t
                        and "words kept together," in t and "a self-contained word" in t
                        for t in found)
                and all(c in found for c in ("Cellone", "Celltwo", "Cellthree", "Cellfour")))

    def broken():
        """The paragraphs' text, each one's sequences together: the strut
        of the empty line, an artifact, ends one."""
        why = why_not()
        if why:
            return skip(why)
        import pdftext
        found = pdftext.element_texts(pdf_path, "/text") if os.path.exists(pdf_path) else []
        return ("Breakthird breakfourth, breakfifth breaksixth, wordfirst wordsecond, "
                "self-contained, co\u2010operate, anti-inflammatory, and an empty line after it."
                in found
                and "Ragone ragtwo ragthree ragfour ragfive." in found
                and "Centerone" in found and "Centertwo" in found and "Boxafter" in found
                and "Mboxone Mboxtwo and Paris - London." in found and "Capone Captwo" in found
                and "Tildeone Tildetwo" in found
                and "Unboxlead Unboxone unboxtwo Unboxthree unboxtail." in found
                and "Termone Termtwo" in pdftext.element_texts(pdf_path, "/itemlabel"))

    formulas = []

    def headings():
        r"""(Each heading's kind and text, its Spans' together, the
        bookmarks' titles, and the headings' /T), or a reason to skip;
        each formula's text in formulas."""
        why = why_not()
        if why:
            return skip(why)
        import pikepdf
        import pdftext
        if not os.path.exists(pdf_path):
            return [], [], []
        marked = pdftext.marked_text(pdf_path)
        found, titles, marks = [], [], []
        del formulas[:]
        with pikepdf.open(pdf_path) as pdf:
            pages = {page.objgen: n for n, page in enumerate(pdf.pages)}

            def text_of(element):
                """An element's text, its own and its descendants', in
                order."""
                kids = element.get("/K")
                kids = list(kids) if isinstance(kids, pikepdf.Array) else [kids]
                page, text = element.get("/Pg"), ""
                for kid in kids:
                    if isinstance(kid, pikepdf.Dictionary) and "/S" in kid:
                        text += text_of(kid)
                    elif isinstance(kid, pikepdf.Dictionary) and "/MCID" in kid:
                        where = kid.get("/Pg") or page
                        text += marked.get((pages[where.objgen], int(kid.MCID)), "")
                    elif isinstance(kid, int) and page is not None:
                        text += marked.get((pages[page.objgen], kid), "")
                return text

            def walk(element):
                if isinstance(element, pikepdf.Array):
                    for kid in element:
                        walk(kid)
                elif isinstance(element, pikepdf.Dictionary) and "/S" in element:
                    if str(element.S) in ("/part", "/chapter", "/section"):
                        found.append((str(element.S), text_of(element)))
                        titles.append(str(element.get("/T", "")))
                    elif str(element.S) == "/TOCI":
                        found.append(("/TOCI", text_of(element)))
                    elif str(element.S) == "/Formula":
                        formulas.append(text_of(element))
                    if element.get("/K") is not None:
                        walk(element.K)
            walk(pdf.Root.StructTreeRoot.K)
            item = pdf.Root.get("/Outlines", {}).get("/First") \
                if "/Outlines" in pdf.Root else None
            stack = [item] if item is not None else []
            while stack:
                item = stack.pop()
                while item is not None:
                    marks.append(str(item.get("/Title", "")))
                    if item.get("/First") is not None:
                        stack.append(item.First)
                    item = item.get("/Next")
        return found, marks, titles

    def formula():
        """The formula a narrow box breaks across lines, its text as it
        reads, with no space in it."""
        got = headings()
        if not isinstance(got, tuple):
            return got
        return formulas and all(" " not in text for text in formulas) \
            and any(text.count("+") == 5 for text in formulas)

    def headed():
        got = headings()
        if not isinstance(got, tuple):
            return got
        found, marks, titles = got
        return (("/part", "Part I Partone") in found
                and ("/chapter", "Chapter 1 Alphaone Alphatwo") in found
                and ("/section", "1.1 Gammaone Gammatwo") in found
                and ("/chapter", "Chapter 2 Self-contained") in found
                and "Alphaone Alphatwo" in marks and "Gammaone Gammatwo" in marks
                and "Alphaone Alphatwo" in titles and "Gammaone Gammatwo" in titles)

    def contents():
        """Each contents entry's text, its number's, its title's, and its
        page number's together: a space between each."""
        got = headings()
        if not isinstance(got, tuple):
            return got
        entries = [text for kind, text in got[0] if kind == "/TOCI"]
        return any(re.fullmatch(r"1 Alphaone Alphatwo \d+", t) for t in entries) \
            and any(re.fullmatch(r"1\.1 Gammaone Gammatwo \d+", t) for t in entries)

    def seen():
        r"""On the page: the short caption's two lines, broken where its \\
        is, each centered on the other, and a space's width between the
        words of a list's term and of an \mbox that a \\ joins, which a
        box can't break, an \mbox's in a caption broken so among them; a
        long caption's line after its \\ where its first line starts, at
        the margin, as LaTeX sets a caption longer than a line; a caption
        that ends with its \\ one line, centered as one with none is, no
        empty line under it, nor under a long one; an \hfill\break in a
        box set to a width, its fill the box's room, as it was; a box
        unpacked into a paragraph, its line's words their own width apart,
        where its \\ ends the line; a note's mark in a caption, with a \\
        or without, numbered once, the chapter's first three 1, 2, and 3,
        where LaTeX's tagging, which sets a caption twice, gave 2, 4, and 6,
        and a caption's two, a \settowidth between them, 4 and 5;
        and a line still broken at an \enspace a space follows, and not
        before one."""
        why = why_not()
        if why:
            return skip(why)
        import pdftext
        if not os.path.exists(pdf_path):
            return False
        rows = {}
        for page, baseline, left, right, char in pdftext.glyph_boxes(pdf_path):
            if char.strip():
                rows.setdefault((page, round(baseline, 1)), []).append((left, right, char))
        lines = {key: ("".join(g[2] for g in glyphs), glyphs) for key, glyphs in rows.items()}

        def line(words):
            return next(((key, glyphs) for key, (text, glyphs) in lines.items()
                         if words in text), (None, None))

        def gap(before, after):
            for text, glyphs in lines.values():
                at = text.find(before + after)
                if at >= 0:
                    end = at + len(before)
                    return glyphs[end][0] - glyphs[end - 1][1]
            return None

        def center(glyphs):
            return (glyphs[0][0] + glyphs[-1][1]) / 2

        def mark(words):
            """The number a note's mark sets before the note's words."""
            key, glyphs = line(words)
            if key is None:
                return None
            digits = sorted((left, char) for (page, base), row in rows.items()
                            if page == key[0] and 0 < base - key[1] < 6
                            for left, right, char in row
                            if char.isdigit() and right <= glyphs[0][0] + 0.5)
            return int("".join(char for _, char in digits)) if digits else None

        first, one = line("Capone")
        second, two = line("Captwo")
        trail, trailed = line("Trailone")
        plain, plained = line("Plainone")
        below_trail, below_plain = line("Belowtrail")[0], line("Belowplain")[0]
        long_trail, long_plain = line("trailend")[0], line("plainend")[0]
        below_long_trail, below_long_plain = line("Belowlongtrail")[0], line("Belowlongplain")[0]
        split = next((text for text, _ in lines.values() if "Ensplitone" in text), "")
        tight = next((text for text, _ in lines.values() if "Ennoone" in text), "")
        a, b, c = mark("Notetexta."), mark("Notetextb."), mark("Notetextc.")
        d, e = mark("Notetextd."), mark("Notetexte.")
        nest, nested = line("Nestone"), line("Nesttwo")
        _, margin = line("Longone")
        _, last = line("Longtwo")
        return first is not None and second is not None and first != second \
            and first[0] == second[0] and first[1] > second[1] \
            and abs((one[0][0] + one[-1][1]) / 2 - (two[0][0] + two[-1][1]) / 2) < 1 \
            and 2 < (gap("Termone", "Termtwo") or 0) < 6 \
            and 2 < (gap("Mboxone", "Mboxtwo") or 0) < 6 \
            and nest[0] is not None and nested[0] is not None and nest[0] != nested[0] \
            and 2 < (gap("Nestbox", "Nestboxtwo") or 0) < 6 \
            and margin is not None and last is not None and abs(last[0][0] - margin[0][0]) < 1 \
            and trail is not None and plain is not None and below_trail is not None \
            and below_plain is not None \
            and trail[0] == below_trail[0] and plain[0] == below_plain[0] \
            and abs(center(trailed) - center(plained)) < 1 \
            and abs((trail[1] - below_trail[1]) - (plain[1] - below_plain[1])) < 0.5 \
            and None not in (long_trail, long_plain, below_long_trail, below_long_plain) \
            and long_trail[0] == below_long_trail[0] and long_plain[0] == below_long_plain[0] \
            and abs((long_trail[1] - below_long_trail[1])
                    - (long_plain[1] - below_long_plain[1])) < 0.5 \
            and (a, b, c, d, e) == (1, 2, 3, 4, 5) \
            and "EnnooneEnnotwo" in tight \
            and (gap("Fillone", "Filltwo") or 0) > 20 \
            and 2 < (gap("Unboxone", "unboxtwo") or 0) < 6 \
            and "EnpreEnsplitone" in split and "Ensplittwo" not in split

    def en_spaced():
        r"""An \enspace in text is a space in its text, and in a heading's
        title, a space in the heading's text, its contents entry's, its
        bookmark, and its /T."""
        found = texts(work)
        if not isinstance(found, list):
            return found
        got = headings()
        if not isinstance(got, tuple):
            return got
        entries, marks, titles = got
        return any("Enone Entwo, an en space." in t for t in found) \
            and ("/section", "1.2 Ensec Entitle") in entries \
            and any(kind == "/TOCI" and re.fullmatch(r"1\.2 Ensec Entitle \d+", text)
                    for kind, text in entries) \
            and "Ensec Entitle" in marks and "Ensec Entitle" in titles \
            and "its \\enspace a space in the text a screen reader gets" in said \
            and pdf_said("a space for each \\enspace in the text a screen reader gets")

    def ams():
        r"""A tagged document of amsbook's, the space, and an \enspace:
        its chapter heading's number, which amsbook sets after the word
        with an \enspace, a kern, reads "CHAPTER 1", and the text's
        \enspace is a space too; and its contents and list of figures
        start their pages as amsbook starts them, the list of figures on a
        right-hand page, 3, with LaTeX stopping on nothing, where LaTeX's
        tagging made each a numbered chapter,
        "CHAPTER 1" with "sec/title/end" under it, and the book's chapter
        "CHAPTER 3"."""
        why = why_no_tex("no lualatex to build the amsbook document", "lualatex")
        if why:
            return skip(why)
        if not subprocess.run(["kpsewhich", "amsbook.cls"], capture_output=True,
                              text=True).stdout.strip():
            return skip("no amsbook here")
        folder = os.path.join(work, "amsbook")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "ams.tex"), "w", encoding="utf-8") as fh:
            fh.write("\\DocumentMetadata{tagging=on,pdfstandard=ua-2,lang=en-US}\n"
                     "\\documentclass{amsbook}\n" + latexbuild.LINE_BREAK_SPACE
                     + "\\begin{document}\n\\tableofcontents\n\\listoffigures\n"
                     "\\chapter{Introduction}\nAmsone\\enspace Amstwo.\n"
                     "\\begin{figure}\\centering\\rule{1cm}{1cm}\\caption{Amsfigure}"
                     "\\end{figure}\n\\end{document}\n")
        for _ in range(2):
            built = subprocess.run(["lualatex", "-interaction=nonstopmode", "ams.tex"],
                                   cwd=folder, capture_output=True, text=True, timeout=300)
        found = texts(folder, "ams.pdf")
        if not isinstance(found, list):
            return found
        return any("CHAPTER 1" in t for t in found) and any("Amsone Amstwo." in t for t in found) \
            and not any(re.search(r"CHAPTER [23]|sec/title/end", t) for t in found) \
            and any(t.strip() == "Contents" for t in found) \
            and any(t.strip() == "List of Figures" for t in found) \
            and any(re.fullmatch(r"List of Figures\s*3", t.strip()) for t in found) \
            and not re.search(r"^! ", built.stdout, re.M)

    def kept():
        found = texts(own)
        if not isinstance(found, list):
            return found
        return any(t.startswith("Ownfirst / Ownsecond") for t in found) \
            and any(t.startswith("Ownthird | Ownfourth") for t in found) \
            and any("Enown/Entwoown." in t for t in found)

    def pdftex_as_before():
        r"""The tagged copy built as a DVI with pdfTeX, and with pdfLaTeX
        and LuaLaTeX without its \DocumentMetadata, untagged: each builds,
        and pdfLaTeX's PDF has no font of pdfTeX's for spaces."""
        why = why_no_tex("no latex, pdflatex, or lualatex to build the copy untagged", "latex",
                         "pdflatex", "lualatex")
        if why:
            return skip(why)
        if not os.path.exists(copy):
            return False
        text = read(work, "tagged", "notes.tex")
        folder = os.path.join(work, "pdftex")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "dvi.tex"), "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(folder, "untagged.tex"), "w", encoding="utf-8") as fh:
            fh.write(re.sub(r"\\DocumentMetadata\{[^}]*\}\n", "", text))
        dvi = subprocess.run(["latex", "-interaction=nonstopmode", "dvi.tex"], cwd=folder,
                             capture_output=True, text=True, timeout=120)
        pdf = subprocess.run(["pdflatex", "-interaction=nonstopmode", "untagged.tex"],
                             cwd=folder, capture_output=True, text=True, timeout=120)
        shutil.copy(os.path.join(folder, "untagged.tex"), os.path.join(folder, "lua.tex"))
        lua = subprocess.run(["lualatex", "-interaction=nonstopmode", "lua.tex"],
                             cwd=folder, capture_output=True, text=True, timeout=300)
        if dvi.returncode or pdf.returncode or lua.returncode or not os.path.exists(
                os.path.join(folder, "dvi.dvi")) or not os.path.exists(
                os.path.join(folder, "lua.pdf")):
            return False
        with open(os.path.join(folder, "untagged.pdf"), "rb") as fh:
            return b"PdfTeX-Space" not in fh.read()

    def justified():
        r"""A tagged document with the space, ragged2e, and \justifying:
        its line break's space after \justifying as before it."""
        why = why_no_tex("no lualatex to build the ragged2e document", "lualatex")
        if why:
            return skip(why)
        if not subprocess.run(["kpsewhich", "ragged2e.sty"], capture_output=True,
                              text=True).stdout.strip():
            return skip("no ragged2e here")
        folder = os.path.join(work, "ragged2e")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "r2e.tex"), "w", encoding="utf-8") as fh:
            fh.write("\\DocumentMetadata{tagging=on,pdfstandard=ua-2,lang=en-US}\n"
                     "\\documentclass{article}\n\\usepackage{ragged2e}\n"
                     + latexbuild.LINE_BREAK_SPACE + "\\begin{document}\n"
                     "Beforejust\\\\Beforenext\n\n\\justifying\nAfterjust\\\\Afternext\n"
                     "\\end{document}\n")
        subprocess.run(["lualatex", "-interaction=nonstopmode", "r2e.tex"], cwd=folder,
                       capture_output=True, text=True, timeout=300)
        found = texts(folder, "r2e.pdf")
        if not isinstance(found, list):
            return found
        return "Beforejust Beforenext" in found and "Afterjust Afternext" in found

    def tagged(body, cls="article"):
        texts = {"b.tex": "\\documentclass{" + cls + "}\n\\begin{document}\n" + body
                 + "\n\\end{document}\n"}
        counts = texremediate.tag(texts, "b.tex", "en", False, ("ua-2",), None)
        return texts["b.tex"], counts
    again = {"notes.tex": read(work, "tagged", "notes.tex")} if os.path.exists(copy) else {}
    if again:
        texremediate.tag(again, "notes.tex", "en", True, ("ua-2",), None)
    plain, plain_counts = tagged("A paragraph, one line.")
    rows, rows_counts = tagged("\\begin{tabular}{ll}\na & b\\\\\nc & d\\\\\n\\end{tabular}\n\n"
                               "\\begin{align}\nx &= 1\\\\\ny &= 2\n\\end{align}\n\n"
                               "A formula, $\\substack{a\\\\b}$.")
    chapters, chapter_counts = tagged("\\chapter{Introduction}\nA paragraph.\n\n"
                                      "\\chapter*{Unnumbered}\n", "report")
    broke, broke_counts = tagged("Breakone\\break breaktwo.")
    starred, starred_counts = tagged("\\chapter*{Preface}\nA paragraph.\n", "report")
    paged, paged_counts = tagged("One.\n\n\\vfill\\break\n\nTwo.")
    defined, defined_counts = tagged("\\renewcommand\\chapter{\\par}\nA paragraph.", "book")
    memoir, memoir_counts = tagged("\\chapter{Introduction}\nA paragraph.", "memoir")
    listed, listed_counts = tagged("\\tableofcontents\n\\section{One}\nA paragraph.")
    memoir_listed, memoir_listed_counts = tagged("\\tableofcontents\n\\section*{One}\n", "memoir")
    # Captions holding a note's mark: a short caption with brackets inside
    # braces, a \captionof, a \footnote, a \captionbox, and one with a brace
    # in a comment inside it; not a caption without one, one whose mark is
    # in a comment, nor \caption's own definition.
    noted, noted_counts = tagged(
        "\\begin{figure}\\caption[{Short [a]}]{Long\\protect\\footnotemark}\\end{figure}\n"
        "\\footnotetext{N.}\n\\captionof{figure}{Of\\protect\\footnotemark}\n"
        "\\begin{table}\\caption*{Star\\footnote{Note.}}\\end{table}\n"
        "\\begin{figure}\\captionbox{Box\\protect\\footnotemark}{\\rule{1cm}{1cm}}"
        "\\end{figure}\n"
        "\\begin{figure}\\caption{Brace % a } in a comment\nthen\\protect\\footnotemark}"
        "\\end{figure}\n")
    unnoted, unnoted_counts = tagged(
        "\\renewcommand\\caption[1]{#1\\footnotemark}\n"
        "\\begin{figure}\\caption{No note}\\end{figure}\nA \\footnotemark{} in text.\n"
        "\\begin{figure}\\caption{Commented % \\footnotemark\n}\\end{figure}\n")
    ams_listed, ams_listed_counts = tagged("\\tableofcontents\n\\chapter*{One}\n", "amsbook")
    art_listed, art_listed_counts = tagged("\\tableofcontents\n\\section{One}\n", "amsart")
    koma_listed, koma_listed_counts = tagged("\\listoffigures\n\\section*{One}\n", "scrartcl")
    spaced_en, en_counts = tagged("Before\\enspace after.")
    math_en, math_en_counts = tagged("A formula, $a\\enspace b$.")
    defined_en, defined_en_counts = tagged("\\renewcommand\\enspace{\\kern.5em}\nA paragraph.")
    return [
        ("a tagged copy of a book that breaks lines and numbers its chapters gets the space "
         "at a line break and in a heading, and the run says so",
         lambda: os.path.exists(copy)
         and read(work, "tagged", "notes.tex").count(latexbuild.LINE_BREAK_SPACE) == 1
         and "its line breaks (\\\\, \\newline, \\linebreak, and \\break) told to leave a "
             "space between their lines" in said
         and "its parts' and chapters' headings told to leave a space between a heading's "
             "number and its title" in said
         and pdf_said("a space between a line break's two lines in the text a screen reader "
                      "gets", "a space between a part's or a chapter's number and its title in "
                      "the text a screen reader gets")),
        ("its PDF, built from its own LaTeX, has a space between the lines of each \\\\, "
         "\\newline, and \\linebreak in its text, none inside a word a \\linebreak breaks, "
         "one space where \\nolinebreak keeps two words together, and a table's rows as "
         "they were", spaced),
        ("and at \\break, \\hfill\\break, a \\linebreak with no space before it, a "
         "\\linebreak[2] TeX breaks at, and a dash with spaces, and in a box, a short caption, "
         "and a list's term, but none after a hyphen, nor for an empty line, nor at a "
         "paragraph's end, nor after a box with no text", broken),
        ("a center environment's lines as they were, and none in a formula TeX breaks after "
         "an operator", formula),
        ("on the page, a caption short enough for one line but for its \\\\ set as two "
         "lines, broken there and centered, as the caption package sets one, one ending with "
         "its \\\\ one line, and a list's term's and an \\mbox's \\\\, which a box can't "
         "break, a space; a box unpacked into a paragraph and a line an \\enspace ends as "
         "they were; and a note's mark in a caption numbered once, 1, 2, 3, where LaTeX's "
         "tagging gave 2, 4, 6, and a caption's two, a \\settowidth between them, 4 and 5",
         seen),
        ("the run says how many captions hold a note's mark, in the copy and the PDF",
         lambda: "4 caption(s) holding a note's mark told to give it one number" in said
         and pdf_said("one number for a note's mark in a caption")),
        ("its contents' entries read their number, a space, their title, a space, and their "
         "page number, and the run says so", contents_said),
        ("its \\enspace is a space in its text, and the run says so", en_spaced),
        ("and amsbook's \\enspace after the word in its chapter's heading, \"CHAPTER 1\", its "
         "contents and list of figures starting their pages as amsbook starts them, where "
         "LaTeX's tagging made each a numbered chapter", ams),
        ("its part's, chapter's, and section's headings read their number, a space, and "
         "their lines with a space between them, but none after a hyphen, and so do their "
         "bookmarks and structure titles", headed),
        ("built with pdfTeX, as a DVI or untagged without its \\DocumentMetadata, it builds, "
         "with no font of pdfTeX's for spaces, and untagged with LuaLaTeX too",
         pdftex_as_before),
        ("a copy made again from such a copy has it once",
         lambda: again and again["notes.tex"].count(latexbuild.LINE_BREAK_SPACE) == 1),
        ("a book that breaks no line and numbers no chapter doesn't get it, nor one whose \\\\ "
         "end only a table's rows and a formula's lines, nor one whose only chapter is "
         "unnumbered, nor one that breaks a page with \\vfill\\break, defines \\chapter, or "
         "numbers a memoir chapter; one that numbers a chapter and breaks no line does, for "
         "its headings, and so does one whose only break is \\break",
         lambda: latexbuild.LINE_BREAK_SPACE not in plain
         and not plain_counts.get("line_breaks") and not plain_counts.get("heading_lines")
         and latexbuild.LINE_BREAK_SPACE not in rows and not rows_counts.get("line_breaks")
         and latexbuild.LINE_BREAK_SPACE not in starred
         and not starred_counts.get("heading_lines")
         and latexbuild.LINE_BREAK_SPACE not in paged and not paged_counts.get("line_breaks")
         and latexbuild.LINE_BREAK_SPACE not in defined
         and latexbuild.LINE_BREAK_SPACE not in memoir
         and not memoir_counts.get("heading_lines")
         and chapters.count(latexbuild.LINE_BREAK_SPACE) == 1
         and chapter_counts.get("heading_lines") == 1
         and not chapter_counts.get("line_breaks")
         and broke.count(latexbuild.LINE_BREAK_SPACE) == 1
         and broke_counts.get("line_breaks") == 1),
        ("one that sets a list of contents gets it, for the entries, and one that writes an "
         "\\enspace, a kern, for its space, each counted; not a memoir book's contents, which "
         "LaTeX's tagging doesn't set, nor an \\enspace only in a formula or defined",
         lambda: listed.count(latexbuild.LINE_BREAK_SPACE) == 1
         and listed_counts.get("contents_spaces") == 1 and not listed_counts.get("line_breaks")
         and spaced_en.count(latexbuild.LINE_BREAK_SPACE) == 1
         and en_counts.get("en_spaces") == 1 and not en_counts.get("contents_spaces")
         and not plain_counts.get("contents_spaces") and not plain_counts.get("en_spaces")
         and latexbuild.LINE_BREAK_SPACE not in memoir_listed
         and not memoir_listed_counts.get("contents_spaces")
         and latexbuild.LINE_BREAK_SPACE not in math_en and not math_en_counts.get("en_spaces")
         and latexbuild.LINE_BREAK_SPACE not in defined_en
         and not defined_en_counts.get("en_spaces")),
        ("one whose captions hold a note's mark gets it, each such caption counted, a short "
         "caption with brackets, a \\captionof, a \\footnote, a \\captionbox, and one with a "
         "brace in a comment among them; not one whose caption holds none, or only in a "
         "comment, a note in its text and \\caption's own definition aside",
         lambda: noted.count(latexbuild.LINE_BREAK_SPACE) == 1
         and noted_counts.get("caption_notes") == 5
         and latexbuild.LINE_BREAK_SPACE not in unnoted
         and not unnoted_counts.get("caption_notes")),
        ("an amsbook book that sets a list gets it, for the list's start, and an amsart one "
         "for the list's heading, each counted for the run's warning, as a memoir and a "
         "KOMA-Script one are; a book class's isn't",
         lambda: ams_listed.count(latexbuild.LINE_BREAK_SPACE) == 1
         and ams_listed_counts.get("list_chapters") == 1
         and not ams_listed_counts.get("list_headings")
         and ams_listed_counts.get("own_contents") == "amsbook"
         and art_listed.count(latexbuild.LINE_BREAK_SPACE) == 1
         and art_listed_counts.get("list_headings") == 1
         and not art_listed_counts.get("list_chapters")
         and art_listed_counts.get("own_contents") == "amsart"
         and memoir_listed_counts.get("own_contents") == "memoir"
         and not memoir_listed_counts.get("list_chapters")
         and koma_listed_counts.get("own_contents") == "scrartcl"
         and not listed_counts.get("own_contents") and not listed_counts.get("list_chapters")),
        ("a book whose preamble defines \\@gnewline and \\@no@lnbk itself keeps its own, and "
         "its lines get their space", kept),
        ("ragged2e's \\justifying keeps the line break's space", justified),
    ]



def case_class_contents(work):
    """A book in a class that sets its lists with code of its own, which
    LaTeX's tagging reaches only in part: an amsbook book with a contents
    and a list of figures, whose tagged copy and PDF start each list as
    amsbook starts it, its chapter numbered 1 with no list a chapter; an
    amsart article with them, whose PDF builds, each list headed as an
    unnumbered section, its own section numbered 1, where LaTeX stopped on
    the class's own headings;
    the runs saying so, and warning of what's still wrong; and a memoir
    book's copy, warned of too."""
    ams, art, memoir = (os.path.join(work, name) for name in ("amsbook", "amsart", "memoir"))
    for folder, cls, extra, unit in ((ams, "amsbook", "\\listoffigures\n", "chapter"),
                                     (art, "amsart", "\\listoffigures\n", "section"),
                                     (memoir, "memoir", "", "chapter")):
        os.makedirs(folder)
        with open(os.path.join(folder, "book.tex"), "w", encoding="utf-8") as fh:
            fh.write("\\documentclass{" + cls + "}\n\\title{Classed}\n\\begin{document}\n"
                     + ("\\maketitle\n" if folder == art else "")
                     + "\\tableofcontents\n" + extra + "\\" + unit + "{Classone}\nClasstext.\n"
                     "\\begin{figure}\\centering\\rule{1cm}{1cm}\\caption{Classfigure}"
                     "\\end{figure}\n\\end{document}\n")
        with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n"
                     + ("" if folder == memoir else "  pdf:\n    format: pdf\n"))
    ams_done, art_done, memoir_done = convert(ams), convert(art), convert(memoir)
    ams_said = ams_done.stdout + ams_done.stderr
    art_said = art_done.stdout + art_done.stderr
    memoir_said = memoir_done.stdout + memoir_done.stderr
    warning = "a list of contents, figures, or tables in %s is set by %s's own code"

    def pages(folder):
        """The book's PDF's text, a reason to skip, or False with none."""
        why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
        if why:
            return skip(why)
        path = os.path.join(folder, "pdf", "book.pdf")
        if not os.path.exists(path):
            return False
        if not shutil.which("pdftotext"):
            return skip("no pdftotext to read the PDF")
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True,
                              text=True).stdout

    def ams_pdf():
        text = pages(ams)
        if not isinstance(text, str):
            return text
        return "CHAPTER 1" in text and "Classone" in text and "Contents" in text \
            and "List of Figures" in text \
            and not re.search(r"CHAPTER [23]|sec/title/end", text) \
            and "amsbook's lists of contents, figures, and tables starting their pages as " \
            "amsbook starts them" in ams_said \
            and "WARNING: pdf: " + warning % ("the copy LaTeX builds", "amsbook") in ams_said

    def art_untagged():
        """Untagged, an amsart article keeps the class's own headings for its
        lists, which put nothing in its contents: an unnumbered section in
        amsart does, its own contents among them."""
        why = why_no_tex("no lualatex to build the article", "lualatex")
        if why:
            return skip(why)
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import latexbuild
        folder = os.path.join(work, "amsart-untagged")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "art.tex"), "w", encoding="utf-8") as fh:
            fh.write("\\documentclass{amsart}\n" + latexbuild.LINE_BREAK_SPACE
                     + "\\begin{document}\n\\tableofcontents\n\\listoffigures\n"
                     "\\section{Artone}\nText.\n\\begin{figure}\\caption{Artfigure}"
                     "\\end{figure}\n\\end{document}\n")
        subprocess.run(["lualatex", "-interaction=nonstopmode", "art.tex"], cwd=folder,
                       capture_output=True, text=True, timeout=300)
        if not os.path.exists(os.path.join(folder, "art.toc")):
            return False
        toc = read(folder, "art.toc")
        return "Artone" in toc and "Contents" not in toc and toc.count("List of Figures") == 1

    def loaded_classes():
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import texremediate
        folder = os.path.join(work, "own-class")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "mybook.cls"), "w", encoding="utf-8") as fh:
            fh.write("\\NeedsTeXFormat{LaTeX2e}\n\\ProvidesClass{mybook}\n"
                     "\\LoadClass[12pt]{amsbook}\n")
        with open(os.path.join(folder, "ourbook.cls"), "w", encoding="utf-8") as fh:
            fh.write("\\ProvidesClass{ourbook}\n% \\LoadClass{book}\n"
                     "\\LoadClassWithOptions{mybook}\n")
        with open(os.path.join(folder, "plainer.cls"), "w", encoding="utf-8") as fh:
            fh.write("\\ProvidesClass{plainer}\n\\LoadClass{book}\n")
        found = {}
        for cls in ("ourbook", "plainer"):
            texts = {"book.tex": "\\documentclass{%s}\n\\begin{document}\n\\tableofcontents\n"
                                 "\\chapter*{One}\n\\end{document}\n" % cls}
            counts = texremediate.tag(texts, "book.tex", "en", False, ("ua-2",), folder)
            found[cls] = (counts.get("list_chapters"), counts.get("own_contents"))
        return found == {"ourbook": (1, "amsbook"), "plainer": (0, None)}

    def art_pdf():
        text = pages(art)
        if not isinstance(text, str):
            return text
        return "Contents" in text and "List of Figures" in text \
            and re.search(r"(?m)^\s*1\s+Classone", text) \
            and not re.search(r"[0-9][ \t]+(Contents|List of Figures)", text) \
            and "Classfigure" in text and "wasn't built" not in art_said \
            and "its lists of contents, figures, and tables headed as unnumbered sections, " \
            in art_said \
            and "WARNING: pdf: " + warning % ("the copy LaTeX builds", "amsart") in art_said
    return [
        ("an amsbook book's tagged copy starts its lists as amsbook does, and the run says "
         "so and warns of what LaTeX's tagging still does to them",
         lambda: ran(ams_done)
         and "amsbook's lists of contents, figures, and tables told to start their pages as "
             "amsbook does" in ams_said
         and "WARNING: tagged: " + warning % ("the copy", "amsbook") in ams_said
         and "so a chapter's \"Chapter 1.\" is gone" in ams_said),
        ("its PDF, built from its own LaTeX, has its lists headed as amsbook heads them and "
         "its chapter numbered 1, none of them a chapter, and the run says so", ams_pdf),
        ("an amsart article's tagged copy heads its lists as unnumbered sections, and the run "
         "says so and warns of what's still wrong",
         lambda: ran(art_done)
         and "its lists of contents, figures, and tables headed as unnumbered sections, set "
             "as the class sets their headings" in art_said
         and "WARNING: tagged: " + warning % ("the copy", "amsart") in art_said
         and "so a section's number falls under its title" in art_said),
        ("and its PDF builds, where LaTeX had stopped on the lists' headings, and the run "
         "says so", art_pdf),
        ("untagged, an amsart article keeps the class's own headings for its lists, nothing "
         "of them in its contents", art_untagged),
        # A class of the book's own that loads one of them is that class's
        # (texremediate.loaded_class; a review): its own class file beside
        # it, and one that loads that one, a \\LoadClass in a comment aside.
        ("a book in a class of its own beside it, built on amsbook, is taken for amsbook's, "
         "two classes down, and a book class's isn't",
         loaded_classes),
        ("a memoir book's tagged copy is warned of too, its entries run together and its dot "
         "leaders read as text",
         lambda: memoir_done.returncode == 0
         and "WARNING: tagged: " + warning % ("the copy", "memoir") in memoir_said
         and "its dot leaders are read as text" in memoir_said
         and "amsbook's lists" not in memoir_said and "unnumbered sections" not in memoir_said),
    ]


def case_caption_notes(work):
    """A note's mark in a caption LaTeX's tagging sets twice, where it took
    two numbers (a review): a longtable's caption, short and too long for
    its line, whose caption latex-lab's table module sets twice in an
    alignment's cell; a \\captionof in a minipage, whose \\footnote took
    two of the minipage's letters and set its text twice under it; and the
    caption package's \\captionbox. Each takes one number, the notes after
    them theirs, and the run counts them."""
    lt, box = os.path.join(work, "longtable"), os.path.join(work, "captionbox")
    for folder in (lt, box):
        os.makedirs(folder)
        with open(os.path.join(folder, "conversion.yaml"), "w") as fh:
            fh.write("targets:\n  tagged:\n    format: source\n    tagging: \"on\"\n"
                     "  pdf:\n    format: pdf\n")
    with open(os.path.join(lt, "book.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{book}\n\\usepackage{longtable}\n\\makeatletter\n"
                 "\\providecommand\\captionof[1]{\\def\\@captype{#1}\\caption}\n\\makeatother\n"
                 "\\begin{document}\n\\chapter{Capnotes}\n"
                 "\\begin{longtable}{ll}\n\\caption{Ltshort\\protect\\footnotemark}\\\\\n"
                 "a & b \\\\\n\\end{longtable}\n\\footnotetext{Ltnotea.}\n"
                 "\\begin{longtable}{ll}\n\\caption{Ltlong, with words enough to run past the "
                 "width of a line of the page, so that it is set as a "
                 "paragraph\\protect\\footnotemark}\\\\\n"
                 "c & d \\\\\n\\end{longtable}\n\\footnotetext{Ltnoteb.}\n\n"
                 "\\noindent\\begin{minipage}{\\linewidth}\n\\centering\\rule{1cm}{1cm}\n"
                 "\\captionof{figure}{Mpcaption\\protect\\footnote{Mpnote.}}\n"
                 "\\end{minipage}\n\nCaptext.\\footnote{Ltnotec.}\n\\end{document}\n")
    with open(os.path.join(box, "book.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{book}\n\\usepackage{caption}\n\\begin{document}\n"
                 "\\chapter{Boxnotes}\n\\begin{figure}\\centering\n"
                 "\\captionbox{Boxcaption\\protect\\footnotemark}{\\rule{8cm}{1cm}}\n"
                 "\\end{figure}\n\\footnotetext{Boxnotea.}\nBoxtext.\\footnote{Boxnoteb.}\n"
                 "\\end{document}\n")
    lt_done, box_done = convert(lt), convert(box)
    lt_said, box_said = lt_done.stdout + lt_done.stderr, box_done.stdout + box_done.stderr
    told = "%d caption(s) holding a note's mark told to give it one number"

    def pages(folder):
        """The book's PDF's text, a reason to skip, or False with none."""
        why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
        if why:
            return skip(why)
        path = os.path.join(folder, "pdf", "book.pdf")
        if not os.path.exists(path):
            return False
        if not shutil.which("pdftotext"):
            return skip("no pdftotext to read the PDF")
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True,
                              text=True).stdout

    def lt_pdf():
        text = pages(lt)
        if not isinstance(text, str):
            return text
        return re.search(r"Ltshort\s*1(?!\d)", text) \
            and re.search(r"paragraph\s*2(?!\d)", text) \
            and re.search(r"(?m)^\s*1\s*Ltnotea\.", text) \
            and re.search(r"(?m)^\s*2\s*Ltnoteb\.", text) \
            and re.search(r"Captext\.\s*3(?!\d)", text) \
            and re.search(r"(?m)^\s*3\s*Ltnotec\.", text) \
            and re.search(r"Mpcaption\s*a(?![a-z])", text) \
            and re.search(r"(?m)^\s*a\s*Mpnote\.", text) and text.count("Mpnote.") == 1 \
            and "one number for a note's mark in a caption" in lt_said

    def box_pdf():
        text = pages(box)
        if not isinstance(text, str):
            return text
        return re.search(r"Boxcaption\s*1(?!\d)", text) \
            and re.search(r"(?m)^\s*1\s*Boxnotea\.", text) \
            and re.search(r"Boxtext\.\s*2(?!\d)", text) \
            and re.search(r"(?m)^\s*2\s*Boxnoteb\.", text) \
            and "one number for a note's mark in a caption" in box_said
    return [
        ("a longtable's caption, short or long, and a minipage's \\captionof, each holding a "
         "note's mark, are counted in the tagged copy, which gets the block",
         lambda: ran(lt_done) and (told % 3) in lt_said
         and "oer.break.space" in read(lt, "tagged", "book.tex")),
        ("and in its PDF each mark takes one number, the minipage's note one letter and its "
         "text set once, and the note after them its own", lt_pdf),
        ("a \\captionbox holding a note's mark is counted too",
         lambda: ran(box_done) and (told % 1) in box_said),
        ("and in its PDF the mark takes one number, the note after it its own", box_pdf),
    ]


def case_line_measure(work):
    """latexbuild.LINE_LENGTH, the AAA page's measure of its full lines, in
    a document of LaTeX's own in Latin Modern: a paragraph of words a
    hyphenation point divides inside a ligature (of-fi-cial), whose glyph
    TeX keeps in the discretionary there, which the measure passed over,
    and a poem's lines, each ended by a line break, which it counted as
    full, as a review found; the measure's lines and characters are the
    paragraph's full lines' in the PDF's text."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import latexbuild
    os.makedirs(work)
    words = " ".join(("official sufficient efficient difficult affluent office coffee effort "
                      "afford different").split() * 8)
    poem = "\\\\\n".join("A short line of a poem, %d." % i for i in range(12))
    with open(os.path.join(work, "lines.tex"), "w", encoding="utf-8") as fh:
        fh.write("\\documentclass{article}\n" + latexbuild.LINE_LENGTH + "\\begin{document}\n"
                 + words + ".\n\n" + poem + "\n\\end{document}\n")

    def counted():
        why = why_no_tex("no lualatex to build with", "lualatex")
        if why:
            return skip(why)
        if not shutil.which("pdftotext"):
            return skip("no pdftotext to read the PDF")
        subprocess.run(["lualatex", "-interaction=nonstopmode", "lines.tex"], cwd=work,
                       capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
        log = os.path.join(work, "lines.log")
        with open(log, encoding="utf-8", errors="replace") if os.path.exists(log) \
                else io.StringIO() as fh:
            measured = latexbuild.LINE_MEASURED.findall(fh.read())
        text = subprocess.run(["pdftotext", "-raw", os.path.join(work, "lines.pdf"), "-"],
                              capture_output=True, text=True).stdout
        rows = [row.strip() for row in text.split("\n") if row.strip()]
        last = next((i for i, row in enumerate(rows) if row.endswith("different.")), None)
        if not measured or not last:
            return False
        full = rows[:last]
        return (int(measured[-1][0]), int(measured[-1][1])) == (
            len(full), sum(len(row) for row in full)) and len(full) > 4
    return [
        ("the AAA page's measure of a paragraph's full lines counts their characters as "
         "the PDF's text has them, spaces among them, a ligature a hyphenation point "
         "divides as its letters, and no line a line break ends",
         counted),
    ]


def case_pdf_copy(work):
    """The PDF target's copy of the book's folder: a link the book makes
    to a folder beside it still finds it, the book's .latexmkrc is kept
    and doesn't move the PDF, and what LaTeX couldn't resolve is named."""
    why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
    if why:
        return [("the PDF build's copy of the book keeps its links and .latexmkrc",
                 lambda: skip(why))]
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
        why = why_no_tex("no lualatex to build the workbook", "lualatex")
        if why:
            return skip(why)
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
        why = why_no_tex("no pdflatex to build the workbook untagged", "pdflatex")
        if why:
            return skip(why)
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
        LuaLaTeX, tagged; None without LuaLaTeX, "pikepdf" without pikepdf
        to read it."""
        if why_no_tex("no lualatex", "lualatex"):
            return None
        try:
            import pikepdf  # noqa: F401
        except ImportError:
            return "pikepdf"
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
                return skip(why_no_tex("no lualatex to build the copy", "lualatex"))
            if result == "pikepdf":
                return skip("no pikepdf to read the tagged PDF's structure")
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


# Every printable character of ASCII.
ASCII = "".join(chr(c) for c in range(33, 127))

# A display formula too wide for a line, which LaTeX fits to it
# (latexbuild's FIT_MACROS).
LONG_SUM = " + ".join("a_{%d}" % k for k in range(1, 41))


def case_latex_target(work):
    """The latex target: a Markdown book written as LaTeX, a master and a
    file per chapter, read back as a LaTeX source to the same pages. Its
    SVG picture only where rsvg-convert makes it a PDF (why_no_svg): the
    target writes \\includesvg without, which no build here takes."""
    os.makedirs(os.path.join(work, "img"))
    png(os.path.join(work, "img", "square.png"), (90, 90, 90))
    png(os.path.join(work, "img", "a+b.png"), (30, 30, 30))
    with open(os.path.join(work, "img", "circle.svg"), "w") as fh:
        fh.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                 '<circle cx="20" cy="20" r="15" fill="black"/></svg>\n')
    circle = "" if why_no_svg() else "![A black circle.](img/circle.svg)\n\n"
    with open(os.path.join(work, "one.md"), "w", encoding="utf-8") as fh:
        fh.write("# Shapes\n\nA square:\n\n![A gray square.](img/square.png)\n\n"
                 "The area is $s^2$,[^area] and the next chapter has [circles](two.md#circles).\n\n"
                 "| Shape | Sides |\n|---|---|\n| Square | 4 |\n| Triangle | 3 |\n\n"
                 "Measured:\n\n```{#area-code .python .numberLines startFrom=\"3\"}\n"
                 "area = s * s  # in square units\nif area > 10 and s[0] != '{':\n"
                 "    print(\"big\\n\")\n```\n\n"
                 "Called as `area(s[0])`{.python} or `area(t)`, after [the code](#area-code).\n\n"
                 "Its side is $s$.[^side]\n\n"
                 "[^area]: Computed so:\n\n    ```python\n    area = s * s  # 100%\n    ```\n\n"
                 "[^side]: ```python\n    side = s  # one side\n    ```\n")
    with open(os.path.join(work, "two.md"), "w", encoding="utf-8") as fh:
        fh.write("# Circles {#circles}\n\n" + circle +
                 "Its area is $\\pi r^2$.\n\n1. Draw it.\n2. Measure it.\n\n"
                 "So $$A = \\pi r^2.$$\\\nQ.E.D.\n\n"
                 + "A long sum: $$S = " + LONG_SUM + "$$\n\n"
                 # A worked example's steps, which the PDF's LaTeX measures.
                 '<table role="presentation" class="formula-steps"><tr>'
                 '<td style="text-align: right">$x + 1$</td>'
                 '<td style="text-align: center">$=$</td><td style="text-align: left">$2$</td>'
                 '<td style="text-align: left">Take one from each side.</td></tr></table>\n\n'
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
                 "</thead></table>\n\n"
                 # Every character of ASCII, each of those the writer escapes.
                 "```python\nx = %s  # every character\n```\n\nAnd inline: `%s`{.python}.\n"
                 % (ASCII, ASCII.replace("`", "")))
    with open(os.path.join(work, "three.md"), "w", encoding="utf-8") as fh:
        fh.write("# Figures\n\nSee [the triangle](#pascal).\n\n"
                 "<figure id=\"pascal\"><table><tbody><tr><td>1</td></tr><tr><td>1</td>"
                 "<td>1</td></tr></tbody></table><figcaption>The first rows of Pascal's "
                 "triangle</figcaption></figure>\n\n<figure id=\"outer\"><figure>"
                 "<img src=\"img/square.png\" alt=\"A flowchart.\"></figure>"
                 "<figcaption>A small example</figcaption></figure>\n\n"
                 # Two pictures side by side, as LibreTexts sets them.
                 "<figure id=\"pair\"><div class=\"row\"><figure>"
                 "<img src=\"img/square.png\" alt=\"A left square.\"></figure><figure>"
                 "<img src=\"img/square.png\" alt=\"A right square.\"></figure></div>"
                 "<figcaption>Two squares side by side</figcaption></figure>\n\n"
                 "Termthree\n\n:   ```python\n    defined = 3\n    ```\n\n"
                 "```python\nsides = 3  # a triangle\n```\n\n"
                 "Its [lorry]{lang=en-GB} is grey.\n\n"
                 "::: {lang=en-GB}\nA paragraph spelt so.\n\n## Holiday\n\nIts fortnight.\n:::\n")
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
    with open(os.path.join(BIN, "highlighting.theme"), encoding="utf-8") as fh:
        comment = json.load(fh)["text-styles"]["Comment"]["text-color"]
    comment_rgb = ",".join("%.2f" % (int(comment[i:i + 2], 16) / 255) for i in (1, 3, 5))

    back = os.path.join(work, "back")
    read_back = []

    def reading():
        """The latex target read back as a LaTeX source, once."""
        if not read_back:
            shutil.copytree(out, back)
            with open(os.path.join(back, "conversion.yaml"), "w") as fh:
                fh.write("defaults:\n  latex:\n    main: shapes.tex\n"
                         "targets:\n  html:\n    format: html\n")
            read_back.append(convert(back))
        return read_back[0]

    def page(folder, stem):
        path = os.path.join(folder, "html", stem + ".html")
        return read(folder, "html", stem + ".html") if os.path.exists(path) else ""

    def code_texts(text):
        return [html_module.unescape(re.sub(r"<[^>]+>", "", c))
                for c in re.findall(r"<pre\b[^>]*>(.*?)</pre>", text, re.S)]

    def inline_texts(text):
        text = re.sub(r"<pre\b.*?</pre>", "", text, flags=re.S)
        return [html_module.unescape(re.sub(r"<[^>]+>", "", c))
                for c in re.findall(r"<code\b[^>]*>(.*?)</code>", text, re.S)]

    def round_trip():
        if circle and not shutil.which("pdftocairo"):
            # The target makes the SVG picture a PDF, and read back as a
            # LaTeX source, a PDF image is made an SVG with pdftocairo.
            return skip("no pdftocairo to make the latex target's PDF picture an SVG, read "
                        "back (sudo apt install poppler-utils)")
        reading()
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
        why = why_no_tex("no latexmk and lualatex to build the latex target",
                         "latexmk", "lualatex")
        if why:
            return skip(why)
        done = subprocess.run([engine, "-lualatex", "-interaction=nonstopmode",
                               "shapes.tex"], cwd=out, capture_output=True,
                              text=True, timeout=600)
        return done.returncode == 0 and os.path.exists(os.path.join(out, "shapes.pdf"))

    def fitted():
        """The master's build, by latexmk (builds), kept the long sum's fit
        in its .aux, its run counted as the second, where counted as the run
        the file changed on every run."""
        why = why_no_tex("no latexmk and lualatex to build the latex target",
                         "latexmk", "lualatex")
        if why:
            return skip(why)
        aux = os.path.join(out, "shapes.aux")
        text = read(work, "latex", "shapes.aux") if os.path.exists(aux) else ""
        return "\\OERFitState{" in text and "\\OERFitRun{2}" in text

    def edited():
        """The book edited after its build (builds), a sum too wide put
        before the long one, converted again and built again in the same
        folder, with the last build's .aux: the last run says it set both
        smaller, each by its own measure, and the block of code holding
        every character of ASCII, too long for its line, as before. The
        .aux's count of runs, kept from the build before, had said no more
        were to be fitted, and its fits, by their numbers, were the wrong
        formulas'."""
        why = why_no_tex("no latexmk and lualatex to build the latex target",
                         "latexmk", "lualatex")
        if why:
            return skip(why)
        again = work + "-edited"
        shutil.copytree(work, again)
        with open(os.path.join(again, "two.md"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(again, "two.md"), "w", encoding="utf-8") as fh:
            fh.write(text.replace("A long sum:", "A longer sum: $$T = "
                                  + LONG_SUM.replace("a_", "b_") + " + c$$\n\nA long sum:"))
        convert(again)
        done = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode",
                               "shapes.tex"], cwd=os.path.join(again, "latex"),
                              capture_output=True, text=True, timeout=600)
        log = os.path.join(again, "latex", "shapes.log")
        if done.returncode or not os.path.exists(log):
            return False
        with open(log, encoding="utf-8", errors="replace") as fh:
            runs = re.findall(r"^TextbookImprover fit: run \d+, (\d+) narrowed, (\d+) smaller",
                              fh.read(), re.M)
        return bool(runs) and runs[-1] == ("0", "3")

    def in_place():
        """The target's LaTeX built (builds) and then edited in place, the
        long sum made a short one on the line it was on, and built again
        beside the build's .aux: the last run fits nothing but the block of
        code holding every character of ASCII. The .aux's count of runs had
        said no more were to be fitted, and nothing numbered had moved, so
        the long sum's fit went on to the short one."""
        why = why_no_tex("no latexmk and lualatex to build the latex target",
                         "latexmk", "lualatex")
        if why:
            return skip(why)
        again = work + "-in-place"
        shutil.copytree(out, again)
        with open(os.path.join(again, "two.tex"), encoding="utf-8") as fh:
            text = fh.read()
        if text.count(LONG_SUM) != 1:
            return False
        with open(os.path.join(again, "two.tex"), "w", encoding="utf-8") as fh:
            fh.write(text.replace(LONG_SUM, "a_{1} + a_{2}"))
        done = subprocess.run(["latexmk", "-lualatex", "-interaction=nonstopmode",
                               "shapes.tex"], cwd=again, capture_output=True, text=True,
                              timeout=600)
        log = os.path.join(again, "shapes.log")
        if done.returncode or not os.path.exists(log):
            return False
        with open(log, encoding="utf-8", errors="replace") as fh:
            runs = re.findall(r"^TextbookImprover fit: run \d+, (\d+) narrowed, (\d+) smaller",
                              fh.read(), re.M)
        return bool(runs) and runs[-1] == ("0", "1")

    def old_aux():
        """The target's LaTeX built (builds) and built again, forced, beside
        an .aux file as one written before a table could have more than
        one column of words would have it, a worked example's steps' width
        with no column's number: the build ends without an error. Read with
        a third argument, as a width with its column's number is, the line
        took the next one of the .aux for it, and LaTeX ended with Lua's
        error (unexpected symbol near '\\')."""
        why = why_no_tex("no latexmk and lualatex to build the latex target",
                         "latexmk", "lualatex")
        if why:
            return skip(why)
        again = work + "-old-aux"
        shutil.copytree(out, again)
        aux = os.path.join(again, "shapes.aux")
        if not os.path.exists(aux):
            return False
        with open(aux, encoding="utf-8") as fh:
            text, found = re.subn(r"\\OERFitStepsWidth\{(\d+)\}\{\d+\}\{(\d+)\}",
                                  r"\\OERFitStepsState{\1}{\2}", fh.read())
        if not found:
            return False
        with open(aux, "w", encoding="utf-8") as fh:
            fh.write(text)
        done = subprocess.run(["latexmk", "-g", "-lualatex", "-interaction=nonstopmode",
                               "shapes.tex"], cwd=again, capture_output=True, text=True,
                              timeout=600)
        return done.returncode == 0 and os.path.exists(os.path.join(again, "shapes.pdf"))

    def read_files_digested():
        """The fitting's macros (latexbuild.FIT_MACROS) in a document of
        LaTeX's own, after a file it inputs with \\input{} before them, as
        a book's header-includes come before them, whose sum a display
        sets, and with a display in a file read with TeX's own \\input,
        built three times: each file edited, its sum made longer, and the
        document built again beside its .aux, the fitting starts again. A
        hook on LaTeX's \\input{} saw neither."""
        why = why_no_tex("no lualatex to build with", "lualatex")
        if why:
            return skip(why)
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import latexbuild
        folder = work + "-files"
        os.makedirs(folder)

        def terms(letter, count):
            return " + ".join("%s_{%d}" % (letter, k) for k in range(1, count + 1))

        def write(name, text):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                fh.write(text)

        def build():
            subprocess.run(["lualatex", "-interaction=nonstopmode", "doc.tex"], cwd=folder,
                           capture_output=True, timeout=300, stdin=subprocess.DEVNULL)
            log = os.path.join(folder, "doc.log")
            with open(log, encoding="utf-8", errors="replace") if os.path.exists(log) \
                    else io.StringIO() as fh:
                return fh.read()
        write("early.tex", "\\newcommand\\earlysum{" + terms("a", 40) + "}\n")
        write("plain.tex", "{\\OERFitFormula{2}{d}\\[" + terms("b", 40) + "\\]}\n")
        write("doc.tex", "\\documentclass{article}\n\\input{early}\n" + latexbuild.FIT_MACROS
              + "\\begin{document}\n{\\OERFitFormula{1}{d}\\[\\earlysum\\]}\n"
              "\\input plain.tex\n\\end{document}\n")
        for _ in range(3):
            build()
        found = []
        for name, letter in (("early.tex", "a"), ("plain.tex", "b")):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                text = fh.read()
            write(name, text.replace(terms(letter, 40), terms(letter, 50)))
            found.append("TextbookImprover fit: %s has changed since the fits were decided"
                         % name in build())
        return found == [True, True]
    return [
        ("the master starts with \\DocumentMetadata and \\include-s each chapter",
         lambda: master.startswith("\\DocumentMetadata")
         and "\\include{one}" in master and "\\include{two}" in master
         and master.index("\\include{one}") < master.index("\\include{two}")),
        ("each chapter is a file of its own, the master's division commands not in it",
         lambda: "Shapes" in one and "Circles" in two and "\\mainmatter" not in one
         and "\\begin{document}" not in one + two),
        ("the images are beside them, each with its alt text",
         lambda: os.path.exists(os.path.join(out, "img", "square.png"))
         and re.search(r"alt=\{A\s+gray\s+square\.\}", one)),
        ("and the SVG made PDF, with its alt text",
         lambda: skip(why_no_svg()) if why_no_svg()
         else os.path.exists(os.path.join(out, "img", "circle.pdf"))
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
        ("a figure in a figure, or in a div in one: one figure, one caption",
         lambda: three.count("\\begin{figure}") == 2
         and three.count("\\caption{A small example}") == 1
         and three.count("\\caption{Two squares side by side}") == 1
         and len(re.findall(r"alt=\{A\s+left\s+square\.\}", three)) == 1
         and "\\caption{}" not in three),
        ("a head cell's lines are broken in a minipage, as the writer breaks them",
         lambda: "\\begin{minipage}[b]{\\linewidth}\\raggedright\nProof: first,\\\\\n" in two),
        ("the writer's \\multicolumn at a table's edge is there to read back",
         lambda: re.search(r"\\multicolumn\{2\}\{[^}]*@\{\}\}", two) is not None),
        ("a display formula comes out of the emphasis around it, which tagging can't take",
         lambda: "C = 2 \\pi r" in two and "\\emph{\\[" not in two),
        ("a table in a table's cell is a tabular, its head declared for tagging, where "
         "there's tagging, and ruled off",
         lambda: "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/header-rows={1}}\\fi"
         "\\begin{tabular}[t]{" in two
         and "A & B & A and B \\\\\n\\hline\n" in two and "T & F & F \\\\" in two),
        ("what the PDF target's filter writes is there too: a link's /Contents",
         lambda: "\\OERLinkContents{" in one and "\\OERLinkContents" in master),
        ("and a passage's language, tagged around babel's own command",
         lambda: "\\oerlang{en-GB}{\\foreignlanguage{british}{lorry}}" in three
         and "\\begin{oerlanguage}{en-GB}" in three
         and "\\oerlang{en-GB}{Holiday}" in three and "\\NewDocumentCommand \\oerlang" in master),
        ("read back, a passage's language is babel's again, none of its tags printed",
         lambda: reading()
         and '<span lang="en-GB">lorry</span>' in page(back, "three")
         and re.search(r'<div lang="en-GB">\s*<p>A paragraph spelt so\.</p>', page(back, "three"))
         and re.search(r'<h2[^>]*>Holiday</h2>', page(back, "three"))
         and not re.search(r"oerlang|text / lang|en-GB}", page(back, "three"))),
        # LaTeX's tagged footnote can't read a code block's verbatim as its
        # text (footnote-code.lua); read back, Pandoc's reader takes the file
        # the preamble writes.
        ("and a code block in a footnote, read from a file the master's preamble writes",
         lambda: "\\OERCodeFile{oer-code-1.tex}" in one
         and "\\begin{filecontents*}[overwrite]{oer-code-1.tex}" in master),
        ("a block of code is marked to be fitted, as in the PDF, a footnote's too",
         lambda: re.search(r"\\OERFitCode\{(\d+)\}\s*\\OERCodeFile\{oer-code-1\.tex\}\s*"
                           r"\\OERFitCodeEnd\{\1\}", one)
         and re.search(r"\\OERFitCode\{(\d+)\}\s*(?:%[^\n]*\n\s*)?(?:\\protect[^\n]*\n\s*)?"
                       r"\\begin\{Shaded\}.*?\\end\{Shaded\}\s*\\OERFitCodeEnd\{\1\}", three,
                       re.S)),
        # The writer sets a footnote's first block after \footnote{, so a
        # footnote that opens with code opens with its mark there, which a
        # pattern for a mark on a line of its own left, and Pandoc's reader
        # stopped on it ("unexpected ()"). And a definition that opens with
        # code opens with a no-break space before its mark, as the writer
        # opens one with code, which reads back as the writer's own does.
        ("a footnote that opens with code has its mark after \\footnote{, and reads back, "
         "its code a footnote's; and a definition that opens with code opens with a no-break "
         "space, and reads back, the term and its code",
         lambda: re.search(r"\\footnote\{\\OERFitCode\{\d+\}", one)
         and re.search(r"\\item\[Termthree\]\s*~\s*\\OERFitCode\{\d+\}", three)
         and reading()
         and re.search(r'<li id="fn2">\s*<div class="sourceCode"', page(back, "one"))
         and "side = s  # one side" in code_texts(page(back, "one"))
         and re.search(r"<dt>Termthree</dt>", page(back, "three"))
         and "defined = 3" in code_texts(page(back, "three"))),
        ("highlighted code's macros are in the theme's colors (lib/highlighting.py)",
         lambda: "\\newcommand{\\CommentTok}[1]{\\textcolor[rgb]{%s}" % comment_rgb in master
         and "\\begin{Highlighting}" in three),
        ("read back as a LaTeX source, each chapter gives the same page", round_trip),
        # Pandoc's reader made a highlighted block a paragraph and stopped
        # on inline code holding a bracket (latexsource.highlighted_code),
        # and made the PDF target's group around inline code a span
        # (latexsource.inline_code_marks), which a review found.
        ("and highlighted code is code again: a block with its language, numbered from 3, "
         "and its id, a footnote's, and inline code, the text of each as written, every "
         "character of ASCII in it, and no inline code, highlighted or not, in a span",
         lambda: reading()
         and re.search(r'<div class="sourceCode" id="[^"]*area-code"[^>]*><pre\s+class="sourceCode '
                       r'numberSource python numberLines"><code class="sourceCode python" '
                       r'style="counter-reset: source-line 2;">', page(back, "one"))
         and re.search(r'<li id="fn1">.*?<pre\s+class="sourceCode python">', page(back, "one"), re.S)
         and all(code_texts(page(back, s)) == code_texts(page(work, s))
                 and inline_texts(page(back, s)) == inline_texts(page(work, s)) for s in ("one", "two"))
         and "if area > 10 and s[0] != '{':" in code_texts(page(back, "one"))[0]
         and ASCII in code_texts(page(back, "two"))[0]
         and "<code>area(s[0])</code>" in page(back, "one")
         and "<code>area(t)</code>" in page(back, "one")
         and not any(re.search(r"<span>\s*<code", page(back, s)) for s in ("one", "two"))),
        ("it builds with latexmk and LuaLaTeX", builds),
        ("a formula too wide for its line is marked to be fitted, as in the PDF, and "
         "latexmk's runs settle with it fitted",
         lambda: "{\\OERFitFormula{" in two and fitted()),
        ("and with another put before it, built again beside the last build's files, each "
         "is fitted by its own measure",
         edited),
        ("and its LaTeX edited in place, the long sum made short, built again beside them, "
         "nothing is fitted but a block of code too long for its line",
         in_place),
        ("and built again beside an .aux file written before a table could have more than "
         "one column of words, a step's width with no column's number, it builds",
         old_aux),
        ("the fitting starts again for an edit to a file input before its macros, or read "
         "with TeX's own \\input",
         read_files_digested),
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
    pdf_why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
    pdf = not pdf_why
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
    sample = sample_text(work)
    tagged = copy("Topic A One.tex")
    # A pattern names them too, in sorted order.
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("defaults:\n  latex:\n    main: src/*.tex\n"
                 "targets:\n  html:\n    format: html\n")
    pattern = convert(work)
    sorted_sample = sample_text(work)
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
    rerun = subprocess.run(["python3", os.path.join(BIN, "convert.py"), "--quick", "--quiet",
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
            return skip(pdf_why)
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
            return skip(pdf_why)
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
    import pandocversion
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
    # The spaces around them, as LaTeX sets them: "Un mot rouge ici. Un
    # mot, ici. Avec T texte fin. Un gras et vu." (TeX Live 2026, measured);
    # an opening code that takes what follows \begin for an argument, and
    # formulas, a book's environment's and a definition's used in one.
    spaced = {"a.tex": "\\newenvironment{rouge}{}{}\n"
                       "\\newenvironment{titre}[1]{\\textbf{#1} }{}\n"
                       "\\newenvironment{amat}{\\left(}{\\right)}\n"
                       "\\newenvironment{grasb}{\\textbf}{}\n"
                       "\\newenvironment{mytab}{\\begin{tabular}}{\\end{tabular}}\n"
                       "\\newenvironment{coltab}{\\begin{tabular}% its columns\n}"
                       "{\\end{tabular}}\n"
                       "\\newenvironment{myeq}{\\begin{equation}}{\\end{equation}}\n"
                       "\\newcommand{\\foo}{\\begin{rouge}z\\end{rouge}}\n"
                       "Un \\begin{rouge}mot\\end{rouge} rouge ici. Un\\begin{rouge} "
                       "mot\\end{rouge}, ici. Avec \\begin{titre} {T} texte\\end{titre} fin. "
                       "Un \\begin{grasb}{gras}\\end{grasb} et \\begin{rouge} {vu}\\end{rouge}.\n"
                       "$\\begin{amat}x\\end{amat}^2$ $\\foo^2$\n\n"
                       "\\begin{mytab} {ll}a & b\\end{mytab}\n\n"
                       "\\begin{coltab} {l}c\\end{coltab}\n\n"
                       "\\begin{myeq} a\\begin{rouge} y\\end{rouge} ^2\\end{myeq}\n"}
    latexsource.environment_definitions(spaced, ["a.tex"], {},
                                        latexsource.book_environments([spaced["a.tex"]]))
    # MathML, as the run asks for it, so a formula's base shows (pandocversion).
    spaced_read = subprocess.run(
        ["pandoc", "-f", "latex", "-t", "html", "--wrap=none"] + pandocversion.mathml(),
        capture_output=True, text=True,
        input="\\documentclass{book}\n\\begin{document}\n" + spaced["a.tex"]
        + "\\end{document}\n").stdout
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
    # A table ruled row by row as the PDF target writes it, in a latex
    # target's LaTeX read back.
    ruled_back = latexsource.repair_text(
        "{\\OERFitTable{1}{2}{0}\\OERRowRules[F1F1F1]\n\n\\begin{longtable}[]{@{}ll@{}}\n"
        "\\toprule\\noalign{}\n\\endhead\na & b\\OERRowRule \\\\\nc & d\\OERRowRule \\\\\n"
        "\\end{longtable}\n\n\\OERFitTableEnd{1}}\n", {})
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
        why = why_no_tex("no lualatex for the copies' builds", "lualatex")
        if why:
            return skip(why)
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
        why = why_no_tex("no lualatex for the copies' builds", "lualatex")
        if why:
            return skip(why)
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
    language_counts = {}
    languages = latexsource.language_marks(
        "A \\oerlang{fr}{\\foreignlanguage{french}{une {phrase}}} and "
        "\\oerlang{fr} {\\href{https://example.org}{lien}}.\n\\begin{oerlanguage}{fr}\n\n"
        "Un paragraphe.\n\\end{oerlanguage}\n\\section{\\texorpdfstring{\\oerlang{fr}{Une "
        "\\oerlang{fr}{\\foreignlanguage{french}{en}}}}{Une en}}\n% \\oerlang{fr}{kept}\n"
        "\\verb|\\oerlang{x}{y}| and \\oerlang{fr} alone.\n", language_counts)
    return [
        ("the PDF target's language tags are taken out, babel's commands inside them kept, "
         "nothing in a comment or \\verb, nor a tag not as the target writes it",
         lambda: languages == (
             "A \\foreignlanguage{french}{une {phrase}} and "
             "\\href{https://example.org}{lien}.\n\nUn paragraphe.\n"
             "\\section{\\texorpdfstring{Une \\foreignlanguage{french}{en}}{Une en}}\n"
             "% \\oerlang{fr}{kept}\n\\verb|\\oerlang{x}{y}| and \\oerlang{fr} alone.\n")
         and language_counts == {"language_spans": 4, "language_passages": 1,
                                 "language_passages_end": 1}),
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
        ("a language babel hasn't installed, the book's or a passage's, is named, with how "
         "to find its package with tlmgr or with apt",
         lambda: any("babel has no language ngerman, which the book, or a passage of it, is in"
                     in advice and "search --global --file /ngerman.ldf" in advice
                     and "apt-file search /ngerman.ldf" in advice
                     for advice in latexbuild.failure_advice(
                         "! Package babel Error: Unknown option 'ngerman'.\n"
                         "(babel)                Suggested actions:\n"))),
        # TinyTeX has neither, and a build stops on cancel.sty first and,
        # once that's installed, on pict2e.sty: each alone gets the one
        # line, and with another file the one line and that file's.
        ("a struck-out term's packages missing, cancel or pict2e, are named together, "
         "with the command that installs both",
         lambda: all(len(advice) == 1 and "install cancel pict2e" in advice[0]
                     and "texlive-latex-extra texlive-pictures" in advice[0]
                     for advice in (latexbuild.failure_advice(
                         f"! LaTeX Error: File `{name}' not found.\n")
                         for name in ("cancel.sty", "pict2e.sty")))
         and latexbuild.failure_advice("! LaTeX Error: File `cancel.sty' not found.\n"
                                       "! LaTeX Error: File `pict2e.sty' not found.\n"
                                       "! LaTeX Error: File `hanging.sty' not found.\n")[1:]
         == latexbuild.failure_advice("! LaTeX Error: File `hanging.sty' not found.\n")),
        # pict2e.sty alone is what a book that strikes out no term stops on,
        # which picture_paths: off builds without it; cancel.sty means a
        # term is struck out, whose strokes load pict2e whatever the setting.
        ("and without pict2e alone, the advice names picture_paths: off, which a book "
         "that strikes out no term builds without it with; without cancel, it doesn't",
         lambda: "`picture_paths: off` in conversion.yaml, under `defaults:` or the target's "
         "name, builds without pict2e"
         in latexbuild.failure_advice("! LaTeX Error: File `pict2e.sty' not found.\n")[0]
         and "picture_paths" not in latexbuild.failure_advice(
             "! LaTeX Error: File `cancel.sty' not found.\n")[0]),
        ("a font that isn't installed is named, its name split over fontspec's lines too, "
         "with where an OpenStax book's faces come from",
         lambda: any("LaTeX can't find the font IBM Plex Serif Text." in advice
                     and "IBM Plex in its plex package" in advice
                     for advice in latexbuild.failure_advice(
                         "! Package fontspec Error: \n"
                         "(fontspec)                The font \"IBM Plex\n"
                         "(fontspec)                Serif Text\" cannot be found; this may\n"))),
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
         and "\\var {x}\\endvar{} and \\var{y}." in envs["a.tex"]),
        ("a space after an environment the book defines, or after its beginning where it "
         "takes no arguments, is a space, as LaTeX keeps it, where the command's name took "
         "it, and one before its arguments is passed over, as LaTeX passes it",
         lambda: "Un \\rouge mot\\endrouge{} rouge ici. Un\\rouge{} mot\\endrouge , ici. "
         "Avec \\titre  {T} texte\\endtitre{} fin." in spaced["a.tex"]
         and re.search(r"<p>Un mot rouge ici\. Un mot, ici\. Avec <strong>T</strong> texte "
                       r"fin\. Un <strong>gras</strong> et (?:<span>)?vu(?:</span>)?\. <math ",
                       spaced_read) is not None),
        ("and a group or an option after its beginning, which an opening code ending in a "
         "command may take for an argument, follows a space, as it did, where one the code "
         "can't take follows an empty group",
         lambda: "Un \\grasb {gras}\\endgrasb{} et \\rouge{} {vu}\\endrouge ." in spaced["a.tex"]
         and "\\mytab  {ll}a & b\\endmytab \n" in spaced["a.tex"]
         and "\\coltab  {l}c\\endcoltab \n" in spaced["a.tex"]
         and re.search(r"<table>.*?<td[^>]*>a</td>\s*<td[^>]*>b</td>", spaced_read, re.S)
         is not None),
        ("but in a formula, where TeX skips spaces, a space, so no empty group is a "
         "superscript's base, in a book's environment for a formula, and in a definition's "
         "code where no space follows",
         lambda: "$\\amat x\\endamat ^2$" in spaced["a.tex"]
         and "\\myeq  a\\rouge  y\\endrouge  ^2\\endmyeq " in spaced["a.tex"]
         and "\\newcommand{\\foo}{\\rouge z\\endrouge }" in spaced["a.tex"]
         and "<msup><mi>y</mi><mn>2</mn></msup>" in spaced_read
         and "<msup><mi>z</mi><mn>2</mn></msup>" in spaced_read
         and "<mrow></mrow>" not in spaced_read),
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
        ("a table ruled row by row, as the PDF target writes it, is read back without its "
         "rules' commands, which the reader would expand as the preamble defines them",
         lambda: "OERRowRule" not in ruled_back
         and "a & b \\\\\nc & d \\\\\n\\end{longtable}" in ruled_back),
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
    contents_sample = sample_text(work)
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
    pdf_why = why_no_tex("no lualatex for the PDF", "lualatex")
    pdf = not pdf_why
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n"
                 "  tagged:\n    format: source\n    tagging: \"on\"\n"
                 + "  epub:\n    format: epub3\n  docx:\n    format: docx\n"
                 + ("  pdf:\n    format: pdf\n    pdf:\n      from: pages\n" if pdf else ""))
    second = convert(work)
    said = second.stdout + second.stderr
    # build-pdf.py on its own, to read the LaTeX, without the layout and
    # colors convert.py passes it: it had written the default page and
    # none of the book's colors, on which LaTeX stops.
    alone = subprocess.run(
        ["python3", os.path.join(BIN, "build-pdf.py"), "-d", work, "--target", "pdf",
         "--latex-only"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={k: v for k, v in os.environ.items() if not k.startswith("BOOK_LATEX")}) \
        if pdf else None
    alone_said = alone.stdout + alone.stderr if alone else ""
    alone_tex = read(work, "pdf", "book.tex") \
        if os.path.exists(os.path.join(work, "pdf", "book.tex")) else ""

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
                                      encoding="utf-8-sig", newline=""))))),
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
         if pdf else skip(pdf_why)),
        ("and the type size and margins the book's preamble gives, not Pandoc's 10pt in "
         "the book class's margins", lambda: page_layout_kept(work, said)
         if pdf else skip(pdf_why)),
        ("build-pdf.py run on its own, --latex-only, keeps the book's layout and colors, "
         "as convert.py's run gives them",
         lambda: "The LaTeX book's own layout, from its preamble: 11pt type; geometry's "
         "margin=1in; xcolor's dvipsnames colors; indented paragraphs." in alone_said
         and re.search(r"\\documentclass\[[^]]*11pt[^]]*\]\{book\}", alone_tex)
         and "\\usepackage[margin=1in]{geometry}" in alone_tex
         and "\\definecolor{oiB}{rgb}{.337,.608,.741}" in alone_tex
         if pdf else skip(pdf_why)),
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
         if pdf else skip(pdf_why)),
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
         "found", lambda: pdf_numbers(work, said) if pdf else skip(pdf_why)),
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
    why = why_no_tex("no lualatex or latexmk for the PDF target", "lualatex", "latexmk")
    if why:
        return [("a book set with packages tagging can't take builds tagged",
                 lambda: skip(why))]
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
            print("    missing from the PDF:", missing[:6], "..." if len(missing) > 6 else "")
        return not missing

    def passes_ua2():
        """The PDF passes PDF/UA-2, its figures' fonts embedded, which the
        run finds with pypdf and embeds with Ghostscript or pdftocairo:
        without them it says it can't, and PDF/UA-2 fails."""
        verapdf = os.environ.get("VERAPDF") or shutil.which("verapdf")
        if not verapdf:
            return skip("no veraPDF to check the PDF")
        if latexbuild.embedding_tool() is None:
            return skip("no Ghostscript or pdftocairo to embed a figure's fonts "
                        "(sudo apt install ghostscript)")
        try:
            import pypdf  # noqa: F401
        except ImportError:
            return skip("no pypdf for the run to find a figure's fonts to embed")
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
        if latexbuild.embedding_tool() is None:
            return skip("no Ghostscript or pdftocairo to embed a figure's fonts "
                        "(sudo apt install ghostscript)")
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
        ("the PDF from the book's own LaTeX builds tagged", lambda: built_or_why(
            os.path.exists(built) and "built by LaTeX from the book's own files" in said, said)),
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
    sample = yaml.safe_load(read(work, "project-sample.yaml")) \
        if os.path.exists(os.path.join(work, "project-sample.yaml")) else {}
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


def case_bibliography_place(work):
    """The bibliography the run writes out is a page the contents sample
    calls one, at the top level after the parts and appendices it follows,
    so adopted it's in the back matter, unnumbered."""
    files = {
        "book.tex": "\\documentclass{book}\n\\begin{document}\n\\part{Foundations}\n"
                    "\\include{one}\n\\appendix\n\\include{appa}\n"
                    "\\begin{thebibliography}{9}\n\\bibitem{knuth} D. Knuth, \\emph{The "
                    "TeXbook}.\n\\end{thebibliography}\n\\end{document}\n",
        "one.tex": "\\chapter{One}\nAs Knuth says \\cite{knuth}.\n",
        "appa.tex": "\\chapter{Answers}\nThe answers.\n",
    }
    os.makedirs(work)
    for name, text in files.items():
        with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    convert(work)
    import yaml
    sample = yaml.safe_load(read(work, "project-sample.yaml")) \
        if os.path.exists(os.path.join(work, "project-sample.yaml")) else {}
    contents = ((sample or {}).get("project") or {}).get("contents") or []

    def numbered():
        with open(os.path.join(work, "project.yaml"), "w") as fh:
            yaml.safe_dump({"project": dict(sample["project"], numbering=True)}, fh)
        convert(work)
        found = re.search(r"<title>(.*?)</title>", read(work, "html", contents[-1]["page"] + ".html")) \
            if contents and isinstance(contents[-1], dict) else None
        return found and found.group(1) == "Bibliography"
    return [
        ("the sample gives the bibliography's page type bibliography, at the top level, out "
         "of the appendices before it", lambda: isinstance(contents[-1], dict)
         and contents[-1].get("type") == "bibliography" and "role" not in contents[-1]
         and any(isinstance(c, dict) and c.get("title") == "Foundations" for c in contents)),
        ("adopted and numbered, the bibliography is unnumbered, as back matter", numbered),
    ]


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


def case_no_contents(work):
    """A pdf.metadata file's toc: false leaves out the contents page that
    project.contents generates, as it does the template's, in the PDF's
    own LaTeX (a latex target) as in the PDF; without it the page is
    there, where contents puts it."""
    os.makedirs(work)
    for stem, text in (("one", "# One\n\nText.\n"), ("two", "# Two\n\nMore.\n"),
                       ("meta", "---\ntoc: false\n---\n")):
        with open(os.path.join(work, stem + ".md"), "w", encoding="utf-8") as fh:
            fh.write(text)
    with open(os.path.join(work, "project.yaml"), "w") as fh:
        fh.write("project:\n  identifier: shapes\n  title: Shapes\n  language: en\n"
                 "  contents:\n  - generate: toc\n    name: Contents\n  - one\n  - two\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  latex:\n    format: latex\n    pdf:\n      metadata: meta.md\n"
                 "  plain:\n    format: latex\n")
    result = convert(work)
    said = result.stdout + result.stderr

    def master(target):
        path = os.path.join(work, target, "shapes.tex")
        return read(work, target, "shapes.tex") if os.path.exists(path) else ""
    return [
        ("toc: false leaves out the contents page project.contents generates, and the run "
         "says so",
         lambda: result.returncode == 0 and "\\tableofcontents" not in master("latex")
         and "the one project.contents generates is left out too" in said),
        ("without it the page is there, once",
         lambda: master("plain").count("\\tableofcontents") == 1),
    ]


CASES = [("a LaTeX book", case_book), ("two masters", case_masters),
         ("a LaTeX book's language", case_language),
         ("inline code in a LaTeX book", case_inline_code),
         ("babel's main language in a LaTeX book's tagged copy", case_babel_main),
         ("babel's commands the reader stopped on, or dropped", case_babel_reading),
         ("a paragraph break in a box's or a quotation's words", case_inline_breaks),
         ("a LaTeX book's pages in another language, in its copy and its PDF",
          case_page_languages),
         ("a LaTeX book's passages babel sets the language of, in its copy and its PDF",
          case_babel_languages),
         ("one file", case_single), ("an unbuilt book", case_unbuilt),
         ("PDF and EPS images that can't be made SVG", case_unmade_images),
         ("a PDF image's PDF, kept and read again", case_kept_images),
         ("images graphicx scales", case_scaled_images),
         ("an SVG picture the latex target can't make a PDF", case_unmade_svg),
         ("a table tagged as a division of paragraphs", case_layout_tables),
         ("the source target", case_source), ("a book with fonts of its own", case_own_fonts),
         ("a face with a STAT table that isn't a variable font", case_static_face),
         ("a LaTeX book's PDF, from its own LaTeX", case_book_pdf),
         ("a term struck out with cancel, in pieces no book reaches", case_struck_out),
         ("a list's item that opens with fancyvrb's code", case_code_label),
         ("a line break's two lines in a tagged PDF's text", case_line_breaks),
         ("a class's own contents, under tagging", case_class_contents),
         ("a note's mark in a longtable's, a minipage's, and a \\captionbox's caption",
          case_caption_notes),
         ("the AAA page's measure of its lines", case_line_measure),
         ("the PDF build's copy of the book", case_pdf_copy),
         ("the book's other masters", case_other_masters),
         ("calls of the book's macros for an image, as the review found them",
          case_review_macros),
         ("the latex target", case_latex_target),
         ("a book of documents built on their own", case_documents),
         ("the pieces the copies take", case_pieces),
         ("a book made its own way, as OpenIntro is", case_customized),
         ("a book in parts, numbered as LaTeX numbers it", case_parts),
         ("a bibliography placed by its type", case_bibliography_place),
         ("a book's citations and its bibliography", case_bibliography),
         ("floats, classes, and titles as LaTeX has them", case_floats),
         ("a book set with packages tagging can't take", case_unsupported),
         ("no contents page", case_no_contents)]


# The longest cases, started first when they run side by side.
SLOW = {"a LaTeX book's PDF, from its own LaTeX", "a book made its own way, as OpenIntro is",
        "a LaTeX book's pages in another language, in its copy and its PDF",
        "a LaTeX book's passages babel sets the language of, in its copy and its PDF",
        "the latex target", "a book of documents built on their own",
        "a book's citations and its bibliography", "a book set with packages tagging can't take"}


def run_cases(cases, keep):
    """The cases one after another, here: how many checks failed."""
    work = tempfile.mkdtemp(prefix="latex-tests-")
    failed = 0
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
                # What a check prints, under its own line, not the one before.
                said, skips = io.StringIO(), SKIPS[0]
                try:
                    with contextlib.redirect_stdout(said):
                        passed = bool(predicate())
                except Exception as exc:
                    passed, name = False, f"{name}  ({exc})"
                print(("  FAIL  " if not passed else "  skip  " if SKIPS[0] > skips
                       else "  ok    ") + name)
                sys.stdout.write(said.getvalue())
                failed += not passed
    finally:
        if keep:
            print(f"\nOutput left in {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    return failed


def main():
    parser = argparse.ArgumentParser(
        description="Check LaTeX as a source, end to end.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    parser.add_argument("--case", action="append", default=[],
                        help="run only the cases whose label holds this "
                        "(\"source target\", say); may be given again")
    parallel.add_options(parser)
    arguments = parser.parse_args()
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        sys.exit(f"Pandoc {version} is too old; these tests need 3.9 or "
                 "later, as convert.py does.")
    if arguments.case_index is not None:
        # One case, for a run with them side by side: its lines, and how
        # many failed as the exit status.
        return min(run_cases([CASES[arguments.case_index]], arguments.keep), parallel.MOST)
    cases = [(label, case) for label, case in CASES
             if not arguments.case or any(c in label for c in arguments.case)]
    # A part of a label no case has would run nothing, and pass.
    unmatched = [c for c in arguments.case if not any(c in label for label, _ in CASES)]
    if unmatched:
        sys.exit("no case's label holds " + ", ".join(repr(c) for c in unmatched))
    failed = 0
    # What the machine lacks, said first, as the line a run's list of skips
    # says what to install by: the checks that need it skip, as they do
    # where there's no TeX. The cases side by side are told what TeX lacks.
    # Asked here, whatever the environment says already: only this run's
    # answer is handed on.
    os.environ.pop("LATEX_TESTS_TEX", None)
    unready = tex_unready()
    os.environ["LATEX_TESTS_TEX"] = json.dumps(unready)
    if unready:
        print(f"  skip  the checks that build with TeX: {unready}")
    if why_no_svg():
        print(f"  skip  {why_no_svg()}")
    if arguments.jobs > 1 and len(cases) > 1:
        failed += parallel.run(os.path.abspath(__file__), CASES,
                               {label for label, _ in cases}, arguments.jobs,
                               extra=["--keep"] if arguments.keep else [], first=SLOW)
    else:
        failed += run_cases(cases, arguments.keep)
    print(f"\n{failed} check(s) failed across {len(cases)} case(s)"
          if failed else "\nall LaTeX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
