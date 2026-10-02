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
written into the header here. A source's own division commands, read
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
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")
from bookassembly import (  # noqa: E402
    INTERMEDIATE, Assembly, load_documents, targets_of, plan_book, load_page,
    page_title, stringify,
)
from bookcontents import is_generated  # noqa: E402
import pdfparagraphs  # noqa: E402
import pdfretag  # noqa: E402
from names import safe_stem  # noqa: E402

ENGINE = "lualatex"
# The LaTeX release the tagging project describes as usable in production
# for documents that keep to packages supporting it. Older releases load
# pdfmanagement-testphase.sty for \DocumentMetadata, where current ones
# load pdfmanagement-init (documentmetadata-support.ltx), and Ubuntu 24.04's
# texlive packages (LaTeX 2023-11-01) stop on that file not found; they
# would tag less if it were there. Verified here: 2026-06-01.
MINIMUM_LATEX = "2025-11-01"
MISSING_FILE = re.compile(r"File `([^']+)' not found")
DIVISIONS = {"front": "\\frontmatter", "main": "\\mainmatter",
             "appendix": "\\appendix", "back": "\\backmatter"}
# The classes Pandoc's LaTeX writer knows to have \frontmatter and its
# kin (frontmatterClasses in Writers/LaTeX.hs, 3.11). In any other the
# roles write only \appendix.
FRONTMATTER_CLASSES = ("memoir", "book", "scrbook", "extbook", "tufte-book",
                       "ctexbook", "elegantbook")
# Pandoc's template brackets the title and contents with \frontmatter and
# \mainmatter and puts \backmatter after the body, so a front page in
# the body would begin the front matter a second time and number its
# pages from i again. The template's are switched off (has-frontmatter),
# and the book opens in the front matter here instead; the roles say the
# rest.
OPEN_FRONT = "\\AddToHook{begindocument/end}{\\frontmatter}\n"

# Latin Modern, the template's fonts when none is chosen, has no Greek and
# few mathematical symbols, and a character its font lacks is drawn blank
# (.notdef): gone from the page and from the text a screen reader gets. A
# book that uses them as text (a statistics book's mu, sigma, and
# less-than-or-equal) loses them. Latin Modern Math has them, so it fills
# in for each of the three families the metadata file doesn't choose a
# font for. What it can't supply is reported after the build, because
# veraPDF catches only some of it: a character an equation falls back to
# one of LaTeX's older math fonts for is dropped with no trace at all.
# DejaVu Sans comes after it when it's installed, as it is with most Linux
# desktops: it has what Latin Modern Math doesn't, such as the circled
# digits an AsciiDoc book's code callouts are (58 of them in the security
# textbook, all drawn blank without it).
FALLBACK = ("\\IfFontExistsTF{DejaVu Sans}\n"
            "  {\\directlua{luaotfload.add_fallback(\"oerfallback\", "
            "{\"Latin Modern Math:mode=harf;\", \"DejaVu Sans:mode=harf;\"})}}\n"
            "  {\\directlua{luaotfload.add_fallback(\"oerfallback\", "
            "{\"Latin Modern Math:mode=harf;\"})}}\n")
FAMILIES = (("mainfont", "\\setmainfont{Latin Modern Roman}"),
            ("sansfont", "\\setsansfont{Latin Modern Sans}"),
            ("monofont", "\\setmonofont{Latin Modern Mono}"))
MISSING = re.compile(r"Missing character: There is no (\S+)")

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

# Written into the preamble after the metadata file's own header-includes.
# math/setup names both forms of MathML luamml makes (it needs
# unicode-math, which Pandoc's template loads under LuaLaTeX): structure
# elements under each formula, and a MathML file attached to it. The key
# switches every form off before applying the ones listed (read in
# latex-lab-math.ltx), so both are named rather than left to defaults
# that could change. The link commands are
# the ones pdf-target.lua puts around every link; LaTeX's own default
# /Contents -- the address, or "Go to destination" and an id -- is
# switched off, since every link the book's text makes gets one here.
HEADER = r"""\ifdefined\tagpdfsetup
  \tagpdfsetup{math/setup={mathml-SE,mathml-AF}}
\fi
\ExplSyntaxOn
\tl_new:N \l__oer_link_contents_tl
\NewDocumentCommand \OERLinkContents { m }
  {
    \cs_if_exist:NT \pdfannot_dict_put:nne
      {
        \pdfstringdef \l__oer_link_contents_tl {#1}
        \pdfannot_dict_put:nne {link/URI} {Contents}
          { (\l__oer_link_contents_tl) }
        \pdfannot_dict_put:nne {link/GoTo} {Contents}
          { (\l__oer_link_contents_tl) }
      }
  }
\NewDocumentCommand \OERLinkContentsReset { }
  {
    \cs_if_exist:NT \pdfannot_dict_remove:nn
      {
        \pdfannot_dict_remove:nn {link/URI} {Contents}
        \pdfannot_dict_remove:nn {link/GoTo} {Contents}
      }
  }
\AddToHook{begindocument}
  {
    \socket_if_exist:nT {hyp/link/URI/Contents}
      { \socket_assign_plug:nn {hyp/link/URI/Contents} {noop} }
    \socket_if_exist:nT {hyp/link/GoTo/Contents}
      { \socket_assign_plug:nn {hyp/link/GoTo/Contents} {noop} }
  }
\NewDocumentCommand \OERArtifactGraphics { }
  { \cs_if_exist:NT \tag_mc_begin:n { \setkeys{Gin}{artifact} } }
\ExplSyntaxOff
"""


def latex_release():
    """The LaTeX release LuaLaTeX runs, as its \\fmtversion gives it
    ("2026-06-01"), or None when it can't be read."""
    work = tempfile.mkdtemp(prefix="build-pdf-probe-")
    try:
        result = subprocess.run(
            [ENGINE, "-interaction=nonstopmode", "-halt-on-error",
             "\\typeout{OERFMT:\\fmtversion}\\stop"],
            cwd=work, capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    m = re.search(r"OERFMT:(\d{4}-\d{2}-\d{2})", result.stdout)
    return m.group(1) if m else None


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
    release = latex_release()
    if release is None:
        print(f"WARNING: couldn't tell which LaTeX release {ENGINE} runs; "
              f"a tagged PDF needs {MINIMUM_LATEX} or later.",
              file=sys.stderr)
        return None
    if release < MINIMUM_LATEX:
        return (f"{ENGINE} runs the LaTeX release of {release}, and a tagged "
                f"PDF needs {MINIMUM_LATEX} or later (TeX Live 2026). "
                "Distribution packages are often older; docs/installation.md "
                "says how to install a current TeX Live.")
    return None


def raw_latex(text):
    return {"t": "RawBlock", "c": ["latex", text]}


def is_division(block):
    return (block.get("t") == "RawBlock"
            and block["c"][0] in ("latex", "tex")
            and " ".join(block["c"][1].split()) in DIVISIONS.values())


class PdfAssembly(Assembly):
    """The book as LaTeX wants it: numbers and the contents are LaTeX's,
    and a role is a division command."""

    def __init__(self, *args, title_page=None, book_title="",
                 divisions=True, toc_depth=2, **kwargs):
        super().__init__(*args, **kwargs)
        # The book opens in the front matter (OPEN_FRONT): its title
        # page, and the contents when the template places them.
        self.division = "front"
        self.divisions = divisions
        self.toc_depth = toc_depth
        self.toc_placed = False
        # The page made from the metadata file, when its title is the
        # book's: that title is the title block LaTeX draws, so the page
        # gets no heading of its own. A page whose title is its own --
        # a lone heading promoted to the title -- keeps it.
        self.title_page = title_page
        self.book_title = book_title

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
        # A generated contents page belongs to whatever division it sits
        # in; it has no role of its own to change it.
        if depth != 1 or is_generated(entry):
            return
        role = entry.role or "main"
        if role == self.division:
            return
        if self.divisions or role == "appendix":
            self.blocks.append(raw_latex(DIVISIONS[role]))
        self.division = role

    def add_generated(self, entry, depth):
        if entry.generate == "toc":
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
    path = setting if os.path.isabs(setting) else os.path.join(base, setting)
    if not os.path.isfile(path):
        sys.exit(f"pdf.metadata is set to {setting}, which does not exist "
                 f"(looked at {os.path.abspath(path)}).")
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
    meta["toc-depth"] = meta_string(int(resolved["pdf.toc_depth"]))
    setting = str(resolved["pdf.metadata"] or "").strip()
    if setting:
        meta.update(metadata_file(base, setting))
    # Ours come after the author's, so the author's packages are loaded
    # first; a list either way.
    includes = meta.get("header-includes")
    if includes is None:
        includes = {"t": "MetaList", "c": []}
    elif includes.get("t") != "MetaList":
        includes = {"t": "MetaList", "c": [includes]}
    ours = HEADER + FIGURE_PLACEMENT[str(resolved["pdf.figures"])]
    unchosen = [command for field, command in FAMILIES if field not in meta]
    if unchosen:
        ours += FALLBACK + "".join(
            f"{command}[RawFeature={{fallback=oerfallback}}]\n"
            for command in unchosen)
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


def meta_plain(value):
    """A metadata field's text, whichever form it has."""
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return " ".join(str(value["c"]).split())
    return " ".join(stringify(value.get("c", [])).split())


def document_class(meta):
    return meta_plain(meta.get("documentclass"))


def captioned_tables(blocks):
    """For each table in the book, in order, whether it has a caption."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Table":
                found.append(bool(node["c"][1][1]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(blocks)
    return found


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

def build(base, name, resolved, keep, intermediates=None, latex_only=False):
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
    try:
        toc_depth = int(meta_plain(meta.get("toc-depth")))
    except ValueError:
        toc_depth = int(resolved["pdf.toc_depth"])
    assembly = PdfAssembly(
        pages_dir, placed, tree, titles, title_page=title_page,
        book_title=meta_plain(meta.get("title")),
        divisions=document_class(meta) in FRONTMATTER_CLASSES,
        toc_depth=toc_depth)
    if len(tree) == 1 and tree[0][0] == "page":
        assembly.add_single_page(tree[0][1], tree[0][2])
    else:
        assembly.add_tree(tree)
    # Pandoc turns an SVG into a PDF with rsvg-convert before LaTeX sees
    # it (convertImage in PDF.hs), and the image keeps its alt text; without
    # rsvg-convert the LaTeX writer falls back to \\includesvg, which needs
    # Inkscape and passes no alt text at all.
    svgs = svg_images(assembly.blocks)
    if svgs and not latex_only and shutil.which("rsvg-convert") is None:
        sys.exit(f"The book has {len(svgs)} SVG image(s) ({svgs[0]} first), and a PDF "
                 "needs rsvg-convert to turn them into PDF: sudo apt install "
                 "librsvg2-bin (see docs/installation.md).")

    if assembly.toc_placed:
        # project.contents put the contents somewhere; it is there, and
        # not also where the template would put it.
        meta["toc"] = meta_bool(False)
    document = {
        "pandoc-api-version": load_page(pages_dir,
                                        real[0])["pandoc-api-version"],
        "meta": meta,
        "blocks": assembly.blocks,
    }

    out_dir = os.path.join(base, str(resolved["output_dir"] or name))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_name(resolved, project, name))

    work = tempfile.mkdtemp(prefix="build-pdf-")
    try:
        book_json = os.path.join(work, "book.json")
        with open(book_json, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        filters = ["--lua-filter", os.path.join(HERE, "target-blocks.lua"),
                   "--lua-filter", os.path.join(HERE, "pdf-target.lua")]
        environment = dict(os.environ, TARGET_NAME=name,
                           TITLE_BLOCK=str(resolved["title_block"]))
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
        # Run in the content directory: image paths in the intermediates
        # are relative to it.
        result = subprocess.run(command, cwd=base, capture_output=True,
                                text=True, env=environment)
        missing, others = {}, []
        for line in result.stderr.splitlines():
            m = MISSING.search(line)
            if m:
                missing[m.group(1)] = missing.get(m.group(1), 0) + 1
            elif line.strip():
                others.append(line)
        if others:
            print("\n".join(others), file=sys.stderr)
        if missing:
            # One line, not Pandoc's one warning per occurrence.
            print(f"WARNING: {sum(missing.values())} character(s) the "
                  "fonts don't have are missing from the PDF: "
                  + ", ".join(f"{c} (U+{ord(c[0]):04X}) x{n}" for c, n in
                              sorted(missing.items(), key=lambda i: -i[1]))
                  + ". Choose a font that has them in the pdf.metadata "
                  "file (mainfont).", file=sys.stderr)
        repairs = result.returncode == 0 and (
            resolved["pdf.repair_captions"] or resolved["pdf.remove_empty_paragraphs"])
        if repairs and pdfretag.pikepdf is None:
            print("WARNING: pikepdf isn't installed, so table captions keep the tags "
                  "LaTeX gives them, a first row a screen reader reads as data, and "
                  "the empty paragraph elements LaTeX leaves stay (pip install "
                  "pikepdf, or sudo apt install python3-pikepdf).", file=sys.stderr)
        elif repairs:
            if resolved["pdf.repair_captions"]:
                repair_tables(os.path.abspath(out_path), assembly.blocks)
            if resolved["pdf.remove_empty_paragraphs"]:
                remove_empty_paragraphs(os.path.abspath(out_path))
        if result.returncode != 0:
            # tlmgr only manages a TeX Live installed from tug.org or as
            # TinyTeX; Debian's and Ubuntu's texlive packages come with a
            # tlmgr that runs in an uninitialized user mode and installs
            # nothing, so both routes are named.
            for name in dict.fromkeys(MISSING_FILE.findall(result.stderr)):
                print(f"LaTeX can't find {name}. For TinyTeX or TeX Live "
                      f"from tug.org, `tlmgr search --global --file /{name}` "
                      "names the package that has it, and `tlmgr install` "
                      "installs that. For a distribution's texlive packages, "
                      "its package manager does (`apt-file search "
                      f"{name}` on Debian and Ubuntu).", file=sys.stderr)
            sys.exit(f"pandoc failed building {out_path}.")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(os.path.abspath(out_path))          # for whatever runs next
    found = assembly.found
    print(f"Wrote {out_path}: {len(assembly.pages)} page(s), "
          f"{found['images']} image(s), {found['without_alt']} without "
          "alternative text.", file=sys.stderr)
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
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    args = parser.parse_args()

    for program in ("pandoc",) if args.latex_only else ("pandoc", ENGINE):
        if shutil.which(program) is None:
            sys.exit(f"{program} is not on the path; a pdf target needs it "
                     "(see docs/installation.md).")
    if not args.latex_only:
        problem = latex_problem()
        if problem:
            sys.exit(problem)

    try:
        schema, project_schema, documents = load_documents(
            args.dir, args.allow_unknown_keys)
        targets = pdf_targets(schema, project_schema, documents,
                              args.target, args.allow_unknown_keys)
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
        status = build(args.dir, name, resolved, args.keep,
                       args.intermediates, args.latex_only) or status
    return status


if __name__ == "__main__":
    sys.exit(main())
