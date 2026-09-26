"""A remediated copy of an author's own Pandoc Markdown file: the decisions
made about it in the sidecars, written into the text where each element
is, the rest of the file exactly as the author wrote it. Nothing is
parsed and written again, so every construct Pandoc Markdown has survives
as written; what's found and changed is confirmed against Pandoc's own
reading of the file, and anything that can't be confirmed is left alone
and counted.

- **Images.** Alt text from the image-alt sidecar, between ![ and ];
  `[decorative]` empties it and adds .decorative to the image's
  attributes. Each image's syntax is found by a scanner that follows
  Pandoc's rules (a destination runs to the parenthesis that balances the
  opening one, spaces and all), and a path is changed only when the
  scanner finds it as many times as Pandoc reads it, which rules out
  syntax inside code.
- **Links.** From the bare-links sidecar, a bare link, <url> or
  [url](url), becomes [replacement](replacement "title"), since <url>
  can't carry a title; counted the same way.
- **Captions.** A description from the table-captions sidecar, found as
  the filter recorded it (see htmlremediate): a Table: line for a table
  with none, inside its div if it's in one, or joined to the end of a
  label paragraph beside it. A table is found as a stretch of lines that
  Pandoc's Markdown reader reads as exactly that table.
- **Language.** lang in the front matter, when it has none.

Copyright 2026 Robert Szarka
"""

import json
import os
import re
import subprocess
from collections import Counter
from urllib.parse import unquote

ESC = re.compile(r"\\([^A-Za-z0-9\s])")
SPLIT = "<!-- TIQ-SPLIT -->"


def unescape(text):
    return ESC.sub(r"\1", text)


def escape_inline(text):
    return re.sub(r"([\\\[\]*_`<])", r"\\\1", text)


def read(text):
    """Pandoc's reading of Markdown, as the conversion reads it."""
    result = subprocess.run(["pandoc", "-f", "markdown", "-t", "json"], input=text,
                            capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 else {"blocks": []}


def _all(node, out):
    if isinstance(node, dict):
        out.append(node)
        _all(node.get("c"), out)
    elif isinstance(node, list):
        for item in node:
            _all(item, out)
    return out


def elements(blocks, kind):
    return [e for e in _all(blocks, []) if e.get("t") == kind]


def _plain(inlines):
    return "".join(x.get("c", "") if x.get("t") == "Str" else " " if x.get("t") == "Space" else ""
                   for x in inlines)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def scan_images(text):
    """Each image's syntax: {"alt": (start, end), "dest": destination as
    Pandoc reads it, "end": just past it, "attr": (start, end) of an
    attribute block after it, or None}."""
    refs = {k.lower(): unescape(v) for k, v in
            re.findall(r"^\s{0,3}\[([^\]]+)\]:\s*<?([^\s>]+)>?", text, re.M)}
    found, i = [], 0
    while True:
        i = text.find("![", i)
        if i < 0:
            return found
        if i > 0 and text[i - 1] == "\\":
            i += 2
            continue
        j, depth = i + 2, 1
        while j < len(text) and depth:
            if text[j] == "\\":
                j += 2
                continue
            depth += {"[": 1, "]": -1}.get(text[j], 0)
            j += 1
        if depth:
            return found
        alt = (i + 2, j - 1)
        dest, end = None, j
        if text[j:j + 1] == "(":
            k, p = j + 1, 1
            while k < len(text) and p:
                if text[k] == "\\":
                    k += 2
                    continue
                p += {"(": 1, ")": -1}.get(text[k], 0)
                k += 1
            inner = re.sub(r'\s+("[^"]*"|\'[^\']*\')\s*$', "", text[j + 1:k - 1]).strip()
            if inner.startswith("<") and inner.endswith(">"):
                inner = inner[1:-1]
            dest, end = unescape(inner), k
        elif text[j:j + 1] == "[":
            close = text.find("]", j)
            key = (text[j + 1:close] or text[alt[0]:alt[1]]).lower()
            dest, end = refs.get(key), close + 1
        if dest is not None:
            attr = re.compile(r"\{[^}\n]*\}").match(text, end)
            found.append({"alt": alt, "dest": dest, "end": end,
                          "attr": (attr.start(), attr.end()) if attr else None})
        i = j


def sidecar_key(target):
    """The image-alt sidecar's key for a Markdown image's path: forward
    slashes, as the conversion makes it (portable_media_paths), decoded,
    without the extension."""
    path = unquote(target.replace("\\", "/"))
    return os.path.splitext(path[2:] if path.startswith("./") else path)[0]


def remediate_images(text, doc, alts):
    """alts: {path without extension: alt, or None for decorative}.
    Returns (text, counts)."""
    counts = {"described": 0, "decorative": 0, "images_skipped": 0}
    if not alts:
        return text, counts
    wanted = Counter(unquote(e["c"][2][0]) for e in elements(doc["blocks"], "Image"))
    scanned = scan_images(text)
    written = Counter(unquote(o["dest"]) for o in scanned)
    edits = []
    for target, n in wanted.items():
        key = sidecar_key(target)
        if key not in alts:
            continue
        if written[target] != n:
            counts["images_skipped"] += n
            continue
        alt = alts[key]
        for o in scanned:
            if unquote(o["dest"]) != target:
                continue
            edits.append((o["alt"][0], o["alt"][1], "" if alt is None else escape_inline(alt)))
            if alt is None:
                counts["decorative"] += 1
                if o["attr"] is None:
                    edits.append((o["end"], o["end"], "{.decorative}"))
                elif ".decorative" not in text[o["attr"][0]:o["attr"][1]]:
                    # After the last attribute, keeping the author's spacing
                    # before the brace: { width=50% } -> { width=50% .decorative }.
                    attr = text[o["attr"][0]:o["attr"][1]]
                    inner = attr[1:-1]
                    trailing = inner[len(inner.rstrip()):]
                    edits.append((o["attr"][0], o["attr"][1],
                                  "{" + inner.rstrip() + " .decorative" + trailing + "}"))
            else:
                counts["described"] += 1
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + new + text[end:]
    return text, counts


# ---------------------------------------------------------------------------
# Bare links
# ---------------------------------------------------------------------------

def remediate_links(text, doc, links):
    """links: {address: (replacement, title)}. Returns (text, counts)."""
    counts = {"links": 0, "replaced": 0, "links_skipped": 0}
    if not links:
        return text, counts
    bare = Counter(e["c"][2][0] for e in elements(doc["blocks"], "Link")
                   if _plain(e["c"][1]) == e["c"][2][0])
    edits = []
    for url, n in bare.items():
        if url not in links:
            continue
        pattern = re.compile(r"<" + re.escape(url) + r">|\[" + re.escape(url) + r"\]\(\s*<?"
                             + re.escape(url) + r'>?(?:\s+("[^"]*"|\'[^\']*\'))?\s*\)')
        spots = list(pattern.finditer(text))
        if len(spots) != n:
            counts["links_skipped"] += n
            continue
        replacement, title = links[url]
        address = replacement or url
        for m in spots:
            kept = m.group(1)[1:-1] if m.group(1) else ""
            label = title or kept
            new = "[%s](%s%s)" % (address, address,
                                  ' "%s"' % label.replace('"', '\\"') if label else "")
            edits.append((m.start(), m.end(), new))
            counts["replaced"] += bool(replacement)
            counts["links"] += bool(title)
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + new + text[end:]
    return text, counts


# ---------------------------------------------------------------------------
# Tables and their captions
# ---------------------------------------------------------------------------

def _shape(node):
    return re.sub(r'\["[^"]*", \[', '["", [', json.dumps(node, sort_keys=True))


def table_stretches(text, doc):
    """[(first line, end line, wrapped)] for each table Pandoc reads, in
    its reading's order, or None where it can't be found: the stretch of
    lines between blank lines, up to six together, that Pandoc's reader
    reads as exactly that table, alone or inside one div."""
    lines = text.split("\n")
    tables = elements(doc["blocks"], "Table")
    if not tables:
        return []
    stretches, start = [], None
    for i, line in enumerate(lines + [""]):
        if line.strip() and start is None:
            start = i
        elif not line.strip() and start is not None:
            stretches.append((start, i))
            start = None
    candidates = []
    for k in range(len(stretches)):
        for width in range(1, 7):
            if k + width > len(stretches):
                break
            a, b = stretches[k][0], stretches[k + width - 1][1]
            chunk = "\n".join(lines[a:b])
            # A stretch with an unclosed div or code fence would swallow
            # the rest of the batch, and can't be a whole table anyway.
            if len(re.findall(r"^:{3,}\s*\S", chunk, re.M)) != len(re.findall(r"^:{3,}\s*$", chunk, re.M)) \
                    or len(re.findall(r"^\s*(```|~~~)", chunk, re.M)) % 2:
                continue
            if "|" in chunk or "--" in chunk or "+-" in chunk:
                candidates.append((a, b, chunk))
    parsed = read(("\n\n" + SPLIT + "\n\n").join(c[2] for c in candidates))["blocks"]
    segments, current = [], []
    for block in parsed:
        if block.get("t") == "RawBlock" and SPLIT in block["c"][1]:
            segments.append(current)
            current = []
        else:
            current.append(block)
    segments.append(current)
    places = {}
    for (a, b, _), segment in zip(candidates, segments):
        inside = elements(segment, "Table")
        if len(segment) != 1 or len(inside) != 1:
            continue
        places.setdefault(_shape(inside[0]), []).append((a, b, segment[0].get("t") != "Table"))
    out, used = [], Counter()
    for table in tables:
        options = places.get(_shape(table), [])
        # The shortest stretch for each table, in order: a longer one
        # holds the same table with a neighbor.
        options = sorted(options, key=lambda o: (o[0], o[1] - o[0]))
        chosen = None
        for option in options:
            if used[option[:2]] == 0 and (not out or out[-1] is None or option[0] >= out[-1][1]):
                chosen = option
                break
        if chosen:
            used[chosen[:2]] += 1
        out.append(chosen)
    return out


def remediate_captions(text, doc, applied):
    """applied: [(position, how, key, description)] the filter recorded for
    the page. Returns (text, counts)."""
    counts = {"captions": 0, "labels_joined": 0, "captions_left": 0}
    if not applied:
        return text, counts
    places = table_stretches(text, doc)
    lines = text.split("\n")
    inserts = []                      # (line index, lines to insert)
    appends = []                      # (line index, text to append)
    for position, how, key, description in applied:
        place = places[position] if position < len(places) else None
        if place is None:
            counts["captions_left"] += 1
            continue
        a, b, wrapped = place
        if how == "position":
            at = b - 1 if wrapped and re.match(r"^:{3,}\s*$", lines[b - 1]) else b
            # Inside a div, the caption line directly before the closing
            # fence, as a book written by hand has it.
            inserts.append((at, ["", "Table: " + description]))
            counts["captions"] += 1
            continue
        # A label paragraph: the next stretch after the table, or the one
        # before it, whose text is the label.
        if how == "label-after":
            s = b
            while s < len(lines) and not lines[s].strip():
                s += 1
            e = s
            while e < len(lines) and lines[e].strip():
                e += 1
        else:
            e = a
            while e > 0 and not lines[e - 1].strip():
                e -= 1
            s = e
            while s > 0 and lines[s - 1].strip():
                s -= 1
        if s < e and " ".join(" ".join(lines[s:e]).split()) == " ".join(key.split()):
            appends.append((e - 1, " " + description))
            counts["labels_joined"] += 1
        else:
            counts["captions_left"] += 1
    for index, extra in appends:
        lines[index] = lines[index].rstrip() + extra
    for index, block in sorted(inserts, key=lambda i: i[0], reverse=True):
        lines[index:index] = block
    return "\n".join(lines), counts


# ---------------------------------------------------------------------------
# Language, and the file
# ---------------------------------------------------------------------------

def remediate_language(text, language):
    """lang in the front matter when it has none. Returns (text, 1 or 0)."""
    if not language:
        return text, 0
    front = re.match(r"---[ \t]*\n(.*?)\n(---|\.\.\.)[ \t]*(\n|$)", text, re.S)
    if front:
        if re.search(r"^lang\s*:", front.group(1), re.M):
            return text, 0
        at = front.end(1)
        return text[:at] + "\nlang: " + language + text[at:], 1
    return "---\nlang: " + language + "\n---\n\n" + text, 1


def remediate(source, destination, alts=None, links=None, captions=None, language=None):
    """Write destination, a copy of source with the decisions applied.
    Returns a dict of counts."""
    with open(source, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    counts = {}
    # Captions first, while the lines are the author's: the table stretches
    # are found in the text as read.
    new, found = remediate_captions(text, read(text), captions or [])
    counts.update(found)
    new, found = remediate_images(new, read(new), alts or {})
    counts.update(found)
    new, found = remediate_links(new, read(new), links or {})
    counts.update(found)
    new, counts["language"] = remediate_language(new, language)
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    with open(destination, "wb") as fh:
        fh.write(raw if new == text else new.encode("utf-8"))
    counts["changed"] = int(new != text)
    return counts
