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


# A float's tags where the text has it, in a book's PDF and in a LaTeX
# book's (texremediate.FLOATS_HERE). LaTeX's tagging gathers the tags of
# every figure and table that floats into one place, at the end of the
# document unless flushed sooner (latex-lab-testphase-float.sty), where a
# screen reader reaches them after everything else. float/here tags each
# where the text has it; where it's printed doesn't change. The key came in
# latex-lab-float 0.81m (2025-12-04), after LaTeX 2025-11-01; the run
# builds only with a LaTeX that has it (MINIMUM_LATEX), and a copy built
# with an older one, or untagged, skips it.
FLOATS_HERE = ("\\ExplSyntaxOn\\keys_if_exist:nnT {__tag/setup} {float/here}\n"
               "  {\\tagpdfsetup{float/here}}\\ExplSyntaxOff\n")


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


# How small fitting sets something's type (FIT_MACROS): to fit its line,
# no smaller than FIT_FLOOR of its size; to keep it on the paper, a quarter
# inch inside its edge, no smaller than FIT_LEAST.
FIT_FLOOR = 0.75
FIT_LEAST = 0.5

# Something too wide for its line, in a book's PDF (PDF_MACROS), fitted to
# it as LaTeX measures it.
FIT_MACROS = r"""% Something too wide for its line, which TeX can't break:
% a table's columns side by side, or a formula, displayed or in text, as a
% worked example's steps are, an array, in College Algebra 2e (224 points
% too wide, in its first chapter). pdf-target.lua numbers each table not
% in a table's cell, each display formula, and each formula in text that
% is an environment (\OERFitTable, \OERFitFormula), and LaTeX measures
% each as it sets it: a table by the widths longtable records for its
% columns and, where its columns wrap (p columns), by any line of a cell
% longer than its column, its longest piece TeX can't break, a word or a
% formula's part between two of its breaks (post_linebreak_filter), a
% line taken as in a formula from its start where the first of a
% formula's edges in it is an end (the formula ran on from the line
% before, or TeX dropped its start at the break, as it drops glue there:
% TeXbook, chapter 14), and one with no formula's edge in it where it
% ends at a penalty, as TeX breaks a formula (before its right skip, and
% the node ending a text direction that babel's bidi puts there), and
% the next line opens in one (the middle line of a formula over three,
% or a formula that opens a line and breaks after an operator); a
% formula by the list TeX makes of it
% (post_mlist_to_hlist_filter). One wider than its line is fitted on the
% next run, from what this one measured, as Pandoc runs LaTeX again while
% its log asks, four times at most: first its spaces narrowed (a table's
% columns half an em apart, where they were 12 points; a formula's \qquad
% a quad, and an \mspace wider than a quad a quad, as a worked example's
% step is spaced from its reason, and an array's columns closer), then,
% where that's not enough, its type set smaller, as much as it takes, but
% to no less than three quarters of its size (9 points in 12-point type),
% a table's wrapping columns made as wide as its words need, which TeX
% then doesn't hyphenate: a smaller design, wider for its size (below),
% can leave a word a point wider than the column its fit made for it,
% which TeX broke (Twen-tytwo, in the PDF suite's fit book), where it now
% runs a point into the space beside its column. A wrapping table's
% columns are worked out with the spaces between them at the size it's set
% in: counted at the size the run before had, a table set larger on the
% second run than on the first, as one longtable's first widths under a
% head across its columns made too small is, had narrower columns than
% counted, and its longest word ran past one (Introductory Business
% Statistics 2e's Table A7, "denominator" 3.4 points). One whose spaces
% alone fill its line, as those of a table of 45 columns whose widths are
% given do on the default page, the writer giving its columns less than
% no width, has them narrowed on the first run and is fitted on the
% second, as its columns' words then ask. A table that isn't a longtable
% in its group, as the writer sets one of the class float, a tabular in a
% table float, isn't fitted: the widths longtable recorded were the last
% longtable's. A table or a
% display formula fitted is centered on the page, so that one still wider
% than its line runs into both margins alike; and one that would come
% within a quarter inch of the paper's edge even at three quarters of its
% size is set smaller still, as far as it takes, to half its size at
% least. Type set smaller isn't always as much narrower: Latin Modern
% Roman, the default face, has designs for sizes from 5 to 17 points, each
% wider for its size than the next larger (the 9-point 2.8 percent wider
% than the 10-point, the 8-point 3.3 percent wider than the 9-point), and
% in 12-point type unicode-math sets math of 10 points or less in the
% font's forms for subscripts (ssty), 13 percent wider. So whatever is too
% wide is fitted on the first run, a formula's spaces narrowed and its
% type set smaller at once, as its width before narrowing asks; and on the
% second each fit is measured again, and fitted again where it's off its
% line by more than 4 percent of it, too wide or too narrow, more than a
% design's step, less of which centering takes up, and a formula in text
% or a numbered display, which nothing centers, wherever it's too wide.
% longtable sets a table's columns by the widths it recorded the run
% before, and the first run's can be wrong: where a table's head is one
% row, a cell across columns, it gives the last of those columns the
% cell's whole width (Introductory Business Statistics 2e's F tables,
% whose head is "Degrees of freedom in the numerator" across ten columns:
% 816 points too wide on the first run, 254 on the second). The third run
% records the widths of the second's fit, which the fourth sets the
% columns by. Nothing is fitted after the second run, so that the third
% run's pages are the fourth's, and so are the labels the fourth reads
% from the third, a contents page's numbers among them: fitted on its
% third run as well, College Algebra 2e's first chapter ended its fourth
% with "Label(s) may have changed". The .aux file keeps what's fitted, and
% once something is, the run, counted as the second from the second on, so
% that the file stops changing, as latexmk and a deck's build wait for it
% to: counted as the run, it changed on every run, and latexmk stopped at
% its most; and a digest of each of the book's own .tex files LaTeX reads
% (by a path from its folder, not TeX's own): the main file, each it reads
% lines of once these macros are in, a chapter \include-d or a file read
% with TeX's own \input, and each read with LaTeX's \input{} before them,
% as a book's header-includes are, which its list of files has. So a book
% changed since, edited or laid out anew, is fitted as from its first
% run, no fit of the old set, where the count had said no more runs were
% to fit, and the old fits went by their numbers to what had them now: a
% formula of the latex target edited in place kept its old size, and one
% a wider margin made too wide wasn't fitted. The log says what's fitted,
% and what's still wider than its line, which latexbuild.fit_report reads.
% The Lua is written as the blanks' is (below), without a percent sign, a
% hash, a tilde, or a backslash.
\ifdefined\directlua
  \newattribute\OERFitAttribute
  \directlua{
    local attribute = luatexbase.attributes.OERFitAttribute
    local HLIST, VLIST, GLUE, PENALTY, MATH, DIR = node.id("hlist"), node.id("vlist"), node.id("glue"), node.id("penalty"), node.id("math"), node.id("dir")
    local FLOOR, LEAST, AIM, JUMP, TOLERANCE = """ + str(FIT_FLOOR) + ", " + str(FIT_LEAST) + r""", 0.98, 0.04, 32768
    oerfit = { state = {}, kind = {}, line = {}, room = {}, size = {}, columns = {},
               width = {}, tight = {}, sep = {}, sep0 = {}, where = {}, twocol = {}, run = 0,
               sources = { status.filename }, seen = { [status.filename] = true }, stored = {} }
    if string.sub(status.filename, 1, 2) == "./" then oerfit.seen[string.sub(status.filename, 3)] = true end
    local function current()
      local id = tex.getattribute(attribute)
      if id and id > 0 then return id end
      return nil
    end
    local function down(x, places)
      return math.floor(x * places) / places
    end
    local function points(sp)
      return tostring(math.floor(sp / 6553.6 + 0.5) / 10)
    end
    luatexbase.add_to_callback("post_mlist_to_hlist_filter", function(head)
      local id = current()
      if id and not (oerfit.kind[id] == "t" or oerfit.kind[id] == "p") then
        local w = node.dimensions(head)
        if w > (oerfit.width[id] or 0) then oerfit.width[id] = w end
      end
      return true
    end, "oer.fit.formulas")
    local function longest(line, inmath)
      local piece, most = 0, 0
      for n in node.traverse(line.head) do
        if n.id == MATH then
          inmath = n.subtype == 0
        end
        if (n.id == GLUE and not inmath) or (n.id == PENALTY and inmath and n.penalty < 10000) then
          if piece > most then most = piece end
          piece = 0
        elseif not (n.id == GLUE) then
          if not ((n.id == HLIST or n.id == VLIST) and math.abs(n.width - line.width) <= 1) then
            piece = piece + node.dimensions(n, n.next)
          end
        else
          piece = piece + n.width
        end
      end
      if piece > most then most = piece end
      return most
    end
    luatexbase.add_to_callback("post_linebreak_filter", function(head)
      local id = current()
      if id and oerfit.kind[id] == "p" then
        local lines, count, opens = {}, 0, false
        for line in node.traverse_id(HLIST, head) do
          if line.subtype == 1 then
            count = count + 1
            lines[count] = line
          end
        end
        for k = count, 1, -1 do
          local line, first = lines[k], nil
          for n in node.traverse_id(MATH, line.head) do
            first = n.subtype
            break
          end
          if first then
            opens = first == 1
          else
            local last = node.tail(line.head)
            while last and (last.id == GLUE or last.id == DIR) do last = last.prev end
            opens = opens and last and last.id == PENALTY or false
          end
          if line.width > 0 then
            local t = longest(line, opens) / line.width
            if t > (oerfit.tight[id] or 0) then oerfit.tight[id] = t end
          end
        end
      end
      return true
    end, "oer.fit.cells")
    function oerfit.open(id, kind, line, room, size, columns, where, sep0, twocol)
      oerfit.kind[id], oerfit.line[id], oerfit.room[id] = kind, line, room
      oerfit.size[id], oerfit.columns[id], oerfit.where[id] = size, columns, where
      oerfit.sep0[id], oerfit.twocol[id] = sep0, twocol
      local s = oerfit.state[id]
      if s then
        tex.sprint(string.char(92) .. "OERFitApply{" .. kind .. "}{" .. s.narrow .. "}{"
          .. s.factor .. "}{" .. s.columns .. "}{" .. s.center .. "}{" .. columns .. "}")
      end
    end
    function oerfit.table(id, width, sep)
      oerfit.width[id], oerfit.sep[id] = width, sep
    end
    function oerfit.next(kind, id, s, w, line, room, tight)
      local size = oerfit.size[id]
      local center = 0
      if kind == "d" then center = 1 end
      if not (kind == "t" or kind == "p") then
        local f = math.min(1, s.factor * line / w * AIM)
        if f >= FLOOR then return { narrow = 1, factor = down(f, 1000), columns = 1, center = center } end
        local least = FLOOR
        if w * FLOOR / s.factor > room then least = math.max(LEAST, down(s.factor * room / w * AIM, 1000)) end
        return { narrow = 1, factor = least, columns = 1, center = center }
      end
      local k = oerfit.columns[id]
      local sep = oerfit.sep[id] or 0
      local pad = 2 * (k - 1) * sep
      local narrow = 2 * (k - 1) * 0.25 * size
      if kind == "p" and line <= pad then
        if line <= narrow then return nil end
        return { narrow = 1, factor = 1, columns = 1, center = 1 }
      end
      if w <= pad then return nil end
      if kind == "t" then
        local content = (w - pad) / s.factor
        if content + 2 * (k - 1) * (oerfit.sep0[id] or sep) <= line then
          return { narrow = 0, factor = 1, columns = 1, center = 0 }
        end
        local f = line / (content + narrow) * AIM
        if f >= 1 then return { narrow = 1, factor = 1, columns = 1, center = 1 } end
        if f >= FLOOR then return { narrow = 1, factor = down(f, 1000), columns = 1, center = 1 } end
        local least = FLOOR
        if FLOOR * (content + narrow) > room then
          least = math.max(LEAST, down(room / (content + narrow) * AIM, 1000))
        end
        return { narrow = 1, factor = least, columns = 1, center = 1 }
      end
      local shares = (w - pad) / (s.columns * (line - pad))
      local c = math.min(1, 1 / shares)
      local b = tight * s.columns * (line - pad) / s.factor
      local f = AIM * line / (b / c + AIM * narrow)
      if f >= 1 then return { narrow = 1, factor = 1, columns = down(c, 10000), center = 1 } end
      if f >= FLOOR then return { narrow = 1, factor = down(f, 1000), columns = down(c, 10000), center = 1 } end
      local least, per = FLOOR, b * shares / AIM + narrow
      if FLOOR * per > room then least = math.max(LEAST, down(room / per * AIM, 1000)) end
      if line <= narrow * least then return nil end
      return { narrow = 1, factor = least, columns = down(least * b / (AIM * (line - narrow * least)), 10000),
               center = 1 }
    end
    local function sorted(list)
      local ids, count = {}, 0
      for id in pairs(list) do
        count = count + 1
        ids[count] = id
      end
      table.sort(ids)
      return ids, count
    end
    local function digest(name)
      local f = io.open(name, "rb")
      if not f then return "none" end
      local text = f:read("a") or ""
      f:close()
      return md5.sumhexa(text)
    end
    local function hex(s)
      local out = {}
      for i = 1, string.len(s) do out[i] = string.format(string.char(37) .. "02x", string.byte(s, i)) end
      return table.concat(out)
    end
    function oerfit.unhex(h)
      local out = {}
      for i = 1, string.len(h) - 1, 2 do out[(i + 1) // 2] = string.char(tonumber(string.sub(h, i, i + 1), 16)) end
      return table.concat(out)
    end
    local function source(name)
      if string.sub(name, 1, 2) == "./" then name = string.sub(name, 3) end
      if not (string.lower(string.sub(name, -4)) == ".tex") then name = name .. ".tex" end
      if oerfit.seen[name] or string.sub(name, 1, 1) == "/" then return end
      oerfit.seen[name] = true
      local f = io.open(name, "rb")
      if f then
        f:close()
        table.insert(oerfit.sources, name)
      end
    end
    local reading = status.filename
    luatexbase.add_to_callback("process_input_buffer", function(line)
      if not (status.filename == reading) then
        reading = status.filename
        source(reading)
      end
      return line
    end, "oer.fit.sources")
    function oerfit.check()
      for name in string.gmatch(token.get_macro("@filelist") or "", "[^,]+") do
        source((string.gsub(name, "[{} ]", "")))
      end
      for name, sum in pairs(oerfit.stored) do
        if not (digest(name) == sum) then
          oerfit.state, oerfit.run = {}, 0
          texio.write_nl("log", "TextbookImprover fit: " .. name .. " has changed since the fits were decided")
          return
        end
      end
    end
    function oerfit.decide()
      local run = oerfit.run + 1
      local changed, narrowed, smaller, smallest, wide = 0, 0, 0, 1, {}
      for id, kind in pairs(oerfit.kind) do
        local s = oerfit.state[id] or { narrow = 0, factor = 1, columns = 1, center = 0 }
        local w, line, room = oerfit.width[id], oerfit.line[id], oerfit.room[id]
        local tight = oerfit.tight[id] or 0
        local over = w and w > line + TOLERANCE
        local cells = kind == "p" and tight > 1.002
        if over or cells then
          local onpaper = 1
          if w and w > room then onpaper = 0 end
          wide[id] = kind .. " " .. points(math.max(0, (w or 0) - line)) .. " " .. oerfit.where[id]
            .. " " .. s.factor .. " " .. s.center .. " " .. onpaper .. " " .. (oerfit.twocol[id] or 0)
        end
        local far = w and (w > (1 + JUMP) * line or w < (1 - JUMP) * line) or tight > 1 + JUMP
        local new, refit = nil, false
        if w and run == 1 and (over or cells) then
          new = oerfit.next(kind, id, s, w, line, room, math.max(tight, 0.05))
        elseif w and run == 2 and (oerfit.state[id] and (far or (kind == "i" or kind == "e") and over)
                                   or not oerfit.state[id] and (over or cells)) then
          new, refit = oerfit.next(kind, id, s, w, line, room, math.max(tight, 0.05)), true
        end
        if new and ((refit and (not (new.narrow == s.narrow) or not (new.center == s.center)
                                or math.abs(new.factor - s.factor) > 0.0005
                                or math.abs(new.columns - s.columns) > 0.00005))
                    or new.narrow > s.narrow or new.center > s.center
                    or new.factor < s.factor - 0.0005) then
          oerfit.state[id], s = new, new
          changed = changed + 1
        end
        if s.narrow == 1 and s.factor >= 1 then narrowed = narrowed + 1 end
        if s.factor < 1 then
          smaller = smaller + 1
          if s.factor < smallest then smallest = s.factor end
        end
      end
      local ids, count = sorted(oerfit.state)
      for _, id in ipairs(ids) do
        local s = oerfit.state[id]
        tex.sprint(string.char(92) .. "OERFitWrite{" .. id .. "}{" .. s.narrow .. "}{" .. s.factor
          .. "}{" .. s.columns .. "}{" .. s.center .. "}")
      end
      if count > 0 then
        tex.sprint(string.char(92) .. "OERFitWriteRun{" .. math.min(run, 2) .. "}")
        for _, name in ipairs(oerfit.sources) do
          tex.sprint(string.char(92) .. "OERFitWriteSource{" .. hex(name) .. "}{" .. digest(name) .. "}")
        end
      end
      texio.write_nl("term and log", "TextbookImprover fit: run " .. run .. ", " .. narrowed
        .. " narrowed, " .. smaller .. " smaller, smallest " .. smallest)
      for id, said in pairs(wide) do
        texio.write_nl("term and log", "TextbookImprover fit wide: " .. said)
      end
      if changed > 0 then
        texio.write_nl("term and log", "Package TextbookImprover Warning: " .. changed
          .. " fitted to their lines. Rerun LaTeX.")
      end
      texio.write_nl("term and log", "")
    end
  }
  \ExplSyntaxOn
  \dim_new:N \g__oer_fit_dim
  \dim_new:N \l__oer_fit_margin_dim
  \muskip_new:N \l__oer_fit_muskip
  \cs_new_protected:Npn \OERFitState #1#2#3#4#5
    { \directlua { oerfit.state[#1] = { narrow = #2, factor = #3, columns = #4, center = #5 } } }
  \cs_new_protected:Npn \OERFitRun #1 { \directlua { oerfit.run = #1 } }
  \cs_new_protected:Npn \OERFitSource #1#2 { \directlua { oerfit.stored[oerfit.unhex("#1")] = "#2" } }
  \cs_new_protected:Npn \OERFitWrite #1#2#3#4#5
    { \exp_args:Nc \iow_now:Ne { @auxout } { \token_to_str:N \OERFitState {#1}{#2}{#3}{#4}{#5} } }
  \cs_new_protected:Npn \OERFitWriteRun #1
    { \exp_args:Nc \iow_now:Ne { @auxout } { \token_to_str:N \OERFitRun {#1} } }
  \cs_new_protected:Npn \OERFitWriteSource #1#2
    { \exp_args:Nc \iow_now:Ne { @auxout } { \token_to_str:N \OERFitSource {#1}{#2} } }
  % Before any fit the .aux file keeps is set, whether a file of the book
  % has changed since: one LaTeX has read lines of since these macros, or
  % input with \input{} before them, as its list of files says.
  \AddToHook { begindocument } { \directlua { oerfit.check() } }
  \AddToHook { enddocument / afterlastpage }
    { \legacy_if:nT { @filesw } { \directlua { oerfit.decide() } } }
  % The margin a centered table or display, or a formula in text, may run
  % into: the narrower of the page's margins, on either side of a
  % two-sided page, less a quarter inch at the paper's edge; none on a page
  % of two columns, where it would be the other column.
  \cs_new_protected:Npn \__oer_fit_margin:
    {
      \dim_set:Nn \l__oer_fit_margin_dim
        {
          \dim_min:nn
            {
              \dim_min:nn { 1in + \hoffset + \oddsidemargin } { 1in + \hoffset + \evensidemargin }
            }
            {
              \dim_min:nn { \paperwidth - 1in - \hoffset - \oddsidemargin - \textwidth }
                { \paperwidth - 1in - \hoffset - \evensidemargin - \textwidth }
            }
          - 0.25in
        }
      \dim_compare:nNnT \l__oer_fit_margin_dim < { 0pt } { \dim_zero:N \l__oer_fit_margin_dim }
      \legacy_if:nT { @twocolumn } { \dim_zero:N \l__oer_fit_margin_dim }
    }
  \cs_new_protected:Npn \__oer_fit_size:n #1
    {
      \fontsize { \fp_eval:n { #1 * \use:c { f@size } } pt }
        { \fp_eval:n { #1 * \dim_to_fp:n { \use:c { f@baselineskip } } } pt }
      \selectfont
    }
  % A display's type, its line spacing kept: TeX breaks the lines before it
  % in its paragraph as the display begins, inside the group, so smaller
  % spacing had set them closer.
  \cs_new_protected:Npn \__oer_fit_size_spaced:n #1
    {
      \fontsize { \fp_eval:n { #1 * \use:c { f@size } } pt } { \use:c { f@baselineskip } }
      \selectfont
    }
  \cs_new_protected:Npn \__oer_fit_mskip:n #1
    {
      \muskip_set:Nn \l__oer_fit_muskip {#1}
      \dim_compare:nNnTF { \tex_mutoglue:D \l__oer_fit_muskip } > { 18 pt }
        { \tex_mskip:D 18 mu \scan_stop: }
        { \tex_mskip:D \l__oer_fit_muskip }
    }
  \cs_new_protected:Npn \__oer_fit_narrow_math:
    {
      \cs_set_protected:Npn \mspace ##1 { \__oer_fit_mskip:n {##1} }
      \cs_set_eq:NN \qquad \quad
      \dim_set:Nn \arraycolsep { 0.4 \arraycolsep }
    }
  \cs_new_protected:Npn \__oer_fit_center_display:
    {
      \tex_everydisplay:D \exp_after:wN
        {
          \tex_the:D \tex_everydisplay:D
          \tex_advance:D \tex_displayindent:D - \l__oer_fit_margin_dim
          \tex_advance:D \tex_displaywidth:D 2 \l__oer_fit_margin_dim
        }
    }
  % What the run before decided for a table or formula: #1 its kind, t a
  % table whose columns don't wrap, p one whose do, d a display formula, e
  % a numbered one, i a formula in text; #2 its spaces narrowed or not; #3
  % its type's size, a part of its own; #4 a wrapping table's columns'
  % width, a part of the widths its LaTeX gives them; #5 centered or not;
  % and #6 a table's number of columns.
  \cs_new_protected:Npn \OERFitApply #1#2#3#4#5#6
    {
      \fp_compare:nNnT {#3} < { 1 }
        {
          \str_case:nnF {#1}
            {
              { d } { \__oer_fit_size_spaced:n {#3} }
              { e } { \__oer_fit_size_spaced:n {#3} }
            }
            { \__oer_fit_size:n {#3} }
        }
      \int_compare:nNnT {#2} = { 1 }
        {
          \str_case:nnF {#1}
            {
              { t } { \dim_set:Nn \tabcolsep { 0.25 em } }
              { p } { \dim_set:Nn \tabcolsep { 0.25 em } }
            }
            { \__oer_fit_narrow_math: }
        }
      \str_if_eq:nnT {#1} { p }
        {
          \dim_set:Nn \linewidth
            {
              \fp_to_dim:n
                { (#4) * ( \linewidth - 2 * (#6 - 1) * \tabcolsep ) + 2 * (#6 - 1) * \tabcolsep }
            }
          \int_set:Nn \tex_hyphenpenalty:D { 10000 }
        }
      \int_compare:nNnT {#5} = { 1 }
        {
          \str_if_eq:nnTF {#1} { d } { \__oer_fit_center_display: }
            {
              \skip_set:Nn \LTleft { 0pt plus 1fill minus 1fill }
              \skip_set:Nn \LTright { 0pt plus 1fill minus 1fill }
            }
        }
    }
  % A table, in a group pdf-target.lua opens: #1 its number, #2 its
  % columns, #3 1 where they wrap. The widths longtable records are
  % forgotten, so that a table no longtable sets has none.
  \NewDocumentCommand \OERFitTable { m m m }
    {
      \setattribute \OERFitAttribute {#1}
      \cs_gset_eq:cN { LT@save@row } \scan_stop:
      \__oer_fit_margin:
      \directlua
        {
          oerfit.open(#1, "\int_compare:nNnTF {#3} = { 1 } { p } { t }",
            \dim_to_decimal_in_sp:n { \hsize },
            \dim_to_decimal_in_sp:n { \hsize + 2 \l__oer_fit_margin_dim },
            \dim_to_decimal_in_sp:n { \use:c { f@size } pt }, #2,
            \int_use:N \tex_inputlineno:D, \dim_to_decimal_in_sp:n { \tabcolsep },
            \legacy_if:nTF { @twocolumn } { 1 } { 0 })
        }
    }
  % A table's end: its width, by the widths longtable recorded, none where
  % no longtable was set in the group, which leaves it as it is.
  \NewDocumentCommand \OERFitTableEnd { m }
    {
      \dim_gzero:N \g__oer_fit_dim
      \cs_if_exist:cT { LT@save@row }
        {
          \group_begin:
            \cs_set:cpn { LT@entry } ##1 ##2 { \dim_gadd:Nn \g__oer_fit_dim {##2} }
            \use:c { LT@save@row }
          \group_end:
        }
      \directlua
        {
          oerfit.table(#1, \dim_to_decimal_in_sp:n { \g__oer_fit_dim },
            \dim_to_decimal_in_sp:n { \tabcolsep })
        }
    }
  % A formula, in a group pdf-target.lua opens: #1 its number, #2 d for a
  % display, e for a numbered one, which isn't centered, its number at the
  % line's end, and i for a formula in text, the last two running on into
  % the margin to the right of their line. A display isn't fitted under
  % the fleqn class option, which sets it a margin from the line's left
  % end, in a box as wide as the line.
  \bool_new:N \l__oer_fit_skip_bool
  \NewDocumentCommand \OERFitFormula { m m }
    {
      \bool_set_false:N \l__oer_fit_skip_bool
      \str_if_eq:nnF {#2} { i }
        {
          \cs_if_exist:cT { if@fleqn }
            { \legacy_if:nT { @fleqn } { \bool_set_true:N \l__oer_fit_skip_bool } }
        }
      \bool_if:NF \l__oer_fit_skip_bool
        {
          \setattribute \OERFitAttribute {#1}
          \__oer_fit_margin:
          \directlua
            {
              oerfit.open(#1, "#2", \dim_to_decimal_in_sp:n { \linewidth },
                \dim_to_decimal_in_sp:n
                  {
                    \str_if_eq:nnTF {#2} { d } { \linewidth + 2 \l__oer_fit_margin_dim }
                      { \hsize - \use:c { @totalleftmargin } + \l__oer_fit_margin_dim }
                  },
                \dim_to_decimal_in_sp:n { \use:c { f@size } pt }, 0, \int_use:N \tex_inputlineno:D,
                0, \legacy_if:nTF { @twocolumn } { 1 } { 0 })
            }
        }
    }
  \ExplSyntaxOff
\else
  \NewDocumentCommand\OERFitTable{mmm}{}
  \NewDocumentCommand\OERFitTableEnd{m}{}
  \NewDocumentCommand\OERFitFormula{mm}{}
  \def\OERFitState#1#2#3#4#5{}
  \def\OERFitRun#1{}
  \def\OERFitSource#1#2{}
\fi
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
""" + FIT_MACROS


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


def line_owners(lines, pages):
    """The book's page each line of its LaTeX is on: the last of pages
    ({label: stem}, its id as page_id gives it) whose label is at or
    before it, or None."""
    owner, current = [], None
    for text in lines:
        for label in LABEL.findall(text):
            current = pages.get(label, current)
        owner.append(current)
    return owner


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
    owner = line_owners(lines, pages)
    table, inside = [], False
    for text in lines:
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


def page_list(pages):
    """Pages, as the build's warnings name them: the first six, and how
    many more."""
    return ", ".join(pages[:6]) + (f", and {len(pages) - 6} more" if len(pages) > 6 else "")


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
            + (f"; on {len(pages)} page(s), widest first: " + page_list(pages) if pages else "")
            + ".")


# What FIT_MACROS says it fitted on a run: how many of the tables and
# formulas it numbered it has narrowed alone, and how many it set smaller,
# and the smallest part of its type's size any is in; and each that was still
# wider than its line on the run: its kind (t a table whose columns don't
# wrap, p one whose do, d a display formula, e a numbered one, i a formula
# in text), how many points wider, the line of LaTeX its group opened on,
# the part of its type's size it was in, whether it was centered, whether
# it was on the paper, a quarter inch inside its edge, and whether its page
# has two columns, where it has no more room than its column.
FITTED = re.compile(r"^TextbookImprover fit: run (\d+), (\d+) narrowed, (\d+) smaller, "
                    r"smallest ([\d.]+)$", re.M)
FIT_WIDE = re.compile(r"^TextbookImprover fit wide: ([tpdei]) ([\d.]+) (\d+) ([\d.]+) ([01]) ([01]) "
                      r"([01])$", re.M)


def fit_report(output, source, pages):
    """[lines to print] for what FIT_MACROS fitted, from what LaTeX's last
    run said (output) about its input (source), pages as overfull_lines
    takes them: what it fitted; what's still wider than the text, centered
    on the page, which LaTeX doesn't report as an overfull box; and, as
    warnings, what isn't a quarter inch inside the paper's edge even at the
    least it sets type in, and what's wider than its column, on a page of
    two. A formula still wider than its line, but a display centered
    within the margins, is LaTeX's overfull box as well, which
    overfull_lines names among the lines too wide; a table, centered, isn't
    one."""
    found = FITTED.findall(output)
    if not found:
        return []
    narrowed, smaller, smallest = found[-1][1:]
    narrowed, smaller = int(narrowed), int(smaller)
    owner = line_owners(source.split("\n"), pages)

    def page(line):
        line = int(line) - 1
        return owner[line] if 0 <= line < len(owner) else None
    wide = [(float(points), kind, page(line), float(factor), center == "1", paper == "1",
             columns == "1")
            for kind, points, line, factor, center, paper, columns in FIT_WIDE.findall(output)]
    said = []
    if narrowed or smaller:
        said.append(f"Fitted {narrowed + smaller} table(s) and formula(s) too wide for "
                    f"their lines to them: "
                    + "; ".join(([f"{narrowed} by narrowing their spaces"] if narrowed else [])
                                + ([f"{smaller} in smaller type as well, the smallest at "
                                    f"{round(float(smallest) * 100)}% of its size"]
                                   if smaller else []))
                    + ".")
    # A table whose word runs a point into the space beside its column,
    # though the table fits its line, is no wider than the text.
    middle = sorted((w for w in wide if w[4] and w[5] and w[0] > 0), key=lambda w: -w[0])
    if middle:
        tables = sum(1 for w in middle if w[1] in "tp")
        said.append(f"{len(middle)} of them, still wider than the text, "
                    f"{'is' if len(middle) == 1 else 'are'} centered on "
                    f"the page ({tables} table(s), {len(middle) - tables} display "
                    f"formula(s)), the widest {middle[0][0]:,.0f} points wider"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in middle if w[2])))
                       if any(w[2] for w in middle) else "")
                    + ".")
    off = sorted((w for w in wide if not w[5] and not w[6]), key=lambda w: -w[0])
    if off:
        said.append(f"WARNING: {len(off)} table(s) or formula(s) are too wide for the paper "
                    f"even in smaller type, the smallest at "
                    f"{round(min(w[3] for w in off) * 100)}% of its size, and run to within a "
                    "quarter inch of its edge or past it, the widest "
                    f"{off[0][0]:,.0f} points wider than the text"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in off if w[2])))
                       if any(w[2] for w in off) else "")
                    + ".")
    beside = sorted((w for w in wide if not w[5] and w[6]), key=lambda w: -w[0])
    if beside:
        said.append(f"WARNING: {len(beside)} table(s) or formula(s) on pages of two columns "
                    f"are too wide for their column even in smaller type, the smallest at "
                    f"{round(min(w[3] for w in beside) * 100)}% of its size, and run past it, "
                    f"the widest {beside[0][0]:,.0f} points wider than the column"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in beside if w[2])))
                       if any(w[2] for w in beside) else "")
                    + ".")
    return said


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
