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


def pdf(path):
    """A one-page PDF holding a blue rectangle, written by hand."""
    stream = b"0 0 1 rg 5 5 30 10 re f\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 20] "
               b"/Contents 4 0 R >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream
               + b"endstream"]
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
        ("alt text holding LaTeX is read as LaTeX",
         lambda: 'alt="50% shaded"' in one),
        ("an image named without its extension is found",
         lambda: 'src="img/square.png"' in one),
        ("and, with no alt key, is reported rather than described as \"image\"",
         lambda: "img/square.png" in missing_alt and 'alt="image"' not in one),
        ("an artifact is decorative",
         lambda: re.search(r'<img src="img/rule\.png"[^>]*alt=""', one)
         and 'aria-hidden="true"' in one),
        ("a drawing LaTeX can't make costs only itself",
         lambda: "1 of the book's 2 drawing(s)" in log
         and os.path.exists(os.path.join(work, "rendered", "ch1", "one-1.svg"))
         if can_draw() else skip("no LaTeX or pdftocairo: drawings not rendered")),
        ("a drawing is rendered whole and keeps its figure's caption",
         lambda: re.search(r'<figure[^>]*>\s*(<div class="center">\s*)?'
                           r'<img src="rendered/ch1/one-1\.svg"', one) and "A line" in one
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
         and "alt={A gray square.}" in one and "alt={A black circle.}" in two
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
         "PDF's, hyperref for its bookmarks, the unused titlesec out, enumitem's settings "
         "taken, the box a division, and \\leavevmode before its formula",
         lambda: "\\DocumentMetadata" in copy("Topic B Two.tex")
         and "\\title{\\textrm{Topic A: The First Topic}}" in tagged
         and "\\usepackage[hidelinks]{hyperref}" in tagged
         and "% book uses none of its commands: \\usepackage{titlesec}" in tagged
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
    in_math = ("\\newcommand{\\grp}[1]{\\begingroup #1\\endgroup}\n"
               "\\newcommand{\\hl}[1]{\\grp{#1}\\hspace{1em}{z}}\n"
               "\\newcommand{\\remark}[1]{\\noindent\\begingroup #1\\endgroup}\n"
               "Text $\\hl{x}$ and \\remark{y}.\n")
    math_kept = latexsource.repair_text(in_math, {}, latexsource.math_macros([in_math]))
    no_macros = latexsource.math_macros(["A formula: $x + 1$, and no macro.\n"])
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
    return [
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
        ("the sample's probe finds each macro's formula by its mark, past one whose "
         "expansion breaks its paragraph", lambda: probed == {"worse"}),
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
    "main.tex": r"""\documentclass{book}
\usepackage{graphicx}
\usepackage{xcolor}
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
\endgroup
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
\newcommand{\secref}[1]{Section~\ref{#1}}
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
$s = 5.5 \hfill R^2 = 70\%$, and
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
""",
    "ch_one/TeX/extra.tex": "\\begin{parts}\n\\item An extra part\n\\end{parts}\n",
    "ch_one/TeX/review.tex": "\\section{Review}\nThe review of chapter one.\n\n"
                             "\\Figure[A green triangle for the review]{0.3}{triangle}\n\n"
                             "\\remark{The variance is never negative.}\n"
                             "\\centering \\begingroup\\itshape A centered italic line.\\endgroup\n\n"
                             "\\eocesol{The solution to the first exercise.}\n",
    # An alt text too long for the pages' liking, of two paragraphs, as
    # OpenIntro writes some.
    "ch_two/TeX/ch_two.tex": "\\chapter{Second chapter}\n\\renewcommand{\\chapterfolder}{ch_two}\n"
                             "\\Figure[A gray star in chapter two, drawn with five points of equal "
                             "length.\n\nIts center filled, the one sample this chapter comes "
                             "back to]{0.5}{star}\n\n"
                             "\\Figuress[A purple hexagon with six equal sides]{2cm}{hexagon}{hexagon}\n\n"
                             "\\includegraphics[alt={The hexagon again, named in capitals}]"
                             "{ch_two/figures/hexagon/HEXAGON.png}\n",
    "ch_two/TeX/review.tex": "\\section{Review two}\nAs \\nameref{ch_one} said, and Figure~"
                             "\\ref{fig:panels} there shows.\n\n\\section{The $t$ distribution}\n"
                             "A heading with a formula in it. See \\nameref{sec:named}, "
                             "\\nameref{fig:panels}, and \\nameref{sec:spread}.\n\n"
                             "\\section{\\nameref{sec:data}}\\label{sec:named}\nNamed.\n",
    "LICENSE.md": "# License\n\nCC BY-SA 3.0.\n",
    "project.yaml": "project:\n  identifier: org.example.custom\n  title: A Custom Book\n",
    "conversion.yaml": "targets:\n  html:\n    format: html\n",
}


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
                 + "  epub:\n    format: epub3\n"
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
        ("a row of the alt text report whose current alt text has a line end in it is "
         "one row, its image named, and every row names an image", lambda: (lambda rows: any(
             row.get("Image") == "ch_two/figures/star/star.png"
             and row.get("Reason", "").startswith("too long") and "\n" in row.get("CurrentAlt", "")
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
        ("a color the book defines is CSS",
         lambda: re.search(r'<span\s+style="color: rgb\(86, 155, 189\)"><strong>A\s+question', one)),
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
        ("a LICENSE.md beside a LaTeX book isn't a page, and a comment in a package list "
         "isn't a package", lambda: not os.path.exists(os.path.join(work, "html", "LICENSE.html"))
         and "%tocloft" not in said),
        ("the PDF built from the pages takes an alt text of two paragraphs, and a formula "
         "in a color the book defines",
         lambda: os.path.exists(os.path.join(work, "pdf", "org.example.custom.pdf"))
         if pdf else skip("no lualatex for the PDF")),
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
         "underline in text, \\textcolor, \\hfill, \\index, and \\vspace in a formula are put "
         "so texmath reads it, as OpenIntro writes them",
         lambda: all(a + "</annotation>" in one for a in (
             "P(\\text{rolling a }\\texttt{1})",
             "\\texttt{income\\_ver}_{\\texttt{verified}}",
             "P(\\underline{{\\color{black}{\\text{mammogram$^+$}}}}\\text{ and has BC})",
             "s = 5.5 \\quad R^2 = 70\\%", "{\\color{oiB}{\\bar{x}}} = 21"))
         and re.search(r'<math display="block"[^>]*>(?:(?!</math>).)*<annotation '
                       r'encoding="application/x-tex">\\begin\{align\*\}\s*x = 1\s*'
                       r'\\end\{align\*\}</annotation>', one, re.S)),
        ("a formula's macro is as the book defines it, so texmath reads it",
         lambda: "x\\hspace{1em}{} = 1</annotation>" in one),
        ("the contents sample names the authors, not the affiliations under each name",
         lambda: __import__("yaml").safe_load(contents_sample or "{}").get(
             "project", {}).get("authors") == ["Ann Lee", "Bo Chen"]),
        ("and every link in it has its target: a label in a heading's braces is a label "
         "LaTeX finds", lambda: "Hyper reference" not in said
         if pdf else skip("no lualatex for the PDF")),
        ("in the EPUB, a link to a figure in another chapter's file names the file, and "
         "a formula in a heading has the navigation document declare MathML", epub_links),
        ("a brace a style file never closes stops the run, which names the file and line",
         lambda: stopped.returncode != 0
         and "style/style.tex:2 (a { that nothing in the file closes)" in told),
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
