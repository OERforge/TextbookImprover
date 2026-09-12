#!/usr/bin/env python3
"""
compare-output.py -- compare two runs of the conversion semantically,
ignoring the cosmetic churn that a byte comparison drowns in.

    compare-output.py before/ after/          # compare two output trees
    compare-output.py before/ after/ --json baseline.json
    compare-output.py baseline.json after/    # compare against a saved run
    compare-output.py out/ out2/ --idempotent # expect zero differences

Changing how a document reaches HTML -- a different intermediate format, a
different pandoc version, a reordered filter -- rewrites almost every byte
of the output while usually meaning nothing. Column widths get recomputed,
whitespace moves, entities encode differently. Running `diff` on two such
trees reports every file and tells you nothing.

This reduces each page to a signature of the things that carry meaning:
the title, the heading outline, the shape of every table and the header
markup on it, the figures, the images and their alt text. Two pages with
the same signature are the same page for accessibility purposes, however
different their bytes. Anything that does differ is reported by field, so
a noisy field can be silenced with --ignore once you have decided it does
not matter.

It also compares the sidecar reports the Lua filter writes. Those are
headerless CSVs whose Source column holds a filename, and that filename
changes when the intermediate format changes, so any cell that looks like
a file reference is reduced to its stem before comparing. Pass --raw-csv
to compare them literally instead.

Media gets the same treatment. Every file that is not a page or a report
is inventoried by path-without-extension and by content, so correcting an
image's extension reads as a rename rather than as one file lost and
another gained, and a file whose bytes changed is distinguished from one
that merely moved.

Every reference in every page is then resolved against that inventory, in
three separate buckets. Media -- the src of an img, embed, or object --
fails when a file is missing or misnamed, which is what the media handling
in convert.sh exists to prevent. Page links -- an href to another page of
the same book -- fail when the book does not hold together, usually a
naming or outline problem rather than a conversion one. Asset links -- an
href or src pointing at a stylesheet, a script, a PDF -- fail on their
own terms. They are counted and reported apart because rolling them into
one number hides all three. External URLs and same-page fragments are
counted but not resolved, since neither is this script's to check.

A page that carries an <embed> instead of an <img> -- what pandoc writes
when it cannot tell an image's type -- is reported in its own field,
because such a page validates cleanly and shows nothing.

Exit status is 0 when the two runs agree and 1 when they do not, so this
can gate a commit.

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

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from html.parser import HTMLParser
from urllib.parse import unquote

HTML_SUFFIXES = (".html", ".htm", ".xhtml")

# src values that name something other than a file in this run. Kept in
# step with the same list in build-cartridge.py.
EXTERNAL = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#")

# Elements whose text we capture rather than skip.
TEXT_ELEMENTS = {"title", "caption", "figcaption",
                 "h1", "h2", "h3", "h4", "h5", "h6"}

# Fields compared loosely rather than exactly. See within_tolerance.
TOLERANT_FIELDS = {"word_count"}

# A difference of this many words or fewer is never reported, whatever the
# percentage. Without it a short page is held to an unreasonably fine
# standard: three words is a rounding error on a chapter and two percent
# of a review-questions page.
WORD_FLOOR = 5

# Elements whose text is machinery rather than reading matter.
SKIP_ELEMENTS = {"head", "script", "style"}

# Elements that never have an end tag, so they must not touch the stacks.
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

# Extensions that mark a CSV cell as a file reference rather than prose.
# Cells matching these are compared by stem, because the same document is
# called 1-1-foo.docx, 1-1-foo.md, or 1-1-foo.html depending on which
# stage of which pipeline wrote the row.
PATH_SUFFIXES = (".docx", ".md", ".markdown", ".html", ".htm", ".xhtml",
                 ".tex", ".epub", ".json", ".png", ".jpg", ".jpeg", ".gif",
                 ".svg", ".webp", ".tif", ".tiff", ".bmp", ".so", ".emf",
                 ".wmf", ".pdf")

# Curly punctuation folded to ASCII under --fold-quotes. A document that
# went through a Markdown intermediate and one that did not can disagree
# about these without any editorial difference.
FOLD = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "--", "\u2026": "...", "\u00a0": " ",
}


def normalise_text(text, fold=False):
    """Collapse whitespace, and optionally fold curly punctuation."""
    if fold:
        for char, plain in FOLD.items():
            text = text.replace(char, plain)
    return " ".join(text.split())


def split_fragment(value):
    """Separate a trailing #anchor from a file reference."""
    if "#" in value:
        path, _, fragment = value.partition("#")
        return path, "#" + fragment
    return value, ""


def stem_of(value):
    """Reduce a file reference to its bare stem, keeping any anchor.

    media/rId35.so, /books/econ/10-problems.docx, and 10-problems.md become
    rId35 and 10-problems, so a row survives both a change of intermediate
    format and a change of working directory. The anchor is kept because
    the filter uses it to tell one unlabelled table in a document from the
    next: 10-problems.md#table-6 and 10-problems.docx#table-6 must agree,
    but neither may collapse into plain 10-problems.
    """
    path, fragment = split_fragment(value)
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    root, ext = os.path.splitext(base)
    return (root if ext else base) + fragment


def looks_like_path(value):
    """True when a CSV cell names a file rather than holding prose."""
    if not value or " " in value.strip():
        return False
    path, _fragment = split_fragment(value)
    return "/" in path or path.lower().endswith(PATH_SUFFIXES)


# --------------------------------------------------------------------------
# reading a page
# --------------------------------------------------------------------------

class PageParser(HTMLParser):
    """Collect a semantic signature from one HTML page.

    Everything recorded here is something a change to the pipeline could
    plausibly break in a way that matters. Presentation is deliberately
    absent: no widths, no styles, no class names, no element order beyond
    the heading outline.
    """

    def __init__(self, fold=False):
        super().__init__(convert_charrefs=True)
        self.fold = fold
        self.lang = ""
        self.title = ""
        self.headings = []          # (level, text)
        self.tables = []            # innermost-last while open
        self.finished_tables = []
        self.figures = 0
        self.figcaptions = 0
        self.images = []            # (src, stem, extension, alt or None)
        self.embeds = []            # src values
        self.links = []             # (kind, href) for a/link/script
        self.math = 0
        self._capture = []          # stack of (name, buffer)
        self._table_stack = []
        self._table_seq = 0
        self.words = 0
        self._skip_depth = 0

    # -- text capture ------------------------------------------------------

    def _start_capture(self, name):
        self._capture.append((name, []))

    def _end_capture(self):
        if not self._capture:
            return None, ""
        name, buf = self._capture.pop()
        return name, normalise_text("".join(buf), self.fold)

    def handle_data(self, data):
        if self._capture:
            self._capture[-1][1].append(data)
        # A coarse count of visible words. Structure comparison alone would
        # not notice a filter that dropped a document's prose, and a count
        # is insensitive to the rewrapping and re-encoding that make a
        # character-level comparison useless here.
        if not self._skip_depth:
            self.words += len(data.split())

    # -- elements ----------------------------------------------------------

    def handle_startendtag(self, tag, attrs):
        # Do not let a self-closing tag push and pop the stacks.
        self.handle_starttag(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)

        if tag in SKIP_ELEMENTS:
            self._skip_depth += 1
        if tag == "html":
            self.lang = attr.get("lang", "")
        elif tag == "img":
            src = attr.get("src", "")
            _, ext = os.path.splitext(src)
            self.images.append(
                (src, stem_of(src), ext.lower(), attr.get("alt")))
            return
        elif tag == "a":
            if attr.get("href"):
                self.links.append(("a", attr["href"]))
        elif tag in ("link", "script"):
            # <link> covers stylesheets and the like; <script src> is the
            # same kind of dependency and costs nothing to include.
            href = attr.get("href") or attr.get("src")
            if href:
                self.links.append((tag, href))
        elif tag in ("embed", "object"):
            # Pandoc writes <embed> rather than <img> when it cannot tell
            # an image's type, which is what a media file left with the
            # wrong extension produces. The page validates and the picture
            # does not appear, so this is worth its own field.
            src = attr.get("src") or attr.get("data")
            if src:
                self.embeds.append(src)
            return
        elif tag == "figure":
            self.figures += 1
        elif tag == "math":
            self.math += 1
        elif tag == "table":
            # Numbered on the way in, not on the way out, so that a nested
            # table does not take the outer table's place in the report.
            self._table_seq += 1
            self._table_stack.append({
                "_order": self._table_seq,
                "rows": 0, "cols": 0, "th": 0, "td": 0, "thead_rows": 0,
                "colspan": 0, "rowspan": 0, "caption": "",
                "scope": Counter(), "headers_attr": 0, "cell_ids": 0,
                "role": attr.get("role", ""), "_in_thead": False,
                "_row_cols": 0,
            })
            return
        elif tag in ("thead", "tr", "th", "td") and self._table_stack:
            self._cell_or_row(tag, attr)
            return

        if tag in TEXT_ELEMENTS:
            self._start_capture(tag)

    def _cell_or_row(self, tag, attr):
        table = self._table_stack[-1]
        if tag == "thead":
            table["_in_thead"] = True
        elif tag == "tr":
            table["rows"] += 1
            table["_row_cols"] = 0
            if table["_in_thead"]:
                table["thead_rows"] += 1
        else:
            span = self._int(attr.get("colspan"), 1)
            rows = self._int(attr.get("rowspan"), 1)
            table["th" if tag == "th" else "td"] += 1
            table["colspan"] += span - 1
            table["rowspan"] += rows - 1
            table["_row_cols"] += span
            table["cols"] = max(table["cols"], table["_row_cols"])
            if attr.get("scope"):
                table["scope"][attr["scope"]] += 1
            if attr.get("headers"):
                table["headers_attr"] += 1
            if attr.get("id"):
                table["cell_ids"] += 1

    @staticmethod
    def _int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def handle_endtag(self, tag):
        if tag in SKIP_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "thead" and self._table_stack:
            self._table_stack[-1]["_in_thead"] = False
            return
        if tag == "table" and self._table_stack:
            table = self._table_stack.pop()
            for key in ("_in_thead", "_row_cols"):
                table.pop(key, None)
            table["scope"] = dict(table["scope"])
            self.finished_tables.append(table)
            return
        if tag == "figcaption":
            self.figcaptions += 1

        if tag in TEXT_ELEMENTS and self._capture:
            name, text = self._end_capture()
            if name != tag:
                return
            if tag == "title":
                self.title = text
            elif tag == "caption" and self._table_stack:
                self._table_stack[-1]["caption"] = text
            elif tag[0] == "h" and len(tag) == 2 and tag[1].isdigit():
                self.headings.append((int(tag[1]), text))


def signature(path, fold=False):
    """Reduce one HTML file to an ordered dict of comparable fields."""
    return read_page(path, fold=fold)[0]


def read_page(path, fold=False):
    """Return (signature, list of src values) for one HTML file.

    The raw src values are kept out of the signature -- they are too noisy
    to compare directly -- but are needed to check every reference against
    what is actually on disk.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        parser = PageParser(fold=fold)
        parser.feed(handle.read())
        parser.close()
    parser.finished_tables.sort(key=lambda t: t.pop("_order"))

    sig = OrderedDict()
    sig["title"] = parser.title
    sig["lang"] = parser.lang
    sig["h1_count"] = sum(1 for level, _ in parser.headings if level == 1)
    sig["h1_text"] = " | ".join(t for lv, t in parser.headings if lv == 1)
    # The outline catches a heading that changed level or went missing
    # without listing every heading's text, which would be pure noise.
    sig["heading_outline"] = ",".join(str(lv) for lv, _ in parser.headings)
    sig["heading_count"] = len(parser.headings)
    sig["word_count"] = parser.words
    sig["figure_count"] = parser.figures
    sig["figcaption_count"] = parser.figcaptions
    sig["math_count"] = parser.math
    sig["img_count"] = len(parser.images)
    sig["embed_count"] = len(parser.embeds)
    buckets = Counter(classify_link(href) for _kind, href in parser.links)
    for bucket in ("page", "asset", "external", "fragment"):
        sig["link_%s_count" % bucket] = buckets.get(bucket, 0)
    # Stems and extensions are separate fields so that renaming media to
    # its real content type shows up in one place instead of looking like
    # every image changed.
    sig["img_stems"] = " ".join(stem for _, stem, _, _ in parser.images)
    sig["img_extensions"] = " ".join(sorted(
        {ext for _, _, ext, _ in parser.images}))
    sig["img_alt_missing"] = sum(
        1 for _, _, _, alt in parser.images if alt is None)
    sig["img_alt_empty"] = sum(
        1 for _, _, _, alt in parser.images
        if alt is not None and not alt.strip())
    sig["table_count"] = len(parser.finished_tables)
    for index, table in enumerate(parser.finished_tables, start=1):
        for key in ("rows", "cols", "th", "td", "thead_rows", "colspan",
                    "rowspan", "headers_attr", "cell_ids", "role", "caption"):
            sig["table[%d].%s" % (index, key)] = table[key]
        sig["table[%d].scope" % index] = " ".join(
            "%s=%d" % (k, v) for k, v in sorted(table["scope"].items()))
    return (sig,
            [src for src, _, _, _ in parser.images] + parser.embeds,
            parser.links)


# --------------------------------------------------------------------------
# reading a run
# --------------------------------------------------------------------------

def relative(path, root):
    """Path relative to the run root, with forward slashes."""
    return os.path.relpath(path, root).replace(os.sep, "/")


def digest_of(path):
    """SHA-256 of a file, read in chunks so a large image costs nothing."""
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def collect_files(root, hash_content=True):
    """Inventory every file that is not a page or a report.

    Keyed by path-without-extension relative to the run root, because that
    is what survives the rename this pipeline exists to perform: media
    extracted as 1-1-foo/media/rId26.so and later corrected to .png is the
    same image in the same place, and should read as a renamed file rather
    than as one file lost and another gained.
    """
    files = {}
    for base, _dirs, names in os.walk(root):
        for name in sorted(names):
            lowered = name.lower()
            if lowered.endswith(HTML_SUFFIXES) or lowered.endswith(".csv"):
                continue
            path = os.path.join(base, name)
            if not os.path.isfile(path):
                continue
            key, ext = os.path.splitext(relative(path, root))
            entry = {"ext": ext.lower(), "size": os.path.getsize(path)}
            if hash_content:
                entry["digest"] = digest_of(path)
            if key in files:
                # Two files differing only in extension: exactly the state
                # an interrupted rename leaves behind, so say so rather
                # than silently keeping one.
                files[key].setdefault("duplicates", []).append(entry["ext"])
                continue
            files[key] = entry
    return files


def resolve_reference(src, page_path, root):
    """Turn an src attribute into a key comparable with collect_files.

    Returns None for anything that is not a local file: an absolute URL, a
    data URI, a bare fragment. Those are not this script's business, the
    same distinction convert.sh draws when it anchors its media search to
    the document's own extraction directory.
    """
    src = src.strip()
    if not src or src.lower().startswith(EXTERNAL):
        return None
    src = src.split("#", 1)[0].split("?", 1)[0]
    if not src:
        return None
    src = unquote(src)
    target = os.path.normpath(
        os.path.join(os.path.dirname(page_path), src))
    key, _ext = os.path.splitext(relative(target, root))
    return key


def classify_link(href):
    """Sort one href into a bucket without resolving it.

    external   an absolute URL or a scheme this run does not own
    fragment   a link within the same page
    page       a link to another page of the same book
    asset      a link to a stylesheet, a PDF, an image, anything else
    """
    href = href.strip()
    if not href:
        return None
    if href.startswith("#"):
        return "fragment"
    if href.lower().startswith(EXTERNAL):
        return "external"
    path = href.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return "fragment"
    _root, ext = os.path.splitext(path)
    if not ext or ext.lower() in HTML_SUFFIXES:
        return "page"
    return "asset"


def collect(root, fold=False):
    """Return (signatures, references) for every HTML page under root.

    Signatures are keyed by page stem. References map each page stem to
    the keys it points at, resolved relative to the page's own directory,
    split by kind: media a page displays, pages it links to, and other
    assets it depends on. They are kept apart because a broken image and a
    broken link to the next section are different problems with different
    fixes, and rolling them into one count hides both.

    page_keys is every page's own key, so a link between pages can be
    checked without confusing it with a file on disk.
    """
    pages, references, page_keys = {}, {}, set()
    for base, _dirs, names in os.walk(root):
        for name in sorted(names):
            if not name.lower().endswith(HTML_SUFFIXES):
                continue
            path = os.path.join(base, name)
            stem = os.path.splitext(name)[0]
            if stem in pages:
                sys.stderr.write(
                    "warning: two pages named %s under %s; keeping the first\n"
                    % (stem, root))
                continue
            sig, srcs, links = read_page(path, fold=fold)
            pages[stem] = sig
            page_keys.add(os.path.splitext(relative(path, root))[0])

            found = {"media": set(), "page": set(), "asset": set()}
            for src in srcs:
                key = resolve_reference(src, path, root)
                if key is not None:
                    found["media"].add(key)
            for _kind, href in links:
                bucket = classify_link(href)
                if bucket not in ("page", "asset"):
                    continue
                key = resolve_reference(href, path, root)
                if key is not None:
                    found[bucket].add(key)
            references[stem] = {k: sorted(v) for k, v in found.items()}
    return pages, references, page_keys


def collect_reports(root, raw=False):
    """Sidecar CSVs under root, keyed by filename, as sorted row tuples.

    The reports are a set of findings rather than an ordered document, so
    rows are sorted before comparing: two runs that report the same
    problems in a different order agree.
    """
    reports = {}
    for base, _dirs, names in os.walk(root):
        for name in sorted(names):
            if not name.lower().endswith(".csv"):
                continue
            path = os.path.join(base, name)
            rows = []
            with open(path, encoding="utf-8", errors="replace",
                      newline="") as handle:
                for row in csv.reader(handle):
                    if not raw:
                        row = [stem_of(cell) if looks_like_path(cell) else cell
                               for cell in row]
                    rows.append(tuple(row))
            reports.setdefault(name, []).extend(rows)
    return {name: sorted(rows) for name, rows in reports.items()}


def load(source, fold=False, raw=False, files=True, hash_content=True):
    """Read either a directory of output or a previously saved --json file."""
    if os.path.isdir(source):
        pages, references, page_keys = collect(source, fold=fold)
        return {"pages": pages,
                "references": references,
                "page_keys": sorted(page_keys),
                "reports": collect_reports(source, raw=raw),
                "files": collect_files(source, hash_content=hash_content)
                         if files else {}}
    with open(source, encoding="utf-8") as handle:
        saved = json.load(handle)
    saved.setdefault("pages", {})
    saved.setdefault("references", {})
    saved.setdefault("page_keys", [])
    saved.setdefault("files", {})
    saved["reports"] = {name: sorted(tuple(r) for r in rows)
                        for name, rows in saved.get("reports", {}).items()}
    return saved


# --------------------------------------------------------------------------
# comparing
# --------------------------------------------------------------------------

def within_tolerance(old, new, percent):
    """True when two counts agree closely enough to mean nothing.

    Word counts wobble by a few words whenever anything structural moves --
    a promoted heading takes its words with it -- so comparing them exactly
    makes the field fire on every page and say nothing. Comparing them
    loosely still catches the failure worth catching, which is a filter
    that drops a document's prose.
    """
    if not isinstance(old, int) or not isinstance(new, int):
        return False
    if old == new:
        return True
    gap = abs(old - new)
    if gap <= WORD_FLOOR:
        return True
    largest = max(abs(old), abs(new))
    return largest > 0 and gap * 100.0 / largest <= percent


def compare_pages(before, after, ignore, tolerance=2.0):
    """Return (field counter, examples, only_before, only_after, same)."""
    fields = Counter()
    examples = {}
    shared = sorted(set(before) & set(after))
    same = 0
    for stem in shared:
        differing = []
        keys = list(OrderedDict.fromkeys(
            list(before[stem].keys()) + list(after[stem].keys())))
        for key in keys:
            if key in ignore:
                continue
            old = before[stem].get(key, "<absent>")
            new = after[stem].get(key, "<absent>")
            if old == new:
                continue
            if key in TOLERANT_FIELDS and within_tolerance(old, new, tolerance):
                continue
            differing.append((key, old, new))
        if differing:
            for key, old, new in differing:
                fields[key] += 1
                examples.setdefault(key, []).append((stem, old, new))
        else:
            same += 1
    return (fields, examples,
            sorted(set(before) - set(after)),
            sorted(set(after) - set(before)),
            same)


def report(before, after, args):
    pages_before, pages_after = before["pages"], after["pages"]
    fields, examples, only_before, only_after, same = compare_pages(
        pages_before, pages_after, set(args.ignore), args.word_tolerance)

    shared = len(set(pages_before) & set(pages_after))
    print("Pages: %d in baseline, %d in candidate, %d in both"
          % (len(pages_before), len(pages_after), shared))
    print("  %d identical, %d differing" % (same, shared - same))

    if only_before:
        print("\nOnly in baseline (%d): %s"
              % (len(only_before), ", ".join(only_before[:8])
                 + (" ..." if len(only_before) > 8 else "")))
    if only_after:
        print("\nOnly in candidate (%d): %s"
              % (len(only_after), ", ".join(only_after[:8])
                 + (" ..." if len(only_after) > 8 else "")))

    if fields:
        print("\nDifferences by field:")
        # Collapse per-table fields so one changed table does not print as
        # a dozen unrelated-looking rows.
        grouped = Counter()
        for key, count in fields.items():
            grouped[re.sub(r"^table\[\d+\]\.", "table[*].", key)] += count
        width = max(len(k) for k in grouped)
        for key, count in sorted(grouped.items(),
                                 key=lambda kv: (-kv[1], kv[0])):
            print("  %5d  %-*s" % (count, width, key))

        for key in sorted(examples, key=lambda k: (-fields[k], k)):
            rows = examples[key][:args.examples]
            print("\n-- %s (%d page%s)"
                  % (key, fields[key], "" if fields[key] == 1 else "s"))
            for stem, old, new in rows:
                print("   %s" % stem[:70])
                print("       baseline:  %s" % _show(old))
                print("       candidate: %s" % _show(new))

    differences = bool(fields or only_before or only_after)
    differences |= _report_csvs(before["reports"], after["reports"], args)

    if before.get("files") or after.get("files"):
        differences |= _report_files(before, after, args)
        print("\nReferences:")
        old_bad = _report_references(before, "baseline", args)
        new_bad = _report_references(after, "candidate", args)
        if new_bad != old_bad:
            differences = True
    return differences


def _show(value):
    text = str(value)
    return text if len(text) <= 100 else text[:97] + "..."


def _report_files(before, after, args):
    """Compare the file inventories of two runs."""
    old, new = before["files"], after["files"]
    if not old and not new:
        return False

    print("\nFiles (media and anything else that is not a page or report):")
    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))
    renamed, changed, identical = [], [], 0

    for key in sorted(set(old) & set(new)):
        a, b = old[key], new[key]
        same_bytes = (a.get("digest") == b.get("digest")
                      if "digest" in a and "digest" in b
                      else a["size"] == b["size"])
        if a["ext"] != b["ext"]:
            renamed.append((key, a["ext"], b["ext"], same_bytes))
        elif not same_bytes:
            changed.append((key, a["size"], b["size"]))
        else:
            identical += 1

    print("  %d file(s) in baseline, %d in candidate, %d unchanged"
          % (len(old), len(new), identical))

    _by_extension("  only in baseline", only_old, old, args)
    _by_extension("  only in candidate", only_new, new, args)

    if renamed:
        moved = sum(1 for r in renamed if not r[3])
        print("  %d renamed (same path, different extension)%s"
              % (len(renamed),
                 ", of which %d also changed content" % moved if moved else
                 ", all with identical content"))
        for key, a, b, same in renamed[:args.examples]:
            print("       %s: %s -> %s%s"
                  % (key, a or "(none)", b or "(none)",
                     "" if same else "  [content differs]"))
    if changed:
        print("  %d changed content" % len(changed))
        for key, a, b in changed[:args.examples]:
            print("       %s: %d -> %d bytes" % (key, a, b))

    duplicates = [(side, key, entry["duplicates"])
                  for side, table in (("baseline", old), ("candidate", new))
                  for key, entry in sorted(table.items())
                  if entry.get("duplicates")]
    if duplicates:
        print("  %d path(s) present under more than one extension, which is "
              "what an interrupted rename leaves behind:" % len(duplicates))
        for side, key, exts in duplicates[:args.examples]:
            print("       %s: %s %s" % (side, key, " ".join(exts)))

    return bool(only_old or only_new or renamed or changed)


def _by_extension(label, keys, table, args):
    """Summarise a list of files by extension so a hundred do not print."""
    if not keys:
        return
    counts = Counter(table[k]["ext"] or "(none)" for k in keys)
    summary = ", ".join("%d %s" % (n, ext)
                        for ext, n in counts.most_common())
    print("%s: %d (%s)" % (label, len(keys), summary))
    for key in keys[:args.examples]:
        print("       %s%s" % (key, table[key]["ext"]))


def _report_references(run, label, args):
    """Check a run's references against what is actually present.

    Reported in three buckets because they fail for different reasons and
    are fixed in different places. A broken media reference is the failure
    the media gate in convert.sh exists to prevent: pandoc writes an
    <embed> rather than an <img> for a file it cannot type, and the page
    looks fine in the source and blank in a browser. A broken page link
    means the book does not hold together, which is usually a naming or
    outline problem rather than a conversion one. A broken asset link is a
    missing stylesheet or download. Orphans -- files nothing points at --
    are milder, but usually the other half of one of the above.
    """
    files, references = run["files"], run["references"]
    page_keys = set(run.get("page_keys", []))
    if not references:
        return None

    dangling = {"media": [], "page": [], "asset": []}
    referenced = set()
    for stem in sorted(references):
        buckets = references[stem]
        for bucket in ("media", "page", "asset"):
            for key in buckets.get(bucket, []):
                known = page_keys if bucket == "page" else files
                if bucket != "page":
                    referenced.add(key)
                if key not in known:
                    dangling[bucket].append((stem, key))
    orphans = sorted(set(files) - referenced)

    print("  %s" % label)
    for bucket, noun in (("media", "media reference"),
                         ("page", "page link"),
                         ("asset", "asset link")):
        bad = dangling[bucket]
        total = sum(len(references[s].get(bucket, [])) for s in references)
        if bad:
            print("    %-18s %d of %d broken" % (noun + "s:", len(bad), total))
            for stem, key in bad[:args.examples]:
                print("         %s points at missing %s" % (stem, key))
        else:
            print("    %-18s %d, all resolve" % (noun + "s:", total))
    if orphans:
        print("    %-18s %d never referenced" % ("files:", len(orphans)))
        for key in orphans[:args.examples]:
            print("         nothing points at %s%s" % (key, files[key]["ext"]))
    else:
        print("    %-18s all referenced" % "files:")

    return (len(dangling["media"]), len(dangling["page"]),
            len(dangling["asset"]), len(orphans))


def _report_csvs(before, after, args):
    names = sorted(set(before) | set(after))
    if not names:
        return False
    print("\nReports:")
    differences = False
    for name in names:
        old = before.get(name)
        new = after.get(name)
        if old is None or new is None:
            side = "candidate" if old is None else "baseline"
            print("  %-28s missing from %s" % (name, side))
            differences = True
            continue
        only_old = [r for r in old if r not in new]
        only_new = [r for r in new if r not in old]
        if not only_old and not only_new:
            print("  %-28s identical (%d rows)" % (name, len(old)))
            continue
        differences = True
        print("  %-28s %d row(s) only in baseline, %d only in candidate"
              % (name, len(only_old), len(only_new)))
        for row in only_old[:args.examples]:
            print("       baseline:  %s" % _show(",".join(row)))
        for row in only_new[:args.examples]:
            print("       candidate: %s" % _show(",".join(row)))
    return differences


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare two conversion runs semantically.")
    parser.add_argument("baseline",
                        help="directory of output, or a saved --json file")
    parser.add_argument("candidate", nargs="?",
                        help="directory of output to compare against it")
    parser.add_argument("--json", metavar="FILE",
                        help="write the baseline's signatures to FILE and "
                             "stop, so a run can be archived and compared "
                             "against later")
    parser.add_argument("--ignore", action="append", default=[],
                        metavar="FIELD",
                        help="skip a field, e.g. --ignore img_extensions; "
                             "repeatable")
    parser.add_argument("--examples", type=int, default=3, metavar="N",
                        help="examples to print per differing field "
                             "(default 3)")
    parser.add_argument("--no-files", action="store_true",
                        help="skip the file inventory and the reference "
                             "check, comparing only pages and reports")
    parser.add_argument("--no-hash", action="store_true",
                        help="compare files by size rather than by content, "
                             "which is faster but cannot tell a renamed "
                             "file from a rewritten one")
    parser.add_argument("--word-tolerance", type=float, default=2.0,
                        metavar="PCT",
                        help="how far word counts may drift before being "
                             "reported, as a percentage (default 2); "
                             "differences of %d words or fewer are never "
                             "reported" % WORD_FLOOR)
    parser.add_argument("--fold-quotes", action="store_true",
                        help="treat curly quotes, dashes, and ellipses as "
                             "their ASCII equivalents")
    parser.add_argument("--raw-csv", action="store_true",
                        help="compare report CSVs literally instead of "
                             "reducing file references to their stems")
    parser.add_argument("--idempotent", action="store_true",
                        help="phrase the summary as an idempotency check")
    args = parser.parse_args()

    if not os.path.exists(args.baseline):
        sys.exit("No such file or directory: %s" % args.baseline)

    before = load(args.baseline, fold=args.fold_quotes, raw=args.raw_csv,
                  files=not args.no_files, hash_content=not args.no_hash)

    if args.json:
        if args.candidate:
            sys.exit("Give --json a baseline to save, or two runs to "
                     "compare, not both.")
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(before, handle, indent=1, sort_keys=True)
        print("Wrote %d page signature(s), %d report(s), and %d file "
              "record(s) to %s"
              % (len(before["pages"]), len(before["reports"]),
                 len(before["files"]), args.json))
        return 0

    if not args.candidate:
        sys.exit("Give a second run to compare against, or --json to save "
                 "this one as a baseline.")
    if not os.path.exists(args.candidate):
        sys.exit("No such file or directory: %s" % args.candidate)

    after = load(args.candidate, fold=args.fold_quotes, raw=args.raw_csv,
                 files=not args.no_files, hash_content=not args.no_hash)
    differences = report(before, after, args)

    print()
    if args.idempotent:
        print("Not idempotent: the second run differs from the first."
              if differences else
              "Idempotent: the second run reproduces the first.")
    else:
        print("Runs differ." if differences else "Runs agree.")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
