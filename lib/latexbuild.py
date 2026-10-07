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
import shutil
import subprocess
import tempfile

ENGINE = "lualatex"
# The LaTeX release the tagging project describes as usable in production
# for documents that keep to packages supporting it. Older releases load
# pdfmanagement-testphase.sty for \DocumentMetadata, where current ones
# load pdfmanagement-init (documentmetadata-support.ltx), and Ubuntu 24.04's
# texlive packages (LaTeX 2023-11-01) stop on that file not found; they
# would tag less if it were there. Verified here: 2026-06-01.
MINIMUM_LATEX = "2025-11-01"
MISSING_FILE = re.compile(r"File `([^']+)' not found")
MISSING = re.compile(r"Missing character: There is no (\S+)")
CAPACITY = re.compile(r"TeX capacity exceeded, sorry \[([^\]=]+)")


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
                f"PDF needs {MINIMUM_LATEX} or later (TeX Live 2026). "
                "Distribution packages are often older; docs/installation.md "
                "says how to install a current TeX Live.")
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
            for ref in (resources.get("/Font") or {}).values():
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
            for ref in (resources.get("/XObject") or {}).values():
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


def failure_advice(log):
    """What to do about a failed build, from its log: a file LaTeX can't
    find, or one of TeX's tables outgrown."""
    said = []
    # tlmgr only manages a TeX Live installed from tug.org or as TinyTeX;
    # Debian's and Ubuntu's texlive packages come with a tlmgr that runs in
    # an uninitialized user mode and installs nothing, so both routes are
    # named.
    for name in dict.fromkeys(MISSING_FILE.findall(log)):
        said.append(f"LaTeX can't find {name}. For TinyTeX or TeX Live "
                    f"from tug.org, `tlmgr search --global --file /{name}` "
                    "names the package that has it, and `tlmgr install` "
                    "installs that. For a distribution's texlive packages, "
                    "its package manager does (`apt-file search "
                    f"{name}` on Debian and Ubuntu).")
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
