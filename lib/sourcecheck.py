"""
sourcecheck.py -- what a source document says about itself, read from
the JSON Pandoc makes of it, before any filter has fixed anything.

An audit looks at the author's file as Pandoc sees it, so it reports
what is there to fix: images with no alt text and no decorative
marker, tables with no header row and no marker, links whose text is
their own URL, headings that skip a level, raw HTML the conversion
would pass through untouched, math that cannot be written back. A
Word source adds what the table census can say, since the census
reads OOXML, which a Markdown file has none of.

The filter reports some of the same things on a conversion, from its
own reading. Both come from the same document, and the fixture test
holds their counts equal, because two implementations drift.

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
import os
import re
import subprocess

from findings import Finding

EXTERNAL = ("http://", "https://", "mailto:", "tel:", "#", "//")


def read(path, kind):
    """Pandoc's JSON of a source, with no filter."""
    reader = "docx" if kind == "source-docx" else "markdown"
    result = subprocess.run(["pandoc", "-f", reader, "-t", "json", path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300])
    return json.loads(result.stdout)


def text_of(inlines):
    out = []
    for i in inlines:
        if not isinstance(i, dict):
            continue
        t = i.get("t")
        if t == "Str":
            out.append(i["c"])
        elif t in ("Space", "SoftBreak", "LineBreak"):
            out.append(" ")
        elif t in ("Emph", "Strong", "Underline", "Strikeout", "SmallCaps",
                   "Superscript", "Subscript"):
            out.append(text_of(i["c"]))
        elif t in ("Link", "Image", "Span"):
            out.append(text_of(i["c"][1]))
        elif t == "Quoted":
            out.append(text_of(i["c"][1]))
        elif t in ("Code", "Math"):
            out.append(i["c"][1])
    return "".join(out)


def walk(node, on_block=None, on_inline=None):
    if isinstance(node, dict):
        t = node.get("t")
        if on_inline and t in ("Image", "Link", "Math", "Span", "Str",
                               "RawInline"):
            on_inline(node)
        if on_block and t in ("Header", "Table", "RawBlock", "Figure", "Div"):
            on_block(node)
        for value in node.values():
            walk(value, on_block, on_inline)
    elif isinstance(node, list):
        for item in node:
            walk(item, on_block, on_inline)


def table_has_header_row(table):
    head = table["c"][3]
    return bool(head[1])




def book_language(path):
    """The language a project.yaml beside the file declares, if any."""
    candidate = os.path.join(os.path.dirname(os.path.abspath(path)),
                             "project.yaml")
    try:
        with open(candidate, encoding="utf-8") as fh:
            m = re.search(r"^\s*language:\s*(\S+)", fh.read(), re.M)
            return m.group(1).strip("'\"") if m else ""
    except OSError:
        return ""


def check(path, kind, markers=("matrix", "row-headers")):
    """Findings for one source. kind is source-docx or source-md."""
    name = os.path.basename(path)
    out = []
    try:
        doc = read(path, kind)
    except RuntimeError as exc:
        out.append(Finding(name, "source-unreadable", str(exc), file=name,
                           kind=kind, severity="error", fix="manual"))
        return out
    meta = doc.get("meta", {})
    h1s = [b for b in doc["blocks"] if isinstance(b, dict)
           and b.get("t") == "Header" and b["c"][0] == 1]
    if "title" not in meta and len(h1s) != 1:
        out.append(Finding(name, "source-no-title", "no title metadata and, "
                           "for a Word file, no Title-styled paragraph",
                           file=name, kind=kind))
    if kind == "source-md" and "lang" not in meta and not book_language(path):
        out.append(Finding(name, "source-no-language",
                           "no lang: in the YAML header and no language in a "
                           "project.yaml beside it (the run's default, en, "
                           "applies)", file=name, kind=kind, severity="note"))

    marked_tables = set()
    headings = []
    table_index = [0]

    def on_block(node):
        t = node["t"]
        if t == "Div":
            classes = node["c"][0][1]
            if any(c in markers for c in classes):
                for inner in node["c"][1]:
                    if isinstance(inner, dict) and inner.get("t") == "Table":
                        marked_tables.add(id(inner))
        elif t == "Header":
            headings.append((node["c"][0], text_of(node["c"][2])))
        elif t == "Table":
            table_index[0] += 1
            n = table_index[0]
            caption = node["c"][1]
            has_caption = bool(caption[1]) or bool(caption[0])
            if not table_has_header_row(node) and id(node) not in marked_tables:
                first_col = []
                for body in node["c"][4]:
                    for row in body[3]:
                        cells = row[1]           # Row: [attr, cells]
                        blocks = cells[0][4] if cells else []
                        first = blocks[0] if blocks else None
                        first_col.append(text_of(first["c"]).strip()
                                         if first and first.get("t") in
                                         ("Plain", "Para") else "")
                keyed = (len(first_col) > 1 and all(first_col)
                         and len(set(first_col)) == len(first_col))
                if not keyed:
                    out.append(Finding(f"table {n}", "source-table-no-headers",
                                       "no header row and no marker; first "
                                       "column does not key the rows",
                                       file=name, kind=kind))
            if not has_caption and kind == "source-md":
                out.append(Finding(f"table {n}", "source-table-no-caption",
                                   "no caption line", file=name, kind=kind,
                                   severity="note"))
        elif t == "RawBlock":
            fmt, body = node["c"]
            if fmt in ("html", "html5"):
                head = body.strip().split("\n", 1)[0][:60]
                out.append(Finding(name, "source-raw-html", head, file=name,
                                   kind=kind))

    image_index = [0]

    def on_inline(node):
        t = node["t"]
        if t == "Image":
            image_index[0] += 1
            attr, alt, (src, _) = node["c"]
            decorative = "decorative" in attr[1]
            if not text_of(alt).strip() and not decorative:
                out.append(Finding(f"image {image_index[0]}",
                                   "source-image-no-alt", os.path.basename(src),
                                   file=name, kind=kind))
        elif t == "Link":
            attr, inner, (target, _) = node["c"]
            label = text_of(inner).strip()
            if label and label == target or label.rstrip("/") == target.rstrip("/"):
                if target.startswith(("http://", "https://")) and \
                        "aria-label" not in dict(attr[2]):
                    out.append(Finding(name, "source-link-bare-url", target[:80],
                                       file=name, kind=kind))
        elif t == "Math":
            body = node["c"][1]
            if re.search(r"\\\s*$", body):
                out.append(Finding(name, "source-math-trailing-space",
                                   body[-40:], file=name, kind=kind))

    walk(doc["blocks"], on_block, on_inline)

    last = None
    for level, text in headings:
        if last is not None and level > last + 1:
            out.append(Finding(name, "source-heading-skips-level",
                               f"h{last} to h{level}: {text[:60]}", file=name,
                               kind=kind))
        last = level
    return out


def census_findings(path, tc):
    """A Word source's tables as the census sees them: the guess it
    would make for each data table, and the ones it could not settle."""
    name = os.path.basename(path)
    out = []
    try:
        body = tc.read_body(path)
    except Exception as exc:
        return [Finding(name, "source-unreadable", f"census: {exc}"[:200],
                        file=name, kind="source-docx", severity="note",
                        fix="manual")]
    if body is None:
        return out
    for index, (tbl, depth) in enumerate(tc.all_tables(body), 1):
        kind, ev, nrows, ncols = tc.classify(tbl)
        value, reason = tc.explain(tbl, kind, ev)
        if value is None:                # a layout table, or empty
            continue
        where = f"table {index} ({nrows}x{ncols})"
        if value in ("none", "unknown"):
            out.append(Finding(where, "source-table-no-headers",
                               f"{kind}: {reason}"[:160], file=name,
                               kind="source-docx"))
        else:
            out.append(Finding(where, "source-table-headers-guessed",
                               f"{value}: {reason}"[:160], file=name,
                               kind="source-docx"))
    return out
