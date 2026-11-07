"""
fakeace.py -- a stand-in for DAISY's Ace, so the suites can check what
the output check and the audit make of its report without Node or a
browser, wherever they run.

install(folder) writes the stand-in, an executable that ACE can name.
It answers as Ace 1.4.6 does, in its report.json's shape: --version
prints its version; given -o OUT and an EPUB, it writes OUT/report.json,
with an assertion of Ace's own on the package when the package document
has no schema:accessMode (metadata-accessmode), and on each content
document an assertion of axe-core's for each picture without an alt
attribute (image-alt) and one of Ace's own rule for each element with an
epub:type and no role (epub-type-has-matching-role), as Ace's copy of
axe-core asserts them. It names a content document from the package's
folder, as Ace does, but the navigation document, from the EPUB's root
after a /. FAKE_ACE_FAIL, set, has it write Ace's error for a browser it
can't find, and end with 1, as Ace does; FAKE_ACE_BLIND, set, has it
find nothing of its own on the package; FAKE_ACE_LOG names a file each
run appends its arguments to, as a line of JSON.

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
import sys

VERSION = "1.4.6"

SCRIPT = r'''
import json
import os
import posixpath
import re
import sys
import zipfile

args = sys.argv[1:]
log = os.environ.get("FAKE_ACE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(args) + "\n")
if args == ["--version"]:
    print(VERSION)
    sys.exit(0)
blind = bool(os.environ.get("FAKE_ACE_BLIND"))
if os.environ.get("FAKE_ACE_FAIL"):
    sys.stderr.write("\x1b[31merror\x1b[39m:   Ace processing error: Could not find Chrome "
                     "(ver. 148.0.7778.97). This can occur if either\n")
    print("Re-run Ace using the --verbose option to enable full debug logging.")
    sys.exit(1)
out = args[args.index("-o") + 1]
epub = args[-1]


def test(by, rule, impact, message, about, tags, css=None):
    result = {"earl:outcome": "fail", "dct:description": message}
    if css:
        result["earl:pointer"] = {"cfi": ["/4/2"], "css": [css]}
    return {"@type": "earl:assertion", "earl:result": result, "earl:assertedBy": by,
            "earl:mode": "automatic",
            "earl:test": {"earl:impact": impact, "dct:title": rule, "dct:description": about,
                          "help": {"url": "http://kb.daisy.org/publishing/docs/",
                                   "dct:title": rule, "dct:description": about},
                          "rulesetTags": tags}}


with zipfile.ZipFile(epub) as archive:
    container = archive.read("META-INF/container.xml").decode("utf-8")
    package = re.search(r'full-path="([^"]+)"', container).group(1)
    opf = archive.read(package).decode("utf-8")
    folder = posixpath.dirname(package)
    documents = [{"@type": "earl:assertion", "earl:testSubject": {"url": package},
                  "earl:result": {"earl:outcome": "pass"}, "assertions": []}]
    if "schema:accessMode" not in opf and not blind:
        documents[0]["assertions"].append(test(
            "Ace", "metadata-accessmode", "serious",
            "Publications must declare the 'schema:accessMode' metadata",
            "Ensures a 'schema:accessMode' metadata is present", ["EPUB"]))
    for item in re.findall(r"<item\b[^>]*>", opf):
        href = re.search(r'href="([^"]+)"', item).group(1)
        if not href.endswith(".xhtml"):
            continue
        text = archive.read(posixpath.join(folder, href)).decode("utf-8")
        url = "/" + posixpath.join(folder, href) if 'properties="nav"' in item else href
        found = []
        for img in re.findall(r"<img\b[^>]*>", text):
            if "alt=" not in img:
                found.append(test("aXe", "image-alt", "critical",
                                  "Element does not have an alt attribute",
                                  "Ensures <img> elements have alternate text",
                                  ["wcag2a", "wcag111"], "img"))
        for element in re.findall(r"<(\w+)\b([^>]*\bepub:type=[^>]*)>", text):
            if "role=" not in element[1]:
                found.append(test("aXe", "epub-type-has-matching-role", "moderate",
                                  "Element has no ARIA role matching its epub:type",
                                  "Ensure the element has an ARIA role matching its epub:type",
                                  ["cat.aria", "best-practice"], element[0]))
        documents.append({"@type": "earl:assertion", "earl:testSubject": {"url": url},
                          "earl:result": {"earl:outcome": "fail" if found else "pass"},
                          "assertions": found})
for document in documents:
    if document["assertions"]:
        document["earl:result"]["earl:outcome"] = "fail"
os.makedirs(out, exist_ok=True)
report = {"@type": "earl:report", "dct:title": "Ace Report",
          "earl:assertedBy": {"@type": "earl:software", "doap:name": "DAISY Ace",
                              "doap:release": {"doap:revision": VERSION}},
          "earl:testSubject": {"url": epub}, "assertions": documents,
          "earl:result": {"earl:outcome": "fail" if any(d["assertions"] for d in documents)
                          else "pass"}}
with open(os.path.join(out, "report.json"), "w", encoding="utf-8") as fh:
    json.dump(report, fh)
'''


def install(folder):
    """The stand-in's path, written into the folder."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "ace-puppeteer")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\nVERSION = {VERSION!r}\n" + SCRIPT)
    os.chmod(path, 0o755)
    return path
