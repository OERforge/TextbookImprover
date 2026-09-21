#!/usr/bin/env python3
"""
unpack-site.py -- turn a book saved from the web into a directory
convert.py can convert, or into a copy of the site that works offline.

    python3 unpack-site.py saved-pages/ -o book         # a browser's saves
    python3 unpack-site.py mhtml-dir/ -o book           # .mhtml, one a page
    python3 unpack-site.py saved-pages/ -o site --whole-pages

A book (the default) is each page's content and nothing around it: the
generator is recognized from what the pages say about themselves, and
its profile says where the content is and what inside it is chrome (a
page's own table of contents, a link icon on every heading). A site
(--whole-pages) keeps every page whole, stylesheets and scripts too.
Either way every reference points at what is here: a link between pages
at the page's file, an image or stylesheet at its one copy under
assets/ however many pages saved it, and anything we don't hold at the
URL it had. project.yaml holds the book's title and language and, as
contents, the order its own menus give. unpack-report.csv says what was
missing and what was guessed.

Nothing is fetched. What isn't in the save is reported, not found.

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
import os
import re
import sys
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import htmlparse as hp
    import sitesource
    from unpacking import contents_tree, project_yaml, write_report, summarize
except ImportError as exc:
    sys.exit(f"Cannot find the library ({exc}). It should be in a lib/ "
             "directory beside bin/.")

# Hosts that serve other people's frameworks, fonts, and scripts. A page
# that loads jQuery from one of these is expected to, and it isn't
# reported as part of the book we don't hold.
THIRD_PARTY = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com",
               "code.jquery.com", "ajax.googleapis.com", "fonts.googleapis.com",
               "fonts.gstatic.com", "cdn.mathjax.org", "polyfill.io",
               "www.googletagmanager.com", "www.google-analytics.com")
SEPARATORS = (" | ", " \u2013 ", " \u2014 ", " - ")


def split_titles(titles):
    """(book title or None, {url: page title}): a suffix every page's
    <title> shares is the site's name, not the page's."""
    for sep in SEPARATORS:
        tails = {t.rsplit(sep, 1)[1].strip() for t in titles.values()
                 if sep in t}
        if len(tails) == 1 and sum(sep in t for t in titles.values()) \
                >= 0.8 * len(titles):
            book = tails.pop()
            return book, {u: t.rsplit(sep, 1)[0].strip() if sep in t else t
                          for u, t in titles.items()}
    return None, titles


def main():
    parser = argparse.ArgumentParser(
        description="Unpack pages saved from the web into HTML sources or "
                    "an offline copy, every reference pointing at what is "
                    "here.")
    parser.add_argument("inputs", nargs="+",
                        help="a directory of saved pages or .mhtml files, "
                             "or .mhtml files")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--whole-pages", action="store_true",
                        help="keep each page whole: an offline copy of the "
                             "site rather than a book's sources")
    parser.add_argument("--third-party", action="append", default=[],
                        metavar="HOST",
                        help="a host serving frameworks or fonts that pages "
                             "may load from where they are (repeatable; "
                             "added to a built-in list)")
    parser.add_argument("--profile", choices=[p["name"] for p in
                                              sitesource.PROFILES],
                        help="the generator's profile, when it isn't "
                             "recognized")
    args = parser.parse_args()
    out = args.output
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f"{out} exists and is not empty; unpacking would mix two "
                 "books. Name another directory with -o.")
    backend = hp.require()

    site = sitesource.load(args.inputs)
    if not site.pages:
        sys.exit("No saved pages found.")
    notes = list(site.notes)
    keep_hosts = set(THIRD_PARTY) | set(args.third_party)
    for page in site.pages.values():
        page.root = hp.parse(page.text)
    sitesource.page_names(site)

    profile = next((p for p in sitesource.PROFILES
                    if p["name"] == args.profile), None) or \
        sitesource.detect_profile([p.text for p in site.pages.values()])
    notes.append(("site", "profile",
                  f"{profile['name']}: "
                  + ("named with --profile" if args.profile else
                     "recognized from the pages" if profile["detect"]
                     else "no generator recognized; main, then article, "
                          "then body")
                  + f"; {site.kind}; parsed with {backend}"))

    # The order comes from the menus, so it is read before any is removed.
    entries, how = sitesource.order(site)
    notes.append(("site", "order", how))

    titles, languages, math_lost = {}, {}, []
    for url, page in site.pages.items():
        title = next((hp.text_of(e) for e in page.root.iter()
                      if hp.local(e.tag) == "title"), "") or page.name
        titles[url] = title
        languages[page.root.get("lang") or ""] = \
            languages.get(page.root.get("lang") or "", 0) + 1
        if re.search(r'class="MathJax(_Display)?"|<mjx-container', page.text) \
                and not re.search(r'type="math/(tex|mml)|<math[\s>]',
                                  page.text):
            math_lost.append(page.name + ".html")
    book_title, titles = split_titles(titles)

    # Authors: the profile's element (Scribble writes them as a paragraph
    # on the contents page), else <meta name="author">, from the first
    # page that has either.
    authors = []
    ordered = [e[2] for e in entries] + list(site.pages)
    for url in ordered:
        root = site.pages[url].root
        found = [hp.text_of(e) for s in profile.get("authors", [])
                 for e in hp.select(root, s)]
        found += [e.get("content", "") for e in root.iter()
                  if hp.local(e.tag) == "meta"
                  and (e.get("name") or "").lower() == "author"]
        for text in found:
            for name in re.split(r",\s*(?:and\s+)?|\s+and\s+", text):
                if name.strip() and name.strip() not in authors:
                    authors.append(name.strip())
        if authors:
            break
    for name in math_lost:
        notes.append((name, "math-lost",
                      "equations are here only as MathJax's rendering; the "
                      "TeX they were written in isn't in the save"))

    os.makedirs(out, exist_ok=True)
    used, missing, markup = set(), [], {}
    for url, page in site.pages.items():
        root = page.root
        if not args.whole_pages:
            content = None
            for selector in profile["content"]:
                found = hp.select(root, selector)
                if found:
                    content = found[0]
                    break
            if content is None:
                content = root
                notes.append((page.name + ".html", "no-content-region",
                              "the profile's content selectors found "
                              "nothing; the whole page is kept"))
            parent_of = hp.parents(content)
            doomed = [e for selector in profile["chrome"]
                      for e in hp.select(content, selector) if e is not content]
            doomed += [e for e in content.iter()
                       if hp.local(e.tag) in ("style", "link", "noscript")
                       or (hp.local(e.tag) == "script" and not
                           sitesource.MATH_SCRIPT.search(e.get("type") or ""))]
            for element in doomed:
                hp.drop(element, parent_of)
            # <a name="x"> with no href: an anchor Pandoc's reader drops.
            # Ids and fragments take one form (see fragment_id).
            for element in content.iter():
                if hp.local(element.tag) == "a" and element.get("name") \
                        and not element.get("href"):
                    if not element.get("id"):
                        element.set("id", element.get("name"))
                    del element.attrib["name"]
                    element.tag = "span"
                if element.get("id"):
                    element.set("id", sitesource.fragment_id(element.get("id")))
                if (element.get("href") or "").startswith("#"):
                    element.set("href", "#" + sitesource.fragment_href(
                        element.get("href")[1:]))
            page.root = content
        sitesource.rewrite(site, page, keep_hosts, None, used, missing)
        if args.whole_pages:
            markup[url] = "<!DOCTYPE html>\n" + hp.serialize(root)
        else:
            inner = hp.serialize(page.root, inner=True)
            if hp.local(page.root.tag) not in ("main",):
                inner = inner
            language = root.get("lang") or ""
            markup[url] = (
                "<!DOCTYPE html>\n<html" + (f' lang="{language}"' if
                                            language else "") + ">\n"
                "<head>\n<meta charset=\"utf-8\">\n<title>"
                + hp._escape_text(titles[url]) + "</title>\n</head>\n"
                "<body>\n<main>\n" + inner + "\n</main>\n</body>\n</html>\n")

    names = sitesource.resource_names(site, used)
    notes += [n for n in site.notes if n[1] == "extension-corrected"]
    for key, relative in names.items():
        path = os.path.join(out, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(site.resources[key][0])
    for url, page in site.pages.items():
        with open(os.path.join(out, page.name + ".html"), "w",
                  encoding="utf-8") as fh:
            fh.write(sitesource.finish_references(markup[url], names))

    counted = {}
    for where, kind, target in missing:
        counted.setdefault((kind, target), []).append(where)
    for (kind, target), pages in sorted(counted.items()):
        notes.append((pages[0], kind, f"{target} (from {len(pages)} page(s))"))

    by_url = {url: page.name for url, page in site.pages.items()}
    outline = [(depth, title, url, "") for depth, title, url in entries]
    tree, named = contents_tree(outline, by_url, notes)
    unnamed = [p.name for u, p in site.pages.items() if p.name not in named]
    for name in unnamed:
        notes.append((name + ".html", "not-in-menu",
                      "no menu names this page; listed at the end of "
                      "contents"))
    host = urlsplit(next(iter(site.pages))).netloc
    title = book_title or (titles.get(entries[0][2]) if entries else "") \
        or host
    language = max(languages, key=languages.get) or "en"
    meta = {"title": [title], "language": [language], "creator": authors,
            "identifier": [host + site.root]}
    if not args.whole_pages:
        with open(os.path.join(out, "project.yaml"), "w",
                  encoding="utf-8") as fh:
            fh.write(project_yaml("unpack-site.py", meta, tree, {}, unnamed,
                                  title))
    write_report(os.path.join(out, "unpack-report.csv"), notes)
    summarize(notes, out, len(site.pages))
    print(f"{len(names)} resource(s) under {out}/assets/, each once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
