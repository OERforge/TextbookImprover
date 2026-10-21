"""What a LaTeX build of a tagged PDF needs, and what its log means, for
both ways a PDF target is built: from the pages through Pandoc's LaTeX
writer (bin/build-pdf.py), and from a LaTeX book's own files
(convert.py, pdf.from: book).

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

import os
import re
import shlex
import shutil
import subprocess
import tempfile

ENGINE = "lualatex"
# The oldest LaTeX release a tagged build is taken to. The tagging project
# describes 2025-11-01 as usable in production for documents that keep to
# packages supporting it, but measured with the suites (TeX Live 2025's
# 2025-11-01 against TeX Live 2026's 2026-06-01, which passes every check),
# 2025-11-01 stops a PDF/UA-1 book (math/setup has no mathml-MS) and a
# LaTeX book with enumitem's settings, gives a table cell's formulas no
# MathML and an eqnarray*'s no file, leaves floats' tags at the end (there's
# no float/here), and repeats the enumerate package's labels. Releases
# before it load pdfmanagement-testphase.sty for \DocumentMetadata, where
# current ones load pdfmanagement-init (documentmetadata-support.ltx), and
# Ubuntu 24.04's texlive packages (LaTeX 2023-11-01) stop on that file not
# found.
MINIMUM_LATEX = "2026-06-01"
MISSING_FILE = re.compile(r"File `([^']+)' not found")
MISSING = re.compile(r"Missing character: There is no (\S+)")
CAPACITY = re.compile(r"TeX capacity exceeded, sorry \[([^\]=]+)")
# A language babel hasn't installed, which Pandoc's template names for a
# passage in it (french, ngerman), as a class option babel reads.
BABEL_UNKNOWN = re.compile(r"Package babel Error: Unknown option [`']([^'`\s]+)'")
# A font fontspec can't find, which it says over several lines, each
# after "(fontspec)".
MISSING_FONT = re.compile(r'The font "([^"]+)" cannot be found')


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


def latex_problem(warn):
    """Why the LuaLaTeX on the path can't tag a PDF, or None. warn gets a
    message when the release can't be told."""
    release = latex_release()
    if release is None:
        warn(f"WARNING: couldn't tell which LaTeX release {ENGINE} runs; "
             f"a tagged PDF needs {MINIMUM_LATEX} or later.")
        return None
    if release < MINIMUM_LATEX:
        return (f"{ENGINE} runs the LaTeX release of {release}, and a tagged "
                f"PDF needs {MINIMUM_LATEX} or later: TeX Live 2026 since its "
                "June update (`" + tlmgr_command("update --self --all")
                + "` brings an earlier TeX Live 2026 to it). Distribution "
                "packages are often older; docs/installation.md says how to "
                "install a current TeX Live.")
    return None


# A PDF figure that draws its text with fonts it doesn't embed, as R's pdf()
# device does with Helvetica, Symbol, and ZapfDingbats (548 of OpenIntro
# Statistics' 563 figures): PDF/UA requires every font embedded (8.4.5.5.1
# in PDF/UA-2) and each glyph mapped to Unicode (8.4.5.8), and veraPDF
# fails the book's PDF on both, the figures being part of its pages. Each
# is written again with its fonts embedded: by Ghostscript, with its list
# of fonts never to embed emptied (base-14 fonts are on it by default), its
# images passed through and its pages unrotated; or by poppler's
# pdftocairo, which embeds what it draws, when Ghostscript isn't installed.
# Both checked: veraPDF passes a tagged document holding the figure.
EMBED_GS = ["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
            "-dEmbedAllFonts=true", "-dSubsetFonts=true", "-dAutoRotatePages=/None",
            "-dPassThroughJPEGImages=true", "-dPassThroughJPXImages=true",
            "-dDownsampleColorImages=false", "-dDownsampleGrayImages=false",
            "-dDownsampleMonoImages=false",
            # An image stored losslessly stays so: pdfwrite's automatic
            # choice made a Flate raster JPEG (a mean error of 9 in 255).
            "-dAutoFilterColorImages=false", "-dColorImageFilter=/FlateEncode",
            "-dAutoFilterGrayImages=false", "-dGrayImageFilter=/FlateEncode"]
# A figure, not a document: a PDF of more pages than this is left as it is.
FIGURE_PAGES = 3


def unembedded_fonts(path):
    """The names of the fonts a PDF's pages draw with, form XObjects too,
    that it doesn't embed; None when it can't be read (or pypdf isn't
    installed), or has more pages than a figure (FIGURE_PAGES)."""
    try:
        import logging
        from pypdf import PdfReader
        # A figure's broken cross-reference table, which pypdf repairs and
        # says so, one line each, is no news here.
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = PdfReader(path)
        if len(reader.pages) > FIGURE_PAGES:
            return None
        names, seen = set(), set()

        def walk(resources):
            if resources is None:
                return
            resources = resources.get_object()
            # What .get() returns can be a reference, which pypdf before
            # 4.1 doesn't follow when it's read from: Ubuntu 24.04's is
            # 4.0.2.
            fonts, xobjects = resources.get("/Font"), resources.get("/XObject")
            for ref in (fonts.get_object() if fonts is not None else {}).values():
                font = ref.get_object()
                if id(font) in seen:
                    continue
                seen.add(id(font))
                if font.get("/Subtype") == "/Type3":
                    continue
                described = font
                if font.get("/Subtype") == "/Type0":
                    described = font["/DescendantFonts"][0].get_object()
                descriptor = described.get("/FontDescriptor")
                descriptor = descriptor.get_object() if descriptor is not None else {}
                if not any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                    names.add(str(font.get("/BaseFont", "")).lstrip("/"))
            for ref in (xobjects.get_object() if xobjects is not None else {}).values():
                xobject = ref.get_object()
                if xobject.get("/Subtype") == "/Form" and id(xobject) not in seen:
                    seen.add(id(xobject))
                    walk(xobject.get("/Resources"))
        for page in reader.pages:
            walk(page.get("/Resources"))
        return names
    except Exception:  # noqa: BLE001 -- a PDF pypdf can't read is left alone
        return None


def embedding_tool():
    """The program that embeds a figure's fonts here, or None."""
    if shutil.which("gs"):
        return "gs"
    if shutil.which("pdftocairo"):
        return "pdftocairo"
    return None


def embed_fonts(source, dest, tool):
    """source written to dest with its fonts embedded, by tool
    (embedding_tool). Returns whether it was."""
    if tool == "gs":
        command = EMBED_GS + ["-o", dest, "-c", "<</NeverEmbed [ ]>> setdistillerparams",
                              "-f", source]
    else:
        command = ["pdftocairo", "-pdf", source, dest]
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              stdin=subprocess.DEVNULL, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and os.path.isfile(dest) and unembedded_fonts(dest) == set()


def figure_pdfs(root, skip=()):
    """The PDFs under root, relative to it, outside the folders skip names
    (absolute paths) and a version control folder: a book's figures, and
    whatever else it keeps as PDF, which unembedded_fonts tells apart. A
    folder the book links to is followed, once (figs -> ../shared/figs)."""
    found = []
    skip = {os.path.abspath(s) for s in skip}
    seen = set()
    for folder, dirs, files in os.walk(root, followlinks=True):
        real = os.path.realpath(folder)
        if real in seen:
            dirs[:] = []
            continue
        seen.add(real)
        dirs[:] = [d for d in dirs if d not in (".git", ".hg", ".svn")
                   and os.path.abspath(os.path.join(folder, d)) not in skip]
        for name in files:
            if name.lower().endswith(".pdf"):
                found.append(os.path.relpath(os.path.join(folder, name), root))
    return sorted(found)


def writable_path(out_root, name):
    """out_root/name, made safe to write a file at without writing outside
    out_root: a folder on the way that is a link to one outside it (a
    copy of the book keeps its links) is made a folder of its own, of
    links to what the linked one holds, and the file's own link, if it is
    one, is replaced by the file, not written through."""
    root = os.path.realpath(out_root)
    parts = os.path.normpath(name).split(os.sep)
    at = out_root
    for part in parts[:-1]:
        at = os.path.join(at, part)
        if os.path.islink(at):
            target = os.path.realpath(at)
            if target == root or target.startswith(root + os.sep):
                continue
            os.remove(at)
            os.makedirs(at)
            for entry in os.listdir(target):
                os.symlink(os.path.join(target, entry), os.path.join(at, entry))
        elif not os.path.isdir(at):
            os.makedirs(at, exist_ok=True)
    return os.path.join(out_root, *parts)


def embed_figure_fonts(root, out_root, names, done=None, workers=4):
    """Each PDF of names (relative to root) whose fonts aren't all embedded,
    written to out_root at the same path with them embedded. done, a dict
    if given, maps a name to the file already written for it, which is
    copied, and gets each one written here. Returns (written, failed,
    tool): the names written, those that couldn't be, and the program used
    (None when neither is installed, and nothing is written)."""
    import concurrent.futures
    done = {} if done is None else done
    wanted = [name for name in names if unembedded_fonts(os.path.join(root, name))]
    tool = embedding_tool()
    if not wanted or tool is None:
        return [], wanted, tool

    def one(name):
        # Written beside it and moved over it, so a link there is replaced,
        # not written through: the book's own figure stays as it is.
        dest = writable_path(out_root, name)
        work = dest + ".embedding.pdf"
        if name in done and os.path.isfile(done[name]) \
                and os.path.abspath(done[name]) != os.path.abspath(dest):
            shutil.copyfile(done[name], work)
            ok = True
        else:
            ok = embed_fonts(os.path.join(root, name), work, tool)
        if ok:
            os.replace(work, dest)
        elif os.path.exists(work):
            os.remove(work)
        return name, ok
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, wanted))
    written = [n for n, ok in results if ok]
    for name in written:
        done.setdefault(name, os.path.join(out_root, name))
    return written, [n for n, ok in results if not ok], tool


# amssymb's and latexsym's names that unicode-math has no command for.
# amssymb, loaded before unicode-math (by Pandoc's template, and by most
# books), leaves them drawn from TeX's own symbol fonts, whose glyphs map
# to control characters: GIAM's \square read as U+0003, \blacksquare U+0004,
# \lozenge U+0006, which a screen reader can't say and veraPDF passes.
# Each is made the character it is, from Latin Modern Math, or, for one
# that font lacks, from the text's fonts and their fallback, set as a box
# (\mbox); only a name that is still amssymb's (a math character, or one
# built from its \dabar@), or the kernel's placeholder for latexsym's, so
# a book's own definition is kept. Inside \ExplSyntaxOn, for unicode-math
# under LuaLaTeX.
UM_ALIASES = r"""  % amssymb's names unicode-math has no command for, which drew control
  % characters from TeX's fonts (\square as U+0003): the characters they are.
  \ExplSyntaxOn
  \cs_new_protected:Npn \__oer_um_if_legacy:NT #1#2
    {
      \cs_if_free:NTF #1 {#2}
        {
          \token_if_mathchardef:NTF #1 {#2}
            {
              \exp_args:Ne \str_if_in:nnTF { \cs_meaning:N #1 } { not@base } {#2}
                { \exp_args:Ne \str_if_in:nnT { \cs_meaning:N #1 } { dabar@ } {#2} }
            }
        }
    }
  \cs_new_protected:Npn \__oer_um_alias:NN #1#2
    { \__oer_um_if_legacy:NT #1 { \cs_set_eq:NN #1 #2 } }
  \cs_new_protected:Npn \__oer_um_text:NNn #1#2#3
    { \__oer_um_if_legacy:NT #1 { \cs_set_protected:Npn #1 { #2 { \mbox { \Uchar "#3 } } } } }
  \AtBeginDocument
    {
      \__oer_um_alias:NN \Box \mdlgwhtsquare
      \__oer_um_alias:NN \square \mdlgwhtsquare
      \__oer_um_alias:NN \blacksquare \mdlgblksquare
      \__oer_um_text:NNn \Diamond \mathord { 25C7 }
      \__oer_um_alias:NN \lozenge \mdlgwhtlozenge
      \__oer_um_text:NNn \blacklozenge \mathord { 29EB }
      \__oer_um_alias:NN \lhd \vartriangleleft
      \__oer_um_alias:NN \rhd \vartriangleright
      \__oer_um_alias:NN \unlhd \trianglelefteq
      \__oer_um_alias:NN \unrhd \trianglerighteq
      \__oer_um_alias:NN \leadsto \rightsquigarrow
      \__oer_um_alias:NN \centerdot \cdotp
      \__oer_um_alias:NN \circlearrowleft \acwopencirclearrow
      \__oer_um_alias:NN \circlearrowright \cwopencirclearrow
      \__oer_um_text:NNn \dashrightarrow \mathrel { 21E2 }
      \__oer_um_text:NNn \dasharrow \mathrel { 21E2 }
      \__oer_um_text:NNn \dashleftarrow \mathrel { 21E0 }
      \__oer_um_alias:NN \doteqdot \Doteq
      \__oer_um_alias:NN \doublecap \Cap
      \__oer_um_alias:NN \doublecup \Cup
      \__oer_um_alias:NN \gggtr \ggg
      \__oer_um_alias:NN \llless \lll
      \__oer_um_alias:NN \gvertneqq \gneqq
      \__oer_um_alias:NN \lvertneqq \lneqq
      \__oer_um_alias:NN \ngeqq \ngeq
      \__oer_um_alias:NN \ngeqslant \ngeq
      \__oer_um_alias:NN \nleqq \nleq
      \__oer_um_alias:NN \nleqslant \nleq
      \__oer_um_alias:NN \npreceq \npreccurlyeq
      \__oer_um_alias:NN \nsucceq \nsucccurlyeq
      \__oer_um_alias:NN \nshortmid \nmid
      \__oer_um_alias:NN \nshortparallel \nparallel
      \__oer_um_alias:NN \nsubseteqq \nsubseteq
      \__oer_um_alias:NN \nsupseteqq \nsupseteq
      \__oer_um_alias:NN \ntriangleleft \nvartriangleleft
      \__oer_um_alias:NN \ntriangleright \nvartriangleright
      \__oer_um_alias:NN \restriction \upharpoonright
      \__oer_um_alias:NN \shortmid \mid
      \__oer_um_alias:NN \shortparallel \parallel
      \__oer_um_alias:NN \smallfrown \frown
      \__oer_um_alias:NN \smallsmile \smile
      \__oer_um_alias:NN \thickapprox \approx
      \__oer_um_alias:NN \thicksim \sim
      \__oer_um_alias:NN \varpropto \propto
      \__oer_um_alias:NN \varsubsetneq \subsetneq
      \__oer_um_alias:NN \varsubsetneqq \subsetneq
      \__oer_um_alias:NN \varsupsetneq \supsetneq
      \__oer_um_alias:NN \varsupsetneqq \supsetneq
    }
  \ExplSyntaxOff
"""


# How math is tagged, by the standard the PDF claims. PDF 2.0 (PDF/UA-2)
# has a MathML namespace, so each formula gets its MathML as structure
# elements and as an attached file. PDF 1.7 (PDF/UA-1) has neither, and
# MathML structure elements there are non-standard types veraPDF rejects;
# the formula keeps the attached file, and latex-lab gives it its TeX
# source as alternative text, which it switches on itself for PDF/UA-1.
# pdf.ua1_math: office, the default, adds the MathML as Microsoft Office's
# own attribute on the formula (/O /MSFT_Office /MSFT_MathML), which Word
# writes in the PDFs it saves and latex-lab's mathml-MS option reproduces.
# NVDA reads that attribute before a formula's alternative text
# (NVDAObjects/IAccessible/adobeAcrobat.py, _get_mathMl), and in Acrobat
# it read the formulas as math, where with alt it read the TeX source.
MATH_SETUP = {
    "ua2": "mathml-SE,mathml-AF",
    "ua1-alt": "mathml-AF",
    "ua1-office": "mathml-AF,mathml-MS",
}


def math_setup(standards, choice):
    """The math/setup value for the standards the PDF claims."""
    if any(s.lower().startswith("ua-1") for s in standards) and \
            not any(s.lower().startswith("ua-2") for s in standards):
        return MATH_SETUP["ua1-" + choice]
    return MATH_SETUP["ua2"]


# Highlighted code's spaces as characters in a tagged PDF's text, which is
# what a screen reader reads. Pandoc writes highlighted code in fancyvrb's
# Verbatim (inline, \Verb), its tokens colored by \textcolor, and fancyvrb
# makes a space \ , interword glue; under LuaLaTeX a space beside a
# color's change became no character at all ("return12-2* p >0"), and a
# run of spaces, an indentation, one. A space as \nobreak\ , as LaTeX's
# own verbatim makes one, is a character each, and nothing on the page
# moves. Read after Pandoc's highlighting macros: by build-pdf.py in a
# book's preamble when it has highlighted code, and by a deck's template.
CODE_SPACES = r"""\makeatletter
\fvset{formatcom*={\def\FV@Space{\nobreak\ }}}
\makeatother
"""


# PDF/UA-1 wants a /Contents on every link (7.18.5), LaTeX's own too: a
# contents line, a cross-reference it makes. hyperref has a plug for that
# ("Go to destination" and the destination's name, or the address), which
# would overwrite the text-and-description /Contents pdf-target.lua gives a
# text link. These plugs use hyperref's text only for a link that has none
# of its own.
UA1_LINKS = r"""\ExplSyntaxOn
\AddToHook{begindocument/end}
  {
    \socket_if_exist:nT {hyp/link/GoTo/Contents}
      {
        \socket_new_plug:nnn {hyp/link/GoTo/Contents}{oer}
          {
            \tl_if_empty:NT \l__oer_link_contents_tl
              {
                \pdfstringdef \l_tmpa_tl {Go~to~destination~#1}
                \pdfannot_dict_put:nne {link/GoTo}{Contents}{(\l_tmpa_tl)}
              }
          }
        \socket_assign_plug:nn {hyp/link/GoTo/Contents}{oer}
      }
    \socket_if_exist:nT {hyp/link/URI/Contents}
      {
        \socket_new_plug:nnn {hyp/link/URI/Contents}{oer}
          {
            \tl_if_empty:NT \l__oer_link_contents_tl
              {
                \pdfstringdef \l_tmpa_tl {#1}
                \pdfannot_dict_put:nne {link/URI}{Contents}{(\l_tmpa_tl)}
              }
          }
        \socket_assign_plug:nn {hyp/link/URI/Contents}{oer}
      }
  }
\ExplSyntaxOff
"""


def is_ua1(standards):
    return any(s.lower().startswith("ua-1") for s in standards) and \
        not any(s.lower().startswith("ua-2") for s in standards)


def label_prefixes(resolved):
    """The words that begin a caption's own label, for pdf-target.lua,
    which sets such a caption without a label of LaTeX's, in a book's PDF
    and a deck's: the captions settings figures-and-tables.lua reads them
    from."""
    return {"TABLE_LABEL_PREFIXES": ",".join(map(str, resolved["captions.table_prefixes"])),
            "FIGURE_LABEL_PREFIXES": ",".join(map(str, resolved["captions.figure_prefixes"]))}


# A formula's term struck out, in a book's PDF and a deck's (PDF_MACROS),
# and in a LaTeX book's that loads cancel (texremediate.tag).
CANCEL_STROKES = r"""% A formula's term struck out with the cancel package (\cancel,
% \bcancel, and \xcancel, which texmath writes for MathML's diagonal
% strikes, and \cancelto): cancel draws each stroke with picture mode's
% \line, and \cancelto's arrow with \vector, which set glyphs of LaTeX's
% line10 font, whose map to Unicode has only a space, and veraPDF failed
% College Algebra 2e's first chapter on two of them (PDF/UA-2's 8.4.5.8).
% pict2e draws picture mode's lines and arrows as paths, with no font.
% cancel, given pict2e, asks for LaTeX's own commands
% (\OriginalPictureCmds), its comment saying pict2e's have no bounding
% box, which pict2e's \line has now; told to use pict2e's, it draws each
% stroke where it did (measured: \cancel, \bcancel, \xcancel, and
% \cancelto, in text, in a script, and displayed). pict2e is loaded at the
% end of the preamble, after any pict2e the document loads with options
% of its own, and only where cancel is, since it has drawing commands of
% its own, \arc, \Line, \polygon, \moveto, and the rest, which, loaded so
% late, replaced a document's own \arc, on which LaTeX then stopped
% ("Missing number"), and stopped LaTeX on a \newcommand of one in the
% text ("already defined"). So those names are set aside before it loads
% and, at \begin{document}, given back as the document had them or taken
% away. Not \maxovalrad, which pict2e's \oval reads, nor the trig
% package's names (\UseSin and the rest), which pict2e loads.
\ExplSyntaxOn
\clist_const:Nn \c__oer_pictiie_names_clist
  {
    arc, pIIearc, Line, polyline, Vector, polyvector, polygon, moveto,
    lineto, curveto, circlearc, closepath, strokepath, fillpath, buttcap,
    roundcap, squarecap, miterjoin, roundjoin, beveljoin, ltxarrows,
    pstarrows, cbezier
  }
\AddToHook { begindocument / before }
  {
    \IfPackageLoadedT { cancel }
      {
        \IfPackageLoadedF { pict2e }
          {
            \clist_map_inline:Nn \c__oer_pictiie_names_clist
              {
                \cs_set_eq:cc { __oer_pictiie_ #1 : } {#1}
                \cs_undefine:c {#1}
              }
            \RequirePackage { pict2e }
            \AddToHook { begindocument / end }
              {
                \clist_map_inline:Nn \c__oer_pictiie_names_clist
                  {
                    \cs_if_exist:cTF { __oer_pictiie_ #1 : }
                      { \cs_set_eq:cc {#1} { __oer_pictiie_ #1 : } }
                      { \cs_undefine:c {#1} }
                  }
              }
          }
        \cs_set_eq:NN \OriginalPictureCmds \scan_stop:
      }
  }
\ExplSyntaxOff
"""


# Written into a tagged PDF's preamble, by build-pdf.py after the metadata
# file's own header-includes, and by a deck's template (decks.py).
# math/setup names both forms of MathML luamml makes (it needs
# unicode-math, which Pandoc's template loads under LuaLaTeX): structure
# elements under each formula, and a MathML file attached to it. The key
# switches every form off before applying the ones listed (read in
# latex-lab-math.ltx), so both are named rather than left to defaults
# that could change. The link commands are
# the ones pdf-target.lua puts around every link; LaTeX's own default
# /Contents -- the address, or "Go to destination" and an id -- is
# switched off, since every link the book's text makes gets one here.
PDF_MACROS = r"""\ExplSyntaxOn
% A long table's cells that a row span covers are recorded as untagged
% (table/multirow), and the record outlives the table: measured, every
% table after one with spans lost the cells at the same positions. Each
% long table starts with none.
\AddToHook{env/longtable/begin}
  {
    \prop_if_exist:NT \g__tbl_untagged_cells_prop
      { \prop_gclear:N \g__tbl_untagged_cells_prop }
  }
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
    \tl_clear:N \l__oer_link_contents_tl
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
% A table of class unnumbered that has a caption is written in a group
% that sets \LTcaptype to none, and the caption package, which the
% template loads, stopped at its \caption ("No float type 'none'
% defined"), looking for the list such a table goes in (\ext@none). A list
% nothing opens takes it, and the caption has no label, as an unnumbered
% one hasn't.
\cs_if_exist:cF { ext@none } { \cs_gset:cpn { ext@none } { none } }
\AddToHook { begindocument/before }
  {
    \IfPackageLoadedT { caption }
      { \captionsetup [ none ] { labelformat = empty , labelsep = none } }
  }
% A caption that carries its own label, "Figure 1.1 The real number line",
% which LaTeX numbered again ("Figure 1: Figure 1.1 ..."), and an
% unnumbered figure's, which LaTeX numbered: pdf-target.lua sets such a
% figure or table in a group with \OERNoCaptionLabel, and its caption gets
% no label. Tagged, a figure's caption is LaTeX's own
% (latex-lab-testphase-float.sty): its label is the caption/label socket's,
% "#1:~", which the caption package doesn't reach, between two tagging
% sockets that switch paragraph tagging off, open a Lbl, and close it and
% switch paragraph tagging on again. Here the label is nothing, and the
% two only switch paragraph tagging off, starting the paragraph as the
% label would have, and on, so the caption's Caption holds its paragraph
% and no empty Lbl; made noop, they had left LaTeX's paragraph tagging one
% short at a caption too long to center. A long table's caption, and an
% untagged figure's, is the caption package's, when the template loads it
% (for a book with tables), told to give none; an untagged figure's without
% it is set as LaTeX's standard classes set one, without the label. A long
% table's without it, as in a deck's PDF, where ltx-talk's label is
% "Table:", is longtable's, which an empty \LTcaptype sets with no label
% and no number (longtable 4.27).
\socket_if_exist:nT { tagsupport / caption / label / begin }
  {
    \NewTaggingSocketPlug { caption / label / begin } { oer-own-label }
      { \tagpdfparaOff \mode_leave_vertical: }
    \NewTaggingSocketPlug { caption / label / end } { oer-own-label }
      { \tagpdfparaOn }
  }
\box_new:N \l__oer_caption_box
\cs_new_protected:Npn \__oer_unlabeled_caption:nn #1 #2
  {
    \skip_vertical:N \abovecaptionskip
    \hbox_set:Nn \l__oer_caption_box {#2}
    \dim_compare:nNnTF { \box_wd:N \l__oer_caption_box } > \hsize
      { #2 \par }
      {
        \tex_global:D \use:c { @minipagefalse }
        \hbox_to_wd:nn \hsize { \hfil \box_use:N \l__oer_caption_box \hfil }
      }
    \skip_vertical:N \belowcaptionskip
  }
\NewDocumentCommand \OERNoCaptionLabel { }
  {
    \socket_if_exist:nTF { caption / label }
      {
        \socket_assign_plug:nn { caption / label } { noop }
        \AssignTaggingSocketPlug { caption / label / begin } { oer-own-label }
        \AssignTaggingSocketPlug { caption / label / end } { oer-own-label }
      }
      {
        \IfPackageLoadedF { caption }
          { \cs_set_eq:cN { @makecaption } \__oer_unlabeled_caption:nn }
      }
    \IfPackageLoadedTF { caption }
      { \captionsetup { labelformat = empty , labelsep = none } }
      { \tl_set:Nn \LTcaptype { } }
  }
% A footnote's mark in a figure's caption took a number for each time
% LaTeX set the caption: a tagged PDF's figure caption is set twice
% (latex-lab-testphase-float.sty's \@makecaption sets it in a box, its
% tagging suspended, to measure it, then again), as an untagged one too
% long for its line is where the caption package isn't loaded, and the
% mark stepped the footnote counter both times, so the note took the
% second number and the first went to none. pdf-target.lua opens a
% caption holding a note with \OERCaptionNotes and a number of its own:
% the first time the caption is set, the counter is noted, and each time
% after, it's set back.
\int_new:N \g__oer_caption_notes_int
\int_new:N \g__oer_caption_footnote_int
\NewDocumentCommand \OERCaptionNotes { m }
  {
    \int_compare:nNnTF {#1} = { \g__oer_caption_notes_int }
      { \int_gset_eq:cN { c@footnote } \g__oer_caption_footnote_int }
      {
        \int_gset:Nn \g__oer_caption_notes_int {#1}
        \int_gset_eq:Nc \g__oer_caption_footnote_int { c@footnote }
      }
  }
% A passage in another language (pdf-target.lua): a span or a link a Span
% with its /Lang, opened in the paragraph, and a div's blocks in
% oerlanguage, whose structure elements take its /Lang; untagged, the
% words alone. babel's own commands, inside them, set its hyphenation and
% tag nothing. Its words alone in a structure element's title and a
% bookmark.
\NewDocumentCommand \oerlang { m +m }
  {
    \cs_if_exist:NTF \tag_mc_end_push:
      {
        \mode_leave_vertical:
        \tag_mc_end_push:
        \tag_struct_begin:n { tag = Span , lang = #1 }
        \tag_mc_begin:n { }
        #2
        \tag_mc_end:
        \tag_struct_end:
        \tag_mc_begin_pop:n { }
      }
      { #2 }
  }
\NewDocumentEnvironment { oerlanguage } { m }
  {
    \par
    \keys_if_exist:nnT { __tag / setup } { text / lang }
      { \tagpdfsetup { text / lang = #1 } }
  }
  { \par }
\text_declare_purify_equivalent:Nn \oerlang { \use_ii:nn }
\AddToHook { package / hyperref / after }
  { \pdfstringdefDisableCommands { \cs_set:Npn \oerlang #1#2 {#2} } }
% A box (a div of class box), set off by a rule above it and one below,
% each an artifact, kept with the box's first and last lines. Above, LaTeX
% is left as a heading leaves it (\@afterheading), so a heading that opens
% the box, as a box's legend does, isn't preceded by the place to break a
% page every heading has: the rule had stayed at a page's foot, its box on
% the next page. A paragraph that opens the box is indented, where the
% book indents them, as it was before. Below, that's ended, if nothing in
% the box began a paragraph, as a figure alone doesn't: the heading after
% it had lost its space above. Neither touches \everypar while a list's
% item, a quotation's, or a definition's label waits for the item's first
% paragraph, which an untagged build sets it beside from \everypar: a box
% that opened one had stopped LaTeX ("perhaps a missing \item").
\NewDocumentCommand \OERBoxRule { m }
  {
    \par
    \str_if_eq:nnTF {#1} { above }
      { \skip_vertical:N \bigskipamount }
      { \nobreak \skip_vertical:N \medskipamount }
    \cs_if_exist:NT \tag_mc_begin:n { \tag_mc_begin:n { artifact } }
    \hrule height 0.4pt
    \cs_if_exist:NT \tag_mc_end: { \tag_mc_end: }
    \str_if_eq:nnTF {#1} { above }
      {
        \nobreak \skip_vertical:N \medskipamount
        \legacy_if:nF { @inlabel }
          { \use:c { @afterindenttrue } \use:c { @afterheading } }
      }
      {
        \skip_vertical:N \bigskipamount
        \use:c { @nobreakfalse } \clubpenalty = \use:c { @clubpenalty }
        \legacy_if:nF { @inlabel } { \everypar { } }
      }
  }
% A line too wide in the contents, or in a list of figures or tables, is
% reported by TeX at a line of the list's own file (book.toc), which the
% build had looked up in the book's LaTeX: Sociology's front matter's page
% numbers, too wide for the contents' column, were counted as lines of
% text. The log marks where each list is set, whatever class or package
% sets it, for latexbuild.overfull_lines.
\AddToHook { begindocument / end }
  {
    \cs_set_eq:Nc \__oer_start_toc:n { @starttoc }
    \cs_set_protected:cpn { @starttoc } #1
      {
        \typeout { TextbookImprover~list:~#1 }
        \__oer_start_toc:n {#1}
        \typeout { TextbookImprover~list~end }
      }
  }
% A fill-in blank (\OERBlank, below): its underscores in a bookmark and in
% a structure element's title.
\text_declare_purify_equivalent:Nn \OERBlank { \use:n }
\AddToHook { package / hyperref / after }
  { \pdfstringdefDisableCommands { \cs_set:Npn \OERBlank #1 {#1} } }
\ExplSyntaxOff
""" + CANCEL_STROKES + r"""% A fill-in blank, a run of four or more underscores pdf-target.lua marks
% (\OERBlank), that runs past the end of its line into the margin: TeX
% can't break a run of underscores, and Sociology's chapter 19 quiz had a
% question whose blank ran 24 points past its line. Once a paragraph's
% lines are made, such a blank is drawn shorter, its underscores
% overlapping, so it ends where the line does and the line's spaces are
% their natural width again. Every underscore is still in the text, for a
% screen reader and for copying, and a blank that fits its line is left as
% it is. A blank is drawn no shorter than three underscores; a line that
% leaves less room than that still runs over. TeX has named the line as
% too wide (overfull) by then, so the log names each line fitted this way
% too: how much too wide TeX said it was, the line of LaTeX TeX said its
% paragraph ended on, and how much too wide it is now, which
% latexbuild.overfull_lines reads. The Lua is written without a percent
% sign, a hash, a tilde, or a backslash, which TeX would read as its own,
% and without a comment, which would run on to the end, TeX joining the
% lines.
\ifdefined\directlua
  \newattribute\OERBlankAttribute
  \NewDocumentCommand\OERBlank{m}
    {\leavevmode\setattribute\OERBlankAttribute{1}#1\unsetattribute\OERBlankAttribute}
  \directlua{
    local attribute = luatexbase.attributes.OERBlankAttribute
    local GLYPH, GLUE, KERN, HLIST = node.id("glyph"), node.id("glue"), node.id("kern"), node.id("hlist")
    local function points(s)
      local out = tostring(s // 65536) .. "."
      s = 10 * (s - (s // 65536) * 65536) + 5
      local delta = 10
      repeat
        if delta > 65536 then s = s + 32768 - 50000 end
        out = out .. tostring(s // 65536)
        s = 10 * (s - (s // 65536) * 65536)
        delta = delta * 10
      until s <= delta
      return out
    end
    local function fit(line)
      local over = node.dimensions(line.glue_set, line.glue_sign, line.glue_order, line.head) - line.width
      if over <= tex.hfuzz then return end
      local runs, count, run = {}, 0, nil
      for n in node.traverse(line.head) do
        if n.id == GLYPH and n.char == 95 and node.has_attribute(n, attribute) then
          if run then
            run.size = run.size + 1
            run.glyphs[run.size] = n
          else
            run = { glyphs = { n }, size = 1 }
            count = count + 1
            runs[count] = run
          end
        elseif not (n.id == KERN) then
          run = nil
        end
      end
      if count == 0 then return end
      local shrink = 0
      for glue in node.traverse_id(GLUE, line.head) do
        if glue.shrink_order == 0 then shrink = shrink + glue.shrink end
      end
      local need = over + shrink
      for i = 1, count do
        run = runs[i]
        if need > 0 and run.size > 3 and node.dimensions(line.glue_set, line.glue_sign,
            line.glue_order, line.head, run.glyphs[run.size].next) > line.width then
          local width = node.dimensions(run.glyphs[1], run.glyphs[run.size].next)
          local take = math.min(need, width - width * 3 // run.size)
          local each = take // (run.size - 1)
          local left = take - each * (run.size - 1)
          for j = 1, run.size - 1 do
            local kern = node.new(KERN, 1)
            kern.kern = 0 - each - ((j <= left) and 1 or 0)
            node.insert_after(line.head, run.glyphs[j], kern)
          end
          need = need - take
        end
      end
      if need == over + shrink then return end
      if need == 0 then
        line.glue_set, line.glue_sign, line.glue_order = 0, 0, 0
      elseif need < shrink then
        line.glue_set, line.glue_sign, line.glue_order = need / shrink, 2, 0
      else
        line.glue_set, line.glue_order = 1, 0
      end
      texio.write_nl("term and log", "TextbookImprover blank: " .. points(over)
        .. "pt over at line " .. tostring(tex.inputlineno) .. ", now "
        .. points(math.max(0, need - shrink)) .. "pt")
      texio.write_nl("term and log", "")
    end
    luatexbase.add_to_callback("post_linebreak_filter", function(head)
      for line in node.traverse_id(HLIST, head) do
        if line.subtype == 1 and not (line.glue_sign == 1) then fit(line) end
      end
      return true
    end, "oer.blanks")
  }
\else
  \NewDocumentCommand\OERBlank{m}{#1}
\fi
"""


def missing_characters(lines):
    """{character: times} LaTeX's log says a font didn't have, and the
    lines that aren't about that."""
    missing, others = {}, []
    for line in lines:
        m = MISSING.search(line)
        if m:
            missing[m.group(1)] = missing.get(m.group(1), 0) + 1
        elif line.strip():
            others.append(line)
    return missing, others


def missing_warning(missing, advice):
    """One line for the characters missing from a PDF, not one per time."""
    return (f"WARNING: {sum(missing.values())} character(s) the fonts don't have "
            "are missing from the PDF: "
            + ", ".join(f"{c} (U+{ord(c[0]):04X}) x{n}" for c, n in
                        sorted(missing.items(), key=lambda i: -i[1]))
            + ". " + advice)


_TEX_ROOT = []


def tlmgr_command(words):
    """tlmgr and its arguments as they're to be typed here: with sudo
    before them when the TeX tree tlmgr manages isn't the user's to write,
    as a TeX Live installed with sudo (/usr/local/texlive) isn't, where
    TinyTeX, in the home folder, is. After sudo, tlmgr is named by its
    path, the one beside the kpsewhich asked: sudo looks for a program in
    a list of folders of its own (Ubuntu's secure_path), which TeX Live's
    isn't in, so `sudo tlmgr` isn't found, or runs a distribution's tlmgr
    in its place; and tlmgr puts its own folder first on the path of the
    programs it runs (tlmgr.pl's BEGIN block), so its path is all sudo
    needs."""
    if not _TEX_ROOT:
        root = ""
        if shutil.which("kpsewhich"):
            try:
                root = subprocess.run(["kpsewhich", "-var-value=TEXMFROOT"],
                                      capture_output=True, text=True,
                                      stdin=subprocess.DEVNULL).stdout.strip()
            except OSError:
                root = ""
        _TEX_ROOT.append(root)
    root = _TEX_ROOT[0]
    if not (root and os.path.isdir(root) and not os.access(root, os.W_OK)):
        return "tlmgr " + words
    found = shutil.which("kpsewhich")
    path = os.path.join(os.path.dirname(found), "tlmgr") if found else ""
    if not os.path.isfile(path):
        path = shutil.which("tlmgr") or ""
    return "sudo " + (shlex.quote(path) if path else "tlmgr") + " " + words


# LaTeX's report of a line it couldn't fit to its width (TeXbook ch. 14,
# \hbadness and \hfuzz): where the box came from, a paragraph's lines, an
# alignment's rows (a table), or a box made whole (a display formula).
OVERFULL = re.compile(r"^Overfull \\hbox \((\d+(?:\.\d+)?)pt too wide\) "
                      r"(?:in paragraph at lines (\d+)--(\d+)|in alignment at lines (\d+)--\d+"
                      r"|detected at line (\d+))", re.M)
# A line whose fill-in blank PDF_MACROS drew shorter to fit it, which TeX
# had already reported: how much too wide TeX said it was, the line of
# LaTeX its paragraph ended on, as TeX's report names it, and how much too
# wide it is now.
SHORTENED = re.compile(r"^TextbookImprover blank: (\d+(?:\.\d+)?)pt over at line (\d+), "
                       r"now (\d+(?:\.\d+)?)pt", re.M)
# Where LaTeX sets the contents, or a list of figures or tables, as
# PDF_MACROS marks it (the list's file's extension, toc for the contents),
# and where it's done: a line too wide there is the list's, reported at a
# line of the list's own file.
LISTS = re.compile(r"^TextbookImprover list(?:: (\S+)| end)$", re.M)
# How much wider than its text a line has to be to be named: a point or
# two sits in the margin unseen, but more shows.
OVERFULL_LEAST = 3.0
LABEL = re.compile(r"\\label\{(page-[^}]*)\}")


def overfull_lines(output, source, pages):
    """[(points, kind, page)] for each line LaTeX set wider than its text,
    or a table's column, by more than OVERFULL_LEAST points, from what a LaTeX run said
    (output) about its input (source): kind is table (a row, or a cell's
    line, of a longtable), formula (a display), or text, and page the
    book's page it's on, the last of pages ({label: stem}, its id as
    page_id gives it) whose label is at or before it. A line whose blank
    was drawn shorter to fit it (SHORTENED) is as wide as it is now. A line
    of the contents is kind contents, and one of another list (LISTS) kind
    list, on no page."""
    lists, opened = [], None
    for m in LISTS.finditer(output):
        if m.group(1):
            opened = (m.end(), m.group(1))
        elif opened:
            lists.append((opened[0], m.start(), opened[1]))
            opened = None
    if opened:
        lists.append((opened[0], len(output), opened[1]))
    shortened = {}
    for m in SHORTENED.finditer(output):
        shortened.setdefault(int(m.group(2)), []).append((float(m.group(1)), float(m.group(3))))
    lines = source.split("\n")
    owner, current, table, inside = [], None, [], False
    for text in lines:
        for label in LABEL.findall(text):
            current = pages.get(label, current)
        owner.append(current)
        if "\\begin{longtable}" in text:
            inside = True
        table.append(inside)
        if "\\end{longtable}" in text:
            inside = False
    found = []
    for m in OVERFULL.finditer(output):
        points = float(m.group(1))
        fitted = shortened.get(int(m.group(3) or 0), [])
        match = next((f for f in fitted if abs(f[0] - points) < 0.001), None)
        if match:
            fitted.remove(match)
            points = match[1]
        if points <= OVERFULL_LEAST:
            continue
        listed = next((name for start, end, name in lists if start <= m.start() < end), None)
        if listed:
            found.append((points, "contents" if listed == "toc" else "list", None))
            continue
        line = int(m.group(2) or m.group(4) or m.group(5)) - 1
        if not 0 <= line < len(lines):
            continue
        if m.group(4) or table[line]:
            kind = "table"
        elif m.group(5) and re.search(r"\\\[|\\\]|\\(?:begin|end)\{(?:equation|align|gather|multline)",
                                      "\n".join(lines[max(0, line - 3):line + 1])):
            kind = "formula"
        else:
            kind = "text"
        found.append((points, kind, owner[line]))
    return found


def overfull_warning(found, where="PDF"):
    """One line for what overfull_lines found, or None."""
    if not found:
        return None
    kinds = {"table": "in table(s)", "formula": "display formula(s)",
             "text": "line(s) of text", "contents": "in the contents",
             "list": "in a list of figures or tables"}
    one = {"table": "in a table", "formula": "a display formula", "text": "a line of text",
           "contents": "in the contents", "list": "in a list of figures or tables"}
    counts = {}
    for _points, kind, _page in found:
        counts[kind] = counts.get(kind, 0) + 1
    widest = max(found, key=lambda f: f[0])
    pages = list(dict.fromkeys(page for _points, _kind, page in
                               sorted(found, key=lambda f: -f[0]) if page))
    return (f"WARNING: {len(found)} line(s) of the {where} are more than "
            f"{OVERFULL_LEAST:g} points wider than the text or table column they're set in, "
            f"so they run into the margin, past the page's edge, or into the next column: "
            + ", ".join(f"{counts[k]} {kinds[k]}" for k in kinds if k in counts)
            + f"; the widest is {one[widest[1]]}" + (f" on {widest[2]}" if widest[2] else "")
            + f", {widest[0]:,.0f} points too wide"
            + (f"; on {len(pages)} page(s), widest first: " + ", ".join(pages[:6])
               + (f", and {len(pages) - 6} more" if len(pages) > 6 else "") if pages else "")
            + ".")


def failure_advice(log):
    """What to do about a failed build, from its log: a file LaTeX can't
    find, the two packages a struck-out term needs among them, a language
    babel hasn't, a font that isn't installed, or one of TeX's tables
    outgrown."""
    said = []
    missing = list(dict.fromkeys(MISSING_FILE.findall(log)))
    # A formula's term struck out: Pandoc's template loads cancel for it in
    # the preamble, and CANCEL_STROKES loads pict2e at \begin{document},
    # neither of which TinyTeX or TeX Live's medium scheme has, so a build
    # stops on cancel.sty and, once that's installed, on pict2e.sty, which
    # the book never names. Both are named at once; a book that loads
    # pict2e for drawings of its own is told the same, cancel included.
    if {"cancel.sty", "pict2e.sty"} & set(missing):
        said.append("LaTeX can't find cancel.sty or pict2e.sty. A formula's struck-out term "
                    "(\\cancel, \\bcancel, or \\xcancel) needs TeX's cancel package and "
                    "pict2e, which the run loads with cancel to draw the strokes as paths, "
                    "and a book can load pict2e for drawings of its own. For TinyTeX or TeX "
                    f"Live from tug.org, `{tlmgr_command('install cancel pict2e')}` installs "
                    "both; for Debian's or Ubuntu's texlive packages, `sudo apt install "
                    "texlive-latex-extra texlive-pictures`.")
    # tlmgr only manages a TeX Live installed from tug.org or as TinyTeX;
    # Debian's and Ubuntu's texlive packages come with a tlmgr that runs in
    # an uninitialized user mode and installs nothing, so both routes are
    # named.
    for name in missing:
        if name in ("cancel.sty", "pict2e.sty"):
            continue
        said.append(f"LaTeX can't find {name}. For TinyTeX or TeX Live "
                    f"from tug.org, `{tlmgr_command('search --global --file /' + name)}` "
                    f"names the package that has it, and `{tlmgr_command('install')}` "
                    "installs that. For a distribution's texlive packages, "
                    "its package manager does (`apt-file search "
                    f"{name}` on Debian and Ubuntu).")
    # The book's language or a passage's, which babel reads from a file of
    # the language's name (ngerman.ldf, in babel-german), and without which
    # it stops; its hyphenation patterns are in the language's hyphen-
    # package, without which babel says so in the log and hyphenates the
    # language by another's. On Debian and Ubuntu both are in one
    # texlive-lang- package (texlive-lang-spanish for Spanish).
    for name in dict.fromkeys(BABEL_UNKNOWN.findall(log)):
        said.append(f"babel has no language {name}, which the book, or a passage of it, is "
                    "in. For TinyTeX or TeX Live from tug.org, "
                    f"`{tlmgr_command('search --global --file /' + name + '.ldf')}` names the "
                    "package that has it (babel-german for ngerman), and the language's "
                    "hyphen- package has its hyphenation (hyphen-german for German); "
                    f"`{tlmgr_command('install')}` installs both. For a distribution's "
                    f"texlive packages, `apt-file search /{name}.ldf` names the one that has "
                    "both on Debian and Ubuntu (texlive-lang-german for German). A full TeX "
                    "Live has every language.")
    # A face the PDF's metadata file names, an OpenStax book's among them
    # (cnx.project.DESIGNS), that isn't installed: Debian's and Ubuntu's
    # TeX Live leave Noto Sans to fonts-noto-core.
    joined = re.sub(r"\n\(fontspec\)\s*", " ", log)
    for name in dict.fromkeys(MISSING_FONT.findall(joined)):
        said.append(f"LaTeX can't find the font {name}. Install it, or name one that's "
                    "installed where it's chosen: for a PDF from the pages, the pdf.metadata "
                    "file (mainfont, sansfont, monofont, or mathfont), where taking its lines "
                    "out gives the default, Latin Modern. TeX Live has an OpenStax book's: "
                    "IBM Plex in its plex package, and Noto Sans in its noto package, or on "
                    "Debian and Ubuntu in fonts-noto-core.")
    # A tagged book can outgrow TeX's tables: tagging keeps every structure
    # element, and a large book runs out of strings, hash, or memory
    # (Prescott, TUGboat 47:2; pdfLaTeX on GIAM's tagged copy ran out of
    # main memory). A stack that overflows is usually a macro that calls
    # itself without end instead.
    # titlesec's \titleformat, which LaTeX's tagging can't build with; a
    # tagged copy loads it only when the tagging status list rates it
    # compatible, and defines its commands otherwise (texremediate.SHIMS).
    if "Package titlesec Error: No format for this command" in log:
        said.append("titlesec can't build with LaTeX's tagging (the tagging project "
                    "rated it currently incompatible), and the book sets its headings "
                    "with it: without its \\titleformat settings, and the package, "
                    "LaTeX's own headings would build. A source target with tagging on "
                    "writes a copy that doesn't load it, unless the status list "
                    "installed with TeX rates it compatible.")
    capacity = CAPACITY.search(log)
    if capacity:
        table = capacity.group(1).strip()
        if re.search(r"stack|grouping levels|nest|input levels", table):
            said.append(f"LaTeX ran out of {table}, which usually means a macro "
                        "that calls itself without end: the log above names "
                        "the line it was on.")
        else:
            said.append(f"LaTeX ran out of {table}: the book is bigger than TeX's "
                        "default limits allow, as a tagged book can be. Raise the "
                        "limit in texmf.cnf, or with the variable of the same name "
                        "in the environment (max_strings for strings, hash_extra "
                        "for the hash, extra_mem_top and extra_mem_bot for "
                        "pdfTeX's main memory), and run again "
                        "(https://tex.stackexchange.com/a/741777/).")
    return said


FILE_LINE_ERROR = re.compile(r"^[^:\n]+\.\w+:\d+: ")


def first_errors(log, limit=3):
    """The first errors in a LaTeX log, each with the lines that follow it
    up to the one naming where it was (l.123). With -file-line-error an
    error opens with its file and line, and a file's name can have spaces
    (FINC 308's "Topic 03 Financial Statements and Net Worth.tex:45: ")."""
    lines = log.splitlines()
    found = []
    for i, line in enumerate(lines):
        if "==> Fatal error occurred" in line:
            continue
        if line.startswith("! ") or FILE_LINE_ERROR.match(line):
            piece = [line]
            for follow in lines[i + 1:i + 8]:
                piece.append(follow)
                if re.match(r"^l\.\d+", follow):
                    break
            found.append("\n".join(piece))
            if len(found) == limit:
                break
    return found
