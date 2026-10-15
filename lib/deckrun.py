"""
deckrun.py -- a run of convert.py over a folder of PowerPoint decks.

Each deck is checked (pptxcheck.py), the decisions a person has to make
are written to the reports the sidecars are filled from, and each
format: source target writes the decisions already made into a copy of
each deck (pptxremediate.py). The reports:

- image-alt-missing.csv: a row for each picture whose alt text is
  missing or says nothing, keyed on the image's content so one row covers
  every copy of it (media/ and the first 16 characters of its SHA-256),
  with the image itself written to that path beside the decks so a person
  can look at it; a row for each other object (a chart, an embedded
  object, a group) that needs alt text, keyed on deck/slide-N/shape-M;
  and for a picture whose copies are cropped to show different parts of
  its image, a row for each copy, keyed on its shape as an object's is;
- table-headers-new.csv: each table with no header row marked, keyed on
  its content as a book's tables are, with the table census's guess;
- slide-titles-new.csv: each slide with no title, and each whose title
  an earlier slide in its deck has, keyed on deck/slide-N, the second of
  them drafted "Title (2)", the third "Title (3)"; a slide with no title
  drafted from the heading it shows, when it shows one (pptxtitle.py),
  which its copy makes its title in place, numbered so too when an earlier
  slide has that title;
- reading-order-new.csv: each slide read in another order than it's laid
  out, keyed on deck/slide-N, with an order drafted for a person to
  review, as near to the layout as it can come without drawing two
  shapes that overlap the other way round (pptxorder.py);
- bare-links-new.csv: each address a deck's link shows as its text, as
  a book's report has them, for the bare-links sidecar a book's run reads;
- slides-check.csv: every finding, in the output check's format; and,
  once a source target has written its copies, output-check.csv, what's
  left to do in them, and math-repaired.csv, each equation they repaired
  (math.repair_equations), in a book's columns, written out in one line
  (pptxremediate.equation_text) as the rows of math-keep.csv name one to
  keep as it was.

A report is written only when it has rows, and a stale one is removed:
the file being there says there's work to do.

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
import os
import zipfile
from collections import Counter, OrderedDict

import alttext
import findings as fl
import pptxcheck
import pptxfonts
import pptxorder
import pptxparse
import pptxremediate
import pptxtitle
import sidecars
import tablecensus

ALT_COLUMNS = ["Image", "Alt", "Source", "Reason", "CurrentAlt", "Drafted by", "Reviewed"]
TABLE_COLUMNS = ["key", "headers", "split-at", "caption-rows", "part-captions", "source",
                 "label", "preview", "drafted-by", "reviewed"]
TITLE_COLUMNS = ["Slide", "Title", "Source", "Drafted by", "Reviewed"]
ORDER_COLUMNS = ["Slide", "Order", "Source", "Shapes", "Note", "Drafted by", "Reviewed"]
LINK_COLUMNS = ["URL", "Replacement", "Title", "Source", "Context", "Drafted by", "Reviewed"]
MATH_COLUMNS = ["Kind", "Page", "Before", "After"]
# The alt-text findings that ask a person for a decision.
DECIDE = ("pptx-object-no-alt", "pptx-shape-no-alt", "pptx-alt-is-file-name",
          "pptx-alt-placeholder", "pptx-alt-auto-generated", "pptx-alt-page-title",
          "pptx-alt-credit", "pptx-alt-same-for-crops", "pptx-alt-shared", "pptx-alt-too-long",
          "pptx-master-image-no-alt")


def deck_sources(base):
    """The PowerPoint decks at the top of a folder, in name order, all but
    the lock files PowerPoint keeps beside a deck it has open (~$...). One
    that can't be read is still a deck, for the run to name."""
    return [name for name in sorted(os.listdir(base))
            if name.lower().endswith(".pptx") and not name.startswith("~$")
            and os.path.isfile(os.path.join(base, name))]


# An OLE compound file's first bytes: what Office writes a deck saved with
# a password as, and PowerPoint 97-2003's own format.
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def unreadable(path, exc):
    """Why a deck can't be read, in words a person can act on."""
    with open(path, "rb") as fh:
        head = fh.read(8)
    if not head:
        return "the file is empty"
    if head == OLE:
        return ("it's saved with a password, or in PowerPoint 97-2003's format under a .pptx "
                "name; saved again from PowerPoint, without a password, it can be read")
    if not zipfile.is_zipfile(path):
        return "it isn't a PowerPoint file (a .pptx is a zip, and this isn't one)"
    return str(exc)


def clashing(decks):
    """Decks whose names are one name in the sidecars' keys (Deck.pptx and
    Deck.PPTX), as {name: [files]}."""
    seen = {}
    for name in decks:
        seen.setdefault(pptxremediate.deck_name(name), []).append(name)
    return {key: files for key, files in seen.items() if len(files) > 1}


def reason_of(check, detail):
    """The Reason column, in the words a book's report uses."""
    if check in ("pptx-object-no-alt", "pptx-shape-no-alt", "pptx-master-image-no-alt"):
        return "missing (%s)" % detail
    return {"pptx-alt-is-file-name": "a file name or extension",
            "pptx-alt-placeholder": alttext.reason("placeholder", detail.split(":")[0]),
            "pptx-alt-auto-generated": "generated by Office",
            "pptx-alt-page-title": "a web page's title",
            "pptx-alt-credit": "a credit or a source",
            "pptx-alt-same-for-crops": "shared with a copy showing another part",
            # "shared with 2 other pictures: A graph" -> "shared with 2 other pictures"
            "pptx-alt-shared": detail.split(":")[0],
            # "227 characters (limit 120)" -> "too long (227 characters)"
            "pptx-alt-too-long": "too long (%s)" % detail.split(" (")[0]}.get(check, detail)


def census_view(table):
    """A deck's table as the table census reads a table: the grid, a
    merged cell repeated across the columns it spans as Word's is, and
    PowerPoint's header-column flag as Word's table look."""
    grid = []
    for line in table.grid:
        row = []
        for text, bold, span, vertical in line:
            row.extend([tablecensus.Cell.of(text, bold=bold, span=span, vmerge=vertical)] * span)
        grid.append(row)
    return tablecensus.View(grid, {"firstRow": table.first_row,
                                   "firstColumn": table.first_col})


def census_guess(table):
    """The headers value the table census would fill a table-headers row
    with, as the header pre-pass does for a book's table: empty when it
    has no guess, or reads the table as layout. A book's split-at and
    caption-rows aren't guessed, since PowerPoint can't split a table or
    give it a caption: its header row is the first row, whatever that
    holds."""
    view = census_view(table)
    try:
        kind, ev, _rows, _cols = tablecensus.classify(view)
        value = tablecensus.guess_table(view, kind, ev)[0]
    except Exception:             # a guess is help, not a requirement
        return ""
    return "" if value in (None, "unknown") else value


def preview(table):
    """The first row's first three cells, as a book's report previews a
    table."""
    first = table.rows[0][:3] if table.rows else []
    return " | ".join(" ".join(c.split())[:24] for c in first)


def write_rows(path, columns, rows):
    """A report with rows, or none: a stale one is removed."""
    if not rows:
        if os.path.exists(path):
            os.remove(path)
        return False
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)
    return True


def alt_row(key, sources, reason, current, copies):
    """An image-alt-missing row. A picture's names every copy of its image
    and each alt text they have now, since its decision is all of theirs:
    a copy whose own alt text was fine is in the row too, to keep or to
    replace."""
    if current is None:
        found = copies.get(sources, {})
        wheres = list(found)
        shown = wheres if len(wheres) <= 12 else wheres[:12] + ["... (%d in all)" % len(wheres)]
        states = []
        for state in (s for now in found.values() for s in sorted(now)):
            if state not in states:
                states.append(state)
        return [key, "", "; ".join(shown), reason, " | ".join(states), "", ""]
    return [key, "", "; ".join(sources), reason, current, "", ""]


def cropped_apart(placed):
    """The images whose copies show different parts of them, cropped
    differently, all on slides: each copy is a picture of its own, and
    is described on its own, keyed on its shape. One with a copy on a
    layout or master keeps its one row, which only a picture's key can
    name there."""
    return {digest for digest, where in placed.items()
            if all(slide is not None for _dname, slide, _shape, _where in where)
            and len(set(pptxcheck.crop_views(
                [shape.crop for _dname, _slide, shape, _where in where]))) > 1}


def crop_rows(key, found):
    """A row for each copy of a picture cropped differently in different
    places, keyed on its shape, its Reason naming the image it shows part
    of, which is written to the key the picture's row would have had."""
    rows, seen = [], set()
    for name, dname, slide, shape, check, detail in found:
        okey = pptxremediate.object_key(dname, slide, shape) if slide is not None else None
        if okey is None or okey in seen:
            continue
        seen.add(okey)
        rows.append([okey, "", "%s slide %d" % (name, slide.number),
                     "%s; a crop of %s, which other copies crop differently"
                     % (reason_of(check, detail), key),
                     " ".join((shape.descr or "").split()), "", ""])
    return rows


def one_alt_for_parts(alts, placed, split):
    """{picture's key: [where]} for each picture cropped differently in
    different places whose row in the sidecar gives copies showing
    different parts of it one alt text; a row keyed on each copy's shape
    can give each its own."""
    out = OrderedDict()
    for digest, where in placed.items():
        if digest not in split:
            continue
        crops, wheres = [], []
        for dname, slide, shape, place in where:
            if pptxremediate.object_key(dname, slide, shape) in alts:
                continue
            for key in (pptxremediate.image_key(digest, dname), pptxremediate.image_key(digest)):
                if key in alts:
                    if alts[key]:
                        crops.append(shape.crop)
                        if place not in wheres:
                            wheres.append(place)
                    break
        if len(set(pptxcheck.crop_views(crops))) > 1:
            out[pptxremediate.image_key(digest)] = wheres
    return out


def deck_key(key):
    """Whether an image-alt key is a deck's: a picture's content, or an
    object on a slide."""
    return key.startswith("media/") or "/media/" in key or "/slide-" in key


def unmatched(paths, alts, tables, titles, present, say, orders=(), links=()):
    """Said once for each sidecar: rows whose key no deck has. A picture's
    key is its content, so a row stops matching only when the picture is
    replaced; an object's and a slide's are the ids PowerPoint gave them,
    which last until the slide or the shape is deleted. Either way, the
    deck's new key is in this run's report."""
    for kind, rows, setting, what in (
            ("alt", [k for k in alts if deck_key(k)], "image_alt", "picture or object"),
            ("table", list(tables), "table_headers", "table"),
            ("slide", list(titles), "slide_titles", "slide"),
            ("slide", list(orders), "reading_order", "slide"),
            ("link", list(links), "bare_links", "bare link")):
        stale = sorted(k for k in rows if k not in present[kind])
        if stale and paths.get(setting):
            say("NOTE: %d row(s) of %s match no %s in these decks (%s%s); if a deck "
                "changed, its new row is in this run's report, and the old one can go."
                % (len(stale), os.path.basename(paths[setting]), what,
                   ", ".join(k[:40] for k in stale[:3]), ", ..." if len(stale) > 3 else ""))


def summarize(lead, found, say):
    """The counts a person reads first, as the audit prints them, after
    a lead saying what was checked."""
    if not found:
        say(lead + "nothing found.")
        return
    lines = fl.summary_lines(found)
    say(lead + lines[0])
    for line in lines[1:]:
        if line:
            say("  " + line)


def report(path, columns, rows, noun, sidecar, say, hint=None):
    """A report and what to do with it, said as a book's run says it: one
    with no sidecar (None) records what was done."""
    if not write_rows(path, columns, rows):
        return
    say("Wrote %s (%d %s)." % (path, len(rows), noun))
    if sidecar:
        say("Fill in the second column, then append the rows to %s." % sidecar)
    if hint:
        say(hint)


def run(base, decks, targets, paths, reports, language=None, alt_max_chars=120,
        alt_placeholders=(), check_only=False, say=print):
    """Check, report, and remediate every deck; 0 when every deck was read
    and every copy written."""
    alts = pptxremediate.alt_rows(paths.get("image_alt"))
    unknown = set()
    tables = pptxremediate.header_rows(paths.get("table_headers"), unknown)
    for value in sorted(unknown):
        say("WARNING: %s: headers value %r is not one this version understands; "
            "treated as blank" % (paths.get("table_headers"), value))
    titles = pptxremediate.title_rows(paths.get("slide_titles"))
    links = pptxremediate.link_rows(paths.get("bare_links"))
    keep = sidecars.math_keep_rows(paths.get("math_keep"))
    bad = []
    orders = pptxremediate.order_rows(paths.get("reading_order"), bad)
    for key, token in bad:
        say("WARNING: %s: the order for %s isn't a list of shape ids (%r isn't one); its slide is "
            "left as it is." % (paths.get("reading_order"), key, token))
    rules = pptxcheck.placeholder_rules(alt_placeholders)
    clashes = clashing(decks)
    if clashes:
        for key, files in sorted(clashes.items()):
            say("ERROR: %s are one deck in the sidecars' keys (%s), whose rows would be applied "
                "to both; rename all but one." % (" and ".join(files), key))
        return 1
    found, parsed = [], []
    alt_report = OrderedDict()      # key: [sources, reason, current alt]
    table_report = OrderedDict()
    title_report = []
    headings = set()    # the keys of rows drafted from a slide's heading
    own_titles = []     # rows for slides with a title no other slide has
    order_report = []
    link_report = OrderedDict()     # address: [title, [sources], context]
    images = {}
    present = {"alt": set(), "table": set(), "slide": set(), "link": set()}  # every key the decks have
    copies = {}       # image digest: {where: what each copy's alt text is now}
    placed = OrderedDict()  # image digest: [(deck, slide, shape, where)], every copy
    image_found = {}  # image digest: [(name, deck, slide, shape, check, detail)] to decide
    failed = 0
    for name in decks:
        path = os.path.join(base, name)
        try:
            deck = pptxparse.read(path)
        except Exception as exc:
            say("ERROR: %s couldn't be read as a PowerPoint deck: %s" % (name, unreadable(path, exc)))
            failed += 1
            continue
        parsed.append((name, path, deck))
    # A font one deck embeds restricted is restricted in every deck that
    # uses it, whether or not that one embeds it.
    restricted = restricted_fonts(parsed)
    for name, path, deck in parsed:
        found += pptxcheck.check(deck, name, alt_max_chars=alt_max_chars,
                                 alt_placeholders=alt_placeholders, restricted=restricted)
        dname = pptxremediate.deck_name(path)

        def note(shape, check, detail, slide):
            if check not in DECIDE:
                return
            known, _alt = pptxremediate.decision(alts, dname, slide, shape)
            if known:
                return
            if shape.image and shape.image[1]:
                digest, ext = shape.image[1], shape.image[2]
                key = pptxremediate.image_key(digest) + ext
                images.setdefault(digest, (path, shape.image[0], key))
                # Its sources and alt text are every copy's, filled in
                # once every deck is read: the row's decision is theirs,
                # unless its copies show different parts of the image.
                alt_report.setdefault(key, [digest, reason_of(check, detail), None])
                image_found.setdefault(digest, []).append((name, dname, slide, shape, check, detail))
                return
            if slide is None:
                return
            key = pptxremediate.object_key(dname, slide, shape)
            alt_report.setdefault(key, [["%s slide %d" % (name, slide.number)],
                                        reason_of(check, detail),
                                        " ".join((shape.descr or "").split())])

        for slide, shapes in [(s, list(s.all_shapes())) for s in deck.slides] + [
                (None, [x for _part, tops in deck.masters for top in tops for x in top.walk()])]:
            present["slide"].add(pptxremediate.slide_key(dname, slide) if slide else None)
            for shape in shapes:
                if shape.image and shape.image[1]:
                    present["alt"].update((pptxremediate.image_key(shape.image[1]),
                                           pptxremediate.image_key(shape.image[1], dname)))
                    where = ("%s slide %d" % (name, slide.number) if slide is not None
                             else "%s layout or master" % name)
                    now = ("(decorative)" if shape.decorative else
                           " ".join((shape.descr or "").split()) or "(none)")
                    copies.setdefault(shape.image[1], OrderedDict()).setdefault(where, set()).add(now)
                    placed.setdefault(shape.image[1], []).append((dname, slide, shape, where))
                if slide is not None and shape.id:
                    present["alt"].add(pptxremediate.object_key(dname, slide, shape))
                if shape.table is not None:
                    present["table"].add(shape.table.key())
        flagged = set()
        for slide in deck.slides:
            loose = frozenset(id(p) for p in pptxcheck.loose_pieces(slide))
            for shape, check, detail in pptxcheck.alt_items(slide, rules, alt_max_chars, loose):
                note(shape, check, detail, slide)
                # A shape a row decides has the row's alt text, which is
                # compared with the rest; its own is no matter.
                if not pptxremediate.decision(alts, dname, slide, shape)[0]:
                    flagged.add(id(shape))
            for shape in slide.all_shapes():
                if shape.table is None or shape.table.first_row:
                    continue
                key = shape.table.key()
                if key in tables or key in table_report:
                    continue
                guess = census_guess(shape.table)
                table_report[key] = [key, guess, "", "", "",
                                     "%s slide %d" % (name, slide.number),
                                     (slide.title or "")[:60], preview(shape.table),
                                     "TI" if guess else "", ""]
        for slide, shape, check, detail in pptxcheck.crop_items(deck, flagged):
            note(shape, check, detail, slide)
            if not pptxremediate.decision(alts, dname, slide, shape)[0]:
                flagged.add(id(shape))
        def decided(slide, shape):
            # What the copy's alt text will be: a picture one row describes
            # anew no longer shares the alt text it had.
            known, alt = pptxremediate.decision(alts, dname, slide, shape)
            if not known:
                return None if shape.decorative else shape.descr
            return None if alt is None else alt or shape.descr

        for slide, shape, check, detail in pptxcheck.shared_items(deck, flagged, decided):
            note(shape, check, detail, slide)
        rows = untitled_rows(name, dname, deck, titles)
        headings.update(r[0] for r in rows if r[1])
        title_report += rows
        title_report += repeated_titles(name, dname, deck, titles)
        for slide in deck.slides:
            for shape in slide.all_shapes():
                for link in shape.links:
                    if not (link.external and link.text.strip()
                            and pptxcheck.bare(link.text, link.target)):
                        continue
                    present["link"].add(link.target)
                    if link.target in links:
                        continue
                    entry = link_report.setdefault(link.target, [link.tooltip or "", [],
                                                                 link.context[-160:].strip()])
                    where = "%s slide %d" % (name, slide.number)
                    if where not in entry[1]:
                        entry[1].append(where)
        order_report += order_rows(path, name, dname, deck, orders, alts)
        own_titles += kept_titles(dname, deck, titles)
        for shape, check, detail in pptxcheck.master_items(deck, rules, alt_max_chars):
            note(shape, check, detail, None)
    # The images the report names, written where their keys point, so a
    # person can open the one a row is about.
    for digest, (path, part, key) in images.items():
        target = os.path.join(base, key)
        if not os.path.exists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zipfile.ZipFile(path) as zf, open(target, "wb") as out:
                out.write(zf.read(part))
    if not failed:
        unmatched(paths, alts, tables, titles, present, say, orders, links)
    split = cropped_apart(placed)
    parts = one_alt_for_parts(alts, placed, split)
    if parts:
        say("NOTE: %d row(s) of %s give one alt text to copies of a picture cropped to show "
            "different parts of it (%s); a row keyed on each copy's shape (deck/slide-N/shape-M) "
            "can describe each." % (
                len(parts), os.path.basename(paths.get("image_alt") or "image-alt.csv"),
                "; ".join("%s: %s" % (key, ", ".join(wheres[:3]) + (", ..." if len(wheres) > 3
                                                                    else ""))
                          for key, wheres in list(parts.items())[:3])
                + ("; ..." if len(parts) > 3 else "")))
    if own_titles:
        say("NOTE: %d row(s) of %s aren't used: each is for a slide with a title of its own "
            "that no other slide in its deck has, which its copy keeps (%s%s)." % (
                len(own_titles), os.path.basename(paths.get("slide_titles") or "slide-titles.csv"),
                ", ".join(own_titles[:3]), " ..." if len(own_titles) > 3 else ""))
    # A CSV, as every report beside the sources is: a Markdown report
    # there would be read as a book's page on the next run, and the folder
    # taken for a book. audit.py writes one, from the decks, wherever -o says.
    check_csv = reports["slides_check"]
    fl.write_csv(check_csv, found)
    summarize("Checked %d deck(s): " % len(parsed), found, say)
    say("Written to %s." % check_csv)
    font_report(parsed, restricted, targets, say)
    alt_lines, parted = [], False
    for key, (sources, reason, current) in alt_report.items():
        if current is None and sources in split:
            alt_lines += crop_rows(key, image_found[sources])
            parted = True
        else:
            alt_lines.append(alt_row(key, sources, reason, current, copies))
    report(reports["image_alt_missing"], ALT_COLUMNS, alt_lines,
           "picture(s) and object(s) needing alt text", paths["image_alt"], say,
           "Use [decorative] in the Alt column for one that carries no meaning. A "
           "picture's row covers every copy of it, on every slide of every deck; its "
           "image is at the path the row names." + (
               " A copy cropped to show another part of its image than its other copies show "
               "has a row of its own, keyed on its shape, whose Reason names its image."
               if parted else ""))
    report(reports["table_headers_new"], TABLE_COLUMNS, list(table_report.values()),
           "table(s) with no header row marked", paths["table_headers"], say)
    hints = []
    if any(r[3] and r[0] in headings for r in title_report):
        hints.append("A Title drafted from a slide's heading makes the heading its title, in "
                     "place, as PowerPoint's Set as Slide Title does; any other Title for a slide "
                     "with none is added above it, where it's read and not seen.")
    if any(r[3] and r[0] not in headings for r in title_report):
        hints.append("A title for a slide that has one takes its place on the slide, where it's "
                     "seen; the title as it is keeps it.")
    report(reports["slide_titles_new"], TITLE_COLUMNS, title_report,
           "slide(s) with no title, or with a title an earlier slide has",
           paths["slide_titles"], say, " ".join(hints) or None)
    if reports.get("bare_links_new"):
        report(reports["bare_links_new"], LINK_COLUMNS,
               [[url, "", title, "; ".join(sources), context, "", ""]
                for url, (title, sources, context) in link_report.items()],
               "bare link(s), whose text is their address", paths["bare_links"], say,
               "A Replacement that's an address replaces the link's address and its text; any "
               "other replaces its text. A Title is its ScreenTip. A row left blank keeps the "
               "link as it is (docs/bare-links.md).")
    if reports.get("reading_order_new"):
        report(reports["reading_order_new"], ORDER_COLUMNS, order_report,
               "slide(s) read in another order than they're laid out", paths["reading_order"], say,
               "Each Order is drafted from the slide's layout; a blank one leaves the slide as it "
               "is. Shapes that overlap keep their order, since PowerPoint draws in the order a "
               "screen reader reads.")
    if check_only:
        return 1 if failed else 0
    copies = []
    math_rows = OrderedDict()   # (kind, deck, before, after), each repair once
    kept, repairing = set(), False  # the keep rows that kept an equation
    for target in targets:
        if target.format != "source":
            continue                # a conversion's, after this (convert.py)
        os.makedirs(target.output_dir, exist_ok=True)
        totals = Counter()
        written = changed = 0
        plan, replaced = font_plan(target, restricted, say), []
        for name, path, deck in parsed:
            destination = os.path.join(target.output_dir, name)
            if os.path.abspath(destination) == os.path.abspath(path):
                say("ERROR: target %s would write over %s; give it an output_dir of its own."
                    % (target.name, name))
                failed += 1
                continue
            problems, repairs = [], []
            dname = pptxremediate.deck_name(path)
            # A row with a blank Page keeps its equation in every deck.
            named = [row for row in keep if row[0] == "equation" and row[1] in ("", dname)]
            equations = setting(target, "math.repair_equations")
            repairing = repairing or equations
            counts = pptxremediate.remediate(path, destination, alts, tables, titles,
                                             language, deck=dname, orders=orders,
                                             problems=problems, links=links,
                                             equations=equations, fonts=plan, replaced=replaced,
                                             keep_equations={row[2] for row in named},
                                             repairs=repairs)
            for before, after in repairs:
                if after is None:
                    # The deck's own row keeps it, as a page's does a book's,
                    # else the row for every deck.
                    rows = [row for row in named if row[2] == before]
                    kept.update([row for row in rows if row[1]] or rows)
                else:
                    math_rows.setdefault(("equation", dname, before, after), None)
            for key, why in problems:
                if key == pptxremediate.deck_name(path):
                    say("WARNING: %s: in %s, %s." % (target.name, name, why))
                else:
                    say("WARNING: %s: the reading order for %s isn't written: %s." % (
                        target.name, key, why))
            totals.update(counts)
            written += 1
            # What was left as it was isn't a change.
            changed += any(n for key, n in counts.items()
                           if key not in ("skipped", "orders_refused", "titles_kept",
                                          "equations_kept"))
            copies.append((target, name, destination))
        say("%s: %d deck(s) written, %d of them changed: %d picture(s) and object(s) given alt "
            "text and %d marked decorative, %d header row(s) and %d header column(s) marked, "
            "%d slide(s) given the heading they show as their title, in place, %d title(s) "
            "added above their slides, %d deck(s) given the project's language as their "
            "default, and %d given a title in the file's properties, their first slide's."
            % (target.name, written, changed,
               totals["described"], totals["decorative"], totals["header_rows"],
               totals["header_columns"], totals["titles_in_place"], totals["titles"],
               totals["language"], totals["core_title"]))
        if totals["links"] or totals["replaced"]:
            say("%s: %d bare link(s) given a ScreenTip and %d a replacement, as %s says." % (
                target.name, totals["links"], totals["replaced"],
                os.path.basename(paths.get("bare_links") or "bare-links.csv")))
        if totals["equations_repaired"] or totals["equations_kept"]:
            say("%s: %d equation(s) given the characters they mean, %d character(s) in all "
                "(math.repair_equations)%s." % (
                    target.name, totals["equations_repaired"], totals["equation_characters"],
                    "; %d kept as they were, as %s says" % (
                        totals["equations_kept"],
                        os.path.basename(paths.get("math_keep") or "math-keep.csv"))
                    if totals["equations_kept"] else ""))
        if totals["retitled"]:
            say("%s: %d slide(s) given the title %s gives in place of one another slide has." % (
                target.name, totals["retitled"],
                os.path.basename(paths.get("slide_titles") or "slide-titles.csv")))
        if totals["orders"]:
            say("%s: %d slide(s) put in the reading order %s gives." % (
                target.name, totals["orders"],
                os.path.basename(paths.get("reading_order") or "reading-order.csv")))
        if totals["repaired"]:
            say("%s: %d thing(s) PowerPoint couldn't read put right, as Pandoc's PowerPoint "
                "writer leaves them: empty shapes taken out, and prefixes declared that were "
                "used without their namespace." % (target.name, totals["repaired"]))
        for (old, new), (decks_, places, unembedded) in replaced_fonts(replaced).items():
            say("%s: %s replaced with %s in %d deck(s), %d place(s) in all%s." % (
                target.name, old, new, decks_, places,
                ", and its embedded files taken out of %d" % unembedded if unembedded else ""))
        if totals["skipped"]:
            say("WARNING: %s: %d decision(s) not written, for shapes whose id their slide "
                "repeats, which PowerPoint repairs when it opens and saves the deck."
                % (target.name, totals["skipped"]))
    if reports.get("math_repaired"):
        report(reports["math_repaired"], MATH_COLUMNS, list(math_rows), "math repair(s)", None,
               say, "Each is an equation's characters repaired, Before and After written out "
               "in one line, much as PowerPoint's linear format writes an equation; "
               "math.repair_equations turns them off.")
    if paths.get("math_keep"):
        # Only a run that repairs equations can keep one.
        off = () if repairing else ("math.repair_equations",)
        for line in sidecars.keep_warning(os.path.basename(paths["math_keep"]),
                                          [row for row in keep if row not in kept],
                                          "these decks", off + ("math.from_text",)):
            say(line)
    if copies and reports.get("output_check"):
        failed += check_copies(copies, reports["output_check"], tables, alt_max_chars,
                               alt_placeholders, say, orders, links, restricted)
    return 1 if failed else 0


def restricted_fonts(parsed):
    """{typeface: fsType} of the fonts a license restricts that any deck of
    the run embeds so, in the order they're first found."""
    out = OrderedDict()
    for _name, _path, deck in parsed:
        for typeface, fstype in deck.fonts.restricted().items():
            out.setdefault(typeface, fstype)
    return out


def font_report(parsed, restricted, targets, say):
    """The run's word on each restricted font: how many decks use it, how
    many embed it so and how many use it without embedding it, and what
    fonts.restricted does about it."""
    replacing = [t for t in targets if t.format == "source"
                 and value(t, "fonts.restricted", "keep") == "replace"]
    for typeface, fstype in restricted.items():
        # A deck that embeds it with a license that lets it be edited
        # isn't held back by it.
        users = [d for _n, _p, d in parsed
                 if (d.fonts.used.get(typeface) or typeface in d.fonts.embedded)
                 and (typeface not in d.fonts.embedded or d.fonts.embedded[typeface].restricted)]
        embedded = sum(1 for d in users if typeface in d.fonts.restricted())
        stuck = sum(1 for d in users if typeface not in d.fonts.embedded and d.fonts.embedding)
        loose = sum(1 for d in users if typeface not in d.fonts.embedded and not d.fonts.embedding)
        said = []
        if embedded:
            said.append("%d embed it, so PowerPoint opens them read-only where %s isn't "
                        "installed" % (embedded, typeface))
        if stuck:
            said.append("%d use it without embedding it, set to embed their fonts, so "
                        "PowerPoint won't save them there" % stuck)
        if loose:
            said.append("%d use it without embedding it, so it's shown in another font there"
                        % loose)
        nearest = sorted({pptxfonts.nearest(d.fonts, typeface, restricted) or "" for d in users})
        near = ", ".join(n for n in nearest if n) or "none of them have one near it"
        if replacing:
            then = ("%s copies use another font in its place (fonts.restricted: replace): the "
                    "one fonts.replacements names, else the nearest each deck uses (%s)." % (
                        " and ".join("%s's" % t.name for t in replacing), near))
        else:
            then = ("Set fonts.restricted: replace for the copies to use another font in its "
                    "place: the nearest each deck uses (%s), or the one fonts.replacements "
                    "names." % near)
        say("WARNING: %d of %d deck(s) use the restricted font %s, whose license %s: %s. %s" % (
            len(users), len(parsed), typeface,
            "lets a deck embed it for preview and print only" if fstype & pptxfonts.PREVIEW_PRINT
            else "forbids embedding it", "; ".join(said), then))


def value(target, key, default=None):
    """A target's setting as it is, or default for one it doesn't have."""
    try:
        found = target[key]
    except (KeyError, TypeError):
        return default
    return default if found is None else found


def font_plan(target, restricted, say):
    """{typeface: the font in its place, or None for the nearest each deck
    uses} for a target's copies: each font fonts.replacements names, and,
    with fonts.restricted: replace, each the run finds restricted."""
    names = value(target, "fonts.replacements", {}) or {}
    if not isinstance(names, dict):
        say("WARNING: %s: fonts.replacements is a map of fonts, each to the one to use in its "
            "place (Avenir Next: Arial), and this isn't one; it's left out." % target.name)
        names = {}
    plan = OrderedDict((str(k), str(v) if v else None) for k, v in names.items())
    if value(target, "fonts.restricted", "keep") == "replace":
        for typeface in restricted:
            plan.setdefault(typeface, None)
    return plan


def replaced_fonts(replaced):
    """{(typeface, the font in its place): (decks, places, decks it was
    embedded in)} from what remediate() was told."""
    out = OrderedDict()
    for old, new, places, embedded in replaced:
        decks, total, unembedded = out.get((old, new), (0, 0, 0))
        out[(old, new)] = (decks + 1, total + places, unembedded + bool(embedded))
    return out


def untitled_rows(name, dname, deck, titles):
    """slide-titles-new.csv's rows for the slides with no title that the
    sidecar doesn't decide yet, each drafted from the heading it shows,
    when it shows one (pptxtitle.heading()), for a person to review, which
    its copy then makes its title in place: numbered "Heading (2)" when an
    earlier slide has that title, or is to have it."""
    seen, rows = Counter(), []
    for slide in deck.slides:
        key = pptxremediate.slide_key(dname, slide)
        title = slide.title or titles.get(key)
        if title:
            seen[pptxcheck.same_title(title)] += 1
            continue
        where = "%s slide %d%s" % (name, slide.number,
                                   ", layout %s" % slide.layout if slide.layout else "")
        shape = pptxtitle.heading(slide)
        if shape is None:
            rows.append([key, "", where, "", ""])
            continue
        text = pptxtitle.collapsed(shape.text)
        seen[pptxcheck.same_title(text)] += 1
        count = seen[pptxcheck.same_title(text)]
        rows.append([key, text if count == 1 else "%s (%d)" % (text, count),
                     "%s, its heading in %s" % (where, shape.name or "shape %s" % shape.id),
                     "TI", ""])
    return rows


def repeated_titles(name, dname, deck, titles):
    """slide-titles-new.csv's rows for the slides whose title an earlier
    slide in the deck has, as PowerPoint's checker compares them, the
    sidecar not deciding them yet: the second drafted "Title (2)", and so
    on, for a person to review."""
    first, count, rows = {}, Counter(), []
    for slide in deck.slides:
        if not slide.title:
            continue
        same = pptxcheck.same_title(slide.title)
        count[same] += 1
        if same not in first:
            first[same] = slide.number
            continue
        key = pptxremediate.slide_key(dname, slide)
        if key not in titles:
            rows.append([key, "%s (%d)" % (slide.title, count[same]),
                         "%s slide %d, titled as slide %d is" % (name, slide.number, first[same]),
                         "TI", ""])
    return rows


def kept_titles(dname, deck, titles):
    """The keys of slide-titles.csv's rows that a copy doesn't use: for a
    slide with a title of its own that no other slide in its deck has,
    as when a slide that had none, or had another's, has been given its
    own in PowerPoint since its row was written."""
    shared = Counter(pptxcheck.same_title(s.title) for s in deck.slides if s.title)
    out = []
    for slide in deck.slides:
        key = pptxremediate.slide_key(dname, slide)
        if slide.title and shared[pptxcheck.same_title(slide.title)] < 2 \
                and titles.get(key) and titles[key] != slide.title:
            out.append(key)
    return out


def sidecar_decorative(alts, dname, slide):
    """The ids of a slide's shapes that its copy marks decorative, as the
    image-alt sidecar decides, so aren't read; a shape whose id another
    on the slide has too is left as it is, as a copy leaves it."""
    count = Counter(s.id for s in slide.all_shapes() if s.id)
    return {s.id for s in slide.shapes if s.id and count[s.id] == 1
            and pptxremediate.decision(alts, dname, slide, s) == (True, None)}


def order_rows(path, name, dname, deck, orders, alts=None):
    """reading-order-new.csv's rows for a deck: each slide read in another
    order than it's laid out that the sidecar hasn't decided, with an order
    drafted from its layout and, in Shapes, what each id is. A shape the
    image-alt sidecar marks decorative (alts) isn't read, as in the copy."""
    flagged = []
    for slide in deck.slides:
        gone = sidecar_decorative(alts or {}, dname, slide)
        if pptxremediate.slide_key(dname, slide) not in orders \
                and pptxcheck.reading_order(slide, deck.width, deck.height, gone):
            flagged.append((slide, gone))
    rows = []
    if not flagged:
        return rows
    with zipfile.ZipFile(path) as zf:
        for slide, gone in flagged:
            read = pptxcheck.read_shapes(slide, deck.width, deck.height, gone)
            try:
                kids = pptxorder.tree(pptxparse.part_text(zf.read(slide.part))[0], slide)
            except (KeyError, UnicodeDecodeError):
                kids = None
            ids, note = pptxorder.draft(kids, read) if kids else (
                None, "the slide's shapes couldn't be read in order")
            rows.append([pptxremediate.slide_key(dname, slide), " ".join(ids or []),
                         "%s slide %d" % (name, slide.number),
                         "; ".join(pptxorder.label(s) for s in read), note,
                         "TI" if ids else "", ""])
    return rows


def setting(target, key, default=False):
    """A target's setting, or default for one that has none."""
    try:
        return bool(target[key])
    except (KeyError, TypeError):
        return default


def check_copies(copies, path, tables, alt_max_chars, alt_placeholders, say, orders=None,
                 links=None, restricted=None):
    """The output check, on the copies: what's left to do in each, a table
    the sidecar says has no headers not counted against it, nor a slide
    put in the order the sidecar gives. Returns the number of copies that
    couldn't be read back."""
    found, unreadable = [], 0
    for target, name, destination in copies:
        try:
            deck = pptxparse.read(destination)
        except Exception as exc:
            say("ERROR: %s's copy of %s can't be read back: %s" % (target.name, name, exc))
            unreadable += 1
            continue
        found += pptxcheck.check(deck, os.path.join(os.path.basename(target.output_dir), name),
                                 kind="pptx", alt_max_chars=alt_max_chars,
                                 alt_placeholders=alt_placeholders, tables=tables,
                                 orders=pptxremediate.slide_orders(
                                     orders or {}, pptxremediate.deck_name(name)),
                                 links=pptxremediate.decided_links(links or {}),
                                 restricted=restricted)
    if found:
        fl.write_csv(path, found)
    elif os.path.exists(path):
        os.remove(path)
    summarize("Output check: %d deck(s), " % len(copies), found, say)
    if found:
        say("Written to %s." % path)
    return unreadable
