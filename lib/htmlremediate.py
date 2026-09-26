"""A remediated copy of an author's own HTML page: the decisions made about
it in the sidecars, written back into the page as text edits, the rest of
it as the author wrote it. For a book kept as hand-maintained HTML; a page
saved from a platform is better fixed in the platform.

- **Tables.** A header declaration from the table-headers sidecar, never a
  guess (see docxremediate): a header row's cells become <th scope="col">,
  a header column's <th scope="row">. A table is found by its position
  among the page's tables, as Pandoc numbers them, and changed only when
  its row count and first cell are what the pre-pass saw.
- **Images.** Alt text from the image-alt sidecar, matched by the image's
  path, extension aside; `[decorative]` gives alt="".
- **Links.** From the bare-links sidecar, a bare link's title, and its
  replacement address, which replaces both the address and the text.
- **Captions.** A description from the table-captions sidecar: for a table
  with no label anywhere, as its <caption>; for one whose label is a
  paragraph beside it, joined to the end of that paragraph, where it
  stands, as the rendered page joins it. The filter records which table it
  gave each description to, by position (the sidecar's key names the table
  as the filter sees the page, which can differ from the file), and the
  copy finds that table as it does for headers.
- **Language.** The book's language as lang on <html>, when it has none.

Copyright 2026 Robert Szarka
"""

import html as htmllib
import os
import re
import shutil
import tempfile

TABLE_TAG = re.compile(r"<table\b[^>]*>|</table\s*>", re.I)
ROW_TAG = re.compile(r"<table\b[^>]*>|</table\s*>|<tr\b[^>]*>|</tr\s*>", re.I)
CELL = re.compile(r"<(td|th)\b([^>]*)>(.*?)</\1\s*>", re.I | re.S)


def table_spans(page):
    """[(start, end)] of every <table>, nested ones included, in document
    order, which is the order Pandoc numbers them in."""
    spans, stack = [], []
    for m in TABLE_TAG.finditer(page):
        if m.group(0).lower().startswith("<table"):
            stack.append(len(spans))
            spans.append([m.start(), None])
        elif stack:
            spans[stack.pop()][1] = m.end()
    return [tuple(s) for s in spans if s[1] is not None]


def _own_rows(table):
    rows, depth, start = [], 0, None
    for m in ROW_TAG.finditer(table):
        tag = m.group(0).lower()
        if tag.startswith("<table"):
            depth += 1
        elif tag.startswith("</table"):
            depth -= 1
        elif depth == 1 and tag.startswith("<tr"):
            start = m.start()
        elif depth == 1 and tag.startswith("</tr") and start is not None:
            rows.append((start, m.end()))
            start = None
    return rows


def _text(fragment):
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _header_cell(match, scope):
    attrs = re.sub(r'\sscope\s*=\s*("[^"]*"|\'[^\']*\'|\S+)', "", match.group(2))
    return '<th%s scope="%s">%s</th>' % (attrs, scope, match.group(3))


def _row_cells(row, scope, first_only):
    count = 0

    def one(m):
        nonlocal count
        count += 1
        if first_only and count > 1:
            return m.group(0)
        return _header_cell(m, scope)
    return CELL.sub(one, row)


def remediate_tables(page, resolved):
    """Each table's sidecar declaration written into its cells. Returns
    (page, counts)."""
    counts = {"header_rows": 0, "header_columns": 0, "skipped": 0, "undecided": 0}
    spans = table_spans(page)
    edits = []
    for entry in resolved:
        value = entry.get("headers")
        if entry.get("supplier") != "sidecar":
            counts["undecided"] += entry.get("supplier") == "guess" and value in (
                "first-row", "first-column", "both")
            continue
        if value not in ("first-row", "first-column", "both"):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or index >= len(spans):
            counts["skipped"] += 1
            continue
        start, end = spans[index]
        table = page[start:end]
        rows = _own_rows(table)
        first = CELL.search(table[rows[0][0]:rows[0][1]]) if rows else None
        if len(rows) != entry.get("rows") or (entry.get("first") and not (
                first and _text(first.group(3)).startswith(entry["first"][:30]))):
            counts["skipped"] += 1
            continue
        head = len(entry.get("caption_rows") or [])
        new = table
        for i, (r_start, r_end) in reversed(list(enumerate(rows))):
            row = new[r_start:r_end]
            if value in ("first-row", "both") and i == head:
                row = _row_cells(row, "col", False)
            elif value in ("first-column", "both") and i > head - (value == "first-column"):
                row = _row_cells(row, "row", True)
            new = new[:r_start] + row + new[r_end:]
        counts["header_rows"] += value in ("first-row", "both")
        counts["header_columns"] += value in ("first-column", "both")
        edits.append((start, end, new))
    for start, end, new in sorted(edits, reverse=True):
        page = page[:start] + new + page[end:]
    return page, counts


def remediate_captions(page, applied, resolved):
    """applied: [(position, how, key, description)] the filter recorded for the
    page; resolved: the pre-pass's entries for it, which give each table's
    shape. Returns (page, counts)."""
    counts = {"captions": 0, "captions_left": 0, "labels_joined": 0}
    shapes = {e.get("index"): e for e in resolved}
    spans = table_spans(page)
    edits = []
    for position, how, key, description in applied:
        if how in ("label-after", "label-before") and position < len(spans):
            start, end = spans[position]
            if how == "label-after":
                para = re.compile(r"\s*(?:<!--.*?-->\s*)*(<p\b[^>]*>)(.*?)(</p\s*>)",
                                  re.I | re.S).match(page, end)
            else:
                # The paragraph's content bounded: never across a </p>.
                paras = list(re.finditer(r"(<p\b[^>]*>)((?:(?!</p\s*>).)*)(</p\s*>)"
                                         r"\s*(?:<!--.*?-->\s*)*\Z", page[:start], re.I | re.S))
                para = paras[-1] if paras else None
            if para and _text(para.group(2)) == " ".join(key.split()):
                edits.append((para.start(3), " " + htmllib.escape(description, quote=False)))
                counts["labels_joined"] += 1
            else:
                counts["captions_left"] += 1
            continue
        if how != "position":
            counts["captions_left"] += 1
            continue
        entry = shapes.get(position)
        if entry is None or position >= len(spans):
            counts["captions_left"] += 1
            continue
        start, end = spans[position]
        table = page[start:end]
        rows = _own_rows(table)
        first = CELL.search(table[rows[0][0]:rows[0][1]]) if rows else None
        opening = TABLE_TAG.match(table)
        if len(rows) != entry.get("rows") or not opening \
                or re.match(r"\s*<caption\b", table[opening.end():], re.I) \
                or (entry.get("first") and not (
                    first and _text(first.group(3)).startswith(entry["first"][:30]))):
            counts["captions_left"] += 1
            continue
        at = start + opening.end()
        edits.append((at, "<caption>%s</caption>" % htmllib.escape(description, quote=False)))
        counts["captions"] += 1
    for at, text in sorted(edits, reverse=True):
        page = page[:at] + text + page[at:]
    return page, counts


def remediate_images(page, alts):
    """alts: {path without extension: alt, or None for decorative}.
    Returns (page, counts)."""
    counts = {"described": 0, "decorative": 0}
    if not alts:
        return page, counts

    def one(m):
        tag = m.group(0)
        src = re.search(r'\ssrc\s*=\s*("([^"]*)"|\'([^\']*)\')', tag, re.I)
        if not src:
            return tag
        path = htmllib.unescape(src.group(2) if src.group(2) is not None else src.group(3))
        key = os.path.splitext(path[2:] if path.startswith("./") else path)[0]
        if key not in alts:
            return tag
        alt = alts[key]
        tag = re.sub(r'\salt\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', "", tag, flags=re.I)
        end = -2 if tag.endswith("/>") else -1
        counts["decorative" if alt is None else "described"] += 1
        return tag[:end].rstrip() + ' alt="%s"' % htmllib.escape(alt or "", quote=True) \
            + (" />" if end == -2 else ">")
    return re.sub(r"<img\b[^>]*>", one, page, flags=re.I), counts


def remediate_links(page, links):
    """links: {address: (replacement, title)}. A bare link, its text its
    own address, gets its title, and its replacement as both address and
    text. Returns (page, counts)."""
    counts = {"links": 0, "replaced": 0}
    if not links:
        return page, counts

    def one(m):
        attrs, text = m.group(1), m.group(2)
        href = re.search(r'\shref\s*=\s*("([^"]*)"|\'([^\']*)\')', attrs, re.I)
        if not href:
            return m.group(0)
        address = htmllib.unescape(href.group(2) if href.group(2) is not None else href.group(3))
        if address not in links or _text(text) != address:
            return m.group(0)
        replacement, title = links[address]
        if replacement:
            attrs = attrs.replace(href.group(0), ' href="%s"' % htmllib.escape(replacement, quote=True))
            text = htmllib.escape(replacement, quote=False)
            counts["replaced"] += 1
        if title and not re.search(r"\stitle\s*=", attrs, re.I):
            attrs += ' title="%s"' % htmllib.escape(title, quote=True)
            counts["links"] += 1
        return "<a%s>%s</a>" % (attrs, text)
    return re.sub(r"<a\b([^>]*)>(.*?)</a\s*>", one, page, flags=re.I | re.S), counts


def remediate_language(page, language):
    """lang on <html>, when it has none. Returns (page, 1 or 0)."""
    if not language:
        return page, 0
    tag = re.search(r"<html\b[^>]*>", page, re.I)
    if not tag or re.search(r"\slang\s*=", tag.group(0), re.I):
        return page, 0
    new = tag.group(0)[:-1].rstrip() + ' lang="%s">' % htmllib.escape(language, quote=True)
    return page[:tag.start()] + new + page[tag.end():], 1


def alt_rows(path):
    """{image path without its extension: alt, or None for decorative}
    from an image-alt sidecar."""
    import csv
    found = {}
    if not path or not os.path.exists(path):
        return found
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            image, alt = (row.get("Image") or "").strip(), (row.get("Alt") or "").strip()
            if image and alt:
                found[os.path.splitext(image)[0]] = None if alt == "[decorative]" else alt
    return found


def caption_rows(path):
    """{page: [(position, how, key, description)]} from the file the filter
    writes (CAPTIONS_APPLIED), each table once."""
    import csv
    found, seen = {}, set()
    if not path or not os.path.exists(path):
        return found
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 5 or not row[1].strip().isdigit():
                continue
            stem, position = row[0], int(row[1])
            if (stem, position) in seen:
                continue
            seen.add((stem, position))
            found.setdefault(stem, []).append((position, row[2], row[3], row[4]))
    return found


def link_rows(path):
    """{address: (replacement, title)} from a bare-links sidecar."""
    import csv
    found = {}
    if not path or not os.path.exists(path):
        return found
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            url = (row.get("URL") or "").strip()
            replacement, title = (row.get("Replacement") or "").strip(), (row.get("Title") or "").strip()
            if url and (replacement or title):
                found[url] = (replacement, title)
    return found


def remediate(source, destination, tables=None, alts=None, links=None, language=None,
              captions=None):
    """Write destination, a copy of source with the decisions applied.
    Returns a dict of counts."""
    with open(source, "rb") as fh:
        raw = fh.read()
    page = raw.decode("utf-8")
    counts = {}
    new, found = remediate_tables(page, tables or [])
    counts.update(found)
    new, found = remediate_captions(new, captions or [], tables or [])
    counts.update(found)
    new, found = remediate_images(new, alts or {})
    counts.update(found)
    new, found = remediate_links(new, links or {})
    counts.update(found)
    new, counts["language"] = remediate_language(new, language)
    handle, temporary = tempfile.mkstemp(suffix=".html",
                                         dir=os.path.dirname(os.path.abspath(destination)))
    os.close(handle)
    with open(temporary, "wb") as fh:
        fh.write(raw if new == page else new.encode("utf-8"))
    shutil.move(temporary, destination)
    counts["changed"] = int(new != page)
    return counts
