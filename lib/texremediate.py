"""A remediated copy of an author's own LaTeX book: the decisions made
about it in the sidecars, written into the text where each element is, the
rest of every file exactly as the author wrote it. Nothing is parsed and
written again; an element is found the way lib/latexsource.py found it for
the conversion, so a decision reaches the element it was made about.

- **Images and drawings.** Alt text from the image-alt sidecar, as the
  `alt` key LaTeX's tagging reads (`\\includegraphics[alt={...}]`,
  `\\begin{picture}[alt={...}]`, `\\begin{tikzpicture}[alt={...}]`), or
  `artifact` for `[decorative]`. Without tagging, a LaTeX or a package
  that doesn't know a key stops on it, so a block in the master's
  preamble (KEYS_SKIPPED) skips each one that isn't known: pdfLaTeX
  builds the book as before (checked with TeX Live 2023, 2025, and 2026),
  and with `\\DocumentMetadata{tagging=on}` each becomes the figure's /Alt.
  A drawing is named as the conversion named it (latexsource.drawing_name);
  an image by its file. fig2dev's pair of picture environments is one
  drawing: the alt text goes on the first, and the second, its labels, is
  marked `artifact` so it isn't a figure of its own. A `pspicture` has no
  key for it and is counted.
- **Images behind the author's macros.** A macro the book defines whose
  body holds one `\\includegraphics`, its file made from an argument
  (`\\newcommand{\\fig}[2]{\\includegraphics[width=#2]{#1}}`), is followed
  to each call: the key is set just before the call and set back just
  after it, `\\setkeys{Gin}{alt={...}}\\fig{sq}{1cm}\\setkeys{Gin}{alt={}}`,
  so the macro is left as the author wrote it; a macro whose own alt key
  takes an argument gets the text in that argument, and one that passes
  an argument to \\includegraphics as keys gets alt among the call's. A
  decision the copy can't write (a call in a moving argument, a macro
  with alt text of its own), or for an image reached some other way, is
  counted against what the conversion's pages showed, so the run can
  name it.
- **Files a build makes.** A file beside a same-named xfig source (`.fig`)
  is fig2dev's, and running the book's build again would write over what's
  written into it; such files are counted, so the run can say so.
- **A page in another language.** In every copy, a page in another
  language than the copy's (languages.csv, or its file) is marked to be
  tagged in its own where the copy is built with LaTeX's tagging: hooks
  LaTeX runs around reading a file, in the master's preamble, set LaTeX's
  own key for a language (`text/lang`) as the page's `\\include`-d file
  begins and set it back as it ends, and then every other page a file
  begins, and each chapter the master sets itself, is set to the copy's,
  or to the one the book's babel commands have selected there (below),
  so none is in another's from the section around it; a document
  that `\\include`-s nothing is in its page's language, its
  `\\DocumentMetadata`'s, or from `\\begin{document}` where it has none.
  No file of the author's changes but the master's preamble, and built
  without tagging, nothing is tagged. A page of the master's own text,
  before its first `\\include` or a part or chapter it sets between them,
  has no file of its own for the hooks, and is counted.
- **A passage babel puts in another language.** In every copy of a book
  that loads babel and marks a passage in another language than the
  copy's with babel's own commands (`\\foreignlanguage`, `otherlanguage`,
  `\\selectlanguage`, and the like), hooks babel runs as it selects a
  language, in the master's preamble, tag the passage in it where the
  copy is built with LaTeX's tagging: `text/lang` for a paragraph or more,
  and a Span of its own for `\\foreignlanguage`'s words, or for a passage
  begun inside a paragraph, to its group's end or the paragraph's; after
  it, the language around it, not the one babel goes back to. Nothing of
  the author's changes but the master's preamble, and built without
  tagging, nothing is tagged.

The copy holds every .tex file the master reaches, at the same relative
paths and with the same file modes, ready to be laid over the author's
tree.
"""

import os
import re
import shutil

import languages
import latexbuild
import latexsource
import names

GENERATED_FROM = (".fig", ".xfig")
INCLUDEGRAPHICS = re.compile(r"\\includegraphics\s*(\[[^]]*\])?\s*\{([^}]*)\}")
BEGIN_DRAWING = re.compile(r"\\begin\s*\{(picture|tikzpicture|pspicture)\}")


def escape(text):
    """Alt text as LaTeX reads it inside a key's braces."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\textbackslash{}")
        elif ch in "{}%#&$_":
            out.append("\\" + ch)
        elif ch == "~":
            out.append("\\textasciitilde{}")
        elif ch == "^":
            out.append("\\textasciicircum{}")
        else:
            out.append(ch)
    return "".join(out)


def _key(alt):
    return "artifact" if alt is None else "alt={%s}" % escape(alt)


def with_key(options, key):
    """An optional argument ("[...]" or None) with key set, any alt or
    artifact the author gave replaced."""
    if not options:
        return "[%s]" % key
    inner = options[1:-1]
    parts = [p for p in _split(inner) if p.strip()
             and not re.match(r"\s*(alt\s*=|artifact\s*$)", p)]
    return "[%s]" % ",".join([key] + parts)


def _split(inner):
    """Comma-separated keys, commas inside braces kept."""
    parts, depth, current = [], 0, []
    for ch in inner:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def generated(base, name):
    stem = os.path.splitext(os.path.join(base, name))[0]
    return any(os.path.exists(stem + ext) for ext in GENERATED_FROM)


def _image_key(base, name, path, dirs):
    """The sidecar's key for an \\includegraphics: the file the conversion
    used, without its extension; a PDF or EPS is its SVG under rendered/."""
    found = latexsource.resolve_graphic(base, path.strip(), dirs)
    if not found:
        return None
    stem, ext = os.path.splitext(found)
    stem = stem.replace(os.sep, "/")
    if ext.lower() in (".pdf", ".eps", ".ps"):
        return "%s/%s" % (latexsource.RENDERED, stem)
    return stem


# --------------------------------------------------------------------------
# images behind an author's macro: found as latexsource finds them
# --------------------------------------------------------------------------

# Arguments written to a file and read back (a caption to the list of
# figures, a heading to the contents), where \setkeys would be expanded
# and break.
# Arguments LaTeX writes to a file and reads back, or keeps to typeset
# elsewhere (a heading's in the contents and running heads, a caption's in
# the list of figures, an index entry, a title's \thanks), where \setkeys
# would be expanded and stop the build: each command's arguments in order,
# o optional and m mandatory, and which of them move.
MOVING = {
    "caption": ("om", {0, 1}), "subcaption": ("om", {0, 1}),
    "captionof": ("mom", {1, 2}), "subcaptionbox": ("om", {0, 1}),
    "part": ("om", {0, 1}), "chapter": ("om", {0, 1}), "section": ("om", {0, 1}),
    "subsection": ("om", {0, 1}), "subsubsection": ("om", {0, 1}),
    "paragraph": ("om", {0, 1}), "subparagraph": ("om", {0, 1}),
    "markboth": ("mm", {0, 1}), "markright": ("m", {0}),
    "addcontentsline": ("mmm", {2}), "index": ("m", {0}), "thanks": ("m", {0}),
    "title": ("om", {0, 1}), "author": ("om", {0, 1}),
}
MOVING_COMMAND = re.compile(r"\\(" + "|".join(sorted(MOVING, key=len, reverse=True))
                            + r")(?![A-Za-z@])\*?")


def _moving_spans(text, skip):
    """(start, end) of each moving argument in text, in code (MOVING)."""
    spans = []
    for m in MOVING_COMMAND.finditer(text):
        if latexsource.in_spans(m.start(), skip):
            continue
        signature, moving = MOVING[m.group(1)]
        pos = m.end()
        for index, kind in enumerate(signature):
            at = latexsource.argument_space(text, pos)
            if kind == "o":
                if not text.startswith("[", at):
                    continue
                close = latexsource.closing_bracket(text, at)
                if close < 0:
                    break
                if index in moving:
                    spans.append((at + 1, close))
                pos = close + 1
            else:
                if not text.startswith("{", at):
                    break
                close = latexsource.matching_brace(text, at)
                if close < 0:
                    break
                if index in moving:
                    spans.append((at + 1, close - 1))
                pos = close
    return spans


# A paragraph break in an argument: a blank line, or \par.
PARAGRAPH_BREAK = re.compile(r"[ \t]*\n[ \t]*\n\s*|\s*\\par(?![A-Za-z@])\s*")


def remediate_file(base, name, text, alts, dirs, is_master=False, macros=None,
                   definitions=(), accounted=None, unplaced=None, values=None):
    """The file's text with alt text written in. Returns (text, counts).
    macros: image_macros' macros, followed to each call here outside
    definitions, the spans of the file's own definitions; values: {call's
    position: {macro: value}}, the book's macros without arguments as
    they're defined at each call (latexsource.macro_walk). accounted and
    unplaced, sets if given, get the key of each image or drawing with a
    decision: accounted when it's written, or counted as a pspicture;
    unplaced when it's found and can't be written."""
    accounted = set() if accounted is None else accounted
    unplaced = set() if unplaced is None else unplaced
    counts = {"described": 0, "decorative": 0, "pspicture": 0, "generated": 0,
              "macro_calls": 0}
    edits = []                         # (start, end, replacement, closes)
    offset = 0
    if is_master:
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, text)
        offset = begin[0].end() if begin else len(text)
    found = [(s + offset, e + offset, a)
             for s, e, a in latexsource.drawings(text[offset:])]
    inside = []
    for index, (start, end, _) in enumerate(found, start=1):
        inside.append((start, end))
        whole = len(found) == 1 and not re.sub(
            r"%[^\n]*", "", text[:start] + text[end:]).strip()
        key = os.path.splitext(latexsource.drawing_name(name, index, whole))[0]
        if key not in alts:
            continue
        alt = alts[key]
        first = True
        for m in BEGIN_DRAWING.finditer(text, start, end):
            # Only the drawings at this span's own level: a nested one is
            # part of the figure.
            if any(s < m.start() < e for s, e in
                   [(b.end(), latexsource.environment_end(text, b.group(1), b.start()))
                    for b in BEGIN_DRAWING.finditer(text, start, m.start())]):
                continue
            env = m.group(1)
            if env == "pspicture":
                counts["pspicture"] += 1
                accounted.add(key)
                first = False
                continue
            options = re.match(r"\s*\[[^]]*\]", text[m.end():])
            had = options.group(0).strip() if options else None
            stop = m.end() + (options.end() if options else 0)
            key_here = _key(alt) if first else "artifact"
            edits.append((m.end(), stop, with_key(had, key_here), False))
            if first:
                counts["decorative" if alt is None else "described"] += 1
                accounted.add(key)
            first = False
        if generated(base, name):
            counts["generated"] += 1
    spans = latexsource.skip_spans(text)
    for m in INCLUDEGRAPHICS.finditer(text):
        if latexsource.in_spans(m.start(), spans) or \
                any(s <= m.start() < e for s, e in inside):
            continue
        key = _image_key(base, name, m.group(2), dirs)
        if key is None or key not in alts:
            continue
        alt = alts[key]
        options = with_key(m.group(1), _key(alt))
        edits.append((m.start(), m.end(),
                      "\\includegraphics%s{%s}" % (options, m.group(2)), False))
        counts["decorative" if alt is None else "described"] += 1
        accounted.add(key)
        if generated(base, name):
            counts["generated"] += 1
    moving = None
    flat = {}
    for start, end, macro_name, args in latexsource.macro_calls(
            text, macros or {}, sorted(spans + list(definitions))):
        if any(s <= start < e for s, e in inside):
            continue
        macro = macros[macro_name]
        if macro["alt"] is not None and macro["alt"] <= len(args):
            # An alt-text argument of paragraphs, as OpenIntro's authors
            # write some, which \includegraphics can't take ("Paragraph
            # ended before \Gin@ii was complete"): its paragraphs run on,
            # unless a decision replaces it below.
            given_alt, at, stop = args[macro["alt"] - 1]
            if at is not None and PARAGRAPH_BREAK.search(given_alt):
                # A line end, not a space: a comment before the break ends
                # where it did.
                flat[(at, stop)] = PARAGRAPH_BREAK.sub("\n", text[at:stop])
        # The file as the call makes it: its arguments, and a macro without
        # arguments as it's defined there (\chapterfolder, set at each
        # chapter's start).
        path = latexsource.with_arguments(
            latexsource.with_values(macro["file"], (values or {}).get(start, {})),
            [(a[0].strip(),) for a in args])
        if "\\" in path or "#" in path:
            continue
        key = _image_key(base, name, path, dirs)
        if key is None or key not in alts:
            continue
        alt = alts[key]
        if moving is None:
            moving = _moving_spans(text, spans)
        if macro["keyed"] or any(s <= start < e for s, e in moving) or (
                macro["alt"] is not None and (alt is None or macro.get("alt_shared"))):
            # The body's own key wins over one set before the call; a
            # moving argument would expand \setkeys; an alt argument
            # can't say artifact, and one the body also uses elsewhere (a
            # caption) would change that too.
            unplaced.add(key)
            continue
        options_arg = macro.get("options")
        given = args[options_arg - 1] if options_arg else None
        if macro["alt"] is not None:
            _, at, stop = args[macro["alt"] - 1]
            # Braced once more for alt=#3, which takes the argument bare,
            # so a comma in it doesn't end the key; an optional argument
            # loses its outer braces, so it's braced again to keep them.
            written = escape(alt) if macro.get("alt_braced") else "{%s}" % escape(alt)
            delimiters = macro.get("delimiters")
            if delimiters and delimiters[macro["alt"]]:
                # A \def's delimited argument, whose braces TeX takes off
                # where they're around it whole (\figalt chat.png;{...};),
                # braced once more, so a comma or its delimiter in the
                # description doesn't end it.
                written = "{%s}" % written
            if at is None:              # an optional argument not given
                at = stop = start + 1 + len(macro_name)
                edits.append((at, stop, "[{%s}]" % written, False))
            elif text[at - 1] == "[":   # braced, so a ] in it doesn't end it
                edits.append((at, stop, "{%s}" % written, False))
            else:
                edits.append((at, stop, written, False))
        elif given and given[1] is not None:
            # The call's own keys, which an alt among them would make win:
            # the description goes in with them (\fig[width=2cm,alt={...}]{sq}).
            _, at, stop = given
            edits.append((at, stop, with_key("[" + given[0] + "]", _key(alt))[1:-1], False))
        elif given and macro["default"] is not None and options_arg == 1 and (
                not macro["default"].strip()
                or latexsource.OWN_KEY.search("[" + macro["default"] + "]")):
            # The call's keys not given, and nothing in their place, or a
            # default with alt text of its own, which would win over a key
            # set before: given, the description among them.
            at = start + 1 + len(macro_name)
            default = macro["default"].strip()
            edits.append((at, at, with_key("[%s]" % default if default else None,
                                           _key(alt)), False))
        else:
            # Set before the call and set back after it, with no group
            # around it: a group would undo the call's paragraph settings
            # (\centering) before its paragraph ends, and the label its
            # \caption sets before a \label after it. alt={} is the state a
            # graphic starts in: no description, LaTeX's tagging warning.
            edits.append((end, end, "\\setkeys{Gin}{alt={}}", True))
            edits.append((start, start, "\\setkeys{Gin}{%s}" % _key(alt), False))
        counts["decorative" if alt is None else "described"] += 1
        counts["macro_calls"] += 1
        accounted.add(key)
        if generated(base, name):
            counts["generated"] += 1
    for (at, stop), joined in flat.items():
        if not any(e[0] < stop and at < e[1] for e in edits):
            edits.append((at, stop, joined, False))
            counts["alt_paragraphs"] = counts.get("alt_paragraphs", 0) + 1
    # From the end back, so each place is still where it was found; where
    # one call ends and the next begins, the next one's opening goes in
    # first and the first one's closing in front of it.
    for start, stop, new, _ in sorted(edits, key=lambda e: (e[0], e[1], not e[3]),
                                      reverse=True):
        text = text[:start] + new + text[stop:]
    return text, counts


DEFINITIONS_NOTE = (
    "%% The definitions in %s, which a person wrote to say what\n"
    "%% the book's macros mean, so they replace the book's own here.\n")
DEFINES = re.compile(r"\\(?:(?:(?:re)?newcommand|providecommand)\*?|def)\b")
# The keys the copy writes stop a build where nothing defines them, which
# without tagging is: a picture's before LaTeX 2026-06-01, whose \picture
# took no options; a tikzpicture's before pgf 3.1.12 (2026-08-01), which
# defines both as keys that do nothing, waiting for tagging, where only
# latex-lab's tikz module, loaded by tagging, had defined them; and artifact
# before graphicx 1.2e (2024-12-31), TeX Live 2023's stopping at it. The LaTeX
# suite builds the block against those older definitions, so it's checked
# whatever the TeX that runs it. This block, before the
# master's \begin{document}, gives each a key that does nothing where it's
# missing, at the end of the preamble, when every package is loaded, and
# leaves the kernel's \picture alone unless it's the one that took no
# options (latex-lab's, for tagging, takes them). Checked with TeX Live
# 2023, 2025, and 2026, each building with pdfLaTeX, a picture without
# keys drawn as before, and with 2025 and 2026 tagged with LuaLaTeX, every
# figure keeping its alt text; GIAM's copy builds to its 434 pages on all
# three. The block puts @'s category code back as it found it.
KEYS_SKIPPED = r"""% Written for LaTeX's tagging, which reads the alt and artifact keys this
% copy gives images and drawings: a key this LaTeX or a package doesn't
% know is skipped, so the book builds without tagging as it did.
\edef\TIQatcode{\the\catcode`\@}\catcode`\@=11
\long\def\TIQkernelpicture#1{\pictur@#1}
\AtBeginDocument{%
  \ifx\picture\TIQkernelpicture
    \renewcommand\picture[1][]{\TIQkernelpicture}%
  \fi
  \ifdefined\define@key
    \@ifundefined{KV@Gin@alt}{\define@key{Gin}{alt}{}}{}%
    \@ifundefined{KV@Gin@artifact}{\define@key{Gin}{artifact}[]{}}{}%
  \fi
  \ifdefined\pgfkeysifdefined
    \pgfkeysifdefined{/tikz/alt/.@cmd}{}{\pgfkeys{/tikz/alt/.code={}}}%
    \pgfkeysifdefined{/tikz/artifact/.@cmd}{}{\pgfkeys{/tikz/artifact/.code={}}}%
  \fi}
\catcode`\@=\TIQatcode\relax
"""

# A page in another language than the copy's (languages.csv, or its file),
# tagged in its own by LaTeX's key for a language (text/lang, which every
# structure element opened while it's set takes as its /Lang): set as LaTeX
# begins to read the page's \include-d file and set back as the file ends,
# by hooks LaTeX runs around reading every file (file/before, file/after),
# which look the file up as \include gave it (\CurrentFilePath/
# \CurrentFile), so nothing of the author's but the master's preamble
# changes. Once one page needs it, every page an \include begins gets its
# language, the copy's for one in the copy's: an element with no /Lang
# takes the one around it, so with only the French pages set (2026-10-28's
# first patch, as its review found), an English file of sections after a
# French chapter was in that chapter's section, French, and so was every
# chapter after a French file that opens a part, in the part. Set back, the
# language is none, so what the master sets after a file, in the section
# the file opened, is in that section's language, as the pages take it for
# the file's page (in a class without chapters, a section the master sets
# after a section's file is one of its own, in the book's language, where
# the pages take it as the file's: measured with article); but a chapter
# the master sets itself is a page of its own (latexsource.cut_pages), so
# LaTeX's hook before \chapter (cmd/chapter/before) sets it to the copy's
# where no page's file is being read: in a part a French file opens, the
# master's own English chapter had been French (the second review). A
# part the master sets is one of the book's, in the book's language, as
# set back. The pages' files are as the reading took them (page_files),
# not by name: an \include in a conditional's branch the reading didn't
# take, or a name with a dot in it, had given a page's language to
# another file (the second review). LaTeX's hooks for an
# \include-d file by name (include/ch02/before) don't run for a file in a
# folder (\include{parts/ch03}), and its hooks for a file by its name alone
# (file/ch03.tex/before) run for every file of that name, so another
# chapter's solutions/ch03.tex would have taken ch03's language too. Not a
# group around the file, which would end what the file defines for the
# files after it: a chapter that defines a macro a later one uses stopped
# LaTeX in a group ("Undefined control sequence"). Measured on TeX Live
# 2026 (LaTeX 2026-06-01, tagpdf 2026-10-08): the chapter's section, its
# heading, the heading's label ("Chapter 2", the class's, in the language
# babel gives it), and its text take the language; a contents entry, set
# elsewhere, keeps the book's. The key is there wherever the master has a
# \DocumentMetadata, which tags only where its tagging is on (the second
# review measured a version alone, tagging=draft, and testphase); without
# one, nothing is set, and the copy builds as before. The block begins
# and ends with these lines, so a copy made from a copy has it replaced.
LANGUAGES_BEGIN = "% Written for LaTeX's tagging: a page in another language than the book's\n"
LANGUAGES_END = "% End of the pages' languages.\n"
LANGUAGES_SETUP = r"""% (languages.csv) is tagged in its own, set as LaTeX starts to read the
% page's file and set back when the file ends, and every other page a file
% begins, and each chapter the master sets itself, in the book's, or the
% one the book's babel commands have selected there, where the copy tags
% those; not in a group, which would end what the file defines for the
% files after it. Without tagging, nothing is tagged.
\ExplSyntaxOn
\prop_gclear_new:N \g__tiq_language_prop
\tl_clear_new:N \l__tiq_language_tl
\tl_clear_new:N \l__tiq_language_file_tl
\tl_gclear_new:N \g__tiq_language_book_tl
\bool_if_exist:NF \g__tiq_language_file_bool { \bool_new:N \g__tiq_language_file_bool }
\bool_gset_false:N \g__tiq_language_file_bool
\cs_set_protected:Npn \TIQpagelanguage #1
  {
    \keys_if_exist:nnT { __tag / setup } { text / lang }
      { \tagpdfsetup { text / lang = {#1} } }
  }
\cs_set_protected:Npn \TIQfilelanguage #1#2
  { \prop_gput:Nnn \g__tiq_language_prop {#1} {#2} }
\cs_set_protected:Npn \TIQbooklanguage #1
  { \tl_gset:Nn \g__tiq_language_book_tl {#1} }
\cs_set_protected:Npn \__tiq_language_file:
  { \tl_set:Nx \l__tiq_language_file_tl { \CurrentFilePath / \CurrentFile } }
\cs_set_protected:Npn \__tiq_language_book:
  {
    \tl_set_eq:NN \l__tiq_language_tl \g__tiq_language_book_tl
    \cs_if_exist:NT \__tiq_babel_here:N { \__tiq_babel_here:N \l__tiq_language_tl }
  }
\AddToHook { file / before } [ TIQ / language ]
  {
    \__tiq_language_file:
    \prop_get:NVNT \g__tiq_language_prop \l__tiq_language_file_tl \l__tiq_language_tl
      {
        \bool_gset_true:N \g__tiq_language_file_bool
        \tl_if_eq:NNT \l__tiq_language_tl \g__tiq_language_book_tl
          { \__tiq_language_book: }
        \exp_args:NV \TIQpagelanguage \l__tiq_language_tl
      }
  }
\AddToHook { file / after } [ TIQ / language ]
  {
    \__tiq_language_file:
    \prop_if_in:NVT \g__tiq_language_prop \l__tiq_language_file_tl
      {
        \par
        \tl_clear:N \l__tiq_language_tl
        \cs_if_exist:NT \__tiq_babel_here:N { \__tiq_babel_here:N \l__tiq_language_tl }
        \exp_args:NV \TIQpagelanguage \l__tiq_language_tl
        \bool_gset_false:N \g__tiq_language_file_bool
      }
  }
\cs_set_protected:Npn \__tiq_language_own:
  {
    \bool_if:NF \g__tiq_language_file_bool
      {
        \__tiq_language_book:
        \exp_args:NV \TIQpagelanguage \l__tiq_language_tl
      }
  }
\AddToHook { cmd / chapter / before } [ TIQ / language ] { \__tiq_language_own: }
\ExplSyntaxOff
"""
FILE_LANGUAGE = "\\TIQfilelanguage{%s}{%s}\n"
BOOK_LANGUAGE = "\\TIQbooklanguage{%s}\n"
DOCUMENT_LANGUAGE = "\\AddToHook{begindocument/end}[TIQ/language]{\\TIQpagelanguage{%s}}\n"
LANGUAGES_BLOCK = re.compile(re.escape(LANGUAGES_BEGIN) + r".*?" + re.escape(LANGUAGES_END),
                             re.S)
# What an \include's name can't hold for the copy to name the file as
# LaTeX's hooks see it: a macro, which LaTeX expands, or a brace, a
# comment, or a parameter, which TeX reads otherwise.
NOT_A_NAME = re.compile(r"[\\{}%#]")
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")


def included_file_key(argument):
    """The file an \\include names, as LaTeX's hooks around reading it see
    it (\\CurrentFilePath/\\CurrentFile): its folder as written, a slash,
    and its name with .tex, which \\include takes off and puts back, and
    without the quotes LaTeX drops ("parts/ch03.tex", "/ch02.tex" for one
    beside the master, "/two words.tex" for "two words"); None for one
    that holds a macro, a brace, a comment, or a parameter."""
    name = argument.strip().replace('"', "")
    if name.endswith(".tex"):
        name = name[:-len(".tex")]
    if not name or NOT_A_NAME.search(name):
        return None
    folder, _, file = name.rpartition("/")
    return folder + "/" + file + ".tex" if file.strip() else None


def language_marks(page_languages, reference):
    """{page: language} of page_languages ({page: language}) for each page
    whose language is a tag and another than reference's."""
    return {page: lang for page, lang in page_languages.items()
            if LANGUAGE_TAG.fullmatch(lang or "") and not languages.same_tag(lang, reference)}


def metadata_braces(text):
    """(where its brace opens, where it closes, just past it) of a master's
    \\DocumentMetadata, the first in its code, or None where it has none."""
    for m in latexsource.code_matches(DOCUMENT_METADATA, text):
        open_at = m.end()
        while open_at < len(text) and text[open_at].isspace():
            open_at += 1
        if text[open_at:open_at + 1] != "{":
            continue
        close = latexsource.matching_brace(text, open_at)
        if close >= 0:
            return open_at, close
    return None


def metadata_items(inner):
    """[(key, value, (where the value begins, where it ends))] of a
    \\DocumentMetadata's keys, inner its text between the braces, a comment
    in it read as TeX reads one, to its line's end: written over, a key on
    a line ending in a comment had taken the brace after it for the
    comment's (the third review)."""
    masked = re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), inner)
    items, depth, start = [], 0, 0
    for at, ch in enumerate(masked + ","):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "," and depth == 0:
            key, equals, value = masked[start:at].partition("=")
            if key.strip():
                begins = start + len(key) + len(equals)
                items.append((key.strip(), value.strip(),
                              (begins + len(value) - len(value.lstrip()),
                               begins + len(value.rstrip()))))
            start = at + 1
    return items


def metadata_keys(text):
    """[(key, value)] of a master's \\DocumentMetadata (metadata_braces),
    or None where it has none."""
    braces = metadata_braces(text)
    if braces is None:
        return None
    return [(key, value.strip("{}").strip())
            for key, value, _ in metadata_items(text[braces[0] + 1:braces[1] - 1])]


# What testphase turns tagging on with, measured on TeX Live 2026
# (LuaLaTeX, a structure tree written): phase-I, phase-II, phase-III, and
# latest, where math or table alone writes none.
TESTPHASE_TAGGING = re.compile(r"\b(?:phase-(?:I|II|III)|latest)\b")


def tags_itself(text):
    """Whether a master builds with LaTeX's tagging: its \\DocumentMetadata
    says tagging=on, as a copy made to build with it does (tag), or names
    a testphase that turns it on, as books written for tagging in 2024
    did. One that says tagging=off or draft, has no such key, or only sets
    the PDF's version, builds untagged."""
    keys = dict(metadata_keys(text) or [])
    if "tagging" in keys:
        return keys["tagging"] == "on"
    return bool(TESTPHASE_TAGGING.search(keys.get("testphase", "")))


def with_document_language(text, lang):
    """text with its master's \\DocumentMetadata (metadata_braces) in lang:
    its lang's value replaced where it has one, else lang= put first, the
    rest as the author wrote it, comments and lines too; or None where it
    has none to change."""
    braces = metadata_braces(text)
    if braces is None:
        return None
    inside = braces[0] + 1
    items = metadata_items(text[inside:braces[1] - 1])
    for key, _, (begins, ends) in items:
        if key == "lang":
            return text[:inside + begins] + lang + text[inside + ends:]
    return text[:inside] + "lang=%s" % lang + (", " if items else "") + text[inside:]


def page_languages_block(master, outline, page_languages, reference, page_files=None,
                         only=None):
    """(block, marked, unmarked) for a copy: the lines for its preamble
    that tag, where it's built with LaTeX's tagging, each page of
    page_languages ({page: language}, the master's) in another language
    than reference (the copy's own) in its own, the pages as they're cut
    (latexsource.cut_pages). A page an \\include begins is tagged by the
    hooks around reading its file, and once one is, every other file is
    too, and each chapter the master sets itself, in reference, so none is
    in another's from the section or part around it; a document
    that \\include-s nothing, one page, is tagged from \\begin{document}.
    outline: the master's [(\\include's argument, role)] as LaTeX reads them
    (latexsource.book_outline), its macros' \\include-s written out;
    page_files: {index in outline: the page the reading made of that
    \\include}, the reading's own (convert.py's LATEX_PAGE_FILES), else
    each file's page named as cut_pages names it. A file the reading made
    no page of, as one in a conditional's branch it didn't take, is in
    reference, and of two files one page is made of, the page is the
    later, as the pages have it, and the earlier is in reference. marked:
    [(page, language)]; unmarked: [(page, language, why)], why "own" for a
    page of the master's own text (before its first \\include, or a part
    or chapter it sets between them) and "named" for a file an \\include
    names with a macro, a brace, a comment, or a parameter, which the
    block can't name as LaTeX's hooks see it. only: the names the master's
    \\includeonly lets LaTeX read (latexsource.included_only), or None: a
    file it leaves out is in neither list, since what LaTeX builds hasn't
    it, and gets no line."""
    marks = language_marks(page_languages, reference)
    if not marks:
        return "", [], []
    if page_files is None or any(index >= len(outline) for index in page_files):
        page_files = {index: names.safe_stem(latexsource.include_stem(argument.strip()))
                      for index, (argument, _) in enumerate(outline)}
    last = {page: index for index, page in sorted(page_files.items())}
    lines, marked, unmarked, reached = [BOOK_LANGUAGE % reference], [], [], set()
    for index, (argument, _) in enumerate(outline):
        key = included_file_key(argument)
        page = page_files.get(index)
        if only is not None and latexsource.include_name(argument) not in only:
            if page is not None:
                reached.add(page)
            continue
        if page is None or last[page] != index:
            # No page, or not the page: the later file of its name is.
            if key is not None:
                lines.append(FILE_LANGUAGE % (key, reference))
            continue
        reached.add(page)
        if key is None:
            # Defensive: a run stops on such a name, which reaches no file
            # (latexsource.reached), before any copy is made.
            if page in marks:
                unmarked.append((page, marks[page], "named"))
            continue
        lang = marks.get(page, reference)
        lines.append(FILE_LANGUAGE % (key, lang))
        if page in marks:
            marked.append((page, lang))
    stem = names.safe_stem(os.path.splitext(os.path.basename(master))[0])
    for page, lang in sorted(marks.items()):
        if page in reached:
            continue
        if page == stem and not outline:
            # The document is the page, its chapters too.
            lines[0] = BOOK_LANGUAGE % lang
            lines.append(DOCUMENT_LANGUAGE % lang)
            marked.append((page, lang))
        else:
            unmarked.append((page, lang, "own"))
    if not marked:
        return "", marked, unmarked
    return LANGUAGES_BEGIN + LANGUAGES_SETUP + "".join(lines) + LANGUAGES_END, marked, unmarked


# A passage the book's own babel commands put in another language, tagged
# in it where the copy is built with LaTeX's tagging. babel sets the
# passage's hyphenation and words and tags nothing (LATEX-NOTES); the
# pages have \foreignlanguage's and otherlanguage's passages as Pandoc
# reads them, a span or a div with its language, which the PDF from the
# pages tags (latexbuild's \oerlang and oerlanguage), and the copy, which
# is the author's markup, had nothing. babel runs a hook of LaTeX's each
# time it selects a language, after its own settings for it
# (babel/*/afterextras): for \selectlanguage, otherlanguage,
# otherlanguage*, \foreignlanguage*, and \foreignlanguage, and for
# babeltags' commands, which are these; and another before
# \foreignlanguage's words (babel/*/foreign), as it sets them with
# \BabelText (read in babel.sty 26.13). So the block's hooks, in the
# master's preamble, are all the copy needs. A passage of a paragraph or
# more has LaTeX's key for a language (text/lang) set as babel selects it,
# in the group babel's command makes, so what it begins takes it, and the
# group's end sets it back. A passage otherlanguage or otherlanguage*
# begins inside a paragraph, as babeltags' {\fr un mot} does, is a Span
# with its /Lang from there to the group's end, a second the group begins
# ending there with it, and \foreignlanguage's words are a Span of their
# own, opened in the paragraph, as \oerlang opens one, so the paragraph
# keeps its language: with text/lang set as babel selects their language,
# a paragraph that begins with them took it whole, where babel doesn't
# begin the paragraph before it selects the language (measured with
# babel's own command for that emptied; babel 26.13 begins it where LaTeX
# has \GetDocumentProperties). Where LaTeX's tagging ends a structure
# around such a Span before that, the Span ends first: the block sets
# tagpdf's \tag_struct_end: again, once tagging is known, to end any Span
# of its own that is the structure begun last, since tagpdf's ends the
# structure begun last, whatever it was begun for (read in tagpdf 1.0h),
# and so had ended the Span in the paragraph's place, the next paragraph
# inside the one left open, or in a table's cell's or a list's label's,
# which veraPDF's PDF/UA-2 profile failed (the sixth review); and
# \tag_struct_end:n, which names what it ends, as LaTeX's tagging does for
# a paragraph a tabular begins in, since tagpdf's debug code checks that
# name first and warned of the Span there (the seventh review). What
# begins inside the passage is in its language by the key, which the words
# set too once their Span is open: its next paragraphs, the paragraph
# after a display, a list, a tabular, a box, or an [H] float inside it,
# and a note's paragraph; the last paragraph that begins inside it is in
# it whole, with any words after the passage's end. But where a Span of
# the block's ends first at another structure's end than a paragraph's
# text (\UseStructureName{para/textblock}), the key is emptied for the
# rest of the group, since LaTeX's tagging begins a list item's body in
# the group of a declaration in its label (\item[\fr d\'ej\`a vu]), whose
# language babel leaves at the label's end, and the body had been French.
# \BabelText is set again as a \long macro, since babel's \BabelWrapText
# makes one that isn't, and stopped LaTeX on words that hold a paragraph
# break ("Paragraph ended before \BabelText was complete", the fifth
# review). A \selectlanguage inside a paragraph sets what begins after the
# paragraph: a Span from it to the paragraph's end was empty where it ends
# a paragraph, as an author's \selectlanguage{english} at a file's end
# does. Not a \selectlanguage of a language babel is in already, its
# region aside, as the block last saw babel's in the group it's in, or
# babel's main one where it has seen none: babel restores a language so
# after a group, where the group's end has set text/lang back already, and
# the page needn't be in babel's language. A page languages.csv puts in
# Spanish, babel's English throughout, had been English after an English
# quotation in it, to its end, and from a \selectlanguage{english} at its
# head, which an author may give every chapter; and by name, under the
# \DocumentMetadata{lang=en-US} a project in American English gives a
# tagged copy, babel's main language was american, and the author's
# english another (the fifth review). Only from begindocument/end: babel
# selects languages as it reads the .aux file at \begin{document}, where
# the name of babel's command, which \IfBabelSelectorTF tests, isn't set
# yet and stopped LaTeX ("Undefined control sequence"), and it selects the
# book's own there; and not once the last page is out (enddocument/
# afterlastpage), where it reads the .aux file again. Where the copy tags
# its pages' languages too (page_languages_block), a page with no language
# of its own, which those hooks give the book's, is in babel's where babel
# is in another language than its main one there (\__tiq_babel_here:N), as
# a \selectlanguage{french} the master sets before a chapter's \include,
# or before a \chapter of its own, puts it: the page is in the language
# LaTeX sets it in, as where no page is in another language and those
# hooks aren't written; a page languages.csv puts in a language begins in
# it, whatever babel's; and the master's text after a file is in babel's
# where babel is left in another, where it had been in the file's page's,
# if a page elsewhere had a row (the fifth review). A language's tag is
# the table's the reading uses for a preamble's language
# (latexsource.BABEL), so babel's language for the book is tagged as the
# reading names the book's language from it, else babel's own
# (\localeinfo*{tag.bcp47}), latin's la: babel's german is de-1901 by its
# own and de by the table, and babel's alias francais has no tag of
# babel's. A language with neither is in the language around it, and
# LaTeX's log names it (Package TIQ Warning). Measured on TeX Live 2026
# (LuaLaTeX, babel 26.13): a paragraph set by otherlanguage,
# otherlanguage*, \foreignlanguage*, or \selectlanguage, a chapter whose
# file selects French, babeltags' declaration and otherlanguage* inside a
# paragraph, two in one group, a note inside one, an otherlanguage begun
# on a paragraph's last line holding a paragraph break, a declaration
# around a display, around a list, in a table's cell, two there, and in a
# list's label, and \foreignlanguage's words in a paragraph, heading,
# contents entry, caption, note, table cell, list label, link, box, and a
# formula's \text, and around a display, each in its language, the running
# head over a French section, which babel sets in \foreignlanguage too, an
# artifact with no Span; every word where it was without the block, to
# under a hundredth of a point, and the structure the same but for the
# Spans, which veraPDF's PDF/UA-2 profile passes. Without tagging, nothing
# is tagged: pdfLaTeX builds the copy as before, TeX Live 2023's (babel
# 24.1) too. The block begins and ends with these lines, so a copy made
# from a copy has it replaced.
BABEL_BEGIN = "% Written for LaTeX's tagging: a passage the book's babel commands put in\n"
BABEL_END = "% End of babel's languages.\n"
BABEL_SETUP = r"""% another language is tagged in it, set as babel selects the language and
% set back as babel's group ends, \foreignlanguage's words a Span of their
% own, as is a passage begun inside a paragraph, to its group's end or
% where LaTeX's tagging ends what's around it, and a page in no language
% of its own in babel's; the language's tag the table's below, else
% babel's own. Without tagging, nothing is tagged.
\ExplSyntaxOn
\prop_gclear_new:N \g__tiq_babel_prop
\seq_gclear_new:N \g__tiq_babel_warned_seq
\tl_clear_new:N \l__tiq_babel_tl
\str_clear_new:N \l__tiq_babel_str
\str_clear_new:N \l__tiq_babel_part_str
\str_clear_new:N \l__tiq_babel_here_str
\str_gclear_new:N \g__tiq_babel_main_str
\seq_gclear_new:N \g__tiq_babel_open_seq
\seq_gclear_new:N \g__tiq_babel_struct_seq
\tl_clear_new:N \l__tiq_babel_id_tl
\tl_gclear_new:N \g__tiq_babel_text_tl
\int_if_exist:NF \g__tiq_babel_id_int { \int_new:N \g__tiq_babel_id_int }
\bool_if_exist:NF \l__tiq_babel_closed_bool { \bool_new:N \l__tiq_babel_closed_bool }
\bool_if_exist:NF \g__tiq_babel_bool { \bool_new:N \g__tiq_babel_bool }
\bool_gset_false:N \g__tiq_babel_bool
\cs_set_protected:Npn \TIQbabeltags #1
  { \prop_gput_from_keyval:Nn \g__tiq_babel_prop {#1} }
\cs_set_protected:Npn \__tiq_babel_tag:
  {
    \prop_get:NVNF \g__tiq_babel_prop \languagename \l__tiq_babel_tl
      { \tl_set:Ne \l__tiq_babel_tl { \localeinfo* { tag.bcp47 } } }
  }
\cs_set_protected:Npn \__tiq_babel_part:NN #1#2
  {
    \tl_if_empty:NTF #1
      { \str_set:Ne #2 { ? \languagename } }
      {
        \str_set:NV #2 #1
        \regex_replace_once:nnN { \A([A-Za-z]+)(-[A-Za-z]{4})?(-.*)?\Z } { \1\2 } #2
      }
  }
\msg_set:nnn { TIQ } { babel-untagged }
  { babel's~language~#1~has~no~language~tag:~its~text~is~in~the~language~around~it. }
\cs_set_protected:Npn \__tiq_babel_warn:n #1
  {
    \str_set:Ne \l__tiq_babel_str { #1 : \languagename }
    \seq_if_in:NVF \g__tiq_babel_warned_seq \l__tiq_babel_str
      {
        \seq_gput_right:NV \g__tiq_babel_warned_seq \l__tiq_babel_str
        \str_set:Ne \l__tiq_babel_str { \languagename }
        \exp_args:NnnV \msg_warning:nnn { TIQ } { babel- #1 } \l__tiq_babel_str
      }
  }
\cs_set_protected:Npn \__tiq_babel_set:n #1
  { \tagpdfsetup { text / lang = {#1} } }
\cs_set_protected:Npn \__tiq_babel_select:
  {
    \tl_if_empty:NTF \l__tiq_babel_tl
      { \__tiq_babel_warn:n { untagged } }
      {
        \mode_if_horizontal:T { \IfBabelSelectorTF { select } { } { \__tiq_babel_inline: } }
        \exp_args:NV \__tiq_babel_set:n \l__tiq_babel_tl
      }
  }
\cs_set_protected:Npn \__tiq_babel_open:
  {
    \int_gincr:N \g__tiq_babel_id_int
    \seq_gput_right:Nx \g__tiq_babel_open_seq { \int_use:N \g__tiq_babel_id_int }
    \tag_mc_end_push:
    \exp_args:Ne \tag_struct_begin:n { tag = Span , lang = \l__tiq_babel_tl }
    \seq_gput_right:Nx \g__tiq_babel_struct_seq { \tag_get:n { struct_num } }
    \tag_mc_begin:n { }
  }
\cs_set_protected:Npn \__tiq_babel_inline:
  {
    \__tiq_babel_open:
    \cs_gset_protected:cpx { __tiq_babel_close_ \int_use:N \g__tiq_babel_id_int : }
      { \__tiq_babel_close:n { \int_use:N \g__tiq_babel_id_int } }
    \exp_args:Nc \group_insert_after:N
      { __tiq_babel_close_ \int_use:N \g__tiq_babel_id_int : }
  }
\cs_set_protected:Npn \__tiq_babel_close:n #1
  {
    \seq_if_in:NnT \g__tiq_babel_open_seq {#1}
      { \__tiq_babel_close_to:n {#1} }
  }
\cs_set_protected:Npn \__tiq_babel_pop:
  {
    \seq_gpop_right:NN \g__tiq_babel_struct_seq \l__tiq_babel_id_tl
    \seq_gpop_right:NN \g__tiq_babel_open_seq \l__tiq_babel_id_tl
  }
\cs_set_protected:Npn \__tiq_babel_close_one:
  {
    \__tiq_babel_pop:
    \tag_mc_if_in:T { \tag_mc_end: }
    \__tiq_babel_struct_end:
    \tag_mc_begin_pop:n { }
  }
\cs_set_protected:Npn \__tiq_babel_before_end:
  {
    \bool_set_false:N \l__tiq_babel_closed_bool
    \__tiq_babel_end_inner:
    \bool_if:NT \l__tiq_babel_closed_bool
      {
        \str_if_eq:eeF { \tag_get:n { struct_tag } } { \g__tiq_babel_text_tl }
          { \__tiq_babel_set:n { } }
      }
  }
\cs_set_protected:Npn \__tiq_babel_end_inner:
  {
    \seq_get_right:NNT \g__tiq_babel_struct_seq \l__tiq_babel_id_tl
      {
        \str_if_eq:eeT { \l__tiq_babel_id_tl } { \tag_get:n { struct_num } }
          {
            \bool_set_true:N \l__tiq_babel_closed_bool
            \__tiq_babel_pop:
            \tag_mc_if_in:T { \tag_mc_end: }
            \__tiq_babel_struct_end:
            \tag_mc_begin_pop:n { }
            \tag_mc_if_in:T { \tag_mc_end: }
            \__tiq_babel_end_inner:
          }
      }
  }
\cs_set_protected:Npn \__tiq_babel_close_to:n #1
  {
    \__tiq_babel_close_one:
    \str_if_eq:VnF \l__tiq_babel_id_tl {#1} { \__tiq_babel_close_to:n {#1} }
  }
\cs_set_protected:Npn \__tiq_babel_language:
  {
    \bool_if:NT \g__tiq_babel_bool
      {
        \__tiq_babel_tag:
        \__tiq_babel_part:NN \l__tiq_babel_tl \l__tiq_babel_part_str
        \str_if_empty:NT \l__tiq_babel_here_str
          { \str_set_eq:NN \l__tiq_babel_here_str \g__tiq_babel_main_str }
        \str_if_eq:NNTF \l__tiq_babel_part_str \l__tiq_babel_here_str
          { \IfBabelSelectorTF { select } { } { \__tiq_babel_passage: } }
          {
            \str_set_eq:NN \l__tiq_babel_here_str \l__tiq_babel_part_str
            \__tiq_babel_passage:
          }
      }
  }
\cs_set_protected:Npn \__tiq_babel_passage:
  { \IfBabelSelectorTF { foreign } { } { \__tiq_babel_select: } }
\cs_set_protected:Npn \__tiq_babel_span:n #1
  {
    \mode_leave_vertical:
    \__tiq_babel_open:
    \exp_args:NV \__tiq_babel_set:n \l__tiq_babel_tl
    \exp_args:Ne \__tiq_babel_words:nn { \int_use:N \g__tiq_babel_id_int } {#1}
  }
\cs_set:Npn \__tiq_babel_words:nn #1#2 { #2 \__tiq_babel_close:n {#1} }
\cs_set_protected:Npn \__tiq_babel_words:
  {
    \bool_if:NT \g__tiq_babel_bool
      {
        \__tiq_babel_tag:
        \tl_if_empty:NTF \l__tiq_babel_tl
          { \__tiq_babel_warn:n { untagged } }
          {
            \cs_set_eq:NN \__tiq_babel_text:n \BabelText
            \cs_set:Npn \BabelText ##1 { \__tiq_babel_text:n { \__tiq_babel_span:n {##1} } }
          }
      }
  }
\cs_set_protected:Npn \__tiq_babel_here:N #1
  {
    \bool_if:NT \g__tiq_babel_bool
      {
        \__tiq_babel_tag:
        \__tiq_babel_part:NN \l__tiq_babel_tl \l__tiq_babel_part_str
        \str_if_eq:NNF \l__tiq_babel_part_str \g__tiq_babel_main_str
          { \tl_if_empty:NF \l__tiq_babel_tl { \tl_set_eq:NN #1 \l__tiq_babel_tl } }
      }
  }
% babel before 26.11 runs these two hooks without declaring them, and
% LaTeX runs nothing in a hook that isn't declared; declared, they run,
% and one babel declares is as it was.
\cs_if_exist:NT \ActivateGenericHook
  {
    \ActivateGenericHook { babel / * / afterextras }
    \ActivateGenericHook { babel / * / foreign }
  }
\AddToHook { babel / * / afterextras } [ TIQ / babel ] { \__tiq_babel_language: }
\AddToHook { babel / * / foreign } [ TIQ / babel ] { \__tiq_babel_words: }
\AddToHook { begindocument / end } [ TIQ / babel ]
  {
    \bool_lazy_and:nnT
      { \cs_if_exist_p:N \IfBabelSelectorTF }
      { \keys_if_exist_p:nn { __tag / setup } { text / lang } }
      {
        \__tiq_babel_tag:
        \__tiq_babel_part:NN \l__tiq_babel_tl \l__tiq_babel_part_str
        \str_gset_eq:NN \g__tiq_babel_main_str \l__tiq_babel_part_str
        \bool_gset_true:N \g__tiq_babel_bool
        \tl_gset:Ne \g__tiq_babel_text_tl
          {
            \cs_if_exist:NTF \UseStructureName
              { \UseStructureName { para / textblock } } { text }
          }
        \cs_if_exist:NF \__tiq_babel_struct_end:
          {
            \cs_gset_eq:NN \__tiq_babel_struct_end: \tag_struct_end:
            \cs_gset_protected:Npn \tag_struct_end:
              { \__tiq_babel_before_end: \__tiq_babel_struct_end: }
            \cs_gset_eq:NN \__tiq_babel_struct_end:n \tag_struct_end:n
            \cs_gset_protected:Npn \tag_struct_end:n #1
              { \__tiq_babel_before_end: \__tiq_babel_struct_end:n {#1} }
          }
      }
  }
\AddToHook { enddocument / afterlastpage } [ TIQ / babel ]
  { \bool_gset_false:N \g__tiq_babel_bool }
\ExplSyntaxOff
"""


def babel_table(table=None):
    """The block's lines giving the tag for each of babel's names in table
    (latexsource.BABEL's), a few to a line."""
    items = ["%s=%s" % pair for pair in (table or latexsource.BABEL).items()]
    return "".join("\\TIQbabeltags{%s}\n" % ", ".join(items[at:at + 4])
                   for at in range(0, len(items), 4))


BABEL_BLOCK = re.compile(re.escape(BABEL_BEGIN) + r".*?" + re.escape(BABEL_END), re.S)
# babel's commands for a passage in another language, as the copy counts
# them: \foreignlanguage and \foreignlanguage*, \selectlanguage, and
# otherlanguage, otherlanguage*, and selectlanguage as environments, each
# with its language's name, after an option where it has one ([date]).
BABEL_COMMAND = re.compile(
    r"\\(?:foreignlanguage\*?|selectlanguage)(?![A-Za-z@])\s*(?:\[[^]]*\]\s*)?"
    r"\{\s*([^{}\\%\s#]+)\s*\}"
    r"|\\begin\s*\{(?:otherlanguage\*?|selectlanguage)\}\s*(?:\[[^]]*\]\s*)?"
    r"\{\s*([^{}\\%\s#]+)\s*\}")
# babeltags' names, each for a language (\babeltags{fr = french}), which
# give it a command for its \foreignlanguage (\textfr) and one for its
# otherlanguage* (\fr, \begin{fr}).
BABEL_TAGS_DECLARED = re.compile(r"\\babeltags\s*\{([^{}]*)\}")


def babel_tag(name):
    """The table's tag for one of babel's names for a language
    (latexsource.BABEL), as written or in lower case, or None."""
    return latexsource.BABEL.get(name) or latexsource.BABEL.get(name.lower())


def babel_passages(texts, files, counted=None):
    """{babel's name for a language: how many} of the book's own babel
    commands that set a passage's language (BABEL_COMMAND, and babeltags'
    for each name a file of files declares), in the code of counted
    (files where it's None), all in texts, as they're written, a macro's
    definition among them, though not a name a macro or its parameter
    gives (\\foreignlanguage{#1}); each name as written, or in lower case
    where only that is the table's (latexsource.BABEL), as babel takes a
    name."""
    tags = {}
    for name in files:
        for m in latexsource.code_matches(BABEL_TAGS_DECLARED, texts[name]):
            for item in m.group(1).split(","):
                short, _, language = (part.strip() for part in item.partition("="))
                if re.fullmatch(r"[A-Za-z]+", short) and language:
                    tags[short] = language
    babeltags = re.compile(
        r"\\(?:text)?(%s)(?![A-Za-z@])|\\begin\s*\{(%s)\}" % (("|".join(tags),) * 2)) \
        if tags else None
    found = {}
    for name in files if counted is None else counted:
        text = texts[name]
        spans = latexsource.skip_spans(text)
        named = [m.group(1) or m.group(2)
                 for m in latexsource.code_matches(BABEL_COMMAND, text, spans)]
        if babeltags:
            named += [tags[m.group(1) or m.group(2)]
                      for m in latexsource.code_matches(babeltags, text, spans)]
        for language in named:
            if language not in latexsource.BABEL and language.lower() in latexsource.BABEL:
                language = language.lower()
            found[language] = found.get(language, 0) + 1
    return found


def remediate(base, out_dir, master, files, alts, tagging=False, language=None,
              headers=None, definitions=None, definitions_name="", seen=None,
              mathml=True, standard=("ua-2",), written=(), picture_paths=True,
              page_languages=None, book_language="en", page_files=None):
    """Write a remediated copy of each file in files (relative to base) to
    out_dir at the same relative path. alts: {key: alt, or None for
    decorative} (htmlremediate.alt_rows); tagging: made to build with
    LaTeX's tagging (tag), the book's language its lang; page_languages:
    {page: language} for the master's pages, as decided for every target,
    each in another language than the copy's (its preamble's, else
    book_language) marked in its own (page_languages_block), in every
    copy, since its tagging may come later, and a document of one page in
    it whole, as its \\DocumentMetadata's where it has one: in
    languages_marked where the copy builds with LaTeX's tagging
    (tags_itself), else in languages_untagged, and in languages_unmarked
    one it can't; and in every copy of a book that loads babel, each
    passage its own babel commands set the language of marked to be
    tagged in it (BABEL_SETUP), where a command names another language
    than the copy's or a page is in another, the commands counted in
    babel_marked or babel_untagged as languages_marked's are
    (babel_passages); page_files: {index of the master's \\include: its
    page}, as the reading made them (page_languages_block); headers:
    {place: headers}, a person's table-header decisions, declared for
    tagging when the copy is tagged (declare), since without tagging
    \\tagpdfsetup isn't defined and the build stops; seen: the keys of
    the images and drawings on the conversion's pages, against which a
    decision the copy couldn't write is counted; mathml: whether a tagged
    copy loads unicode-math for its formulas' MathML; standard: the PDF
    standards a tagged copy's \\DocumentMetadata claims; picture_paths:
    whether a tagged copy draws picture mode with pict2e (tag); written: files
    another master's copy has written already, read here and not written
    again, as when a book's masters share chapters. Returns a dict of
    counts, and in unplaced_keys the keys of those decisions."""
    master_text = latexsource.read_text(os.path.join(base, master))
    dirs = latexsource.graphics_paths(latexsource.split_master(master_text)[0])
    folder = os.path.dirname(master)
    if folder:
        # A master below the book's directory finds its images from its
        # own folder, as the read does (latexsource.prepare).
        dirs = [folder] + [os.path.join(folder, d) for d in dirs] + dirs
    totals = {"files": 0, "changed": 0}
    originals, texts = {}, {}
    for name in files:
        originals[name] = latexsource.read_text(os.path.join(base, name))
    # The macros the conversion follows, so a call is found as it was read
    # (latexsource.expand_image_macros): the book's definitions in the order
    # LaTeX reads them, a chapter where the book's own macro \include-s it,
    # and a person's definitions after the preamble, which the copy holds.
    order = [(name, originals[name]) for name in files]
    after = None
    if definitions:
        after = definitions_name or "definitions"
        order.append((after, definitions))
    includes = latexsource.include_macros(order)
    macros, definition_spans = latexsource.image_macros(order, includes, after)
    calls = {name: [c[0] for c in latexsource.macro_calls(
        originals[name], macros, sorted(latexsource.skip_spans(originals[name])
                                        + definition_spans.get(name, [])))]
        for name in files}
    values = latexsource.macro_walk(order, lambda *_: None, includes, after, calls)[2] \
        if macros else {}
    accounted, unplaced = set(), set()
    keyed = False
    for name in files:
        texts[name], counts = remediate_file(
            base, name, originals[name], alts, dirs, name == master, macros,
            definition_spans.get(name, ()), accounted, unplaced,
            {pos: found for (text, pos), found in values.items() if text == name})
        # A key in a file another master's copy wrote is in this one's
        # build too.
        keyed = keyed or bool(counts["described"] or counts["decorative"])
        if name in written:             # counted where it was written
            continue
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
    # A decision the pages show but the copy didn't write: the image is
    # reached some way the copy doesn't follow, or the copy found it and
    # couldn't write it there.
    missing = {key for key in (seen or ()) if key in alts} - accounted
    totals["unplaced_keys"] = sorted(unplaced | missing)
    totals["unplaced"] = len(totals["unplaced_keys"])
    tagged = tagging or bool(latexsource.code_matches(DOCUMENT_METADATA, originals[master]))
    if headers and tagged:
        totals.update(declare(texts, files, headers))
    elif headers:
        totals["headers_untagged"] = len(headers)
    if definitions:
        # After the book's preamble, as the conversion reads them.
        text = texts[master]
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, text)
        if begin:
            at = begin[0].start()
            block = DEFINITIONS_NOTE % definitions_name + definitions.rstrip("\n") + "\n"
            texts[master] = text[:at] + block + text[at:]
            spans = latexsource.skip_spans(definitions)
            totals["definitions"] = sum(1 for m in DEFINES.finditer(definitions)
                                        if not latexsource.in_spans(m.start(), spans))
    if keyed and master not in written:
        text = texts[master]
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, text)
        if begin:
            at = begin[0].start()
            texts[master] = text[:at] + KEYS_SKIPPED + text[at:]
            totals["keys_skipped"] = 1
    if tagging:
        if not language:
            language = latexsource.preamble_language(
                latexsource.split_master(originals[master])[0])
        for key, n in tag(texts, master, language, mathml, standard, base,
                          picture_paths).items():
            totals["tag_" + key] = n
    # The pages' languages, as decided now: a copy made from a copy has its
    # block written again, or taken out where no page needs one. In every
    # copy, tagged or not: built without LaTeX's tagging, the block sets
    # nothing, and built with it, as a person may build any copy, it's
    # there (2026-11-05: the language is rewritten everywhere that it's
    # applicable). Against the copy's own language, its \DocumentMetadata's
    # or its preamble's, which a page's elements take where the block
    # gives them none.
    texts[master] = LANGUAGES_BLOCK.sub("", texts[master])
    begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, texts[master])
    reference = languages.tag(latexsource.preamble_language(
        latexsource.split_master(texts[master])[0])) or languages.tag(book_language) or "en"
    marks = language_marks(page_languages or {}, reference)
    if begin and marks and master not in written:
        expanded = {name: originals[name] for name in files}
        latexsource.expand_include_macros(expanded, files, {})
        outline, _ = latexsource.book_outline(latexsource.split_master(expanded[master])[1])
        stem = names.safe_stem(os.path.splitext(os.path.basename(master))[0])
        one = None if outline or stem not in marks else \
            with_document_language(texts[master], marks[stem])
        if one is not None:
            # A document of one page, in its page's language whole: its
            # \DocumentMetadata's, which its title and bookmarks take too,
            # where the hook gave them the book's (the second review).
            texts[master] = one
            block, marked, unmarked = "", [(stem, marks[stem])], []
        else:
            block, marked, unmarked = page_languages_block(
                master, outline, page_languages, reference, page_files,
                latexsource.included_only(latexsource.split_master(texts[master])[0]))
        if block:
            at = begin[0].start()
            texts[master] = texts[master][:at] + block + texts[master][at:]
        tagged_copy = tags_itself(texts[master])
        totals["languages_marked" if tagged_copy else "languages_untagged"] = marked
        totals["languages_unmarked"] = unmarked
        totals["languages_tagged"] = int(tagged_copy)
    # The pages the master's \includeonly leaves out of what LaTeX builds
    # from the copy, which the pages have: Pandoc's reader reads every
    # \include whatever \includeonly says.
    only = latexsource.included_only(latexsource.split_master(texts[master])[0]) \
        if master not in written else None
    if only is not None:
        expanded = {name: originals[name] for name in files}
        latexsource.expand_include_macros(expanded, files, {})
        outline, _ = latexsource.book_outline(latexsource.split_master(expanded[master])[1])
        left = []
        for index, (argument, _) in enumerate(outline):
            if latexsource.include_name(argument) in only:
                continue
            page = page_files.get(index) if page_files is not None else \
                names.safe_stem(latexsource.include_stem(argument.strip()))
            if page is not None and page not in left:
                left.append(page)
        if left:
            totals["includeonly_left"] = left
    # The passages the book's own babel commands set the language of, as
    # the book has them now, in every copy as the pages' languages are
    # (2026-11-05: an author who runs TextbookImprover against their
    # source is expecting the run to remediate it): a copy made
    # from a copy has its block written again, or taken out where nothing
    # needs it, as in a book whose commands all name the copy's language
    # (a \selectlanguage{english} at each chapter's head) and whose pages
    # are all in it. In a page marked in another, a passage in the copy's
    # language is in another than the page's. A file another master's copy
    # wrote is counted there.
    texts[master] = BABEL_BLOCK.sub("", texts[master])
    if master not in written and "babel" in preamble_packages(texts, master, base)[0]:
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, texts[master])
        found = babel_passages(texts, files)
        if begin and found and (marks or any(
                not languages.same_language(babel_tag(name) or "", reference)
                for name in found)):
            at = begin[0].start()
            texts[master] = (texts[master][:at] + BABEL_BEGIN + BABEL_SETUP + babel_table()
                             + BABEL_END + texts[master][at:])
            totals["babel_marked" if tags_itself(texts[master]) else "babel_untagged"] = \
                babel_passages(texts, files, [f for f in files if f not in written])
    for name in files:
        if name in written:
            continue
        out = os.path.join(out_dir, name)
        os.makedirs(os.path.dirname(out) or out_dir, exist_ok=True)
        # As read (latexsource.read_text): a byte that isn't UTF-8, in a file
        # in Latin-1, say, is written back as it was.
        with open(out, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(texts[name])
        # The author's file mode, so the copy laid over the tree changes
        # only what it says: 65 of the 165 files GIAM's copy writes are
        # executable, and each written as 644 was a change in git's diff.
        shutil.copymode(os.path.join(base, name), out)
        totals["files"] += 1
        totals["changed"] += int(texts[name] != originals[name])
    return totals


# --------------------------------------------------------------------------
# tagging: the copy made to build with LaTeX's own tagging (tagging: on)
# --------------------------------------------------------------------------

DOCUMENTCLASS = re.compile(r"\\documentclass\b")
DOCUMENT_METADATA = re.compile(r"\\DocumentMetadata\b")
OPTIONED = re.compile(r"(\\(?:documentclass|usepackage|RequirePackage)\s*)\[([^]]*)\]")
PDFTEX_SETTING = re.compile(
    r"\\pdf(?:compresslevel|objcompresslevel|minorversion|output)\s*=?\s*\d+[ \t]*\n?")
# pdfTeX's own commands, which LuaTeX doesn't have, and \pdfoutput, by whose
# absence an old test tells LaTeX with dvips from pdfLaTeX, and so takes
# LuaLaTeX for the first (GIAM's workbook and solutions manual choose their
# class options with \ifx\pdfoutput\undefined). luatex85 gives LuaTeX each
# of them, as the LaTeX team's package for legacy documents, so the pdfTeX
# branch is taken and what's in it works: \ifnum\pdfoutput>0, \pdfinfo,
# \pdfcatalog (checked tagged, veraPDF passing). Rewriting the test instead
# sent LuaLaTeX into a branch whose pdfTeX commands it lacks.
PDFTEX_COMMANDS = re.compile(
    r"\\pdf(?:output|info|catalog|names|trailer|pagewidth|pageheight|pageattr|pagesattr"
    r"|pageresources|pagebox|literal|obj|lastobj|refobj|xform|lastxform|refxform|ximage"
    r"|lastximage|refximage|lastximagepages|xformname|xformattr|xformresources|annot"
    r"|lastannot|startlink|endlink|lastlink|dest|outline|thread|startthread|endthread"
    r"|save|restore|setmatrix|colorstack|colorstackinit|adjustspacing|protrudechars"
    r"|noligatures|fontexpand|copyfont|fontattr|fontname|fontobjnum|fontsize|includechars"
    r"|draftmode|horigin|vorigin|pxdimen|insertht|savepos|lastxpos|lastypos|pageref"
    r"|normaldeviate|uniformdeviate|setrandomseed|randomseed|primitive|creationdate"
    r"|decimaldigits|gamma|imageresolution|pkresolution|pkmode|mapfile|mapline"
    r"|gentounicode|glyphtounicode|uniqueresname|retval|texversion|texrevision"
    r"|destmargin|linkmargin|threadmargin|compresslevel|objcompresslevel|minorversion)"
    r"(?![A-Za-z@])")
LUATEX85 = ("% Written for LaTeX's tagging, built with LuaLaTeX: pdfTeX's commands, which\n"
            "% LuaTeX lacks, and \\pdfoutput, which a test for pdfTeX looks for, as the\n"
            "% luatex85 package gives them to LuaTeX. pdfLaTeX builds as before.\n"
            "\\ifdefined\\directlua\\RequirePackage{luatex85}\\fi\n")
# babel's main language as the book's own build has it, where the copy gives
# the book its lang: babel takes its main language from \DocumentMetadata's
# lang where the book names none with main= (read in babel.sty 26.13), so a
# book in ngerman, the 1996 spelling, given lang=de was set in german,
# hyphenated by the 1901 rules ("Zucker" unbroken, where the author's build
# breaks "Zu-cker"), and one in british, in a project in en-US, in american
# ("or-ga-ni-za-tion" for "or-gan-iz-a-tion"). main= keeps the book's, the
# PDF's /Lang lang's still (measured on TeX Live 2026, LuaLaTeX); passed
# before the class, it reaches babel wherever the book loads it, and keeps a
# language the class's options name. Not where the book names its main
# language itself, with main= or \babelprovide[main], which babel keeps: a
# second main= stopped LaTeX ("Bad option 'main=french'").
BABEL_MAIN = ("%% Written for LaTeX's tagging: babel's main language the book's own,\n"
              "%% which babel would otherwise take from \\DocumentMetadata's lang.\n"
              "\\PassOptionsToPackage{main=%s}{babel}\n")
PROVIDE_MAIN = re.compile(r"\\babelprovide\s*\[[^]]*\bmain\b")
PASSED_OPTIONS = re.compile(r"\\PassOptionsToPackage\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
CLASS_OPTIONS = re.compile(r"\\documentclass(?:\s|%[^\n]*)*\[([^]]*)\]")
# A face with a STAT table that isn't a variable font embedded from its own
# file by LuaLaTeX, not as luaotfload embeds a variable face, which Acrobat
# said it couldn't extract (latexbuild.STATIC_FONTS): just after
# \DocumentMetadata, before the class, since luaotfload settles how a face
# is embedded when it first loads it, and a class, a package, or the book's
# own fontspec setting can load one. Every tagged copy has it, as a book's
# PDF from its pages does: whether a face has the table isn't known until
# LuaLaTeX loads it (TeX Live's josefin package sets Josefin Sans, which has
# one, by fontspec), and another face is embedded as before.
STATIC_FONTS = ("% Written for LuaLaTeX, which builds this copy: a face with a STAT table\n"
                "% that isn't a variable font embedded from its own file, not as luaotfload\n"
                "% embeds a variable font, which Acrobat said it couldn't extract. Any other\n"
                "% face is embedded as before, and pdfLaTeX builds as before.\n"
                + latexbuild.STATIC_FONTS)
NEWTHEOREM = re.compile(r"\\newtheorem\s*\{(\w+)\}")
STARRED_THEOREM = re.compile(r"\\newtheorem\*\s*\{(\w+)\*\}\s*\{[^}]*\}")
CENTERLINE = re.compile(r"\\centerline(?![A-Za-z@])")
# A display formula that opens a paragraph in a center, flushleft, or
# flushright environment: right after its \begin (GIAM's), or after a blank
# line, as in a paragraph column of a table there (FINC 308's boxes), where
# LaTeX 2026-06-01's tagging leaves a paragraph open; \leavevmode before it
# opens the paragraph first.
CENTERED = re.compile(r"\\begin\s*\{(center|flushleft|flushright)\}")
BLOCK_FORMULA = re.compile(
    r"(\\begin\s*\{(?:center|flushleft|flushright)\}\s*|\n[ \t]*\n\s*)"
    r"(?=\\\[|\\begin\s*\{(?:equation|align|alignat|flalign|gather|multline"
    r"|displaymath|eqnarray)\*?\})")
CENTERLINE_DEFINITION = (
    "% Written for LaTeX's tagging: \\centerline on a line of its own is a\n"
    "% centered paragraph, which tagging takes; in a paragraph it's as before.\n"
    "\\let\\TIQcenterline\\centerline\n"
    "\\renewcommand{\\centerline}[1]{\\ifvmode{\\centering #1\\par}"
    "\\else\\TIQcenterline{#1}\\fi}\n")
# Each formula's MathML, which luamml makes only from an OpenType math font:
# with TeX's own fonts it isn't made at all, and when it's forced, a symbol
# TeX builds from pieces comes out as the pieces (\implies as "=" and "⇒",
# \neq as "=" and a combining stroke, \cong as nothing), and the AMS fonts'
# letters as plain ones (ℕ as "N"), 536 of GIAM's 4,521 formulas against
# unicode-math's. unicode-math's Latin Modern is TeX's own design; the
# fallback gives a character the fonts lack a glyph (GIAM's \vdots in a
# typewriter label), which PDF/UA-2 requires (.notdef, 8.4.5.9).
PACKAGE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]*)\}")
PACKAGE_OPTIONS = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[([^]]*)\])?\s*\{([^}]*)\}")


def package_options(pieces, name):
    """The options the preamble's pieces (preamble_packages's) load the
    package name with, a list."""
    return [o.strip() for piece in pieces
            for m in latexsource.code_matches(PACKAGE_OPTIONS, piece)
            if name in latexsource.package_names(m.group(2))
            for o in (m.group(1) or "").split(",") if o.strip()]
PREAMBLE_INPUT = re.compile(r"\\input\s*\{\s*([^}]+?)\s*\}")
MATH_SETUP_KEY = re.compile(r"math/setup")
UNICODE_MATH = ("unicode-math", "lua-unicode-math")
# Packages that set the book's fonts, or math symbols unicode-math clashes
# with: such a book keeps its own, and its formulas get no MathML here.
OWN_FONTS = frozenset("""
    times mathptmx mathptm txfonts pxfonts newtxtext newtxmath newtxsf newpxtext
    newpxmath mathpazo palatino palatcm helvet courier bookman newcent charter utopia
    fourier fouriernc kpfonts libertine libertinus libertinust1math mathdesign eulervm
    euler ccfonts concmath cmbright arev lucidabr lucimatx mtpro2 MinionPro mathastext
    sansmath sfmath stix stix2 XCharter tgtermes tgpagella tgheros tgcursor tgbonum
    tgschola tgadventor tgchorus gentium ebgaramond garamondx baskervald Baskervaldx
    crimson cochineus erewhon heuristica iwona kurier anttor mlmodern fontspec wasysym
    esint stmaryrd mathabx MnSymbol fdsymbol boisik isomath""".split())
MATH_SETUP_LINE = "  \\ifdefined\\tagpdfsetup\\tagpdfsetup{math/setup={mathml-SE,mathml-AF}}\\fi\n"
# A float's tags: LaTeX's tagging gathers every figure's and table's at the
# end of the document unless told otherwise (latex-lab-testphase-float),
# where a screen reader reaches them after everything else; the 91 of
# GIAM's 195 figures in floats were there. float/here tags each where the text has it; where
# it's printed doesn't change.
FLOAT = re.compile(r"\\begin\s*\{(?:figure|table)\*?\}")
FLOAT_KEY = re.compile(r"\\tagpdfsetup\s*\{[^}]*float/")
# The key came in latex-lab-float 0.81m (2025-12-04), after LaTeX 2025-11-01.
# The run builds only with a LaTeX that has it (MINIMUM_LATEX); a copy its
# author builds with an older one skips it.
FLOATS_HERE = (
    "% Written for LaTeX's tagging: a figure's or table's tags where the text\n"
    "% has it, not gathered at the end of the document; it's printed where it was.\n"
    + latexbuild.FLOATS_HERE)
# enumitem's settings for a list, which LaTeX's tagging replaces with an
# emulation of its own (latex-lab-enumitem, loaded by latex-lab-testphase-
# block in place of enumitem.sty). The emulation stops on the settings it
# lacks ("Some keys specified on the itemize environment are unknown"), so
# each is taken here: nolistsep is nosep, resume continues the numbering,
# and the rest -- code to run around a list, a nested label, a
# description's style -- is left out. resume takes a series' name too
# (resume=name), as enumitem's does and the list template's own, a
# boolean, doesn't: LaTeX 2026-06-01 stopped on it ("accepts boolean
# values only"), and 2026-11-01 set the list's item with no label, its
# structure a Part and a P in an L, and a description after it numbered
# (measured 2026-11-10). The emulation of LaTeX 2026-06-01 (0.80f) also
# stopped on * and ! for a computed width ("Missing number", FINC 308's 101
# lists with leftmargin=*) and had no labelindent or ref, so there a width
# to compute or a label's indent is left to its defaults and ref is left
# out; 2026-11-01's (0.80i, 2026-10-24) computes each width itself, * as !,
# and has its own labelindent and ref, which these would hide. A
# template's own keys are set through \SetTemplateKeys, which 2026-11-01
# no longer keeps as l3keys of template/<type>/<name> ("The key
# 'template/block/std/left-margin' is unknown"). Checked key by key
# against both; with enumitem itself (no tagging), the block does nothing.
ENUMITEM_KEYS = r"""% Written for LaTeX's tagging, which lays out lists with an emulation of
% enumitem: the settings it lacks are taken, so the lists build. resume
% continues the numbering, a series' name or not, and code around a list
% (before, after) and a nested label (label*) are left out; with LaTeX
% 2026-06-01, a width to compute (leftmargin=*) or a label's indent is
% left to its defaults and ref is left out too. With enumitem itself,
% nothing changes.
\ExplSyntaxOn
\cs_if_exist:cT { ver@latex-lab-enumitem.sty }
  {
    \bool_lazy_and:nnF
      { \cs_if_exist_p:N \ltlabenumdate }
      { \str_compare_p:eNe { \ltlabenumdate } > { 2026-10-23 } }
      {
        \keys_define:nn { template / block / std }
          {
            leftmargin .code:n =
              { \str_case:nnF {#1} { {*} { } {!} { } }
                  { \SetTemplateKeys { block } { std } { left-margin = {#1} } } } ,
            labelindent .code:n = { } , ref .code:n = { }
          }
        \keys_define:nn { template / list / std }
          {
            labelwidth .code:n =
              { \str_case:nnF {#1} { {*} { } {!} { } }
                  { \SetTemplateKeys { list } { std } { label-width = {#1} } } }
          }
      }
    \keys_define:nn { template / block / std }
      {
        labelindent* .code:n = { } ,
        widest .code:n = { } , widest* .code:n = { } , left .code:n = { } ,
        label* .code:n = { } , series .code:n = { } ,
        before .code:n = { } , before* .code:n = { } ,
        after .code:n = { } , after* .code:n = { } ,
        first .code:n = { } , first* .code:n = { } , style .code:n = { } ,
        itemjoin .code:n = { } , itemjoin* .code:n = { } ,
        afterlabel .code:n = { } , mode .code:n = { } , fullwidth .code:n = { }
      }
    \keys_define:nn { template / blockenv / std }
      { nolistsep .meta:n = { nosep } }
    \keys_define:nn { template / list / std }
      {
        resume .code:n =
          { \tl_if_empty:NF \l__block_counter_tl
              { \exp_args:Nnne \SetTemplateKeys { list } { std }
                  { start = \int_eval:n { \value { \l__block_counter_tl } + 1 } } } } ,
        resume* .code:n = { \SetTemplateKeys { list } { std } { resume } }
      }
  }
\ExplSyntaxOff
"""
# A box (latexsource.box_tables), a table of one paragraph column holding
# prose, which the pages make a div: tagged as a division of paragraphs, not
# a table (table/tagging=div, latex-lab-testphase-table), the setting kept
# to its table by a group. Checked: veraPDF passes it, and the next table is
# a table again.
BOX_OPEN = "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=div}\\fi"
# A table in a box is a table: tagging set back for it, the setting and the
# two plugs table/tagging=on leaves as div set them (checked: a Table, with
# no presentation role, and veraPDF passes).
DATA_OPEN = ("{\\ifdefined\\tagpdfsetup\\tagpdfsetup{table/tagging=on}"
             "\\AssignTaggingSocketPlug{tbl/hmode/begin}{Table}"
             "\\AssignTaggingSocketPlug{tbl/vmode/begin}{Table}\\fi")
DECLARED_BEFORE = re.compile(r"\{\\ifdefined\\tagpdfsetup\\tagpdfsetup"
                             r"\{table/header-(?:[^{}]|\{[^{}]*\})*\}\\fi$")
BOXES_NOTE = (
    "% Written for LaTeX's tagging: a table of one column of prose, a box around\n"
    "% a passage, is tagged as a division of paragraphs, not a table, by\n"
    "% {\\tagpdfsetup{table/tagging=div} before it and } after.\n")
# The PDF's title (dc:title), which PDF/UA-2 requires: LaTeX's tagging takes
# it from \title, which nothing prints without \maketitle. A document that
# names none, by \title or hyperref's pdftitle, gets the title its large type
# gives it (latexsource.visual_title), or its file's name.
TITLE_SET = re.compile(r"\\title\s*[\[{]|pdftitle\s*=")
MAKETITLE = re.compile(r"\\maketitle(?![A-Za-z@])")
TITLE_NOTE = (
    "% Written for LaTeX's tagging: the document's title, for the PDF's title,\n"
    "% which PDF/UA-2 requires; nothing prints it without \\maketitle.\n")
# A class whose own \title and \author replace LaTeX's tagging's, loaded
# before the class at \DocumentMetadata, which give the PDF its title
# (dc:title) and author (dc:creator): LaTeX's tagging takes them otherwise
# only at \maketitle (cmd/maketitle/before), so a book in one with no
# \maketitle, the copy's \title (TITLE_NOTE) among them, had no title.
# OWN_TITLE takes them as \maketitle would, at the preamble's end, where
# LaTeX's tagging has none; and hyperref's pdftitle, where the book gives
# it, is the PDF's title anyway. Measured with amsart, amsbook, amsproc,
# and memoir (given LaTeX's own commands, MEMOIR_COMMANDS), LaTeX
# 2026-06-01 and 2026-11-01.
OWN_TITLE_CLASSES = ("amsart", "amsbook", "amsproc", "memoir")
PDFTITLE = re.compile(r"pdftitle\s*=")
OWN_TITLE = (
    "% Written for LaTeX's tagging: the PDF's title and author from \\title and\n"
    "% \\author, as LaTeX's tagging takes them at \\maketitle, where it has none:\n"
    "% this class's own \\title and \\author don't give them to it.\n"
    "\\makeatletter\\ExplSyntaxOn\n"
    "\\tl_if_exist:NT \\g__tag_title_title_tl\n"
    "  {\n"
    "    \\tl_if_empty:NT \\g__tag_title_title_tl\n"
    "      { \\cs_if_exist:NT \\@title { \\tl_gset_eq:NN \\g__tag_title_title_tl \\@title } }\n"
    "  }\n"
    "\\tl_if_exist:NT \\g__tag_title_author_tl\n"
    "  {\n"
    "    \\tl_if_empty:NT \\g__tag_title_author_tl\n"
    "      { \\cs_if_exist:NT \\@author { \\tl_gset_eq:NN \\g__tag_title_author_tl \\@author } }\n"
    "  }\n"
    "\\ExplSyntaxOff\\makeatother\n")
# memoir 3.8.4b changes \title and \author (with xpatch), which under
# tagging are LaTeX's tagging's own, and its changes don't fit them: a
# \title or an \author, the book's or the copy's, stopped the build ("Extra
# \endgroup"). And hyperref loads memoir's changes for it (memhfixc), whose
# footnote mark steps a counter hyperref doesn't make where
# \DocumentMetadata is given (Hfootnote; hyperref.sty's
# \IfDocumentMetadataT), so with hyperref, the book's or the copy's
# (HYPERREF_NOTE), the first note stopped it ("No counter 'Hfootnote'
# defined"); hyperfootnotes=false would build, but LaTeX's footnote code
# then links no note's mark. MEMOIR_COMMANDS,
# before the class, gives memoir LaTeX's own \title and \author to change,
# as latex.ltx declares them, and keeps the footnote mark memhfixc would
# replace, LaTeX's tagging's, which links a note's mark to its note;
# memhfixc's links for \pagenote stay. And LaTeX's footnote code, loaded
# with \DocumentMetadata, sets its own mark in memoir's place at
# class/memoir/after, which has none of memoir's comma between marks in
# succession (\multfootsep), so two notes' marks ran together, "12" for
# "1,2"; MEMOIR_COMMANDS gives memoir's two macros for it (\m@mmf@check,
# \m@mmf@prepare) to that mark's hooks, fnmark and fnmark/end, where they
# go in memoir's own, where memoir defines them. Measured with LaTeX
# 2026-06-01 and 2026-11-01.
MEMOIR_COMMANDS = (
    "% Written for LaTeX's tagging: \\title and \\author as LaTeX defines them,\n"
    "% for memoir to change, where LaTeX's tagging's own, which memoir's changes\n"
    "% don't fit, stopped LaTeX (\"Extra \\endgroup\"); the footnote mark\n"
    "% hyperref's changes for memoir (memhfixc) would replace kept, where theirs\n"
    "% steps a counter hyperref doesn't make with \\DocumentMetadata (\"No\n"
    "% counter 'Hfootnote' defined\"); and memoir's comma between marks in\n"
    "% succession given to the footnote mark LaTeX sets in memoir's place,\n"
    "% which ran them together (\"12\" for \"1,2\").\n"
    "\\makeatletter\n"
    "\\AddToHook{class/memoir/before}{%\n"
    "  \\DeclareRobustCommand\\title[1]{\\gdef\\@title{#1}}%\n"
    "  \\DeclareRobustCommand*\\author[1]{\\gdef\\@author{#1}}}\n"
    "\\AddToHook{package/memhfixc/before}{\\global\\let\\oer@footnotemark\\@footnotemark}\n"
    "\\AddToHook{package/memhfixc/after}{\\global\\let\\@footnotemark\\oer@footnotemark}\n"
    "\\AddToHook{class/memoir/after}{%\n"
    "  \\ifdefined\\m@mmf@check\n"
    "    \\AddToHook{fnmark}{\\m@mmf@check}\\AddToHook{fnmark/end}{\\m@mmf@prepare}%\n"
    "  \\fi}\n"
    "\\makeatother\n")
# The PDF's bookmarks, which hyperref makes from the headings (PDF/UA-1
# 7.17 recommends them), its links as the book had them (hidelinks): for a
# book that loads neither hyperref nor a package that must come after it.
HYPERREF_AFTER = frozenset("cleveref glossaries glossaries-extra hypcap bookmark".split())
HYPERREF_NOTE = (
    "% Written for LaTeX's tagging: hyperref, for the PDF's bookmarks, with its\n"
    "% links drawn as the text around them (hidelinks).\n"
    "\\usepackage[hidelinks]{hyperref}\n")
LIST_OPTIONS = re.compile(r"\\begin\s*\{(?:itemize|enumerate|description)\*?\}\s*\[|"
                          r"\\setlist\*?\s*(?:\[[^]]*\])?\s*\{")
# The settings the emulation lacks, as the run names them: laid out by its
# defaults, numbering continued, or left out; and those LaTeX 2026-06-01's
# lacked, which 2026-11-01's lays out itself (ENUMITEM_KEYS).
ENUMITEM_DEFAULTS = ("labelindent*", "widest", "widest*", "left", "style", "mode",
                     "fullwidth", "nolistsep")
ENUMITEM_LEFT_OUT = ("label*", "series", "before", "before*", "after", "after*",
                     "first", "first*", "itemjoin", "itemjoin*", "afterlabel")
ENUMITEM_EARLIER = ("leftmargin=*", "leftmargin=!", "labelwidth=*", "labelwidth=!",
                    "labelindent", "ref")


def enumitem_settings(texts):
    """{setting: times} for the enumitem settings in texts' lists and
    \\setlist commands that LaTeX's tagging's emulation lacks: a key, or
    key=* and key=! for a width to compute, and resume, resume*."""
    found = {}
    for text in texts.values():
        spans = latexsource.skip_spans(text)
        for m in LIST_OPTIONS.finditer(text):
            if latexsource.in_spans(m.start(), spans):
                continue
            close = "]" if m.group(0).endswith("[") else "}"
            depth, end = 0, None
            for i in range(m.end(), len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}" and depth:
                    depth -= 1
                elif ch == close and not depth:
                    end = i
                    break
            if end is None:
                continue
            for item in _split(text[m.end():end]):
                key, _, value = item.partition("=")
                key, value = key.strip(), value.strip()
                name = f"{key}={value}" if key in ("leftmargin", "labelwidth") \
                    and value in ("*", "!") else key
                if name in ENUMITEM_DEFAULTS or name in ENUMITEM_LEFT_OUT \
                        or name in ENUMITEM_EARLIER or name in ("resume", "resume*"):
                    found[name] = found.get(name, 0) + 1
    return found


# Packages LaTeX's tagging can't build a tagged PDF with, or whose output it
# can't tag (the tagging project's status list rates titlesec, framed, soul,
# ulem, tabto, and wrapfig currently incompatible, and mdframed and soulutf8
# never to be supported): the copy loads none of them, by LaTeX's own way of
# skipping a package (\disable@package@load), and defines their commands
# where the book would have loaded it, so what the book says is kept and
# how they made it look isn't. titlesec stopped the build ("No format for
# this command"), at OpenIntro Statistics' first heading. Each was built
# tagged with what it's written with in the book, the text checked, and
# veraPDF's PDF/UA-2 profile passed. A package the installed status list
# rates compatible, or partially, is loaded as the book has it.
#
# The definitions are written in expl3 under internal names, and the
# command each package's load runs makes them the package's own; a
# parameter inside the command that does is doubled (##1), and one inside
# a definition made in a loop there doubled again.
SHIM_COMMON = r"""\cs_new_protected:Npn \__oer_block_begin:n #1
  {
    \par \addvspace { \medskipamount }
    \tl_if_blank:nF {#1} { \noindent { \bfseries #1 } \par }
  }
\cs_new_protected:Npn \__oer_block_end:
  { \par \addvspace { \medskipamount } }
"""
SHIMS = {
    "titlesec": (r"""\NewDocumentCommand \__oer_titleformat:w { +m +o +m +m +m +m +o } { }
\cs_new_protected:Npn \__oer_titleclass:Nn #1#2
  {
    \cs_if_exist:NF #1
      {
        \str_case_e:nnF { \tl_if_novalue:nF {#2} { \cs_to_str:N #2 } }
          {
            { part } { \cs_if_exist:NTF \chapter { \cs_gset_eq:NN #1 \chapter } { \cs_gset_eq:NN #1 \section } }
            { chapter } { \cs_gset_eq:NN #1 \section }
            { section } { \cs_gset_eq:NN #1 \subsection }
            { subsection } { \cs_gset_eq:NN #1 \subsubsection }
            { paragraph } { \cs_gset_eq:NN #1 \subparagraph }
          }
          { \cs_gset_eq:NN #1 \paragraph }
      }
  }
\cs_new_protected:Npn \__oer_shim_titlesec:
  {
    \cs_gset_eq:NN \__oer_shim_titlesec: \prg_do_nothing:
    \DeclareDocumentCommand \titleformat { s }
      { \IfBooleanTF {##1} { \use_none:nn } { \__oer_titleformat:w } }
    \DeclareDocumentCommand \titlespacing { s +m +m +m +m +o } { }
    \DeclareDocumentCommand \titlelabel { +m } { }
    \DeclareDocumentCommand \titleclass { m o m o } { \__oer_titleclass:Nn ##1 {##4} }
    \DeclareDocumentCommand \assignpagestyle { m m } { }
    \DeclareDocumentCommand \titlerule { s o }
      {
        \IfBooleanTF {##1} { \use_none:n }
          { \leavevmode \leaders \hrule height \IfValueTF {##2} {##2} { 0.4pt } \hfill \kern 0pt \relax }
      }
    \providecommand \filcenter { \leftskip = 0pt plus 1fil \rightskip = 0pt plus 1fil \parfillskip = 0pt }
    \providecommand \filleft { \leftskip = 0pt plus 1fil \rightskip = 0pt \parfillskip = 0pt }
    \providecommand \filright { \leftskip = 0pt \rightskip = 0pt plus 1fil }
    \providecommand \fillast { }
    \providecommand \filinner { }
    \providecommand \filouter { }
    \providecommand \chaptertitlename { \chaptername }
    % titlesec's page styles (\newpagestyle, \sethead) are titleps's, which
    % LaTeX's tagging takes, loaded when the first is defined, as titlesec
    % does: loaded at once, it clashed with fancyhdr's \headrule
    % (OpenIntro Statistics, which uses fancyhdr's styles and no others).
    \cs_gset_protected:Npn \newpagestyle { \__oer_titleps:N \newpagestyle }
    \cs_gset_protected:Npn \renewpagestyle { \__oer_titleps:N \renewpagestyle }
    \cs_gset_protected:Npn \widenhead { \__oer_titleps:N \widenhead }
    % Loaded at once with titlesec's pagestyles option, as titlesec loads it.
    \bool_if:NT \g__oer_titlesec_pagestyles_bool { \__oer_titleps:N \scan_stop: }
  }
\bool_if_exist:NF \g__oer_titlesec_pagestyles_bool
  { \bool_new:N \g__oer_titlesec_pagestyles_bool }
\cs_new_protected:Npn \__oer_titleps:N #1
  {
    \cs_undefine:N \newpagestyle
    \cs_undefine:N \renewpagestyle
    \cs_undefine:N \widenhead
    \RequirePackage { titleps }
    #1
  }
""", "headings are set as the class sets them, without the fonts, rules, spacing, and "
         "labels titlesec gave them, and a heading level titlesec made is the class's "
         "next level down"),
    "mdframed": (r"""\tl_new:N \l__oer_mdf_title_tl
\tl_new:N \g__oer_mdf_setup_tl
\keys_define:nn { oer / mdframed }
  {
    frametitle .tl_set:N = \l__oer_mdf_title_tl ,
    style .code:n =
      { \tl_if_exist:cT { g__oer_mdf_style_#1_tl } { \keys_set:nv { oer / mdframed } { g__oer_mdf_style_#1_tl } } } ,
    unknown .code:n = { }
  }
\cs_new_protected:Npn \__oer_mdf_begin:n #1
  {
    \tl_clear:N \l__oer_mdf_title_tl
    \keys_set:nV { oer / mdframed } \g__oer_mdf_setup_tl
    \keys_set:nn { oer / mdframed } {#1}
    \exp_args:NV \__oer_block_begin:n \l__oer_mdf_title_tl
  }
\cs_new_protected:Npn \__oer_shim_mdframed:
  {
    \cs_gset_eq:NN \__oer_shim_mdframed: \prg_do_nothing:
    \DeclareDocumentEnvironment { mdframed } { O{} } { \__oer_mdf_begin:n {##1} } { \__oer_block_end: }
    \DeclareDocumentCommand \newmdenv { O{} m }
      { \NewDocumentEnvironment {##2} { O{} } { \__oer_mdf_begin:n { ##1 , ####1 } } { \__oer_block_end: } }
    \DeclareDocumentCommand \renewmdenv { O{} m }
      { \RenewDocumentEnvironment {##2} { O{} } { \__oer_mdf_begin:n { ##1 , ####1 } } { \__oer_block_end: } }
    \DeclareDocumentCommand \surroundwithmdframed { O{} m }
      {
        \AddToHook { env / ##2 / before } { \__oer_mdf_begin:n {##1} }
        \AddToHook { env / ##2 / after } { \__oer_block_end: }
      }
    \DeclareDocumentCommand \mdfsetup { m } { \tl_gput_right:Nn \g__oer_mdf_setup_tl { , ##1 } }
    \DeclareDocumentCommand \mdfdefinestyle { m m }
      { \tl_gclear_new:c { g__oer_mdf_style_##1_tl } \tl_gset:cn { g__oer_mdf_style_##1_tl } {##2} }
    \DeclareDocumentCommand \mdfapptodefinestyle { m m }
      {
        \tl_if_exist:cF { g__oer_mdf_style_##1_tl } { \tl_new:c { g__oer_mdf_style_##1_tl } }
        \tl_gput_right:cn { g__oer_mdf_style_##1_tl } { , ##2 }
      }
    \DeclareDocumentCommand \newmdtheoremenv { O{} m o m o }
      {
        \IfValueTF {##3} { \newtheorem {##2} [##3] {##4} }
          { \IfValueTF {##5} { \newtheorem {##2} {##4} [##5] } { \newtheorem {##2} {##4} } }
        \surroundwithmdframed [##1] {##2}
      }
    \cs_gset_eq:NN \mdtheorem \newmdtheoremenv
    \DeclareDocumentCommand \mdfsubtitle { O{} m } { \par \noindent { \bfseries ##2 } \par }
    \cs_gset_eq:NN \mdfsubsubtitle \mdfsubtitle
  }
""", "a framed passage is set as the text around it is, without its frame or background, "
         "its frame title a line in bold"),
    "framed": (r"""\cs_new_protected:Npn \__oer_shim_framed:
  {
    \cs_gset_eq:NN \__oer_shim_framed: \prg_do_nothing:
    \clist_map_inline:nn { framed , oframed , shaded , shaded* , snugshade , snugshade* , leftbar }
      { \DeclareDocumentEnvironment {##1} { } { \__oer_block_begin:n { } } { \__oer_block_end: } }
    \DeclareDocumentEnvironment { titled-frame } { +m } { \__oer_block_begin:n {##1} } { \__oer_block_end: }
    \DeclareDocumentEnvironment { MakeFramed } { +m } { \__oer_block_begin:n { } } { \__oer_block_end: }
    \cs_if_exist:NF \FrameRule { \newdimen \FrameRule \FrameRule = 0.4pt }
    \cs_if_exist:NF \FrameSep { \newdimen \FrameSep \FrameSep = 3pt }
    \cs_if_exist:NF \OuterFrameSep { \newskip \OuterFrameSep }
    \providecommand \FrameCommand { }
    \providecommand \FirstFrameCommand { }
    \providecommand \MidFrameCommand { }
    \providecommand \LastFrameCommand { }
    \providecommand \FrameHeightAdjust { 0.6em }
    \providecommand \FrameRestore { }
    \providecommand \TitleBarFrame { }
  }
""", "a framed, shaded, or barred passage is set as the text around it is, without its "
         "frame, shading, or bar, a titled frame's title a line in bold"),
    "soul": (r"""\cs_new_protected:Npn \__oer_shim_soul:
  {
    \cs_gset_eq:NN \__oer_shim_soul: \prg_do_nothing:
    \DeclareDocumentCommand \so { +m } {##1}
    \DeclareDocumentCommand \textso { +m } {##1}
    \DeclareDocumentCommand \caps { +m } { \textsc {##1} }
    \DeclareDocumentCommand \textcaps { +m } { \textsc {##1} }
    \DeclareDocumentCommand \ul { +m } { \emph {##1} }
    \DeclareDocumentCommand \textul { +m } { \emph {##1} }
    \DeclareDocumentCommand \st { +m } {##1}
    \DeclareDocumentCommand \textst { +m } {##1}
    \DeclareDocumentCommand \hl { +m } { \emph {##1} }
    \DeclareDocumentCommand \texthl { +m } { \emph {##1} }
    \clist_map_inline:nn { sethlcolor , setulcolor , setstcolor , setuldepth , setuloverlap , soulaccent , capssave , capsselect }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { +m } { } }
    % Text soul prints as it is, without its spacing.
    \DeclareDocumentCommand \soulomit { +m } {##1}
    \DeclareDocumentCommand \sloppyword { +m } {##1}
    \clist_map_inline:nn { setul , soulregister , soulfont }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { m m } { } }
    \DeclareDocumentCommand \capsdef { m m m m m } { }
    \DeclareDocumentCommand \sodef { m m m m m } { }
    \clist_map_inline:nn { resetul , resetso , capsreset }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { } { } }
  }
""", "letter-spaced and struck-out text is set plain, underlined and highlighted text "
         "emphasized (italic), small capitals kept"),
    "ulem": (r"""\cs_new_protected:Npn \__oer_shim_ulem:
  {
    \cs_gset_eq:NN \__oer_shim_ulem: \prg_do_nothing:
    \clist_map_inline:nn { uline , uuline , uwave , dashuline , dotuline }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { +m } { \emph {####1} } }
    \clist_map_inline:nn { sout , xout }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { +m } {####1} }
    \DeclareDocumentCommand \markoverwith { +m } { }
    % A style of the book's own is \bgroup\markoverwith{...}\ULon{text},
    % as ulem's documentation writes one: the text, and the group closed.
    \cs_gset_protected:Npn \ULon ##1 { ##1 \egroup }
    \clist_map_inline:nn { normalem , ULforem }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { } { } }
    \DeclareDocumentCommand \useunder { m m m } { }
    \cs_if_exist:NF \ULdepth { \newdimen \ULdepth }
    \providecommand \ULthickness { 0.4pt }
  }
""", "underlined text is emphasized (italic), and struck-out text set plain"),
    "tabto": (r"""\cs_new_protected:Npn \__oer_shim_tabto:
  {
    \cs_gset_eq:NN \__oer_shim_tabto: \prg_do_nothing:
    \DeclareDocumentCommand \tabto { s m } { \unskip \quad \ignorespaces }
    \DeclareDocumentCommand \tab { } { \unskip \quad \ignorespaces }
    \DeclareDocumentCommand \TabPositions { m } { }
    \DeclareDocumentCommand \NumTabs { m } { }
    \cs_if_exist:NF \CurrentLineWidth { \newdimen \CurrentLineWidth }
    \cs_if_exist:NF \TabPrevPos { \newdimen \TabPrevPos }
  }
""", "a tab stop is a space"),
    "wrapfig": (r"""% A figure in the column, \caption numbering it as a figure's, as
% \captionof does: a float (\begin{figure}) stopped the build in a minipage
% ("Not in outer par mode") and was dropped in multicols. Tagged as LaTeX's
% tagging tags a float, its caption a child of it: in a Div, which veraPDF
% sees through, the caption was a child of the section, among others
% (PDF/UA-2's 8.2.5.27).
\cs_new_protected:Npn \__oer_inline_float:n #1
  {
    \__oer_block_begin:n { }
    \tag_struct_begin:n { tag = float }
    \tl_set:Nn \@captype {#1}
    \centering
  }
\cs_new_protected:Npn \__oer_inline_float_end:
  { \par \tag_struct_end: \__oer_block_end: }
\cs_new_protected:Npn \__oer_shim_wrapfig:
  {
    \cs_gset_eq:NN \__oer_shim_wrapfig: \prg_do_nothing:
    \DeclareDocumentEnvironment { wrapfigure } { o m o m } { \__oer_inline_float:n { figure } } { \__oer_inline_float_end: }
    \DeclareDocumentEnvironment { wraptable } { o m o m } { \__oer_inline_float:n { table } } { \__oer_inline_float_end: }
    \DeclareDocumentEnvironment { wrapfloat } { m o m o m } { \__oer_inline_float:n {##1} } { \__oer_inline_float_end: }
    \cs_if_exist:NF \wrapoverhang { \newdimen \wrapoverhang }
    \providecommand \WFclear { }
  }
""", "a figure or table the text wrapped around is set in the column on its own, where "
         "it was, not floating"),
    # The enumerate package's label patterns, \begin{enumerate}[(a)]: with
    # tagging on, LaTeX's own lists take the optional argument as keys, and
    # stopped on "(a)" ("Some keys specified on the enumerate environment
    # are unknown", at OpenIntro's first). At \begin{document}, after the
    # tagging code defines its lists, enumerate is a wrapper around them
    # that reads an argument naming none of their keys as the package
    # does, with its own loop: each A, a, I, i, or 1 outside braces the
    # counter, styled as the last one is, the rest as written, so a
    # pattern a macro passes (#1) or a style file holds is read too.
    "enumerate": (r"""\ExplSyntaxOff
\newtoks\oer@enLab
\def\oer@enEnd{\oer@enEnd}
\def\oer@enLabel#1#2{\def\oer@enStyle{#1*}%
  \oer@enLab\expandafter{\the\oer@enLab\oer@enCounter}\oer@enloop}
\def\oer@enSpace{\afterassignment\oer@enSp@ce\let\@tempa= }
\def\oer@enSp@ce{\oer@enLab\expandafter{\the\oer@enLab\space}\oer@enloop}
\def\oer@enGroup#1{\oer@enLab\expandafter{\the\oer@enLab{#1}}\oer@enloop}
\def\oer@enOther#1{\oer@enLab\expandafter{\the\oer@enLab#1}\oer@enloop}
\def\oer@enloop{\futurelet\oer@entemp\oer@enloop@}
\def\oer@enloop@{%
  \ifx A\oer@entemp \def\@tempa{\oer@enLabel\Alph}\else
  \ifx a\oer@entemp \def\@tempa{\oer@enLabel\alph}\else
  \ifx i\oer@entemp \def\@tempa{\oer@enLabel\roman}\else
  \ifx I\oer@entemp \def\@tempa{\oer@enLabel\Roman}\else
  \ifx 1\oer@entemp \def\@tempa{\oer@enLabel\arabic}\else
  \ifx\@sptoken\oer@entemp \let\@tempa\oer@enSpace\else
  \ifx\bgroup\oer@entemp \let\@tempa\oer@enGroup\else
  \ifx\oer@enEnd\oer@entemp \let\@tempa\@gobble\else
  \let\@tempa\oer@enOther\fi\fi\fi\fi\fi\fi\fi\fi
  \@tempa}
\ExplSyntaxOn
\tl_new:N \l__oer_enum_tl
\bool_new:N \l__oer_enum_keys_bool
\cs_new_protected:Npn \__oer_enum_if_keys:nTF #1#2#3
  {
    \bool_set_true:N \l__oer_enum_keys_bool
    \tl_if_in:nnF {#1} { = }
      {
        \clist_map_inline:nn {#1}
          {
            \bool_lazy_any:nF
              {
                { \keys_if_exist_p:nn { template / list / std } {##1} }
                { \keys_if_exist_p:nn { template / block / std } {##1} }
                { \keys_if_exist_p:nn { template / blockenv / std } {##1} }
                { \keys_if_exist_p:nn { template / item / std } {##1} }
              }
              { \bool_set_false:N \l__oer_enum_keys_bool \clist_map_break: }
          }
      }
    \bool_if:NTF \l__oer_enum_keys_bool {#2} {#3}
  }
\cs_new_protected:Npn \__oer_enum_open:n #1
  { \begin { oer@enumerate } [ label = {#1} ] }
\cs_new_protected:Npn \__oer_enum_begin:n #1
  {
    \__oer_enum_if_keys:nTF {#1}
      { \begin { oer@enumerate } [#1] }
      {
        \oer@enLab { }
        \cs_set_eq:NN \oer@enStyle \scan_stop:
        \oer@enloop #1 \oer@enEnd
        \tl_set:No \l__oer_enum_tl { \tex_the:D \oer@enLab }
        \cs_if_eq:NNF \oer@enStyle \scan_stop:
          { \exp_args:NNnV \tl_replace_all:Nnn \l__oer_enum_tl { \oer@enCounter } \oer@enStyle }
        \exp_args:NV \__oer_enum_open:n \l__oer_enum_tl
      }
  }
\cs_new_protected:Npn \__oer_enum_wrap:
  {
    \NewEnvironmentCopy { oer@enumerate } { enumerate }
    \RenewDocumentEnvironment { enumerate } { o }
      { \IfNoValueTF {##1} { \begin { oer@enumerate } } { \__oer_enum_begin:n {##1} } }
      { \end { oer@enumerate } }
  }
\cs_new_protected:Npn \__oer_shim_enumerate:
  {
    \cs_gset_eq:NN \__oer_shim_enumerate: \prg_do_nothing:
    \AddToHook { begindocument } { \__oer_enum_wrap: }
  }
""", "a list's label pattern, (a) or i., is read as the package reads it and given to "
         "LaTeX's tagging's lists as their label key, so the labels are as they were"),
    # wasysym's symbols, drawn from its own font, which has no Unicode for
    # them (veraPDF: 8.4.5.8; \Box read as "2"), so a book that loads it
    # kept TeX's fonts and its formulas had no MathML (OWN_FONTS). As the
    # Unicode characters they are, from the OpenType fonts and their
    # fallback, unicode-math can be loaded; the few no font here has are
    # the nearest that is (APL's), or named in brackets. With LuaLaTeX
    # only, as unicode-math is (math_block). The integrals are left to
    # amsmath, which unicode-math loads after, and stopped on one already
    # defined (\iint), and which gives them as Unicode's.
    "wasysym": (r"""\cs_new_protected:Npn \__oer_wasy_char:nn #1#2
  { \exp_args:Nc \DeclareRobustCommand {#1} { \Uchar "#2 \scan_stop: } }
\cs_new_protected:Npn \__oer_wasy_pair:w #1/#2 \q_stop { \__oer_wasy_char:nn {#1} {#2} }
\cs_new_protected:Npn \__oer_wasy_word:nn #1#2
  { \exp_args:Nc \DeclareRobustCommand {#1} { \mbox { [#2] } } }
\cs_new_protected:Npn \__oer_shim_wasysym:
  {
    \cs_gset_eq:NN \__oer_shim_wasysym: \prg_do_nothing:
    \clist_map_inline:nn
      {
      AC/223F, APLbox/25A1, APLcirc/2218, APLcomment/2229, APLdown/2207,
      APLdownarrowbox/2193, APLinput/25A1, APLinv/00F7, APLleftarrowbox/2190,
      APLlog/229B, APLminus/00AF, APLnot/223C, APLrightarrowbox/2192, APLstar/22C6,
      APLup/2206, APLuparrowbox/2191, APLvert/2223, Bowtie/22C8, Box/25A1,
      CIRCLE/25CF, CheckedBox/2611, Circle/25CB, DOWNarrow/25BC, Diamond/25C7,
      HF/2248, Join/22C8, LEFTCIRCLE/25D6, LEFTarrow/25C0, LEFTcircle/25D0,
      LHD/25C0, Leftcircle/25D6, RHD/25B6, RIGHTCIRCLE/25D7, RIGHTarrow/25B6,
      RIGHTcircle/25D1, Rightcircle/25D7, Square/2610, Thorn/00DE, UParrow/25B2,
      VHF/224B, XBox/2612, agemO/2127, apprge/2273, apprle/2272, aquarius/2652,
      ascnode/260A, astrosun/2609, ataribox/25A3, blacksmiley/263B,
      brokenvert/00A6, cancer/264B, capricornus/2651, cent/00A2, checked/2713,
      conjunction/260C, currency/00A4, davidsstar/2721, descnode/260B,
      diameter/2300, earth/2641, eighthnote/266A, female/2640, frownie/2639,
      gemini/264A, hexagon/2B21, hexstar/2721,
      invdiameter/2300, inve/0259, invneg/2310, jupiter/2643, kreuz/2720,
      leadsto/21DD, leftmoon/263E, leftturn/21BA, lhd/22B2, libra/264E,
      lightning/2607, male/2642, mars/2642, mercury/263F, mho/2127, neptune/2646,
      notbackslash/2216, notslash/002F, ocircle/25CB,
      openo/0254, opposition/260D, pentagon/2B20, permil/2030, phone/260E,
      photon/223F, pisces/2653, pluto/2647, pointer/261E, quarternote/2669,
      rhd/22B3, rightmoon/263D, rightturn/21BB, sagittarius/2650, saturn/2644,
      scorpio/264F, smiley/263A, sqsubset/228F, sqsupset/2290, sun/263C,
      taurus/2649, thorn/00FE, twonotes/266B, unlhd/22B4, unrhd/22B5, uranus/2645,
      varangle/2222, varhexagon/2B22, varhexstar/2736, venus/2640, vernal/2648,
      virgo/264D, wasylozenge/2311, wasypropto/221D, wasytherefore/2234,
      varint/222B, varoint/222E, wasyeuro/20AC, wasyparagraph/00B6, Paragraph/00B6,
      wasycmd/2318, applecmd/2318, longs/017F, roundz/007A, fullmoon/25CB,
      newmoon/25CF, aries/2648, leo/264C, logof/229B, iintop/222C, iiintop/222D,
      oiintop/222F
      }
      { \__oer_wasy_pair:w ##1 \q_stop }
    \__oer_wasy_word:nn { bell } { bell }
    \__oer_wasy_word:nn { clock } { clock }
    \__oer_wasy_word:nn { recorder } { recorder }
    \__oer_wasy_word:nn { fullnote } { whole~note }
    \__oer_wasy_word:nn { halfnote } { half~note }
    \__oer_wasy_word:nn { gluon } { gluon }
    \__oer_wasy_word:nn { octagon } { octagon }
    \cs_if_exist:NF \euro { \cs_gset_eq:NN \euro \wasyeuro }
    \DeclareRobustCommand \textwasy [1] {##1}
    \providecommand \wasyfamily { }
    \providecommand \wasy { }
  }
""", "its symbols are drawn as the Unicode characters they are, from the OpenType "
            "fonts, so its formulas get their MathML; a few no font here has are the "
            "nearest one (APL's), or named in brackets ([bell])"),
}
# A package that loads as another's stand-in does.
SHIM_ALIASES = {"soulutf8": "soul"}
# A stand-in that needs LuaLaTeX, whose \Uchar it uses; under pdfLaTeX the
# package loads as the book has it.
SHIM_LUATEX = {"wasysym"}
# Packages math_block can stand in for (SHIMS) and load unicode-math for
# the formulas' MathML, where the rest of OWN_FONTS keep TeX's fonts.
STAND_IN_FONTS = frozenset({"wasysym"})
STAND_IN_NOTE = (
    "% Written for the formulas' MathML, which unicode-math makes: {}, whose\n"
    "% symbols its own font gives no Unicode, isn't loaded with LuaLaTeX; its\n"
    "% commands are the Unicode characters they draw, defined as below.\n")
SHIM_NOTE = (
    "% Written for LaTeX's tagging, which can't build a tagged PDF with these\n"
    "% packages or can't tag what they make (the tagging project's status list):\n"
    "% {}. None is loaded; where the book loads one, its commands are\n"
    "% defined as below instead, to keep what the book says, not how it looks.\n")


def shimmed_packages(packages, base=None):
    """The packages among packages the copy replaces (SHIMS, SHIM_ALIASES),
    in SHIMS' order: each one the tagging status list installed with TeX
    doesn't rate compatible or partially compatible, or every one, when
    the list isn't installed."""
    statuses = {}
    if base:
        import taggingstatus
        path = taggingstatus.kpsewhich(taggingstatus.DATA, base)
        if path:
            statuses = taggingstatus.load(path)[1]
    found = [name for name in list(SHIMS) + list(SHIM_ALIASES)
             if name in packages and name not in STAND_IN_FONTS]
    return [name for name in found if statuses.get((name, "sty")) not in (3, 4)]


def shim_block(names, stand_ins=(), pagestyles=False):
    """What goes before the class for the packages names, which the copy
    replaces, and stand_ins, which math_block stands in for: the
    definitions, and each package's load made to run them. pagestyles:
    the book loads titlesec with that option, which loads titleps."""
    if not names and not stand_ins:
        return ""
    every = list(names) + [n for n in stand_ins if n not in names]
    shims = list(dict.fromkeys(SHIM_ALIASES.get(n, n) for n in every))
    note = SHIM_NOTE.format(", ".join(names)) if names else ""
    if stand_ins:
        note += STAND_IN_NOTE.format(", ".join(stand_ins))
    return (note + "\\makeatletter\n\\ExplSyntaxOn\n" + SHIM_COMMON
            + "".join(SHIMS[s][0] for s in shims)
            + ("\\bool_gset_true:N \\g__oer_titlesec_pagestyles_bool\n"
               if pagestyles and "titlesec" in shims else "")
            + "\\ExplSyntaxOff\n"
            + "".join(("\\ifdefined\\directlua\\disable@package@load{%s}{\\csname "
                       "__oer_shim_%s:\\endcsname}\\fi\n" if n in SHIM_LUATEX else
                       "\\disable@package@load{%s}{\\csname __oer_shim_%s:\\endcsname}\n")
                      % (n, SHIM_ALIASES.get(n, n)) for n in every)
            + "\\makeatother\n")


def shim_changes(names):
    """What replacing names changes in the book's look, in words."""
    shims = list(dict.fromkeys(SHIM_ALIASES.get(n, n) for n in names))
    return "; ".join(f"{s}: {SHIMS[s][1]}" for s in shims)


MATH_FONTS = (
    "% Written for LaTeX's tagging: each formula's MathML, which LaTeX makes\n"
    "% from an OpenType math font (unicode-math's Latin Modern Math, the design\n"
    "% of TeX's own), with a fallback for a character the fonts lack, which\n"
    "% would otherwise have no glyph. With LuaLaTeX; pdfLaTeX builds as before.\n"
    "\\ifdefined\\directlua\n"
    "  \\usepackage{unicode-math}\n"
    "  \\IfFontExistsTF{DejaVu Sans}\n"
    "    {\\directlua{luaotfload.add_fallback(\"textbookimprover\",\n"
    "      {\"Latin Modern Math:mode=harf;\", \"DejaVu Sans:mode=harf;\"})}}\n"
    "    {\\directlua{luaotfload.add_fallback(\"textbookimprover\",\n"
    "      {\"Latin Modern Math:mode=harf;\"})}}\n"
    "  \\setmainfont{Latin Modern Roman}[RawFeature={fallback=textbookimprover}]\n"
    "  \\setsansfont{Latin Modern Sans}[RawFeature={fallback=textbookimprover}]\n"
    "  \\setmonofont{Latin Modern Mono}[RawFeature={fallback=textbookimprover}]\n")


# The same fonts and fallback without unicode-math, for a book with no
# formula whose text has a package's symbols as Unicode (wasysym's).
TEXT_FONTS = MATH_FONTS.replace(
    "% Written for LaTeX's tagging: each formula's MathML, which LaTeX makes\n"
    "% from an OpenType math font (unicode-math's Latin Modern Math, the design\n"
    "% of TeX's own), with a fallback for a character the fonts lack, which\n"
    "% would otherwise have no glyph. With LuaLaTeX; pdfLaTeX builds as before.\n",
    "% Written for LaTeX's tagging: the OpenType Latin Modern fonts, with a\n"
    "% fallback for a character they lack, which would otherwise have no glyph.\n"
    "% With LuaLaTeX; pdfLaTeX builds as before.\n").replace(
    "  \\usepackage{unicode-math}\n", "  \\usepackage{fontspec}\n")


# A PostScript font's NFSS family the book names itself (OpenIntro's
# headings ask for \fontfamily{phv}), which the OpenType fonts' encoding,
# TU, doesn't have: LuaLaTeX set its text in Latin Modern, with a warning
# each time (425 in OpenIntro). TeX Gyre's OpenType fonts are their clones,
# declared under the family's own name where the font is installed.
GYRE = {"phv": "TeX Gyre Heros", "ptm": "TeX Gyre Termes", "pcr": "TeX Gyre Cursor",
        "ppl": "TeX Gyre Pagella", "pbk": "TeX Gyre Bonum", "pnc": "TeX Gyre Schola",
        "pag": "TeX Gyre Adventor", "pzc": "TeX Gyre Chorus"}
FAMILY_USE = re.compile(r"\\(?:fontfamily\s*\{\s*|usefont\s*\{[^{}]*\}\s*\{\s*"
                        r"|(?:renewcommand|def)\s*\{?\s*\\(?:rm|sf|tt|family)default\s*\}?\s*\{\s*)"
                        r"(%s)\s*\}" % "|".join(GYRE))


def gyre_families(texts):
    """(lines, families): each PostScript family the book's files name,
    declared as its TeX Gyre clone for the OpenType fonts, if installed."""
    used = sorted({m.group(1) for t in texts.values()
                   for m in latexsource.code_matches(FAMILY_USE, t)})
    if not used:
        return "", []
    return ("  % The PostScript fonts the book names, as TeX Gyre's clones.\n"
            + "".join("  \\IfFontExistsTF{%s}{\\newfontfamily\\oergyre%s{%s}[NFSSFamily=%s,\n"
                      "    RawFeature={fallback=textbookimprover}]}{}\n"
                      % (GYRE[f], f, GYRE[f], f) for f in used)), used


CLASS = re.compile(r"\\documentclass\s*(?:\[[^]]*\])?\s*\{([^}]*)\}")
LOAD_CLASS = re.compile(r"\\LoadClass(?:WithOptions)?\s*(?:\[[^]]*\])?\s*\{([^}]*)\}")


def preamble_packages(texts, master, base=None):
    """(packages, preamble pieces): the names the master's preamble loads,
    with each file of texts it \\input-s there, and those pieces of text;
    with base, the package and class files beside the book that it loads
    too, and what they load, as a book sets its fonts in a style of its own
    (bookstyle.sty loading newtxmath)."""
    preamble = latexsource.split_master(texts[master])[0]
    pieces = [preamble]
    for m in latexsource.code_matches(PREAMBLE_INPUT, preamble):
        name = m.group(1)
        for candidate in (name, name + ".tex"):
            path = os.path.normpath(os.path.join(os.path.dirname(master), candidate))
            if path in texts:
                pieces.append(texts[path])
                break
    names, classes, read, queue = set(), set(), set(), list(pieces)
    folder = os.path.dirname(master)
    while queue:
        piece = queue.pop(0)
        loaded = [n for m in latexsource.code_matches(PACKAGE, piece)
                  for n in latexsource.package_names(m.group(1))]
        names.update(loaded)
        wanted = [(n, ".sty") for n in loaded]
        for pattern in (CLASS, LOAD_CLASS):
            for m in latexsource.code_matches(pattern, piece):
                classes.add(m.group(1).strip())
                wanted.append((m.group(1).strip(), ".cls"))
        if not base:
            continue
        for name, ext in wanted:
            for where in dict.fromkeys((folder, "")):
                path = os.path.join(base, where, name + ext)
                if path not in read and os.path.isfile(path):
                    read.add(path)
                    text = latexsource.read_text(path)
                    pieces.append(text)
                    queue.append(text)
                    break
    return names, pieces


# A bold the book takes from bm or amsmath's \boldsymbol, which under
# unicode-math draws a formula's letters from TeX's own fonts, where they
# aren't (bm: "There is no 𝑥 (U+1D465) in font rm-lmbx10", a missing glyph
# PDF/UA-2 fails), or puts a formula inside the formula's MathML text
# (\boldsymbol). unicode-math's bold italic is the same letters, bold.
BOLD_MATH = re.compile(r"\\boldsymbol(?![A-Za-z@])")
# amsbsy's \pmb, the poor man's bold, on which LuaTeX stopped while
# LaTeX's tagging took the formula's MathML (\pmb{\hat{p}_1 - b}: "(nodes):
# trying to set an attribute fails, case 2").
POOR_BOLD = re.compile(r"\\pmb(?![A-Za-z@])")


def math_block(texts, master, base=None):
    """(block, counts): what the master gets before \\begin{document} for
    its formulas' MathML, and what was decided. A book with no formula
    gets nothing, unless it loads a package stood in for (wasysym), whose
    symbols then need the OpenType fonts and their fallback (TEXT_FONTS);
    one that loads unicode-math gets the MathML forms named, unless it
    names them itself; one whose fonts are its own keeps them, and the
    packages are named. A PostScript family the book names (\\fontfamily
    {phv}) is declared as its TeX Gyre clone with the OpenType fonts, and
    a book with no formula gets those for it too."""
    families, gyre = gyre_families(texts)
    if not any(latexsource.code_matches(latexsource.MATH_SPANS, t) for t in texts.values()):
        names, _ = preamble_packages(texts, master, base)
        stand_in = names & STAND_IN_FONTS
        if (stand_in or gyre) and not names & (OWN_FONTS - STAND_IN_FONTS) \
                and not names & set(UNICODE_MATH):
            counts = {"text_fonts": 1}
            if stand_in:
                counts["math_stand_in"] = ", ".join(sorted(stand_in))
            if gyre:
                counts["gyre"] = ", ".join(gyre)
            return TEXT_FONTS + families + "\\fi\n", counts
        return "", {}
    names, pieces = preamble_packages(texts, master, base)
    own_setup = any(latexsource.code_matches(MATH_SETUP_KEY, piece) for piece in pieces)
    setup = "" if own_setup else MATH_SETUP_LINE
    if names & set(UNICODE_MATH):
        if not setup:
            return "", {}
        return ("% Written for LaTeX's tagging: each formula's MathML, both forms.\n"
                + setup.lstrip()), {"math_setup": 1}
    kept = sorted(names & (OWN_FONTS - STAND_IN_FONTS))
    if kept:
        return "", {"math_kept": ", ".join(kept)}
    bold, counts = "", {"math": 1}
    if names & STAND_IN_FONTS:
        counts["math_stand_in"] = ", ".join(sorted(names & STAND_IN_FONTS))
    used = [n for n, found in (("bm", "bm" in names), ("\\boldsymbol", any(
        latexsource.code_matches(BOLD_MATH, t) for t in texts.values())), ("\\pmb", any(
        latexsource.code_matches(POOR_BOLD, t) for t in texts.values()))) if found]
    if used:
        bold = ("  % bm's, amsmath's, and amsbsy's bold as unicode-math's bold italic, whose\n"
                "  % letters the fonts have; TeX's own, which they'd use, lack them, and\n"
                "  % LuaTeX stopped on \\pmb's overprinting while tagging.\n"
                + ("  \\AtBeginDocument{\\renewcommand{\\bm}[1]{\\symbfit{#1}}}\n"
                   if "bm" in used else "")
                + ("  \\AtBeginDocument{\\renewcommand{\\boldsymbol}[1]{\\symbfit{#1}}}\n"
                   if "\\boldsymbol" in used else "")
                + ("  \\AtBeginDocument{\\renewcommand{\\pmb}[1]{\\symbfit{#1}}}\n"
                   if "\\pmb" in used else ""))
        counts["math_bold"] = ", ".join(used)
    if gyre:
        counts["gyre"] = ", ".join(gyre)
    return MATH_FONTS + families + setup + bold + latexbuild.UM_ALIASES + "\\fi\n", counts


def _code_subn(pattern, text, replace):
    """re.subn on text, matches in comments and verbatim left alone."""
    spans = latexsource.skip_spans(text)
    count = [0]

    def one(m):
        if latexsource.in_spans(m.start(), spans):
            return m.group(0)
        count[0] += 1
        return replace(m)
    return pattern.sub(one, text), count[0]


def _without_pdftex(m):
    options = [o for o in m.group(2).split(",") if o.strip() != "pdftex"]
    if len(options) == len(m.group(2).split(",")):
        return m.group(0)
    return m.group(1) + ("[%s]" % ",".join(options) if any(o.strip() for o in options) else "")


def _opening_formulas(text):
    """(text, count): \\leavevmode before each display formula that opens
    a paragraph inside a center, flushleft, or flushright environment
    (BLOCK_FORMULA), in code."""
    skip = latexsource.skip_spans(text)
    inside = []
    for m in CENTERED.finditer(text):
        if latexsource.in_spans(m.start(), skip) or any(s <= m.start() < e for s, e in inside):
            continue
        end = latexsource.environment_end(text, m.group(1), m.start())
        if end > 0:
            inside.append((m.start(), end))
    at = [m.end(1) for m in BLOCK_FORMULA.finditer(text)
          if not latexsource.in_spans(m.start(), skip)
          and any(s <= m.start() < e for s, e in inside)]
    for pos in reversed(at):
        text = text[:pos] + "\\leavevmode" + text[pos:]
    return text, len(at)


# The packages that load fancyvrb, whose lists a tagged copy has keep an
# item's label beside the code that opens it (tag).
FANCYVRB_LOADERS = {"fancyvrb", "fvextra", "minted"}

# A block of code, whose lines a tagged copy has a reader of PDF 1.7 read
# a line each (latexbuild.CODE_LINES, tag): an environment the LaTeX
# reader keeps as written (latexsource.VERBATIM) but comment, one of
# fancyvrb's that it reads as code, alltt, or a file of code read in.
CODE_INPUTS = re.compile(r"\\begin\s*\{(?:alltt|BVerbatim|LVerbatim)\}"
                         r"|\\(?:lstinputlisting|VerbatimInput|inputminted)(?![a-zA-Z@])")


def code_blocks(text):
    """Whether text holds a block of code (CODE_INPUTS), outside a comment."""
    for start, _end in latexsource.skip_spans(text):
        m = latexsource.VERBATIM_BEGIN.match(text, start)
        if m and m.group(1) != "comment":
            return True
    return bool(latexsource.code_matches(CODE_INPUTS, text))


# A drawing in LaTeX's picture mode, which a tagged copy has pict2e draw
# (tag), counted to say so.
PICTURE = re.compile(r"\\begin\s*\{picture\}")
# babel's \foreignlanguage, and polyglossia's, in a heading or a caption,
# whose title in the PDF's structure, and its contents entry's, LaTeX's
# tagging makes plain (\pdf_purify:nN), which keeps the arguments of a
# command it has no equivalent for: "Le \foreignlanguage{french}{titre}"
# was titled "Le frenchtitre", where its bookmark, hyperref's, had "Le
# titre" (2026-11-06). Its words alone are, an option before its language
# taken with it, as latexbuild's \href is.
FOREIGNLANGUAGE = re.compile(r"\\foreignlanguage(?![A-Za-z@])")
FOREIGN_TITLES = r"""% In a title LaTeX's tagging makes plain, \foreignlanguage's words alone.
\ExplSyntaxOn
\cs_if_exist:NF \__tiq_purify_foreign:w
  { \cs_new:Npn \__tiq_purify_foreign:w #1 # { \use_ii:nn } }
\text_declare_purify_equivalent:Nn \foreignlanguage { \__tiq_purify_foreign:w }
\ExplSyntaxOff
"""
# A line break in a paragraph: \\, \newline, \linebreak, or \break (and
# so \hfill\break), which leaves no space between its lines in a tagged
# PDF's text without latexbuild.LINE_BREAK_SPACE.
LINE_BREAK = re.compile(r"\\\\|\\(?:newline|linebreak|break)(?![A-Za-z@])")
# A \break with only a vertical command, or nothing, before it on its
# line, after a blank one, which breaks a page, not a line (\vfill\break).
VERTICAL_BEFORE = re.compile(r"\\(?:vfill|vfil|vss|par|newpage|clearpage|cleardoublepage|"
                             r"pagebreak|bigskip|medskip|smallskip|vspace\*?\s*\{[^{}]*\}|"
                             r"vskip\s*[^\s\\]+)\s*$")
# A numbered part or chapter, whose heading the book class, report, and
# amsbook set as two paragraphs, its number's and its title's, which run
# together in a tagged PDF's text without latexbuild.LINE_BREAK_SPACE: a
# call, with its title in braces, not a definition of the command
# (\renewcommand\chapter{...}) or a starred one; in those classes alone,
# since memoir's and KOMA-Script's headings aren't tagged so.
NUMBERED_HEADING = re.compile(r"\\(?:part|chapter)\s*(?:\[[^\]]*\]\s*)?\{")
DEFINING = re.compile(r"\\(?:renewcommand|newcommand|providecommand|def|gdef|edef|xdef|let|"
                      r"DeclareRobustCommand|NewDocumentCommand|RenewDocumentCommand|"
                      r"DeclareDocumentCommand|ProvideDocumentCommand)\*?\s*$")
HEADING_CLASSES = ("book", "report", "amsbook")
# A list of contents, figures, or tables, whose entries' numbers, titles,
# and page numbers run together in a tagged PDF's text without
# latexbuild.LINE_BREAK_SPACE ("1.1A section3"), in the classes whose
# entries LaTeX's tagging sets (latex-lab's toc module; memoir's, KOMA's,
# and amsbook's are their own), and an \enspace, a kern, for which LaTeX's
# tagging writes no space ("Some textwith").
CONTENTS_LIST = re.compile(r"\\(?:tableofcontents|listoffigures|listoftables)(?![A-Za-z@])")
CONTENTS_CLASSES = ("article", "report", "book")
# amsbook, whose lists LaTeX's tagging made numbered chapters, each
# numbering the book's chapters one on (latexbuild.LINE_BREAK_SPACE starts
# each as amsbook does); and amsart and amsproc, whose lists' headings it
# stopped on (the block sets each as an unnumbered section).
LIST_CHAPTER_CLASSES = ("amsbook",)
LIST_HEADING_CLASSES = ("amsart", "amsproc")
# The classes whose contents LaTeX's tagging reaches only in part, their
# own code setting it, which the run warns of where a book in one sets a
# list (convert.py's OWN_CONTENTS, measured with TeX Live 2026).
OWN_CONTENTS_CLASSES = ("amsart", "amsbook", "amsproc", "memoir", "scrartcl", "scrbook",
                        "scrreprt")
# A caption, \caption's (a float's or a longtable's), \captionof's, or the
# caption package's \captionbox's, whose note's mark LaTeX's tagging
# numbered twice, setting the caption twice (latexbuild.LINE_BREAK_SPACE).
CAPTION = re.compile(r"\\caption(of|box)?(?![A-Za-z@])\s*\*?\s*")
NOTE_MARK = re.compile(r"\\footnote(?:mark)?(?![A-Za-z@])")
ENSPACE = re.compile(r"\\enspace(?![A-Za-z@])")
# Environments whose \\ ends a table's row or a formula's line, not a
# paragraph's line (paragraph_breaks).
ROW_ENVIRONMENTS = ("tabular", "tabular*", "tabularx", "tabulary", "longtable", "longtable*",
                    "supertabular", "xtabular", "tabu", "tblr", "longtblr", "NiceTabular",
                    "array", "NiceArray", "subarray", "align", "align*", "alignat", "alignat*",
                    "aligned", "alignedat", "flalign", "flalign*", "gather", "gather*",
                    "gathered", "multline", "multline*", "split", "eqnarray", "eqnarray*",
                    "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix",
                    "smallmatrix", "cases", "dcases", "rcases")
ROW_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{(%s)\}"
                             % "|".join(re.escape(name) for name in ROW_ENVIRONMENTS))


def paragraph_breaks(text):
    """LINE_BREAK's matches in text's code that break a paragraph's line:
    not in a formula, nor in an environment whose \\ ends a table's row or
    a formula's line (ROW_ENVIRONMENTS), one inside another counted
    whole."""
    spans = latexsource.skip_spans(text)
    rows, depth, start = [], 0, 0
    for m in latexsource.code_matches(ROW_ENVIRONMENT, text, spans):
        if m.group(1) == "begin":
            if depth == 0:
                start = m.start()
            depth += 1
        elif depth > 0:
            depth -= 1
            if depth == 0:
                rows.append((start, m.end()))
    if depth > 0:
        rows.append((start, len(text)))
    maths = latexsource.math_spans(text, spans)
    return [m for m in latexsource.code_matches(LINE_BREAK, text, spans)
            if not latexsource.in_spans(m.start(), rows)
            and not latexsource.in_spans(m.start(), maths)
            and not (m.group(0) == "\\break" and page_break(text, m.start()))]


def page_break(text, at):
    """Whether the \\break at text's index at breaks a page, not a line:
    a vertical command before it on its line (VERTICAL_BEFORE), or nothing
    before it but a blank line."""
    start = text.rfind("\n", 0, at) + 1
    before = text[start:at].rstrip()
    if before:
        return bool(VERTICAL_BEFORE.search(before))
    previous = text[:start].rstrip(" \t")
    return not previous.rstrip("\n") or previous.endswith("\n\n") or \
        bool(VERTICAL_BEFORE.search(previous.rstrip()))


def text_enspaces(text):
    """ENSPACE's matches in text's code that call \\enspace in text: not in
    a formula, where it's a kern still, nor where the book defines it."""
    spans = latexsource.skip_spans(text)
    maths = latexsource.math_spans(text, spans)
    return [m for m in latexsource.code_matches(ENSPACE, text, spans)
            if not latexsource.in_spans(m.start(), maths)
            and not DEFINING.search(text[max(0, m.start() - 40):m.start()])]


def bracket_end(text, start):
    """The index just past the optional argument that opens at text[start]
    == '[': its first ] outside braces, or -1."""
    depth, i = 0, start + 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "]" and depth == 0:
            return i + 1
        i += 1
    return -1


def loaded_class(name, master, base):
    """The class a class of the book's own, beside it, loads
    (\\LoadClass{amsbook} in mybook.cls), followed as far as such files go,
    as preamble_packages follows them: name where there's none, or no
    base. A book in a class built on amsbook sets its lists with amsbook's
    code (a review)."""
    seen, folder = {name}, os.path.dirname(master)
    while base:
        for where in dict.fromkeys((folder, "")):
            path = os.path.join(base, where, name + ".cls")
            if os.path.isfile(path):
                break
        else:
            return name
        found = latexsource.code_matches(LOAD_CLASS, latexsource.read_text(path))
        loaded = found[0].group(1).strip() if found else ""
        if not loaded or loaded in seen:
            return name
        seen.add(loaded)
        name = loaded
    return name


def caption_notes(text):
    """How many captions in text's code hold a note's mark: \\caption's
    argument, \\captionbox's first, or \\captionof's after its type, past
    a short caption in brackets, that calls \\footnotemark or \\footnote;
    not where the book defines \\caption itself. Comments and verbatim
    text are blanked first, so that a brace or a mark in a comment counts
    for nothing (a review)."""
    pieces, last = [], 0
    for start, end in latexsource.skip_spans(text):
        pieces.append(text[last:start])
        pieces.append(" " * (end - start))
        last = end
    pieces.append(text[last:])
    text = "".join(pieces)
    count = 0
    for m in CAPTION.finditer(text):
        if DEFINING.search(text[max(0, m.start() - 40):m.start()]):
            continue
        at = m.end()
        if m.group(1) == "of":
            if not text.startswith("{", at):
                continue
            at = latexsource.matching_brace(text, at)
            if at < 0:
                continue
        at = len(text) - len(text[at:].lstrip())
        if text.startswith("[", at):
            at = bracket_end(text, at)
            if at < 0:
                continue
            at = len(text) - len(text[at:].lstrip())
        if not text.startswith("{", at):
            continue
        end = latexsource.matching_brace(text, at)
        if end > 0 and NOTE_MARK.search(text, at, end):
            count += 1
    return count


def numbered_headings(text):
    """NUMBERED_HEADING's matches in text's code that call the command,
    not define it."""
    return [m for m in latexsource.code_matches(NUMBERED_HEADING, text)
            if not DEFINING.search(text[max(0, m.start() - 40):m.start()])]


def tag(texts, master, language, mathml=True, standard=("ua-2",), base=None,
        picture_paths=True):
    """texts: {name: text}, changed in place to build with LaTeX's tagging
    on LuaLaTeX, each change measured on GIAM, where it was needed:
    \\DocumentMetadata before \\documentclass (the standards given, ua-2 by
    default), babel's main language the book's where it gives the book its
    lang (BABEL_MAIN), the pdftex option and pdfTeX's own settings taken out, a
    starred theorem the book defines beside its numbered one defined only
    when tagging hasn't (tagging's \\newtheorem defines thm* with thm),
    \\centerline on a line of its own made a centered paragraph,
    \\leavevmode put before a display formula opening a paragraph in a
    center environment, which leaves one open in LaTeX 2026-06-01, each
    float's tags where the text has it (FLOATS_HERE), the packages
    tagging can't build or tag with replaced by definitions that keep the
    text (SHIMS), pict2e for picture mode, unless picture_paths is false,
    and for the terms cancel strikes out (latexbuild.PICTURE_PATHS), the
    PDF's title and author from a class's own \\title and \\author, which
    don't give them to LaTeX's tagging (OWN_TITLE), memoir given LaTeX's
    own \\title and \\author to change and its footnote mark kept
    (MEMOIR_COMMANDS), and, unless mathml is false, unicode-math
    for the formulas' MathML (math_block). Returns counts."""
    counts = {"metadata": 0, "pdftex_options": 0, "pdftex_settings": 0,
              "theorems": 0, "centerline": 0, "formulas": 0, "floats": 0}
    if mathml:
        block, decided = math_block(texts, master, base)
        counts.update(decided)
    else:
        block = ""
        counts["math_off"] = int(any(latexsource.code_matches(latexsource.MATH_SPANS, t)
                                     for t in texts.values()))
    floats = sum(len(latexsource.code_matches(FLOAT, t)) for t in texts.values())
    packages, pieces = preamble_packages(texts, master, base)
    if floats and not any(latexsource.code_matches(FLOAT_KEY, piece) for piece in pieces):
        block += FLOATS_HERE
        counts["floats"] = floats
    if "enumitem" in packages:
        block += ENUMITEM_KEYS
        counts["enumitem"] = enumitem_settings(texts)
    # Picture mode drawn with paths by pict2e, unless picture_paths is
    # false, and a term the book strikes out with cancel either way, not
    # with glyphs of the line10 and lcircle10 fonts, which have no map to
    # Unicode; not again in a copy made from a copy, where its constant
    # would stop LaTeX ("already defined").
    if (picture_paths or "cancel" in packages) and not any(
            "c__oer_pictiie_names_clist" in piece for piece in pieces):
        block += ("" if picture_paths else latexbuild.PICTURE_FONTS) + latexbuild.PICTURE_PATHS
        counts["cancel"] = int("cancel" in packages)
        counts["picture"] = int(picture_paths and any(
            latexsource.code_matches(PICTURE, t) for t in texts.values()))
    # A list's item that opens with fancyvrb's code keeps its label beside
    # the code's first line under tagging, as a book's PDF from its pages
    # does (latexbuild.CODE_ITEM_LABEL, 2026-10-28), where the book loads
    # fancyvrb or a package that loads it; not again in a copy made from a
    # copy.
    if packages & FANCYVRB_LOADERS and not any(
            "cmd / FV@ListVSpace / before" in piece for piece in pieces):
        block += "\\ExplSyntaxOn\n" + latexbuild.CODE_ITEM_LABEL + "\\ExplSyntaxOff\n"
        counts["code_label"] = 1
    # A block of code's lines a line each to a reader of PDF 1.7, as in a
    # book's PDF from its pages (latexbuild.CODE_LINES), where the book has
    # a block of code; not again in a copy made from a copy.
    if any(code_blocks(t) for t in texts.values()) and not any(
            "oer / code-lines" in piece for piece in pieces):
        block += "\\ExplSyntaxOn\n" + latexbuild.CODE_LINES + "\\ExplSyntaxOff\n"
        counts["code_lines"] = 1
    # A title that holds \foreignlanguage titled by its words alone
    # (FOREIGN_TITLES), where the book has one; not again in a copy made
    # from a copy.
    if any(latexsource.code_matches(FOREIGNLANGUAGE, t) for t in texts.values()) \
            and not any("__tiq_purify_foreign:w" in piece for piece in pieces):
        block += FOREIGN_TITLES
        counts["foreign_titles"] = 1
    # A line break's two lines with a space between them in the text a
    # screen reader gets, and a heading's number and title, as a book's
    # PDF from its pages has them (latexbuild.LINE_BREAK_SPACE), where the
    # book breaks a paragraph's line with \\, \newline, \linebreak, or
    # \break (paragraph_breaks: a \\ that ends a table's row or a
    # formula's line isn't one), numbers a part or a chapter, sets a list
    # of contents, figures, or tables in a class whose entries LaTeX's
    # tagging sets (CONTENTS_CLASSES), the entries getting a space between
    # their number, title, and page number, or writes an \enspace in text,
    # which gets one too; where a caption holds a note's mark, which the
    # block numbers once, and where amsbook sets a list, which it starts as
    # amsbook does (LIST_CHAPTER_CLASSES), or amsart or amsproc does, whose
    # heading it sets as an unnumbered section (LIST_HEADING_CLASSES); not
    # again in a copy made from a copy. A class that sets its contents with
    # code of its own (OWN_CONTENTS_CLASSES) is counted for the run to warn
    # of.
    breaks = any(paragraph_breaks(t) for t in texts.values())
    classes = latexsource.code_matches(latexsource.DOCUMENT_CLASS, texts[master])
    name = loaded_class(classes[0].group(1), master, base) if classes else ""
    book_class = name
    lists = any(latexsource.code_matches(CONTENTS_LIST, t) for t in texts.values())
    headings = name in HEADING_CLASSES and any(numbered_headings(t) for t in texts.values())
    contents = name in CONTENTS_CLASSES and lists
    enspaces = any(text_enspaces(t) for t in texts.values())
    notes = sum(caption_notes(t) for t in texts.values())
    list_chapters = name in LIST_CHAPTER_CLASSES and lists
    list_headings = name in LIST_HEADING_CLASSES and lists
    if (breaks or headings or contents or enspaces or notes or list_chapters
            or list_headings) and not any("oer.break.space" in piece for piece in pieces):
        block += latexbuild.LINE_BREAK_SPACE
        counts["line_breaks"] = int(breaks)
        counts["heading_lines"] = int(headings)
        counts["contents_spaces"] = int(contents)
        counts["en_spaces"] = int(enspaces)
        counts["caption_notes"] = notes
        counts["list_chapters"] = int(list_chapters)
        counts["list_headings"] = int(list_headings)
    if name in OWN_CONTENTS_CLASSES and lists:
        counts["own_contents"] = name
    shimmed = shimmed_packages(packages, base)
    # A package math_block stands in for, so unicode-math loads.
    stand_ins = [n for n in (counts.get("math_stand_in") or "").split(", ") if n]
    numbered = set()
    for text in texts.values():
        spans = latexsource.skip_spans(text)
        numbered.update(m.group(1) for m in NEWTHEOREM.finditer(text)
                        if not latexsource.in_spans(m.start(), spans))
    uses_centerline = False
    for name, text in list(texts.items()):
        def options(m):
            new = _without_pdftex(m)
            counts["pdftex_options"] += int(new != m.group(0))
            return new
        text, _ = _code_subn(OPTIONED, text, options)
        text, n = _code_subn(PDFTEX_SETTING, text, lambda m: "")
        counts["pdftex_settings"] += n
        if latexsource.code_matches(PDFTEX_COMMANDS, text):
            counts["luatex85"] = 1

        def theorem(m):
            if m.group(1) not in numbered:
                return m.group(0)
            counts["theorems"] += 1
            return "\\ifcsname %s*\\endcsname\\else%s\\fi" % (m.group(1), m.group(0))
        text, _ = _code_subn(STARRED_THEOREM, text, theorem)
        text, n = _opening_formulas(text)
        counts["formulas"] += n
        boxes = latexsource.box_tables(text)
        edits = []
        for start, end in boxes:
            edits += [(start, 1, BOX_OPEN), (end, 0, "}")]
        for start, end in latexsource.table_spans(text):
            if any(s < start and end <= e for s, e in boxes):
                # Around a header declaration the table has (declare), so
                # it's set after tagging is set back, as it reads.
                declared = DECLARED_BEFORE.search(text, 0, start)
                if declared and declared.end() == start and text[end:end + 1] == "}":
                    start, end = declared.start(), end + 1
                edits += [(start, 1, DATA_OPEN), (end, 0, "}")]
        # From the end; where one table ends as the next begins, the
        # closing brace goes before the opening one.
        for at, _, piece in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:at] + piece + text[at:]
        counts["boxes"] = counts.get("boxes", 0) + len(boxes)
        spans = latexsource.skip_spans(text)
        if any(not latexsource.in_spans(m.start(), spans)
               for m in CENTERLINE.finditer(text)):
            uses_centerline = True
        texts[name] = text
    text = texts[master]
    if counts.get("boxes"):
        block += BOXES_NOTE
    if "hyperref" not in packages and not packages & HYPERREF_AFTER:
        block += HYPERREF_NOTE
        counts["hyperref"] = 1
    maketitle = any(latexsource.code_matches(MAKETITLE, t) for t in texts.values())
    if not any(latexsource.code_matches(TITLE_SET, piece) for piece in pieces) \
            and not maketitle:
        found = latexsource.visual_title(texts[master])
        title = found[4] if found else escape(os.path.splitext(os.path.basename(master))[0])
        block += TITLE_NOTE + "\\title{%s}\n" % title
        counts["title"] = 1
        counts["title_visual"] = int(bool(found))
    # The PDF's title and author from \title and \author, after the
    # copy's \title, in a class whose own commands don't give them to
    # LaTeX's tagging (OWN_TITLE_CLASSES), where nothing takes them at
    # \maketitle and the book names no pdftitle; not again in a copy made
    # from a copy.
    if book_class in OWN_TITLE_CLASSES and not maketitle \
            and not any(latexsource.code_matches(PDFTITLE, piece) for piece in pieces) \
            and not any("g__tag_title_title_tl" in piece for piece in pieces):
        block += OWN_TITLE
        counts["own_title"] = book_class
    if block:
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, text)
        if begin:
            at = begin[0].start()
            text = text[:at] + block + text[at:]
    if uses_centerline:
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, text)
        if begin:
            at = begin[0].start()
            text = text[:at] + CENTERLINE_DEFINITION + text[at:]
            counts["centerline"] = 1
    claimed = list(standard) or ["ua-2"]
    claim = claimed[0] if len(claimed) == 1 else "{%s}" % ",".join(claimed)
    after = None                        # where what must follow it goes
    given = False                       # the book given its lang here
    own = latexsource.code_matches(DOCUMENT_METADATA, text)
    if not own:
        found = latexsource.code_matches(DOCUMENTCLASS, text)
        if found:
            # First, before any code: a class chosen inside a conditional
            # (\ifx\pdfoutput...) is still after it.
            spans = latexsource.skip_spans(text)
            first = next((m.start() for m in re.finditer(r"\S", text)
                          if not latexsource.in_spans(m.start(), spans)), found[0].start())
            at = text.rfind("\n", 0, min(first, found[0].start())) + 1
            line = "\\DocumentMetadata{%spdfstandard=%s, tagging=on}\n" % (
                "lang=%s, " % language if language else "", claim)
            text = text[:at] + line + text[at:]
            counts["metadata"] = 1
            after = at + len(line)
            given = bool(language)
    else:
        text, after, added = _complete_metadata(text, own[0], language, claim)
        if added:
            counts["metadata_added"] = ", ".join(added)
        given = "lang=%s" % language in added
    if given and after is not None and "babel" in packages:
        main = book_babel_main(pieces)
        if main:
            text = text[:after] + BABEL_MAIN % main + text[after:]
            counts["babel_main"] = main
        elif main is not None:
            counts["babel_main_unknown"] = language
    if counts.get("luatex85") and after is not None:
        text = text[:after] + LUATEX85 + text[after:]
    if (shimmed or stand_ins) and after is not None:
        # Before the class, which may load one of them itself.
        text = text[:after] + shim_block(
            shimmed, stand_ins, "pagestyles" in package_options(pieces, "titlesec")) \
            + text[after:]
        if shimmed:
            counts["shims"] = ", ".join(shimmed)
    # memoir given LaTeX's own \title and \author to change, and its
    # footnote mark kept from hyperref's changes for it (MEMOIR_COMMANDS),
    # before the class, a class of the book's own that loads memoir's too;
    # not again in a copy made from a copy.
    if book_class == "memoir" and after is not None and "class/memoir/before" not in text:
        text = text[:after] + MEMOIR_COMMANDS + text[after:]
        counts["memoir_commands"] = 1
    # First after \DocumentMetadata, before anything loads a face; not again
    # in a copy made from a copy.
    if after is not None and "oerfonts = {" not in text:
        text = text[:after] + STATIC_FONTS + text[after:]
    texts[master] = text
    return counts


def book_babel_main(pieces):
    """babel's main language as the book's build sets it, by its name
    (latexsource.babel_main), from the options the preamble's pieces
    (preamble_packages's) give babel and the master's class's: None where
    the book names it itself (BABEL_MAIN), "" where it can't be known."""
    options = []
    for pattern in (PASSED_OPTIONS, PACKAGE_OPTIONS):
        for piece in pieces:
            for m in latexsource.code_matches(pattern, piece):
                if "babel" in latexsource.package_names(m.group(2)):
                    options += latexsource.option_list(
                        latexsource.COMMENT.sub("", m.group(1) or ""))
    if any(o.partition("=")[0].strip() == "main" for o in options) \
            or any(latexsource.code_matches(PROVIDE_MAIN, piece) for piece in pieces):
        return None
    found = latexsource.code_matches(CLASS_OPTIONS, pieces[0])
    return latexsource.babel_main(options, latexsource.option_list(
        latexsource.COMMENT.sub("", found[0].group(1))) if found else [])


def _key_spans(inner):
    """(start, end) of each key of a comma list, commas inside braces kept;
    inner with its comments blanked (_complete_metadata)."""
    spans, depth, start = [], 0, 0
    for i, ch in enumerate(inner):
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            spans.append((start, i))
            start = i + 1
    spans.append((start, len(inner)))
    return spans


def _complete_metadata(text, m, language, claim):
    """(text, where the line after it begins, keys added): the book's own
    \\DocumentMetadata with tagging=on, and its language and the claimed
    standard when it names none, so a copy made for tagging is tagged: one
    that only sets the PDF's version builds untagged. Its keys are read
    without its comments, which LaTeX skips, a comma in one ending no key,
    and its lines and comments are kept: tagging's value is made on where
    it stands, and the keys added go after the last, before any comment on
    its line, where they had been joined after it, the comment taking them
    and the closing brace."""
    open_at = m.end()
    while open_at < len(text) and text[open_at].isspace():
        open_at += 1
    if text[open_at:open_at + 1] != "{":
        return text, None, []
    close = latexsource.matching_brace(text, open_at)
    if close < 0:
        return text, None, []
    start = open_at + 1
    inner = text[start:close - 1]
    # Each comment made spaces of its length, so the keys are read without
    # it and each place in masked is the same in inner.
    masked = latexsource.COMMENT.sub(lambda c: " " * len(c.group()), inner)
    names = {}
    for a, b in _key_spans(masked):
        key = masked[a:b]
        if key.strip():
            # The last of two the same, as LaTeX takes it.
            names[key.partition("=")[0].strip()] = (a + len(key) - len(key.lstrip()),
                                                    a + len(key.rstrip()))
    added, retagged = [], None
    if "tagging" not in names:
        added.append("tagging=on")
    elif masked[slice(*names["tagging"])].partition("=")[2].strip().strip("{}") != "on":
        retagged = names["tagging"]
    if "lang" not in names and language:
        added.append("lang=%s" % language)
    if "pdfstandard" not in names:
        added.append("pdfstandard=%s" % claim)
    new = inner
    if added:
        at = len(masked.rstrip())
        joint = "" if not masked.strip() else " " if masked.rstrip().endswith(",") else ", "
        new = new[:at] + joint + ", ".join(added) + new[at:]
    if retagged:
        new = new[:retagged[0]] + "tagging=on" + new[retagged[1]:]
        added.insert(0, "tagging=on")
    if added:
        text = text[:start] + new + text[close - 1:]
        close = start + len(new) + 1
    line_end = text.find("\n", close)
    return text, (len(text) if line_end < 0 else line_end + 1), added


# --------------------------------------------------------------------------
# table headers: a person's decision, as LaTeX's tagging declares it
# --------------------------------------------------------------------------

HEADER_KEYS = {"first-row": "table/header-rows={1}",
               "first-column": "table/header-columns={1}",
               "both": "table/header-rows={1},table/header-columns={1}",
               # A layout table, tagged as a division of paragraphs, as the
               # PDF target tags one and a box is (BOX_OPEN).
               "layout": "table/tagging=div"}


def declare(texts, files, decisions):
    """texts: {name: text}, changed in place. decisions: {place: headers},
    a place as latexsource.table_place names a table (its file's index
    among files, its own among the file's tables) and headers one of
    table-headers.csv's first-row, first-column, both, or layout (tagged
    as a division of paragraphs). Each table gets its declaration just
    before it, in a group of its own, since
    \\tagpdfsetup holds until it's changed, and only where it's defined,
    since it isn't without tagging and the book may yet be built without:
    {\\ifdefined\\tagpdfsetup\\tagpdfsetup{...}\\fi\\begin{tabular}...\\end{tabular}}.
    A table the author declared already is left.
    Returns counts."""
    counts = {"header_rows": 0, "header_columns": 0, "declared_already": 0,
              "layout_tables": 0}
    by_file = {}
    for place, headers in decisions.items():
        m = re.fullmatch(r"F(\d+)N(\d+)", place)
        if m and headers in HEADER_KEYS and int(m.group(1)) < len(files):
            by_file.setdefault(files[int(m.group(1))], {})[int(m.group(2))] = headers
    for name, wanted in by_file.items():
        text = texts[name]
        spans = latexsource.table_spans(text)
        edits = []
        for ordinal, headers in wanted.items():
            if not 0 < ordinal <= len(spans):
                continue
            start, end = spans[ordinal - 1]
            before = text[:start].rstrip()
            if re.search(r"\\tagpdfsetup\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\s*(?:\\fi\b)?"
                         r"\s*(?:%[^\n]*\n\s*)*$", before):
                counts["declared_already"] += 1
                continue
            edits.append((end, "}", True))
            edits.append((start, "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{%s}\\fi"
                          % HEADER_KEYS[headers], False))
            counts["header_rows"] += int(headers in ("first-row", "both"))
            counts["header_columns"] += int(headers in ("first-column", "both"))
            counts["layout_tables"] += int(headers == "layout")
        # As in remediate_file: where one table ends and the next begins,
        # the first one's closing goes in front of the next one's opening.
        for at, piece, _ in sorted(edits, key=lambda e: (e[0], not e[2]), reverse=True):
            text = text[:at] + piece + text[at:]
        texts[name] = text
    return counts
