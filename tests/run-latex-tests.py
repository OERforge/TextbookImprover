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


def convert(work):
    return subprocess.run(
        ["python3", os.path.join(BIN, "convert.py"), "--quiet"], cwd=work,
        capture_output=True, text=True, stdin=subprocess.DEVNULL)


def read(work, *parts):
    with open(os.path.join(work, *parts), encoding="utf-8") as fh:
        return fh.read()


def epub_links_resolve(work):
    """Every #fragment link in the EPUB names an id one of its files has."""
    import zipfile
    with zipfile.ZipFile(os.path.join(work, "epub", "book.epub")) as z:
        texts = [z.read(n).decode("utf-8") for n in z.namelist()
                 if n.endswith(".xhtml")]
    ids = set()
    for text in texts:
        ids.update(re.findall(r'\sid="([^"]+)"', text))
    targets = set()
    for text in texts:
        targets.update(re.findall(r'href="[^"#]*#([^"]+)"', text))
    return "page-one" in ids and targets and targets <= ids


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


FIG2DEV_PAIR = ("\\begin{picture}(0,0)%\n\\includegraphics{figures/f.png}%\n"
                "\\end{picture}%\n\\setlength{\\unitlength}{3947sp}%\n"
                "\\begin{picture}(600,300)(0,0)\n\\put(0,0){label}\n\\end{picture}%\n")


def case_source(work):
    """The source target: alt text from the sidecar written into the
    author's own files, as keys LaTeX's tagging reads."""
    os.makedirs(os.path.join(work, "figures"))
    png(os.path.join(work, "sq.png"), (128, 128, 128))
    png(os.path.join(work, "figures", "f.png"), (0, 0, 0))
    with open(os.path.join(work, "figures", "f.fig"), "w") as fh:
        fh.write("#FIG 3.2\n")
    with open(os.path.join(work, "figures", "f.tex"), "w") as fh:
        fh.write(FIG2DEV_PAIR)
    source = ("\\documentclass[pdftex,12pt]{article}\n\\usepackage{graphicx}\n"
              "\\usepackage{amsthm}\n\\usepackage[english]{babel}\n\\pdfcompresslevel=9\n"
              "\\newtheorem{thm}{Theorem}\n\\newtheorem*{thm*}{Theorem}\n"
              "\\newcommand{\\suchthat}{\\; \\rule[-3pt]{.5pt}{13pt} \\;}\n"
              "\\begin{document}\n"
              "\\begin{thm*} Unnumbered. \\end{thm*}\n\n"
              "The set $\\{ x \\suchthat x > 0 \\}$.\n\n"
              "\\centerline{\\begin{tabular}{c} a \\\\ \\end{tabular}}\n\n"
              "Inline \\centerline{x} \\newline more.\n\n"
              "\\begin{center}\n\\[ 1! = 1 \\]\net cetera\n\\end{center}\n\n"
              "A square: \\includegraphics[width=1cm]{sq}.\n\n"
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
                 "rendered/figures/f.svg,A figure from xfig\n")
    with open(os.path.join(work, "conversion.yaml"), "w") as fh:
        fh.write("targets:\n  html:\n    format: html\n  fixed:\n    format: source\n"
                 "  tagged:\n    format: source\n    tagging: \"on\"\n"
                 "  kept:\n    format: source\n    latex_definitions: \"off\"\n")
    with open(os.path.join(work, "latex-conversion-macros.tex"), "w", encoding="utf-8") as fh:
        fh.write("% For reading.\n\\renewcommand{\\suchthat}{\\mid}\n")
    before = fingerprint(work)
    convert(work)
    # A person's header decision for the table, from the census's row.
    new = os.path.join(work, "table-headers-new.csv")
    rows = list(csv.DictReader(open(new, encoding="utf-8-sig"))) if os.path.exists(new) else []
    with open(os.path.join(work, "table-headers.csv"), "w", encoding="utf-8") as fh:
        fh.write("key,headers\n" + "".join("%s,first-row\n" % r["key"] for r in rows
                                            if "Name" in r.get("preview", "")))
    before = fingerprint(work, skip_dirs=("fixed", "tagged", "kept", "build"))
    result = convert(work)
    said = result.stdout + result.stderr
    fixed = os.path.join(work, "fixed")
    notes = read(work, "fixed", "notes.tex") \
        if os.path.exists(os.path.join(fixed, "notes.tex")) else ""
    pair = read(work, "fixed", "figures", "f.tex") \
        if os.path.exists(os.path.join(fixed, "figures", "f.tex")) else ""

    tagged = read(work, "tagged", "notes.tex") \
        if os.path.exists(os.path.join(work, "tagged", "notes.tex")) else ""

    def build(tree, engine, text=None):
        """The author's tree with tree laid over it (and notes.tex as text,
        if given), built with engine: (exit status, log)."""
        build = os.path.join(work, "build-" + os.path.basename(tree) + "-" + engine)
        shutil.copytree(work, build, ignore=shutil.ignore_patterns(
            "fixed", "tagged", "kept", "html", "build*", "rendered"))
        shutil.copytree(tree, build, dirs_exist_ok=True)
        if text is not None:
            with open(os.path.join(build, "notes.tex"), "w", encoding="utf-8") as fh:
                fh.write(text)
        done = subprocess.run([engine, "-interaction=nonstopmode", "notes.tex"],
                              cwd=build, capture_output=True, text=True, timeout=300)
        return done.returncode, done.stdout

    def builds_tagged():
        if not shutil.which("lualatex"):
            return skip("no lualatex to build the tagged copy")
        status, log = build(os.path.join(work, "tagged"), "lualatex")
        return status == 0 and "para hooks differ" not in log \
            and "Parent-Child" not in log and "already defined" not in log

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
        ("a comment is left alone",
         lambda: "% \\includegraphics{sq} in a comment" in notes),
        ("the run says which are in files the book's own build makes",
         lambda: "own build" in said and "writes over them" in said),
        ("the author's files are untouched by the source target",
         lambda: fingerprint(work, skip_dirs=("fixed", "tagged", "kept", "build")) == before),
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
         "\\begin{tabular}{cc}" in tagged and tagged.count("\\tagpdfsetup{") == 1),
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
        ("tagging off leaves the book's build alone",
         lambda: "\\DocumentMetadata" not in notes and "pdftex" in notes),
        ("the tagged copy builds with LuaLaTeX, no tagging error or warning", builds_tagged),
        ("and without \\DocumentMetadata it builds with pdfLaTeX", builds_untagged),
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
         ("the source target", case_source), ("the latex target", case_latex_target),
         ("a book too big for TeX", case_capacity)]


def main():
    parser = argparse.ArgumentParser(
        description="Check LaTeX as a source, end to end.")
    parser.add_argument("--keep", action="store_true",
                        help="leave the built output in place")
    arguments = parser.parse_args()
    if shutil.which("pandoc") is None:
        sys.exit("pandoc is not on the path.")
    work = tempfile.mkdtemp(prefix="latex-tests-")
    failed = 0
    try:
        for label, case in CASES:
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
    print(f"\n{failed} check(s) failed across {len(CASES)} case(s)"
          if failed else "\nall LaTeX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
