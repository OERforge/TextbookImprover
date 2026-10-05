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


def remediate_file(base, name, text, alts, dirs, is_master=False):
    """The file's text with alt text written in. Returns (text, counts)."""
    counts = {"described": 0, "decorative": 0, "pspicture": 0, "generated": 0}
    edits = []                         # (start, end, replacement)
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
                first = False
                continue
            options = re.match(r"\s*\[[^]]*\]", text[m.end():])
            had = options.group(0).strip() if options else None
            stop = m.end() + (options.end() if options else 0)
            key_here = _key(alt) if first else "artifact"
            edits.append((m.end(), stop, with_key(had, key_here)))
            if first:
                counts["decorative" if alt is None else "described"] += 1
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
                      "\\includegraphics%s{%s}" % (options, m.group(2))))
        counts["decorative" if alt is None else "described"] += 1
        if generated(base, name):
            counts["generated"] += 1
    for start, stop, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[stop:]
    return text, counts


def remediate(base, out_dir, master, files, alts, tagging=False, language=None,
              headers=None):
    """Write a remediated copy of each file in files (relative to base) to
    out_dir at the same relative path. alts: {key: alt, or None for
    decorative} (htmlremediate.alt_rows); tagging: made to build with
    LaTeX's tagging (tag), the book's language its lang; headers:
    {place: headers}, a person's table-header decisions, declared for
    tagging when the copy is tagged (declare), since without tagging
    \\tagpdfsetup isn't defined and the build stops. Returns a dict of
    counts."""
    master_text = latexsource.read_text(os.path.join(base, master))
    dirs = latexsource.graphics_paths(latexsource.split_master(master_text)[0])
    totals = {"files": 0, "changed": 0}
    originals, texts = {}, {}
    for name in files:
        originals[name] = latexsource.read_text(os.path.join(base, name))
        texts[name], counts = remediate_file(base, name, originals[name], alts, dirs,
                                             name == master)
        for key, n in counts.items():
            totals[key] = totals.get(key, 0) + n
    tagged = tagging or bool(latexsource.code_matches(DOCUMENT_METADATA, originals[master]))
    if headers and tagged:
        totals.update(declare(texts, files, headers))
    elif headers:
        totals["headers_untagged"] = len(headers)
    if tagging:
        if not language:
            language = latexsource.preamble_language(
                latexsource.split_master(originals[master])[0])
        for key, n in tag(texts, master, language).items():
            totals["tag_" + key] = n
    for name in files:
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


def tag(texts, master, language):
    """texts: {name: text}, changed in place to build with LaTeX's tagging
    on LuaLaTeX, each change measured on GIAM, where it was needed:
    \\DocumentMetadata before \\documentclass (pdfstandard ua-2), the
    pdftex option and pdfTeX's own settings taken out, a starred theorem
    the book defines beside its numbered one defined only when tagging
    hasn't (tagging's \\newtheorem defines thm* with thm), \\centerline on
    a line of its own made a centered paragraph, and \\leavevmode put
    before a display formula opening a center environment, which leaves
    a paragraph open in LaTeX 2026-06-01. Returns counts."""
    counts = {"metadata": 0, "pdftex_options": 0, "pdftex_settings": 0,
              "theorems": 0, "centerline": 0, "formulas": 0}
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
    if uses_centerline:
        begin = latexsource.code_matches(latexsource.BEGIN_DOCUMENT, text)
        if begin:
            at = begin[0].start()
            text = text[:at] + CENTERLINE_DEFINITION + text[at:]
            counts["centerline"] = 1
    if not latexsource.code_matches(DOCUMENT_METADATA, text):
        found = latexsource.code_matches(DOCUMENTCLASS, text)
        if found:
            at = text.rfind("\n", 0, found[0].start()) + 1
            text = text[:at] + "\\DocumentMetadata{%spdfstandard=ua-2, tagging=on}\n" % (
                "lang=%s, " % language if language else "") + text[at:]
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
            edits.append((end, "}"))
            edits.append((start, "{\\ifdefined\\tagpdfsetup\\tagpdfsetup{%s}\\fi"
                          % HEADER_KEYS[headers]))
            counts["header_rows"] += int(headers in ("first-row", "both"))
            counts["header_columns"] += int(headers in ("first-column", "both"))
        for at, piece in sorted(edits, key=lambda e: e[0], reverse=True):
            text = text[:at] + piece + text[at:]
        texts[name] = text
    return counts
