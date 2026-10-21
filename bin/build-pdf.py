#!/usr/bin/env python3
"""
build-pdf.py -- assemble a book's pages into one tagged PDF.

    build-pdf.py                  # build every pdf target in conversion.yaml
    build-pdf.py --target pdf     # build one of them
    build-pdf.py --keep           # leave book.json and book.tex beside it
    build-pdf.py --latex-only     # write book.json and book.tex, and stop

Reads the filtered intermediates convert.py writes, as the EPUB
assembler does, and places the pages by the same tree (lib/bookassembly.py
does both). Pandoc's LaTeX writer and LuaLaTeX then write the PDF, with
LaTeX's tagging switched on by the PDF/UA standard the target declares.

Three things differ from the EPUB, and each is LaTeX's to do rather than
ours. LaTeX numbers the book: titles carry no numbers, and numbersections
follows the book's numbering setting. A page's role becomes the division
command it came from (\\frontmatter, \\mainmatter, \\appendix,
\\backmatter), written where the role changes. And a contents page that
project.contents generates is \\tableofcontents, where the entry sits.

What the writer can't be told -- row headers, decorative images, a
link's /Contents -- is pdf-target.lua's job, with the macros it needs
written into the header here; a code block in a footnote, which LaTeX
can't read as the footnote's text, is footnote-code.lua's. A source's
own division commands, read
into the roles when the book was converted, are dropped here, where the
roles are written.

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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

try:
    import downsample
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")
from bookassembly import (  # noqa: E402
    INTERMEDIATE, Assembly, load_documents, targets_of, plan_book, load_page,
    page_id, page_title, stringify, wants_title_page,
)
from bookcontents import flatten_pages, is_generated, role_of  # noqa: E402
import highlighting  # noqa: E402
import latexbuild  # noqa: E402
from latexbuild import (  # noqa: E402
    ENGINE, PDF_MACROS as HEADER, UA1_LINKS, is_ua1, label_prefixes, math_setup,
)
import pagefooter  # noqa: E402
import pdfparagraphs  # noqa: E402
import pdfretag  # noqa: E402
from names import safe_stem  # noqa: E402

DIVISIONS = {"front": "\\frontmatter", "main": "\\mainmatter",
             "appendix": "\\appendix", "back": "\\backmatter"}
# The classes Pandoc's LaTeX writer knows to have \frontmatter and its
# kin (frontmatterClasses in Writers/LaTeX.hs, 3.11). In any other the
# roles write only \appendix.
FRONTMATTER_CLASSES = ("memoir", "book", "scrbook", "extbook", "tufte-book",
                       "ctexbook", "elegantbook")
# The classes Pandoc's LaTeX writer knows to have chapters (chaptersClasses in
# Writers/LaTeX.hs, 3.12.1), where a top-level heading is a \chapter.
CHAPTER_CLASSES = ("memoir", "book", "report", "scrreprt", "scrreport", "scrbook",
                   "extreport", "extbook", "tufte-book", "ctexrep", "ctexbook",
                   "elegantbook")
# Pandoc's template brackets the title and contents with \frontmatter and
# \mainmatter and puts \backmatter after the body, so a front page in
# the body would begin the front matter a second time and number its
# pages from i again. The template's are switched off (has-frontmatter),
# and the book opens in the front matter here instead; the roles say the
# rest.
OPEN_FRONT = "\\AddToHook{begindocument/end}{\\frontmatter}\n"

# The page every book's PDF has unless its pdf.metadata file says
# otherwise, a field at a time, or it's a LaTeX book, whose own layout it
# keeps (book_layout): Pandoc's LaTeX variables, and ragged-right.
DEFAULT_LAYOUT = os.path.join(HERE, "pdf-layout.yaml")
# The classes whose type sizes are 10pt, 11pt, and 12pt alone, as their
# options: another size goes to KOMA-Script's scrextend, which sets it for
# any class, with the sizes of the class's other type, its space around a
# display formula, a float, and a footnote, and its lists' spacing. Its
# one check of another package, that \@footnotemark is still LaTeX's own,
# is for an option of its own nothing here uses, and LaTeX's tagging
# changes \@footnotemark, so it would warn on every build: it's skipped.
# What it leaves, the class set at the size it loaded with: a list's
# indents and its label's space (book.cls, in ems), the space above a
# page's first line (\topskip, the type's size), and a paragraph's indent,
# which are set again as the class sets them, at this size. parskip, which
# Pandoc's template loads before, set the space between paragraphs from
# the class's size (half a line), and the lists' spacing to match, none
# above a list or between its items but that, which scrextend replaced
# with its own: at 13.5pt, a list had 14 points more above it and below
# it than a paragraph, and its items were indented as at 10pt. Both are
# set again as parskip sets them.
STANDARD_CLASSES = ("book", "report", "article")
CLASS_SIZES = ("10pt", "11pt", "12pt")
TYPE_SIZE = re.compile(r"\d+(?:\.\d+)?pt", re.I)
SIZE_PACKAGE = ("\\makeatletter\\let\\OER@CheckCommand\\CheckCommand"
                "\\let\\CheckCommand\\providecommand\n"
                "\\RequirePackage[fontsize=%s]{scrextend}\n"
                "\\let\\CheckCommand\\OER@CheckCommand\n"
                "\\if@twocolumn\\leftmargini2em\\leftmarginv.5em\\leftmarginvi.5em"
                "\\ifdim\\parindent>\\z@\\parindent1em\\fi\n"
                "\\else\\leftmargini2.5em\\leftmarginv1em\\leftmarginvi1em"
                "\\ifdim\\parindent>\\z@\\parindent1.5em\\fi\\fi\n"
                "\\leftmarginii2.2em\\leftmarginiii1.87em\\leftmarginiv1.7em\\labelsep.5em\n"
                "\\labelwidth\\leftmargini\\advance\\labelwidth-\\labelsep"
                "\\tabbingsep\\labelsep\n"
                "\\topskip\\f@size\\p@\\maxdepth.5\\topskip\n"
                "\\@ifpackageloaded{parskip}{\\parskip=.5\\baselineskip plus 2pt\\relax\n"
                "\\def\\@listI{\\leftmargin\\leftmargini\\topsep\\z@\\parsep\\parskip\\itemsep\\z@}"
                "\\let\\@listi\\@listI\\@listi\n"
                "\\def\\@listii{\\leftmargin\\leftmarginii\\labelwidth\\leftmarginii"
                "\\advance\\labelwidth-\\labelsep\\topsep\\z@\\parsep\\parskip\\itemsep\\z@}\n"
                "\\def\\@listiii{\\leftmargin\\leftmarginiii\\labelwidth\\leftmarginiii"
                "\\advance\\labelwidth-\\labelsep\\topsep\\z@\\parsep\\parskip\\itemsep\\z@}\n"
                "\\partopsep\\z@}{}\\makeatother\n")
# Ragged right, breaking no word at a line's end: the right margin given
# all the stretch, as LaTeX's \raggedright gives it, from the start of the
# text and in what LaTeX sets apart from it, a footnote, a float's
# caption, a minipage, each of which begins by setting its lines justified
# again (\@parboxrestore). Not \raggedright itself, whose \\ ends the
# paragraph: LaTeX's tagging made a line break's two lines two paragraphs,
# and a caption's line break, set in a box first, stopped LaTeX ("Not
# allowed in LR mode"). ragged2e's \RaggedRight hyphenates. And without
# microtype's font expansion, which draws a line's letters up to 2%
# narrower or wider to justify it, and which a ragged line, which needs
# none, used to fit more on it: in the PDF suite's footer book, a
# caption's lines had been drawn at 11.75 points of 11.96, and a
# footnote's at 9.77 of 9.96.
RAGGED_RIGHT = ("\\makeatletter\n"
                "\\AtBeginDocument{\\@rightskip\\@flushglue\\rightskip\\@rightskip}\n"
                "\\g@addto@macro\\@parboxrestore{\\@rightskip\\@flushglue\\rightskip\\@rightskip}\n"
                "\\ifdefined\\microtypesetup\\microtypesetup{expansion=false}\\fi\n"
                "\\makeatother\n")
# Room for a page number of four digits, as a book of a thousand pages
# has, in the contents and a list of figures: the standard classes leave
# 1.55em, three digits' room, and a fourth ran into the margin (62 lines
# of Sociology's contents in 13.5pt type), or over a chapter's title.
PAGE_NUMBER_ROOM = ("\\makeatletter\\ifdefined\\@pnumwidth"
                    "\\def\\@pnumwidth{2.5em}\\def\\@tocrmarg{3.5em}\\fi\\makeatother\n")
# A metadata file's own LaTeX that sets what the page's geometry or
# linestretch would: loading geometry, and loading setspace or setting the
# line spacing (book_metadata).
OWN_GEOMETRY = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*"
                          r"\{[^}]*\bgeometry\b")
OWN_SPACING = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*"
                         r"\{[^}]*\bsetspace\b|\\(?:linespread|setstretch|onehalfspacing"
                         r"|doublespacing|singlespacing)(?![A-Za-z@])")

# Latin Modern, the template's fonts when none is chosen, has no Greek and
# few mathematical symbols, and a character its font lacks is drawn blank
# (.notdef): gone from the page and from the text a screen reader gets. A
# book that uses them as text (a statistics book's mu, sigma, and
# less-than-or-equal) loses them. Latin Modern Math has them, so it fills
# in for each of the three families, and for a face the metadata file
# names for one, unless the file gives the face fallbacks of its own
# (Pandoc's mainfontfallback, say): Noto Sans, an OpenStax book's face,
# has no less-than-or-equal either. What it can't supply is reported
# after the build, because veraPDF catches only some of it: a character
# an equation falls back to one of LaTeX's older math fonts for is
# dropped with no trace at all.
# DejaVu Sans comes after it when it's installed, as it is with most Linux
# desktops: it has what Latin Modern Math doesn't, such as the circled
# digits an AsciiDoc book's code callouts are (58 of them in the security
# textbook, all drawn blank without it). New Computer Modern's math font
# comes last when it's installed, as it is wherever decks are built: it has
# the circled letters OpenStax's math books letter a question's parts with
# (1,391 in the first chapter of College Algebra), which neither has.
FALLBACK = ("\\def\\OERFallbackFonts{\"Latin Modern Math:mode=harf;\"}\n"
            "\\IfFontExistsTF{DejaVu Sans}\n"
            "  {\\edef\\OERFallbackFonts{\\OERFallbackFonts, "
            "\"DejaVu Sans:mode=harf;\"}}{}\n"
            "\\IfFontExistsTF{NewCMMath-Book.otf}\n"
            "  {\\edef\\OERFallbackFonts{\\OERFallbackFonts, "
            "\"NewCMMath-Book.otf:mode=harf;\"}}{}\n"
            "\\directlua{luaotfload.add_fallback(\"oerfallback\", "
            "{\\OERFallbackFonts})}\n")
FAMILIES = (("mainfont", "\\setmainfont", "Latin Modern Roman"),
            ("sansfont", "\\setsansfont", "Latin Modern Sans"),
            ("monofont", "\\setmonofont", "Latin Modern Mono"))

# Where figures go (pdf.figures). LaTeX's tagging gathers the tags of a
# figure that floats into one place: at the end of the document unless
# told to flush them, which it does when a section begins (the float/flush
# key of latex-lab-testphase-float.sty). A figure placed H doesn't float,
# so its tags stay where the text has it.
FIGURE_PLACEMENT = {
    "in_place": "\\usepackage{float}\\floatplacement{figure}{H}\n",
    "section": ("\\usepackage[section]{placeins}\n"
                "\\ifdefined\\tagpdfsetup\n"
                "  \\AddToHook{cmd/section/before}{\\tagpdfsetup{float/flush=section}}\n"
                "  \\AddToHook{cmd/chapter/before}{\\tagpdfsetup{float/flush=chapter}}\n"
                "\\fi\n"),
    "float": "",
}

# A running head no wider than the line leaves beside the page number: the
# book class sets a chapter's or section's title there in one line, however
# long, and FINC 308's longest titles ran into the number and off the
# page's edge. A longer one is scaled down to fit. Wrapped around the
# kernel's mark commands, which every chapter and section mark goes
# through, whatever the class; a copy (\NewCommandCopy), since they're
# robust. An empty mark stays empty, as the kernel tells them apart
# (2e-right-nonempty). The head is an artifact, so its text is the
# reader's no matter its size.
RUNNING_HEADS = r"""\RequirePackage{graphicx}
\makeatletter
\newsavebox\oer@headbox
\DeclareRobustCommand\oerfithead[1]{%
  \sbox\oer@headbox{#1}%
  \ifdim\wd\oer@headbox>\dimexpr\textwidth-3em\relax
    \resizebox{\dimexpr\textwidth-3em\relax}{!}{\usebox\oer@headbox}%
  \else\usebox\oer@headbox\fi}
\NewCommandCopy\oer@markboth\markboth
\NewCommandCopy\oer@markright\markright
\ExplSyntaxOn
\cs_new:Npn \__oer_fit_mark:n #1
  { \tl_if_blank:nF {#1} { \exp_not:n { \oerfithead {#1} } } }
\DeclareRobustCommand*\markboth[2]
  { \exp_args:Nee \oer@markboth { \__oer_fit_mark:n {#1} } { \__oer_fit_mark:n {#2} } }
\DeclareRobustCommand*\markright[1]
  { \exp_args:Ne \oer@markright { \__oer_fit_mark:n {#1} } }
\ExplSyntaxOff
\makeatother
"""


def svg_images(blocks):
    """The SVG images the book holds."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Image" and node["c"][2][0].lower().split("?")[0].endswith(".svg"):
                found.append(node["c"][2][0])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(blocks)
    return found


def latex_problem():
    """Why the LuaLaTeX on the path can't tag a PDF, or None."""
    return latexbuild.latex_problem(lambda m: print(m, file=sys.stderr))


def raw_latex(text):
    return {"t": "RawBlock", "c": ["latex", text]}


# Where a file of the latex target begins, in the LaTeX the writer gives:
# a name, or none for what the master keeps.
FILE_MARK = "%%TextbookImproverFile:%s"
FILE_MARK_LINE = re.compile(r"^%TextbookImproverFile:(\S*)\n", re.M)


def split_book(text):
    """The writer's one file as a master and a file per top-level entry:
    (master, {name: body}). The master keeps the preamble, what stands
    between the entries (division commands, the contents), and an
    \\include for each file, in its place."""
    files, master, last, current = {}, [], 0, None
    for m in FILE_MARK_LINE.finditer(text):
        piece = text[last:m.start()]
        if current:
            files[current] = files.get(current, "") + piece
        else:
            master.append(piece)
        current = m.group(1) or None
        if current:
            master.append("\\include{%s}\n" % current)
        last = m.end()
    end = text.rfind("\\end{document}")
    if current and end > last:
        files[current] = files.get(current, "") + text[last:end]
        master.append(text[end:])
    else:
        master.append(text[last:])
    return "".join(master), files


def svg_to_pdf(blocks, base, out_dir):
    """Each SVG image made a PDF beside where it goes in out_dir, with
    rsvg-convert as Pandoc's own PDF route does, and the image pointed at
    it: the LaTeX writer gives an SVG \\includesvg, which needs Inkscape
    and takes no alt text. Returns how many, and the SVGs it couldn't."""
    made, failed = [0], []

    def walk(value):
        if isinstance(value, dict):
            if value.get("t") == "Image":
                target = value["c"][2]
                src = target[0]
                if src.lower().endswith(".svg") and "://" not in src:
                    pdf = os.path.splitext(src)[0] + ".pdf"
                    out = os.path.join(out_dir, pdf)
                    os.makedirs(os.path.dirname(out) or out_dir, exist_ok=True)
                    done = subprocess.run(["rsvg-convert", "-f", "pdf", "-o", out,
                                           os.path.join(base, src)],
                                          capture_output=True) \
                        if shutil.which("rsvg-convert") else None
                    if done is not None and done.returncode == 0:
                        target[0] = pdf
                        made[0] += 1
                    else:
                        failed.append(src)
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(blocks)
    return made[0], failed


def copy_images(blocks, base, out_dir):
    """Every local image the book shows, copied to out_dir at its own
    relative path, so the folder builds on its own. Returns how many."""
    count = [0]

    def walk(value):
        if isinstance(value, dict):
            if value.get("t") == "Image":
                src = value["c"][2][0]
                source = os.path.join(base, src)
                out = os.path.join(out_dir, src)
                if "://" not in src and os.path.isfile(source) \
                        and not os.path.exists(out):
                    os.makedirs(os.path.dirname(out) or out_dir, exist_ok=True)
                    shutil.copy(source, out)
                    count[0] += 1
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(blocks)
    return count[0]


def is_division(block):
    return (block.get("t") == "RawBlock"
            and block["c"][0] in ("latex", "tex")
            and " ".join(block["c"][1].split()) in DIVISIONS.values())


class PdfAssembly(Assembly):
    """The book as LaTeX wants it: numbers and the contents are LaTeX's,
    and a role is a division command."""

    def __init__(self, *args, title_page=None, book_title="",
                 divisions=True, toc_depth=2, mark_files=False, contents=True, **kwargs):
        super().__init__(*args, **kwargs)
        # The book opens in the front matter (OPEN_FRONT): its title
        # page, and the contents when the template places them.
        self.division = "front"
        self.divisions = divisions
        self.toc_depth = toc_depth
        self.toc_placed = False
        # Whether the book has a contents page: not when the metadata
        # file says toc: false, which a generated contents page in
        # project.contents gives way to too (toc_dropped).
        self.contents = contents
        self.toc_dropped = False
        # The page made from the metadata file, when its title is the
        # book's: that title is the title block LaTeX draws, so the page
        # gets no heading of its own. A page whose title is its own --
        # a lone heading promoted to the title -- keeps it.
        self.title_page = title_page
        self.book_title = book_title
        self.mark_files = mark_files
        self.file_names = set()

    def add_page(self, stem, title_override, depth, heading=True,
                 number=None):
        if stem == self.title_page and self.book_title and \
                page_title(load_page(self.base, stem), stem) == self.book_title:
            heading = False
        start = len(self.blocks)
        super().add_page(stem, title_override, depth, heading=heading,
                         number=number)
        # The source's own division commands were read into the roles
        # when the book was converted, and before_entry writes them from
        # the roles; the copies in the page would say them twice.
        self.blocks[start:] = [b for b in self.blocks[start:]
                               if not is_division(b)]

    def before_entry(self, entry, depth):
        # For the latex target, each top-level entry is a file of its own,
        # and what comes between them (a division command, the contents)
        # stays in the master; marks say which is which.
        if depth == 1 and self.mark_files:
            self.blocks.append(raw_latex(FILE_MARK % ""))
        self._division(entry, depth)
        if depth == 1 and self.mark_files and not is_generated(entry):
            self.blocks.append(raw_latex(FILE_MARK % self.file_name(entry)))

    def file_name(self, entry):
        """A top-level entry's file, without .tex: a page's own stem, a
        group's first page's, or its title's; never two the same."""
        kind, a, b = entry
        stem = a if kind == "page" else next(
            (s for s in flatten_pages([entry]) if s), safe_stem(a) or "part")
        stem = safe_stem(stem) or "part"
        name, n = stem, 2
        while name in self.file_names:
            name, n = f"{stem}-{n}", n + 1
        self.file_names.add(name)
        return name

    def _division(self, entry, depth):
        # A generated contents page belongs to whatever division it sits
        # in; it has no role of its own to change it.
        if depth != 1 or is_generated(entry):
            return
        role = role_of(entry)
        if role == self.division:
            return
        if self.divisions or role == "appendix":
            self.blocks.append(raw_latex(DIVISIONS[role]))
        self.division = role

    def add_generated(self, entry, depth):
        if entry.generate == "toc" and not self.contents:
            self.toc_dropped = True
        elif entry.generate == "toc":
            # As the template writes it, depth and all.
            self.blocks.append(raw_latex(
                f"{{\\setcounter{{tocdepth}}{{{self.toc_depth}}}"
                "\\tableofcontents}"))
            self.toc_placed = True


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------

def meta_string(text):
    return {"t": "MetaString", "c": str(text)}


def meta_bool(value):
    return {"t": "MetaBool", "c": bool(value)}


def metadata_file(base, setting):
    """The metadata of the file pdf.metadata names, as Pandoc reads it."""
    # Whole, since Pandoc runs in the book's folder: a path relative to a
    # folder given relative to where the build runs (-d book) had Pandoc
    # look for book/book/meta.yaml.
    path = os.path.abspath(os.path.join(base, setting))
    if not os.path.isfile(path):
        sys.exit(f"pdf.metadata is set to {setting}, which does not exist "
                 f"(looked at {path}).")
    if path.lower().endswith((".yaml", ".yml")):
        command = ["pandoc", "-f", "markdown", "-t", "json",
                   "--metadata-file", path]
        stdin = ""
    else:
        command = ["pandoc", "-f", "markdown", "-t", "json", path]
        stdin = None
    result = subprocess.run(command, input=stdin, capture_output=True,
                            text=True, cwd=base)
    if result.returncode != 0:
        sys.exit(f"pandoc could not read {path}:\n{result.stderr}")
    return json.loads(result.stdout).get("meta", {})


def book_metadata(project, resolved, base, numbered):
    """project.yaml's facts, then this target's settings, then whatever
    the metadata file says, which wins."""
    meta = {"title": meta_string(project["title"]),
            "lang": meta_string(project["language"]),
            # Inlines, not a MetaString: the writer decides whether the
            # class has chapters from stringify of this field, and
            # stringify finds no text in a MetaString (Shared.hs), so the
            # template would write \documentclass{book} over headings one
            # level too low.
            "documentclass": {"t": "MetaInlines",
                              "c": [{"t": "Str", "c": "book"}]}}
    authors = [str(a) for a in (project.get("authors") or []) if str(a)]
    if authors:
        meta["author"] = {"t": "MetaList",
                          "c": [meta_string(a) for a in authors]}
    standards = [str(s) for s in (resolved["pdf.standard"] or []) if str(s)]
    if standards:
        meta["pdfstandard"] = {"t": "MetaList",
                               "c": [meta_string(s) for s in standards]}
    meta["numbersections"] = meta_bool(numbered)
    meta["toc"] = meta_bool(True)
    # A LaTeX book's own layout, as its preamble gives it (latex_book):
    # its type size, paper, margins, line spacing, and paragraph indents,
    # where the default page would have its own. Any other book's is the
    # default page (pdf-layout.yaml). The metadata file still wins, a
    # field at a time, and the run says what of a LaTeX book's layout is
    # left.
    layout, colors = latex_book(base, resolved)
    if layout is None:
        if not os.path.isfile(DEFAULT_LAYOUT):
            sys.exit(f"The PDF target's default page, {DEFAULT_LAYOUT}, is missing; it comes "
                     "with TextbookImprover, and docs/configuration.md shows it whole.")
        page = metadata_file(HERE, DEFAULT_LAYOUT)
    else:
        page = {key: meta_value(value) for key, value in layout.items()}
    setting = str(resolved["pdf.metadata"] or "").strip()
    own = metadata_file(base, setting) if setting else {}
    # A type size or a paper the metadata file gives as a class option is
    # its choice, as its own fontsize or papersize would be, and replaces
    # the page's: the book class takes its options in the order it
    # declares them, not the order they're given, so the default's 12pt
    # had won over a file's 11pt, and its Letter over a file's a4paper. A
    # standard class takes 10pt, 11pt, and 12pt alone and ignores another
    # size, so there the option is the file's fontsize, set as one is
    # (scrextend, below).
    options = [o.strip() for o in
               ",".join(meta_plain(o) for o in meta_items(own.get("classoption"))).split(",")
               if o.strip()]
    sizes = [class_option_size(o) for o in options if class_option_size(o)]
    if "fontsize" not in own and sizes:
        if (meta_plain(own.get("documentclass")) or document_class(meta)) in STANDARD_CLASSES:
            own["fontsize"] = meta_string(sizes[-1])
            own["classoption"] = {"t": "MetaList", "c": [meta_string(o) for o in options
                                                         if not class_option_size(o)]}
        else:
            page.pop("fontsize", None)
    if "papersize" not in own and any(o.lower().endswith("paper")
                                      or o.lower().startswith("paper=") for o in options):
        page.pop("papersize", None)
    # And margins or line spacing the file's own LaTeX sets, which the
    # page's fields would load geometry or setspace for first: loaded
    # again with options of the file's, either stopped LaTeX ("Option
    # clash for package geometry"), and a spacing the file set was undone
    # by the page's \setstretch, which comes after it.
    own_tex = raw_tex(own.get("header-includes"))
    if "geometry" not in own and OWN_GEOMETRY.search(own_tex):
        page.pop("geometry", None)
    if "linestretch" not in own and OWN_SPACING.search(own_tex):
        page.pop("linestretch", None)
    meta.update(page)
    meta.update(own)
    if layout:
        carried = layout_words({k: v for k, v in layout.items()
                                if meta.get(k) == meta_value(v)})
        if carried:
            print("The LaTeX book's own layout, from its preamble: "
                  + "; ".join(carried) + ".", file=sys.stderr)
    if "toc-depth" not in meta:
        # pdf.toc_depth counts levels as the EPUB's contents do, an entry at
        # the top of project.contents being level 1, and the template hands
        # toc-depth to LaTeX's tocdepth, which counts a chapter as 0. So a
        # class with chapters takes one less, as Pandoc's writer gives its
        # own --toc-depth (Writers/LaTeX.hs), which a field set here skips:
        # at 2 a book's contents and bookmarks went three levels deep, a
        # page's subsections too (1,030 entries in Sociology's, 24 pages,
        # where its EPUB's contents have the 295 of two levels).
        depth = int(resolved["pdf.toc_depth"])
        if document_class(meta) in CHAPTER_CLASSES:
            depth -= 1
        meta["toc-depth"] = meta_string(depth)
    # Ours come after the author's, so the author's packages are loaded
    # first, but for a type size and the contents' depth, which come before
    # them; a list either way.
    includes = meta.get("header-includes")
    if includes is None:
        includes = {"t": "MetaList", "c": []}
    elif includes.get("t") != "MetaList":
        includes = {"t": "MetaList", "c": [includes]}
    # The bookmarks go as deep as LaTeX's tocdepth when each is written
    # (hyperref's bookmarksdepth, unset), and Pandoc's template sets it
    # only where it writes the contents, inside $if(toc)$, as build-pdf's
    # own contents page does where project.contents places it: with toc:
    # false the class's own depth stood, and the bookmarks went a level
    # deeper than pdf.toc_depth says. Set from the start, ahead of the
    # author's LaTeX, which can still set its own; the contents set it
    # again to the same.
    depth = meta_plain(meta.get("toc-depth"))
    if re.fullmatch(r"-?\d+", depth):
        includes["c"].insert(0, {"t": "MetaBlocks", "c": [
            raw_latex("\\setcounter{tocdepth}{%s}\n" % depth)]})
    # The standards in effect, the metadata file's if it set them.
    claimed = meta.get("pdfstandard")
    claimed = [meta_plain(c) for c in claimed["c"]] if claimed and claimed.get("t") == "MetaList" \
        else ([meta_plain(claimed)] if claimed else [])
    ours = ("\\ifdefined\\tagpdfsetup\n  \\tagpdfsetup{math/setup={%s}}\n\\fi\n"
            % math_setup(claimed, str(resolved["pdf.ua1_math"]))) + HEADER
    if is_ua1(claimed):
        # LaTeX's own links, a footnote's mark among them, get no /Contents,
        # which PDF/UA-1 requires of every link (7.18.5); a footnote mark
        # isn't made a link. (The template loads hyperref after this.)
        ours += "\\PassOptionsToPackage{hyperfootnotes=false}{hyperref}\n" + UA1_LINKS
    ours += FIGURE_PLACEMENT[str(resolved["pdf.figures"])]
    ours += RUNNING_HEADS
    # A type size the class doesn't have, whose option the class would
    # ignore, leaving the type 10pt: set through scrextend, ahead of the
    # author's packages, as the class's option would be. In lowercase, as
    # the class names its options, which it matches letter for letter:
    # 12PT had left the type 10pt.
    size = meta_plain(meta.get("fontsize")).replace(" ", "").lower()
    if TYPE_SIZE.fullmatch(size):
        meta["fontsize"] = meta_string(size)
    if document_class(meta) in STANDARD_CLASSES and TYPE_SIZE.fullmatch(size) \
            and size not in CLASS_SIZES:
        del meta["fontsize"]
        includes["c"].insert(0, {"t": "MetaBlocks", "c": [raw_latex(SIZE_PACKAGE % size)]})
    if document_class(meta) in STANDARD_CLASSES:
        ours += PAGE_NUMBER_ROOM
    # Ragged right, as the default page has it, unless the metadata file
    # says false.
    if meta_truth(meta.pop("ragged-right", None)):
        ours += RAGGED_RIGHT
    # The footer setting at the foot of every page, its words alone
    # (pagefooter: LaTeX's tagging marks the foot an artifact).
    ours += pagefooter.latex_preamble(resolved["footer"], base)
    # The template loads amssymb before unicode-math, which leaves the
    # names unicode-math lacks drawn as control characters.
    ours += "\\ifdefined\\directlua\n" + latexbuild.UM_ALIASES + "\\fi\n"
    # A highlighted code block's spaces as characters (Pandoc's macros come
    # before these, and define Highlighting when there's highlighted code).
    ours += ("\\ifdefined\\directlua\\ifdefined\\Highlighting\n" + latexbuild.CODE_SPACES
             + "\\fi\\fi\n")
    # A LaTeX book's own colors (latex_book): a formula keeps its TeX as
    # the book wrote it, \color{redcards} and all, and LaTeX stops on a
    # color nothing defines (OpenIntro Statistics).
    if colors:
        ours += ("\\RequirePackage{xcolor}\n\\makeatletter\n"
                 + "\n".join(guarded_color(c) for c in colors)
                 + "\n\\makeatother\n")
    faces = []
    for field, command, default in FAMILIES:
        if field not in meta:
            faces.append(f"{command}{{{default}}}[RawFeature={{fallback=oerfallback}}]\n")
        elif field + "fallback" not in meta and meta_plain(meta[field]):
            # Set again, as the template set it, with the fallbacks: for
            # the text's face, babel's too, which the template gives the
            # language the book is in, and which is the one the text gets.
            given = meta.get(field + "options")
            given = given["c"] if given and given.get("t") == "MetaList" \
                else [given] if given else []
            options = ",".join([meta_plain(o) for o in given if meta_plain(o)]
                               + ["RawFeature={fallback=oerfallback}"])
            name = meta_plain(meta[field])
            faces.append(f"{command}{{{name}}}[{options}]\n")
            if field == "mainfont":
                faces.append(f"\\ifdefined\\babelfont\\babelfont{{rm}}[{options}]{{{name}}}\\fi\n")
    if faces:
        ours += FALLBACK + "".join(faces)
    if document_class(meta) in FRONTMATTER_CLASSES:
        meta["has-frontmatter"] = meta_bool(False)
        ours += OPEN_FRONT
    # A heading below a subsection is run in to the text that follows it in
    # the standard classes, and one followed by another heading instead, as
    # a page that opens with nested headings and no text between them is,
    # leaves LaTeX's paragraph tagging one paragraph short: "The number of
    # automatic begin (7286) and end (7285)" in DCIC, which stopped its PDF.
    # The template's block-headings puts each such heading on its own line,
    # and a metadata file can still say otherwise.
    if "block-headings" not in meta:
        meta["block-headings"] = meta_bool(True)
    includes["c"].append({"t": "MetaBlocks", "c": [raw_latex(ours)]})
    meta["header-includes"] = includes
    return meta


COLORLET = re.compile(r"\\colorlet\s*(?:\[[^]]*\])?\s*\{[^{}]*\}\s*(?:\[[^]]*\])?"
                      r"\s*\{([^{}]*)\}")


def guarded_color(statement):
    """A book's color statement for the PDF from its pages, a \\colorlet
    made only when each color it's made of is defined: one a book defines
    in a style file of its own isn't among the statements convert.py
    passes on, and xcolor stopped on it ("Undefined color `brand'") where
    the book itself builds."""
    m = COLORLET.match(statement.strip())
    if not m:
        return statement
    names = [p.strip().lstrip("-") for p in m.group(1).split("!")]
    for name in reversed([n for n in names if n and not re.fullmatch(r"[\d.]+", n)]):
        statement = "\\@ifundefinedcolor{%s}{}{%s}" % (name, statement)
    return statement


def meta_value(value):
    """A JSON value as Pandoc's metadata: a list, a flag, or a string."""
    if isinstance(value, list):
        return {"t": "MetaList", "c": [meta_value(v) for v in value]}
    if isinstance(value, bool):
        return meta_bool(value)
    return meta_string(value)


def latex_book(base, resolved):
    """A LaTeX book's own page and colors: (the layout its preamble gives
    its pages, as Pandoc's variables, {} when it says nothing of them, or
    None for a book of any other source; its color statements, a line
    each). convert.py passes them (BOOK_LATEX_LAYOUT, JSON, and
    BOOK_LATEX_COLORS); run on its own, --latex-only say, the script
    read neither, and wrote the default page and none of the book's
    colors, on which LaTeX can stop. So it reads them as convert.py does,
    from the masters latex.main chooses (latexsource.book_page)."""
    text = os.environ.get("BOOK_LATEX_LAYOUT")
    if text is not None:
        try:
            layout = json.loads(text or "{}")
        except ValueError:
            layout = {}
        return (layout if isinstance(layout, dict) else {},
                [c for c in os.environ.get("BOOK_LATEX_COLORS", "").splitlines()
                 if c.strip()])
    import latexsource
    main = [str(entry).strip() for entry in (resolved["latex.main"] or [])
            if str(entry).strip()]
    try:
        masters, _ = latexsource.chosen_masters(base, main)
        pages = [latexsource.book_page(base, master) for master in masters]
    except OSError:
        pages = []
    if not pages:
        return None, []
    colors = []
    for _, statements in pages:
        for statement in statements:
            if statement not in colors:
                colors.append(statement)
    # A statement a line, as convert.py passes them.
    return pages[0][0], [" ".join(c.split()) for c in colors]


def layout_words(layout):
    """What a book's layout carries over, in words, for the log."""
    words = []
    if layout.get("fontsize"):
        words.append(f"{layout['fontsize']} type")
    if layout.get("papersize"):
        words.append(f"{layout['papersize']} paper")
    if layout.get("geometry"):
        words.append("geometry's " + ", ".join(layout["geometry"]))
    options = layout.get("classoption") or []
    sides = [o for o in options if o not in ("dvipsnames", "svgnames", "x11names")]
    if sides:
        words.append(", ".join(sides))
    if len(sides) < len(options):
        words.append("xcolor's " + ", ".join(o for o in options if o not in sides)
                     + " colors")
    if layout.get("linestretch"):
        words.append(f"line spacing {layout['linestretch']}")
    if layout.get("indent"):
        words.append("indented paragraphs")
    return words


def meta_items(value):
    """A metadata field's items: a list's, or the field itself, or none."""
    if not value:
        return []
    return value["c"] if value.get("t") == "MetaList" else [value]


def class_option_size(option):
    """The type size a class option names, 13.5pt or KOMA-Script's
    fontsize=13.5pt, in lowercase, or None."""
    size = option.replace(" ", "").lower()
    if size.startswith("fontsize="):
        size = size[len("fontsize="):]
    return size if TYPE_SIZE.fullmatch(size) else None


def raw_tex(value):
    """The LaTeX a metadata field holds as raw TeX, or as a string, its
    comments left out."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") in ("RawBlock", "RawInline") and isinstance(node.get("c"), list):
                if str(node["c"][0]).lower() in ("latex", "tex"):
                    found.append(str(node["c"][1]))
                return
            if node.get("t") == "MetaString":
                found.append(str(node.get("c", "")))
                return
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    return "\n".join(re.sub(r"(?<!\\)%.*", "", line)
                     for text in found for line in text.splitlines())


def meta_plain(value):
    """A metadata field's text, whichever form it has."""
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return " ".join(str(value["c"]).split())
    return " ".join(stringify(value.get("c", [])).split())


def document_class(meta):
    return meta_plain(meta.get("documentclass"))


def meta_truth(value):
    """Whether a metadata field is set true: YAML's true, or a word that
    says so."""
    if not value:
        return False
    if value.get("t") == "MetaBool":
        return bool(value["c"])
    return meta_plain(value).lower() in ("true", "yes", "on")


def count_math(blocks):
    """How many equations the book holds."""
    found = [0]

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Math":
                found[0] += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(blocks)
    return found[0]


def captioned_tables(blocks):
    """For each table in the book, in order, whether it has a caption. Not
    a layout table, which pdf-target.lua tags as a division of paragraphs,
    so the PDF has no Table for it; a table inside one is a table."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Table" and not any(
                    k == "role" and v in ("presentation", "none")
                    for k, v in node["c"][0][2]):
                found.append(bool(node["c"][1][1]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(blocks)
    return found


def repair(path, resolved, blocks):
    """The repairs after LaTeX that the target's settings ask for, on a
    tagged PDF. One built to no PDF/UA standard isn't tagged, so has no
    tags to repair; the retagging had stopped the run on it."""
    if not pdfretag.tagged(path):
        return
    if resolved["pdf.repair_captions"]:
        repair_tables(path, blocks)
    if resolved["pdf.remove_empty_paragraphs"]:
        remove_empty_paragraphs(path)


def repair_tables(path, blocks):
    """pdf.repair_captions, after LaTeX: see lib/pdfretag.py."""
    if pdfretag.pikepdf is None:
        return
    captioned = captioned_tables(blocks)
    counts = pdfretag.retag(path, captioned)
    if not counts["matched"]:
        print(f"WARNING: the PDF's tables don't line up with the book's "
              f"{len(captioned)}, so no caption was retagged.", file=sys.stderr)
        return
    print(f"Table captions retagged: {counts['captions']} of "
          f"{sum(captioned)}; {counts['artifacts']} empty repeated head(s) "
          "taken out of their tables"
          + (f", {counts['artifacts_left']} with content left in"
             if counts["artifacts_left"] else "") + ".", file=sys.stderr)


def remove_empty_paragraphs(path):
    """pdf.remove_empty_paragraphs, after the captions: see
    lib/pdfparagraphs.py."""
    count = pdfparagraphs.remove_from(path)
    if count is None:
        print("WARNING: the PDF's parent tree isn't the flat array LaTeX "
              "writes, so its empty paragraph elements were left.", file=sys.stderr)
    else:
        print(f"Empty paragraph elements removed: {count}.", file=sys.stderr)


def output_name(resolved, project, target):
    """<identifier>.pdf unless the target names a file. The extension is
    added to a filename given without one, and always to an identifier,
    which may end in anything (org.example.pdf is a fine identifier)."""
    name = str(resolved["filename"] or "").strip()
    if name:
        return name if name.lower().endswith(".pdf") else name + ".pdf"
    return (project["identifier"] or target) + ".pdf"


def pdf_targets(schema, project_schema, documents, requested, allow_unknown):
    return targets_of(schema, project_schema, documents, requested,
                      allow_unknown, "pdf")


# --------------------------------------------------------------------------

def latex_said(log_path):
    """(what LaTeX's last run said, the LaTeX it read) from Pandoc's JSON
    log of a PDF build (--log), its makePDF messages; empty when the log
    has neither."""
    try:
        with open(log_path, encoding="utf-8") as fh:
            messages = json.load(fh)
    except (OSError, ValueError):
        return "", ""
    said = source = ""
    for message in messages:
        if message.get("type") != "MakePDFInfo":
            continue
        if message.get("description") == "LaTeX output":
            said = message.get("contents") or ""
        elif message.get("description") == "Source:":
            source = message.get("contents") or ""
    return said, source


def build(base, name, resolved, keep, intermediates=None, latex_only=False,
          as_latex=False):
    project = resolved.project
    for warning in resolved.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    pages_dir = intermediates or base
    tree, titles, placed, numbered = plan_book(pages_dir, resolved, "PDF")
    real = [s for s in placed if os.path.exists(
        os.path.join(pages_dir, s + INTERMEDIATE))]

    setting = str(resolved["pdf.metadata"] or "").strip()
    title_page = safe_stem(os.path.splitext(os.path.basename(setting))[0]) \
        if setting else None
    meta = book_metadata(project, resolved, base, numbered)
    claimed = meta.get("pdfstandard")
    claimed = [meta_plain(c) for c in claimed["c"]] if claimed and claimed.get("t") == "MetaList" \
        else ([meta_plain(claimed)] if claimed else [])
    try:
        toc_depth = int(meta_plain(meta.get("toc-depth")))
    except ValueError:
        toc_depth = int(resolved["pdf.toc_depth"])
    # toc: false in the metadata file: no contents page, the template's or
    # one project.contents generates.
    contents = not (meta.get("toc") or {}).get("t") == "MetaBool" or bool(meta["toc"]["c"])
    assembly = PdfAssembly(
        pages_dir, placed, tree, titles, title_page=title_page,
        notes_title=" ".join(str(resolved["notes.title"] or "").split()) or "Notes",
        book_title=meta_plain(meta.get("title")),
        divisions=document_class(meta) in FRONTMATTER_CLASSES,
        toc_depth=toc_depth, mark_files=as_latex, contents=contents)
    if len(tree) == 1 and tree[0][0] == "page":
        # The divisions are written where the role changes, between entries,
        # so a book of one page never reached its main matter: numbered i in
        # roman, its chapter unnumbered. Its one entry starts its division.
        assembly.before_entry(tree[0], 1)
        assembly.add_single_page(tree[0][1], tree[0][2])
    else:
        assembly.add_tree(tree)
    assembly.finish()
    # Pandoc turns an SVG into a PDF with rsvg-convert before LaTeX sees
    # it (convertImage in PDF.hs), and the image keeps its alt text; without
    # rsvg-convert the LaTeX writer falls back to \\includesvg, which needs
    # Inkscape and passes no alt text at all.
    formulas = count_math(assembly.blocks) if is_ua1(claimed) else 0
    if formulas:
        if str(resolved["pdf.ua1_math"]) == "office":
            how = ("with their TeX source as alternative text and their MathML attached "
                   "as files and as Microsoft Office's attribute, which NVDA reads; a "
                   "reader that takes only the alternative text reads the TeX as written")
        else:
            how = ("with their TeX source as alternative text, which a screen reader "
                   "reads as written, and their MathML attached as files")
        print(f"WARNING: PDF/UA-1 has no standard way to tag MathML, so the book's "
              f"{formulas} equation(s) are tagged as formulas {how}. PDF/UA-2 tags "
              "MathML properly.", file=sys.stderr)
    svgs = svg_images(assembly.blocks)
    if svgs and not latex_only and shutil.which("rsvg-convert") is None and not as_latex:
        sys.exit(f"The book has {len(svgs)} SVG image(s) ({svgs[0]} first), and a PDF "
                 "needs rsvg-convert to turn them into PDF: sudo apt install "
                 "librsvg2-bin (see docs/installation.md).")

    if assembly.toc_placed:
        # project.contents put the contents somewhere; it is there, and
        # not also where the template would put it.
        meta["toc"] = meta_bool(False)
    if assembly.toc_dropped:
        print("The book has no contents page: the pdf.metadata file says toc: false, and "
              "the one project.contents generates is left out too.", file=sys.stderr)
    # Without a title page the title is the PDF's metadata only (title-meta,
    # which hyperref makes its /Title and dc:title), and the book's first
    # heading says it.
    if not wants_title_page(str(resolved["title_page"]), tree, assembly) \
            and "title" in meta:
        meta["title-meta"] = meta_string(meta_plain(meta.pop("title")))
    document = {
        "pandoc-api-version": load_page(pages_dir,
                                        real[0])["pandoc-api-version"],
        "meta": meta,
        "blocks": assembly.blocks,
    }

    out_dir = os.path.join(base, str(resolved["output_dir"] or name))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_name(resolved, project, name))
    if as_latex:
        return write_latex(base, name, resolved, project, document, out_dir)

    work = tempfile.mkdtemp(prefix="build-pdf-")
    try:
        book_json = os.path.join(work, "book.json")
        with open(book_json, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        filters = ["--lua-filter", os.path.join(HERE, "target-blocks.lua"),
                   "--lua-filter", os.path.join(HERE, "footnote-code.lua"),
                   "--lua-filter", os.path.join(HERE, "pdf-target.lua")] + highlighting.ARGS
        environment = dict(os.environ, TARGET_NAME=name,
                           TITLE_BLOCK=str(resolved["title_block"]),
                           **label_prefixes(resolved))
        if keep or latex_only:
            # The LaTeX as the PDF was made from it, for reading when
            # something needs explaining; not needed to build.
            subprocess.run(["pandoc", "-f", "json", "-t", "latex", "-s",
                            book_json, "-o",
                            os.path.join(os.path.abspath(out_dir),
                                         "book.tex")] + filters,
                           cwd=base, env=environment)
            shutil.copy(book_json, os.path.join(out_dir, "book.json"))
        if latex_only:
            print(os.path.abspath(os.path.join(out_dir, "book.tex")))
            return 0
        command = ["pandoc", "-f", "json", "-t", "pdf", book_json,
                   "-o", os.path.abspath(out_path),
                   f"--pdf-engine={ENGINE}"] + filters
        # images.downsample: scaled copies, which Pandoc finds before the
        # originals, the run's own or made here.
        try:
            scaled = downsample.folder_for_build(
                downsample.limit_of(resolved["images.downsample"]), base, [document], work,
                lambda line: print(line, file=sys.stderr))
        except RuntimeError as exc:
            sys.exit(str(exc))
        command += downsample.resource_args(scaled)
        # Pandoc's log, as JSON: LaTeX's input and what each run of it said,
        # which names the lines it couldn't fit (overfull_lines).
        log_path = os.path.join(work, "pandoc-log.json")
        command += ["--log", log_path]
        # Run in the content directory: image paths in the intermediates
        # are relative to it.
        result = subprocess.run(command, cwd=base, capture_output=True,
                                text=True, env=environment)
        if result.returncode == 0:
            line = latexbuild.overfull_warning(latexbuild.overfull_lines(
                *latex_said(log_path), {page_id(stem): stem for stem, _t, _d in assembly.pages}))
            if line:
                print(line, file=sys.stderr)
        missing, others = latexbuild.missing_characters(result.stderr.splitlines())
        if others:
            print("\n".join(others), file=sys.stderr)
        if missing:
            # One line, not Pandoc's one warning per occurrence.
            print(latexbuild.missing_warning(
                missing, "Choose a font that has them in the pdf.metadata file "
                "(mainfont)."), file=sys.stderr)
        repairs = result.returncode == 0 and (
            resolved["pdf.repair_captions"] or resolved["pdf.remove_empty_paragraphs"])
        if repairs and pdfretag.pikepdf is None:
            print("WARNING: pikepdf isn't installed, so table captions keep the tags "
                  "LaTeX gives them, a first row a screen reader reads as data, and "
                  "the empty paragraph elements LaTeX leaves stay (pip install "
                  "pikepdf, or sudo apt install python3-pikepdf).", file=sys.stderr)
        elif repairs:
            repair(os.path.abspath(out_path), resolved, assembly.blocks)
        if result.returncode != 0:
            for advice in latexbuild.failure_advice(result.stderr):
                print(advice, file=sys.stderr)
            sys.exit(f"pandoc failed building {out_path}.")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(os.path.abspath(out_path))          # for whatever runs next
    found = assembly.found
    print(f"Wrote {out_path}: {len(assembly.pages)} page(s), "
          f"{found['images']} image(s), {found['without_alt']} without "
          "alternative text.", file=sys.stderr)
    return 0


def write_latex(base, name, resolved, project, document, out_dir):
    """The latex target: the LaTeX the PDF target builds from, as a master
    file that \\include-s a file per top-level entry, with the images it
    shows beside them, SVGs made PDFs. Prints the master's path."""
    svgs, failed = svg_to_pdf(document["blocks"], base, out_dir)
    copied = copy_images(document["blocks"], base, out_dir)
    work = tempfile.mkdtemp(prefix="build-latex-")
    try:
        book_json = os.path.join(work, "book.json")
        with open(book_json, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        filters = ["--lua-filter", os.path.join(HERE, "target-blocks.lua"),
                   "--lua-filter", os.path.join(HERE, "footnote-code.lua"),
                   "--lua-filter", os.path.join(HERE, "pdf-target.lua"),
                   "--lua-filter", os.path.join(HERE, "latex-target.lua")] + highlighting.ARGS
        environment = dict(os.environ, TARGET_NAME=name,
                           TITLE_BLOCK=str(resolved["title_block"]),
                           **label_prefixes(resolved))
        done = subprocess.run(["pandoc", "-f", "json", "-t", "latex", "-s", book_json]
                              + filters, cwd=base, env=environment,
                              capture_output=True, text=True)
        sys.stderr.write(done.stderr)
        if done.returncode:
            return done.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)
    master, files = split_book(done.stdout)
    master_name = os.path.splitext(output_name(resolved, project, name))[0] + ".tex"
    for stem, body in files.items():
        with open(os.path.join(out_dir, stem + ".tex"), "w", encoding="utf-8") as fh:
            fh.write(body.strip("\n") + "\n")
    with open(os.path.join(out_dir, master_name), "w", encoding="utf-8") as fh:
        fh.write(master)
    print(f"{name}: {master_name} and {len(files)} file(s) it \\include-s, "
          f"{copied} image(s) beside them" + (f", {svgs} SVG(s) made PDF" if svgs else "")
          + ". Build it with latexmk -lualatex.", file=sys.stderr)
    if failed:
        print(f"WARNING: {len(failed)} SVG image(s) weren't made PDF ({failed[0]} first): "
              "rsvg-convert is needed (sudo apt install librsvg2-bin); LaTeX's \\includesvg "
              "is left, which needs Inkscape and takes no alt text.", file=sys.stderr)
    print(os.path.abspath(os.path.join(out_dir, master_name)))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Assemble the filtered intermediates into a tagged PDF.")
    parser.add_argument("-d", "--dir", default=".",
                        help="the content directory (default: .)")
    parser.add_argument("--target", default=None,
                        help="build this pdf target only")
    parser.add_argument("--intermediates", default=None,
                        help="read the filtered intermediates from here "
                             "rather than from the content directory")
    parser.add_argument("--if-declared", action="store_true",
                        help="exit quietly when no pdf target is declared")
    parser.add_argument("--keep", action="store_true",
                        help="leave book.json and book.tex beside the PDF")
    parser.add_argument("--latex-only", action="store_true",
                        help="write book.json and book.tex beside where the "
                             "PDF would go, and don't run LaTeX")
    parser.add_argument("--latex-target", action="store_true",
                        help="build the latex targets (format: latex): the "
                             "book's LaTeX as a master and a file per chapter")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    parser.add_argument("--title", default=None,
                        help="the book's title when no configuration gives "
                             "one: convert.py passes what it read from the "
                             "sources, a master file's title, and says so")
    args = parser.parse_args()

    for program in ("pandoc",) if args.latex_only or args.latex_target else ("pandoc", ENGINE):
        if shutil.which(program) is None:
            sys.exit(f"{program} is not on the path; a pdf target needs it "
                     "(see docs/installation.md).")
    if not args.latex_only and not args.latex_target:
        problem = latex_problem()
        if problem:
            sys.exit(problem)

    try:
        schema, project_schema, documents = load_documents(
            args.dir, args.allow_unknown_keys)
        targets = targets_of(schema, project_schema, documents, args.target,
                             args.allow_unknown_keys,
                             "latex" if args.latex_target else "pdf")
    except oerconfig.ConfigError as exc:
        sys.exit(str(exc))

    if not targets:
        if args.if_declared:
            return 0
        print("No target with format: pdf in conversion.yaml. Declare one "
              "to build a PDF:", file=sys.stderr)
        print("  targets:\n    pdf:\n      format: pdf", file=sys.stderr)
        return 1

    status = 0
    for name, resolved in targets:
        if args.title:
            resolved.project["title"] = args.title
        status = build(args.dir, name, resolved, args.keep,
                       args.intermediates, args.latex_only,
                       as_latex=args.latex_target) or status
    return status


if __name__ == "__main__":
    sys.exit(main())
