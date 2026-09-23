"""
findings.py -- one format for everything a check finds, and the two
things written from it: a CSV other tools can read, and a Markdown
report a person can.

A finding is where, which check, and what, as it has been since the
output check; and now also which file, what kind of thing that file is,
how bad it is, which standard it answers to, which tool said so, and
where the fix lives. The CSV's first three columns are the ones the
output check has always written, so nothing reading it today breaks;
the rest are added after them. A reader that zips known column names
against each row ignores what it doesn't know, which is the rule the
sidecars established.

The report's header lists every input with its SHA-256, size, tool
version, and the date, so a stale report says so; the same hashes key a
small cache that lets an unchanged input be skipped.

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

import csv
import datetime
import hashlib
import json
import os
from collections import Counter, OrderedDict

COLUMNS = ["Where", "Check", "Detail", "File", "Kind", "Severity",
           "Standard", "Tool", "Fix"]

SEVERITIES = ("error", "warning", "note")
KINDS = ("source-docx", "source-md", "html", "epub", "pdf")
FIXES = ("source", "sidecar", "manual", "tool", "none")

# What each check means, once. The output check's descriptions live
# here now too, so a report can explain a check and a CSV can carry the
# standard it answers to. A WCAG standard names the lowest 2.x version
# the success criterion appears in, its number, and its level; a PDF/UA
# one names the clause of ISO 14289-1. Severity and fix are the usual
# case; a finding may override them.
CHECKS = OrderedDict([
    # output: pages and EPUBs
    ("image-without-alt", ("an img element has no alt attribute",
                           "error", "WCAG 2.0 SC 1.1.1 (A)", "sidecar")),
    ("image-empty-alt-not-decorative",
     ("an img has alt=\"\" but is not marked decorative", "warning",
      "WCAG 2.0 SC 1.1.1 (A)", "sidecar")),
    ("image-alt-is-file-name",
     ("an img's alt only repeats its file name", "warning",
      "WCAG 2.0 SC 1.1.1 (A)", "sidecar")),
    ("no-lang", ("the html element declares no language", "error",
                 "WCAG 2.0 SC 3.1.1 (A)", "source")),
    ("no-title", ("the page has no title", "error", "WCAG 2.0 SC 2.4.2 (A)", "source")),
    ("duplicate-id", ("an id used more than once in one document", "error",
                      "HTML Living Standard", "tool")),
    ("invalid-id", ("an id containing whitespace, which no id may", "error",
                    "HTML Living Standard", "tool")),
    ("heading-skips-level", ("a heading level is skipped", "warning",
                             "WCAG 2.0 SC 1.3.1 (A)", "source")),
    ("table-without-headers-or-caption",
     ("a data table with no th and no caption", "warning", "WCAG 2.0 SC 1.3.1 (A)",
      "sidecar")),
    ("table-not-in-scroll-region",
     ("a data table outside the focusable scroll wrapper (HTML pages)",
      "warning", "WCAG 2.1 SC 1.4.10 (AA)", "tool")),
    ("link-to-missing-file", ("a link names a file that is not in the set",
                              "error", "WCAG 2.0 SC 2.4.4 (A)", "source")),
    ("link-to-missing-fragment", ("a link's #fragment matches no id",
                                  "error", "WCAG 2.0 SC 2.4.4 (A)", "source")),
    ("epub-manifest", ("the EPUB's manifest or spine is inconsistent",
                       "error", "EPUB 3.3", "tool")),
    ("epub-metadata", ("required EPUB metadata is missing", "error",
                       "EPUB 3.3", "source")),
    # source: what a Word or Markdown file says about itself
    ("source-image-no-alt", ("an image with no alt text and no decorative "
                             "marker", "error", "WCAG 2.0 SC 1.1.1 (A)", "source")),
    ("source-table-no-headers", ("a table with no header row, no marker, "
                                 "and no keying first column", "warning",
                                 "WCAG 2.0 SC 1.3.1 (A)", "sidecar")),
    ("source-table-headers-guessed",
     ("a table whose headers the census guessed; confirm in the sidecar",
      "note", "WCAG 2.0 SC 1.3.1 (A)", "sidecar")),
    ("source-table-no-caption", ("a data table with nothing to caption it",
                                 "warning", "WCAG 2.0 SC 1.3.1 (A)", "sidecar")),
    ("source-link-bare-url", ("a link whose text is its own URL", "note",
                              "WCAG 2.0 SC 2.4.4 (A)", "source")),
    ("source-heading-skips-level", ("a heading level is skipped", "warning",
                                    "WCAG 2.0 SC 1.3.1 (A)", "source")),
    ("source-raw-html", ("a raw HTML block the conversion passes through "
                         "unchanged", "note", "", "source")),
    ("source-math-trailing-space", ("math ending in a thin space, which "
                                    "cannot be written back as Markdown",
                                    "note", "", "source")),
    ("source-no-title", ("the document has no title", "warning",
                         "WCAG 2.0 SC 2.4.2 (A)", "source")),
    ("source-no-language", ("the document declares no language", "warning",
                            "WCAG 2.0 SC 3.1.1 (A)", "source")),
    # pdf: what the file states
    ("pdf-not-tagged", ("the PDF is not marked as tagged (no /MarkInfo "
                        "/Marked true), so it has no structure a screen "
                        "reader can use", "error", "PDF/UA-1 clause 7.1", "source")),
    ("pdf-no-structure-tree", ("the PDF has no structure tree", "error",
                               "PDF/UA-1 clause 7.1", "source")),
    ("pdf-no-title", ("the PDF has no title, or it isn't set to display",
                      "error", "PDF/UA-1 clause 7.1", "source")),
    ("pdf-no-language", ("the PDF declares no language", "error",
                         "PDF/UA-1 clause 7.2", "source")),
    ("pdf-no-outline", ("the PDF has no bookmark outline", "warning",
                        "PDF/UA-1 clause 7.17", "source")),
    ("pdf-no-xmp", ("the PDF has no XMP metadata", "note", "", "source")),
    ("pdf-pages-without-text", ("pages with no extractable text, which "
                                "are scans or images of text", "error",
                                "WCAG 2.0 SC 1.4.5 (AA)", "manual")),
    ("pdf-fonts-not-embedded", ("fonts the PDF uses but does not embed",
                                "warning", "PDF/UA-1 clause 7.21", "source")),
    ("pdf-encrypted", ("the PDF is encrypted, which may block assistive "
                       "technology", "warning", "PDF/UA-1 clause 7.1", "source")),
    ("pdf-claims-unverified", ("the PDF claims a conformance level; only a "
                               "validator can confirm it", "note", "",
                               "tool")),
    ("pdf-unreadable", ("the file could not be read as a PDF", "error", "",
                        "manual")),
    # tools
    ("vnu:error", ("the Nu HTML checker reported an error", "error",
                   "HTML Living Standard", "tool")),
    ("vnu:warning", ("the Nu HTML checker reported a warning", "warning",
                     "HTML Living Standard", "tool")),
    ("vnu:failed", ("the Nu HTML checker could not run", "note", "", "tool")),
    ("epubcheck:failed", ("epubcheck could not run", "note", "", "tool")),
    ("verapdf:failed", ("veraPDF could not run", "note", "", "tool")),
])


class Finding:
    """One thing found. The first three fields are what the output
    check has always recorded; the rest say more about it."""

    __slots__ = ("where", "check", "detail", "file", "kind", "severity",
                 "standard", "tool", "fix")

    def __init__(self, where, check, detail, file="", kind="",
                 severity=None, standard=None, tool="oer", fix=None):
        self.where, self.check, self.detail = where, check, detail
        self.file, self.kind, self.tool = file, kind, tool
        meaning = CHECKS.get(check)
        if meaning is None and check.startswith("epubcheck:"):
            meaning = ("epubcheck reported " + check.split(":", 1)[1],
                       "error", "EPUB 3.3", "tool")
        if meaning is None and check.startswith("verapdf:"):
            meaning = ("veraPDF reported " + check.split(":", 1)[1],
                       "error", "PDF/UA (veraPDF)", "source")
        self.severity = severity or (meaning[1] if meaning else "warning")
        self.standard = standard if standard is not None else (
            meaning[2] if meaning else "")
        self.fix = fix or (meaning[3] if meaning else "manual")

    def row(self):
        return [self.where, self.check, self.detail, self.file, self.kind,
                self.severity, self.standard, self.tool, self.fix]


def describe(check):
    """What a check means, in a sentence."""
    meaning = CHECKS.get(check)
    if meaning:
        return meaning[0]
    if check.startswith("epubcheck:"):
        return "epubcheck message " + check.split(":", 1)[1]
    if check.startswith("verapdf:"):
        return "veraPDF rule " + check.split(":", 1)[1]
    return check


def upgrade(finding):
    """A three-field Finding from outputcheck, as a full one."""
    if isinstance(finding, Finding):
        return finding
    return Finding(finding.where, finding.check, finding.detail)


# --------------------------------------------------------------------------
# inputs: hashes, and the cache that skips an unchanged one
# --------------------------------------------------------------------------

def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe_input(path):
    return {"path": path, "sha256": digest(path),
            "bytes": os.path.getsize(path)}


class Cache:
    """audit-cache.json: input hash -> the findings last written for it,
    so an unchanged input is not checked again unless asked."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def lookup(self, sha256):
        entry = self.data.get(sha256)
        if not entry or sha256 == "__report__":
            return None
        out = []
        for r in entry.get("findings", []):
            r = list(r) + [""] * (len(COLUMNS) - len(r))
            out.append(Finding(r[0], r[1], r[2], file=r[3], kind=r[4],
                               severity=r[5] or None, standard=r[6],
                               tool=r[7] or "oer", fix=r[8] or None))
        return out

    def store(self, sha256, findings):
        self.data[sha256] = {"findings": [f.row() for f in findings],
                             "when": now()}

    def note_inputs(self, hashes):
        """Which inputs the last report covered, and when."""
        self.data["__report__"] = {"inputs": sorted(hashes), "when": now()}

    def same_inputs(self, hashes):
        report = self.data.get("__report__") or {}
        return report.get("inputs") == sorted(hashes)

    def audited_at(self):
        return (self.data.get("__report__") or {}).get("when", "?")

    def save(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1)


def now():
    return datetime.datetime.now().astimezone().replace(
        microsecond=0).isoformat()


# --------------------------------------------------------------------------
# what is written
# --------------------------------------------------------------------------

def write_csv(path, findings):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for f in findings:
            writer.writerow(upgrade(f).row())


def read_csv(path):
    """Findings back from a CSV, ours or an older three-column one."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, None) or []
        out = []
        for row in reader:
            values = dict(zip(header, row))
            out.append(Finding(
                values.get("Where", ""), values.get("Check", ""),
                values.get("Detail", ""), file=values.get("File", ""),
                kind=values.get("Kind", ""),
                severity=values.get("Severity") or None,
                standard=values.get("Standard"),
                tool=values.get("Tool") or "oer",
                fix=values.get("Fix") or None))
        return out


def summary_lines(findings):
    """The counts a person reads first."""
    findings = [upgrade(f) for f in findings]
    by_severity = Counter(f.severity for f in findings)
    by_check = Counter(f.check for f in findings)
    lines = []
    if not findings:
        return ["Nothing found."]
    parts = [f"{by_severity[s]} {s}{'s' if by_severity[s] != 1 else ''}"
             for s in SEVERITIES if by_severity[s]]
    lines.append(f"{len(findings)} finding(s): " + ", ".join(parts) + ".")
    lines.append("")
    for check, count in by_check.most_common():
        lines.append(f"- `{check}` ×{count}: {describe(check)}")
    return lines


def render_html(markdown_path, html_path, css_path=None):
    """The report as a page, through Pandoc, with the pipeline's own
    stylesheet embedded when it is given."""
    import subprocess
    import sys
    command = ["pandoc", os.path.abspath(markdown_path),
               "-o", os.path.abspath(html_path), "--standalone",
               "--metadata", "lang=en", "--metadata", "pagetitle=Audit"]
    if css_path and os.path.exists(css_path):
        command += ["--css", os.path.abspath(css_path), "--embed-resources"]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"audit.html not written: {detail.strip()[:200]}",
              file=sys.stderr)


def render_docx(markdown_path, docx_path, compat_tool=None):
    """The report as a Word document, through Pandoc, then declared as
    the current Word format so Word treats it as a current file and its
    own Accessibility Checker runs on it (Pandoc's reference document
    carries no compatibility mode; see util/docx-compat.py)."""
    import subprocess
    import sys
    try:
        subprocess.run(["pandoc", os.path.abspath(markdown_path), "-o",
                        os.path.abspath(docx_path), "--metadata",
                        "lang=en"], check=True, capture_output=True,
                       text=True)
        if compat_tool and os.path.exists(compat_tool):
            subprocess.run([sys.executable, compat_tool, "--set", "15",
                            os.path.abspath(docx_path)], check=True,
                           capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"audit.docx not written: {detail.strip()[:200]}",
              file=sys.stderr)


def write_report(path, findings, inputs, sections=None, version="",
                 title="Accessibility audit"):
    """A Markdown report: the header that dates and hashes it, the
    summary, the findings by file, then any sections a checker wants to
    add (a PDF's metadata, say) as (heading, lines) pairs."""
    findings = [upgrade(f) for f in findings]
    out = [f"# {title}", ""]
    out.append(f"Produced {now()}" + (f" by TextbookImprover {version}"
                                      if version else "") + ".")
    out.append("")
    out.append("## Inputs")
    out.append("")
    for item in inputs:
        out.append(f"- `{item['path']}` — {item['bytes']:,} bytes, "
                   f"SHA-256 `{item['sha256'][:16]}…`")
    out.append("")
    out.append("The hashes say which files this report is about; if a "
               "file's hash has changed, the report is stale for it.")
    out.append("")
    out.append("## Summary")
    out.append("")
    out += summary_lines(findings)
    out.append("")
    by_file = OrderedDict()
    for f in findings:
        by_file.setdefault(f.file or f.where.split("#")[0], []).append(f)
    if findings:
        out.append("## Findings")
        out.append("")
        for file, items in by_file.items():
            out.append(f"### {file}")
            out.append("")
            for f in items:
                where = f" at `{f.where}`" if f.where and f.where != file \
                    else ""
                tail = []
                if f.standard:
                    tail.append(f.standard)
                if f.fix and f.fix != "none":
                    tail.append(f"fix: {f.fix}")
                if f.tool and f.tool != "oer":
                    tail.append(f"by {f.tool}")
                out.append(f"- **{f.severity}** `{f.check}`{where}: "
                           f"{f.detail}" + (f" ({'; '.join(tail)})" if tail
                                            else ""))
            out.append("")
    for heading, lines in (sections or []):
        out.append(f"## {heading}")
        out.append("")
        out += lines
        out.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out).rstrip("\n") + "\n")
