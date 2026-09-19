#!/usr/bin/env python3
"""
run-unit-tests.py -- check the small pure functions, and the places where
one fact is written down twice.

    python3 tests/run-unit-tests.py

Needs nothing but Python 3 and PyYAML. Fast enough to run on every save.

TWO KINDS OF CHECK

The first is ordinary: a function, some inputs, the answers. These
functions decide filenames and directory names, which means their mistakes
end up in an LMS rather than in a stack trace. One of them shipped for a
day: a reverse-DNS identifier such as org.example.book-2e was read as a
filename whose extension was ".book-2e", so the archive came out with no
extension at all. That is a three-line assertion here.

The second kind checks that a fact stated in two places still agrees.
lib/bookcontents.py has a built-in back-matter order, and the packaging
schema documents a default for it; they drifted, and the schema's copy was
missing seven entries. A schema exists to be the single description of a
setting, so anywhere a default is also hardcoded is worth asserting about
rather than trusting.

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

import importlib.util
import os
import re
import subprocess
import tempfile
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))

try:
    import yaml
except ImportError:
    sys.exit("This needs PyYAML:\n    sudo apt install python3-yaml")

import oerconfig                                     # noqa: E402


def load(path, name):
    """Import a script by path, since bin/ is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cartridge = load(os.path.join(ROOT, "bin", "build-cartridge.py"), "cartridge")
validator = load(os.path.join(ROOT, "bin", "validate-manifest.py"), "validator")


# --------------------------------------------------------------------------
# the archive's name
# --------------------------------------------------------------------------

def check_archive_name():
    def name(settings, project, target="cartridge"):
        return cartridge.archive_name(settings, project, target)

    cc = {"format": "common-cartridge", "filename": ""}
    zipped = {"format": "zip", "filename": ""}
    return [
        ("a dotted identifier still gets the format's extension",
         lambda: name(cc, {"identifier": "org.szarka.badm224.ibs2e"})
                 == "org.szarka.badm224.ibs2e.imscc"),
        ("a plain identifier gets it too",
         lambda: name(cc, {"identifier": "ibs2"}) == "ibs2.imscc"),
        ("a filename given in full is used exactly",
         lambda: name({"format": "common-cartridge",
                       "filename": "course.imscc"},
                      {"identifier": "ibs2"}) == "course.imscc"),
        ("a filename given without one gets the format's extension",
         lambda: name({"format": "common-cartridge", "filename": "course"},
                      {"identifier": "ibs2"}) == "course.imscc"),
        ("the extension follows the format",
         lambda: name(zipped, {"identifier": "org.example.book-2e"})
                 == "org.example.book-2e.zip"),
        ("with no identifier it falls back to the target's name",
         lambda: name(cc, {}, "brightspace") == "brightspace.imscc"),
    ]


# --------------------------------------------------------------------------
# the content prefix
# --------------------------------------------------------------------------

def check_content_prefix():
    def prefix(title, identifier, **settings):
        options = {"prefix_content": True, "prefix": ""}
        options.update(settings)
        return cartridge.content_prefix(
            {"title": title, "identifier": identifier}, options)

    return [
        ("readable from the title, unique from the identifier",
         lambda: prefix("Introductory Business Statistics 2e",
                        "org.szarka.badm224.ibs2e")
                 == "introductory-business-statistics-a678320ab5"),
        ("two books sharing a title get different directories",
         lambda: prefix("General Sociology", "a")
                 != prefix("General Sociology", "b")),
        ("the same book gets the same directory every time",
         lambda: prefix("General Sociology", "x")
                 == prefix("General Sociology", "x")),
        # The version is deliberately absent, which keeps an update
        # landing on the same paths. It cannot be asserted directly
        # because it is not an input to this function -- so what is
        # asserted instead is where the uniqueness comes from: the digest
        # is over the identifier, so it survives any change of title.
        ("the digest comes from the identifier, not the title",
         lambda: prefix("One Title", "same-id").rsplit("-", 1)[-1]
                 == prefix("A Quite Different Title", "same-id")
                 .rsplit("-", 1)[-1]),
        ("a title that sanitises to nothing leaves the digest alone",
         lambda: re.fullmatch(r"[0-9a-f]{10}", prefix("課程", "x")) is not None),
        ("punctuation and spacing are reduced, not dropped",
         lambda: prefix("A  Book: Second (Revised) Edition", "x")
                 .startswith("a-book-second-revised-edition-")),
        ("an explicit prefix wins",
         lambda: prefix("Anything", "x", prefix="my-book") == "my-book"),
        ("a leading or trailing slash on an explicit prefix is dropped",
         lambda: prefix("Anything", "x", prefix="/my-book/") == "my-book"),
        ("turning it off gives no prefix at all",
         lambda: prefix("Anything", "x", prefix_content=False) == ""),
    ]


# --------------------------------------------------------------------------
# the wrapper module's name
# --------------------------------------------------------------------------

def check_wrapper_title():
    def title(template, project=None, manifest=None):
        return cartridge.wrapper_title(
            project or {"title": "Stats"},
            {"module_title": template},
            manifest or {"version": "1.3", "title": "Stats"})

    return [
        ("the default template names the book and its version",
         lambda: title("{title} ({version})") == "Stats (1.3)"),
        ("a template may name the book alone",
         lambda: title("{title}") == "Stats"),
        ("a template naming something unknown does not stop the build",
         lambda: title("{title} {nonsense}") == "Stats"),
        ("an empty template falls back to the title",
         lambda: title("") == "Stats"),
    ]


# --------------------------------------------------------------------------
# identifiers, which IMS types as xs:ID
# --------------------------------------------------------------------------

def check_identifiers():
    good = ["org.szarka.badm224.ibs2e", "ibs2", "_private",
            "i3f2504e04f8911d39a0c0305e82c3301", "a-b_c.d"]
    bad = ["3f2504e0-4f89-11d3-9a0c-0305e82c3301",
           "urn:uuid:3f2504e0", "general sociology", "", "-leading-dash"]
    return [
        ("valid XML names are accepted",
         lambda: all(validator.NCNAME_RE.match(v) for v in good)),
        ("a bare UUID is refused, because it starts with a digit",
         lambda: not validator.NCNAME_RE.match(bad[0])),
        ("a urn: form is refused, because of the colons",
         lambda: not validator.NCNAME_RE.match(bad[1])),
        ("anything else invalid is refused too",
         lambda: not any(validator.NCNAME_RE.match(v) for v in bad)),
    ]


# --------------------------------------------------------------------------
# facts written down twice
# --------------------------------------------------------------------------

def check_consistency():
    schema = yaml.safe_load(
        open(os.path.join(ROOT, "bin", "schema-packaging.yaml"),
             encoding="utf-8"))
    declared = (schema["keys"]["grouping"]["keys"]["back_matter"]["default"])
    source = open(os.path.join(ROOT, "lib", "bookcontents.py"),
                  encoding="utf-8").read()
    builtin = re.findall(
        r'"([^"]+)"',
        re.search(r"BACK_MATTER_ORDER = \[(.*?)\]", source, re.S).group(1))

    conversion = yaml.safe_load(
        open(os.path.join(ROOT, "bin", "schema-conversion.yaml"),
             encoding="utf-8"))
    convert_sh = open(os.path.join(ROOT, "bin", "convert.sh"),
                      encoding="utf-8").read()

    def fallbacks_agree():
        """convert.sh repeats the schema's defaults so a bare directory
        converts with no configuration. Two copies, so worth asserting."""
        pairs = {
            "PROMOTE_H1_TO_TITLE": ("promote_h1_to_title",),
            "AUTHOR_BYLINE": ("author_byline",),
            "ALT_MAX_CHARS": ("images", "alt_max_chars"),
        }
        for variable, path in pairs.items():
            node = conversion["keys"]
            for part in path:
                node = node["keys"][part] if "keys" in node else node[part]
                if isinstance(node, dict) and part in node.get("keys", {}):
                    node = node["keys"][part]
            found = re.search(r'(?m)^%s="([^"]*)"' % variable, convert_sh)
            if not found:
                return False
            if str(found.group(1)) != str(node["default"]):
                return False
        return True

    return [
        ("the schema's back-matter default matches the built-in order",
         lambda: list(declared) == builtin),
        ("convert.sh's built-in fallbacks match the schema's defaults",
         fallbacks_agree),
        ("every schema loads and declares its keys",
         lambda: all("keys" in yaml.safe_load(open(p, encoding="utf-8"))
                     for p in (
                         os.path.join(ROOT, "bin", "schema-packaging.yaml"),
                         os.path.join(ROOT, "bin", "schema-conversion.yaml"),
                         os.path.join(ROOT, "lib", "schema-project.yaml")))),
        ("every declared setting has a description",
         lambda: not undescribed()),
    ]


def undescribed():
    """Settings with no description, which would appear in a generated
    configuration as a bare key with nothing saying what it is."""
    missing = []
    for path in (os.path.join(ROOT, "bin", "schema-packaging.yaml"),
                 os.path.join(ROOT, "bin", "schema-conversion.yaml"),
                 os.path.join(ROOT, "lib", "schema-project.yaml")):
        schema = oerconfig.load_schema(path)

        def walk(node, prefix=""):
            for name, child in node.keys.items():
                where = f"{prefix}{name}"
                if not child.description:
                    missing.append(f"{os.path.basename(path)}:{where}")
                if child.is_section:
                    walk(child, where + ".")
        walk(schema.root)
    return missing


# --------------------------------------------------------------------------

def check_sidecar_paths():
    """How convert.sh turns a configured sidecar name into a path.

    It built "$PWD/$name" unconditionally, so an absolute setting became
    "/book//srv/corrections/table-captions.csv". The filter read nothing,
    every correction in the file was discarded, and the only trace was an
    instruction telling the user to append their work to a path that did
    not exist. Sidecars are the one thing here that no script can
    reproduce, so failing to read one silently is the worst failure this
    pipeline has.
    """
    script = os.path.join(ROOT, "bin", "convert.sh")
    with open(script, encoding="utf-8") as handle:
        source = handle.read()

    # A real directory, because bash sets $PWD from the working directory
    # and ignores it in the environment.
    base = tempfile.mkdtemp(prefix="sidecar-paths-")

    def resolve(name):
        # The same case statement convert.sh uses, exercised through a
        # shell so this fails if the shell semantics differ from what the
        # Python here assumes.
        result = subprocess.run(
            ["bash", "-c",
             'resolve_path() { case "$1" in /*) printf %s "$1" ;; '
             '*) printf %s "$PWD/$1" ;; esac ; } ; resolve_path "$1"',
             "_", name],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
            cwd=base)
        return result.stdout

    return [
        ("an absolute sidecar path is used as given",
         lambda: resolve("/srv/corrections/table-captions.csv")
                 == "/srv/corrections/table-captions.csv"),
        ("a bare name resolves against the content directory",
         lambda: resolve("table-captions.csv")
                 == os.path.join(base, "table-captions.csv")),
        ("a path escaping the content directory stays relative to it",
         lambda: resolve("../corrections/table-captions.csv")
                 == os.path.join(base, "../corrections/table-captions.csv")),
        # Asserted against the script itself, so a later rewrite cannot
        # quietly reintroduce the shape of the bug.
        ("convert.sh no longer prefixes $PWD unconditionally",
         lambda: '"$PWD/$TABLE_CAPTIONS_NAME"' not in source
                 and '"$PWD/$IMAGE_ALT_NAME"' not in source),
        ("convert.sh resolves every sidecar and report through one helper",
         lambda: source.count("resolve_path \"$") >= 7),
        ("a configured sidecar that does not exist stops the run",
         lambda: "check_sidecar" in source and "exit 1" in source),
    ]


GROUPS = [
    ("the archive's name", check_archive_name),
    ("the content prefix", check_content_prefix),
    ("the wrapper module's name", check_wrapper_title),
    ("identifiers", check_identifiers),
    ("facts written down twice", check_consistency),
    ("sidecar paths", check_sidecar_paths),
]


def main():
    failed = 0
    for label, group in GROUPS:
        print(f"{label}:")
        try:
            checks = group()
        except Exception as exc:
            print(f"  ERROR building the checks: {exc}")
            failed += 1
            continue
        for name, predicate in checks:
            try:
                passed = predicate()
            except Exception as exc:
                passed, name = False, f"{name}  ({exc})"
            print(("  ok    " if passed else "  FAIL  ") + name)
            failed += not passed
    if failed:
        extra = undescribed()
        if extra:
            print("\nsettings with no description:")
            for item in extra:
                print("  " + item)
    print(f"\n{failed} failed" if failed else "\nall unit checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
