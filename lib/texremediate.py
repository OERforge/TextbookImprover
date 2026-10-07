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
  to each call: the call is wrapped in a group that sets the key first,
  `{\\setkeys{Gin}{alt={...}}\\fig{sq}{1cm}}`, so the macro is left as the
  author wrote it; a macro whose own alt key takes an argument gets the
  text in that argument. A decision the copy can't write, for an image
  reached some other way, is counted against what the conversion's
  pages showed, so the run can name it.
- **Files a build makes.** A file beside a same-named xfig source (`.fig`)
  is fig2dev's, and running the book's build again would write over what's
  written into it; such files are counted, so the run can say so.

The copy holds every .tex file the master reaches, at the same relative
paths, ready to be laid over the author's tree.
"""

import os
import re

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
MOVING = re.compile(r"\\(?:caption|chapter|section|subsection|subsubsection|paragraph"
                    r"|subparagraph|part|markboth|markright|addcontentsline)\*?\s*"
                    r"(?:\[[^]]*\]\s*)?\{")


def _moving_spans(text, skip):
    spans = []
    for m in MOVING.finditer(text):
        if latexsource.in_spans(m.start(), skip):
            continue
        close = latexsource.matching_brace(text, m.end() - 1)
        if close > 0:
            spans.append((m.end(), close))
    return spans


def remediate_file(base, name, text, alts, dirs, is_master=False, macros=None,
                   definitions=(), accounted=None, unplaced=None):
    """The file's text with alt text written in. Returns (text, counts).
    macros: image_macros' macros, followed to each call here outside
    definitions, the spans of the file's own definitions. accounted and
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
    for start, end, macro_name, args in latexsource.macro_calls(
            text, macros or {}, sorted(spans + list(definitions))):
        if any(s <= start < e for s, e in inside):
            continue
        macro = macros[macro_name]
        index = int(re.search(r"#(\d)", macro["file"]).group(1))
        path = re.sub(r"#\d", lambda _: args[index - 1][0].strip(), macro["file"])
        if "\\" in path or "#" in path:
            continue
        key = _image_key(base, name, path, dirs)
        if key is None or key not in alts:
            continue
        alt = alts[key]
        if moving is None:
            moving = _moving_spans(text, spans)
        if macro["keyed"] or any(s <= start < e for s, e in moving) or (
                macro["alt"] is not None and alt is None):
            # The body's own key wins over one set before the call; a
            # moving argument would expand \setkeys; an alt argument
            # can't say artifact.
            unplaced.add(key)
            continue
        if macro["alt"] is not None:
            _, at, stop = args[macro["alt"] - 1]
            if at is None:              # an optional argument not given
                at = stop = start + 1 + len(macro_name)
                edits.append((at, stop, "[{%s}]" % escape(alt), False))
            elif text[at - 1] == "[":   # braced, so a ] in it doesn't end it
                edits.append((at, stop, "{%s}" % escape(alt), False))
            else:
                edits.append((at, stop, escape(alt), False))
        else:
            edits.append((end, end, "}", True))
            edits.append((start, start, "{\\setkeys{Gin}{%s}" % _key(alt), False))
        counts["decorative" if alt is None else "described"] += 1
        counts["macro_calls"] += 1
        accounted.add(key)
        if generated(base, name):
            counts["generated"] += 1
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
DEFINES = re.compile(r"\\(?:(?:re|provide)?newcommand\*?|def)\b")


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
    totals = {"files": 0, "changed": 0}
    originals, texts = {}, {}
    for name in files:
        originals[name] = latexsource.read_text(os.path.join(base, name))
    # The macros the conversion follows, so a call is found as it was read
    # (latexsource.expand_image_macros).
    macros, definition_spans = latexsource.image_macros(
        [(name, originals[name]) for name in files])
    accounted, unplaced = set(), set()
    for name in files:
        texts[name], counts = remediate_file(
            base, name, originals[name], alts, dirs, name == master, macros,
            definition_spans.get(name, ()), accounted, unplaced)
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
        for key, n in tag(texts, master, language, mathml, standard).items():
            totals["tag_" + key] = n
    for name in files:
        if name in written:
            continue
        out = os.path.join(out_dir, name)
        os.makedirs(os.path.dirname(out) or out_dir, exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="") as fh:
            fh.write(texts[name])
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
# An old way of telling pdfLaTeX from LaTeX with dvips, which takes LuaLaTeX
# for the second, since LuaTeX has no \pdfoutput (GIAM's workbook and
# solutions manual choose their class options with it).
PDFOUTPUT_TEST = re.compile(r"\\ifx\s*\\pdfoutput\s*\\undefined(?![A-Za-z@])")
PDFOUTPUT_REPLACEMENT = "\\ifnum0\\ifx\\pdfoutput\\undefined\\ifx\\directlua\\undefined1\\fi\\fi=1 "
NEWTHEOREM = re.compile(r"\\newtheorem\s*\{(\w+)\}")
STARRED_THEOREM = re.compile(r"\\newtheorem\*\s*\{(\w+)\*\}\s*\{[^}]*\}")
CENTERLINE = re.compile(r"\\centerline(?![A-Za-z@])")
BLOCK_FORMULA = re.compile(r"(\\begin\s*\{(?:center|flushleft|flushright)\}\s*)(?=\\\[)")
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
FLOATS_HERE = (
    "% Written for LaTeX's tagging: a figure's or table's tags where the text\n"
    "% has it, not gathered at the end of the document; it's printed where it was.\n"
    "\\ifdefined\\tagpdfsetup\\tagpdfsetup{float/here}\\fi\n")
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


def preamble_packages(texts, master):
    """(packages, preamble pieces): the names the master's preamble loads,
    with each file of texts it \\input-s there, and those pieces of text."""
    preamble = latexsource.split_master(texts[master])[0]
    pieces = [preamble]
    for m in latexsource.code_matches(PREAMBLE_INPUT, preamble):
        name = m.group(1)
        for candidate in (name, name + ".tex"):
            path = os.path.normpath(os.path.join(os.path.dirname(master), candidate))
            if path in texts:
                pieces.append(texts[path])
                break
    names = set()
    for piece in pieces:
        for m in latexsource.code_matches(PACKAGE, piece):
            names.update(n.strip() for n in m.group(1).split(",") if n.strip())
    return names, pieces


def math_block(texts, master):
    """(block, counts): what the master gets before \\begin{document} for
    its formulas' MathML, and what was decided. A book with no formula
    gets nothing; one that loads unicode-math gets the MathML forms
    named, unless it names them itself; one whose fonts are its own keeps
    them, and the packages are named."""
    if not any(latexsource.code_matches(latexsource.MATH_SPANS, t) for t in texts.values()):
        return "", {}
    names, pieces = preamble_packages(texts, master)
    own_setup = any(latexsource.code_matches(MATH_SETUP_KEY, piece) for piece in pieces)
    setup = "" if own_setup else MATH_SETUP_LINE
    if names & set(UNICODE_MATH):
        if not setup:
            return "", {}
        return ("% Written for LaTeX's tagging: each formula's MathML, both forms.\n"
                + setup.lstrip()), {"math_setup": 1}
    kept = sorted(names & OWN_FONTS)
    if kept:
        return "", {"math_kept": ", ".join(kept)}
    return MATH_FONTS + setup + "\\fi\n", {"math": 1}


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


def tag(texts, master, language, mathml=True, standard=("ua-2",)):
    """texts: {name: text}, changed in place to build with LaTeX's tagging
    on LuaLaTeX, each change measured on GIAM, where it was needed:
    \\DocumentMetadata before \\documentclass (the standards given, ua-2 by
    default), the pdftex option and pdfTeX's own settings taken out, a
    starred theorem the book defines beside its numbered one defined only
    when tagging hasn't (tagging's \\newtheorem defines thm* with thm),
    \\centerline on a line of its own made a centered paragraph,
    \\leavevmode put before a display formula opening a center
    environment, which leaves a paragraph open in LaTeX 2026-06-01, each
    float's tags where the text has it (FLOATS_HERE), and, unless mathml
    is false, unicode-math for the formulas' MathML (math_block).
    Returns counts."""
    counts = {"metadata": 0, "pdftex_options": 0, "pdftex_settings": 0,
              "theorems": 0, "centerline": 0, "formulas": 0, "floats": 0}
    if mathml:
        block, decided = math_block(texts, master)
        counts.update(decided)
    else:
        block = ""
        counts["math_off"] = int(any(latexsource.code_matches(latexsource.MATH_SPANS, t)
                                     for t in texts.values()))
    floats = sum(len(latexsource.code_matches(FLOAT, t)) for t in texts.values())
    if floats and not any(latexsource.code_matches(FLOAT_KEY, piece)
                          for piece in preamble_packages(texts, master)[1]):
        block += FLOATS_HERE
        counts["floats"] = floats
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
        text, n = _code_subn(PDFOUTPUT_TEST, text, lambda m: PDFOUTPUT_REPLACEMENT)
        counts["pdfoutput_tests"] = counts.get("pdfoutput_tests", 0) + n

        def theorem(m):
            if m.group(1) not in numbered:
                return m.group(0)
            counts["theorems"] += 1
            return "\\ifcsname %s*\\endcsname\\else%s\\fi" % (m.group(1), m.group(0))
        text, _ = _code_subn(STARRED_THEOREM, text, theorem)
        text, n = _code_subn(BLOCK_FORMULA, text, lambda m: m.group(1) + "\\leavevmode")
        counts["formulas"] += n
        spans = latexsource.skip_spans(text)
        if any(not latexsource.in_spans(m.start(), spans)
               for m in CENTERLINE.finditer(text)):
            uses_centerline = True
        texts[name] = text
    text = texts[master]
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
    if not latexsource.code_matches(DOCUMENT_METADATA, text):
        found = latexsource.code_matches(DOCUMENTCLASS, text)
        if found:
            # First, before any code: a class chosen inside a conditional
            # (\ifx\pdfoutput...) is still after it.
            spans = latexsource.skip_spans(text)
            first = next((m.start() for m in re.finditer(r"\S", text)
                          if not latexsource.in_spans(m.start(), spans)), found[0].start())
            at = text.rfind("\n", 0, min(first, found[0].start())) + 1
            claimed = list(standard) or ["ua-2"]
            text = text[:at] + "\\DocumentMetadata{%spdfstandard=%s, tagging=on}\n" % (
                "lang=%s, " % language if language else "",
                claimed[0] if len(claimed) == 1 else "{%s}" % ",".join(claimed)) + text[at:]
            counts["metadata"] = 1
    texts[master] = text
    return counts


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
