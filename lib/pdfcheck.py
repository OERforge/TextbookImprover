"""
pdfcheck.py -- what a PDF states about itself, and what that implies.

The simple report: metadata, what the file claims to conform to, and
the structure it carries, all read from the file with pypdf. Nothing
here verifies a claim. "Claims PDF/UA-2" is a fact about the file;
whether it *is* PDF/UA-2 is veraPDF's to say, and the full report adds
veraPDF when it is installed. What this version settles is triage:
whether a PDF is even a candidate for remediation (tagged, with a
structure tree, text rather than scans) or has to go back to its
source.

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

import json
import logging
import os
import re
import subprocess
import tempfile
from collections import Counter
from xml.etree import ElementTree

import alttext
import wcag
from findings import Finding, describe_input

try:
    import pypdf
except ImportError:                     # reported, not fatal
    pypdf = None

# What pypdf says as it reads past a fault in a file's syntax, a key a
# dictionary holds twice (LaTeX's graphics code gives an included PDF that
# has a transparency group a second /Group) or a broken cross-reference
# table, is no finding, and printed in the middle of the run's own lines
# it reads as one. veraPDF judges the file.
logging.getLogger("pypdf").setLevel(logging.ERROR)


def _text(value):
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _xmp_field(xmp, names):
    """The first of several XMP properties that is set, as text."""
    for name in names:
        try:
            value = getattr(xmp, name)
        except Exception:
            value = None
        if value:
            if isinstance(value, dict):          # dc:title etc.
                value = value.get("x-default") or next(iter(value.values()))
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            return _text(value)
    return ""


def _xmp_raw(reader, key):
    """A property from the raw XMP packet, for what pypdf's object
    doesn't expose (pdfuaid:part, pdfaid:part, pdfaid:conformance)."""
    try:
        xmp = reader.xmp_metadata
        if xmp is None:
            return ""
        packet = xmp.stream.get_data().decode("utf-8", "replace")
    except Exception:
        return ""
    m = re.search(r"<%s>([^<]*)</%s>" % (key, key), packet) or \
        re.search(r"\b%s=\"([^\"]*)\"" % key, packet)
    return m.group(1).strip() if m else ""


# How many structure elements the walk visits. A book LaTeX tags runs to
# tens of thousands (MathML alone is thousands of elements per chapter),
# and every Figure has to be reached for its /Alt to be checked.
WALK_LIMIT = 500000


def _walk_structure(node, counts, depth=0, seen=0, alts=None):
    """Count structure elements by type, a bounded walk, and collect
    each Figure's /Alt in alts."""
    if seen > WALK_LIMIT or depth > 200:
        return seen
    try:
        obj = node.get_object() if hasattr(node, "get_object") else node
    except Exception:
        return seen
    if not isinstance(obj, dict):
        return seen
    kind = obj.get("/S")
    if kind is not None:
        counts[_text(kind).lstrip("/")] += 1
        seen += 1
        if alts is not None and _text(kind) == "/Figure":
            alts.append(_text(obj.get("/Alt")) if "/Alt" in obj else None)
    kids = obj.get("/K")
    if kids is None:
        return seen
    try:
        kids = kids.get_object() if hasattr(kids, "get_object") else kids
    except Exception:
        return seen
    if not isinstance(kids, list):
        kids = [kids]
    for kid in kids:
        if isinstance(kid, int):
            continue                      # a marked-content id
        seen = _walk_structure(kid, counts, depth + 1, seen, alts)
    return seen


# Operators that show something inside marked content: text, or an
# XObject (an image, or a form that may hold text of its own).
SHOWING = {b"Tj", b"TJ", b"'", b'"', b"Do"}


def _resolved(obj):
    try:
        return obj.get_object() if hasattr(obj, "get_object") else obj
    except Exception:
        return None


def _role_resolver(tree):
    """A structure type's standard type, through the tree's /RoleMap and
    each namespace's /RoleMapNS, as pdfparagraphs.make_role_resolver
    follows them."""
    mapping = {}

    def add(rolemap, first):
        rolemap = _resolved(rolemap)
        if not isinstance(rolemap, dict):
            return
        for key, value in rolemap.items():
            value = _resolved(value)
            if isinstance(value, list):
                value = value[0] if value else None
            if value is not None and (first or _text(key) not in mapping):
                mapping[_text(key)] = _text(value)

    add(tree.get("/RoleMap"), True)
    for namespace in _resolved(tree.get("/Namespaces")) or []:
        namespace = _resolved(namespace)
        if isinstance(namespace, dict):
            add(namespace.get("/RoleMapNS"), False)

    def resolve(kind):
        seen = set()
        while kind in mapping and kind not in seen:
            seen.add(kind)
            kind = mapping[kind]
        return kind
    return resolve


def _showing_mcids(page):
    """The marked-content ids on a page whose content shows something, or
    None when its content stream can't be read."""
    try:
        contents = page.get_contents()
        operations = contents.operations if contents is not None else []
    except Exception:
        return None
    properties = {}
    try:
        resources = _resolved(page.get("/Resources")) or {}
        properties = _resolved(resources.get("/Properties")) or {}
    except Exception:
        properties = {}
    shown, stack = set(), []
    for operands, operator in operations:
        if operator == b"BDC":
            mcid = None
            if len(operands) > 1:
                listed = _resolved(operands[1])
                if not isinstance(listed, dict):
                    listed = _resolved(properties.get(_text(listed)))
                if isinstance(listed, dict) and "/MCID" in listed:
                    mcid = int(listed["/MCID"])
            stack.append(mcid)
        elif operator == b"BMC":
            stack.append(None)
        elif operator == b"EMC":
            if stack:
                stack.pop()
        elif operator in SHOWING or operator == b"INLINE IMAGE":
            current = next((m for m in reversed(stack) if m is not None), None)
            if current is not None:
                shown.add(current)
    return shown


def _header_content(cell, page, resolve, depth=0):
    """What a header cell holds: (whether it holds a formula, the
    (page, mcid) of its marked content outside formulas, whether it holds
    anything else that may be read: content in a form XObject, or a
    figure outside a formula; and the page its first content is on)."""
    formula, outside, other, pages = False, [], False, []

    def walk(node, page, in_formula, depth):
        nonlocal formula, other
        if depth > 200:
            other = True
            return
        page = node.get("/Pg", page)
        kids = _resolved(node.get("/K"))
        if kids is None:
            return
        if not isinstance(kids, list):
            kids = [kids]
        for kid in kids:
            kid = _resolved(kid)
            if isinstance(kid, int):
                pages.append(page)
                if not in_formula:
                    outside.append((page, int(kid)))
            elif isinstance(kid, dict) and _text(kid.get("/Type")) == "/MCR":
                pages.append(kid.get("/Pg", page))
                if "/Stm" in kid:
                    other = other or not in_formula
                elif not in_formula and "/MCID" in kid:
                    outside.append((kid.get("/Pg", page), int(kid["/MCID"])))
            elif isinstance(kid, dict) and "/S" in kid:
                role = resolve(_text(kid.get("/S")))
                if role == "/Formula":
                    formula = True
                    walk(kid, page, True, depth + 1)
                else:
                    if role == "/Figure" and not in_formula:
                        other = True
                    walk(kid, page, in_formula, depth + 1)

    walk(cell, page, False, depth)
    return formula, outside, other, next((p for p in pages if p is not None), page)


def _formula_headers(reader, tree):
    """Where each header cell holding only formulas is, as "page P, table
    T, header H": a TH with a Formula in it and nothing outside its
    formulas that shows text. NVDA's Acrobat support puts a single space
    in its buffer for a formula and takes a column's header from the
    header cell's text there (adobeAcrobat.cpp), so such a header is never
    announced, as it was heard in Acrobat, where the words beside a
    formula were. Marked content holding only a space glyph counts as
    text here, so a cell padded that way isn't found."""
    resolve = _role_resolver(tree)
    numbers, cache = {}, {}
    for index, page in enumerate(reader.pages, 1):
        ref = getattr(page, "indirect_reference", None)
        if ref is not None:
            numbers[ref.idnum] = (index, page)

    def shows(page_ref, mcid):
        number = numbers.get(getattr(page_ref, "idnum", None))
        if number is None:
            return True
        if number[0] not in cache:
            cache[number[0]] = _showing_mcids(number[1])
        shown = cache[number[0]]
        return shown is None or mcid in shown

    found, tables, counted = [], [], {"tables": 0, "elements": 0}

    def walk(node, page, depth):
        node = _resolved(node)
        if not isinstance(node, dict) or depth > 200 or counted["elements"] > WALK_LIMIT:
            return
        counted["elements"] += 1
        page = node.get("/Pg", page)
        role = resolve(_text(node.get("/S"))) if "/S" in node else ""
        if role == "/Table":
            counted["tables"] += 1
            tables.append([counted["tables"], 0])     # its number, its headers so far
        if role == "/TH" and tables:
            tables[-1][1] += 1
            formula, outside, other, first = _header_content(node, page, resolve)
            if formula and not other and not any(shows(p, m) for p, m in outside):
                where = numbers.get(getattr(first, "idnum", None))
                found.append("%stable %d, header %d" % (
                    "page %d, " % where[0] if where else "", tables[-1][0], tables[-1][1]))
            return
        kids = _resolved(node.get("/K"))
        if kids is None:
            return
        if not isinstance(kids, list):
            kids = [kids]
        for kid in kids:
            walk(kid, page, depth + 1)
        if role == "/Table":
            tables[-1:] = []

    walk(tree, None, 0)
    return found


def _outline_depth(outlines, depth=1):
    deepest, count = depth if outlines else 0, 0
    for item in outlines or []:
        if isinstance(item, list):
            d, c = _outline_depth(item, depth + 1)
            deepest, count = max(deepest, d), count + c
        else:
            count += 1
    return deepest, count


def inspect(path):
    """(facts, findings) for one PDF. facts is an ordered dict of what
    the file states; findings is what that implies."""
    facts, out = {}, []
    name = os.path.basename(path)
    if pypdf is None:
        out.append(Finding(name, "pdf-unreadable",
                           "pypdf is not installed (sudo apt install "
                           "python3-pypdf, or pip3 install --user pypdf "
                           "on Ubuntu 22.04)", file=name, kind="pdf"))
        return facts, out
    try:
        reader = pypdf.PdfReader(path)
        encrypted = reader.is_encrypted
        if encrypted:
            try:
                reader.decrypt("")
            except Exception:
                pass
        pages = len(reader.pages)
    except Exception as exc:
        out.append(Finding(name, "pdf-unreadable", str(exc)[:200], file=name,
                           kind="pdf"))
        return facts, out

    info = reader.metadata or {}
    facts["file"] = describe_input(path)
    facts["pages"] = pages
    try:
        facts["pdf-version"] = reader.pdf_header.replace("%PDF-", "")
    except Exception:
        facts["pdf-version"] = ""
    facts["encrypted"] = bool(encrypted)
    facts["title"] = _text(info.get("/Title", ""))
    facts["author"] = _text(info.get("/Author", ""))
    facts["producer"] = _text(info.get("/Producer", "")) \
        or _xmp_raw(reader, "pdf:Producer")
    facts["creator"] = _text(info.get("/Creator", "")) \
        or _xmp_raw(reader, "xmp:CreatorTool")
    facts["created"] = _text(info.get("/CreationDate", "")) \
        or _xmp_raw(reader, "xmp:CreateDate")
    facts["modified"] = _text(info.get("/ModDate", "")) \
        or _xmp_raw(reader, "xmp:ModifyDate")
    root = reader.trailer.get("/Root", {})
    try:
        root = root.get_object()
    except Exception:
        pass
    facts["language"] = _text(root.get("/Lang", "")) if isinstance(root, dict) else ""
    mark = root.get("/MarkInfo") if isinstance(root, dict) else None
    try:
        mark = mark.get_object() if mark is not None else None
    except Exception:
        mark = None
    facts["tagged"] = bool(mark and mark.get("/Marked"))
    display = root.get("/ViewerPreferences") if isinstance(root, dict) else None
    try:
        display = display.get_object() if display is not None else None
    except Exception:
        display = None
    facts["display-doc-title"] = bool(display and display.get("/DisplayDocTitle"))

    # XMP and the claims
    xmp = None
    try:
        xmp = reader.xmp_metadata
    except Exception:
        xmp = None
    facts["xmp"] = xmp is not None
    if xmp is not None:
        facts["xmp-title"] = _xmp_field(xmp, ["dc_title"])
        facts["xmp-creator"] = _xmp_field(xmp, ["dc_creator"])
        facts["xmp-language"] = _xmp_field(xmp, ["dc_language"])
    facts["claims-pdfua"] = _xmp_raw(reader, "pdfuaid:part")
    part = _xmp_raw(reader, "pdfaid:part")
    conf = _xmp_raw(reader, "pdfaid:conformance")
    facts["claims-pdfa"] = (part + conf.lower()) if part else ""

    # structure
    tree = root.get("/StructTreeRoot") if isinstance(root, dict) else None
    counts = Counter()
    alts = []
    if tree is not None:
        _walk_structure(tree, counts, alts=alts)
    facts["structure-tree"] = tree is not None
    facts["tags"] = dict(counts.most_common(12))
    facts["tag-total"] = sum(counts.values())
    facts["tag-total-capped"] = facts["tag-total"] >= WALK_LIMIT
    if tree is not None:
        try:
            headers = _formula_headers(reader, _resolved(tree))
        except Exception:                 # a malformed tree is veraPDF's to name
            headers = []
        for where in headers:
            out.append(Finding(name, "pdf-table-header-is-formula", where,
                               file=name, kind="pdf"))
    # LaTeX's tagging code gives an image with no alt text its file name
    # as /Alt (latex-lab-testphase-graphic.sty, the alt-text-missing
    # warning), which a validator accepts and which describes nothing, and
    # a drawing with none a placeholder of its own.
    for alt in alts:
        if alt is not None and FILE_NAME.search(alt.strip()):
            out.append(Finding(name, "pdf-figure-alt-is-file-name", alt,
                               file=name, kind="pdf"))
        elif alt is not None and alt.strip() in LATEX_PLACEHOLDERS:
            out.append(Finding(name, "pdf-figure-alt-is-placeholder", alt,
                               file=name, kind="pdf"))
        elif alt is not None:
            # By the rules a deck's pictures are judged by (alttext.py).
            found = alttext.problem(alt, limit=None)
            if found:
                check = {"placeholder": "pdf-figure-alt-is-placeholder",
                         "is-file-name": "pdf-figure-alt-is-file-name"}.get(
                    found[0], "pdf-figure-alt-" + found[0])
                out.append(Finding(name, check, alt, file=name, kind="pdf"))
    try:
        depth, count = _outline_depth(reader.outline)
    except Exception:
        depth, count = 0, 0
    facts["outline-entries"] = count
    facts["outline-depth"] = depth

    # pages: text, and fonts
    empty, fonts, unembedded = [], set(), set()
    for index, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if not text.strip():
            empty.append(index)
        try:
            resources = page.get("/Resources")
            resources = resources.get_object() if resources is not None else {}
            for _, font in (_resolved(resources.get("/Font")) or {}).items():
                font = font.get_object()
                base = _text(font.get("/BaseFont", "")).lstrip("/")
                fonts.add(base)
                desc = font.get("/FontDescriptor")
                desc = desc.get_object() if desc is not None else None
                embedded = desc is not None and any(
                    k in desc for k in ("/FontFile", "/FontFile2",
                                        "/FontFile3"))
                if desc is not None and not embedded and \
                        _text(font.get("/Subtype")) != "/Type0":
                    unembedded.add(base)
        except Exception:
            pass
    facts["pages-without-text"] = empty
    facts["fonts"] = sorted(fonts)
    facts["fonts-not-embedded"] = sorted(unembedded)

    # the implications
    if not facts["tagged"]:
        out.append(Finding(name, "pdf-not-tagged", "no /MarkInfo /Marked true",
                           file=name, kind="pdf"))
    if not facts["structure-tree"]:
        out.append(Finding(name, "pdf-no-structure-tree", "no /StructTreeRoot",
                           file=name, kind="pdf"))
    if not (facts["title"] or facts.get("xmp-title")):
        out.append(Finding(name, "pdf-no-title", "no /Title and no dc:title",
                           file=name, kind="pdf"))
    elif not facts["display-doc-title"]:
        out.append(Finding(name, "pdf-no-title",
                           "a title is set but /DisplayDocTitle is not, so "
                           "viewers show the file name", file=name, kind="pdf",
                           severity="warning"))
    if not (facts["language"] or facts.get("xmp-language")):
        out.append(Finding(name, "pdf-no-language", "no /Lang and no "
                           "dc:language", file=name, kind="pdf"))
    if not facts["outline-entries"]:
        out.append(Finding(name, "pdf-no-outline", "no bookmarks", file=name,
                           kind="pdf"))
    if not facts["xmp"]:
        out.append(Finding(name, "pdf-no-xmp", "no XMP packet", file=name,
                           kind="pdf"))
    if empty:
        shown = ", ".join(str(p) for p in empty[:8])
        more = f" and {len(empty) - 8} more" if len(empty) > 8 else ""
        out.append(Finding(name, "pdf-pages-without-text",
                           f"{len(empty)} of {pages} page(s): {shown}{more}",
                           file=name, kind="pdf"))
    if unembedded:
        out.append(Finding(name, "pdf-fonts-not-embedded",
                           ", ".join(sorted(unembedded)[:6]), file=name,
                           kind="pdf"))
    if facts["encrypted"]:
        out.append(Finding(name, "pdf-encrypted", "the file is encrypted",
                           file=name, kind="pdf"))
    claims = [c for c in (
        f"PDF/UA-{facts['claims-pdfua']}" if facts["claims-pdfua"] else "",
        f"PDF/A-{facts['claims-pdfa']}" if facts["claims-pdfa"] else "")
        if c]
    if claims:
        out.append(Finding(name, "pdf-claims-unverified", "claims "
                           + " and ".join(claims), file=name, kind="pdf"))
    return facts, out


def facts_lines(facts):
    """The metadata section of a report, from inspect()'s facts."""
    if not facts:
        return ["(not read)"]
    f = facts
    lines = []
    lines.append(f"- **File:** `{os.path.basename(f['file']['path'])}`, "
                 f"{f['file']['bytes']:,} bytes, {f['pages']} page(s), "
                 f"PDF {f['pdf-version'] or '?'}"
                 + (", encrypted" if f["encrypted"] else ""))
    lines.append(f"- **SHA-256:** `{f['file']['sha256']}`")
    lines.append(f"- **Title:** {f['title'] or f.get('xmp-title') or '(none)'}"
                 + ("" if f["display-doc-title"] else
                    " (not set to display; viewers show the file name)"))
    lines.append(f"- **Author:** {f['author'] or f.get('xmp-creator') or '(none)'}")
    lines.append(f"- **Language:** {f['language'] or f.get('xmp-language') or '(none)'}")
    lines.append(f"- **Created / modified:** {f['created'] or '?'} / "
                 f"{f['modified'] or '?'}")
    lines.append(f"- **Producer / creator:** {f['producer'] or '?'} / "
                 f"{f['creator'] or '?'}")
    lines.append(f"- **XMP metadata:** {'present' if f['xmp'] else 'none'}")
    claims = []
    if f["claims-pdfua"]:
        claims.append(f"PDF/UA-{f['claims-pdfua']}")
    if f["claims-pdfa"]:
        claims.append(f"PDF/A-{f['claims-pdfa']}")
    lines.append("- **Claims:** " + (", ".join(claims) if claims else "none")
                 + (" (a claim, not a verification; veraPDF checks it)"
                    if claims else ""))
    lines.append(f"- **Tagged:** {'yes' if f['tagged'] else 'no'}; "
                 f"**structure tree:** "
                 f"{'yes' if f['structure-tree'] else 'no'}"
                 + ((", 20,000+ elements (count stopped there)"
                     if f.get("tag-total-capped")
                     else f", {f['tag-total']:,} element(s)")
                    if f["tag-total"] else ""))
    if f["tags"]:
        lines.append("- **Tags by type:** " + ", ".join(
            f"{k} ×{v}" for k, v in f["tags"].items()))
    lines.append("- **Outline:** "
                 + (f"{f['outline-entries']} bookmark(s), {f['outline-depth']} "
                    f"level(s) deep" if f["outline-entries"] else "none"))
    lines.append("- **Pages without text:** "
                 + (str(len(f["pages-without-text"])) if f["pages-without-text"]
                    else "none"))
    lines.append(f"- **Fonts:** {len(f['fonts'])}"
                 + (f", not embedded: {', '.join(f['fonts-not-embedded'])}"
                    if f["fonts-not-embedded"] else ", all embedded"))
    return lines


# What LaTeX's tagging writes as a drawing's alt text when it has none: a
# picture environment's (latex-lab-testphase-graphic.sty) and a
# tikzpicture's (latex-lab-testphase-tikz.sty), LaTeX 2026-06-01.
LATEX_PLACEHOLDERS = ("picture environment", "Alternative text missing!")
FILE_NAME = re.compile(r"(^|[/\\])[^/\\\s]+\.(png|jpe?g|gif|svg|pdf|eps|"
                       r"tiff?|webp|bmp)$", re.I)


def settle_claims(found, verapdf_found):
    """The findings once veraPDF has run: its verdict replaces the note
    that the file's claims are unverified. No failed rule means the
    claims held for every profile veraPDF applied; a failed rule is a
    finding of its own. If veraPDF couldn't run, the note stays."""
    if any(f.check == "verapdf:failed" for f in verapdf_found):
        return found + verapdf_found
    return [f for f in found if f.check != "pdf-claims-unverified"] \
        + verapdf_found


def run_verapdf(command, path):
    """veraPDF's failed rules as findings, when it is installed, one per
    rule and profile. The profiles are veraPDF's own choice from what the
    file claims: given PDF/UA-2 and PDF/A-4f, veraPDF 1.30 applies PDF/UA-2
    with Tagged PDF, PDF/A-4f, and both WTPDF 1.0 profiles (measured).
    Read from its JSON report: its text format names the file and the
    profile on a FAIL line, never the rule."""
    name = os.path.basename(path)
    try:
        result = subprocess.run(command + ["--format", "json", "--nonpdfext",
                                           "--maxfailuresdisplayed", "1",
                                           path],
                                capture_output=True, encoding="utf-8", errors="replace",
                                timeout=1800)
        report = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return [Finding(name, "verapdf:failed", str(exc)[:200], file=name,
                        kind="pdf", tool="verapdf")]
    out = []
    for job in report.get("report", {}).get("jobs", []):
        results = job.get("validationResult") or []
        if isinstance(results, dict):
            results = [results]
        if not results:
            out.append(Finding(name, "verapdf:failed",
                               str(job.get("taskException")
                                   or "no validation result")[:200],
                               file=name, kind="pdf", tool="verapdf"))
        for profile in results:
            for rule in profile.get("details", {}).get("ruleSummaries", []):
                spec = rule.get("specification", "")
                clause = rule.get("clause", "")
                test = rule.get("testNumber", "")
                detail = (f"{rule.get('description', '').strip()} "
                          f"({rule.get('failedChecks', 0)} failed check(s); "
                          f"{profile.get('profileName', '')})")
                out.append(Finding(name, f"verapdf:{clause}-{test}",
                                   detail[:400], file=name, kind="pdf",
                                   standard=f"{spec} clause {clause}",
                                   tool="verapdf"))
    return out


# --------------------------------------------------------------------------
# veraPDF's WCAG 2.2 machine checks, when they're asked for (--wcag)
# --------------------------------------------------------------------------
#
# veraPDF's WCAG 2.2 profiles hold most of PDF/UA's rules and eleven of
# their own, on the objects of a semantic layer (SATextChunk, SAFigure,
# and so on) that two modules veraPDF's release doesn't include build,
# wcag-validation and wcag-algorithms, with PDFBox, which draws the pages
# for the contrast check. Without them veraPDF passes those rules with
# nothing checked and says nothing of it: its document model adds the
# semantic layer only when the class that builds it loads
# (GFCosDocument.getdocument, 1.30.3). VERAPDF_WCAG names a folder holding
# the jars and the two machine profiles, one for PDF 2.0 and one for PDF
# 1.x, and veraPDF's launcher puts CLASSPATH_PREFIX ahead of its own jar.
# A probe, a PDF of ten underscores written here, is checked first in the
# same run: its rule 1.3.1-1, five or more of one character in a row,
# fails only when the modules have loaded, so it says whether the rest
# were checked. Only the profile's own rules are reported, PDF/UA's being
# the run's without --wcag, and each as a note: the rules are heuristics
# and some misread a book, and the profile is WCAG 2.2's, beyond what many
# readers are held to. What veraPDF leaves unsaid (a file it skipped, an
# error it printed as it went) is said here.

WCAG_VARIABLE = "VERAPDF_WCAG"
WCAG_MODULES = ("wcag-validation", "wcag-algorithms")
WCAG_PROFILES = {"2": "WCAG-2-2-Machine-PDF20.xml", "1": "WCAG-2-2-Machine.xml"}
WCAG_FILES = {"2": "PDF 2.0", "1": "PDF 1.x"}   # the files each profile is for
WCAG_CAVEAT = "veraPDF's WCAG checks are experimental and may be wrong"
WCAG_SKIPPED = ("without them veraPDF skips its WCAG checks silently, passing "
                "their rules unchecked")
WCAG_DOCS = "docs/installation.md, Optional: veraPDF's WCAG modules"
WCAG_ALONE = ("--verbose lists veraPDF's WCAG checks one by one, with --wcag; without it, "
              "it changes nothing.")
WCAG_VERBOSE = ("Each rule's failed checks are counted, not listed: run again with --verbose "
                "for each one, with what the PDF has there (a link's address, the line "
                "repeated characters are on), or check one PDF so with check-output.py "
                "--wcag --verbose --pdf.")
# The failed checks veraPDF is asked to list for a rule, each a finding
# (it lists 100 unless told; on Introduction to Sociology 3e, 789 bare
# links fail 2.4.9-1, on 121 pages). However many are asked for, veraPDF
# lists about 10,000 of a PDF's failed checks in all, PDF/UA's rules'
# among them, and past that only a rule's first (BaseValidator's
# MAX_CHECKS_NUMBER, 1.30.3; measured), so this asks for every one it
# will list.
WCAG_LISTED = 10000


def wcag_probe():
    """The probe's bytes: a page whose one tagged paragraph is ten
    underscores, in Helvetica, not embedded. veraPDF fails it on
    PDF/UA's rules whether the modules load or not, and on rule 1.3.1-1
    only when they do."""
    content = (b"/P <</MCID 0>> BDC\nBT /F1 12 Tf 72 720 Td (__________) Tj ET\n"
               b"EMC\n")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /MarkInfo << /Marked true >> "
        b"/StructTreeRoot 5 0 R /Lang (en) >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 8 0 R "
        b"/StructParents 0 /Tabs /S >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /StructTreeRoot /K [6 0 R] /ParentTree 9 0 R "
        b"/ParentTreeNextKey 1 >>",
        b"<< /Type /StructElem /S /Document /P 5 0 R /K [7 0 R] >>",
        b"<< /Type /StructElem /S /P /P 6 0 R /Pg 3 0 R /K [0] >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Nums [0 [7 0 R]] >>",
    ]
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, start))
    return bytes(out)


def pdf_major(path):
    """"2" for a file whose header says PDF 2.0, which LaTeX writes in a
    PDF/UA-2 file's, else "1": which of the two profiles it's checked
    against."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024)
    except OSError:
        return "1"
    found = re.search(rb"%PDF-(\d)\.\d", head)
    return "2" if found and found.group(1) == b"2" else "1"


def wcag_modules(folder):
    """{module: [versions]} for the WCAG modules' jars in the folder,
    read from their names (wcag-validation-1.30.3.jar); a sources or a
    javadoc jar isn't one."""
    found = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return found
    for name in names:
        for module in WCAG_MODULES:
            matched = re.match(re.escape(module) + r"-(\d+(?:\.\d+)*)\.jar$", name)
            if matched:
                found.setdefault(module, []).append(matched.group(1))
    return found


def run_verapdf_wcag(command, paths, folder=None, timeout=3600, verbose=False):
    """veraPDF's WCAG 2.2 machine checks on the PDFs, as (findings,
    lines): a note for each of the profile's own rules a PDF failed,
    counting its failed checks, and the lines for the run's summary or a
    report, the first saying whether the checks ran, then a warning for
    anything that kept them from running or from checking everything,
    which veraPDF itself doesn't say, then one for each rule a PDF
    failed, and one saying --verbose lists each check. verbose: a note
    for each failed check instead, with what the PDF has there, which
    veraPDF's report doesn't say (a link's address, the line repeated
    characters are on), and a line for each after its rule's. With no
    PDFs, the probe alone, which checks the setup. folder: where the
    modules and the profiles are, VERAPDF_WCAG's when not given."""
    if folder is None:
        folder = os.environ.get(WCAG_VARIABLE, "").strip()
    if not folder:
        return [], [f"WARNING: veraPDF's WCAG modules aren't installed ({WCAG_VARIABLE} "
                    f"names no folder of them), and {WCAG_SKIPPED}; --wcag ran nothing "
                    f"({WCAG_DOCS})."]
    if not os.path.isdir(folder):
        return [], [f"WARNING: veraPDF's WCAG modules aren't installed: {folder} "
                    f"({WCAG_VARIABLE}) isn't a folder, and {WCAG_SKIPPED}; --wcag ran "
                    f"nothing ({WCAG_DOCS})."]
    modules = wcag_modules(folder)
    missing = [module for module in WCAG_MODULES if module not in modules]
    if missing:
        return [], [f"WARNING: veraPDF's WCAG modules aren't installed: {folder} "
                    f"({WCAG_VARIABLE}) has no {' or '.join(missing)} jar, and "
                    f"{WCAG_SKIPPED}; --wcag ran nothing ({WCAG_DOCS})."]
    warnings = [f"WARNING: --wcag: {folder} ({WCAG_VARIABLE}) has {module} "
                f"{' and '.join(modules[module])}, and Java loads one, without saying "
                "which; keep only veraPDF's own version."
                for module in WCAG_MODULES if len(modules[module]) > 1]
    profiles = {major: os.path.join(folder, name) for major, name in WCAG_PROFILES.items()}
    groups = {}
    for path in paths:
        groups.setdefault(pdf_major(path), []).append(os.path.abspath(path))
    def unfit(major):
        """Why the folder's profile for a PDF major.x file can't be run, if
        it can't: it isn't there, or the probe can't tell with it."""
        name = WCAG_PROFILES[major]
        if not os.path.isfile(profiles[major]):
            return f"{folder} ({WCAG_VARIABLE}) has no {name}"
        tells = _probe_tells(profiles[major])
        if tells is None:
            return f"{name} in {folder} ({WCAG_VARIABLE}) can't be read as a profile"
        if not tells:
            return (f"{name} in {folder} ({WCAG_VARIABLE}) lacks the rule veraPDF's 1.30 "
                    "machine profiles have on repeated characters, 1.3.1-1, which the "
                    "probe needs to tell whether veraPDF's WCAG modules loaded")
        return ""

    for major, group in sorted(groups.items(), reverse=True):
        why = unfit(major)
        if why:
            warnings.append(f"WARNING: --wcag: {why}, so the WCAG checks didn't run on "
                            f"{len(group)} {WCAG_FILES[major]} file(s): {_listed(group)} "
                            f"({WCAG_DOCS}).")
            del groups[major]
    fit, unfitting = None, []
    if not paths:
        # The setup alone: both profiles should be there, and the probe
        # runs with whichever is, PDF 2.0's first; what it says names the
        # files the checks run on, and the warning the ones they won't,
        # after a warning that the modules didn't load, which is first.
        whys = {major: unfit(major) for major in ("2", "1")}
        unfitting = [f"WARNING: --wcag: {why}, so the WCAG checks won't run on a "
                     f"{WCAG_FILES[major]} file, as a PDF/UA-{major} build is ({WCAG_DOCS})."
                     for major, why in whys.items() if why]
        fit = [major for major in ("2", "1") if not whys[major]]
        groups = {fit[0]: []} if fit else {}
    if not groups:
        return [], warnings + unfitting
    environment = dict(os.environ)
    environment["CLASSPATH_PREFIX"] = os.pathsep.join(
        [os.path.join(os.path.abspath(folder), "*")]
        + ([environment["CLASSPATH_PREFIX"]] if environment.get("CLASSPATH_PREFIX")
           else []))
    findings, rules, ran = [], [], []
    with tempfile.TemporaryDirectory() as work:
        probe = os.path.join(work, "wcag-probe.pdf")
        with open(probe, "wb") as fh:
            fh.write(wcag_probe())
        for major, group in sorted(groups.items(), reverse=True):
            result = _run_wcag(command, profiles[major], probe, group, environment, timeout)
            if isinstance(result, str):
                warnings.append(result)
                continue
            report, stderr = result
            try:
                read = wcag_report(report, probe, folder, modules, group, verbose)
            except Exception as exc:        # a report no veraPDF writes
                warnings.append(f"WARNING: --wcag: veraPDF's report on "
                                f"{WCAG_PROFILES[major]} couldn't be read: {exc}")
                continue
            warnings += read["warnings"]
            if not read["loaded"]:
                break                       # nor will they with the other profile
            findings += read["findings"]
            rules += read["rules"]
            ran.append(read)
            said = _java_error(stderr)
            if said:
                warnings.append("WARNING: --wcag: veraPDF wrote an error as it checked, "
                                f"which may have left some checks undone: {said}")
    head = []
    if ran:
        version = ran[0]["version"]
        if paths:
            head = [f"veraPDF {version}'s WCAG 2.2 machine checks ran on "
                    f"{sum(read['checked'] for read in ran)} PDF(s), with its WCAG modules "
                    f"from {folder}: {WCAG_CAVEAT}, so what they find is a note, never a "
                    "failure."]
        else:
            files = ("PDF 2.0 and PDF 1.x files alike" if len(fit) == 2 else
                     f"a {WCAG_FILES[fit[0]]} file, as a PDF/UA-{fit[0]} build is, but not "
                     f"on a {WCAG_FILES['1' if fit[0] == '2' else '2']} file")
            head = [f"veraPDF {version} loaded its WCAG modules from {folder} ("
                    + ", ".join(f"{module} {' and '.join(modules[module])}"
                                for module in WCAG_MODULES)
                    + f"), so its WCAG 2.2 machine checks run on {files}; {WCAG_CAVEAT}."]
    listed = [line for _, lines in sorted(rules) for line in lines]
    if rules and not verbose:
        listed.append(WCAG_VERBOSE)
    return findings, head + warnings + unfitting + listed


def _listed(paths, shown=3):
    """The files' names, as a warning gives them: three at most, then
    how many more."""
    names = [os.path.basename(path) for path in paths[:shown]]
    if len(paths) > shown:
        names.append(f"{len(paths) - shown} more")
    if len(names) < 3:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _run_wcag(command, profile, probe, group, environment, timeout):
    """veraPDF's JSON report and its stderr from a run of the profile on
    the probe and the group, or a warning saying why there's none."""
    name = os.path.basename(profile)
    try:
        result = subprocess.run(
            command + ["--loglevel", "0", "--nonpdfext", "-p", profile, "--format", "json",
                       "--maxfailuresdisplayed", str(WCAG_LISTED), probe] + group,
            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
            env=environment)
    except subprocess.TimeoutExpired:
        return (f"WARNING: --wcag: veraPDF hadn't finished with {name} after {timeout} "
                "seconds, and was stopped.")
    except OSError as exc:
        return f"WARNING: --wcag: veraPDF couldn't be run: {exc}"
    try:
        return json.loads(result.stdout), result.stderr
    except ValueError:
        said = _java_error(result.stderr) or next(
            (line.strip() for line in reversed((result.stderr + result.stdout).splitlines())
             if line.strip() and not JVM_NOTE.match(line.strip())), "")
        return (f"WARNING: --wcag: veraPDF didn't report on {name}: "
                + (said[:300] if said else f"stopped by signal {-result.returncode}"
                   if result.returncode < 0 else f"exit status {result.returncode}"))


# A Java exception's own line, as a stack trace opens or goes on with it:
# java.io.IOException: ..., Exception in thread "main" ..., Caused by: ...;
# not a frame of the stack, nor a line that only mentions an error, as the
# JVM's note of the options it picked up can (-XX:+HeapDumpOnOutOfMemoryError).
JAVA_EXCEPTION = re.compile(r'^(?:Exception in thread "[^"]*" |Caused by: )?'
                            r'(?:[A-Za-z_$][\w$]*\.)+[\w$]*(?:Exception|Error)\b')


# The JVM's note of the options it picked up from the environment, which
# it writes before anything else: "Picked up JAVA_TOOL_OPTIONS: ...", or
# "NOTE: Picked up JDK_JAVA_OPTIONS: ...".
JVM_NOTE = re.compile(r"(?:NOTE: )?Picked up ")


def _java_error(stderr):
    """The line of Java's stderr that says what went wrong, when one
    does: an exception's own, not a frame of its stack."""
    for line in (stderr or "").splitlines():
        if JAVA_EXCEPTION.match(line.strip()):
            return line.strip()[:300]
    return ""


def _probe_tells(profile):
    """Whether the profile has the rule the probe fails, 1.3.1-1 on
    SARepeatedCharacters, without which a probe that passes says nothing
    of the modules; None when the file can't be read as XML."""
    space = "{http://www.verapdf.org/ValidationProfile}"
    try:
        root = ElementTree.parse(profile).getroot()
    except (OSError, ElementTree.ParseError, ValueError, LookupError):
        return None                         # LookupError: an encoding Python doesn't
                                            # know; ValueError: a multibyte one
    for rule in root.iter(space + "rule"):
        ident = rule.find(space + "id")
        if rule.get("object") == "SARepeatedCharacters" and ident is not None \
                and ident.get("clause") == "1.3.1" and ident.get("testNumber") == "1":
            return True
    return False


def wcag_report(report, probe, folder="", modules=None, expected=(), verbose=False):
    """What veraPDF's JSON report of a run of a WCAG profile, the probe
    among its files, says: {"loaded": whether the probe failed one of
    the profile's own rules, so the modules loaded, "version": veraPDF's,
    "checked": how many PDFs besides the probe were checked, "findings",
    "rules": (a sort key, the summary's lines) for each rule a PDF failed,
    and "warnings"}. When the probe passed, the warning says so and
    nothing else is read, since then no WCAG rule was checked. expected:
    the PDFs given, each of which veraPDF should have reported on.
    verbose: a finding, and a line, for each failed check, with what the
    PDF it names (veraPDF's own name for it) has there."""
    modules = modules or {}
    body = _dict(_dict(report).get("report"))
    details = {}
    for item in _list(_dict(body.get("buildInformation")).get("releaseDetails")):
        details[_dict(item).get("id")] = _dict(item).get("version")
    version = str(details.get("apps") or details.get("validation-model") or "?")
    read = {"loaded": False, "version": version, "checked": 0, "findings": [],
            "rules": [], "warnings": []}
    jobs = [job for job in _list(body.get("jobs")) if isinstance(job, dict)]
    probed = next((job for job in jobs if _same_file(
        _dict(job.get("itemDetails")).get("name"), probe)), None)
    ours = sorted(set(modules.get("wcag-validation") or []))
    other = ours and version != "?" and version not in ours
    if probed is None or not _wcag_failed(probed):
        why = (f"its wcag-validation there is {' and '.join(ours)} and veraPDF is "
               f"{version}, where it must be veraPDF's own version" if other else
               "a jar they need may be missing from the folder, or VERAPDF names "
               "veraPDF's jar rather than its launcher, which reads CLASSPATH_PREFIX")
        read["warnings"].append(f"WARNING: veraPDF {version} didn't load its WCAG modules "
                                f"from {folder} ({why}), and {WCAG_SKIPPED}; nothing it "
                                f"said about them is reported ({WCAG_DOCS}).")
        return read
    read["loaded"] = True
    if other:
        read["warnings"].append(f"WARNING: --wcag: veraPDF {version} loaded wcag-validation "
                                f"{' and '.join(ours)} from {folder}, which should be its "
                                f"own version ({WCAG_DOCS}).")
    seen = set()
    for job in jobs:
        if job is probed:
            continue
        path = str(_dict(job.get("itemDetails")).get("name") or "")
        name = os.path.basename(path)
        if path:
            seen.add(os.path.realpath(path))
        context = _WcagContext(path) if verbose else None
        try:
            results = job.get("validationResult")
            results = [results] if isinstance(results, dict) else [
                result for result in _list(results) if isinstance(result, dict)]
            if not results:
                read["warnings"].append(f"WARNING: --wcag: veraPDF couldn't check {name}: "
                                        + _task_exception(job))
                continue
            read["checked"] += 1
            for profile in results:
                for rule in _list(_dict(profile.get("details")).get("ruleSummaries")):
                    if not isinstance(rule, dict) or not str(
                            rule.get("specification", "")).startswith("WCAG"):
                        continue
                    found, pages, lines = wcag_rule_findings(name, rule, context)
                    read["findings"] += found
                    read["rules"].append((_rule_key(name, rule),
                                          [wcag_rule_line(name, rule, pages)] + lines))
        except Exception as exc:            # a job no veraPDF writes, read as far as it goes
            read["warnings"].append(f"WARNING: --wcag: veraPDF's report on {name} couldn't "
                                    f"be read: {exc}")
    for path in expected:
        if os.path.realpath(path) not in seen:
            read["warnings"].append(
                f"WARNING: --wcag: veraPDF didn't check {os.path.basename(path)}, and said "
                "nothing of it, as it doesn't of a file it can't open by its name (one "
                "outside ASCII where the locale isn't UTF-8, say).")
    return read


def wcag_rule_findings(name, rule, context=None):
    """(findings, pages, lines) for one of the WCAG profile's own rules a
    PDF failed: a note saying so, with how many of its checks failed and
    the pages of those veraPDF listed, the first 20, the criterion, its
    level, and its Understanding document; and the pages. context (a _WcagContext, for
    --verbose): a note for each failed check veraPDF lists instead,
    saying where (the PDF, and the page when veraPDF gives one), the rule,
    what veraPDF found, and what the PDF has there, and one more for a
    rule failed more often than veraPDF lists, saying how many more; and
    a line for each listed check, for the summary."""
    clause = str(rule.get("clause", ""))
    check = f"verapdf-wcag:{clause}-{rule.get('testNumber', '')}"
    description = str(rule.get("description") or "").strip().rstrip(".")
    about = f"{wcag.named(clause)}: {wcag.url(clause)}. {WCAG_CAVEAT}."
    listed = _failed_checks(rule)
    total = max(_count(rule.get("failedChecks")), len(listed))

    def note(where, detail):
        return Finding(where, check, detail, file=name, kind="pdf", severity="note",
                       standard=wcag.standard(clause), tool="verapdf", fix="manual")

    pages = sorted({page for page in map(_wcag_page, listed) if page})
    if context is None:
        each = "each" if total <= len(listed) else f"the {len(listed)} veraPDF listed"
        return ([note(name, f"{description}: {total} failed check(s)"
                            f"{_pages_listed(pages, total, len(listed), shown=20)}; "
                            f"--verbose lists {each}, with what the PDF has there. {about}")],
                pages, [])
    out, lines = [], []
    for item in listed:
        page = _wcag_page(item)
        said = _wcag_said(item)
        there = context.about(str(rule.get("object") or ""), item)
        if there:
            said = f"{said} ({there})" if said else there
        where = f"{name}#page={page}" if page else name
        out.append(note(where, f"{description}: {said}. {about}" if said
                        else f"{description}. {about}"))
        lines.append(f"  {where}: {said or description}")
    if total > len(listed):
        more = (f"{total - len(listed)} more failed check(s), which veraPDF didn't list (it "
                "lists about 10,000 of a PDF's at most)" if listed
                else f"{total} failed check(s)")
        out.append(note(name, f"{description}: {more}. {about}"))
        lines.append(f"  {name}: {more}")
    return out, pages, lines


def _pages_listed(pages, total, listed, shown=None):
    """The pages a rule's listed checks are on, as a finding or a line
    names them: ", pages 3, 10", the first shown of them, and how many
    more; ", the first 100 on pages 3, 10" when veraPDF listed fewer
    checks than failed; nothing without pages."""
    if not pages:
        return ""
    named = pages if shown is None else pages[:shown]
    words = ", ".join(str(page) for page in named) + (
        f", and {len(pages) - len(named)} more" if len(pages) > len(named) else "")
    where = f"page{'s' if len(pages) > 1 else ''} {words}"
    if total > listed:
        where = f"the first{'' if listed == 1 else f' {listed}'} on {where}"
    return f", {where}"


class _WcagContext:
    """What a PDF has where veraPDF's failed checks are, which veraPDF's
    report doesn't say, for --verbose: a link annotation's address (its
    check's context, .../pages[2]/annots[0]), and the line of text a
    check's box is on, for repeated characters, whose context names no
    text. Read with pypdf, the PDF opened when first asked; nothing where
    the PDF, or pypdf, can't say."""

    def __init__(self, path):
        self.path = path
        self.reader = None
        self.texts = {}

    def about(self, kind, item):
        """What the PDF has where the failed check is, or ""."""
        try:
            if kind == "SALinkAnnotation":
                found = re.search(r"/pages\[(\d+)\]/annots\[(\d+)\]",
                                  str(item.get("context") or ""))
                return self.link(int(found.group(1)), int(found.group(2))) if found else ""
            if kind == "SARepeatedCharacters":
                location = item.get("location")
                box = _list(_dict(json.loads(location) if isinstance(location, str)
                                  else location).get("bbox"))[0]
                line = self.line(int(box["p"]), [float(v) for v in box["rect"]])
                if line:
                    return f'on the line "{line[:117]}…"' if len(line) > 120 \
                        else f'on the line "{line}"'
        except Exception:                   # a page or an annotation the PDF hasn't
            return ""
        return ""

    def page(self, index):
        """The page, counted from 0; the PDF, once it can't be opened,
        isn't tried again for the next check."""
        if self.reader is None:
            self.reader = False
            self.reader = pypdf.PdfReader(self.path)
        if self.reader is False or index < 0:
            raise LookupError(index)
        return self.reader.pages[index]

    def link(self, page, number):
        """Where the link annotation goes: an address, or a place in the
        PDF; and its description (/Contents) when that isn't the address."""
        annotation = self.page(page)["/Annots"][number].get_object()
        action = annotation.get("/A")
        action = action.get_object() if action is not None else {}
        # Indexed, an indirect value is read where it's kept.
        address = action["/URI"] if "/URI" in action else None
        if address is not None:
            raw = getattr(address, "original_bytes", None)
            # A URI is UTF-8 in PDF 2.0, ASCII in 1.7; pypdf reads one
            # without a UTF-16 byte-order mark as PDFDocEncoding, which
            # garbles one outside ASCII.
            address = (bytes(raw).decode("utf-8", "replace")
                       if isinstance(raw, (bytes, bytearray))
                       and not bytes(raw).startswith((b"\xfe\xff", b"\xff\xfe"))
                       else _text(address))
        words = " ".join(_text(annotation["/Contents"] if "/Contents" in annotation
                               else None).split())
        said = f"the link to {address}" if address else "a link to a place in the PDF"
        if words and words != address:
            said += f', described as "{words[:80]}…"' if len(words) > 80 \
                else f', described as "{words}"'
        return said

    def line(self, page, rect):
        """The words of the line the box is on, in order across the page: the
        line of the run of text the box starts in, its baseline in the box's
        lower half, with what's raised or lowered on it (a subscript, a
        superscript, a footnote's mark) less than 0.4 of the box's height
        off, where the lines above and below are about its height away."""
        items = self.texts.get(page)
        if items is None:
            items, shown = [], []
            self.texts[page] = items            # a page pypdf can't read, read once

            def at(cm, tm):
                return (tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
                        tm[4] * cm[0] + tm[5] * cm[2] + cm[4])

            def before(operator, operands, cm, tm):
                if operator in (b"Tj", b"TJ"):
                    shown.append(at(cm, tm))

            def after(operator, operands, cm, tm):
                # ' and " move to the next line, then show: their run's
                # place is where the move left it.
                if operator in (b"'", b'"'):
                    shown.append(at(cm, tm))

            def visit(text, cm, tm, font, size):
                # A run's place is where its first show operator was:
                # around marked content, as a blank's Span is, pypdf gives
                # some runs none (the origin, 4.0.2 those after it, 5.9
                # those before), or the origin of a transformed page.
                if text:
                    y, x = shown[0] if shown else at(cm, tm)
                    items.append((y, x, text))
                shown.clear()
            try:
                self.page(page).extract_text(visitor_operand_before=before,
                                             visitor_operand_after=after, visitor_text=visit)
            except Exception:
                items.clear()                   # a page read partway is a page not read
                raise
        left, foot, top = min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[1], rect[3])
        near = [item for item in items if foot - 1 <= item[0] <= (foot + top) / 2]
        if not near:
            return ""
        started = [item for item in near if item[1] <= left + 1]
        base = (max(started, key=lambda item: item[1]) if started
                else min(near, key=lambda item: abs(item[0] - foot)))[0]
        off = max(2.0, 0.4 * (top - foot))
        words = " ".join("".join(text for y, x, text in sorted(
            (item for item in items if abs(item[0] - base) < off), key=lambda i: i[1])).split())
        # Spaces pypdf puts in: before a mark, and between the underscores
        # of a fill-in blank drawn shorter, to fit its line, overlapping.
        words = re.sub(r" ([.,;:!?])", r"\1", words)
        return re.sub(r"_(?: _){2,}", lambda run: run.group().replace(" ", ""), words)


def wcag_rule_line(name, rule, pages):
    """The summary's line for a rule a PDF failed: the criterion, how
    many checks failed, the pages of those veraPDF listed, which says
    so when it didn't list them all, and the Understanding document."""
    clause = str(rule.get("clause", ""))
    listed = len(_failed_checks(rule))
    total = max(_count(rule.get("failedChecks")), listed)
    where = _pages_listed(pages, total, listed, shown=8)
    description = str(rule.get("description") or "").strip().rstrip(".")
    return (f"{name}: verapdf-wcag:{clause}-{rule.get('testNumber', '')}, "
            f"{wcag.named(clause)}: {total} failed check(s){where}: {description}. "
            f"{wcag.url(clause)}")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _count(value):
    """A count from veraPDF's report, 0 for anything not a count."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return int(value) if isinstance(value, str) and value.isdigit() else 0


def _failed_checks(rule):
    return [item for item in _list(rule.get("checks"))
            if isinstance(item, dict) and item.get("status") == "failed"]


def _rule_key(name, rule):
    """A rule's place in the summary: its PDF, then its criterion's and
    its test's numbers, in order."""
    test = str(rule.get("testNumber", ""))
    return (name, [int(part) for part in re.findall(r"\d+", str(rule.get("clause", "")))],
            int(test) if test.isdigit() else 0, test)


def _task_exception(job):
    """What veraPDF says kept it from checking a file: its exception's
    message, from the dictionary its report gives one as."""
    said = job.get("taskException")
    if isinstance(said, dict):
        said = said.get("exceptionMessage") or said.get("exception") or said.get("type")
    return str(said or "no validation result")[:300]


def _same_file(name, path):
    return bool(name) and os.path.realpath(str(name)) == os.path.realpath(path)


def _wcag_failed(job):
    """Whether veraPDF found one of a WCAG profile's own rules failed in
    the job on an object of the semantic layer (SARepeatedCharacters, say),
    which it can only once its WCAG modules have loaded and built one."""
    results = job.get("validationResult")
    results = [results] if isinstance(results, dict) else _list(results)
    for profile in results:
        for rule in _list(_dict(_dict(profile).get("details")).get("ruleSummaries")):
            rule = _dict(rule)
            if str(rule.get("specification", "")).startswith("WCAG") \
                    and str(rule.get("object", "")).startswith("SA") \
                    and (rule.get("status") == "failed" or _count(rule.get("failedChecks"))):
                return True
    return False


def _wcag_page(item):
    """The page a failed check is on, counted from 1: the first its
    location's boxes are on (veraPDF counts from 0), or the page its
    context names, as an annotation's does (root/doc[0]/pages[2]/annots[0])."""
    location = item.get("location")
    if isinstance(location, str):
        try:
            location = json.loads(location)
        except ValueError:
            location = None
    if isinstance(location, dict):
        pages = [box.get("p") for box in _list(location.get("bbox"))
                 if isinstance(box, dict) and isinstance(box.get("p"), int)
                 and not isinstance(box.get("p"), bool) and box.get("p") >= 0]
        if pages:
            return min(pages) + 1
    found = re.search(r"/pages\[(\d+)\]", str(item.get("context") or ""))
    return int(found.group(1)) + 1 if found else None


def _wcag_said(item):
    """What veraPDF says of a failed check: its message, then the text
    the check was about and the structure element, when its context
    names them (…/children[2](14 0 obj P P)/children[0]{the text})."""
    context = str(item.get("context") or "")
    parts = [str(item.get("errorMessage") or "").strip()]
    text = re.search(r"\{([^{}]*)\}$", context)
    if text and text.group(1).strip():
        words = " ".join(text.group(1).split())
        parts.append(f'"{words[:80]}…"' if len(words) > 80 else f'"{words}"')
    said = ", ".join(part for part in parts if part)
    elements = re.findall(r"\((\d+) \d+ obj ([^()]*)\)", context)
    if elements and elements[-1][1].split():
        number, types = elements[-1]
        said += f" ({types.split()[-1]}, object {number})"
    return said.strip()
