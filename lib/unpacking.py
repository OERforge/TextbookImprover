"""
unpacking -- what the unpackers share: where each writes (one folder, or
a part of a project laid out with src/), a project.yaml holding a book's
metadata and its outline as contents, and unpack-report.csv. Standard
library only.

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

import filecmp
import hashlib
import os
import re
import shutil
import sys

import sidecars
import projectpaths

P = projectpaths.of

# What a book kept in one folder has at its top, by which a folder is
# known not to be a project laid out with src/.
FLAT_SOURCES = (".docx", ".md", ".html", ".adoc", ".asciidoc", ".tex", ".pptx", ".odp",
                ".ppt", ".key")


def record_path(out, part):
    """Where the record of what a part was unpacked to is kept."""
    return P(out).top("output", "work", "unpacked", part + ".txt")


def hashes(folder):
    """{path from folder: SHA-256} of every file under it, but what
    Windows leaves beside a file saved into WSL (name:Zone.Identifier),
    which is no file of the book's."""
    found = {}
    for directory, dirs, names in os.walk(folder):
        dirs.sort()
        for name in sorted(names):
            if name.endswith(":Zone.Identifier"):
                continue
            path = os.path.join(directory, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            digest = hashlib.sha256()
            with open(path, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(block)
            found[os.path.relpath(path, folder).replace(os.sep, "/")] = digest.hexdigest()
    return found


def write_record(out, part, unpacker, options, source, folder=None):
    """Record what a part's upstream file was unpacked to: each file of
    the part's sources (or of folder, a fresh unpacking elsewhere) and
    its hash, under the unpacker, its options, and the file it read."""
    path = record_path(out, part)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    found = hashes(folder or P(out).sources(part))
    lines = ["# What " + (source or "the part's upstream file") + " was unpacked to, for "
             "telling later what has changed in src/" + part + "/. Written by a run; "
             "deleting it is safe.",
             "# unpacker: " + str(unpacker or ""),
             "# options: " + " ".join(options or ()),
             "# from: " + str(source or "")]
    lines += [f"{digest}  {name}" for name, digest in sorted(found.items())]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def read_record(out, part):
    """({key: value} of the record's head, {path: hash}), or None when
    there is no record."""
    try:
        with open(record_path(out, part), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    head, found = {}, {}
    for line in lines:
        if line.startswith("# ") and ": " in line:
            key, value = line[2:].split(": ", 1)
            head.setdefault(key, value)
        elif not line.startswith("#") and "  " in line:
            digest, name = line.split("  ", 1)
            found[name] = digest
    return head, found


def changed(recorded, now):
    """(added, changed, removed), each a sorted list of paths: what the
    part's sources hold now against what was unpacked."""
    return (sorted(set(now) - set(recorded)),
            sorted(n for n in now if n in recorded and now[n] != recorded[n]),
            sorted(set(recorded) - set(now)))


def add_part_option(parser):
    import argparse
    # convert.py's own way of starting an unpacker, in a project it holds
    # the lock of, or in a folder of its own for making the record again.
    parser.add_argument("--from-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--part", metavar="NAME",
        help="write a project laid out with src/: -o is then the project's folder, the "
             "sources go to src/NAME/ (book, for a book), a drafted sidecar to "
             "sidecars/NAME/, the report to output/reports/NAME/, and project.yaml to "
             "the top, with the file this was unpacked from as the part's from")


# A version-control folder isn't the book's: Git's can hold a token
# (.git/config), and its objects are the book's files again.
NOT_COPIED = (".git", ".hg", ".svn")


def copy_folder(source, dest):
    """Copy a folder of sources to dest, which isn't there: its files and
    folders, without a version-control folder, a link (which could lead
    anywhere, and would lead there from the copy), or anything that is
    neither file nor folder. Returns how many files were copied and what
    was left out, as phrases."""
    files, links, others, kept_out = 0, 0, 0, set()
    for directory, dirs, names in os.walk(source):
        kept_out |= {d for d in dirs if d in NOT_COPIED}
        links += sum(1 for d in dirs if os.path.islink(os.path.join(directory, d)))
        dirs[:] = sorted(d for d in dirs if d not in NOT_COPIED
                         and not os.path.islink(os.path.join(directory, d)))
        to = os.path.join(dest, os.path.relpath(directory, source))
        os.makedirs(to, exist_ok=True)
        for name in sorted(names):
            path = os.path.join(directory, name)
            if os.path.islink(path):
                links += 1
            elif not os.path.isfile(path):
                others += 1
            else:
                shutil.copyfile(path, os.path.join(to, name))
                files += 1
    left = [f"{name}/" for name in sorted(kept_out)]
    if links:
        left.append(f"{links} link(s)")
    if others:
        left.append(f"{others} thing(s) that are neither file nor folder")
    return files, left


class Placed:
    """Where an unpacker writes. Without a part, one folder, as before:
    it must be missing or empty. With a part, a project laid out with
    src/: the sources go to a missing or empty src/<part>/ and nothing
    else of the project's is replaced. A settings file goes to the top
    when there is none of its name, and beside the report as a sample
    when there is; a sidecar is written only where there is none.

    upstream is the file or folder unpacked, unpacker its name among a
    part's from's, options the options given that change what's written.
    A file or a folder from outside the project is copied into upstream/
    once the unpacking is done, so the project holds what it was made
    from, and every path it was read by is inside it."""

    def __init__(self, out, part=None, upstream=None, unpacker=None, options=(),
                 from_run=False):
        self.out, self.part, self.from_run = out, part, from_run
        self.unpacker, self.options = unpacker, list(options)
        self.kept, self.copy, self.source, self.unrecorded = [], None, None, None
        if not part:
            if os.path.exists(out) and os.listdir(out):
                sys.exit(f"{out} exists and is not empty; unpacking would mix two "
                         "books. Name another directory with -o.")
            return
        if not projectpaths.PART_NAME.match(part):
            sys.exit(f"--part {part}: a part's name is a lowercase letter, then lowercase "
                     "letters, digits, - and _ (book, for a book).")
        why = None if from_run else projectpaths.refused_root(out)
        above = None if from_run else projectpaths.inside_project(out)
        if why or above:
            sys.exit(f"{out} can't be a project's folder: "
                     + (why or f"it's among the sources or outputs of the project {above}")
                     + ". Nothing was unpacked.")
        why = projectpaths.refused_link(out, [part])
        if why:
            sys.exit(f"{why}. Nothing was unpacked.")
        if os.path.lexists(out) and not os.path.isdir(out):
            sys.exit(f"{out} is a file; -o names the project's folder. Nothing was unpacked.")
        held = sorted(os.listdir(out)) if os.path.isdir(out) else []
        if os.path.lexists(os.path.join(out, "src")):
            if not projectpaths.is_tree(out) and any(
                    not n.startswith(".") for n in os.listdir(os.path.join(out, "src"))):
                sys.exit(f"{out}/src holds files of its own, so {out} isn't a project laid "
                         "out with a folder for each part under src/. Name a new folder "
                         "with -o, or move the book there into the layout first with "
                         "util/move-to-src.py. Nothing was unpacked.")
        else:
            flat = [n for n in held if n.lower().endswith(FLAT_SOURCES)
                    and os.path.isfile(os.path.join(out, n))]
            if flat:
                sys.exit(f"{out} holds sources at its top ({', '.join(flat[:3])}"
                         + (", ..." if len(flat) > 3 else "") + "), as a book kept in one "
                         "folder does. Name a new folder with -o, or move the book there "
                         "into the layout first with util/move-to-src.py. Nothing was "
                         "unpacked.")
        sources = os.path.join(out, "src", part)
        if os.path.isdir(sources) and os.listdir(sources):
            sys.exit(f"{sources} exists and is not empty; unpacking would mix two sets of "
                     "sources. Move or empty the folder to unpack again, or name another "
                     "part with --part. Nothing was unpacked.")
        if upstream:
            self._upstream(upstream)
        if from_run:
            # The run names the file itself and copies nothing.
            self.copy, self.unrecorded = None, None
        os.makedirs(sources, exist_ok=True)
        projectpaths.set_part(part, out)
        try:
            projectpaths.claim_output(out)
            if not from_run:
                projectpaths.lock(out)
        except projectpaths.Refused as exc:
            if not os.listdir(sources):
                os.rmdir(sources)
            sys.exit(str(exc).replace("Nothing was converted.", "Nothing was unpacked."))

    def _upstream(self, upstream):
        """Settle where the part's upstream file is in the project,
        before anything is written."""
        root = os.path.realpath(self.out)
        real = os.path.realpath(upstream)
        if real != root and os.path.commonpath([root, real]) == root:
            self.source = os.path.relpath(real, root).replace(os.sep, "/")
            return
        name = os.path.basename(real)
        if not os.path.isfile(real) and not os.path.isdir(real):
            self.unrecorded = (f"{upstream} is neither a file nor a folder, so it isn't "
                               "copied to the project's upstream/ and the part's from isn't "
                               "written.")
            return
        if name.startswith(".") or not re.match(r"[A-Za-z0-9][A-Za-z0-9._ ()+-]*\Z", name):
            self.unrecorded = (f"{upstream} has a name the project's upstream/ doesn't take, "
                               "so it isn't copied there and the part's from isn't written.")
            return
        dest = os.path.join(self.out, "upstream", name)
        if os.path.isdir(real):
            # A folder is copied whole or not at all: one of its name
            # there already is another copy, whose files may have changed.
            if os.path.commonpath([real, root]) == real:
                sys.exit(f"{upstream} holds the project's folder, {self.out}, so it can't "
                         "be copied into it. Name a project's folder outside it with -o. "
                         "Nothing was unpacked.")
            if os.path.lexists(dest):
                sys.exit(f"{dest} is there already: a part's upstream folder is never "
                         f"replaced or added to. Unpack from {dest} itself, or move or "
                         "rename it. Nothing was unpacked.")
            self.copy = (real, dest)
        elif os.path.lexists(dest):
            if os.path.islink(dest) or not os.path.isfile(dest) \
                    or not filecmp.cmp(real, dest, shallow=False):
                sys.exit(f"{dest} is there already and isn't {upstream}: a part's upstream "
                         "file is never replaced. Move or rename one of them. Nothing was "
                         "unpacked.")
        else:
            self.copy = (real, dest)
        self.source = "upstream/" + name

    @property
    def where(self):
        """The folder the sources went to, for a message."""
        return P(self.out).sources() if self.part else self.out

    def settings(self, name):
        """The path to write a settings file of this name to: the top,
        or beside the report as a sample when the project has one."""
        top = P(self.out).top(name)
        if not self.part or not os.path.lexists(top):
            return top
        stem, ext = os.path.splitext(name)
        # Not -sample: the run writes a project-sample.yaml of its own there.
        sample = P(self.out).report(f"{stem}-unpacked{ext}")
        self.kept.append((name, sample))
        return sample

    def sidecar(self, name):
        """The path to write a drafted sidecar to, or None when the part
        has one of that name, which is left as it is."""
        path = P(self.out).sidecar(name)
        if self.part:
            if os.path.lexists(path):
                self.kept.append((os.path.join("sidecars", self.part, name), None))
                return None
            os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def from_lines(self, indent=2):
        """project.yaml's lines that declare the part and what it was
        unpacked from, under project:."""
        pad = " " * indent
        lines = [f"{pad}parts:", f"{pad}  {self.part}:", f"{pad}    kind: book"]
        if self.source:
            lines += [f"{pad}    from:", f"{pad}      file: {yaml_string(self.source)}",
                      f"{pad}      unpacker: {self.unpacker}"]
            if self.options:
                lines.append(f"{pad}      options: ["
                             + ", ".join(yaml_string(o) for o in self.options) + "]")
        return lines

    def write_project(self, text):
        """Write project.yaml's text, with the part declared in it."""
        if self.part:
            block = "\n".join(self.from_lines()) + "\n"
            if "\n  contents:" in text:
                text = text.replace("\n  contents:", "\n" + block + "  contents:", 1)
            elif "\nproject:\n" in "\n" + text:
                text = ("\n" + text).replace("\nproject:\n", "\nproject:\n" + block, 1)[1:]
            else:
                text += "project:\n" + block
        with open(self.settings(projectpaths.PROJECT_NAME), "w", encoding="utf-8") as fh:
            fh.write(text)

    def finish(self):
        """Copy the upstream file in, record what was unpacked, and say
        what was left as it was."""
        if not self.part:
            return
        write_record(self.out, self.part, self.unpacker, self.options, self.source)
        if self.copy and os.path.isdir(self.copy[0]):
            files, left = copy_folder(*self.copy)
            print(f"{os.path.basename(self.copy[1])}/ copied to "
                  f"{os.path.dirname(self.copy[1])}/, the part's upstream folder: "
                  f"{files} file(s)"
                  + (f"; left out: {', '.join(left)}" if left else "") + ".")
        elif self.copy:
            os.makedirs(os.path.dirname(self.copy[1]), exist_ok=True)
            shutil.copyfile(*self.copy)
            print(f"{os.path.basename(self.copy[1])} copied to "
                  f"{os.path.dirname(self.copy[1])}/, the part's upstream file.")
        if self.unrecorded:
            print(self.unrecorded)
        for name, sample in self.kept:
            if self.from_run:
                continue
            if sample:
                print(f"{name} is there already and is left as it is; what this would have "
                      f"written is {sample}.")
            else:
                print(f"{name} is there already and is left as it is.")
        if not self.from_run and any(name == projectpaths.PROJECT_NAME
                                     for name, _ in self.kept):
            print(f"Add the part to {projectpaths.PROJECT_NAME}, under project:\n"
                  + "\n".join(self.from_lines()))


def xml_name(text):
    """A project identifier has to be an XML name with no colon; a
    package's is usually a URL or a UUID."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-",
                  re.sub(r"^[a-z]+:/*", "", text.strip())).strip("-.")
    return name if re.match(r"[A-Za-z_]", name or "") else "book-" + name


def yaml_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def contents_tree(outline, names, notes):
    """The navigation's entries as a contents tree. An entry that names a
    page is that page; one with entries beneath it is a group, opened by
    its own page when it has one. An entry that points inside a page
    (a fragment, after the page has already been named) is not a page
    and is reported: that is the split's work."""
    tree, stack, seen, inside = [], [], set(), 0
    for depth, title, path, fragment in outline:
        page = names.get(path)
        if page is None or page in seen:
            if page is not None:
                inside += 1
            node = {"title": title, "items": []}
        else:
            seen.add(page)
            node = {"title": title, "page": page, "items": []}
        del stack[depth:]
        (stack[-1]["items"] if stack else tree).append(node)
        stack.append(node)
    if inside:
        notes.append(("navigation", "entries-inside-pages",
                      f"{inside} navigation entries point inside a page "
                      "already named; pages.split_level in conversion.yaml "
                      "cuts a page at its headings"))

    def prune(nodes):
        out = []
        for node in nodes:
            node["items"] = prune(node["items"])
            if "page" in node or node["items"]:
                out.append(node)
        return out
    return prune(tree), seen


def write_contents(nodes, lines, indent, flagged, top=True):
    """No group around the whole book: it would push every page a level
    down in the cartridge and the EPUB's contents. An entry may say its
    role and type, and an entry with generate is a page the run writes
    (a contents page), under name."""
    pad = " " * indent
    for node in nodes:
        page, items = node.get("page"), node.get("items") or []
        extra = [f"{pad}  {key}: {node[key]}" for key in ("role", "type")
                 if node.get(key)]
        if node.get("generate"):
            lines.append(f"{pad}- generate: {node['generate']}")
            if node.get("name"):
                lines.append(f"{pad}  name: {node['name']}")
            lines.append(f"{pad}  title: {yaml_string(node['title'])}")
            lines += extra
        elif items:
            lines.append(f"{pad}- title: {yaml_string(node['title'])}")
            if node.get("role"):
                lines.append(f"{pad}  role: {node['role']}")
            lines.append(f"{pad}  items:")
            if page:
                lines.append(f"{pad}    - page: {page}")
                lines.append(f"{pad}      title: {yaml_string(node['title'])}")
                if node.get("type"):
                    lines.append(f"{pad}      type: {node['type']}")
            write_contents(items, lines, indent + 4, flagged, False)
        else:
            lines.append(f"{pad}- page: {page}" + (
                "        # " + flagged[page] if page in flagged else ""))
            lines.append(f"{pad}  title: {yaml_string(node['title'])}")
            lines += extra


def project_yaml(source, meta, tree, flagged, unnamed, title):
    """project.yaml's text. meta holds lists under title, language,
    creator, identifier, publisher, description."""
    lines = ["# Written by " + source + "; yours to edit.", "project:",
             "  identifier: " + xml_name((meta.get("identifier") or [title])[0]),
             "  title: " + yaml_string(title),
             "  language: " + yaml_string((meta.get("language") or ["en"])[0])]
    for key in ("description", "publisher"):
        if meta.get(key):
            lines.append(f"  {key}: " + yaml_string(meta[key][0]))
    if meta.get("creator"):
        lines.append("  authors:")
        lines += ["    - " + yaml_string(a) for a in meta["creator"]]
    lines += ["  contents:"]
    write_contents(tree, lines, 4, flagged)
    for page in unnamed:
        lines.append(f"    - page: {page}" + (
            "        # " + flagged[page] if page in flagged else ""))
    return "\n".join(lines) + "\n"


def write_report(path, notes):
    with open(path, "w", newline="", encoding=sidecars.CSV_ENCODING) as fh:
        writer = sidecars.csv_writer(fh)
        writer.writerow(["Where", "Check", "Detail"])
        writer.writerows(notes)


def summarize(notes, out, pages, placed=None):
    if placed is not None and placed.part:
        print(f"{pages} page(s) written to {placed.where}/, a part of the project {out}/")
    else:
        print(f"{pages} page(s) and project.yaml written to {out}/")
    counts = {}
    for _where, check, _detail in notes:
        counts[check] = counts.get(check, 0) + 1
    for check, count in sorted(counts.items()):
        print(f"  {count:5d}  {check}")
    if notes:
        print(f"Details in {P(out).report('unpack-report.csv')}.")
    if placed is not None:
        placed.finish()
