#!/usr/bin/env python3
"""
fetch-exercises.py -- fetch the exercises OpenStax's books keep in its
exercise bank, and the pictures they show, into the cache unpack-cnx.py
reads, for several books at once or on a machine without the books'
repositories; and pack the cache into zip files to carry to a machine
that can't reach the bank.

    python3 util/fetch-exercises.py osbooks-principles-marketing \\
        osbooks-contemporary-mathematics
    python3 util/fetch-exercises.py --write-list exercises.tsv osbooks-*
    python3 util/fetch-exercises.py --list exercises.tsv
    python3 util/fetch-exercises.py --list exercises.tsv --zip ~/exercise-zips

Given repositories (clones of OpenStax's osbooks-* repositories, as
unpack-cnx.py takes them), it puts each of their books together as
unpack-cnx.py does, to learn which exercises it embeds, and fetches them;
--book limits it to the books it names, and may be given again.
--write-list writes those exercises to a list and stops, needing no
network: a line per exercise, tab-separated, the repository's folder's
name, the book, how the book names the exercise (nickname or tag), and
its name. --list reads such a list in place of the repositories, so a
machine with the network needs only the list and TextbookImprover.

Each exercise is asked of https://exercises.openstax.org eight at a time,
as unpack-cnx.py asks, and kept in its cache,
~/.cache/textbookimprover/cnx-exercises unless --exercises-cache names
another; so are the pictures they show. One already there isn't asked
for again, so a run that stops partway can be run again, and
--update-exercises asks for each again and writes a newer version over
the cache's copy, as unpack-cnx.py's does. What couldn't be had is
written to fetch-failures.tsv in the current folder, and asked for again
on the next run, the file removed by a run where nothing fails; a book
that can't be put together is named, and the others go on; and with
--update-exercises, an exercise the bank couldn't be asked about again is
named in the file too. Any of them makes the run's exit 1.

--zip writes the cache's files for these exercises and their pictures
into zip files in the folder it names, none much over --zip-size
megabytes (450 by default), and fetches nothing; zip files of an earlier
run there (cnx-exercises-01.zip and on) are removed first. Unzipped
together into an empty folder, they're the cache again, for
unpack-cnx.py's --exercises-cache and --offline on a machine without the
network.

Needs lxml (python3-lxml), as unpack-cnx.py does, and the network but
for --write-list and --zip.

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
import concurrent.futures
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import lxml  # noqa: F401
except ImportError:
    sys.exit("fetch-exercises.py needs lxml: sudo apt install python3-lxml "
             "(or pip install lxml).")
try:
    from cnx.assemble import assemble
    from cnx.exercises import TOKEN_VARIABLE, Bank, html_children, wanted
    from cnx.repo import Repo
except ImportError as exc:
    sys.exit(f"Cannot find TextbookImprover's library beside util/: {exc}")


def pictures(value):
    """Each picture's address in the HTML anywhere in an API answer, read
    with the unpacker's own parser, so an address is the one it asks for."""
    if isinstance(value, str):
        if "<img" not in value.lower():
            return []
        found = []
        for element in html_children(value)[1]:
            for img in element.iter("img"):
                src = img.get("src") or ""
                if src.startswith(("http://", "https://")):
                    found.append(src)
        return found
    if isinstance(value, dict):
        return [u for v in value.values() for u in pictures(v)]
    if isinstance(value, list):
        return [u for v in value for u in pictures(v)]
    return []


def listed(repositories, books):
    """(repository, book, kind, code) for each exercise the repositories'
    books embed, books limiting them where given; the books asked for that
    none of the repositories has; and those that couldn't be put together,
    each said as it's met, whose exercises aren't listed."""
    rows, found, failed = [], set(), []
    for path in repositories:
        try:
            repo = Repo(path)
        except ValueError as exc:
            sys.exit(str(exc))
        name = os.path.basename(os.path.normpath(path))
        for book in repo.books:
            if books and book.slug not in books:
                continue
            found.add(book.slug)
            try:
                _, body = assemble(repo, book)
            except Exception as exc:
                print(f"{name}: {book.slug} couldn't be put together, so its exercises "
                      f"aren't listed: {exc!r}", file=sys.stderr)
                failed.append(book.slug)
                continue
            rows += [(name, book.slug, kind, code) for kind, code in wanted(body)]
    return rows, [b for b in books if b not in found], failed


def read_list(path, books):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 4:
                rows.append(tuple(parts))
    known = sorted({r[1] for r in rows})
    unknown = [b for b in books if b not in known]
    if unknown:
        sys.exit("The list has no book called " + ", ".join(unknown)
                 + ". Its books: " + ", ".join(known))
    return [r for r in rows if not books or r[1] in books]


def main():
    parser = argparse.ArgumentParser(
        description="Fetch exercises from OpenStax's exercise bank into the "
                    "cache unpack-cnx.py reads, for repositories' books or a "
                    "list of exercises.")
    parser.add_argument("repositories", nargs="*", metavar="REPOSITORY",
                        help="OpenStax osbooks-* repositories (git clones)")
    parser.add_argument("--book", action="append", default=[],
                        help="only this book, by its slug; may be given again")
    parser.add_argument("--list", metavar="FILE",
                        help="read the exercises from a list --write-list wrote, "
                        "in place of repositories")
    parser.add_argument("--write-list", metavar="FILE",
                        help="write the repositories' exercises to a list and stop")
    parser.add_argument("--exercises-cache", "--cache", metavar="DIR", dest="cache",
                        help="the cache's folder (default: unpack-cnx.py's)")
    parser.add_argument("--update-exercises", action="store_true",
                        help="ask the bank again for each exercise the cache has, "
                        "and write a newer version over the cache's copy")
    parser.add_argument("--zip", metavar="FOLDER",
                        help="write the cache's files for these exercises into "
                        "zip files here, and fetch nothing")
    parser.add_argument("--zip-size", type=int, default=450, metavar="MB",
                        help="the most each zip file holds before the next "
                        "begins (default: 450)")
    args = parser.parse_args()
    if bool(args.list) == bool(args.repositories):
        parser.error("name repositories or a --list, one or the other")
    if args.write_list and args.list:
        parser.error("--write-list writes the list of the repositories' exercises")
    if args.zip and args.update_exercises:
        parser.error("--zip packs the cache as it is, and asks the bank nothing")

    unassembled = []
    if args.list:
        rows = read_list(args.list, args.book)
    else:
        rows, unknown, unassembled = listed(args.repositories, args.book)
        if unknown:
            sys.exit("No repository named has a book called " + ", ".join(unknown)
                     + "; unpack-cnx.py --list names a repository's books.")
    if args.write_list:
        with open(args.write_list, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write("\t".join(row) + "\n")
        print(f"Wrote {len(rows)} exercise(s) of {len({r[1] for r in rows})} book(s) to "
              f"{args.write_list}.")
        return 1 if unassembled else 0

    exercises = list(dict.fromkeys((r[2], r[3]) for r in rows))
    if os.environ.get(TOKEN_VARIABLE):
        print(f"{TOKEN_VARIABLE} is set, so what the bank gives with it is kept "
              "apart, under with-token; unset it to fetch what anyone can.")
    bank = Bank(cache=args.cache, offline=bool(args.zip), update=args.update_exercises)
    print(f"{len(exercises)} exercise(s) of {len({r[1] for r in rows})} book(s); "
          f"the cache is {bank.cache}")

    if not args.zip:
        step, asked = 200, 0
        for start in range(0, len(exercises), step):
            asked += bank.prefetch(exercises[start:start + step])
            print(f"  {min(start + step, len(exercises))} of {len(exercises)} done, "
                  f"{asked} asked of the bank in this run", flush=True)

    urls, missing = [], []
    for kind, code in exercises:
        data = bank.cached(kind, code)
        if data is None:
            missing.append((kind, code))
        else:
            urls.extend(pictures(data))
    urls = list(dict.fromkeys(urls))

    if args.zip:
        files = [bank.path(kind, code) for kind, code in exercises
                 if os.path.exists(bank.path(kind, code))]
        lost = 0
        for url in urls:
            path = bank.image(url)
            if path:
                files.append(path)
            else:
                lost += 1
        write_zips(bank.cache, files, args.zip, args.zip_size)
        if missing or lost:
            print(f"Not in the cache, so not in the zips: {len(missing)} exercise(s) "
                  f"and {lost} picture(s). Run without --zip first.")
        return 0

    print(f"{len(urls)} picture(s) in them", flush=True)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        got = list(pool.map(bank.image, urls))
    pictures_lost = [u for u, p in zip(urls, got) if p is None]
    if args.update_exercises:
        print(f"--update-exercises: {len(bank.updated)} newer, written over the "
              f"cache's copy; {len(bank.unchanged)} at the cache's version"
              + (f"; {len(bank.not_updated)} not updated, the bank's not newer or not "
                 "to be had" if bank.not_updated else "") + ".")

    failed = sorted(bank.failures.items())
    report = os.path.abspath("fetch-failures.tsv")
    if not (failed or pictures_lost or bank.not_updated) and os.path.exists(report):
        os.remove(report)               # an earlier run's, of what's had now
    if failed or pictures_lost or bank.not_updated:
        with open(report, "w", encoding="utf-8") as fh:
            for (kind, code), why in failed:
                fh.write(f"{kind}\t{code}\t{why}\n")
            for (kind, code), why in sorted(bank.not_updated.items()):
                fh.write(f"{kind}\t{code}\tnot updated: {why}\n")
            for url in pictures_lost:
                fh.write(f"picture\t{url}\tcouldn't be fetched\n")
    size = 0
    for folder, _dirs, names in os.walk(bank.cache):
        for name in names:
            size += os.path.getsize(os.path.join(folder, name))
    print(f"Done: {len(exercises) - len(failed)} of {len(exercises)} exercise(s) and "
          f"{len(urls) - len(pictures_lost)} of {len(urls)} picture(s) in the cache, "
          f"which holds {size / 1e6:,.1f} MB in all.")
    if failed or pictures_lost or bank.not_updated:
        print(f"{len(failed)} exercise(s) and {len(pictures_lost)} picture(s) couldn't be "
              "had" + (f", and {len(bank.not_updated)} exercise(s) weren't updated"
                       if bank.not_updated else "")
              + f"; they're listed in {report}. Running again tries them again.")
    if unassembled:
        print(f"{len(unassembled)} book(s) couldn't be put together, so their exercises "
              "weren't fetched: " + ", ".join(unassembled) + ".")
    return 1 if failed or pictures_lost or unassembled or bank.unreachable else 0


def write_zips(cache, files, folder, most_mb):
    """The files, by their paths under cache, in zip files in folder, a new
    one begun once the last holds most_mb megabytes; an earlier run's zip
    files there removed first, so that the folder's are this run's alone."""
    os.makedirs(folder, exist_ok=True)
    earlier = sorted(name for name in os.listdir(folder)
                     if re.fullmatch(r"cnx-exercises-\d+\.zip", name))
    for name in earlier:
        os.remove(os.path.join(folder, name))
    if earlier:
        print(f"Removed {len(earlier)} zip file(s) of an earlier run from {folder}.")
    most = most_mb * 1_000_000
    part, held, out, made = 1, 0, None, []
    for path in dict.fromkeys(files):
        if out is None or held >= most:
            if out is not None:
                out.close()
            name = os.path.join(folder, f"cnx-exercises-{part:02d}.zip")
            out = zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED)
            made.append(name)
            part, held = part + 1, 0
        out.write(path, os.path.relpath(path, cache))
        held += os.path.getsize(path)
    if out is not None:
        out.close()
    for name in made:
        print(f"Wrote {name} ({os.path.getsize(name) / 1e6:,.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
