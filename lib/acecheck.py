"""
acecheck.py -- DAISY's Ace (Ace by DAISY) on an EPUB, with --wcag, when
it's installed.

Ace checks an EPUB as a reading system meets it: axe-core on its content
documents, as --wcag does here, and checks of its own, on the package
(its language, its accessibility metadata) and in the content documents
(an epub:type without the ARIA role it maps to, a page break without a
label, the rules OWN_RULES names, which Ace adds to its copy of
axe-core). Its own checks are what's reported, each a note, as axe-core's
are; its axe-core results are counted and left out, since they're the
rules --wcag runs itself, in a browser locked down as Ace's isn't.

Ace isn't locked down: it runs a book's scripts, in a browser without
its sandbox, so it's for books one made, never for one a stranger sent,
and a web front end that checks uploads would leave it out. It needs
Node, and a browser: the ace command Ace's package installs runs
axe-core in Electron, which wants a display, and ace-puppeteer,
installed with it, in Puppeteer's headless Chrome, which
PUPPETEER_EXECUTABLE_PATH can name (Playwright's Chromium does). ACE
names the command to run; otherwise the first of COMMANDS on the path
is.

An audit keeps each EPUB's result, by its SHA-256, with Ace's version
and this file's, and runs Ace again only on an EPUB that has changed
(check's cache).

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

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import findings as findings_lib  # noqa: E402

VARIABLE = "ACE"
# Looked for on the path in this order: Puppeteer's headless Chrome first,
# which needs no display, then the command that runs Electron.
COMMANDS = ("ace-puppeteer", "ace-cli", "ace")
NOT_FOUND = ("Ace's checks not run: Ace by DAISY not found (set ACE, or put ace-puppeteer or "
             "ace on the path; docs/installation.md, Optional: Ace by DAISY).")
NOT_RUN_QUICK = "Ace's checks not run (--quick)."
NOT_RUN_NO_EPUB = "Ace's checks not run: no EPUB to check."
# The rules Ace adds to its copy of axe-core, which are its own.
OWN_RULES = ("epub-type-has-matching-role", "pagebreak-label")
# How long Ace has with an EPUB, in seconds: it took 150 with the 218
# content documents of the largest book tried.
TIMEOUT = 1800
# The elements a rule's line names, as axe-core's do.
SHOWN = 3
COLORS = re.compile(r"\x1b\[[0-9;]*m")


def find():
    """(command, why): the command to run Ace, as a list, ACE's (a .js
    file run with node) or the first of COMMANDS on the path; or None,
    and the summary's line saying why."""
    named = os.environ.get(VARIABLE, "").strip()
    if named:
        if not os.path.isfile(named):
            return None, f"Ace's checks not run: ACE is {named}, which isn't there."
        if named.endswith(".js"):
            node = shutil.which("node")
            if not node:
                return None, (f"Ace's checks not run: ACE is {named}, which needs Node, and "
                              "node isn't on the path.")
            return [node, named], ""
        return [named], ""
    for name in COMMANDS:
        found = shutil.which(name)
        if found:
            return [found], ""
    return None, NOT_FOUND


def version(command):
    """The version Ace says it is (--version), or ""."""
    try:
        said = subprocess.run(command + ["--version"], capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    found = re.match(r"\s*v?(\d+\.\d+\.\d+\S*)", said)
    return found.group(1) if found else ""


def said(result):
    """What Ace said of why it stopped: its last error line, else its
    last line."""
    lines = [COLORS.sub("", line).strip() for line in (result.stderr + "\n" + result.stdout)
             .splitlines()]
    errors = [line.split(":", 1)[1].strip() for line in lines if line.startswith("error:")]
    errors = [e.replace("Ace processing error: ", "", 1) for e in errors if e]
    if errors:
        return errors[-1][:300]
    lines = [line for line in lines if line and not line.startswith("Re-run Ace")]
    return lines[-1][:300] if lines else ""


def run(command, epub, timeout=TIMEOUT):
    """Ace's report on an EPUB, read (read_report), or {"error": why}."""
    with tempfile.TemporaryDirectory(prefix="ace-") as work:
        out = os.path.join(work, "report")
        try:
            result = subprocess.run(command + ["-o", out, "-t", os.path.join(work, "temp"),
                                               "-f", os.path.abspath(epub)],
                                    capture_output=True, text=True, timeout=timeout,
                                    stdin=subprocess.DEVNULL, cwd=work)
        except subprocess.TimeoutExpired:
            return {"error": f"it hadn't finished after {timeout} seconds, and was stopped"}
        except OSError as exc:
            return {"error": f"it didn't start ({exc})"}
        try:
            with open(os.path.join(out, "report.json"), encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError):
            why = said(result)
            return {"error": why or f"it ended with status {result.returncode} and wrote "
                                    "no report"}
    return read_report(report)


def read_report(report):
    """{"version", "own": its own findings, each {"rule", "document",
    "package", "impact", "message", "about", "help", "tags", "css"},
    "axe": {"rules", "elements"} for axe-core's, left out} from Ace's
    report.json. A content document is named by its path in the EPUB:
    Ace gives the package's so, and a content document's from the
    package's folder, or from the EPUB's root after a /."""
    release = (report.get("earl:assertedBy") or {}).get("doap:release") or {}
    documents = [d for d in report.get("assertions") or [] if isinstance(d, dict)]
    urls = [str((d.get("earl:testSubject") or {}).get("url") or "") for d in documents]
    folder = next((posixpath.dirname(u.lstrip("/")) for u in urls if u.endswith(".opf")), "")
    own, rules, elements = [], set(), 0
    for document, url in zip(documents, urls):
        package = url.endswith(".opf")
        path = url.lstrip("/") if url.startswith("/") or package else posixpath.normpath(
            posixpath.join(folder, url))
        for assertion in document.get("assertions") or []:
            if not isinstance(assertion, dict):
                continue
            test = assertion.get("earl:test") or {}
            result = assertion.get("earl:result") or {}
            rule = str(test.get("dct:title") or "?")
            css = [str(c) for c in (result.get("earl:pointer") or {}).get("css") or []]
            if str(assertion.get("earl:assertedBy") or "").lower() == "axe" \
                    and rule not in OWN_RULES:
                rules.add(rule)
                elements += 1
                continue
            own.append({"rule": rule, "document": path, "package": package,
                        "impact": str(test.get("earl:impact") or ""),
                        "message": " ".join(str(result.get("dct:description")
                                                or test.get("dct:description") or rule).split()),
                        "about": " ".join(str(test.get("dct:description") or "").split()),
                        "help": str((test.get("help") or {}).get("url") or ""),
                        "tags": [str(t) for t in test.get("rulesetTags") or []], "css": css})
    return {"version": str(release.get("doap:revision") or "?"), "own": own,
            "axe": {"rules": sorted(rules), "elements": elements}}


def standard(own):
    """The standard one of Ace's findings names: EPUB Accessibility's for
    its checks of an EPUB, else a best practice of Ace's."""
    return "EPUB Accessibility 1.1" if "EPUB" in own["tags"] else "Ace best practice"


def own_findings(result, epub, by_epub=False):
    """Ace's own findings on an EPUB, each a note: under the package's
    path or the content document's, and with by_epub filed under the
    EPUB, as an audit's are."""
    name = os.path.basename(epub)
    out = []
    for own in result.get("own") or []:
        at = f", at {', '.join(own['css'][:SHOWN])}" if own["css"] else ""
        detail = (f"{own['message']}" + (f" ({own['impact']})" if own["impact"] else "")
                  + f"{at}" + (f": {own['about']}" if own["about"] else "") + "."
                  + (f" Ace's rule: {own['help']}." if own["help"] else ""))
        out.append(findings_lib.Finding(own["document"], f"ace:{own['rule']}", detail,
                           file=name if by_epub else own["document"].split("/")[-1],
                           kind="epub", severity="note", standard=standard(own), tool="ace",
                           fix="manual"))
    return out


def setup_key(command, said_version):
    """What an EPUB's result turns on besides the EPUB: Ace, by its
    command and version, and this file."""
    with open(os.path.abspath(__file__), "rb") as fh:
        code = hashlib.sha256(fh.read()).hexdigest()
    where = os.path.realpath(command[-1])
    return hashlib.sha256(json.dumps([where, said_version, code]).encode("utf-8")).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(command, epubs, by_epub=False, cache=None, reuse=True, timeout=TIMEOUT):
    """(findings, lines) for Ace on the EPUBs: a note for each of its own
    findings, and the summary's lines, the first saying what ran, then a
    warning for each EPUB it didn't check, then one for each rule. With no
    EPUB, a probe of its own, which checks the setup. cache: a dict an
    audit keeps, each EPUB's result kept by its SHA-256 and, with reuse,
    used while the EPUB and Ace are the same."""
    if not epubs:
        return [], probe(command, timeout)
    said_version = version(command)
    stored = {}
    if cache is not None:
        setup = setup_key(command, said_version)
        if cache.get("setup") != setup:
            cache.clear()
            cache.update({"setup": setup, "epubs": {}})
        stored = cache.setdefault("epubs", {})
    found, failed, results, whens = [], [], [], set()
    when = findings_lib.now()
    for epub in epubs:
        sha = digest(epub) if cache is not None else None
        entry = stored.get(sha) if reuse and sha else None
        if entry:
            result = entry["result"]
            whens.add(entry["when"])
        else:
            result = run(command, epub, timeout)
            if "error" in result:
                failed.append((epub, result["error"]))
                continue
            if sha:
                stored[sha] = {"result": result, "when": when}
        results.append((epub, result, bool(entry)))
        found += own_findings(result, epub, by_epub)
    return found, summary(results, failed, said_version, whens, found)


def summary(results, failed, said_version, whens, found):
    """The summary's lines: what ran, what the cache kept, what wasn't
    checked, and a line for each of Ace's rules."""
    lines = []
    fresh = [r for r in results if not r[2]]
    held = [r for r in results if r[2]]
    left = sorted({rule for _, result, _ in results for rule in result["axe"]["rules"]})
    elements = sum(result["axe"]["elements"] for _, result, _ in results)
    named = next((result["version"] for _, result, _ in results), said_version) or "?"
    if results:
        lines.append(
            f"Ace by DAISY {named} "
            + (f"checked {len(fresh)} EPUB(s)" if fresh else "checked no EPUB again")
            + f": {len(found)} finding(s) of its own"
            + (f" on {len(results)} EPUB(s)" if held else "") + ", a note each, as axe-core's are"
            + (f"; its axe-core results, {elements} element(s) failing {len(left)} rule(s) "
               f"({', '.join(left[:5])}{', and more' if len(left) > 5 else ''}), are left "
               "out, since --wcag runs axe-core's rules itself" if left else "") + ".")
    if held:
        ordered = sorted(whens)
        one = len(ordered) == 1
        when = ordered[0] if one else f"{ordered[0]} to {ordered[-1]}"
        lines.append(f"{len(held)} EPUB(s) weren't checked again: each is unchanged since "
                     + ("the audit that checked it" if one else "the audits that checked them")
                     + f" ({when}), as Ace is, so their findings are "
                     + ("that audit's." if one else "those audits'."))
    for epub, why in failed:
        lines.append(f"WARNING: Ace didn't check {os.path.basename(epub)}: {why}.")
    groups = {}
    for finding in found:
        groups.setdefault(finding.check, []).append(finding)
    for check, group in sorted(groups.items()):
        first = group[0]
        lines.append(f"{check}, {first.standard}: {len(group)} finding(s), the first in "
                     f"{first.where}: {first.detail}")
    return lines


# --------------------------------------------------------------------------
# the probe: an EPUB of its own, which checks the setup
# --------------------------------------------------------------------------

PROBE_PACKAGE = (
    '<?xml version="1.0" encoding="UTF-8"?><package xmlns="http://www.idpf.org/2007/opf" '
    'version="3.0" unique-identifier="id" xml:lang="en"><metadata '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">urn:uuid:'
    '00000000-0000-4000-8000-000000000000</dc:identifier><dc:title>Ace probe</dc:title>'
    '<dc:language>en</dc:language><meta property="dcterms:modified">2026-01-01T00:00:00Z'
    '</meta></metadata><manifest><item id="nav" href="nav.xhtml" '
    'media-type="application/xhtml+xml" properties="nav"/></manifest><spine>'
    '<itemref idref="nav"/></spine></package>')
PROBE_NAV = (
    '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en"><head><title>Ace probe'
    '</title></head><body><nav epub:type="toc" role="doc-toc"><h1>Contents</h1><ol><li>'
    '<a href="nav.xhtml">Contents</a></li></ol></nav></body></html>')
# What the probe lacks, which Ace says.
PROBE_RULE = "metadata-accessmode"


def probe_epub(path):
    """The probe: an EPUB without its accessibility metadata."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", (
            '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:'
            'opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'))
        archive.writestr("EPUB/package.opf", PROBE_PACKAGE)
        archive.writestr("EPUB/nav.xhtml", PROBE_NAV)


def probe(command, timeout=TIMEOUT):
    """The summary's line for the probe: that Ace found what the probe
    lacks, or why not."""
    with tempfile.TemporaryDirectory(prefix="ace-probe-") as work:
        path = os.path.join(work, "probe.epub")
        probe_epub(path)
        result = run(command, path, timeout)
    if "error" in result:
        return [f"WARNING: Ace didn't check a probe EPUB of its own: {result['error']}."]
    rules = {own["rule"] for own in result["own"]}
    if PROBE_RULE not in rules:
        return [f"WARNING: Ace by DAISY {result['version']} checked a probe EPUB of its own, "
                f"and didn't find what it lacks ({PROBE_RULE}): it found "
                + (", ".join(sorted(rules)) or "nothing") + "."]
    return [f"Ace by DAISY {result['version']} checked a probe EPUB of its own and found what "
            f"it lacks ({PROBE_RULE}), so EPUBs can be checked: what it finds is a note, never "
            "a failure."]
