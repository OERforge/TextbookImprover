"""A remediated copy of an author's own LaTeX book: the decisions made
about it in the sidecars, written into the text where each element is, the
rest of every file exactly as the author wrote it. Nothing is parsed and
written again; an element is found the way lib/latexsource.py found it for
the conversion, so a decision reaches the element it was made about.

- **Images and drawings.** Alt text from the image-alt sidecar, as the
  `alt` key LaTeX's tagging reads (`\\includegraphics[alt={...}]`,
  `\\begin{picture}[alt={...}]`, `\\begin{tikzpicture}[alt={...}]`), or
  `artifact` for `[decorative]`. The keys are harmless without tagging:
  pdfLaTeX builds the book as before (checked with TeX Live 2026), and
  with `\\DocumentMetadata{tagging=on}` each becomes the figure's /Alt.
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

The copy holds every .tex file the master reaches, at the same relative
paths and with the same file modes, ready to be laid over the author's
tree.
"""

import os
import re
import shutil

import latexsource

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
                flat[(at, stop)] = PARAGRAPH_BREAK.sub(" ", text[at:stop])
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


def remediate(base, out_dir, master, files, alts, tagging=False, language=None,
              headers=None, definitions=None, definitions_name="", seen=None,
              mathml=True, standard=("ua-2",), written=()):
    """Write a remediated copy of each file in files (relative to base) to
    out_dir at the same relative path. alts: {key: alt, or None for
    decorative} (htmlremediate.alt_rows); tagging: made to build with
    LaTeX's tagging (tag), the book's language its lang; headers:
    {place: headers}, a person's table-header decisions, declared for
    tagging when the copy is tagged (declare), since without tagging
    \\tagpdfsetup isn't defined and the build stops; seen: the keys of
    the images and drawings on the conversion's pages, against which a
    decision the copy couldn't write is counted; mathml: whether a tagged
    copy loads unicode-math for its formulas' MathML; standard: the PDF
    standards a tagged copy's \\DocumentMetadata claims; written: files
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
    for name in files:
        texts[name], counts = remediate_file(
            base, name, originals[name], alts, dirs, name == master, macros,
            definition_spans.get(name, ()), accounted, unplaced,
            {pos: found for (text, pos), found in values.items() if text == name})
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
    if tagging:
        if not language:
            language = latexsource.preamble_language(
                latexsource.split_master(originals[master])[0])
        for key, n in tag(texts, master, language, mathml, standard, base).items():
            totals["tag_" + key] = n
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
# The key came in latex-lab-float 0.81m (2025-12-04), after LaTeX 2025-11-01,
# the oldest release a tagged build is taken to; there it's skipped.
FLOATS_HERE = (
    "% Written for LaTeX's tagging: a figure's or table's tags where the text\n"
    "% has it, not gathered at the end of the document; it's printed where it was.\n"
    "\\ExplSyntaxOn\\keys_if_exist:nnT {__tag/setup} {float/here}\n"
    "  {\\tagpdfsetup{float/here}}\\ExplSyntaxOff\n")
# enumitem's settings for a list, which LaTeX's tagging replaces with an
# emulation of its own (latex-lab-enumitem, loaded by latex-lab-testphase-
# block in place of enumitem.sty, LaTeX 2026-06-01). The emulation stops on
# the settings it lacks ("Some keys specified on the itemize environment
# are unused") and on * and ! for a computed width ("Missing number",
# FINC 308's 101 lists with leftmargin=*), so each is taken here: a width
# to compute or a label's indent is left to the emulation's defaults, resume
# continues the numbering, nolistsep is nosep, and the rest -- code to run
# around a list, a nested label, \ref's form, a description's style -- is
# left out. Checked key by key against the emulation; with enumitem itself
# (no tagging), the block does nothing.
ENUMITEM_KEYS = r"""% Written for LaTeX's tagging, which lays out lists with an emulation of
% enumitem: the settings it lacks are taken, so the lists build. A width to
% compute (leftmargin=*) or a label's indent is left to its defaults, resume
% continues the numbering, and code around a list (before, after), a nested
% label (label*), and ref are left out. With enumitem itself, nothing changes.
\ExplSyntaxOn
\cs_if_exist:cT { ver@latex-lab-enumitem.sty }
  {
    \keys_define:nn { template / block / std }
      {
        leftmargin .code:n =
          { \str_case:nnF {#1} { {*} { } {!} { } }
              { \keys_set:nn { template / block / std } { left-margin = {#1} } } } ,
        labelindent .code:n = { } , labelindent* .code:n = { } ,
        widest .code:n = { } , widest* .code:n = { } , left .code:n = { } ,
        ref .code:n = { } , label* .code:n = { } , series .code:n = { } ,
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
        labelwidth .code:n =
          { \str_case:nnF {#1} { {*} { } {!} { } }
              { \keys_set:nn { template / list / std } { label-width = {#1} } } } ,
        resume .code:n =
          { \tl_if_empty:NF \l__block_counter_tl
              { \keys_set:ne { template / list / std }
                  { start = \int_eval:n { \value { \l__block_counter_tl } + 1 } } } } ,
        resume* .code:n = { \keys_set:nn { template / list / std } { resume } }
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
# defaults, numbering continued, or left out.
ENUMITEM_DEFAULTS = ("leftmargin=*", "leftmargin=!", "labelwidth=*", "labelwidth=!",
                     "labelindent", "labelindent*", "widest", "widest*", "left", "style",
                     "mode", "fullwidth", "nolistsep")
ENUMITEM_LEFT_OUT = ("ref", "label*", "series", "before", "before*", "after", "after*",
                     "first", "first*", "itemjoin", "itemjoin*", "afterlabel")


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
                        or name in ("resume", "resume*"):
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
    \DeclareDocumentCommand \mdfsubtitle { O{} m } { \par \noindent { \bfseries ##2 } \par }
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
    \clist_map_inline:nn { sethlcolor , setulcolor , setstcolor , setuldepth , sloppyword , soulomit , setuloverlap , soulaccent , capssave , capsselect }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { +m } { } }
    \clist_map_inline:nn { setul , soulregister , soulfont , capsdef }
      { \exp_args:Nc \DeclareDocumentCommand {##1} { m m } { } }
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
    \clist_map_inline:nn { ULon , normalem , ULforem }
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
    "wrapfig": (r"""\cs_new_protected:Npn \__oer_shim_wrapfig:
  {
    \cs_gset_eq:NN \__oer_shim_wrapfig: \prg_do_nothing:
    \DeclareDocumentEnvironment { wrapfigure } { o m o m } { \begin {figure} [h] \centering } { \end {figure} }
    \DeclareDocumentEnvironment { wraptable } { o m o m } { \begin {table} [h] \centering } { \end {table} }
    \DeclareDocumentEnvironment { wrapfloat } { m o m o m } { \begin {##1} [h] \centering } { \end {##1} }
    \cs_if_exist:NF \wrapoverhang { \newdimen \wrapoverhang }
    \providecommand \WFclear { }
  }
""", "a figure or table the text wrapped around is set in the column on its own"),
    # The enumerate package's label patterns, \begin{enumerate}[(a)], are
    # written as the keys LaTeX's tagging's lists take (enumerate_labels);
    # its own definitions would be replaced by those lists' anyway.
    "enumerate": (r"""\cs_new_protected:Npn \__oer_shim_enumerate: { }
""", "a list's label pattern, (a) or i., is written as LaTeX's tagging takes it "
         "(label=(\\alph*)), so the labels are as they were"),
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
      wasycmd/2318, applecmd/2318, longs/017F, roundz/007A
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


ENUMERATE_BEGIN = re.compile(r"\\begin\s*\{enumerate\}\s*\[")
ENUMERATE_COUNTERS = {"A": "\\Alph*", "a": "\\alph*", "I": "\\Roman*", "i": "\\roman*",
                      "1": "\\arabic*"}


def enumerate_label(pattern):
    """The enumerate package's label pattern as enumitem's label, which
    LaTeX's tagging's lists take: the first A, a, I, i, or 1 outside braces
    and commands the counter (\\Alph*, \\alph*, \\Roman*, \\roman*,
    \\arabic*), the rest as written; one with none is every item's label,
    as the package makes it."""
    out, i, found = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            m = re.match(r"\\(?:[A-Za-z@]+|.)", pattern[i:])
            out.append(m.group(0))
            i += len(m.group(0))
        elif ch == "{":
            end = latexsource.matching_brace(pattern, i)
            end = len(pattern) if end < 0 else end
            out.append(pattern[i:end])
            i = end
        elif not found and ch in ENUMERATE_COUNTERS:
            out.append(ENUMERATE_COUNTERS[ch])
            found = True
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def enumerate_labels(text):
    """(text, count): each \\begin{enumerate}[pattern] in code with the
    enumerate package's pattern, (a) or i., written [label={...}]: LaTeX's
    tagging lists take its argument as keys, and stopped on "(a)" ("Some
    keys specified on the enumerate environment are unknown", OpenIntro
    Statistics' parts of an exercise). An argument that is already keys
    is left."""
    spans = latexsource.skip_spans(text)
    edits = []
    for m in ENUMERATE_BEGIN.finditer(text):
        if latexsource.in_spans(m.start(), spans):
            continue
        close = _closing_bracket(text, m.end())
        if close is None:
            continue
        pattern = text[m.end():close]
        if any("=" in item for item in _split(pattern)):
            continue
        edits.append((m.end(), close, "label={%s}" % enumerate_label(pattern.strip())))
    for start, end, new in reversed(edits):
        text = text[:start] + new + text[end:]
    return text, len(edits)


def _closing_bracket(text, start):
    """The index of the ] that closes an optional argument opened just
    before start, braces respected, or None."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "\\":
            continue
        if ch == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif ch == "}" and depth and text[i - 1] != "\\":
            depth -= 1
        elif ch == "]" and not depth:
            return i
    return None


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


def shim_block(names, stand_ins=()):
    """What goes before the class for the packages names, which the copy
    replaces, and stand_ins, which math_block stands in for: the
    definitions, and each package's load made to run them."""
    if not names and not stand_ins:
        return ""
    every = list(names) + [n for n in stand_ins if n not in names]
    shims = list(dict.fromkeys(SHIM_ALIASES.get(n, n) for n in every))
    note = SHIM_NOTE.format(", ".join(names)) if names else ""
    if stand_ins:
        note += STAND_IN_NOTE.format(", ".join(stand_ins))
    return (note + "\\makeatletter\n\\ExplSyntaxOn\n" + SHIM_COMMON
            + "".join(SHIMS[s][0] for s in shims) + "\\ExplSyntaxOff\n"
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
    gets nothing; one that loads unicode-math gets the MathML forms
    named, unless it names them itself; one whose fonts are its own keeps
    them, and the packages are named."""
    if not any(latexsource.code_matches(latexsource.MATH_SPANS, t) for t in texts.values()):
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
    return MATH_FONTS + setup + bold + "\\fi\n", counts


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


def tag(texts, master, language, mathml=True, standard=("ua-2",), base=None):
    """texts: {name: text}, changed in place to build with LaTeX's tagging
    on LuaLaTeX, each change measured on GIAM, where it was needed:
    \\DocumentMetadata before \\documentclass (the standards given, ua-2 by
    default), the pdftex option and pdfTeX's own settings taken out, a
    starred theorem the book defines beside its numbered one defined only
    when tagging hasn't (tagging's \\newtheorem defines thm* with thm),
    \\centerline on a line of its own made a centered paragraph,
    \\leavevmode put before a display formula opening a paragraph in a
    center environment, which leaves one open in LaTeX 2026-06-01, each
    float's tags where the text has it (FLOATS_HERE), the packages
    tagging can't build or tag with replaced by definitions that keep the
    text (SHIMS), and, unless mathml is false, unicode-math for the
    formulas' MathML (math_block). Returns counts."""
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
    if not any(latexsource.code_matches(TITLE_SET, piece) for piece in pieces) \
            and not any(latexsource.code_matches(MAKETITLE, t) for t in texts.values()):
        found = latexsource.visual_title(texts[master])
        title = found[4] if found else escape(os.path.splitext(os.path.basename(master))[0])
        block += TITLE_NOTE + "\\title{%s}\n" % title
        counts["title"] = 1
        counts["title_visual"] = int(bool(found))
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
    else:
        text, after, added = _complete_metadata(text, own[0], language, claim)
        if added:
            counts["metadata_added"] = ", ".join(added)
    if counts.get("luatex85") and after is not None:
        text = text[:after] + LUATEX85 + text[after:]
    if (shimmed or stand_ins) and after is not None:
        # Before the class, which may load one of them itself.
        text = text[:after] + shim_block(shimmed, stand_ins) + text[after:]
        if shimmed:
            counts["shims"] = ", ".join(shimmed)
    texts[master] = text
    if "enumerate" in shimmed and after is not None:
        for name in list(texts):
            texts[name], n = enumerate_labels(texts[name])
            counts["enumerate_labels"] = counts.get("enumerate_labels", 0) + n
    return counts


def _complete_metadata(text, m, language, claim):
    """(text, where the line after it begins, keys added): the book's own
    \\DocumentMetadata with tagging=on, and its language and the claimed
    standard when it names none, so a copy made for tagging is tagged: one
    that only sets the PDF's version builds untagged."""
    open_at = m.end()
    while open_at < len(text) and text[open_at].isspace():
        open_at += 1
    if text[open_at:open_at + 1] != "{":
        return text, None, []
    close = latexsource.matching_brace(text, open_at)
    if close < 0:
        return text, None, []
    parts = [p for p in _split(text[open_at + 1:close - 1]) if p.strip()]
    names = {p.partition("=")[0].strip(): i for i, p in enumerate(parts)}
    added = []
    if "tagging" not in names:
        parts.append("tagging=on")
        added.append("tagging=on")
    elif parts[names["tagging"]].partition("=")[2].strip().strip("{}") != "on":
        parts[names["tagging"]] = "tagging=on"
        added.append("tagging=on")
    if "lang" not in names and language:
        parts.append("lang=%s" % language)
        added.append("lang=%s" % language)
    if "pdfstandard" not in names:
        parts.append("pdfstandard=%s" % claim)
        added.append("pdfstandard=%s" % claim)
    if added:
        new = "{" + ", ".join(p.strip() for p in parts) + "}"
        text = text[:open_at] + new + text[close:]
        close = open_at + len(new)
    line_end = text.find("\n", close)
    return text, (len(text) if line_end < 0 else line_end + 1), added


# --------------------------------------------------------------------------
# table headers: a person's decision, as LaTeX's tagging declares it
# --------------------------------------------------------------------------

HEADER_KEYS = {"first-row": "table/header-rows={1}",
               "first-column": "table/header-columns={1}",
               "both": "table/header-rows={1},table/header-columns={1}"}


def declare(texts, files, decisions):
    """texts: {name: text}, changed in place. decisions: {place: headers},
    a place as latexsource.table_place names a table (its file's index
    among files, its own among the file's tables) and headers one of
    table-headers.csv's first-row, first-column, both. Each table gets
    its declaration just before it, in a group of its own, since
    \\tagpdfsetup holds until it's changed, and only where it's defined,
    since it isn't without tagging and the book may yet be built without:
    {\\ifdefined\\tagpdfsetup\\tagpdfsetup{...}\\fi\\begin{tabular}...\\end{tabular}}.
    A table the author declared already is left.
    Returns counts."""
    counts = {"header_rows": 0, "header_columns": 0, "declared_already": 0}
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
        # As in remediate_file: where one table ends and the next begins,
        # the first one's closing goes in front of the next one's opening.
        for at, piece, _ in sorted(edits, key=lambda e: (e[0], not e[2]), reverse=True):
            text = text[:at] + piece + text[at:]
        texts[name] = text
    return counts
