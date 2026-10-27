"""
sidecars.py -- what a sidecar's values mean, read the same way by every
part of the pipeline that reads them.

The filter (figures-and-tables.lua) and the Python that writes a book's
decisions back into its sources read the same image-alt sidecar. They
had each their own idea of the decorative marker: the filter took
"[decorative]" or "decorative" in any case, the Python only the exact
"[decorative]", so a row saying "Decorative" made an image decorative
on the pages and gave the author's copy the alt text "Decorative".

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
import errno
import io
import os
import re
import stat
import tempfile
import unicodedata

# Accepted spellings of the decorative marker, matched case-insensitively
# after trimming. figures-and-tables.lua's DECORATIVE_MARKERS is the same
# list; tests/run-unit-tests.py holds the two together.
DECORATIVE_MARKERS = ("[decorative]", "decorative")


def is_decorative(value):
    """Whether a sidecar's alt text is the decorative marker."""
    return (value or "").strip().lower() in DECORATIVE_MARKERS


# Excel opens a CSV that starts with a byte-order mark as UTF-8, and one
# that doesn't in the computer's code page, Windows-1252 in the US, where
# an en dash shows as "â€“" and a minus sign as "âˆ’"; its "CSV UTF-8"
# writes the mark. So every CSV a run writes for a person, a report or
# rows to adopt as a sidecar, is written in CSV_ENCODING, which puts the
# mark first, and every sidecar is given it (rewrite_as_utf8). A sidecar
# is read as text reads it, which drops the mark at the file's start, and
# through csv_lines, which drops one at a line's start, where appending a
# report to a sidecar, its header row and all, leaves it.
# figures-and-tables.lua and math-repair.lua drop both as they read.
CSV_ENCODING = "utf-8-sig"
BOM = "\ufeff"


def csv_lines(fh):
    """A CSV file's lines, for csv.reader or csv.DictReader, each without
    a byte-order mark at its start."""
    for line in fh:
        yield line.lstrip(BOM)


def dict_rows(fh):
    """A sidecar's rows as csv.DictReader reads them, through csv_lines,
    but a header row repeated partway, as appending a report leaves one:
    a row whose first value is its first column's name, which the other
    readers, the filter's among them, skip too."""
    reader = csv.DictReader(csv_lines(fh))
    for row in reader:
        first = (reader.fieldnames or [""])[0]
        if first.strip() and (row.get(first) or "").strip().lower() == first.strip().lower():
            continue
        yield row


def pandoc_uri(path):
    """A path as Pandoc's readers write an image's (escapeURI, in
    Text/Pandoc/URI.hs at 3.12.1): white space, as Haskell's isSpace has
    it, and <>|"{}[]^` percent-encoded, each byte of their UTF-8."""
    import unicodedata

    def spaced(c):
        n = ord(c)
        return c == " " or 9 <= n <= 13 or n == 0xA0 or (
            n > 0x377 and unicodedata.category(c) == "Zs")
    return "".join("".join("%%%02X" % b for b in c.encode("utf-8"))
                   if spaced(c) or c in '<>|"{}[]^`' else c for c in path)


def page_media_key(stem, path):
    """The image-alt key the filter gives a picture of the page stem
    whose path, as Pandoc's reader writes it, is in media/: the page's
    name first (figures-and-tables.lua's qualify_media), as the report
    keys it, without the extension; None for any other path. Meant for a
    Word file's media, where every file's are media/rIdN, it holds for a
    page's in a book's own media/ folder too, as the CNX unpacker writes
    one, and a copy has to find the row by it as the pages do."""
    if not stem or not path.startswith("media/"):
        return None
    return stem + "/" + os.path.splitext(path)[0]


# The code pages Excel's plain "CSV" saves a file in, in the US and
# Western Europe, as others report Excel's saves (not tried here, where
# there's no Excel): Windows Excel's "CSV (Comma delimited)" in
# Windows-1252, the computer's ANSI code page there, and Excel for Mac's
# "Comma Separated Values" in Mac OS Roman, Excel 2011 for Mac ending each
# line with a CR alone and Excel 2016 for Mac with CR LF, as Windows does.
# Each is Python's codec for it, its name, the suffix the file as it was
# is kept under, and the saves that write it.
WINDOWS_1252 = ("cp1252", "Windows-1252", "windows-1252",
                "as Windows Excel's plain \"CSV\" saves a file in the US and Western Europe")
MAC_ROMAN = ("mac_roman", "Mac OS Roman", "mac-roman",
             "as Excel for Mac's plain \"CSV\" saves a file in the US and Western Europe")
SAVE_AS_UTF8 = "Save it as UTF-8: from Excel, as \"CSV UTF-8 (Comma delimited)\"."

# Read in the wrong one of those code pages, a line's punctuation turns
# into letters and its letters into other letters or marks, and some sit
# where text's never do, which is how the right one is told (misplaced).
# These each code page reads alike, so they tell neither from the other,
# wherever they sit (M±SD).
ALIKE = "\u00a2\u00a3\u00a9\u00b1\u00b5"
# Letters text doesn't have alone, where a sign read in the wrong one is:
# Mac OS Roman's dashes, €, À, Ã, Õ, Œ, œ, ¬, √, ä, é, ö, and û read as
# Windows-1252, and Windows-1252's bullet read as Mac OS Roman. Others
# alone are text's: à, é, ñ, ö, å, ä, Ç, Ä, Ö, Å, Ø, as words, units,
# abbreviations, or the names of letters (o. ä.); Ñ alone is too, seldom,
# as an em dash is often.
ALONE = "\u00d0\u00d1\u00db\u00ca\u00cb\u00cc\u00cd\u00ce\u00cf\u00c2\u00c3\u0160\u017d\u0161\u017e" \
    "\u00ef"
# Signs text never has, Mac OS Roman's § and ¶ read as Windows-1252.
NEVER = "\u00a4\u00a6"
# What text has between letters, besides a math sign: an apostrophe, a
# dash, a middle dot, or an ellipsis (don’t, Hawai‘i, test–retest, l·l).
BETWEEN_LETTERS = "\u2019\u2018\u2013\u2014\u00b7\u2026"
SUPERSCRIPTS = "\u00b9\u00b2\u00b3"
# What Windows-1252 reads where Mac OS Roman's ‡ and ˚ follow a number, as
# a note's mark and a degree are typed (1‡, 45˚): à and û.
AFTER_DIGIT = "\u00e0\u00fb"
FRACTIONS = "\u00bc\u00bd\u00be"


def _letter(char):
    """Whether char is a letter, a modifier letter such as ˆ not one."""
    return char.isalpha() and unicodedata.category(char) != "Lm"


def _latin(char):
    """Whether char is a Latin letter."""
    return _letter(char) and (char.isascii() or unicodedata.name(char, "").startswith("LATIN"))


def misplaced(line):
    """How many of line's characters outside ASCII sit where text's don't,
    as a line read in the wrong code page has them:
    - a Latin capital after a small letter, or after a letter before a
      small one, or between capitals before a small one, or after a digit
      before a small one (donÕt, cafÈ, MŸller, OÕNeill, 1990Õs, 10Êkm), and
      one at a word's start before a capital and a small letter
      (ÁAtención);
    - a small Latin letter before a capital, but ß (ìHelloî, 25ûC, but
      STRAßE), and ª after a small letter (Colaª);
    - a Latin letter between digits, and à or û after a digit but in a
      word, as Mac OS Roman's ‡ and ˚ read there (1990ñ2000, 1à, 45û);
    - a letter text doesn't have alone, alone (a Ð b, ï item), ä after a
      number but in a word, as Mac OS Roman's ‰ reads there (5 ä), and ƒ
      beside a letter (ƒcole);
    - a third letter outside ASCII in a row, a small one among them, or a
      fourth, as Cyrillic or Greek read as Latin letters has (Ïðèâåò,
      ÖÐÎÄ);
    - a mark or a sign between letters, but those text has there (M‰rz,
      a◊b, na•ve);
    - a spacing accent beside a letter or another character outside ASCII,
      or before a number, but ´ after a letter or a digit (1990´s, 5´),
      ¯ after a letter (x¯), and ˚ after a digit (25˚C), as Mac users type a
      degree (f¸r, ‰ˆ¸, ¯ 25 mm);
    - a superscript after a space, ¹ between a digit and a letter, as Mac
      OS Roman's π reads there, a soft hyphen but in a word, and a fraction
      after a letter or before a capital (p ² 0.05, 2¹r, a - b, 10 k½,
      25¼C);
    - ¡ or ¿ after a letter or a digit, or with no ! or ? after it (100 ¡C);
    - ¥ at a field's start before a space and a letter, as a bullet is
      (¥ item);
    - and ¤ or ¦ anywhere (Section ¤ 4.2).
    A character each code page reads alike counts for nothing."""
    count = run = 0
    small = False
    for at, char in enumerate(line):
        if char.isascii() or char in ALIKE:
            run, small = 0, False
            continue
        before = line[at - 1] if at else " "
        after = line[at + 1] if at + 1 < len(line) else " "
        category = unicodedata.category(char)
        if _letter(char):
            latin = _latin(char)
            run, small = run + 1, small or char.islower()
            count += bool(
                (latin and char.isupper()
                 and ((_letter(before) and (before.islower() or after.islower()))
                      or (before.isupper() and after.isupper() and line[at + 2:at + 3].islower())
                      or (before.isdigit() and after.islower())
                      or (not _letter(before) and after.isupper()
                          and line[at + 2:at + 3].islower())))
                or (latin and char.islower() and char != "\u00df" and after.isupper())
                or (char == "\u00aa" and before.islower())
                or (latin and before.isdigit() and (after.isdigit()
                                                    or (char in AFTER_DIGIT and not _letter(after))))
                or (char == "\u00e4" and not _letter(after)
                    and (before.isdigit() or (at > 1 and before == " " and line[at - 2].isdigit())))
                or (char in ALONE and not _letter(before) and not _letter(after))
                or (char == "\u0192" and (_letter(before) or _letter(after)))
                or run > 3 or (run > 2 and small))
            continue
        run, small = 0, False
        if char in "\u00a1\u00bf":
            count += before.isalnum() or ("!" if char == "\u00a1" else "?") not in line[at + 1:]
        elif char in NEVER:
            count += 1
        elif char == "\u00a5":
            count += ((not at or before in ',"\t') and after == " "
                      and _letter(line[at + 2:at + 3] or " "))
        elif char in SUPERSCRIPTS:
            count += before.isspace() or (char == "\u00b9" and before.isdigit() and _letter(after))
        elif char == "\u00ad":
            count += not (_letter(before) and _letter(after))
        elif char in FRACTIONS:
            count += _letter(before) or after.isupper()
        elif category in ("Sk", "Lm"):
            count += ((_letter(before) or _letter(after) or not before.isascii()
                       or not after.isascii() or after.isdigit()
                       or (after.isspace() and line[at + 2:at + 3].isdigit()))
                      and not ((char == "\u00b4" and before.isalnum())
                               or (char == "\u00af" and _letter(before))
                               or (char == "\u02da" and before.isdigit())))
        else:
            count += (not char.isspace() and char not in BETWEEN_LETTERS and category != "Sm"
                      and _letter(before) and _letter(after))
    return count


def _lines(data):
    """data's lines, each with its end as written, so that joined they're
    data again."""
    return re.findall(rb"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$", data)


def read_code_page(path, data=None):
    """A sidecar at path that isn't UTF-8, as Excel's plain "CSV" saves one,
    read as it was written: read as UTF-8, each of its characters outside
    ASCII was a U+FFFD on the pages, and a Python reader stopped with a
    traceback. The lines that aren't UTF-8 are read in one of the code
    pages Excel saves in (above): the one with fewer characters misplaced,
    or, where they have as many, Mac OS Roman when those lines end with a
    CR alone and Windows-1252 otherwise. A line that is UTF-8, as rows
    appended from a report are, is kept as it is. Returns ((each line as
    read, its end as written; the code page; the indexes of the lines read
    in it; and of those kept as UTF-8 that hold a character outside ASCII),
    None); (None, None) for a file that's UTF-8 or isn't a file; or (None,
    what to stop with), when a line holds a control character, which no
    text a spreadsheet saves does, when the file is UTF-16, or when every
    line read in the code page, two of them or more, reads with a
    character misplaced in each code page, or in Mac OS Roman where
    Windows-1252 has no character for a byte, as a file saved in another
    code page reads. data: the file's bytes, read here when not given."""
    if data is None:
        if not os.path.isfile(path):
            return None, None
        with open(path, "rb") as fh:
            data = fh.read()
    try:
        data.decode("utf-8")
        return None, None
    except UnicodeDecodeError:
        pass
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None, ("%s is UTF-16, as Excel's \"Unicode Text\" saves a file, its columns "
                      "apart by tabs, which is no CSV. %s" % (path, SAVE_AS_UTF8))
    pieces = _lines(data)
    mark = BOM.encode("utf-8")

    def read(index, codec):
        # A mark at the line's start is UTF-8's, as a reader takes it.
        piece = pieces[index]
        if codec != "utf-8" and piece.startswith(mark):
            return BOM + piece[len(mark):].decode(codec)
        return piece.decode(codec)

    legacy, kept = [], []
    for index, piece in enumerate(pieces):
        try:
            piece.decode("utf-8")
        except UnicodeDecodeError:
            legacy.append(index)
            control = re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", piece)
            if control:
                return None, ("%s: line %d isn't UTF-8, and holds a control character (byte "
                              "0x%02X), which no text a spreadsheet saves does. %s"
                              % (path, index + 1, piece[control.start()], SAVE_AS_UTF8))
        else:
            if not piece.isascii():
                kept.append(index)
    ended = [pieces[i] for i in legacy if pieces[i].endswith((b"\r", b"\n"))] \
        or [p for p in pieces if p.endswith((b"\r", b"\n"))]
    cr_alone = bool(ended) and all(p.endswith(b"\r") for p in ended)
    readings, trouble = {}, {}
    for page in (WINDOWS_1252, MAC_ROMAN):
        lines = {}
        try:
            for index in legacy:
                lines[index] = read(index, page[0])
        except UnicodeDecodeError as exc:
            trouble[page] = "line %d has byte 0x%02X, which is no character in it" % (
                index + 1, exc.object[exc.start])
            continue
        odd = {index: misplaced(lines[index]) for index in legacy}
        readings[page] = (lines, sum(odd.values()), [i for i in legacy if odd[i]])
        if readings[page][2]:
            first = readings[page][2][0]
            trouble[page] = "line %d reads \"%s\", a character misplaced" % (
                first + 1, shown(lines[first]))
    if all(page in trouble and (page not in readings or readings[page][2] == legacy)
           for page in (WINDOWS_1252, MAC_ROMAN)) \
            and (len(legacy) > 1 or WINDOWS_1252 not in readings):
        return None, ("%s isn't UTF-8, and doesn't read as Windows-1252 (%s) or as Mac OS Roman "
                      "(%s), the code pages Excel's plain \"CSV\" uses in the US and Western "
                      "Europe, so it was saved in another. %s"
                      % (path, trouble[WINDOWS_1252], trouble[MAC_ROMAN], SAVE_AS_UTF8))
    preferred = MAC_ROMAN if cr_alone else WINDOWS_1252
    page = min(readings, key=lambda page: (readings[page][1], page is not preferred))
    lines = readings[page][0]
    return ([lines[index] if index in lines else read(index, "utf-8")
             for index in range(len(pieces))], page, legacy, kept), None


def shown(line):
    """line as a warning shows it, its end dropped and its characters that
    show as nothing named (a no-break space, a soft hyphen)."""
    return "".join("<U+%04X>" % ord(c) if unicodedata.category(c) in ("Cf", "Zs") and c != " "
                   else c for c in line.lstrip(BOM).rstrip("\r\n"))


# The extended attributes a rewritten sidecar keeps besides a person's own
# (user.*): its access control list and its SELinux label (_owned).
KEPT_ATTRIBUTES = ("system.posix_acl_access", "security.selinux")


def _owned(path, like):
    """path given the owner and the mode of like, as far as this process
    may: a run as root keeps a person's sidecar theirs, and one that isn't
    keeps its group, where it's in it, as a shared folder's people are.
    And on Linux the extended attributes that say who may use it or are a
    person's own (KEPT_ATTRIBUTES), its access control list among them, so
    that a person given a file of a shared folder by one keeps it; not
    those that describe its contents, as integrity measurement's do
    (security.ima, security.evm), which the new contents would fail.
    Python reads none on macOS or Windows."""
    status = os.stat(like)
    try:
        os.chmod(path, status.st_mode & 0o7777)
    except OSError:
        pass
    if hasattr(os, "chown"):
        try:
            os.chown(path, status.st_uid, status.st_gid)
        except OSError:
            try:
                os.chown(path, -1, status.st_gid)
            except OSError:
                pass
    if hasattr(os, "listxattr"):
        try:
            names = os.listxattr(like)
        except OSError:
            names = []
        for name in names:
            if not (name.startswith("user.") or name in KEPT_ATTRIBUTES):
                continue
            try:
                os.setxattr(path, name, os.getxattr(like, name))
            except OSError:
                pass


def owner_of(status):
    """The name of the user a file belongs to, or its number where the
    system has no name for it."""
    try:
        import pwd
        return pwd.getpwuid(status.st_uid).pw_name
    except (ImportError, KeyError):
        return "number %d" % status.st_uid


def _look(path):
    """A sidecar's bytes, or what keeps the run from reading one that's
    there: (None, None, None, False) for one that isn't, and (None, why,
    what to do, whether it stops the run), clauses, for one it can't read.
    The run goes on without one this user may not read, which is what to
    do something about (Rob, 2026-10-26: "assume that users will be sloppy
    about permissions but files in the directory are there for a
    reason"), and without a link to nothing, a folder, and something other
    than a file, as a pipe is, which reading would wait on. Any other error
    reading it, a disk's, or a network share's gone stale, stops the run,
    which would otherwise make a book without what the sidecar holds, as
    it did before."""
    if not path or not os.path.lexists(path):
        return None, None, None, False
    if not os.path.exists(path):
        try:
            return None, "is a link to %s, which isn't there" % os.readlink(path), None, False
        except OSError:
            return None, "is a link that leads nowhere", None, False
    if os.path.isdir(path):
        return None, "is a folder, not a file", None, False
    if not os.path.isfile(path):
        return None, "isn't a file but a pipe or a device", None, False
    try:
        with open(path, "rb") as fh:
            return fh.read(), None, None, False
    except OSError as exc:
        why = "can't be read (%s)" % (exc.strerror or exc)
        if exc.errno not in (errno.EACCES, errno.EPERM):
            return None, why, None, True
        try:
            status = os.stat(path)
            if hasattr(os, "geteuid") and os.geteuid() != status.st_uid:
                why += "; it belongs to %s" % owner_of(status)
        except OSError:
            pass
        return None, why, "give the user running this permission to read it", False


def _read(path):
    """A sidecar's bytes, and what keeps the run from reading one that's
    there (_look): (None, None) for one that isn't."""
    return _look(path)[:2]


def unreadable(path):
    """What to say of a sidecar at path that's there but can't be read, to
    a tool that can do nothing without it; None for one that can be, or
    isn't there."""
    _, why, remedy, _ = _look(path)
    if not why:
        return None
    return "%s %s.%s" % (path, why, " To use it, %s." % remedy if remedy else "")


def _unread(path, why, remedy):
    """What a run says of a sidecar that's there and can't be read."""
    return ("WARNING: %s %s, so this run goes on without it, and leaves it as it is.%s"
            % (path, why, " To use it, %s." % remedy if remedy else ""))


MAY_NOT_WRITE = ("this user may not write it",
                 "give the user running this permission to write it")


def _kept(path, beside=False):
    """Why the run leaves a sidecar at path as it is rather than rewriting
    it, each a clause and what would let a run rewrite it; none for one it
    may. Of one's own: one with no write bit is read-only, even to root,
    whom os.access lets write it, and one this user may not write
    otherwise is said to be that; one with another link to it would be
    parted from it by the rewrite, a new file moved into its place; and one
    whose folder this user can't write has nowhere for the new file, nor,
    for one whose file as it was is kept beside it (beside, _keep), a
    link's folder for that. Another user's, whose owner a run that isn't
    root can't keep, is read and left to its owner (Rob, 2026-10-26: "If
    there are files owned by other users but in the correct directory and
    readable by us, then we should use them (with an appropriate
    warning)"), said to be theirs (_theirs). So is one of a user outside
    the user namespace root runs in, as a rootless container runs it, whom
    root sees as the kernel's overflow uid (_overflow_uid), nobody, and may
    write only as anyone may: it had been said to be marked immutable, say,
    as another file root can't write though it has a write bit is."""
    try:
        status = os.stat(path)
    except OSError as exc:      # gone since it was read
        return [_failed(exc)]
    if read_only_disk(path):
        return [("the disk it's on is mounted read-only", "copy the book to a disk that can be "
                 "written")]
    folders = {os.path.dirname(os.path.realpath(path))}
    if beside:
        folders.add(os.path.dirname(os.path.abspath(path)))
    folder = [] if all(os.access(f, os.W_OK) for f in folders) else [
        ("its folder can't be written", "make its folder writable")]
    why = []
    if not status.st_mode & 0o222:
        why.append(("it's read-only", "make it writable"))
    elif not os.access(path, os.W_OK):
        if hasattr(os, "geteuid") and os.geteuid() == 0 and status.st_uid != _overflow_uid():
            why.append(("it can't be written, though it has a write bit (marked immutable, say)",
                        "make it writable"))
        else:
            why.append(MAY_NOT_WRITE)
    if status.st_nlink > 1:
        why.append(("another name links to it, which a rewrite would leave as it was",
                    "make it a file of its own"))
    if hasattr(os, "geteuid") and os.geteuid() != status.st_uid and (
            os.geteuid() != 0 or MAY_NOT_WRITE in why):
        return _theirs(path, status, [w for w in why if w is not MAY_NOT_WRITE] + folder,
                       MAY_NOT_WRITE in why)
    return why + folder


def _overflow_uid():
    """The owner a file of a user outside this user namespace shows, the
    kernel's overflowuid, 65534 unless it's set otherwise."""
    try:
        with open("/proc/sys/kernel/overflowuid", encoding="ascii") as fh:
            return int(fh.read())
    except (OSError, ValueError):
        return 65534


def _theirs(path, status, others=(), unwritable=None):
    """Why another user's sidecar at path, its status status, is left as it
    is, and what to do, for _kept. Where nothing but whose it is keeps the
    run from rewriting it, as nothing would were it this user's, though
    this user may not write it (the usual 0644 is the owner's alone to
    write), it's warned of, whatever it holds, the reason's third item
    True (Rob, 2026-10-27: "we want to warn ... where a sidecar isn't being
    rewritten when it otherwise would be because of file ownership"); else
    the others that would keep it so are said too (others), read-only,
    another name linked to it, or its folder unwritable. A link's own name
    is the one the run says, so a link says whose file it leads to. What to
    do is to replace it with a copy of one's own, made with cp -p, which
    keeps its mode, so that the run rewrites that, where this user can put
    a file in its name's place (_replaceable), and to ask its owner to save
    it as UTF-8 with the mark, which needs no rewrite; the owner named as
    such, since a run in a user namespace sees one outside it as nobody.
    In a folder with the sticky bit, as /tmp has, only a file's owner or
    the folder's may replace it, which keeps the run from replacing it
    there (_owners_only). Having its owner, or root, run the conversion
    instead would make the book's outputs theirs. A file the kernel won't
    let be replaced for another reason, append-only or mounted on its own,
    as a container mounts one, is taken for one that could be (not looked
    for)."""
    owner = owner_of(status)
    subject = ("it's a link to %s, which belongs to another user, %s"
               % (os.path.realpath(path), owner) if os.path.islink(path)
               else "it belongs to another user, %s" % owner)
    ask = "ask its owner, %s, to save it as UTF-8 with the mark" % owner
    if not _replaceable(path):
        remedy = ask
    elif any(w[0] == "it's read-only" for w in others):
        remedy = ("replace it with a copy of your own made with cp -p, which keeps its mode, and "
                  "make the copy writable, or " + ask)
    else:
        remedy = "replace it with a copy of your own made with cp -p, which keeps its mode, or " + ask
    if others:
        return [("; ".join([subject] + [w[0] for w in others]), remedy)]
    if _owners_only(os.path.dirname(os.path.realpath(path)), status):
        return [(subject + ", in a folder where only a file's owner, or the folder's owner, may "
                 "replace it", remedy, True)]
    if unwritable is None:
        unwritable = not os.access(path, os.W_OK)
    if unwritable:
        return [(subject, remedy, True)]
    return [(subject + ", and though the user running this may write it, a rewrite would take "
             "it from them", remedy, True)]


def _owners_only(folder, status):
    """Whether a file whose status is status, in folder, may be replaced or
    removed only by its owner, the folder's owner, or root, this user none
    of them: so in a folder with the sticky bit (restricted deletion), as
    /tmp has."""
    try:
        holder = os.stat(folder)
    except OSError:
        return False
    return (bool(holder.st_mode & stat.S_ISVTX)
            and os.geteuid() not in (holder.st_uid, status.st_uid))


def _replaceable(path):
    """Whether this user can put a file of their own in the place of the
    one named path, as a copy of another user's sidecar would be: its
    name's folder writable, and in one with the sticky bit the name its own
    or the folder (a link's name is its own, whoever the file it leads to
    belongs to)."""
    folder = os.path.dirname(os.path.abspath(path))
    try:
        entry = os.lstat(path)
    except OSError:
        return False
    return os.access(folder, os.W_OK | os.X_OK) and not _owners_only(folder, entry)


class OwnerLost(OSError):
    """A rewrite whose new file couldn't be given the old one's owner, for
    a run that seemed able to give it: root in a user namespace, as a
    rootless container runs, which can't give a file a user outside it
    has, or root on a network share that answers for it as nobody. It
    isn't moved into place, so that the sidecar stays its owner's
    (_replace), and the run says so as for another user's (_theirs)."""


def read_only_disk(path):
    """Whether the disk path is on is mounted read-only, which nothing on it
    can be written past; never so where the system won't say (Windows)."""
    try:
        return bool(os.statvfs(path).f_flag & getattr(os, "ST_RDONLY", 1))
    except (AttributeError, OSError):
        return False


def _failed(exc):
    """A rewrite that failed, as a reason _kept gives one, what to do by
    what failed. On Windows a sharing or lock violation (32, 33) is a file
    another program has open; but replacing a file another program has open
    is "access denied" (5), as Git for Windows and LLVM have found, so that
    is either (not tried here). Elsewhere one a user may not write is
    EACCES or EPERM; anything else, a disk full, is said as it is."""
    why = "it couldn't be written (%s)" % (exc.strerror or exc)
    winerror = getattr(exc, "winerror", None)
    if winerror in (32, 33):
        return why, "close the program that has it open"
    if winerror == 5:
        return why, ("close any program that has it open, or give the user running this "
                     "permission to write it and its folder")
    if getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM):
        return why, "give the user running this permission to write it and its folder"
    return why, "put right what kept it from being written"


def _because(why):
    """_kept's reasons as one clause, what to do as another, and whether
    nothing but whose it is keeps the run from rewriting the sidecar:
    another user's that it would rewrite were it this user's (_theirs)."""
    return ("; ".join(w[0] for w in why), ", and ".join(w[1] for w in why),
            any(len(w) > 2 and w[2] for w in why))


def _replace(path, text):
    """path holding text, written beside it and moved into its place, so
    that a write that fails, a disk full or a file another program holds
    open, leaves it as it was; a link's file, not the link, and its owner
    and its mode kept. One whose new file couldn't be given its owner is
    left as it was (OwnerLost)."""
    real = os.path.realpath(path)
    owner = os.stat(real).st_uid
    handle, temporary = tempfile.mkstemp(prefix="." + os.path.basename(real) + ".",
                                         suffix=".tmp", dir=os.path.dirname(real))
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _owned(temporary, real)
        if os.stat(temporary).st_uid != owner:
            raise OwnerLost(errno.EPERM, "its owner couldn't be kept", real)
        os.replace(temporary, real)
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def _keep(path, suffix, data):
    """data kept beside path, under the code page's name after its own, or
    .2 and on after that when the name's taken, as another run's may be;
    its name."""
    kept, n = "%s.%s" % (path, suffix), 1
    while True:
        try:
            fh = open(kept, "xb")
        except FileExistsError:
            n += 1
            kept = "%s.%s.%d" % (path, suffix, n)
            continue
        try:
            with fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            _owned(kept, path)
        except BaseException:
            os.remove(kept)
            raise
        return kept


def _mark(path, data, limit=10):
    """A sidecar at path, its bytes data, UTF-8 without a byte-order mark,
    given the mark, which Excel needs to open it as UTF-8: without it Excel
    reads the file in the computer's code page, "é" as "Ã©", and saved
    again from Excel that's the sidecar's text. One of ASCII alone, or
    empty, which reads the same either way, is given it too, so that every
    sidecar is UTF-8 as Excel's "CSV UTF-8" writes it, and a script reading
    one as plain UTF-8 finds the mark in every one at once, not in one that
    comes to hold a character outside ASCII later (Rob, 2026-10-26: "Let's
    break everything now, not later"). Nothing else in it changes. Returns
    the lines to say: what was done, and for one that holds characters
    outside ASCII the first limit of its lines that do, as they read, since
    one Excel saved in a code page can happen to read as UTF-8 ("Gauß’s" in
    Windows-1252 as "Gauߒs"), which the mark makes Excel show too; or, for
    one left as it is (_kept), or that couldn't be written, why, it being
    read as UTF-8 all the same, in a warning, but in a note for one of
    ASCII alone the run can't mark, nothing in it reading otherwise, and
    in a warning whatever it holds for another user's that nothing but
    whose it is keeps the run from marking, which it says isn't given the
    mark (_theirs); none for one that has the mark."""
    if data.startswith(BOM.encode("utf-8")):
        return []
    odd = [(index, piece.decode("utf-8")) for index, piece in enumerate(_lines(data))
           if not piece.isascii()]
    why = _kept(path)
    if not why:
        try:
            _replace(path, BOM + data.decode("utf-8"))
        except OSError as exc:
            why = _theirs(path, os.stat(path)) if isinstance(exc, OwnerLost) else [_failed(exc)]
    lines = ["  line %d: %s" % (index + 1, shown(line)) for index, line in odd[:limit]]
    if len(odd) > limit:
        lines.append("  and %d more" % (len(odd) - limit))
    if why:
        reasons, remedy, theirs = _because(why)
        given = "isn't given one" if theirs else "can't be given one"
        if not odd:
            return ["%s: %s has no byte-order mark, and %s: %s. It holds nothing outside ASCII, "
                    "which reads the same either way. To have the mark added, %s."
                    % ("WARNING" if theirs else "NOTE", path, given, reasons, remedy)]
        return (["WARNING: %s has no byte-order mark, which Excel needs to open it as UTF-8, "
                 "and %s: %s. It's read as UTF-8, as it is. Its lines outside ASCII, as they "
                 "read:" % (path, given, reasons)]
                + lines
                + ["  A character there that isn't the one written means Excel saved the file "
                   "in a code page whose bytes happen to read as UTF-8. To have the mark added, "
                   "%s." % remedy])
    if not odd:
        return ["%s had no byte-order mark: one is added, as Excel's \"CSV UTF-8\" writes one, "
                "and nothing else in it changes." % path]
    return (["%s had no byte-order mark, which Excel needs to open it as UTF-8: one is added, "
             "and nothing else in it changes. Its lines outside ASCII, as they read:" % path]
            + lines
            + ["  A character there that isn't the one written means Excel saved the file in a "
               "code page whose bytes happen to read as UTF-8: put it right in Excel, which "
               "opens the file as UTF-8 from now on."])


def _rewrite(path, data, reading, limit=10):
    """A sidecar at path, its bytes data, that isn't UTF-8, as Excel's
    plain "CSV" saves one, rewritten as UTF-8, as read_code_page reads it
    (reading), so that it's read as it was written: the file as it was
    kept beside it (_keep), and the file written as Excel's "CSV UTF-8"
    writes one, a byte-order mark first, its lines' ends as they were. One
    left as it is (_kept), or that couldn't be written, is read so all the
    same, by every reader (text), and left as it was, with no copy beside
    it, the run saying it isn't rewritten, not that it can't be, of
    another user's that nothing but whose it is keeps it from rewriting
    (_theirs). Returns the lines to say: what was done, or why it wasn't,
    showing, as read, the first limit of the lines read in the code page,
    and of those kept as UTF-8 that hold a character outside ASCII."""
    decoded, (_, name, suffix, saved), lines, kept_lines = reading
    content = "".join(decoded)
    why, kept = _kept(path, beside=True), None
    if not why:
        try:
            kept = _keep(path, suffix, data)
            _replace(path, ("" if content.startswith(BOM) else BOM) + content)
        except OSError as exc:
            if kept:
                try:
                    os.remove(kept)
                except OSError:
                    pass
            why = _theirs(path, os.stat(path)) if isinstance(exc, OwnerLost) else [_failed(exc)]
    if why:
        reasons, remedy, theirs = _because(why)
        said = ["WARNING: %s isn't UTF-8: %d line(s) of it are read as %s, %s, but it %s "
                "rewritten as UTF-8: %s. This run reads it so, and leaves it as it is. As read:"
                % (path, len(lines), name, saved, "isn't" if theirs else "can't be", reasons)]
    else:
        said = ["WARNING: %s wasn't UTF-8: %d line(s) of it are read as %s, %s, and the file is "
                "rewritten as UTF-8, as \"CSV UTF-8 (Comma delimited)\" saves one. The file as it "
                "was is %s. As now read:" % (path, len(lines), name, saved, kept)]
    said += ["  line %d: %s" % (index + 1, shown(decoded[index])) for index in lines[:limit]]
    if len(lines) > limit:
        said.append("  and %d more" % (len(lines) - limit))
    if kept_lines:
        said.append("  These are UTF-8, and read as they are:" if why
                    else "  These were UTF-8, and are kept as they were:")
        said += ["  line %d: %s" % (index + 1, shown(decoded[index])) for index in kept_lines[:limit]]
        if len(kept_lines) > limit:
            said.append("  and %d more" % (len(kept_lines) - limit))
    if why:
        said.append("  A character there that isn't the one written means the file was saved in "
                    "another code page: save it from Excel as \"CSV UTF-8 (Comma delimited)\". To "
                    "have the run rewrite it, %s." % remedy)
    else:
        said.append("  A character there that isn't the one written means the file was saved in "
                    "another code page: put %s back in its place, and save it from Excel as "
                    "\"CSV UTF-8 (Comma delimited)\", as any sidecar can be from now on." % kept)
    return said


def rewrite_as_utf8(path, limit=10):
    """A sidecar at path made UTF-8 with the byte-order mark, as Excel's
    "CSV UTF-8" writes one, and every reader reads one (text), whatever it
    holds (Rob, 2026-10-26: "upgrade all sidecars to UTF-8 and read UTF-8
    for all of them"): one that isn't UTF-8, as Excel's plain "CSV" saves
    one, rewritten as UTF-8 (_rewrite), and one that's UTF-8 without the
    mark given it (_mark). One the run may not rewrite (_kept), or fails
    to, is left as it is and read all the same, the run saying why; one
    that's there and can't be read is left as it is and gone without, the
    run saying so (_look). Returns (lines to say, None): none for a sidecar
    that's UTF-8 with the mark already, or isn't there; or (None, what to
    stop with), for one that reads in no code page (read_code_page), or
    that can't be read for another reason than permission, a disk's error,
    left as it was."""
    data, why, remedy, stops = _look(path)
    if stops:
        return None, ("%s %s, so the run stops rather than go on without what it holds. Run it "
                      "again once it can be read." % (path, why))
    if why:
        return [_unread(path, why, remedy)], None
    if data is None:
        return [], None
    reading, stop = read_code_page(path, data)
    if stop:
        return None, stop
    if reading is None:
        return _mark(path, data, limit), None
    return _rewrite(path, data, reading, limit), None


def keep_beside(path, suffix):
    """The sidecar at path kept beside it as it is, under suffix after its
    name, or .2 and on after that when the name's taken, never over a file
    kept before (_keep), for a tool that writes a sidecar in its place
    (util/shortdoi.py); the kept file's name."""
    with open(path, "rb") as fh:
        data = fh.read()
    return _keep(path, suffix, data)


def text(path):
    """A sidecar's text, as every reader reads one: UTF-8, the mark at its
    start dropped; one Excel saved in a code page, which the run couldn't
    rewrite, read as rewrite_as_utf8 reads it (read_code_page); and nothing
    for one that isn't there or can't be read, which rewrite_as_utf8 tells
    of. One that reads in no code page, which stops a run before anything
    reads it, reads with U+FFFD for each byte that isn't UTF-8."""
    data, _ = _read(path)
    if not data:
        return ""
    try:
        read = data.decode("utf-8")
    except UnicodeDecodeError:
        reading, _ = read_code_page(path, data)
        read = "".join(reading[0]) if reading else data.decode("utf-8", "replace")
    return read[1:] if read.startswith(BOM) else read


def opened(path):
    """A sidecar's text (text) as a file to read, for csv.reader through
    csv_lines or dict_rows: every sidecar is read so, not with open."""
    return io.StringIO(text(path), newline="")


def filter_copy(path, folder):
    """Where a reader that takes a sidecar's bytes for UTF-8, as the filters
    do, is to read it: path itself; a copy in folder, UTF-8 with the mark,
    of its text (text), for one in a code page the run couldn't rewrite;
    and "", which names no file, for one that can't be read, as a pipe,
    which a reader would wait on."""
    data, why = _read(path)
    if why:
        return ""
    if not data:
        return path
    try:
        data.decode("utf-8")
        return path
    except UnicodeDecodeError:
        pass
    handle, copy = tempfile.mkstemp(prefix="sidecar-", suffix="-" + os.path.basename(path),
                                    dir=folder)
    with os.fdopen(handle, "w", encoding=CSV_ENCODING, newline="") as fh:
        fh.write(text(path))
    return copy


# The schemes a bare link's Replacement can be an address in, as the
# filter's BARE_SCHEMES: an address replaces the link's address and its
# text, and anything else replaces only its text.
ADDRESS_SCHEMES = ("http", "https", "ftp")


def is_address(value):
    """Whether a bare-links sidecar's Replacement is an address, as
    figures-and-tables.lua's web_scheme tells: a scheme it names, then ://."""
    match = re.match(r"([A-Za-z][A-Za-z0-9+.-]*)://", (value or "").strip())
    return bool(match) and match.group(1).lower() in ADDRESS_SCHEMES


# The setting that makes each kind of math-repaired.csv's rows, and so
# each kind of math-keep.csv's.
MATH_SETTINGS = {"equation": "math.repair_equations", "expression": "math.from_text",
                 "symbol": "math.from_text"}


def math_keep_rows(path):
    """The keep sidecar's rows, (kind, page, before), each once: math a run
    would repair, kept as it was (math-keep.csv, its rows copied from
    math-repaired.csv), a header row anywhere skipped, as appending the
    report again and again carries one along each time."""
    rows = []
    if path and os.path.exists(path):
        with opened(path) as fh:
            for row in csv.reader(csv_lines(fh)):
                if row and row[0].strip().lower() == "kind":
                    continue
                if len(row) >= 3 and row[2]:
                    rows.append((row[0], row[1], row[2]))
    return list(dict.fromkeys(rows))


def keep_warning(name, stale, where="the book", off=()):
    """What a run says of the keep sidecar's rows that kept nothing: the
    math they name isn't in the book, or the decks, as written there, or
    the repairs wouldn't change it. A row of a kind only a setting the run
    has off makes (off: those settings, MATH_SETTINGS) couldn't keep
    anything, and isn't said."""
    stale = [row for row in stale if MATH_SETTINGS.get(row[0]) not in off]
    if not stale:
        return []
    return (["WARNING: %d row(s) of %s kept nothing in this run; the math they name isn't in "
             "%s as written there, or the repairs wouldn't change it:"
             % (len(stale), name, where)]
            + ["  %s,%s,%s" % tuple(row) for row in stale[:10]])
