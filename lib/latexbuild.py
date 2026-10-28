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
# Each is made the character it is, from the math font, or, for one Latin
# Modern Math lacks, from the text's fonts and their fallback, set as a box
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
# of its own. An address keeps its hyphens and backticks, which
# \pdfstringdef would join into dashes and inverted marks, as
# pdf-target.lua's Link keeps a link's text.
UA1_LINKS = r"""\ExplSyntaxOn
\AddToHook{begindocument/end}
  {
    \socket_if_exist:nT {hyp/link/GoTo/Contents}
      {
        \socket_new_plug:nnn {hyp/link/GoTo/Contents}{oer}
          {
            \tl_if_empty:NT \g__oer_link_contents_tl
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
            \tl_if_empty:NT \g__oer_link_contents_tl
              {
                \tl_set:Nn \l_tmpb_tl {#1}
                \tl_replace_all:Nnn \l_tmpb_tl { - } { - { } }
                \tl_replace_all:Nnn \l_tmpb_tl { ` } { { } ` }
                \exp_args:NNV \pdfstringdef \l_tmpa_tl \l_tmpb_tl
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


# Picture mode drawn with paths, in a book's PDF and a deck's (PDF_MACROS),
# and in a LaTeX book's tagged copy (texremediate.tag); with picture_paths
# off (PICTURE_FONTS), only a formula's struck-out term.
PICTURE_PATHS = r"""% LaTeX's picture mode drawn with paths, by pict2e: a picture
% environment's lines, arrows, circles, and ovals, and the strokes the
% cancel package draws through a formula's term (\cancel, \bcancel, and
% \xcancel, which texmath writes for MathML's diagonal strikes, and
% \cancelto) with picture mode's \line and \vector. LaTeX draws them with
% glyphs of its line10 and lcircle10 fonts, whose map to Unicode has only
% a space, and veraPDF failed College Algebra 2e's first chapter on two of
% cancel's (PDF/UA-2's 8.4.5.8); and the fonts have only some slopes and
% sizes, so a circle asked for at 80 points was drawn at 40, the largest,
% LaTeX saying so only in its log ("size unavailable"), and a line of a
% slope they lack, \line(7,3), stopped LaTeX ("Bad \line or \vector
% argument"). pict2e draws what's written. A picture laid out around what
% LaTeX drew, an 80-point circle seen at 40, gets the 80 now;
% picture_paths off (\OERPictureFonts) keeps LaTeX's own, unless cancel is
% loaded: pict2e is loaded for its strokes either way, as before, and then
% draws the document's pictures too. cancel, given pict2e, asks for
% LaTeX's own commands (\OriginalPictureCmds), its comment saying pict2e's
% have no bounding box, which pict2e's \line has now; told to use
% pict2e's, it draws each stroke where it did (measured: \cancel,
% \bcancel, \xcancel, and \cancelto, in text, in a script, and displayed).
% pict2e is loaded at the end of the preamble, after any pict2e the
% document loads with options of its own. It has drawing commands of its
% own, \arc, \Line, \polygon, \moveto, and the rest, which, loaded so
% late, replaced a document's own \arc, on which LaTeX then stopped
% ("Missing number"), and stopped LaTeX on a \newcommand of one in the
% text ("already defined"). So those names are set aside before it loads
% and, at \begin{document}, given back as the document had them or taken
% away; \buttcap among them, which pict2e's \circle, \dot, and \oval
% call, and are given pict2e's own in the group each draws in (taken
% away, and not given it, a circle stopped LaTeX: "Undefined control
% sequence"). \maxovalrad, which \oval reads, is set aside too, since a
% document's own stopped pict2e from loading ("already defined"), and is
% given back where the document had one, and kept where it hadn't. The
% trig package's names, \UseSin and the rest, which pict2e loads and
% uses, stay trig's: a document's own command of one of them is replaced,
% or, made in the text, stops LaTeX.
\ExplSyntaxOn
\clist_const:Nn \c__oer_pictiie_names_clist
  {
    arc, pIIearc, Line, polyline, Vector, polyvector, polygon, moveto,
    lineto, curveto, circlearc, closepath, strokepath, fillpath, buttcap,
    roundcap, squarecap, miterjoin, roundjoin, beveljoin, ltxarrows,
    pstarrows, cbezier
  }
\cs_new_protected:Npn \__oer_pictiie_load:
  {
    \IfPackageLoadedF { pict2e }
      {
        \clist_map_inline:Nn \c__oer_pictiie_names_clist
          {
            \cs_set_eq:cc { __oer_pictiie_ ##1 : } {##1}
            \cs_undefine:c {##1}
          }
        \cs_set_eq:NN \__oer_pictiie_maxovalrad: \maxovalrad
        \cs_undefine:N \maxovalrad
        \RequirePackage { pict2e }
        \cs_set_eq:NN \__oer_pictiie_own_buttcap: \buttcap
        \cs_if_exist:cT { pIIe@circ }
          {
            \cs_set_eq:Nc \__oer_pictiie_circ:n { pIIe@circ }
            \cs_set_protected:cpn { pIIe@circ } ##1
              {
                \cs_set_eq:NN \buttcap \__oer_pictiie_own_buttcap:
                \__oer_pictiie_circ:n {##1}
              }
          }
        \cs_if_exist:cT { pIIe@buttcap }
          {
            \cs_set_eq:Nc \__oer_pictiie_buttcap_ok: { pIIe@buttcap }
            \cs_set_protected:cpn { pIIe@buttcap }
              {
                \cs_set_eq:NN \buttcap \__oer_pictiie_own_buttcap:
                \__oer_pictiie_buttcap_ok:
              }
          }
        \AddToHook { begindocument / end }
          {
            \clist_map_inline:Nn \c__oer_pictiie_names_clist
              {
                \cs_if_exist:cTF { __oer_pictiie_ ##1 : }
                  { \cs_set_eq:cc {##1} { __oer_pictiie_ ##1 : } }
                  { \cs_undefine:c {##1} }
              }
            \cs_if_exist:NT \__oer_pictiie_maxovalrad:
              { \cs_set_eq:NN \maxovalrad \__oer_pictiie_maxovalrad: }
          }
      }
  }
\AddToHook { begindocument / before }
  {
    \cs_if_exist:NTF \OERPictureFonts
      { \IfPackageLoadedT { cancel } { \__oer_pictiie_load: } }
      { \__oer_pictiie_load: }
    \IfPackageLoadedT { cancel }
      { \cs_set_eq:NN \OriginalPictureCmds \scan_stop: }
  }
\ExplSyntaxOff
"""
# picture_paths off: LaTeX's own picture mode, before PICTURE_PATHS is read
# at \begin{document}.
PICTURE_FONTS = "\\def\\OERPictureFonts{}\n"


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
% too wide, in its first chapter); or a line of code, set as it's written
% (in Principles of Data Science, 74 of 243 blocks of code have a line of
% more than 65 characters, which fill the default page's line in IBM Plex
% Mono at 12 points). pdf-target.lua numbers each table not in a table's
% cell, each display formula, each formula in text that is an
% environment, and each block of code not in a table's cell, a footnote's
% in one among them (\OERFitTable, \OERFitFormula, \OERFitCode), and
% LaTeX measures each as it sets it: a table by the widths longtable
% records for its columns and, where its columns wrap (p columns), by any
% line of a cell longer than its column, its longest piece TeX can't
% break, a word, words a no-break space joins, a line of code, or a
% formula's part between two of its breaks (post_linebreak_filter, and
% a line of highlighted code through \FancyVerbFormatLine, below), a
% fill-in blank no more than three underscores, which PDF_MACROS draws a
% blank too long for its line shorter to, at the least, without the kerns
% it draws a long blank's underscores closer with (taken whole, as it
% was, a blank too long for its column set the table in smaller type, the
% PDF suite's fit book's at 87 percent of its size), a
% line taken as in a formula from its start where the first of a
% formula's edges in it is an end (the formula ran on from the line
% before, or TeX dropped its start at the break, as it drops glue there:
% TeXbook, chapter 14), and one with no formula's edge in it where it
% ends at a penalty, as TeX breaks a formula (before its right skip, and
% the node ending a text direction that babel's bidi puts there), and
% the next line opens in one (the middle line of a formula over three,
% or a formula that opens a line and breaks after an operator); a
% formula by the list TeX makes of it
% (post_mlist_to_hlist_filter); and a block of code by its longest line
% (\OERFitCode, below). One wider than its line is fitted on the
% next run, from what this one measured, as Pandoc runs LaTeX again while
% its log asks, four times at most: first its spaces narrowed (a table's
% columns half an em apart, where they were 12 points; a formula's \qquad
% a quad, and an \mspace wider than a quad a quad, as a worked example's
% step is spaced from its reason, and an array's columns closer), then,
% where that's not enough, its type set smaller, as much as it takes, but
% to no less than three quarters of its size (9 points in 12-point type),
% a table's wrapping columns made as wide as its words need, which TeX
% then doesn't hyphenate, nor a worked example's steps' words once they're
% laid out: a smaller design, wider for its size (below),
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
% longtable's. A worked example's steps, whose formulas don't break, and
% a table whose source gives its columns no widths, with words to wrap
% (\OERFitStepsTable), are laid out by what LaTeX measures of them, not by
% pdf-target.lua's counts, which give each column of words its part of
% the line on a first run: each column of formulas, a step's math, as wide
% as its widest, and each column of words, which wraps, as wide as its
% widest paragraph set as one line, where the table so fits its line;
% where it fits with each fill-in blank at its least, each column as
% wide as its widest paragraph so, the columns of blanks sharing the rest
% of the line by how much longer their blanks are whole, as a blank is
% drawn as long as its column leaves room for (counted whole, a long blank
% took the line from the words beside it, which wrapped where they had
% room). A blank's least is three underscores, and where words share its
% line, before it or joined to it up to a space TeX may break at, a
% no-break space not one, two thirds of the line, as the blank macros
% below draw it while TeX breaks the paragraph: a column less than three
% times as wide as those words put the blank on the line after them
% (oerfit.paragraph measures a paragraph so). Otherwise, no narrower than
% its longest piece TeX can't break, a formula whole and a blank's three
% underscores at most, the rest of the line shared among them in
% proportion to how much wider each would be as one line; where even
% that's wider than the line, the table's spaces are
% narrowed; then, in a table's words, a formula's longest part between two
% of its breaks, as TeX breaks a formula in text, a step's formula having
% none; and then its type is set smaller, as another table's is, its
% columns sharing the line as they do at its own size. A table or a
% display formula fitted is centered on the page, so that one still wider
% than its line runs into both margins alike; and one that would come
% within a quarter inch of the paper's edge even at three quarters of its
% size is set smaller still, as far as it takes, to half its size at
% least, but for a block of code that would even at half, whose lines too
% long for their line wrap (\__oer_fit_wrap:, below). Type set smaller
% isn't always as much narrower: Latin Modern
% Roman, the default's face where IBM Plex isn't installed, has designs
% for sizes from 5 to 17 points, each wider for its size than the next
% larger (the 9-point 2.8 percent wider than the 10-point, the 8-point 3.3
% percent wider than the 9-point), and in 12-point type unicode-math sets
% math of 10 points or less in the font's forms for subscripts (ssty), 13
% percent wider in Latin Modern Math. So whatever is too wide is fitted on
% the first run, a formula's spaces narrowed and its type set smaller at
% once, as its width before narrowing asks; and on the second each fit is
% measured again, and fitted again where it's off its line by more than 4
% percent of it, too wide or too narrow, more than a design's step, less
% of which centering takes up, and a formula in text or a numbered
% display, which nothing centers, or a worked example's steps, each of
% whose columns LaTeX measured, wherever it's too wide.
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
% hash, a tilde, or a backslash. The attribute that marks a blank is
% PDF_MACROS', made before these macros; the measures test that it's there
% before they read it, since node.has_attribute reads a nil as attribute 0,
% which luaotfload sets for every node, so that without it, as where the
% LaTeX suite reads these macros alone, no run of underscores is a blank.
\ifdefined\directlua
  \newattribute\OERFitAttribute
  \newattribute\OERFitStepsAttribute
  \newattribute\OERFitWrapAttribute
  \directlua{
    local attribute = luatexbase.attributes.OERFitAttribute
    local column = luatexbase.attributes.OERFitStepsAttribute
    local HLIST, VLIST, GLUE, PENALTY, MATH, DIR = node.id("hlist"), node.id("vlist"), node.id("glue"), node.id("penalty"), node.id("math"), node.id("dir")
    local GLYPH, KERN = node.id("glyph"), node.id("kern")
    local EDGES = {}
    for subtype, name in pairs(node.subtypes("glue")) do
      if name == "leftskip" or name == "rightskip" or name == "parfillskip" then EDGES[subtype] = true end
    end
    local blank = luatexbase.attributes.OERBlankAttribute
    local FLOOR, LEAST, AIM, JUMP, TOLERANCE = """ + str(FIT_FLOOR) + ", " + str(FIT_LEAST) + r""", 0.98, 0.04, 32768
    oerfit = { state = {}, kind = {}, line = {}, room = {}, size = {}, columns = {},
               width = {}, tight = {}, sep = {}, sep0 = {}, where = {}, twocol = {}, run = 0,
               sources = { status.filename }, seen = { [status.filename] = true }, stored = {},
               steps = {}, entries = {}, natural = {}, longest = {}, pieces = {}, applied = {},
               low = {}, edge = {}, right = {}, tall = {} }
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
    local function smaller(whole, line, room)
      local f = down(AIM * line / whole, 1000)
      if f >= FLOOR then return f end
      if FLOOR * whole > room then return math.max(LEAST, down(AIM * room / whole, 1000)) end
      return FLOOR
    end
    local function measured(id)
      return id and not status.output_active
    end
    luatexbase.add_to_callback("post_mlist_to_hlist_filter", function(head)
      local id = current()
      local kind = id and oerfit.kind[id]
      if measured(id) and not (kind == "t" or kind == "p" or kind == "s" or kind == "c") then
        local w = node.dimensions(head)
        if w > (oerfit.width[id] or 0) then oerfit.width[id] = w end
      end
      return true
    end, "oer.fit.formulas")
    local function longest(line, inmath)
      local piece, most, blanks = 0, 0, 0
      for n in node.traverse(line.head) do
        if n.id == MATH then
          inmath = n.subtype == 0
        end
        if n.id == KERN and blank and node.has_attribute(n, blank, 2) then
          piece = piece + 0
        elseif (n.id == GLUE and not inmath
                and not (n.prev and n.prev.id == PENALTY and n.prev.penalty >= 10000))
            or (n.id == PENALTY and inmath and n.penalty < 10000) then
          if piece > most then most = piece end
          piece, blanks = 0, 0
        elseif n.id == GLYPH and n.char == 95 and blank and node.has_attribute(n, blank) then
          blanks = blanks + 1
          if blanks <= 3 then piece = piece + node.dimensions(n, n.next) end
        elseif not (n.id == GLUE) then
          blanks = 0
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
      if not measured(id) then
      elseif oerfit.kind[id] == "p" then
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
      elseif oerfit.kind[id] == "c" then
        for line in node.traverse_id(HLIST, head) do
          if line.subtype == 1 then
            local w = 0
            for n in node.traverse(line.head) do
              if not (n.id == GLUE and EDGES[n.subtype]) then w = w + node.dimensions(n, n.next) end
            end
            oerfit.code(id, w)
          end
        end
      end
      return true
    end, "oer.fit.cells")
    function oerfit.paragraph(head)
      local line, piece, longest, bit, most, inmath, blanks = 0, 0, 0, 0, 0, false, 0
      local low, before, whole, three, joined, state, tied = 0, 0, 0, 0, 0, 0, false
      local function close()
        local least = math.max(before + three + joined, 3 * (before + joined))
        low = math.max(low, math.min(before + whole + joined, least))
        before, whole, three, joined, state = 0, 0, 0, 0, 0
      end
      for n in node.traverse(head) do
        if n.id == MATH then inmath = n.subtype == 0 end
        if n.id == KERN and blank and node.has_attribute(n, blank, 2) then
          line = line + 0
        elseif n.id == GLUE then
          line = line + n.width
          if inmath then
            piece, bit = piece + n.width, bit + n.width
          else
            if piece > longest then longest = piece end
            if bit > most then most = bit end
            piece, bit, blanks = 0, 0, 0
          end
          if inmath or tied then
            if state > 0 then state, joined = 2, joined + n.width else before = before + n.width end
          elseif state > 0 then
            close()
          else
            before = before + n.width
          end
        elseif n.id == PENALTY and inmath and n.penalty < 10000 then
          if bit > most then most = bit end
          bit = 0
        elseif not (n.id == VLIST and math.abs(n.width - tex.hsize) <= 1) then
          local w = node.dimensions(n, n.next)
          line = line + w
          if n.id == GLYPH and n.char == 95 and blank and node.has_attribute(n, blank) then
            blanks = blanks + 1
            if blanks <= 3 then piece, bit = piece + w, bit + w end
            if state == 0 then
              state, whole, three = 1, w, w
            elseif state == 1 then
              whole = whole + w
              if blanks <= 3 then three = three + w end
            elseif blanks <= 3 then
              joined = joined + w
            end
          else
            blanks = 0
            piece, bit = piece + w, bit + w
            if state == 0 then before = before + w else state, joined = 2, joined + w end
          end
        end
        tied = n.id == PENALTY and n.penalty >= 10000
      end
      if state > 0 then close() else low = math.max(low, before) end
      if piece > longest then longest = piece end
      if bit > most then most = bit end
      return line, low, longest, most
    end
    luatexbase.add_to_callback("pre_linebreak_filter", function(head)
      local id, j = current(), tex.getattribute(column)
      if id and oerfit.kind[id] == "s" and j and j > 0 then
        local line, low, longest, most = oerfit.paragraph(head)
        local nat, long, bits = oerfit.natural[id] or {}, oerfit.longest[id] or {}, oerfit.pieces[id] or {}
        oerfit.natural[id], oerfit.longest[id], oerfit.pieces[id] = nat, long, bits
        local lows = oerfit.low[id] or {}
        oerfit.low[id] = lows
        if low > (lows[j] or 0) then lows[j] = low end
        if line > (nat[j] or 0) then nat[j] = line end
        if longest > (long[j] or 0) then long[j] = longest end
        if most > (bits[j] or 0) then bits[j] = most end
      end
      return true
    end, "oer.fit.steps")
    local wrapping = luatexbase.attributes.OERFitWrapAttribute
    local WHATSIT, BOUNDARY, MARK, LOCALPAR = node.id("whatsit"), node.id("boundary"), node.id("mark"), node.id("local_par")
    local INDENT, ROOM = 3, 20
    for subtype, name in pairs(node.subtypes("hlist")) do
      if name == "indent" then INDENT = subtype end
    end
    local unwrap = nil
    local function blank(c)
      return c == 32 or c == 160 or (c >= 8192 and c <= 8203) or c == 8239 or c == 8287 or c == 12288
    end
    local function letter(c)
      return c and ((c >= 48 and c <= 57) or (c >= 65 and c <= 90) or (c >= 97 and c <= 122)
                    or c >= 192 and not blank(c))
    end
    local function spacing(n)
      return n and (n.id == GLUE and not EDGES[n.subtype] or n.id == GLYPH and blank(n.char))
    end
    local function joined(n)
      return n.width == 0 or (n.char >= 768 and n.char <= 879)
    end
    local function rtl(c)
      return (c >= 1424 and c <= 2303) or (c >= 64285 and c <= 65023) or (c >= 65136 and c <= 65279)
    end
    local shaped = {}
    local function ahead(n)
      if not (joined(n) and rtl(n.char)) then return false end
      if shaped[n.font] == nil then
        local f = fonts and fonts.hashes and fonts.hashes.identifiers and fonts.hashes.identifiers[n.font]
        shaped[n.font] = (f and f.hb and true) or false
      end
      return shaped[n.font]
    end
    local function natural(head)
      local width = 0
      for n in node.traverse(head) do width = width + node.dimensions(n, n.next) end
      return width
    end
    function oerfit.box_width(box)
      tex.sprint(math.min(natural(tex.getbox(box).head), 1073741823))
    end
    local function wrap_penalty(at, value)
      local p = node.new(PENALTY)
      p.penalty = value
      p.attr = at.attr
      return p
    end
    luatexbase.add_to_callback("pre_linebreak_filter", function(head)
      if status.output_active then return true end
      local first = head
      while first and not (first.id == GLYPH) do first = first.next end
      if not (first and node.has_attribute(first, wrapping)) then return true end
      head = node.flatten_discretionaries(head)
      local id = current()
      if measured(id) and oerfit.kind[id] == "c" then oerfit.code(id, natural(head)) end
      local text = first
      while text and not (text.id == GLYPH and not blank(text.char)) do text = text.next end
      local indent = node.dimensions(head, text or first)
      local char = 0
      for g in node.traverse_id(GLYPH, text or first) do
        if g.width > 0 then
          char = g.width
          break
        end
      end
      local left, right = 0, tex.hsize
      if type(tex.parshape) == "table" then
        for _, entry in ipairs(tex.parshape) do left, right = entry[1], entry[1] + entry[2] end
      end
      local edge = right
      if not oerfit.boxed and id and oerfit.right[id] then edge = oerfit.right[id] end
      local width, stretch, shrink, stretchorder, shrinkorder = tex.getglue("leftskip")
      if natural(head) <= edge - left - width + TOLERANCE then return head end
      local most = edge - left - width - ROOM * char
      local hang = math.max(0, math.min(indent + 2 * char, most))
      local n, last, glyph = head, nil, first
      while n do
        local after = n.next
        if spacing(n) then
          if not (spacing(after) or after and after.id == PENALTY and spacing(after.next)) then
            head = node.insert_after(head, n, wrap_penalty(glyph, 0))
          end
          last = n
        elseif n.id == GLYPH then
          if last and last.id == GLYPH
              and not (blank(last.char) or ahead(last) or joined(n) and (joined(last) or not ahead(n))) then
            local value = 120
            if letter(last.char) then value = 150 end
            head = node.insert_before(head, n, wrap_penalty(n, value))
          end
          last, glyph = n, n
        elseif not (n.id == WHATSIT or n.id == KERN or n.id == BOUNDARY or n.id == MARK) then
          last = n
        end
        n = after
      end
      unwrap = { left = { width, stretch, shrink, stretchorder, shrinkorder },
                 right = { tex.getglue("rightskip") }, lines = tex.interlinepenalty,
                 id = id, boxed = oerfit.boxed }
      tex.setglue("leftskip", width + hang, stretch, shrink, stretchorder, shrinkorder)
      tex.setglue("rightskip", right - edge, tex.hsize, 0, 0, 0)
      tex.interlinepenalty = 10000
      local k = node.new(KERN)
      k.kern, k.attr = -hang, first.attr
      local at = head
      while at and (at.id == LOCALPAR or at.id == DIR or at.id == HLIST and at.subtype == INDENT) do
        at = at.next
      end
      head = node.insert_before(head, at, k)
      return head
    end, "oer.fit.wrap")
    luatexbase.add_to_callback("post_linebreak_filter", function(head)
      if unwrap then
        local id, tall = unwrap.id, 0
        for n in node.traverse(head) do
          if n.id == HLIST then
            tall = tall + n.height + n.depth
          elseif n.id == GLUE then
            tall = tall + n.width
          elseif n.id == KERN then
            tall = tall + n.kern
          end
        end
        if unwrap.boxed then
          if id and tall > tex.vsize then oerfit.tall[id] = true end
        elseif tall > tex.vsize / 2 then
          for n in node.traverse_id(PENALTY, head) do
            if n.penalty >= 10000 then n.penalty = n.penalty - 10000 + unwrap.lines end
          end
        end
        tex.setglue("leftskip", table.unpack(unwrap.left))
        tex.setglue("rightskip", table.unpack(unwrap.right))
        tex.interlinepenalty = unwrap.lines
        unwrap = nil
      end
      return true
    end, "oer.fit.unwrap")
    function oerfit.open(id, kind, line, room, size, columns, where, sep0, twocol)
      oerfit.kind[id], oerfit.line[id], oerfit.room[id] = kind, line, room
      oerfit.size[id], oerfit.columns[id], oerfit.where[id] = size, columns, where
      oerfit.sep0[id], oerfit.twocol[id] = sep0, twocol
      local s = oerfit.state[id]
      if s then
        tex.sprint(string.char(92) .. "OERFitApply{" .. kind .. "}{" .. s.narrow .. "}{"
          .. s.factor .. "}{" .. s.columns .. "}{" .. s.center .. "}{" .. columns .. "}{"
          .. (s.wrap or 0) .. "}")
      end
    end
    function oerfit.table(id, width, sep)
      oerfit.width[id], oerfit.sep[id] = width, sep
    end
    function oerfit.wrap(id)
      if oerfit.state[id] then oerfit.state[id].wrap = 1 end
    end
    function oerfit.code(id, width, line)
      if oerfit.kind[id] == "p" then
        if line and line > 0 and width / line > (oerfit.tight[id] or 0) then
          oerfit.tight[id] = width / line
        end
      elseif oerfit.kind[id] == "c" and width > (oerfit.width[id] or 0) then
        oerfit.width[id] = width
      end
    end
    function oerfit.code_line(box, line)
      local id = current()
      if measured(id) then oerfit.code(id, natural(tex.getbox(box).head), line) end
    end
    function oerfit.entry(id, width)
      local e = oerfit.entries[id]
      e.n = e.n + 1
      e[e.n] = width
    end
    function oerfit.steps_table(id, letters, guess)
      local info, k = { letters = letters, words = {}, guess = {} }, 0
      for item in string.gmatch(guess, "[^,]+") do
        k = k + 1
        if not (item == "m") then
          table.insert(info.words, k)
          info.guess[k] = tonumber(item)
          info.count = (info.count or 0) + 1
        end
      end
      info.k = k
      oerfit.steps[id] = info
      oerfit.applied[id] = {}
    end
    function oerfit.steps_state(id, j, width)
      local s = oerfit.state[id]
      if s then
        s.widths = s.widths or {}
        s.widths[j] = width
      end
    end
    function oerfit.after_group(spec, j)
      local last, level = string.len(spec), 0
      while j <= last and not (string.byte(spec, j) == 123) do j = j + 1 end
      while j <= last do
        local c = string.byte(spec, j)
        if c == 123 then level = level + 1 elseif c == 125 then level = level - 1 end
        j = j + 1
        if level == 0 then return j end
      end
      return j
    end
    function oerfit.is_letter(c)
      return c and ((c >= 65 and c <= 90) or (c >= 97 and c <= 122))
    end
    function oerfit.spec_columns(spec)
      local n, j, last = 0, 1, string.len(spec)
      while j <= last do
        local c = string.byte(spec, j)
        if c == 64 or c == 33 or c == 60 or c == 62 then
          j = oerfit.after_group(spec, j + 1)
        elseif c == 92 then
          j = j + 1
          while j <= last and oerfit.is_letter(string.byte(spec, j)) do j = j + 1 end
        elseif oerfit.is_letter(c) then
          n = n + 1
          if c == 112 or c == 109 or c == 98 then j = oerfit.after_group(spec, j + 1) else j = j + 1 end
        else
          j = j + 1
        end
      end
      return n
    end
    function oerfit.lt_array(id, opt, spec)
      local info, s, bs = oerfit.steps[id], oerfit.state[id], string.char(92)
      if not (oerfit.spec_columns(spec) == info.k) then
        info.unmeasured = true
        tex.sprint(bs .. "OERFitLTArray[" .. opt .. "]{" .. spec .. "}")
        return
      end
      local parts = {}
      for j = 1, info.k do
        local letter = string.sub(info.letters, j, j)
        if info.guess[j] then
          local width = math.floor(info.guess[j] * (oerfit.line[id] - 2 * (info.k - 1) * oerfit.sep0[id]))
          if s and s.widths and s.widths[j] then width = s.widths[j] end
          oerfit.applied[id][j] = width
          local align = "raggedright"
          if letter == "r" then align = "raggedleft" elseif letter == "c" then align = "centering" end
          parts[j] = ">{" .. bs .. align .. bs .. "arraybackslash" .. bs .. "setattribute" .. bs
            .. "OERFitStepsAttribute{" .. j .. "}}p{" .. width .. "sp}"
        else
          parts[j] = letter
        end
      end
      tex.sprint(bs .. "OERFitLTArray[" .. opt .. "]{@{}" .. table.concat(parts) .. "@{}}")
    end
    function oerfit.steps_next(id, s)
      local info, e = oerfit.steps[id], oerfit.entries[id]
      if info.unmeasured or e.n < info.k then return nil end
      local k, f0 = info.k, s.factor
      local sep, sep0, size = oerfit.sep[id], oerfit.sep0[id], oerfit.size[id]
      local line, room = oerfit.line[id], oerfit.room[id]
      local nat, long, bits = oerfit.natural[id] or {}, oerfit.longest[id] or {}, oerfit.pieces[id] or {}
      local lows = oerfit.low[id] or {}
      local all, applied, natural, longest, pieces, low = 0, 0, 0, 0, 0, 0
      for j = 1, k do all = all + e[j] end
      for _, j in ipairs(info.words) do
        applied = applied + (oerfit.applied[id][j] or 0)
        natural = natural + (nat[j] or 0) / f0
        longest = longest + (long[j] or 0) / f0
        pieces = pieces + (bits[j] or 0) / f0
        low = low + (lows[j] or 0) / f0
      end
      local maths = (all - applied - 2 * (k - 1) * sep) / f0
      local spaced, narrow = 2 * (k - 1) * sep0, 2 * (k - 1) * 0.25 * size
      local function shared(total, f, least)
        local out, base, want = {}, 0, 0
        for _, j in ipairs(info.words) do
          out[j] = f * (least[j] or 0) / f0
          base = base + out[j]
          want = want + math.max(0, f * (nat[j] or 0) / f0 - out[j])
        end
        for _, j in ipairs(info.words) do
          local more = math.max(0, f * (nat[j] or 0) / f0 - out[j])
          if want > 0 then
            out[j] = math.floor(out[j] + (total - base) * more / want)
          else
            out[j] = math.floor(out[j] + (total - base) / info.count)
          end
        end
        return out
      end
      if maths + natural + spaced <= line then
        local out = {}
        for _, j in ipairs(info.words) do out[j] = math.ceil((nat[j] or 0) / f0) end
        return { narrow = 0, factor = 1, columns = 1, center = 0, widths = out }
      end
      if low < natural and maths + low + spaced <= line then
        return { narrow = 0, factor = 1, columns = 1, center = 0, widths = shared(line - maths - spaced, 1, lows) }
      end
      if maths + longest + spaced <= line then
        return { narrow = 0, factor = 1, columns = 1, center = 0, widths = shared(line - maths - spaced, 1, long) }
      end
      if maths + longest + narrow <= line then
        return { narrow = 1, factor = 1, columns = 1, center = 1, widths = shared(line - maths - narrow, 1, long) }
      end
      if maths + pieces + spaced <= line then
        return { narrow = 0, factor = 1, columns = 1, center = 0, widths = shared(line - maths - spaced, 1, bits) }
      end
      if maths + pieces + narrow <= line then
        return { narrow = 1, factor = 1, columns = 1, center = 1, widths = shared(line - maths - narrow, 1, bits) }
      end
      local f = smaller(maths + pieces + narrow, line, room)
      return { narrow = 1, factor = f, columns = 1, center = 1,
               widths = shared(math.max(f * pieces, line - f * (maths + narrow)), f, bits) }
    end
    function oerfit.next(kind, id, s, w, line, room, tight)
      local size = oerfit.size[id]
      local center, narrow = 0, 1
      if kind == "d" then center = 1 end
      if kind == "c" then narrow = 0 end
      if not (kind == "t" or kind == "p") then
        local f = math.min(1, s.factor * line / w * AIM)
        if f >= FLOOR then return { narrow = narrow, factor = down(f, 1000), columns = 1, center = center } end
        local least = FLOOR
        if w * FLOOR / s.factor > room then
          if kind == "c" and w * LEAST / s.factor > room then
            return { narrow = 0, factor = FLOOR, columns = 1, center = 0, wrap = 1 }
          end
          least = math.max(LEAST, down(s.factor * room / w * AIM, 1000))
        end
        return { narrow = narrow, factor = least, columns = 1, center = center }
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
        if line / (content + narrow) * AIM >= 1 then return { narrow = 1, factor = 1, columns = 1, center = 1 } end
        return { narrow = 1, factor = smaller(content + narrow, line, room), columns = 1, center = 1 }
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
      local changed, narrowed, smaller, smallest, wide, wrapped, tall = 0, 0, 0, 1, {}, {}, {}
      for id, kind in pairs(oerfit.kind) do
        local s = oerfit.state[id] or { narrow = 0, factor = 1, columns = 1, center = 0 }
        local w, line, room = oerfit.width[id], oerfit.line[id], oerfit.room[id]
        local tight = oerfit.tight[id] or 0
        local over = w and w > line + TOLERANCE
        local cells = kind == "p" and tight > 1.002
        if s.wrap == 1 then
          wrapped[id] = oerfit.where[id] .. " " .. s.factor .. " " .. (oerfit.twocol[id] or 0)
          if oerfit.tall[id] then tall[id] = oerfit.where[id] end
        elseif over or cells then
          local onpaper = 1
          if w and w > room then onpaper = 0 end
          wide[id] = kind .. " " .. points(math.max(0, (w or 0) - (oerfit.edge[id] or line)))
            .. " " .. oerfit.where[id]
            .. " " .. s.factor .. " " .. s.center .. " " .. onpaper .. " " .. (oerfit.twocol[id] or 0)
        end
        local far = w and (w > (1 + JUMP) * line or w < (1 - JUMP) * line) or tight > 1 + JUMP
        local new, refit = nil, false
        if kind == "s" then
          if w and (run == 1 or run == 2 and over) then new = oerfit.steps_next(id, s) end
          local moved = false
          if new then
            for j, width in pairs(new.widths) do
              if math.abs(width - ((s.widths or {})[j] or 0)) > TOLERANCE then moved = true end
            end
          end
          if new and (not oerfit.state[id] or math.abs(new.factor - s.factor) > 0.0005 or moved) then
            oerfit.state[id], s = new, new
            changed = changed + 1
          end
          new = nil
        elseif w and run == 1 and (over or cells) then
          new = oerfit.next(kind, id, s, w, line, room, math.max(tight, 0.05))
        elseif w and run == 2 and (oerfit.state[id] and (far or (kind == "i" or kind == "e" or kind == "c") and over)
                                   or not oerfit.state[id] and (over or cells)) then
          new, refit = oerfit.next(kind, id, s, w, line, room, math.max(tight, 0.05)), true
        end
        if new and ((refit and (not (new.narrow == s.narrow) or not (new.center == s.center)
                                or math.abs(new.factor - s.factor) > 0.0005
                                or math.abs(new.columns - s.columns) > 0.00005
                                or not ((new.wrap or 0) == (s.wrap or 0))))
                    or new.narrow > s.narrow or new.center > s.center
                    or new.factor < s.factor - 0.0005 or (new.wrap or 0) > (s.wrap or 0)) then
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
        if s.wrap == 1 then tex.sprint(string.char(92) .. "OERFitWrapWrite{" .. id .. "}") end
        if s.widths then
          for j, width in pairs(s.widths) do
            tex.sprint(string.char(92) .. "OERFitStepsWrite{" .. id .. "}{" .. j .. "}{" .. math.floor(width) .. "}")
          end
        end
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
      for id, said in pairs(wrapped) do
        texio.write_nl("term and log", "TextbookImprover fit wrapped: " .. said)
      end
      for id, said in pairs(tall) do
        texio.write_nl("term and log", "TextbookImprover fit tall: " .. said)
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
  % A block of code whose lines wrap (\OERFitCode, below), after its
  % \OERFitState: written so that macros from before it read past it.
  \cs_new_protected:Npn \OERFitWrap #1 { \directlua { oerfit.wrap(#1) } }
  \cs_new_protected:Npn \OERFitWrapWrite #1
    {
      \exp_args:Nc \iow_now:Ne { @auxout }
        {
          \token_to_str:N \ifdefined \token_to_str:N \OERFitWrap
          \token_to_str:N \OERFitWrap {#1} \token_to_str:N \fi
        }
    }
  \cs_new_protected:Npn \OERFitWriteRun #1
    { \exp_args:Nc \iow_now:Ne { @auxout } { \token_to_str:N \OERFitRun {#1} } }
  \cs_new_protected:Npn \OERFitWriteSource #1#2
    { \exp_args:Nc \iow_now:Ne { @auxout } { \token_to_str:N \OERFitSource {#1}{#2} } }
  % A column of words' width (\OERFitStepsWidth: the table, the column,
  % the width). An .aux file written before a table could have more than
  % one such column, as a latex target's folder can keep, has a step's one
  % as \OERFitStepsState, with no column, which is read as nothing: with a
  % third argument, it would take the next line of the .aux for one.
  \cs_new_protected:Npn \OERFitStepsWidth #1#2#3 { \directlua { oerfit.steps_state(#1, #2, #3) } }
  \cs_new_protected:Npn \OERFitStepsState #1#2 { }
  \cs_new_protected:Npn \OERFitStepsWrite #1#2#3
    { \exp_args:Nc \iow_now:Ne { @auxout } { \token_to_str:N \OERFitStepsWidth {#1}{#2}{#3} } }
  % Before any fit the .aux file keeps is set, whether a file of the book
  % has changed since: one LaTeX has read lines of since these macros, or
  % input with \input{} before them, as its list of files says.
  \AddToHook { begindocument } { \directlua { oerfit.check() } }
  \AddToHook { enddocument / afterlastpage }
    { \legacy_if:nT { @filesw } { \directlua { oerfit.decide() } } }
  % The margin a centered table or display may run into: the narrower of
  % the page's margins, on either side of a two-sided page, less a quarter
  % inch at the paper's edge; none on a page of two columns, where it would
  % be the other column.
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
  % And the margin a formula in text, a numbered display, or a block of
  % code may run into, none of which is centered: the right one, the
  % narrower of the two on a two-sided page, less a quarter inch at the
  % paper's edge, where the narrower of all four had been, so that code ran
  % into a wider right margin only as far as a narrower left one allowed.
  \cs_new_protected:Npn \__oer_fit_right_margin:
    {
      \dim_set:Nn \l__oer_fit_margin_dim
        {
          \legacy_if:nTF { @twoside }
            {
              \dim_min:nn { \paperwidth - 1in - \hoffset - \oddsidemargin - \textwidth }
                { \paperwidth - 1in - \hoffset - \evensidemargin - \textwidth }
            }
            { \paperwidth - 1in - \hoffset - \oddsidemargin - \textwidth }
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
  % What the run before decided for a table, a formula, or a block of
  % code: #1 its kind, t a table whose columns don't wrap, p one whose do,
  % s a worked example's steps, d a display formula, e a numbered one, i a
  % formula in text, c a block of code; #2 its spaces narrowed or not; #3 its type's size, a part of its own; #4 a
  % wrapping table's columns' width, a part of the widths its LaTeX gives
  % them; #5 centered or not; #6 a table's number of columns; and #7 1
  % where a block of code's lines wrap.
  \cs_new_protected:Npn \OERFitApply #1#2#3#4#5#6#7
    {
      \int_compare:nNnT {#7} = { 1 } { \__oer_fit_wrap: }
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
              { s } { \dim_set:Nn \tabcolsep { 0.25 em } }
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
        }
      \str_case:nnT {#1} { { p } { } { s } { } } { \int_set:Nn \tex_hyphenpenalty:D { 10000 } }
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
  % columns, #3 1 where they wrap, 2 for a table LaTeX lays out
  % (\OERFitStepsTable). The widths longtable records are forgotten, so
  % that a table no longtable sets has none. A line of highlighted code in
  % a cell of one whose columns wrap is measured against its column, as a
  % line of a cell's paragraph is (\__oer_fit_code_lines:).
  \NewDocumentCommand \OERFitTable { m m m }
    {
      \setattribute \OERFitAttribute {#1}
      \cs_gset_eq:cN { LT@save@row } \scan_stop:
      \int_compare:nNnT {#3} = { 1 } { \__oer_fit_code_lines: }
      \__oer_fit_margin:
      \directlua
        {
          oerfit.open(#1, "\int_case:nnF {#3} { { 1 } { p } { 2 } { s } } { t }",
            \dim_to_decimal_in_sp:n { \hsize },
            \dim_to_decimal_in_sp:n { \hsize + 2 \l__oer_fit_margin_dim },
            \dim_to_decimal_in_sp:n { \use:c { f@size } pt }, #2,
            \int_use:N \tex_inputlineno:D, \dim_to_decimal_in_sp:n { \tabcolsep },
            \legacy_if:nTF { @twocolumn } { 1 } { 0 })
        }
    }
  % A worked example's steps, or a table whose source gives its columns
  % no widths, in a group pdf-target.lua opens: #1 its number, #2 its
  % columns, #3 their alignments' letters, and #4 for each column m, a
  % column of formulas, or a column of words' part of the line
  % pdf-target.lua's count gives it. A column of formulas is set as wide as
  % its widest, as the letter sets it, and a column of words wraps (p), as
  % wide as the run before decided from what LaTeX measured (oerfit.lt_array:
  % the longtable's column specification, in place of the writer's), or on
  % a first run that part of the line. Each paragraph of a column of words
  % is measured as LaTeX sets it, before its lines are broken: how wide it
  % is as one line, its longest piece TeX can't break, a formula whole, and
  % its longest with a formula's parts between its breaks apart, which in
  % the steps, whose formulas don't break, is the same; a fill-in blank no
  % more than three underscores, as it's drawn shorter to fit its line, and
  % a box as wide as the column not at all, the minipage the writer sets a
  % cell's lines in where they're broken where it says, whose paragraphs
  % are measured (oer.fit.steps). A writer's specification of another
  % number of columns, as an edit of the latex target's LaTeX can leave it,
  % is the table's, unmeasured.
  \NewDocumentCommand \OERFitStepsTable { m m m m }
    {
      \OERFitTable {#1} {#2} { 2 }
      \directlua { oerfit.steps_table(#1, "#3", "#4") }
      \cs_set_eq:Nc \OERFitLTArray { LT@array }
      \cs_set_protected:cpn { LT@array } [##1] ##2
        {
          \cs_set_eq:cN { LT@array } \OERFitLTArray
          \directlua
            {
              oerfit.lt_array(#1, "\luaescapestring{##1}",
                "\luaescapestring{\tl_to_str:n{##2}}")
            }
        }
    }
  % A table's end: its width, by the widths longtable recorded, none where
  % no longtable was set in the group, which leaves it as it is, and each
  % column's, for a worked example's steps.
  \NewDocumentCommand \OERFitTableEnd { m }
    {
      \dim_gzero:N \g__oer_fit_dim
      \directlua { oerfit.entries[#1] = { n = 0 } }
      \cs_if_exist:cT { LT@save@row }
        {
          \group_begin:
            \cs_set:cpn { LT@entry } ##1 ##2
              {
                \dim_gadd:Nn \g__oer_fit_dim {##2}
                \directlua { oerfit.entry(#1, \dim_to_decimal_in_sp:n {##2}) }
              }
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
  % the margin to the right of their line (\__oer_fit_right_margin:). A
  % display isn't fitted under the fleqn class option, which sets it a
  % margin from the line's left end, in a box as wide as the line.
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
          \str_if_eq:nnTF {#2} { d } { \__oer_fit_margin: } { \__oer_fit_right_margin: }
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
  % A line of highlighted code, as fancyvrb sets one, measured as LaTeX
  % sets it, in a group of a block of code or of a table whose columns
  % wrap: by the box its characters are set in, through
  % \FancyVerbFormatLine, fancyvrb's own command for a line, which the
  % group wraps and puts back, against the line it's in, for what the
  % attribute names, the innermost (oerfit.code_line): a footnote's code in
  % a table's cell is the code's. Wrapped once, in the outermost group.
  \box_new:N \l__oer_fit_code_box
  \bool_new:N \l__oer_fit_code_lines_bool
  \bool_new:N \l__oer_fit_wrap_bool
  \cs_new_protected:Npn \__oer_fit_code_lines:
    {
      \bool_if:NF \l__oer_fit_code_lines_bool
        {
          \cs_if_exist:NT \FancyVerbFormatLine
            {
              \bool_set_true:N \l__oer_fit_code_lines_bool
              \cs_set_eq:NN \__oer_fit_code_line:n \FancyVerbFormatLine
              \cs_set:Npn \FancyVerbFormatLine ##1
                {
                  \hbox_set:Nn \l__oer_fit_code_box { \__oer_fit_code_line:n {##1} }
                  \directlua
                    {
                      oerfit.code_line(\int_eval:n { \l__oer_fit_code_box },
                        \dim_to_decimal_in_sp:n { \linewidth })
                    }
                  \bool_if:NTF \l__oer_fit_wrap_bool
                    { \__oer_fit_wrap_line: }
                    { \hbox_unpack_drop:N \l__oer_fit_code_box }
                }
            }
        }
    }
  % A block of code whose lines wrap: one too long for the paper even at
  % half its size, set at three quarters (oerfit.next), each line too long
  % for its line broken where it reaches the line's end, the line the fit
  % measured it against, the text's or a quotation's, not into the margin.
  % What it holds is marked
  % (\OERFitWrapAttribute), so that TeX may break a paragraph of it: LaTeX's
  % verbatim's lines, each a paragraph already, and a line of fancyvrb's
  % too long for its line, set as one here, in a box where fancyvrb puts
  % the line's (\__oer_fit_wrap_line:), as fvextra sets a line it breaks.
  % That box is as deep as its lines, from its first line's base, and TeX
  % sets the next line under it by its depth: so each of fancyvrb's lines
  % in the block holds a strut, the line's height above its base and its
  % depth below, and the block sets lines touching where they would
  % otherwise come closer than its spacing, no space between them, so that
  % a line follows a wrapped one at the block's spacing, its own strut's
  % height under the wrapped one's last. Before TeX breaks such a
  % paragraph (oer.fit.wrap, above), it's measured whole, for the fit, by
  % what it holds, in Lua, whose sums run past TeX's largest dimension;
  % within half a point of its line it isn't broken, as fancyvrb's line
  % isn't. It may break after a run of spaces, no-break spaces among them,
  % the space kept at the line's end, which tagpdf writes as a space
  % character, so the line's text is as written: the break, a penalty, has
  % the attributes of the character before the space, since the line's
  % right skip takes the break's, and with the space's tagpdf wrote a
  % second space for it. Or between two characters, after a mark rather
  % than between two letters, a mark's break dearer than a part a space
  % ends can cost, (10 + 100) squared at most with the right skip below, so
  % a word that fits the next row whole goes there; but not to part a
  % character of no width, as a combining mark is once it's set, from the
  % letter it's on: that's the letter before it, but for a mark of a
  % right-to-left script that HarfBuzz shapes (luaotfload's harf mode, as
  % the fallback fonts are loaded), which is set before its letter, as a
  % review found a Hebrew point, which a break left on the line before,
  % where node mode sets it after. Each part after the
  % first hangs the line's indentation (no-break spaces counted, as
  % OpenStax indents code) and two characters further in, a character as
  % wide as the first that has a width, but no further
  % than leaves ROOM characters to a part, where the most had been half
  % the text's width, which set the parts of a line indented further left
  % of its text, and broke a long word's line right after its
  % indentation, leaving its row blank. A run of blanks is one place to
  % break, after it, the indentation too, which TeX takes only where the
  % parts after it have more room than its row, a line indented deeper
  % than leaves ROOM characters: its text then on the next row where its
  % first word doesn't fit after the indentation, rather than run off the
  % paper. Elsewhere a long word after the indentation breaks where the
  % row ends, the parts after it having no more room.
  % The hang is a left skip that much wider, and a kern taking it back
  % from the first line, which a list's paragraph shape doesn't override,
  % as it does a hanging indent. Its right skip ends a part at the line's
  % end, the fit's line from \OERFitCode (oerfit.right), whatever the
  % paragraph's line: a quotation's line ends inside the text's, where
  % LaTeX's own verbatim sets only a left skip, and latex-lab's a
  % paragraph shape 30 points shorter than the quotation's line, as of
  % 2026-06-01, so that its parts had ended 30 points inside it. It
  % stretches as far as the line is wide, so that TeX fills a line
  % before breaking it; the paragraph's discretionaries are taken out, as
  % the line shows them unbroken, so nothing is hyphenated; and a line's
  % parts stay on a page together, as a box's do, unless they take more
  % than half the page: then they break across pages, as a paragraph's
  % lines do (oer.fit.unwrap), where a line too long for a page left its
  % page blank and ran off the next's foot. oer.fit.unwrap puts the
  % paragraph's settings back once it's broken, and keeps for the run's
  % report whether a line of fancyvrb's is taller than the page, its box
  % unbroken (oerfit.tall).
  \cs_new_protected:Npn \__oer_fit_wrap:
    {
      \bool_set_true:N \l__oer_fit_wrap_bool
      \setattribute \OERFitWrapAttribute { 1 }
      \skip_zero:N \lineskip
      \dim_zero:N \lineskiplimit
    }
  % fancyvrb's line, set in \l__oer_fit_code_box: as it is where it fits
  % its line, and otherwise as a paragraph as wide as the line, which TeX
  % breaks. The line is the fit's (\l__oer_fit_code_end_dim, from
  % \OERFitCode) from where fancyvrb's begins: fancyvrb's own is the text's
  % width less the left margin, a quotation's right margin in it. Its
  % width is read in Lua, which reads one past TeX's largest dimension,
  % about 2,275 characters at 12 points, where TeX stopped. LaTeX's tagging
  % tags no paragraph in such a box (2026-06-01): the line's text is its
  % line's (block/verbatim/codeline), as before. The box can't break
  % across pages, as fvextra's can't, which is why oer.fit.unwrap says
  % where one is taller than the page.
  \dim_new:N \l__oer_fit_code_end_dim
  \dim_new:N \l__oer_fit_code_row_dim
  \cs_new_protected:Npn \__oer_fit_wrap_line:
    {
      \dim_set:Nn \l__oer_fit_code_row_dim { \l__oer_fit_code_end_dim - \leftmargin }
      \dim_compare:nNnTF
        { \directlua { oerfit.box_width(\int_eval:n { \l__oer_fit_code_box }) } sp }
        > { \l__oer_fit_code_row_dim + 0.5 pt }
        {
          \vtop
            {
              \hsize \l__oer_fit_code_row_dim
              \skip_zero:N \leftskip
              \tex_parshape:D 0 \scan_stop:
              \dim_zero:N \parindent
              \skip_set:Nn \parfillskip { 0pt plus 1fil }
              \directlua { oerfit.boxed = true }
              \leavevmode \strut \hbox_unpack_drop:N \l__oer_fit_code_box \strut \par
              \directlua { oerfit.boxed = false }
            }
        }
        { \strut \hbox_unpack_drop:N \l__oer_fit_code_box }
    }
  % A block of code, between \OERFitCode and \OERFitCodeEnd, which
  % pdf-target.lua writes around it, a group: #1 its number. Its lines are
  % measured as LaTeX sets them, each by what it holds: fancyvrb's, as
  % Pandoc's writer sets highlighted code (Highlighting) and code in a
  % footnote (Verbatim), as above; and LaTeX's verbatim's, code in no
  % language, whose lines are each a paragraph of one line, by that line,
  % less the glue at its edges, the left one the margin of the list it's
  % in (oer.fit.cells); not a paragraph the output routine sets, a page's
  % footer, while the group is open across a page's break. It's fitted as
  % a formula in text is: not centered, running on into the margin to the
  % right of its line, its spaces left as they are, since they're
  % characters, and its type set smaller, as much as it takes, but to
  % three quarters of its size at least, and smaller still, to half at
  % least, where it would come within a quarter inch of the paper's edge on
  % its right; its lines closer with its type, as a table's are. One that
  % would come that near even at half is set at three quarters, and its
  % lines too long for their line wrap (\__oer_fit_wrap:, above), where
  % it ran off the paper: in OpenStax's books, 7 of 667 blocks of code, 5 of
  % Principles of Data Science's (a paragraph written as a string, 749
  % characters) and 2 of Introduction to Python Programming's. One still
  % wider than its line is said to be by how far it runs past the text's
  % edge, none in a quotation's right margin, and one whose lines wrap is
  % said to, and to be too tall where a line of it fancyvrb sets runs
  % off its page. The log says where each
  % begins and ends, so that a line LaTeX reports as too wide between them,
  % one of verbatim's, is known as code's (latexbuild.overfull_lines):
  % TeX names a line by the line of the file it's reading, the book's or,
  % in a footnote, the file footnote-code.lua wrote the code to, and a
  % footnote's own paragraphs by the line its text ends on.
  \NewDocumentCommand \OERFitCode { m }
    {
      \group_begin:
      \typeout { TextbookImprover~code }
      \setattribute \OERFitAttribute {#1}
      \__oer_fit_right_margin:
      \directlua
        {
          oerfit.open(#1, "c", \dim_to_decimal_in_sp:n { \linewidth },
            \dim_to_decimal_in_sp:n
              { \hsize - \use:c { @totalleftmargin } + \l__oer_fit_margin_dim },
            \dim_to_decimal_in_sp:n { \use:c { f@size } pt }, 0, \int_use:N \tex_inputlineno:D,
            0, \legacy_if:nTF { @twocolumn } { 1 } { 0 })
          oerfit.edge[#1] = \dim_to_decimal_in_sp:n { \hsize - \use:c { @totalleftmargin } }
          oerfit.right[#1] = \dim_to_decimal_in_sp:n { \use:c { @totalleftmargin } + \linewidth }
        }
      \dim_set:Nn \l__oer_fit_code_end_dim { \use:c { @totalleftmargin } + \linewidth }
      \__oer_fit_code_lines:
    }
  \NewDocumentCommand \OERFitCodeEnd { m }
    {
      \typeout { TextbookImprover~code~end }
      \group_end:
    }
  % A line of code in no language is never broken: LaTeX's own verbatim
  % sets its right skip with no stretch, which a break at a hyphen would
  % leave short, and latex-lab's sets it as the paragraph's, which
  % build-pdf.py's ragged right gives a stretch, so that TeX broke a line
  % too long for its line after a hyphen, as LuaTeX may break after one,
  % where it now runs on whole, to be fitted.
  \AddToHook { env / verbatim / begin } { \int_set:Nn \tex_exhyphenpenalty:D { 10000 } }
  \ExplSyntaxOff
\else
  \NewDocumentCommand\OERFitTable{mmm}{}
  \NewDocumentCommand\OERFitStepsTable{mmmm}{}
  \NewDocumentCommand\OERFitTableEnd{m}{}
  \NewDocumentCommand\OERFitFormula{mm}{}
  \NewDocumentCommand\OERFitCode{m}{}
  \NewDocumentCommand\OERFitCodeEnd{m}{}
  \def\OERFitState#1#2#3#4#5{}
  \def\OERFitWrap#1{}
  \def\OERFitStepsWidth#1#2#3{}
  \def\OERFitStepsState#1#2{}
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
% A table ruled row by row (pdf-target.lua's ROW_RULES), in a group with
% \OERRowRules: none of the rules the writer draws above it, under its
% head, and below it (\toprule, \midrule, and \bottomrule, each followed
% by \noalign{}, which is left alone), and booktabs' rules in OpenStax's
% gray (\CT@arc@, booktabs' hook for colortbl's color), or the color its
% optional argument gives, as #rrggbb's digits (a calculus book's Key
% Equations, F1F1F1). A row ruled ends
% with \OERRowRule, and the rule is put after the \noalign longtable
% opens the next row with (the tbl/row/init hook, \group_insert_after:N),
% where a rule between rows goes: booktabs' \specialrule, a \midrule's
% width and space, which in a long table is a row of its own across the
% table's columns, not the line's, an artifact where LaTeX tags
% (latex-lab's firstaid module), and kept on the page of the row above
% it. After the last row of one of the chunks longtable sets a table in
% (\LTchunksize rows, 200), that \noalign is the next chunk's, and the
% rule goes there: put at the row's end (tbl/row/end), in the chunk the
% row ended, it stopped LaTeX's tagging ("\ERRORtbl/row"), since
% latex-lab counts a rule's row off for longtable to count on again
% after it, which longtable doesn't at a chunk's end. The \noalign{}
% after the rule, as after the writer's own, keeps it from taking a row
% that opens with "(" for the columns to trim it to.
\bool_new:N \g__oer_row_rule_bool
\NewDocumentCommand \OERRowRule { } { \bool_gset_true:N \g__oer_row_rule_bool }
\NewDocumentCommand \OERRowRules { O { 757474 } }
  {
    \bool_gset_false:N \g__oer_row_rule_bool
    \cs_set_eq:NN \toprule \prg_do_nothing:
    \cs_set_eq:NN \midrule \prg_do_nothing:
    \cs_set_eq:NN \bottomrule \prg_do_nothing:
    \cs_set:cpn { CT@arc@ } { \color [HTML] {#1} }
  }
\cs_new:Npn \__oer_row_rule:
  { \specialrule { \lightrulewidth } { \aboverulesep } { \belowrulesep } \noalign { } }
\AddToHook { tbl / row / init }
  {
    \bool_if:NT \g__oer_row_rule_bool
      {
        \bool_gset_false:N \g__oer_row_rule_bool
        \group_insert_after:N \__oer_row_rule:
      }
  }
% A link's description, which \pdfstringdef sets globally, and so it's
% cleared globally too: cleared in a group (a footnote, a cell, a
% caption), it came back at the group's end, and in a PDF/UA-1 book a
% link LaTeX made on its own after it got no /Contents (UA1_LINKS).
\tl_new:N \g__oer_link_contents_tl
\NewDocumentCommand \OERLinkContents { m }
  {
    \cs_if_exist:NT \pdfannot_dict_put:nne
      {
        \pdfstringdef \g__oer_link_contents_tl {#1}
        \pdfannot_dict_put:nne {link/URI} {Contents}
          { (\g__oer_link_contents_tl) }
        \pdfannot_dict_put:nne {link/GoTo} {Contents}
          { (\g__oer_link_contents_tl) }
      }
  }
\NewDocumentCommand \OERLinkContentsReset { }
  {
    \tl_gclear:N \g__oer_link_contents_tl
    \cs_if_exist:NT \pdfannot_dict_remove:nn
      {
        \pdfannot_dict_remove:nn {link/URI} {Contents}
        \pdfannot_dict_remove:nn {link/GoTo} {Contents}
      }
  }
% A link in a caption is in its entry in the list of figures or tables
% too, whose structure element LaTeX titles with the entry's text made
% plain (\text_purify:n), which kept the description and the link's
% target: "has a linked wordhttps://example.org/captiona linked word in
% it", and a link within the book its target's name in brackets. A
% description is left out, and a link is its text: an \href's, an
% optional argument before its address too, as hyperref's own
% \pdfstringdef takes it; a \hyperref's, Pandoc's [id]{text} or the
% four-argument form; and a linked citation's (\citeproc, from Pandoc's
% template). hyperref's are declared once it's loaded, so that its own
% declarations, were it to make any, come first.
\cs_new:Npn \__oer_purify_href:w #1 # { \use_ii:nn }
\cs_new:Npn \__oer_purify_hyperref:w #1 #
  { \tl_if_blank:nTF {#1} { \use_iv:nnnn } { \use:n } }
\text_declare_purify_equivalent:Nn \OERLinkContents { \use_none:n }
\text_declare_purify_equivalent:Nn \OERLinkContentsReset { }
\text_declare_purify_equivalent:Nn \citeproc { \use_ii:nn }
\AddToHook { package / hyperref / after }
  {
    \text_declare_purify_equivalent:Nn \href { \__oer_purify_href:w }
    \text_declare_purify_equivalent:Nn \hyperref { \__oer_purify_hyperref:w }
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
% A picture's alt text, which latex-lab makes its figure's /Alt by making
% the alt key's text plain (\pdf_purify:nN). Pandoc's writer writes a
% straight quote there as \textquotesingle, a bar, <, >, ~, and \ as
% commands, and ^ as \^{}, which /Alt had as written ("a cell
% \textquotesingle s"), and curly quotes and dashes as TeX's ligatures,
% `` '' ` ' -- ---, which only a font makes the characters they stand
% for. The commands made plain are their characters, here and wherever
% text is made plain, and the alt key's ^ and ligatures are made
% characters before latex-lab reads it; -\/-, two hyphens as written,
% stays two.
\text_declare_purify_equivalent:Nn \textquotesingle { ' }
\text_declare_purify_equivalent:Nn \textbar { | }
\text_declare_purify_equivalent:Nn \textless { < }
\text_declare_purify_equivalent:Nn \textgreater { > }
\text_declare_purify_equivalent:Nn \textasciitilde { \c_tilde_str }
\text_declare_purify_equivalent:Nn \textbackslash { \c_backslash_str }
\tl_new:N \l__oer_alt_tl
\cs_new_protected:Npn \__oer_alt:n #1
  {
    \tl_set:Nn \l__oer_alt_tl {#1}
    \regex_replace_all:nnN { \c{\^} \cB. \cE. } { \cO\^ } \l__oer_alt_tl
    \tl_replace_all:Nnn \l__oer_alt_tl { --- } { ^^^^2014 }
    \tl_replace_all:Nnn \l__oer_alt_tl { -- } { ^^^^2013 }
    \tl_replace_all:Nnn \l__oer_alt_tl { `` } { ^^^^201c }
    \tl_replace_all:Nnn \l__oer_alt_tl { '' } { ^^^^201d }
    \tl_replace_all:Nnn \l__oer_alt_tl { ` } { ^^^^2018 }
    \tl_replace_all:Nnn \l__oer_alt_tl { ' } { ^^^^2019 }
    \exp_args:NV \__oer_gin_alt:n \l__oer_alt_tl
  }
\AddToHook { begindocument/before }
  {
    \cs_if_exist:cT { KV@Gin@alt }
      {
        \cs_set_eq:Nc \__oer_gin_alt:n { KV@Gin@alt }
        \cs_set_eq:cN { KV@Gin@alt } \__oer_alt:n
      }
  }
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
% A list's item that opens with fancyvrb's code, as Pandoc sets
% highlighted code (Highlighting), has its label beside the code's first
% line. LaTeX's tagging code for lists (latex-lab-testphase-block.sty)
% keeps an item's label in \g__block_labels_box, not \@labels, and sets it
% when the item's first paragraph begins (the para/begin hook). fancyvrb's
% lines aren't paragraphs: its list sets \@inlabel false (\FV@ListVSpace)
% and puts \@labels beside its first line, which the tagging code leaves
% empty, so the label waited for the next item's paragraph and was set
% there, over that item's ("2." over "3."); the PDF's structure had it in
% its own item all the same. Before fancyvrb clears \@inlabel, a label
% waiting there is moved to \@labels, where fancyvrb sets one, as it did
% before the tagging code. Only a label that's waiting: a fix of LaTeX's
% own, which would leave none, isn't undone, and without the tagging code,
% or with its box named otherwise, nothing is done. LaTeX's own verbatim,
% as Pandoc sets code in no language, sets each line as a paragraph,
% which sets the label.
\cs_if_exist:NT \g__block_labels_box
  {
    \AddToHook { package / fancyvrb / after }
      {
        \AddToHook { cmd / FV@ListVSpace / before }
          {
            \legacy_if:nT { @inlabel }
              {
                \box_if_empty:NF \g__block_labels_box
                  {
                    \box_gset_eq:cN { @labels } \g__block_labels_box
                    \box_gclear:N \g__block_labels_box
                  }
              }
          }
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
% And in the text, a Span whose ActualText is "blank", which a screen
% reader should say in place of the underscores, and copying give, where
% a screen reader was left to read them as its punctuation setting has
% it; untagged, the underscores alone. The underscores are drawn, and
% marked, as before.
\NewDocumentCommand \OERBlankSpan { m }
  {
    \cs_if_exist:NTF \tag_mc_end_push:
      {
        \mode_leave_vertical:
        \tag_mc_end_push:
        \tag_struct_begin:n { tag = Span , actualtext = blank }
        \tag_mc_begin:n { }
        #1
        \tag_mc_end:
        \tag_struct_end:
        \tag_mc_begin_pop:n { }
      }
      { #1 }
  }
\ExplSyntaxOff
""" + PICTURE_PATHS + r"""% A fill-in blank, a run of four or more underscores pdf-target.lua marks
% (\OERBlank), that runs past the end of its line into the margin: TeX
% can't break a run of underscores, and Sociology's chapter 19 quiz had a
% question whose blank ran 24 points past its line. Once a paragraph's
% lines are made, such a blank is drawn shorter, its underscores
% overlapping, so it ends where the line does and the line's spaces are
% their natural width again; and so is one whose line is too wide for the
% text joined to its end, up to the next space outside a formula
% ("(____)", "____%", "____$x$"), which had run past the line though the
% blank itself ended within it. Every underscore is still drawn, its
% Span's ActualText what a screen reader says (above), and a blank that
% fits its line is left as it is. A blank is
% drawn no shorter than three underscores; a line that leaves less room
% than that still runs over. TeX has named the line as too wide
% (overfull) by then, so the log names each line fitted this way too: how
% much too wide TeX said it was, the line of LaTeX TeX said its paragraph
% ended on, and how much too wide it is now, which
% latexbuild.overfull_lines reads. In a paragraph of ragged lines, as the
% PDF target sets its text and a table's cells, a blank longer than two
% thirds of its line is drawn at two thirds of it before TeX breaks the
% paragraph into lines, so that words beside it that fit in the other
% third share its line, a label before it as "Name" is, where TeX had
% broken the line before the blank and drawn it shorter on a line of its
% own (Writing Guide with Handbook's form for drafting a position
% argument), and TeX is asked to end a line after it, or after a formula
% joined to it, where a penalty within the formula would have let TeX
% break it before its relation (a penalty of -51, as \linebreak[1]); once
% the lines are made, it's drawn as long as its line leaves room for, up
% to its whole length, to end where its line does. In a paragraph set
% flush to both margins, TeX keeps a label with a blank too long for its
% line itself, taking the line too wide as a last resort, which the blank
% is then drawn shorter to fit, and a line ending at a blank drawn at two
% thirds is too loose for TeX to take: the words after a blank that fitted
% its line with its label had shared the line, the blank drawn shorter. A
% blank drawn shorter, or drawn to fill its line, isn't hung into the
% margin, as microtype hangs an underscore at a line's start or end (a
% fifth of its width in Latin Modern, 1.8 points at 12): the margin's kern
% beside it is set to nothing before it's drawn, so it begins and ends
% where the line does, and a line with no room for that gets back as much
% of the kern as it needs. Hung, a blank drawn to its line's end ran 1.8
% points past its column. A blank that fits as TeX set it keeps its hang,
% as any character at a margin does, beside a blank drawn on its line too,
% and so does a blank drawn at two thirds that its line has room for
% whole; whether a blank reaches past its line's end is measured as TeX
% set the line, hangs and all. With the hang set to nothing and the line's
% spaces set again, a line TeX had shrunk to fit, opening with a blank,
% ran past the margin, and a blank that fitted at a line's end was drawn
% shorter by the space TeX had taken from the line; with the hang put
% back before a blank was drawn to fill its line, a blank alone on a line
% of a narrow column hung past it; and with every hang on a line set to
% nothing where one blank was drawn, a blank beside it lost its own, and
% one that fitted, measured without the other's hang, could be drawn
% shorter. The underscores
% overlap by kerns this marks, the attribute's value 2 to an underscore's
% 1, which FIT_MACROS' measures leave out, taking such a blank as its
% underscores, three at most. In a cell of a table whose columns
% wrap, FIT_MACROS (after these macros, so that its post_linebreak_filter
% function runs first, LaTeX running them last registered first) measures
% a blank as no more than three underscores, as this draws it, so a blank
% too long for its column doesn't of itself set its table in smaller
% type. The Lua is written without a percent sign, a hash, a tilde, or a
% backslash, which TeX would read as its own, and without a comment,
% which would run on to the end, TeX joining the lines.
\ifdefined\directlua
  \newattribute\OERBlankAttribute
  \NewDocumentCommand\OERBlank{m}
    {\leavevmode\OERBlankSpan{\setattribute\OERBlankAttribute{1}#1\unsetattribute\OERBlankAttribute}}
  \directlua{
    local attribute = luatexbase.attributes.OERBlankAttribute
    local GLYPH, GLUE, KERN, HLIST, PENALTY = node.id("glyph"), node.id("glue"), node.id("kern"), node.id("hlist"), node.id("penalty")
    local MARGIN, MATH = node.id("margin_kern"), node.id("math")
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
    local function runs_of(head)
      local runs, count, run = {}, 0, nil
      for n in node.traverse(head) do
        if n.id == GLYPH and n.char == 95 and node.has_attribute(n, attribute, 1) then
          if run then
            run.size = run.size + 1
            run.glyphs[run.size] = n
          else
            run = { glyphs = { n }, size = 1, drawn = false }
            count = count + 1
            runs[count] = run
          end
        elseif n.id == KERN and run then
          if node.has_attribute(n, attribute, 2) then run.drawn = true end
        else
          run = nil
        end
      end
      for i = 1, count do
        run = runs[i]
        run.width = node.dimensions(run.glyphs[1], run.glyphs[run.size].next)
        run.natural = run.width
        local n = run.glyphs[1]
        while not (n == run.glyphs[run.size]) do
          if n.id == KERN then run.natural = run.natural - n.kern end
          n = n.next
        end
        run.least = 3 * run.natural // run.size
      end
      return runs, count
    end
    local function draw(head, run, width)
      local last, n = run.glyphs[run.size], run.glyphs[1].next
      while n and not (n == last) do
        local after = n.next
        if n.id == KERN then
          head = node.remove(head, n)
          node.free(n)
        end
        n = after
      end
      width = math.max(run.least, math.min(run.natural, width))
      local total = run.natural - width
      if total > 0 then
        local each = total // (run.size - 1)
        local left = total - each * (run.size - 1)
        for j = 1, run.size - 1 do
          local kern = node.new(KERN, 1)
          kern.kern = 0 - each - ((j <= left) and 1 or 0)
          node.set_attribute(kern, attribute, 2)
          head = node.insert_after(head, run.glyphs[j], kern)
        end
      end
      run.width, run.drawn = width, total > 0
      return head
    end
    local function line_width()
      local width, shape = tex.hsize, tex.parshape
      if type(shape) == "table" then
        for _, entry in ipairs(shape) do width = entry[2] end
      end
      return width - tex.leftskip.width - tex.rightskip.width
    end
    local function shrink_of(line)
      local shrink = 0
      for glue in node.traverse_id(GLUE, line.head) do
        if glue.shrink_order == 0 then shrink = shrink + glue.shrink end
      end
      return shrink
    end
    local function settle(line, excess)
      line.glue_set, line.glue_sign, line.glue_order = 0, 0, 0
      if excess > 0 then
        local shrink = shrink_of(line)
        if shrink > 0 then
          line.glue_set, line.glue_sign = math.min(1, excess / shrink), 2
        end
      elseif excess < 0 then
        local totals = { 0, 0, 0, 0, 0 }
        for glue in node.traverse_id(GLUE, line.head) do
          totals[glue.stretch_order + 1] = totals[glue.stretch_order + 1] + glue.stretch
        end
        for order = 4, 0, -1 do
          if totals[order + 1] > 0 then
            line.glue_set, line.glue_sign, line.glue_order = (0 - excess) / totals[order + 1], 1, order
            break
          end
        end
      end
    end
    local function after(run)
      local stop, inmath = run.glyphs[run.size].next, false
      while stop and not (stop.id == GLUE and not inmath) do
        if stop.id == MATH then inmath = stop.subtype == 0 end
        stop = stop.next
      end
      return stop
    end
    luatexbase.add_to_callback("pre_linebreak_filter", function(head)
      local runs, count = runs_of(head)
      if count == 0 then return true end
      if not (tex.rightskip.stretch_order > 0 or tex.leftskip.stretch_order > 0) then return true end
      local width = line_width()
      local most = width - width // 3
      for i = 1, count do
        local run = runs[i]
        if run.size > 3 and run.natural > most then
          head = draw(head, run, most)
          local stop = after(run)
          if stop and not (stop.prev.id == PENALTY) then
            local penalty = node.new(PENALTY)
            penalty.penalty = 0 - 51
            node.set_attribute(penalty, attribute, 2)
            head = node.insert_before(head, stop, penalty)
          end
        end
      end
      return head
    end, "oer.blanks.lines")
    local function unprotrude(line, runs, count, chosen)
      local edges, edged = {}, 0
      for n in node.traverse_id(MARGIN, line.head) do
        local beside = n.next
        if n.subtype == 1 then beside = n.prev end
        while beside and not (beside.id == GLYPH) and node.dimensions(beside, beside.next) == 0 do
          if n.subtype == 1 then beside = beside.prev else beside = beside.next end
        end
        if beside and beside.id == GLYPH and not (n.width == 0) then
          for i = 1, count do
            local run = runs[i]
            if chosen[i] and (beside == run.glyphs[1] or beside == run.glyphs[run.size]) then
              edged = edged + 1
              edges[edged] = { beside, n.width, n, run }
              n.width = 0
            end
          end
        end
      end
      return edges, edged
    end
    local function fit(line)
      local runs, count = runs_of(line.head)
      if count == 0 then return end
      local over = node.dimensions(line.glue_set, line.glue_sign, line.glue_order, line.head) - line.width
      local drawn = false
      for i = 1, count do drawn = drawn or runs[i].drawn end
      if not drawn and (line.glue_sign == 1 or over <= tex.hfuzz) then return end
      local sign, set, order = line.glue_sign, line.glue_set, line.glue_order
      if drawn then sign, set, order = 0, 0, 0 end
      local function reach(run, set, sign, order)
        local stop = after(run)
        return stop and node.dimensions(set, sign, order, line.head, stop)
          or node.dimensions(set, sign, order, line.head)
      end
      local chosen, any = {}, false
      for i = 1, count do
        local run = runs[i]
        chosen[i] = run.drawn or (run.size > 3 and run.width > run.least
          and reach(run, line.glue_set, line.glue_sign, line.glue_order) > line.width)
        any = any or chosen[i]
      end
      if not any then return end
      local edges, edged = unprotrude(line, runs, count, chosen)
      local need, shortened = node.dimensions(line.head) - line.width, false
      local again = true
      while again do
        again = false
        if need < 0 then
          for i = 1, count do
            local run = runs[i]
            if run.drawn and need < 0 then
              local wider = math.min(0 - need, run.natural - run.width)
              line.head = draw(line.head, run, run.width + wider)
              need = need + wider
            end
          end
        else
          for i = 1, count do
            local run = runs[i]
            if chosen[i] and need > 0 and run.size > 3 and run.width > run.least and reach(run, set, sign, order) > line.width then
              local take = math.min(need, run.width - run.least)
              line.head = draw(line.head, run, run.width - take)
              need, shortened = need - take, true
            end
          end
        end
        for k = 1, edged do
          local edge = edges[k]
          if edge[3].width == 0 and not edge[4].drawn then
            edge[3].width = edge[2]
            need = need + edge[2]
            again = true
          end
        end
      end
      for k = 1, edged do
        local back = math.min(need, 0 - edges[k][2])
        if back > 0 and edges[k][3].width == 0 then
          edges[k][3].width = 0 - back
          need = need - back
        end
      end
      if not (drawn or shortened) then
        for k = 1, edged do edges[k][3].width = edges[k][2] end
        return
      end
      settle(line, need)
      if over > tex.hfuzz and shortened then
        texio.write_nl("term and log", "TextbookImprover blank: " .. points(over)
          .. "pt over at line " .. tostring(tex.inputlineno) .. ", now "
          .. points(math.max(0, need - shrink_of(line))) .. "pt")
        texio.write_nl("term and log", "")
      end
    end
    luatexbase.add_to_callback("post_linebreak_filter", function(head)
      for line in node.traverse_id(HLIST, head) do
        if line.subtype == 1 then fit(line) end
      end
      return true
    end, "oer.blanks")
  }
\else
  \NewDocumentCommand\OERBlank{m}{\OERBlankSpan{#1}}
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
# Where LaTeX sets a block of code, as FIT_MACROS' \OERFitCode and
# \OERFitCodeEnd mark it: a line too wide there is the code's, which
# fit_report names.
CODE_MARKS = re.compile(r"^TextbookImprover code( end)?$", re.M)
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
    list, on no page. A line of a block of code isn't one, wherever TeX
    says it is (CODE_MARKS): fit_report names a block still too wide."""
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
    # A block of code's lines, which fit_report names, fitted or still too
    # wide: what LaTeX said while it set one, not the lines of the LaTeX
    # between pdf-target.lua's \OERFitCode and \OERFitCodeEnd, since TeX
    # names a footnote's code's line by the line of the file it's read from
    # and the footnote's own paragraphs by the line its text ends on.
    code, opened = [], None
    for m in CODE_MARKS.finditer(output):
        if not m.group(1):
            opened = m.end()
        elif opened is not None:
            code.append((opened, m.start()))
            opened = None
    if opened is not None:
        code.append((opened, len(output)))
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
        if any(start <= m.start() < end for start, end in code):
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


# What FIT_MACROS says it fitted on a run: how many of the tables,
# formulas, and blocks of code it numbered it has narrowed alone, and how
# many it set smaller, and the smallest part of its type's size any is in;
# and each that was still wider than its line on the run: its kind (t a
# table whose columns don't wrap, p one whose do, s one LaTeX lays out, a
# worked example's steps among them, d a display formula, e a numbered
# one, i a formula in text, c a block of code), how many points wider, the line of
# LaTeX its group opened on, the part of its type's size it was in,
# whether it was centered, whether it was on the paper, a quarter inch
# inside its edge, and whether its page has two columns, where it has no
# more room than its column.
FITTED = re.compile(r"^TextbookImprover fit: run (\d+), (\d+) narrowed, (\d+) smaller, "
                    r"smallest ([\d.]+)$", re.M)
FIT_WIDE = re.compile(r"^TextbookImprover fit wide: ([tpsdeic]) ([\d.]+) (\d+) ([\d.]+) ([01]) ([01]) "
                      r"([01])$", re.M)
# And each block of code whose lines wrap on the run, too long for the
# paper even at half its size: the line of LaTeX its group opened on, the
# part of its type's size it's in, and whether its page has two columns.
FIT_WRAPPED = re.compile(r"^TextbookImprover fit wrapped: (\d+) ([\d.]+) ([01])$", re.M)
# And each of them with a line of fancyvrb's, highlighted code's, taller
# than the page wrapped, which can't break across pages: the line of LaTeX
# its group opened on.
FIT_TALL = re.compile(r"^TextbookImprover fit tall: (\d+)$", re.M)


def fit_report(output, source, pages):
    """[lines to print] for what FIT_MACROS fitted, from what LaTeX's last
    run said (output) about its input (source), pages as overfull_lines
    takes them: what it fitted; what's still wider than the text, centered
    on the page, which LaTeX doesn't report as an overfull box, a block
    of code still wider than the text, running into the margin, and one
    whose lines wrap (FIT_WRAPPED); and, as
    warnings, what isn't a quarter inch inside the paper's edge even at the
    least it sets type in, what's wider than its column, on a page of
    two, and a block of code with a highlighted line too long for a page
    even wrapped (FIT_TALL). A formula still wider than its line, but a display centered
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
        said.append(f"Fitted {narrowed + smaller} table(s), formula(s), and block(s) of code "
                    f"too wide for their lines to them: "
                    + "; ".join(([f"{narrowed} by narrowing their spaces"] if narrowed else [])
                                + ([f"{smaller} in smaller type, the smallest at "
                                    f"{round(float(smallest) * 100)}% of its size"]
                                   if smaller else []))
                    + ".")
    # A table whose word runs a point into the space beside its column,
    # though the table fits its line, is no wider than the text.
    middle = sorted((w for w in wide if w[4] and w[5] and w[0] > 0), key=lambda w: -w[0])
    # A block of code isn't centered: one still wider than the text, by
    # how far it runs past the text's edge, runs into the margin on its
    # right (in a quotation, past the quotation's line but not the text's,
    # it's in the quotation's own margin, and not named), and
    # overfull_lines leaves its lines to this, LaTeX's verbatim's among
    # them, which LaTeX reports as lines of text, and fancyvrb's, which it
    # doesn't report at all.
    code = sorted((w for w in wide if w[1] == "c" and w[5] and not w[6] and w[0] > 0),
                  key=lambda w: -w[0])
    if code:
        said.append(f"{len(code)} block(s) of code, still wider than the text in smaller "
                    f"type, the smallest at {round(min(w[3] for w in code) * 100)}% of its "
                    f"size, {'runs' if len(code) == 1 else 'run'} into the margin on its "
                    f"right, the widest {code[0][0]:,.0f} points wider"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in code if w[2])))
                       if any(w[2] for w in code) else "")
                    + ".")
    # A block of code too long for the paper even at half its size, whose
    # lines wrap, is on the paper: said, not warned of.
    wrapped = [(page(line), float(factor)) for line, factor, _columns in FIT_WRAPPED.findall(output)]
    if wrapped:
        pages_wrapped = list(dict.fromkeys(p for p, _f in wrapped if p))
        said.append(f"{len(wrapped)} block(s) of code with a line too long for the paper even at "
                    f"half {'its' if len(wrapped) == 1 else 'their'} size "
                    f"{'is' if len(wrapped) == 1 else 'are'} set at "
                    f"{round(min(f for _p, f in wrapped) * 100)}% of "
                    f"{'its' if len(wrapped) == 1 else 'their'} size, each line too long for its "
                    "line wrapped where it reaches the line's end"
                    + (": on " + page_list(pages_wrapped) if pages_wrapped else "") + ".")
    # Highlighted code's line wrapped is set in a box, as fvextra sets one,
    # which TeX can't break across pages: one taller than the page runs
    # off its foot.
    tall = [page(line) for line in FIT_TALL.findall(output)]
    if tall:
        said.append(f"WARNING: {len(tall)} block(s) of code in a language "
                    f"{'has' if len(tall) == 1 else 'have'} a line too long for a page even "
                    "wrapped, which runs off its page's foot"
                    + (": on " + page_list(list(dict.fromkeys(p for p in tall if p)))
                       if any(tall) else "") + ".")
    if middle:
        tables = sum(1 for w in middle if w[1] in "tps")
        said.append(f"{len(middle)} of them, still wider than the text, "
                    f"{'is' if len(middle) == 1 else 'are'} centered on "
                    f"the page ({tables} table(s), {len(middle) - tables} display "
                    f"formula(s)), the widest {middle[0][0]:,.0f} points wider"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in middle if w[2])))
                       if any(w[2] for w in middle) else "")
                    + ".")
    off = sorted((w for w in wide if not w[5] and not w[6]), key=lambda w: -w[0])
    if off:
        said.append(f"WARNING: {len(off)} table(s), formula(s), or block(s) of code are too "
                    f"wide for the paper even in smaller type, the smallest at "
                    f"{round(min(w[3] for w in off) * 100)}% of its size, and run to within a "
                    "quarter inch of its edge or past it, the widest "
                    f"{off[0][0]:,.0f} points wider than the text"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in off if w[2])))
                       if any(w[2] for w in off) else "")
                    + ".")
    beside = sorted((w for w in wide if not w[5] and w[6]), key=lambda w: -w[0])
    if beside:
        said.append(f"WARNING: {len(beside)} table(s), formula(s), or block(s) of code on "
                    f"pages of two columns are too wide for their column even in smaller type, "
                    f"the smallest at "
                    f"{round(min(w[3] for w in beside) * 100)}% of its size, and run past it, "
                    f"the widest {beside[0][0]:,.0f} points wider than the column"
                    + (": on " + page_list(list(dict.fromkeys(w[2] for w in beside if w[2])))
                       if any(w[2] for w in beside) else "")
                    + ".")
    return said


def failure_advice(log):
    """What to do about a failed build, from its log: a file LaTeX can't
    find, the two packages picture mode and a struck-out term need among
    them, a language
    babel hasn't, a font that isn't installed, or one of TeX's tables
    outgrown."""
    said = []
    missing = list(dict.fromkeys(MISSING_FILE.findall(log)))
    # PICTURE_PATHS loads pict2e at \begin{document} for every PDF, unless
    # picture_paths is off, and for a formula's term struck out, which
    # Pandoc's template loads cancel for in the preamble; neither is in
    # TinyTeX or TeX Live's medium scheme, so a build stops on pict2e.sty,
    # which the book never names, and on cancel.sty where a term is struck
    # out. Both are named at once; a book that loads pict2e for drawings of
    # its own is told the same, cancel included.
    if {"cancel.sty", "pict2e.sty"} & set(missing):
        advice = ("LaTeX can't find cancel.sty or pict2e.sty. The run loads pict2e to draw "
                  "picture mode's lines, arrows, and circles as paths, a formula's "
                  "struck-out term's strokes among them, and a struck-out term "
                  "(\\cancel, \\bcancel, or \\xcancel) needs TeX's cancel package too. "
                  "For TinyTeX or TeX Live from tug.org, "
                  f"`{tlmgr_command('install cancel pict2e')}` installs both; for Debian's "
                  "or Ubuntu's texlive packages, `sudo apt install texlive-latex-extra "
                  "texlive-pictures`.")
        # A build that stopped on pict2e.sty alone may be a book that
        # strikes out no term, which builds without pict2e where
        # picture_paths is off, a setting of a target's or of defaults:,
        # unless its own LaTeX loads pict2e; one that stopped on cancel.sty
        # strikes a term out, and cancel's strokes load pict2e whatever the
        # setting.
        if "pict2e.sty" in missing and "cancel.sty" not in missing:
            advice += (" Or, where the book strikes out no term and its own LaTeX doesn't "
                       "load pict2e, `picture_paths: off` in conversion.yaml, under "
                       "`defaults:` or the target's name, builds without pict2e, LaTeX "
                       "drawing picture mode with its own fonts "
                       "(docs/conversion-settings.md); a struck-out term needs pict2e either "
                       "way.")
        said.append(advice)
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
                    "out gives the default, IBM Plex, or Latin Modern, with a warning, where "
                    "TeX lacks Plex. TeX Live has an OpenStax book's: "
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
