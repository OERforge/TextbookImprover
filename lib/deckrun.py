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
  can look at it; and a row for each other object (a chart, an embedded
  object, a group) that needs alt text, keyed on deck/slide-N/shape-M;
- table-headers-new.csv: each table with no header row marked, keyed on
  its content as a book's tables are, with the table census's guess;
- slide-titles-new.csv: each slide with no title, and each whose title
  an earlier slide in its deck has, keyed on deck/slide-N, the second of
  them drafted "Title (2)", the third "Title (3)";
- reading-order-new.csv: each slide read in another order than it's laid
  out, keyed on deck/slide-N, with an order drafted for a person to
  review, as near to the layout as it can come without drawing two
  shapes that overlap the other way round (pptxorder.py);
- slides-check.csv: every finding, in the output check's format; and,
  once a source target has written its copies, output-check.csv, what's
  left to do in them.

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

import findings as fl
import pptxcheck
import pptxorder
import pptxparse
import pptxremediate
import tablecensus

ALT_COLUMNS = ["Image", "Alt", "Source", "Reason", "CurrentAlt", "Drafted by", "Reviewed"]
TABLE_COLUMNS = ["key", "headers", "split-at", "caption-rows", "part-captions", "source",
                 "label", "preview", "drafted-by", "reviewed"]
TITLE_COLUMNS = ["Slide", "Title", "Source", "Drafted by", "Reviewed"]
ORDER_COLUMNS = ["Slide", "Order", "Source", "Shapes", "Note", "Drafted by", "Reviewed"]
# The alt-text findings that ask a person for a decision.
DECIDE = ("pptx-object-no-alt", "pptx-shape-no-alt", "pptx-alt-is-file-name",
          "pptx-alt-placeholder", "pptx-alt-auto-generated", "pptx-alt-too-long",
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
            "pptx-alt-placeholder": "says nothing (%s)" % detail.split(":")[0],
            "pptx-alt-auto-generated": "generated by Office",
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


def deck_key(key):
    """Whether an image-alt key is a deck's: a picture's content, or an
    object on a slide."""
    return key.startswith("media/") or "/media/" in key or "/slide-" in key


def unmatched(paths, alts, tables, titles, present, say, orders=()):
    """Said once for each sidecar: rows whose key no deck has. A picture's
    key is its content, so a row stops matching only when the picture is
    replaced; an object's and a slide's are the ids PowerPoint gave them,
    which last until the slide or the shape is deleted. Either way, the
    deck's new key is in this run's report."""
    for kind, rows, setting, what in (
            ("alt", [k for k in alts if deck_key(k)], "image_alt", "picture or object"),
            ("table", list(tables), "table_headers", "table"),
            ("slide", list(titles), "slide_titles", "slide"),
            ("slide", list(orders), "reading_order", "slide")):
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
    """A report and what to do with it, said as a book's run says it."""
    if not write_rows(path, columns, rows):
        return
    say("Wrote %s (%d %s)." % (path, len(rows), noun))
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
    order_report = []
    images = {}
    present = {"alt": set(), "table": set(), "slide": set()}   # every key the decks have
    copies = {}       # image digest: {where: what each copy's alt text is now}
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
        found += pptxcheck.check(deck, name, alt_max_chars=alt_max_chars,
                                 alt_placeholders=alt_placeholders)
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
                # once every deck is read: the row's decision is theirs.
                alt_report.setdefault(key, [digest, reason_of(check, detail), None])
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
                if slide is not None and shape.id:
                    present["alt"].add(pptxremediate.object_key(dname, slide, shape))
                if shape.table is not None:
                    present["table"].add(shape.table.key())
        for slide in deck.slides:
            loose = frozenset(id(p) for p in pptxcheck.loose_pieces(slide))
            for shape, check, detail in pptxcheck.alt_items(slide, rules, alt_max_chars, loose):
                note(shape, check, detail, slide)
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
            if not slide.title:
                key = pptxremediate.slide_key(dname, slide)
                if key not in titles:
                    title_report.append([key, "", "%s slide %d%s" % (
                        name, slide.number, ", layout %s" % slide.layout if slide.layout else ""),
                        "", ""])
        title_report += repeated_titles(name, dname, deck, titles)
        order_report += order_rows(path, name, dname, deck, orders)
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
        unmatched(paths, alts, tables, titles, present, say, orders)
    # A CSV, as every report beside the sources is: a Markdown report
    # there would be read as a book's page on the next run, and the folder
    # taken for a book. audit.py writes one, from the decks, wherever -o says.
    check_csv = reports["slides_check"]
    fl.write_csv(check_csv, found)
    summarize("Checked %d deck(s): " % len(parsed), found, say)
    say("Written to %s." % check_csv)
    report(reports["image_alt_missing"], ALT_COLUMNS,
           [alt_row(key, sources, reason, current, copies)
            for key, (sources, reason, current) in alt_report.items()],
           "picture(s) and object(s) needing alt text", paths["image_alt"], say,
           "Use [decorative] in the Alt column for one that carries no meaning. A "
           "picture's row covers every copy of it, on every slide of every deck; its "
           "image is at the path the row names.")
    report(reports["table_headers_new"], TABLE_COLUMNS, list(table_report.values()),
           "table(s) with no header row marked", paths["table_headers"], say)
    report(reports["slide_titles_new"], TITLE_COLUMNS, title_report,
           "slide(s) with no title, or with a title an earlier slide has",
           paths["slide_titles"], say,
           "A title for a slide that has one takes its place on the slide, where it's seen; "
           "the title as it is keeps it." if any(r[3] for r in title_report) else None)
    if reports.get("reading_order_new"):
        report(reports["reading_order_new"], ORDER_COLUMNS, order_report,
               "slide(s) read in another order than they're laid out", paths["reading_order"], say,
               "Each Order is drafted from the slide's layout; a blank one leaves the slide as it "
               "is. Shapes that overlap keep their order, since PowerPoint draws in the order a "
               "screen reader reads.")
    if check_only:
        return 1 if failed else 0
    copies = []
    for target in targets:
        if target.format != "source":
            say("NOTE: target %s is format %s, which isn't written for PowerPoint decks yet; "
                "format: source is, a copy of each deck with the sidecars' decisions written "
                "in (ROADMAP.md, slides)." % (target.name, target.format))
            continue
        os.makedirs(target.output_dir, exist_ok=True)
        totals = Counter()
        written = changed = 0
        for name, path, deck in parsed:
            destination = os.path.join(target.output_dir, name)
            if os.path.abspath(destination) == os.path.abspath(path):
                say("ERROR: target %s would write over %s; give it an output_dir of its own."
                    % (target.name, name))
                failed += 1
                continue
            problems = []
            counts = pptxremediate.remediate(path, destination, alts, tables, titles,
                                             language, deck=pptxremediate.deck_name(path),
                                             orders=orders, problems=problems)
            for key, why in problems:
                say("WARNING: %s: the reading order for %s isn't written: %s." % (
                    target.name, key, why))
            totals.update(counts)
            written += 1
            changed += any(n for key, n in counts.items()
                           if key not in ("skipped", "orders_refused"))
            copies.append((target, name, destination))
        say("%s: %d deck(s) written, %d of them changed: %d picture(s) and object(s) given alt "
            "text and %d marked decorative, %d header row(s) and %d header column(s) marked, "
            "%d title(s) added above their slides, %d deck(s) given the project's language as "
            "their default, and %d given a title in the file's properties, their first slide's."
            % (target.name, written, changed,
               totals["described"], totals["decorative"], totals["header_rows"],
               totals["header_columns"], totals["titles"], totals["language"],
               totals["core_title"]))
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
        if totals["skipped"]:
            say("WARNING: %s: %d decision(s) not written, for shapes whose id their slide "
                "repeats, which PowerPoint repairs when it opens and saves the deck."
                % (target.name, totals["skipped"]))
    if copies and reports.get("output_check"):
        failed += check_copies(copies, reports["output_check"], tables, alt_max_chars,
                               alt_placeholders, say, orders)
    return 1 if failed else 0


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


def order_rows(path, name, dname, deck, orders):
    """reading-order-new.csv's rows for a deck: each slide read in another
    order than it's laid out that the sidecar hasn't decided, with an order
    drafted from its layout and, in Shapes, what each id is."""
    flagged = [s for s in deck.slides if pptxcheck.reading_order(s, deck.width, deck.height)
               and pptxremediate.slide_key(dname, s) not in orders]
    rows = []
    if not flagged:
        return rows
    with zipfile.ZipFile(path) as zf:
        for slide in flagged:
            read = pptxcheck.read_shapes(slide, deck.width, deck.height)
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


def check_copies(copies, path, tables, alt_max_chars, alt_placeholders, say, orders=None):
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
                                     orders or {}, pptxremediate.deck_name(name)))
    if found:
        fl.write_csv(path, found)
    elif os.path.exists(path):
        os.remove(path)
    summarize("Output check: %d deck(s), " % len(copies), found, say)
    if found:
        say("Written to %s." % path)
    return unreadable
