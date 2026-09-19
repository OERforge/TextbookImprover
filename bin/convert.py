#!/usr/bin/env python3
"""
convert.py -- convert a directory of Word documents into accessible pages
and books, one output per target, and hand off to the packager.

    python3 convert.py                  # every target in conversion.yaml
    python3 convert.py --zip            # ... and build the cartridge archive
    python3 convert.py --toc book.pdf   # passed through to the packager
    python3 convert.py --quiet          # without the command trace

Run in the directory holding the .docx files. With no configuration at
all a bare folder of documents converts to one HTML page per document
beside them, as it always has. With targets declared, each is built into
its own output directory: several HTML renderings with different headers
or options, an EPUB, whatever else the schema lists.

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
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
try:
    import oerconfig
except ImportError:
    sys.exit("Cannot find the configuration library. It should be in a "
             "lib/ directory beside bin/.")

FIGURE_FILTER = os.path.join(HERE, "figures-and-tables.lua")
MEDIA_FILTER = os.path.join(HERE, "media-extensions.lua")
HEADER_FILTER = os.path.join(HERE, "header-includes.lua")
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
                # No targets declared: the one implied target writes its
                # pages beside the sources, as every version has.
                resolved.settings["output_dir"] = "."
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
    for target in targets:
        values = {path: target.resolved[path] for path, stage in stages.items()
                  if stage == "filter"}
        target.fingerprint = json.dumps(values, sort_keys=True, default=str)
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


def read_to_json(base, docs, env):
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
    for name in docs:
        stem = name[:-5]
        run(["pandoc", "-f", "docx", "-t", "json", name, "-o", stem + ".json",
             "--lua-filter=" + MEDIA_FILTER, "--extract-media=" + stem],
            env=env, cwd=base)
        stems.append(stem)
    return stems


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
        say(f"Note: {os.path.basename(path)} is left over from a v0.1 run "
            "and is no longer read.")


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
            if not os.path.isfile(os.path.join(base, ref)):
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


def filter_pages(base, stems, target, env):
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
        run(["pandoc", "-f", "json", "-t", "json",
             os.path.join(base, stem + ".json"), "-o", out,
             "--lua-filter=" + FIGURE_FILTER], env=env, cwd=base)
        written.append(out)
    return written


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


def render_html(target, pages, base, fragments, language, env):
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
                   "--lua-filter=" + HEADER_FILTER, "-M", f"lang={language}"]
        if header:
            command.append("--include-before-body=" + header)
        if footer:
            command.append("--include-after-body=" + footer)
        run(command, env=env, cwd=base)
        written.append(out)
    if os.path.abspath(target.output_dir) != os.path.abspath(base):
        copy_media(base, target.output_dir, [os.path.basename(p)
                                             [:-len(INTERMEDIATE)]
                                             .split("--", 1)[0]
                                             for p in pages])
    return written


def copy_media(base, output_dir, sources):
    """A page links its images at <source>/media/..., relative to
    itself. A target writing somewhere other than the content directory
    needs the media there too; a copy keeps the pages self-contained,
    which is what the packager assumes."""
    for source in sorted(set(sources)):
        media = os.path.join(base, source, "media")
        if not os.path.isdir(media):
            continue
        dest = os.path.join(output_dir, source, "media")
        os.makedirs(dest, exist_ok=True)
        for name in os.listdir(media):
            shutil.copy2(os.path.join(media, name), os.path.join(dest, name))


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

        # ---- 1. read ----------------------------------------------------------
        stems = read_to_json(base, docs, env)
        if not stems:
            die("No .docx files here, so there is nothing to convert.")

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
            pages = filter_pages(base, stems, target, fenv)
            pages_by_dir[target.pages_dir] = split_pages(target, pages,
                                                         paths, reports)

        # ---- 4.7 render, per html target --------------------------------------
        written = {}
        renv = dict(env, HEADER_INCLUDES_FILE=css_header)
        for target in targets:
            if target.format == "html":
                written[target.name] = render_html(
                    target, pages_by_dir[target.pages_dir], base,
                    fragments[target.name], language, renv)

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
            command += pages
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
    # `--zip` builds the archive too. It packages the html target that
    # writes beside the sources; a package that includes another target
    # is not built yet, and says so.
    if not os.path.isfile(CARTRIDGE_TOOL):
        say(f"No {CARTRIDGE_TOOL}, so skipping the manifest.")
        return 0
    beside = [t for t in targets if t.format == "html"
              and os.path.abspath(t.output_dir) == os.path.abspath(base)]
    if not beside:
        say("No html target writes beside the sources, so there is nothing "
            "for the packager to read; skipping the manifest.")
        return 0
    result = run(["python3", CARTRIDGE_TOOL, "-d", base] + passthrough,
                 check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
