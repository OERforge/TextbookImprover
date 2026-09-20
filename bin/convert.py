#!/usr/bin/env python3
"""
convert.py -- convert a directory of Word documents into accessible pages
and books, one output per target, and hand off to the packager.

    python3 convert.py                  # every target in conversion.yaml
    python3 convert.py --zip            # ... and build the cartridge archive
    python3 convert.py --toc book.pdf   # passed through to the packager
    python3 convert.py --quiet          # without the command trace

Run in the directory holding the .docx files. That directory keeps the
sources, the intermediates, the sidecars, and the reports; every target
writes into a directory of its own, html/ for the one implied when no
configuration says otherwise. A page the author wrote by hand -- an
.html here with no .docx behind it -- is copied into every HTML
target's directory as it stands, with the local files it refers to, and
read into an intermediate so the EPUB has it too.

THE RUN

  0.   read the configuration and resolve the sidecar paths
  0.5  the table-headers pre-pass, on the .docx files
  1.   .docx -> .json, extracting media           (once per document)
  2.   check every media reference resolves       (the gate)
  3.   render header and footer fragments         (per target)
  4.   filter the .json -> .filtered.json         (once per filter stage)
  4.5  cut sources into pages, when asked         (once per filter stage)
  4.7  render .filtered.json -> .html             (per html target)
  5.   write the reports                          (once per book)
  5.5  assemble the EPUBs                         (per epub3 target)
  5.7  check what was written                     (per target)
  6.   build the cartridge                        (the packager)

Two targets share a filtered intermediate when every setting the
schema marks stage: filter agrees between them; otherwise the filter
runs again into a directory of that target's own. Reports and sidecars
are about the source and are written once per book, whatever the
targets. This used to be convert.sh, and the comments that carried what
the shell script had learned are carried here in turn.

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
import glob
import json
import os
import re
import shutil
import copy
import subprocess
import sys
import tempfile
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import docxrepair
    import notes as notes_lib
    import oerconfig
    from bookcontents import (guess_contents, walk_contents, number_tree,
                              is_generated, toc_blocks)
    from names import safe_path, safe_stem, is_safe
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")

FIGURE_FILTER = os.path.join(HERE, "figures-and-tables.lua")
MEDIA_FILTER = os.path.join(HERE, "media-extensions.lua")
HEADER_FILTER = os.path.join(HERE, "header-includes.lua")
SAFE_MEDIA_FILTER = os.path.join(HERE, "safe-media.lua")
TARGET_FILTER = os.path.join(HERE, "target-blocks.lua")
MARKDOWN_FILTER = os.path.join(HERE, "markdown-source.lua")
SOURCE_EXTENSIONS = (".docx", ".md", ".html")
PAGE_CSS = os.path.join(HERE, "page.css")
HEADERS_TOOL = os.path.join(HERE, "table-headers.py")
SPLIT_TOOL = os.path.join(HERE, "split-pages.py")
EPUB_TOOL = os.path.join(HERE, "build-epub.py")
CHECK_TOOL = os.path.join(HERE, "check-output.py")
CARTRIDGE_TOOL = os.path.join(HERE, "build-cartridge.py")

CONFIG_NAME = "conversion.yaml"
PROJECT_NAME = "project.yaml"
PACKAGING_NAME = "packaging.yaml"
LEGACY_NAME = "imsmanifest.yaml"
INTERMEDIATE = ".filtered.json"

TRACE = True


def say(text):
    print(text, file=sys.stderr)


def die(text, code=1):
    say(text)
    sys.exit(code)


def run(command, env=None, cwd=None, check=True, capture=False):
    """Run a command, tracing it the way `set -x` did.

    Seeing every Pandoc invocation as it happens has been useful more
    than once, so the trace is on unless --quiet.
    """
    if TRACE:
        say("+ " + " ".join(shell_quote(c) for c in command))
    result = subprocess.run(command, env=env, cwd=cwd, text=True,
                            capture_output=capture)
    if check and result.returncode:
        die(f"{os.path.basename(command[0])} failed with exit code "
            f"{result.returncode}.")
    return result


def shell_quote(value):
    value = str(value)
    if re.fullmatch(r"[\w./=:@%,+-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------
# 0. the configuration
# --------------------------------------------------------------------------

class Target:
    """One conversion target, resolved."""

    def __init__(self, name, resolved, base):
        self.name = name
        self.resolved = resolved
        self.format = resolved["format"]
        self.output_dir = os.path.normpath(
            os.path.join(base, str(resolved["output_dir"] or name)))
        self.fingerprint = None      # set once every target is known
        self.pages_dir = None        # where its filtered intermediates are

    def __getitem__(self, key):
        return self.resolved[key]


def load_targets(base, allow_unknown):
    """Every conversion target, resolved, plus the project block."""
    schema = oerconfig.load_schema(os.path.join(HERE, "schema-conversion.yaml"))
    project_schema = oerconfig.load_schema(
        os.path.join(os.path.dirname(HERE), "lib", "schema-project.yaml"))

    legacy = os.path.join(base, LEGACY_NAME)
    config_path = os.path.join(base, CONFIG_NAME)
    if os.path.isfile(legacy) and not os.path.isfile(config_path):
        die(f"{LEGACY_NAME} is the v0.1 configuration and is no longer read.\n"
            "  Split it into project.yaml, conversion.yaml and packaging.yaml:\n"
            f"    python3 {os.path.dirname(HERE)}/util/migrate-config.py -d .\n"
            "  It reports what it will do first with --dry-run, and never\n"
            "  changes the original.")

    documents = []
    project_path = os.path.join(base, PROJECT_NAME)
    try:
        if os.path.isfile(project_path):
            documents.append(oerconfig.load_document(project_path,
                                                     project_schema))
        if os.path.isfile(config_path):
            documents.append(oerconfig.load_document(config_path, schema))
    except oerconfig.ConfigError as exc:
        # A directory with no configuration converts with the defaults. A
        # configuration that exists and cannot be read is a different
        # matter, and stops the run: the alternative is converting a whole
        # book with settings the user thought they had changed, which looks
        # like success and is not. v0.2.0 tolerated both cases alike, so a
        # footer written at the top level -- where v0.1 put it -- was
        # reported and then ignored.
        die(f"{exc}\n\nStopping: the configuration could not be read.\n"
            "  Nothing was converted. Fix the problem above and re-run,\n"
            "  or move the file aside to convert with the defaults.")

    declared = oerconfig.target_names(documents)
    targets = []
    try:
        for name in declared or [None]:
            resolved = oerconfig.resolve(schema, project_schema, documents,
                                         target=name,
                                         allow_unknown=allow_unknown)
            if name is None:
                # No targets declared: one implied html target, which
                # writes into html/ like any other target would.
                name = "html"
            targets.append(Target(name, resolved, base))
    except oerconfig.ConfigError as exc:
        die(str(exc))
    for warning in targets[0].resolved.warnings if targets else []:
        say(f"WARNING: {warning}")

    # Stage fingerprints: targets whose filter-stage settings agree share
    # a filtered intermediate. The first target with a fingerprint owns
    # the content directory; a later one with a different fingerprint gets
    # its own directory under its output directory.
    stages = {}

    def walk(node):
        if node.keys:
            for child in node.keys.values():
                walk(child)
        else:
            stages[node.path] = node.stage
    walk(schema.root)
    names = {t.name for t in targets}
    for target in targets:
        values = {path: target.resolved[path] for path, stage in stages.items()
                 if stage == "filter"}
        # A variant source for this target -- <stem>.<target>.md -- makes
        # its intermediates its own, so it goes into the fingerprint.
        target.variants = variant_sources(base, target.name)
        values["variants"] = sorted(target.variants.values())
        target.fingerprint = json.dumps(values, sort_keys=True, default=str)
    all_variants = {os.path.basename(p) for t in targets
                    for p in t.variants.values()}
    for target in targets:
        target.variant_files = all_variants
    globals()["VARIANT_FILES"] = all_variants
    globals()["TARGET_NAMES"] = names
    owners = {}
    for target in targets:
        if target.fingerprint not in owners:
            owners[target.fingerprint] = target
            target.pages_dir = base if len(owners) == 1 else \
                os.path.join(target.output_dir, "intermediates")
        else:
            target.pages_dir = owners[target.fingerprint].pages_dir
    return targets, targets[0].resolved.project


def resolve_path(base, name):
    """A setting's path: absolute as given, otherwise against the
    content directory.

    Resolving "$PWD/$name" unconditionally turned an absolute setting into
    "/book//home/you/sidecars/table-captions.csv", which no filter could
    read and nothing reported except an instruction to append your work
    to a path that did not exist.
    """
    name = str(name)
    return name if os.path.isabs(name) else os.path.join(base, name)


def check_sidecar(path, setting, default, base):
    """A sidecar the config names but the filter cannot read is almost
    always a wrong path rather than a deliberately empty one, and the run
    would otherwise succeed while silently discarding every correction in
    it. The default names are exempt: not having written one yet is the
    normal starting state."""
    if os.path.exists(path):
        return
    if os.path.basename(path) == default and \
            os.path.dirname(os.path.abspath(path)) == os.path.abspath(base):
        return
    die(f"ERROR: {setting} is set to {path}, which does not exist.\n"
        f"       A relative name resolves against {os.path.abspath(base)}.\n"
        f"       Create the file, or remove the setting to use ./{default}.")


# --------------------------------------------------------------------------
# 1. .docx -> .json
# --------------------------------------------------------------------------

VARIANT_FILES = set()       # every <stem>.<target>.<ext> in the directory
TARGET_NAMES = set()


def variant_sources(base, target_name):
    """{stem: path} of the files that replace a source for one target:
    <stem>.<target>.md, .docx, or .html. The page keeps the stem, so
    contents, links, and sidecars don't know which file produced it."""
    found = {}
    for ext in SOURCE_EXTENSIONS:
        for path in sorted(glob.glob(os.path.join(base, f"*.{target_name}{ext}"))):
            stem = os.path.basename(path)[:-len(f".{target_name}{ext}")]
            found[safe_stem(stem)] = path
    return found


def is_variant(name):
    """A file whose second-to-last name segment is a target's name."""
    return name in VARIANT_FILES


def markdown_sources(base, fragments):
    """The .md files this run converts: a page each, the way a .docx is.

    One with a same-named .docx beside it is what a v0.1 run left behind
    and is not a source; neither is a file the header or footer setting
    names. Everything else written in Markdown is a page of the book."""
    found = []
    for path in sorted(glob.glob(os.path.join(base, "*.md"))):
        name = os.path.basename(path)
        if os.path.abspath(path) in fragments or is_variant(name):
            continue
        if os.path.exists(os.path.join(base, name[:-3] + ".docx")):
            continue
        found.append(name)
    return found


def source_documents(base):
    """The .docx files this run converts, with the ones to skip named.

    Word writes an owner file beside any document it has open: the same
    name prefixed with "~$", the same extension, and not a zip at all.
    Pandoc fails on it and takes the whole run down with it. An empty
    file on a cloud-synced drive is usually a placeholder that has not
    been downloaded yet. A .docx is a zip, so it starts with "PK"; an old
    .doc renamed to .docx does not, and neither does a placeholder.
    """
    found = []
    for path in sorted(glob.glob(os.path.join(base, "*.docx"))):
        name = os.path.basename(path)
        if is_variant(name):
            continue                    # read for its target, below
        if name.startswith("~$"):
            say(f"Skipping {name}: Word lock file, not a document.")
            say("  Close the document in Word, or delete the file.")
            continue
        if os.path.getsize(path) == 0:
            say(f"Skipping {name}: empty file.")
            say("  On a cloud-synced drive this is usually a placeholder "
                "that has")
            say("  not been downloaded yet.")
            continue
        with open(path, "rb") as fh:
            if fh.read(2) != b"PK":
                say(f"Skipping {name}: not a .docx (no zip signature).")
                say("  An older .doc renamed to .docx looks like this. Open "
                    "it in Word")
                say("  and use Save As to convert it.")
                continue
        found.append(name)
    return found


def read_markdown_to_json(base, docs, env):
    """A Markdown source is read as Pandoc's markdown, into the same
    intermediate a .docx gets. Its images are files it names by path,
    so there is nothing to extract; they are copied to each target with
    the page. Raw LaTeX in it -- \\frontmatter, \\chaptermark -- rides
    along and is dropped by the HTML and EPUB writers."""
    stems = []
    for name in docs:
        # A page is named after its source, made safe for an href: the
        # cartridge's, the EPUB's, an LMS's. "01 BigPicture.md" is the
        # page 01-BigPicture.
        stem = safe_stem(name[:-3])
        run(["pandoc", "-f", "markdown", "-t", "json", name,
             "-o", stem + ".json", "--lua-filter=" + MEDIA_FILTER],
            env=env, cwd=base)
        stems.append(stem)
    return stems


def read_to_json(base, docs, env, work):
    """JSON rather than Markdown. Markdown is a format with opinions, and
    everything has to survive its grammar: it has no syntax for a cell
    attribute or for a header column, which are precisely what the
    remediation produces. It also picks the simplest table layout that
    fits, which silently destroys a table whose cells are all empty --
    three of them in these books, where a blank worksheet table came back
    as a paragraph break. The JSON is Pandoc's own AST, so nothing is
    lost, and `pandoc -f json -t markdown` renders it back to something
    readable whenever a human wants to look.

    The media filter runs here rather than afterwards. Word stores images
    with whatever content type the DOCX declares, which is routinely
    application/octet-stream; Pandoc turns that into a ".so" extension
    and then writes <embed> instead of <img> -- a page that validates and
    shows nothing. Renaming inside the mediabag, before --extract-media
    writes anything, means the file and the reference cannot disagree.

    --extract-media has to be on this run for the same reason: it is what
    rewrites each src to "<base>/media/...", and that path is the key the
    alt-text sidecar is stored under.
    """
    stems = []
    repaired_dir = os.path.join(work, "repaired")
    os.makedirs(repaired_dir, exist_ok=True)
    for name in docs:
        stem = safe_stem(name[:-5])
        # Pandoc reads a repaired copy -- bookmarks moved to where its
        # reader keeps them; see lib/docxrepair.py -- and the source is
        # never touched. The copy keeps the name so nothing downstream
        # sees a difference.
        repaired = os.path.join(repaired_dir, name)
        moved = docxrepair.repaired_copy(os.path.join(base, name), repaired)
        if moved and TRACE:
            say(f"# {name}: {moved} bookmark(s) moved into the paragraphs "
                "they precede")
        run(["pandoc", "-f", "docx", "-t", "json", repaired,
             "-o", stem + ".json",
             "--lua-filter=" + MEDIA_FILTER, "--extract-media=" + stem],
            env=env, cwd=base)
        stems.append(stem)
    return stems


LOCAL_REF = re.compile(r'\b(?:src|href)\s*=\s*"([^"]+)"', re.I)
EXTERNAL_REF = ("http://", "https://", "//", "data:", "mailto:", "tel:", "#",
                "javascript:")


def hand_pages(base, stems):
    """Pages the author wrote: .html files beside the sources with no
    .docx behind them and not a piece an earlier split left behind. They
    are final, so they are copied rather than rendered."""
    found = []
    for path in sorted(glob.glob(os.path.join(base, "*.html"))):
        stem = os.path.basename(path)[:-5]
        if stem in stems or stem.split("--", 1)[0] in stems \
                or is_variant(os.path.basename(path)):
            continue
        if not is_safe(stem):
            say(f"WARNING: {stem}.html has a space or other character in "
                "its name that an LMS may not resolve in a link; renaming "
                "the file is the fix, since its own links are yours.")
        found.append(stem)
    return found


def local_references(path):
    """Local files a hand-written page refers to, for copying with it."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        markup = fh.read()
    refs = []
    for raw in LOCAL_REF.findall(markup):
        ref = raw.strip().split("#", 1)[0].split("?", 1)[0]
        if ref and not ref.startswith(EXTERNAL_REF) and ref not in refs:
            refs.append(ref)
    return refs


def copy_hand_pages(base, hand, target_dir, variants=None):
    """A hand-written page and what it refers to, byte for byte, into a
    target's directory; the target's own variant of it when there is
    one. A page linking another page of the book is left to that page; a
    file that isn't there is reported and skipped."""
    variants = variants or {}
    if os.path.abspath(target_dir) == os.path.abspath(base):
        return [os.path.join(base, stem + ".html") for stem in hand]
    os.makedirs(target_dir, exist_ok=True)
    copied = []
    for stem in hand:
        source = variants.get(stem) if str(variants.get(stem, "")).endswith(
            ".html") else os.path.join(base, stem + ".html")
        shutil.copy2(source, os.path.join(target_dir, stem + ".html"))
        copied.append(os.path.join(target_dir, stem + ".html"))
        for ref in local_references(source):
            if ref.endswith(".html"):
                continue
            src = os.path.normpath(os.path.join(base, ref))
            if not os.path.isfile(src) or not src.startswith(
                    os.path.abspath(base)):
                say(f"WARNING: {stem}.html refers to {ref}, which is not "
                    "here; not copied.")
                continue
            dest = os.path.join(target_dir, ref)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
    return copied


def read_hand_pages(base, hand, pages_dir, env, variants=None):
    """An intermediate for each hand-written page, read from its HTML, so
    the EPUB can hold it. No filter runs: a person finished this page."""
    variants = variants or {}
    out = []
    for stem in hand:
        target = os.path.join(pages_dir, stem + INTERMEDIATE)
        source = variants.get(stem) if str(variants.get(stem, "")).endswith(
            ".html") else stem + ".html"
        run(["pandoc", "-f", "html", "-t", "json", source,
             "-o", target], env=env, cwd=base)
        out.append(target)
    return out


def read_variants(base, target, work, env):
    """This target's variant sources, read to raw JSON of their own, so
    filter_pages can take them instead of the shared ones."""
    raw = {}
    for stem, path in target.variants.items():
        name = os.path.basename(path)
        if name.endswith(".html"):
            continue                    # a hand page: copied, not read
        out_dir = os.path.join(work, "variants", target.name)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, stem + ".json")
        if name.endswith(".docx"):
            repaired = os.path.join(out_dir, name)
            docxrepair.repaired_copy(path, repaired)
            run(["pandoc", "-f", "docx", "-t", "json", repaired, "-o", out,
                 "--lua-filter=" + MEDIA_FILTER, "--extract-media=" + stem],
                env=env, cwd=base)
        else:
            run(["pandoc", "-f", "markdown", "-t", "json", path, "-o", out,
                 "--lua-filter=" + MEDIA_FILTER], env=env, cwd=base)
        raw[stem] = out
    return raw


def warn_about_leftovers(base, stems, fragments):
    """An intermediate with no matching .docx is not this run's output.
    Say so and leave it alone rather than treating its stale state as an
    error. Markdown from a v0.1 run is no longer read by anything; it is
    named rather than removed, since deleting a user's files is not this
    script's decision to make."""
    for path in sorted(glob.glob(os.path.join(base, "*.json"))):
        name = os.path.basename(path)
        if name.endswith(INTERMEDIATE) or name[:-5] in stems:
            continue
        say(f"Skipping {name}: no matching .docx in this directory.")
        say("  It is left over from an earlier run, or its .docx has moved.")
    for path in sorted(glob.glob(os.path.join(base, "*.md"))):
        if os.path.abspath(path) in fragments:
            continue
        if not os.path.exists(path[:-3] + ".docx"):
            continue                      # a Markdown source, read above
        say(f"Note: {os.path.basename(path)} is left over from a v0.1 run "
            "and is no longer read.")
    # Pages an earlier version wrote beside the sources. They are named
    # rather than removed, since deleting a user's files is not this
    # script's decision; but they are not this run's pages, which go to
    # each target's directory.
    old = [os.path.basename(p) for p in glob.glob(os.path.join(base, "*.html"))
           if os.path.basename(p)[:-5] in stems
           or os.path.basename(p)[:-5].split("--", 1)[0] in stems]
    if old:
        say(f"Note: {len(old)} page(s) beside the sources ({old[0]}, ...) are "
            "from an earlier run; pages now go to each target's directory.")


# --------------------------------------------------------------------------
# 2. the media gate
# --------------------------------------------------------------------------

def media_references(path):
    """Every media path the intermediate refers to. Read out of the AST
    rather than with grep, because an image path that happens to appear
    in prose is not a reference. An absolute URL is not ours to resolve."""
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Image":
                try:
                    refs.append(node["c"][2][0])
                except (KeyError, IndexError, TypeError):
                    pass
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    with open(path, encoding="utf-8") as fh:
        walk(json.load(fh))
    return sorted(r for r in set(refs)
                  if not r.startswith(("http://", "https://", "//", "data:")))


def media_gate(base, stems, media_rows, report_path):
    """A dead image link is invisible in the generated HTML -- Pandoc
    emits an <embed> rather than an <img> for an extension it does not
    recognise. Stopping here is deliberate: broken output that looks fine
    is worse than no output.

    v0.1 spent this step repairing as well as checking, because the
    renaming happened after extraction and the two could drift apart. They
    cannot now, so what is left is a check. It is kept because the failure
    it guards against is silent, and because the media filter still
    cannot identify every format Word stores: EMF and WMF have no
    browser-renderable equivalent and have to go back to the author.
    """
    problems, rows = [], []
    for stem in stems:
        for ref in media_references(os.path.join(base, stem + ".json")):
            # A Markdown source writes a space in a file name as %20, as a
            # link must; the file on disk has the space.
            if not os.path.isfile(os.path.join(base, unquote(ref))):
                problems.append(f"UNRESOLVED: {stem}.json references "
                                f"missing {ref}.")
                rows.append(f"{ref},{stem}.json,,referenced but not on disk")
    # Anything the media filter could not identify. Its rows are already
    # in the right shape, so they are folded in here and one gate covers
    # both.
    if os.path.exists(media_rows):
        with open(media_rows, encoding="utf-8") as fh:
            for row in fh:
                row = row.strip()
                if row:
                    rows.append(row)
                    problems.append(f"UNRESOLVED: {row.split(',')[0]} could "
                                    "not be identified.")
    if not problems:
        return
    say("")
    say("===================================================")
    for problem in problems:
        say(problem)
    say("===================================================")
    say(f"Stopping: {len(problems)} media reference(s) could not be "
        "resolved.")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("File,Source,Detected,Problem\n")
        fh.write("\n".join(sorted(set(rows))) + "\n")
    say(f"Written to {report_path}.")
    if re.search(r"metafile|EMF|WMF", "\n".join(rows), re.I):
        say("")
        say("EMF/WMF are Word's vector formats, used for equations, SmartArt")
        say("and pasted Office charts. No browser renders them, so they have")
        say("to be replaced. In Word: right-click the image, Save as Picture,")
        say("choose PNG, then re-insert. Or convert in place:")
        say("  libreoffice --headless --convert-to png --outdir DIR FILE")
        say("and rename the result to the name the document expects.")
    die("No HTML was generated.")


# --------------------------------------------------------------------------
# 3. header and footer fragments
# --------------------------------------------------------------------------

def fragment_source(text, base, work, key):
    """The setting is Markdown, or the name of a file holding it."""
    if not text:
        return None
    text = str(text)
    candidate = os.path.join(base, text.strip())
    if "\n" not in text.strip() and os.path.isfile(candidate):
        return os.path.abspath(candidate)
    path = os.path.join(work, key + ".md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")
    return path


def render_fragment(source, out):
    """Pandoc's --include-before-body and --include-after-body take HTML,
    so Markdown from the config is rendered once here and reused for every
    page. The fragment is inserted by the template, after the Lua filter
    has run, which is why promoting the leading H1 to the page title still
    works -- but also why nothing in the fragment is processed by the
    filter. Author its images with explicit alt text."""
    if not source:
        return None
    run(["pandoc", "-f", "markdown-implicit_figures", "-t", "html5",
         "--ascii", source, "-o", out])
    return out


# --------------------------------------------------------------------------
# 4. filter, split, render
# --------------------------------------------------------------------------

def filter_env(target, base, paths, env):
    """What the filter reads: the settings that change the intermediate,
    and where the sidecars and the collected report rows are."""
    r = target.resolved
    out = dict(env)
    out.update({
        "SPACER_BELOW": str(r["images.spacer_below"]),
        "STRIP_SPACER": "true" if r["images.strip_spacer"] else "false",
        "ALT_MAX_CHARS": str(r["images.alt_max_chars"]),
        "RESPONSIVE_IMAGES": "true" if r["images.responsive"] else "false",
        "WRAP_TABLES": "true" if r["tables.wrap"] else "false",
        "TABLE_MARKERS": ",".join(f"{k}={v}" for k, v in
                                  (r["tables.markers"] or {}).items()),
        "MEDIA_STRICT": "1" if r["media.strict"] else "",
        "TABLE_LABEL_PREFIXES": ",".join(map(str, r["captions.table_prefixes"])),
        "FIGURE_LABEL_PREFIXES": ",".join(map(str,
                                              r["captions.figure_prefixes"])),
        "AUTHOR_BYLINE": str(r["author_byline"]),
        "PROMOTE_H1_TO_TITLE": str(r["promote_h1_to_title"]),
        "TABLE_CAPTIONS": paths["table_captions"],
        "IMAGE_ALT": paths["image_alt"],
        "TABLE_HEADERS": paths["table_headers"],
    })
    return out


def filter_pages(base, stems, target, env, raw=None):
    """Two Pandoc runs per page rather than one. The filter writes its
    result back out as JSON -- <page>.filtered.json -- and the HTML writer
    reads that. The extra run costs a fraction of a second per page and
    buys the thing every other output format needs: a page that has
    already been remediated, on disk, in a form any writer can consume.
    The filter is per-page by design -- its sidecar keys, its table
    numbering, and its title promotion all assume one document -- so it
    cannot simply be run over the assembled book."""
    pages_dir = target.pages_dir
    os.makedirs(pages_dir, exist_ok=True)
    written = []
    for stem in stems:
        # Pieces this source was cut into by an earlier run are this run's
        # to replace: the separator marks them as generated from it.
        for old in glob.glob(os.path.join(pages_dir, stem + "--*")):
            if old.endswith((INTERMEDIATE, ".html")):
                os.remove(old)
        out = os.path.join(pages_dir, stem + INTERMEDIATE)
        source = (raw or {}).get(stem) or os.path.join(base, stem + ".json")
        run(["pandoc", "-f", "json", "-t", "json", source, "-o", out,
             "--lua-filter=" + FIGURE_FILTER], env=env, cwd=base)
        written.append(out)
    return written


PUBLISHER_PAGE = re.compile(r"^https?://[^/]+/books/[^/]+/pages/([^#?/]+)([#?].*)?$")


def rewrite_publisher_links(pages):
    """A link to one of this book's pages becomes a link to the page
    here: from the publisher's site, or from a Markdown source naming
    another source by file name. Runs on the filtered intermediates
    before the split, so the split and the assembler treat it as any
    other link between pages; a markdown target turns it back into a
    link to the .md file when it merges."""
    stems = {os.path.basename(p)[:-len(INTERMEDIATE)] for p in pages}
    total = 0
    for path in pages:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        count = 0

        def walk(node):
            nonlocal count
            if isinstance(node, dict):
                if node.get("t") == "Link":
                    target = node["c"][2][0]
                    m = PUBLISHER_PAGE.match(target)
                    if m and safe_stem(m.group(1)) in stems:
                        node["c"][2][0] = safe_stem(m.group(1)) + ".html" \
                            + (m.group(2) or "")
                        count += 1
                    else:
                        # A Markdown source naming another source: the
                        # page is what a reader wants, in whatever the
                        # target writes.
                        local = re.match(r"^([^/#?:]+)\.md(#.*)?$", target)
                        if local and safe_stem(local.group(1)) in stems:
                            node["c"][2][0] = (safe_stem(local.group(1))
                                               + ".html"
                                               + (local.group(2) or ""))
                            count += 1
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
        walk(doc["blocks"])
        if count:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            total += count
    if total:
        say(f"{total} publisher link(s) now point at pages of this book.")


def split_pages(target, pages, paths, reports):
    """split-pages.py runs on the filtered intermediates, after the
    filter and before the render, so the pieces carry everything the
    filter did while the sidecar keys and the reports still name the
    source. It prints the pages to render, in reading order."""
    level = int(target["pages.split_level"])
    if level <= 0:
        for name in ("page_names_new", "page_names_report"):
            if os.path.exists(reports[name]):
                os.remove(reports[name])
        return pages
    result = run(["python3", SPLIT_TOOL, "--level", str(level),
                  "--sidecar", paths["page_names"],
                  "--new", reports["page_names_new"],
                  "--report", reports["page_names_report"]] + pages,
                 capture=True)
    sys.stderr.write(result.stderr)
    return [line for line in result.stdout.split("\n") if line.strip()]


def inline_text(text):
    """A string as Pandoc inlines."""
    out = []
    for index, word in enumerate(text.split()):
        if index:
            out.append({"t": "Space"})
        out.append({"t": "Str", "c": word})
    return out


def with_depth(entry, titles, depth):
    """(stem, title, depth) for a contents entry and everything under
    it, so a merged file keeps the nesting the book declares: a
    chapter's sections are one level down, their own pages another."""
    kind, a, b = entry
    if kind == "page":
        return [(a, titles.get(a, a), depth)]
    out = []
    for index, child in enumerate(b):
        # A group's own opening page is the group, not a level below it.
        child_depth = depth if (index == 0 and child[0] == "page"
                                and (child[2] or titles.get(child[1]))
                                == a) else depth + 1
        out += with_depth(child, titles, child_depth)
    return out


def merge_plan(tree, titles, pages):
    """[(file stem, group title, [(page stem, page title)])] for a
    markdown target that merges: one file per top-level contents entry,
    the pages under it in reading order. A page not in contents is a
    file of its own, so nothing is lost."""
    have = {os.path.basename(p)[:-len(INTERMEDIATE)]: p for p in pages}
    plan, placed, used_names = [], set(), set()
    for entry in tree:
        kind, a, b = entry
        if is_generated(entry):
            continue
        members = [(s, t, d) for s, t, d in with_depth(entry, titles, 0)
                   if s in have]
        if not members:
            continue
        title = a if kind == "group" else titles.get(a, a)
        # The file takes the name of the source its pages came from, so a
        # chapter keeps the name the author knows -- but only when they
        # are all of that source. A single-file book cut into chapters
        # has one source for every group, and each file is named for its
        # own entry instead.
        sources = {m[0].split("--", 1)[0] for m in members}
        stem = None
        if len(sources) == 1:
            source = next(iter(sources))
            whole = sum(1 for s in have if s.split("--", 1)[0] == source)
            if whole == len(members):
                stem = source
        stem = stem or safe_stem(title) or safe_stem(members[0][0])
        if stem in used_names:
            n = 2
            while f"{stem}-{n}" in used_names:
                n += 1
            stem = f"{stem}-{n}"
        used_names.add(stem)
        plan.append((stem, title, members))
        placed.update(m[0] for m in members)
    for stem in have:
        if stem not in placed:
            plan.append((stem, titles.get(stem, stem),
                         [(stem, titles.get(stem, stem), 0)]))
    return plan


def header_levels(node, found):
    if isinstance(node, dict):
        if node.get("t") == "Header":
            found.append(node["c"][0])
        for value in node.values():
            header_levels(value, found)
    elif isinstance(node, list):
        for item in node:
            header_levels(item, found)


def shift_headers(blocks, by):
    for block in blocks:
        if isinstance(block, dict):
            if block.get("t") == "Header":
                block["c"][0] = max(1, min(6, block["c"][0] + by))
            for value in block.values():
                if isinstance(value, (list, dict)):
                    shift_headers(value if isinstance(value, list)
                                  else [value], by)


def retarget_links(blocks, where):
    """A link to a page becomes a link to the file that page is in:
    inside this file, just the fragment; in another, that file and the
    page's anchor."""
    def walk(node, here):
        if isinstance(node, dict):
            if node.get("t") == "Link":
                target = node["c"][2][0]
                m = re.match(r"^([^/#?]+)\.html(#.*)?$", target)
                if m and m.group(1) in where:
                    stem, fragment = m.group(1), m.group(2) or ""
                    holder = where[stem]
                    names_file = stem == holder    # the file, not a page
                    if holder == here:
                        node["c"][2][0] = fragment or (
                            "" if names_file else "#" + stem)
                    else:
                        node["c"][2][0] = holder + ".md" + (
                            fragment or ("" if names_file else "#" + stem))
            for value in node.values():
                walk(value, here)
        elif isinstance(node, list):
            for item in node:
                walk(item, here)
    walk(blocks, where.get("__here__"))


def ids_in(node, found):
    if isinstance(node, dict):
        attr = None
        if node.get("t") in ("Header", "Div", "Span", "Table", "Figure",
                             "CodeBlock", "Code", "Link", "Image"):
            c = node.get("c")
            if isinstance(c, list):
                for part in c:
                    if (isinstance(part, list) and len(part) == 3
                            and isinstance(part[0], str)):
                        attr = part
                        break
        if attr and attr[0]:
            found.append(attr)
        for value in node.values():
            ids_in(value, found)
    elif isinstance(node, list):
        for item in node:
            ids_in(item, found)


def unique_within_file(body, seen):
    """Rename ids this file has already used, and repoint the links in
    this page that named them. Two pages of a chapter each carry an
    anchor the export numbered per file; merged, one has to move, and
    only here is it known which links belong with which copy."""
    attrs = []
    ids_in(body, attrs)
    renamed = {}
    raw_blocks = []

    def collect_raw(node):
        if isinstance(node, dict):
            if node.get("t") in ("RawBlock", "RawInline") \
                    and isinstance(node.get("c"), list) \
                    and node["c"][0] in ("html", "html5"):
                raw_blocks.append(node)
            for value in node.values():
                collect_raw(value)
        elif isinstance(node, list):
            for item in node:
                collect_raw(item)
    collect_raw(body)
    for attr in attrs:
        old = attr[0]
        if old not in seen:
            seen.add(old)
            continue
        base_id = re.sub(r"-\d+$", "", old)
        n = 1
        while f"{base_id}-{n}" in seen:
            n += 1
        attr[0] = f"{base_id}-{n}"
        seen.add(attr[0])
        renamed[old] = attr[0]
    # Ids inside a fenced HTML block (a merged-cell table the Markdown
    # target wrote that way) collide too, and no attribute holds them.
    for node in raw_blocks:
        def rename_raw(m):
            old_id = m.group(2)
            if old_id in seen and old_id not in renamed:
                base_id = re.sub(r"-\d+$", "", old_id)
                n = 1
                while f"{base_id}-{n}" in seen:
                    n += 1
                renamed[old_id] = f"{base_id}-{n}"
                seen.add(renamed[old_id])
            elif old_id not in seen:
                seen.add(old_id)
            return m.group(1) + renamed.get(old_id, old_id) + m.group(3)
        node["c"][1] = re.sub(r'(\sid=")([^"]+)(")', rename_raw, node["c"][1])
    for node in raw_blocks:
        node["c"][1] = re.sub(
            r'(href="#)([^"]+)(")',
            lambda m: m.group(1) + renamed.get(m.group(2), m.group(2))
            + m.group(3), node["c"][1])

    if renamed:
        def walk(node):
            if isinstance(node, dict):
                if node.get("t") == "Link":
                    target = node["c"][2][0]
                    if target.startswith("#") and target[1:] in renamed:
                        node["c"][2][0] = "#" + renamed[target[1:]]
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
        walk(body)
    return len(renamed)


def merged_document(members, title, where, holder, base):
    """One document from several pages: the group's title as its own
    heading, each page a section under it, every page anchored by its
    stem so a link can still name it."""
    api, blocks, seen, moved = None, [], set(), 0
    for index, (stem, page_title, depth) in enumerate(members):
        with open(os.path.join(base, stem + INTERMEDIATE),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        api = api or doc["pandoc-api-version"]
        body = copy.deepcopy(doc["blocks"])
        level = min(6, depth + 1)
        # The page's own headings continue below its heading in the
        # merged file, whatever level they started at: a page whose
        # first heading is an h2 under a section at h2 becomes h3, not
        # h4. Shifting by the level alone skipped a level per page.
        levels = []
        header_levels(body, levels)
        shift = (level + 1 - min(levels)) if levels else 0
        shift_headers(body, shift)
        # The page's own anchor, which a previous merge wrote as the
        # heading's id and the split preserved: the heading below
        # carries it again, so one copy is enough.
        body = [b for b in body
                if not (isinstance(b, dict) and b.get("t") in ("Div", "Plain")
                        and not json.dumps(b.get("c", [])).count('"Str"')
                        and stem in json.dumps(b.get("c", []))[:200])]
        seen.add(stem)
        moved += unique_within_file(body, seen)
        opens_group = index == 0 and page_title == title
        heading = {"t": "Header", "c": [level, [stem, [], []],
                                        inline_text(page_title)]}
        if opens_group:
            # The group's own opening page: its content follows the
            # file's heading rather than repeating the title.
            blocks += body
        else:
            blocks += [heading] + body
    where = dict(where); where["__here__"] = holder
    retarget_links(blocks, where)
    if moved:
        say(f"  {holder}: {moved} id(s) renamed where two pages used one")
    return {"pandoc-api-version": api,
            "meta": {"title": {"t": "MetaString", "c": title}},
            "blocks": blocks}


def render_markdown(target, pages, base, work, project, env):
    """Markdown files as source: what the author decided, in Pandoc's
    own flavor, and nothing the filter derived. One file per page, or
    with merge: groups, one per top-level entry of the book's contents,
    each page a section under it."""
    env = dict(env, TARGET_NAME=target.name)
    os.makedirs(target.output_dir, exist_ok=True)
    jobs = [(os.path.basename(p)[:-len(INTERMEDIATE)], p) for p in pages]
    if str(target["merge"]) == "groups":
        tree, titles, _ = book_tree(project, pages,
                                    numbering_for(target, project))
        plan = merge_plan(tree, titles, pages)
        where = {stem: holder for holder, _, members in plan
                 for stem, _, _ in members}
        # A link may name the file itself (the source a chapter's pages
        # were cut from), which is no longer a page of its own.
        for holder, _, _ in plan:
            where.setdefault(holder, holder)
        jobs = []
        for holder, title, members in plan:
            document = merged_document(members, title, where, holder,
                                       os.path.dirname(pages[0]))
            source = os.path.join(work, f"{target.name}-{holder}.json")
            with open(source, "w", encoding="utf-8") as fh:
                json.dump(document, fh)
            jobs.append((holder, source))
        say(f"{target.name}: {len(pages)} page(s) merged into "
            f"{len(jobs)} file(s).")
    written = []
    for stem, page in jobs:
        out = os.path.join(target.output_dir, stem + ".md")
        # Pipe or grid tables, which keep an empty cell and a
        # multi-paragraph one. What Markdown cannot say (a merged-cell
        # table, a figure with an id) is written as a fenced HTML block,
        # which the reader keeps whole and the filter reads back into
        # the table or figure it was; plain raw HTML would come back one
        # tag at a time.
        run(["pandoc", "-f", "json",
             "-t", "markdown-simple_tables-multiline_tables-raw_html",
             page, "-o", out,
             "--standalone", "--wrap=none", "--markdown-headings=atx",
             "--lua-filter=" + TARGET_FILTER,
             "--lua-filter=" + MARKDOWN_FILTER], env=env, cwd=base)
        written.append(out)
    copy_media(base, target.output_dir, pages, safe=False)
    return written


def render_html(target, pages, base, fragments, language, env):
    env = dict(env, TARGET_NAME=target.name,
               TITLE_BLOCK=str(target["title_block"]))
    """--lua-filter figures-and-tables ran already; what remains is the
    writer. -M lang sets the html lang attribute (WCAG 3.1.1), from the
    project's declared language. v0.1 hardcoded "en" while the manifest
    read its own separate setting, so a book in any other language shipped
    pages that disagreed with the package describing them, and nothing
    checked.

    The stylesheet goes in through header-includes.lua rather than
    --include-in-header, because that option replaces the page's own
    header-includes metadata -- the author <meta>, a split page's
    provenance -- instead of adding to it.

    --math-method=mathml rather than --mathml, which Pandoc 3.11
    deprecated. MathML is now the default, so the option is stated only
    to keep the intent visible.

    --embed-resources is deliberately NOT used. Base64 data URIs inflate
    every page and Brightspace does not render them reliably from an
    imported Common Cartridge, so each page links to its extracted images
    at <page>/media/... instead.
    """
    os.makedirs(target.output_dir, exist_ok=True)
    header, footer = fragments
    written = []
    for page in pages:
        stem = os.path.basename(page)[:-len(INTERMEDIATE)]
        out = os.path.join(target.output_dir, stem + ".html")
        command = ["pandoc", "-f", "json", "-t", "html5", page, "-o", out,
                   "--standalone", "--ascii", "--math-method=mathml",
                   "--lua-filter=" + TARGET_FILTER,
                   "--lua-filter=" + SAFE_MEDIA_FILTER,
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        written.append(out)
    copy_media(base, target.output_dir, pages)
    return written


def page_group(intermediate):
    """(group key, group title) for a page, from the provenance a split
    left in it. A chapter file's sections share the source; a single-file
    book's sections share the H1 above them; a page that was not split
    is a group of one."""
    with open(intermediate, encoding="utf-8") as fh:
        meta = json.load(fh).get("meta", {})

    def text(key):
        value = meta.get(key)
        if not value:
            return ""
        if value.get("t") == "MetaString":
            return value["c"]
        return " ".join("".join(i.get("c", " ") if i["t"] == "Str" else " "
                                for i in value.get("c", [])).split())
    source = text("source-page")
    parents = [p.get("c", "") for p in
               meta.get("page-parents", {}).get("c", [])]
    stem = os.path.basename(intermediate)[:-len(INTERMEDIATE)]
    if not source:
        return stem, text("title") or stem
    if parents:
        return (source, parents[0]), parents[0]
    return source, text("source-title") or source


def meta_text(meta, key):
    value = meta.get(key)
    if not value:
        return ""
    if value.get("t") == "MetaString":
        return value["c"]
    return " ".join("".join(i.get("c", " ") if i["t"] == "Str" else " "
                            for i in value.get("c", [])).split())


def numbering_for(target, project):
    """The target's say, else the book's."""
    choice = str(target["numbering"])
    if choice in ("on", "off", "True", "False"):
        return choice in ("on", "True")
    return bool(project.get("numbering"))


def book_tree(project, pages, numbered=None):
    """The book's structure over this run's pages: project.contents when
    declared, else the guess from names and provenance; numbered when
    the project says so. Returns (tree, titles, api), api being the
    Pandoc API version the intermediates carry, for a document the run
    writes itself."""
    titles, parts, roles = {}, {}, {}
    stems = []
    api = None
    for intermediate in pages:
        stem = os.path.basename(intermediate)[:-len(INTERMEDIATE)]
        stems.append(stem)
        with open(intermediate, encoding="utf-8") as fh:
            doc = json.load(fh)
        api = api or doc.get("pandoc-api-version")
        meta = doc.get("meta", {})
        titles[stem] = meta_text(meta, "title") or stem
        if meta_text(meta, "page-role"):
            roles[stem] = meta_text(meta, "page-role")
        source = meta_text(meta, "source-page")
        if source:
            m = re.match(r"(\d+)/", meta_text(meta, "page-part"))
            parents = [p.get("c", "") for p in
                       meta.get("page-parents", {}).get("c", [])]
            parts[stem] = (source, int(m.group(1)) if m else None, parents,
                           meta_text(meta, "page-position"),
                           meta_text(meta, "source-title"),
                           meta_text(meta, "page-role"))
            if meta_text(meta, "source-title") and source not in titles:
                titles[source] = meta_text(meta, "source-title")
    available, used, problems = set(stems), set(), []
    available.add("notes")          # a page the run may write itself
    contents = project.get("contents") or []
    if contents:
        tree = walk_contents(contents, available, used, problems,
                             suffix=INTERMEDIATE)
    else:
        tree = walk_contents(guess_contents(stems, None, titles, parts, roles),
                             available, used, problems, suffix=INTERMEDIATE)
    for problem in problems:
        say(f"WARNING: {problem}")
    if project.get("numbering") if numbered is None else numbered:
        number_tree(tree, titles)
    return tree, titles, api


def generated_pages(tree):
    out = []
    for entry in tree:
        if is_generated(entry):
            out.append(entry)
        elif entry[0] == "group":
            out += generated_pages(entry[2])
    return out


def write_generated(target, tree, titles, api, base, work, fragments,
                    language, env):
    """The pages contents asks the run to write: a contents page, as a
    nested list of links, numbered when the book is."""
    written = []
    for entry in generated_pages(tree):
        kind, name, title = entry
        if entry.generate != "toc":
            continue
        doc = {"pandoc-api-version": api,
               "meta": {"title": {"t": "MetaString", "c": title}},
               "blocks": toc_blocks(tree, titles, lambda s: s + ".html")}
        source = os.path.join(work, f"{target.name}-{name}.json")
        with open(source, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        out = os.path.join(target.output_dir, name + ".html")
        command = ["pandoc", "-f", "json", "-t", "html5", source, "-o", out,
                   "--standalone", "--ascii",
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        header, footer = fragments
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        written.append(out)
    return written


def arrange_notes(target, pages, base, work, fragments, language, env):
    """Apply notes.numbering and notes.placement to a target's rendered
    pages, and write the Notes page when placement is book."""
    numbering = str(target["notes.numbering"])
    placement = str(target["notes.placement"])
    if numbering == "page" and placement == "page":
        return []
    records = []
    for intermediate in pages:
        stem = os.path.basename(intermediate)[:-len(INTERMEDIATE)]
        path = os.path.join(target.output_dir, stem + ".html")
        if not os.path.exists(path):
            continue
        group, title = page_group(intermediate)
        with open(path, encoding="utf-8") as fh:
            records.append(notes_lib.Page(stem + ".html", fh.read(), group,
                                          title, "html"))
    notes_page = None
    if placement == "book":
        source = os.path.join(work, "notes.md")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("# Notes\n")
        out = os.path.join(target.output_dir, "notes.html")
        command = ["pandoc", "-f", "markdown", "-t", "html5", source,
                   "-o", out, "--standalone", "--ascii",
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        header, footer = fragments
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        with open(out, encoding="utf-8") as fh:
            notes_page = notes_lib.Page("notes.html", fh.read(), "notes",
                                        "Notes", "html")
    changed = notes_lib.arrange(records, numbering, placement, notes_page)
    written = []
    for page in changed:
        path = os.path.join(target.output_dir, page.name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page.text)
        written.append(path)
    if notes_page is not None and notes_page not in changed:
        os.remove(os.path.join(target.output_dir, "notes.html"))
    elif notes_page is not None:
        written.append(os.path.join(target.output_dir, "notes.html"))
    return written


def copy_media(base, output_dir, pages, safe=True):
    """Every local image a page refers to, copied beside the page at the
    same relative path: <source>/media/... for what was extracted from a
    .docx, assets/... or wherever for what a Markdown source names. A
    copy keeps the target's pages self-contained, which is what the
    packager assumes."""
    copied = set()
    for page in pages:
        for ref in media_references(page):
            if ref in copied:
                continue
            src = os.path.normpath(os.path.join(base, unquote(ref)))
            if not os.path.isfile(src):
                continue
            # Under the safe name safe-media.lua wrote into the page;
            # a markdown target writes source, whose references are the
            # author's, so its copies keep the author's names.
            dest = os.path.join(output_dir,
                                safe_path(unquote(ref)) if safe
                                else unquote(ref))
            if os.path.abspath(dest) == os.path.abspath(src):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            copied.add(ref)


# --------------------------------------------------------------------------
# 5. reports
# --------------------------------------------------------------------------

def write_report(rows_file, report, header, noun, sidecar=None, hint=None):
    """Sort and deduplicate the collected rows into a report, or remove a
    stale report when nothing is outstanding -- the file existing at all
    is the signal that there is work to do."""
    rows = []
    if os.path.exists(rows_file):
        with open(rows_file, encoding="utf-8") as fh:
            rows = sorted({line.rstrip("\n") for line in fh
                           if line.strip()})
    if not rows:
        if os.path.exists(report):
            os.remove(report)
        return rows
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(header + "\n" + "\n".join(rows) + "\n")
    say(f"Wrote {report} ({len(rows)} {noun}).")
    if sidecar:
        say(f"Fill in the second column, then append the rows to {sidecar}.")
    if hint:
        say(hint)
    return rows


# --------------------------------------------------------------------------

def main():
    global TRACE
    parser = argparse.ArgumentParser(
        description="Convert the .docx files here, one output per target.",
        epilog="Anything else is passed to build-cartridge.py: --zip, "
               "--toc FILE, --check, --includeallhtml.")
    parser.add_argument("--quiet", action="store_true",
                        help="don't trace each command as it runs")
    parser.add_argument("--check-only", action="store_true",
                        help="read, gate, pre-pass, filter, and write the "
                             "reports, then stop: no output directory is "
                             "written and nothing is packaged")
    parser.add_argument("--allow-unknown-keys", action="store_true",
                        help="report settings this version does not know "
                             "about instead of refusing them")
    args, passthrough = parser.parse_known_args()
    TRACE = not args.quiet
    base = os.getcwd()

    for required in (FIGURE_FILTER, MEDIA_FILTER, HEADER_FILTER, PAGE_CSS):
        if not os.path.isfile(required):
            die(f"Missing {required} -- save it alongside this script.")

    # Pandoc 3.9 introduced the options this script relies on. Earlier
    # versions accept most of the command line and quietly do something
    # else: 3.6 and older write grid tables without cell spans, so a table
    # with merged cells loses them without any warning.
    if shutil.which("pandoc") is None:
        die("pandoc not found. Version 3.9 or later is required.")
    version = subprocess.run(["pandoc", "--version"], capture_output=True,
                             text=True).stdout.split()[1]
    if tuple(int(p) for p in re.findall(r"\d+", version)[:3]) < (3, 9):
        die(f"Pandoc {version} is too old; 3.9 or later is required.")

    targets, project = load_targets(base, args.allow_unknown_keys)
    language = project["language"]
    first = targets[0]        # sidecars and reports are book-level settings

    paths = {key: resolve_path(base, first[f"sidecars.{key}"])
             for key in ("table_captions", "image_alt", "table_headers",
                         "page_names")}
    for key, default in (("table_captions", "table-captions.csv"),
                         ("image_alt", "image-alt.csv"),
                         ("table_headers", "table-headers.csv"),
                         ("page_names", "page-names.csv")):
        check_sidecar(paths[key], f"sidecars.{key}", default, base)
    reports = {key: resolve_path(base, first[f"reports.{key}"])
               for key in ("table_captions_missing", "image_alt_missing",
                           "table_headers_new", "table_headers_report",
                           "page_names_new", "page_names_report",
                           "media_unresolved", "spacer_images",
                           "output_check")}

    work = tempfile.mkdtemp(prefix="convert-")
    try:
        collected = {key: os.path.join(work, key) for key in
                     ("captions_missing", "alt_missing", "spacers",
                      "media_unresolved")}
        env = dict(os.environ)
        env.update({
            "TABLE_CAPTIONS_MISSING": collected["captions_missing"],
            "IMAGE_ALT_MISSING": collected["alt_missing"],
            "SPACER_LOG": collected["spacers"],
            "MEDIA_UNRESOLVED": collected["media_unresolved"],
            "MEDIA_STRICT": "1" if first["media.strict"] else "",
        })

        # ---- 0.5 the pre-pass ------------------------------------------------
        # Runs on the .docx files, before Pandoc sees them, because the
        # evidence the guess reads -- repeat-header rows, bold, shading --
        # does not survive Pandoc's reader. A sidecar row whose key matches
        # no table stops the run.
        docs = source_documents(base)
        if docs:
            env["TABLE_HEADERS_RESOLVED"] = os.path.join(work,
                                                        "table-headers.json")
            run(["python3", HEADERS_TOOL] + docs
                + ["--sidecar", paths["table_headers"],
                   "--new", reports["table_headers_new"],
                   "--report", reports["table_headers_report"],
                   "--resolved", env["TABLE_HEADERS_RESOLVED"]], cwd=base)

        # ---- 3. fragments, per target ----------------------------------------
        fragments = {}
        fragment_files = set()
        for target in targets:
            pair = []
            for key in ("header", "footer"):
                source = fragment_source(target[key], base, work,
                                         f"{target.name}-{key}")
                if source:
                    fragment_files.add(source)
                pair.append(render_fragment(
                    source, os.path.join(work, f"{target.name}-{key}.html")))
            fragments[target.name] = tuple(pair)

        # ---- 1. read ----------------------------------------------------------
        stems = read_to_json(base, docs, env, work)
        stems += read_markdown_to_json(base, markdown_sources(base,
                                                              fragment_files),
                                       env)
        if not stems:
            die("No .docx or .md files here, so there is nothing to convert.")
        warn_about_leftovers(base, stems, fragment_files)

        # ---- 2. the gate ------------------------------------------------------
        media_gate(base, stems, collected["media_unresolved"],
                   reports["media_unresolved"])

        # Past the gate, this run will finish and the reports at the end
        # will be written with whatever is outstanding. Clear them now so
        # one left behind by an earlier run cannot survive into a run that
        # has nothing to report. Doing it here rather than at the top means
        # a run that stops at the gate leaves the previous reports intact.
        for key in ("table_captions_missing", "image_alt_missing",
                    "spacer_images"):
            if os.path.exists(reports[key]):
                os.remove(reports[key])

        # ---- 4. filter and split, once per filter stage ---------------------
        css_header = os.path.join(work, "head.html")
        with open(css_header, "w", encoding="utf-8") as fh, \
                open(PAGE_CSS, encoding="utf-8") as css:
            fh.write("<style>\n" + css.read() + "</style>\n")
        pages_by_dir = {}
        for target in targets:
            if target.pages_dir in pages_by_dir:
                continue
            fenv = filter_env(target, base, paths, env)
            raw = read_variants(base, target, work, env)
            variant_stems = [s for s in raw if s not in stems]
            pages = filter_pages(base, stems + variant_stems, target, fenv,
                                 raw)
            if target["links.rewrite_publisher"]:
                rewrite_publisher_links(pages)
            pages_by_dir[target.pages_dir] = split_pages(target, pages,
                                                         paths, reports)

        if args.check_only:
            say("Check only: the reports are written; nothing was rendered "
                "or packaged.")
            return 0

        # ---- 4.6 hand-written pages ------------------------------------------
        hand = hand_pages(base, stems)
        if hand:
            say(f"{len(hand)} hand-written page(s): " + ", ".join(hand))
        for target in targets:
            if target.pages_dir in pages_by_dir and not any(
                    p.endswith(stem + INTERMEDIATE) for stem in hand
                    for p in pages_by_dir[target.pages_dir]):
                pages_by_dir[target.pages_dir] += read_hand_pages(
                    base, hand, target.pages_dir, env, target.variants)
        hand_stems = set(hand)

        # ---- 4.7 render, per html target --------------------------------------
        written = {}
        renv = dict(env, HEADER_INCLUDES_FILE=css_header)
        for target in targets:
            if target.format == "markdown":
                written[target.name] = render_markdown(
                    target, [p for p in pages_by_dir[target.pages_dir]
                             if os.path.basename(p)[:-len(INTERMEDIATE)]
                             not in hand_stems], base, work, project, renv)
            if target.format == "html":
                rendered = [p for p in pages_by_dir[target.pages_dir]
                            if os.path.basename(p)[:-len(INTERMEDIATE)]
                            not in hand_stems]
                written[target.name] = render_html(
                    target, rendered, base, fragments[target.name], language,
                    renv)
                written[target.name] += copy_hand_pages(
                    base, hand, target.output_dir, target.variants)
                tree, titles, api = book_tree(
                    project, pages_by_dir[target.pages_dir],
                    numbering_for(target, project))
                written[target.name] += write_generated(
                    target, tree, titles, api, base, work,
                    fragments[target.name], language, renv)
                for path in arrange_notes(target, rendered, base, work,
                                          fragments[target.name], language,
                                          renv):
                    if path not in written[target.name]:
                        written[target.name].append(path)

        # ---- 5. reports, once per book ----------------------------------------
        missing = write_report(
            collected["captions_missing"], reports["table_captions_missing"],
            "Label,Description,Source,Excerpt",
            "table(s) needing a description", paths["table_captions"])
        write_report(
            collected["alt_missing"], reports["image_alt_missing"],
            "Image,Alt,Source,Reason,CurrentAlt",
            "image(s) needing alt text", paths["image_alt"],
            "Use [decorative] in the Alt column for images that carry no "
            "meaning.")
        write_report(collected["spacers"], reports["spacer_images"],
                     "Image,Source,Width,Action", "spacer image(s) handled")
        labels = {row.split(",")[0] for row in missing}
        if missing and len(labels) < len(missing):
            # The sidecar is keyed on the label alone, so one description
            # would be applied to every table sharing that label.
            say("Note: the same label appears in more than one document.")
            say("Only one description can apply per label; check the Source "
                "column.")

        # ---- 5.5 EPUBs, per epub3 target -------------------------------------
        epubs = []
        for target in targets:
            if target.format != "epub3":
                continue
            result = run(["python3", EPUB_TOOL, "-d", base,
                          "--target", target.name,
                          "--intermediates", target.pages_dir],
                         capture=True)
            sys.stderr.write(result.stderr)
            epubs += [line for line in result.stdout.split("\n")
                      if line.strip()]

        # ---- 5.7 check, per target -------------------------------------------
        # Findings go to one report beside the others and never stop the
        # run: the output exists, and the list is what to work through.
        command = ["python3", CHECK_TOOL, "--report", reports["output_check"]]
        for pages in written.values():
            command += [p for p in pages if p.endswith(".html")]
        for epub in epubs:
            command += ["--epub", epub]
        if os.path.isfile(CHECK_TOOL):
            run(command, check=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---- 6. the cartridge --------------------------------------------------
    # Handed off to build-cartridge.py, which is read-only with respect to
    # page content and can be run on its own against any directory of
    # HTML. Arguments not recognised here are passed straight through, so
    # `--zip` builds the archive too. It reads its configuration here and
    # its pages from the first html target's directory; a package whose
    # includes name another html target is a roadmap item.
    if not os.path.isfile(CARTRIDGE_TOOL):
        say(f"No {CARTRIDGE_TOOL}, so skipping the manifest.")
        return 0
    html_targets = [t for t in targets if t.format == "html"]
    if not html_targets:
        say("No html target, so there is nothing for the packager to read; "
            "skipping the manifest.")
        return 0
    command = ["python3", CARTRIDGE_TOOL, "-d", base]
    if os.path.abspath(html_targets[0].output_dir) != os.path.abspath(base):
        command += ["--pages", html_targets[0].output_dir]
    result = run(command + passthrough, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
