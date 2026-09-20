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

import os
import re
import subprocess
from collections import Counter

from findings import Finding, describe_input

try:
    import pypdf
except ImportError:                     # reported, not fatal
    pypdf = None


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


def _walk_structure(node, counts, depth=0, seen=0):
    """Count structure elements by type, a bounded walk."""
    if seen > 20000 or depth > 200:
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
        seen = _walk_structure(kid, counts, depth + 1, seen)
    return seen


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
                           "python3-pypdf)", file=name, kind="pdf"))
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
    if tree is not None:
        _walk_structure(tree, counts)
    facts["structure-tree"] = tree is not None
    facts["tags"] = dict(counts.most_common(12))
    facts["tag-total"] = sum(counts.values())
    facts["tag-total-capped"] = facts["tag-total"] >= 20000
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
            for _, font in (resources.get("/Font") or {}).items():
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


def run_verapdf(command, path):
    """veraPDF's failed rules as findings, when it is installed. Its
    profile is chosen by the file's own claim, PDF/UA-2 if it makes one,
    else PDF/UA-1, since a PDF that claims nothing is still judged by
    the accessibility profile."""
    name = os.path.basename(path)
    try:
        result = subprocess.run(command + ["--format", "text", path],
                                capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Finding(name, "verapdf:failed", str(exc)[:200], file=name,
                        kind="pdf")]
    out = []
    for line in result.stdout.splitlines():
        m = re.match(r"\s*FAIL\s+(\S+)\s*(.*)", line)
        if m:
            out.append(Finding(name, "verapdf:" + m.group(1),
                               m.group(2).strip()[:200], file=name,
                               kind="pdf", tool="verapdf"))
    return out
