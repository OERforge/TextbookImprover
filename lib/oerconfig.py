#!/usr/bin/env python3
"""
oerconfig -- load, merge, validate, and write the project's YAML
configuration, against a schema that says what every setting is.

Both halves of the project depend on this; neither depends on the other.
The conversion tools pass it the conversion schema, the packaging tools
pass it the packaging schema, and both pass the project schema that ships
here. Adding a conversion setting therefore touches nothing the packaging
side reads.

    import oerconfig
    schema = oerconfig.load_schema("schema-conversion.yaml")
    project = oerconfig.load_schema("schema-project.yaml")
    docs = [oerconfig.load_document(p) for p in paths]
    resolved = oerconfig.resolve(schema, project, docs, target="epub-full")

WHY A SCHEMA AT ALL

The configuration used to be described in three places at once: the code
that read each key, the code that wrote the sample file, and the README.
They drifted, as three hand-maintained lists of the same thing do. The
sample writer knew about six of the eight top-level keys, so a run that
hit any fatal error wrote a "complete" sample missing captions, grouping,
and manifest.modified -- and then told the user to rename it over their
real config. Deriving the reader, the writer, the validator, and the
documentation from one declaration removes the possibility rather than
fixing the instance.

THE MERGE RULES

Five, kept few on purpose. Every configuration system that grows richer
merge semantics ends up with behavior nobody can predict from reading
the file, and this one has to be reimplemented one day in whatever the
web front end is written in.

  1. Four layers, always in this order: the schema's defaults, the
     project block, the file's defaults block, the target's own block.
  2. The schema decides what nests. A node with `keys` is a section and
     merges key by key; anything else is a setting and is replaced whole.
  3. Lists replace. They never append, and never merge element-wise.
  4. An explicit null clears an inherited value, falling back to the
     schema default. An absent key inherits.
  5. No coercion during the merge. Raw values are merged, and each
     resolved value is coerced once at the end against its declared type.

Rule 5 matters more than it looks: coercing early means a value's type
depends on which layer it came from, and two layers can then disagree
about what "false" meant.

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

import datetime
import difflib
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("Reading configuration needs PyYAML. Install it with:\n"
             "    sudo apt install python3-yaml\n"
             "  or\n"
             "    pip3 install pyyaml")

# A BCP 47 tag, loosely: a primary subtag and any number of subtags. Not a
# registry check -- the point is to catch en_US, "English", and the
# boolean YAML makes of an unquoted "no", not to adjudicate rare tags.
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*$")

TRUE_WORDS = {"true", "yes", "on", "1"}
FALSE_WORDS = {"false", "no", "off", "0"}

SCALAR_TYPES = ("string", "text", "path", "language", "ncname", "bool",
                "int", "float", "enum", "date")

# An XML NCName: a letter or underscore, then letters, digits, and any of
# . - _ . No colons, and it may not start with a digit. IMS types the
# manifest, organization, item and resource identifiers as xs:ID, which
# derives from NCName, so an identifier that breaks this rule produces a
# manifest no validator will accept -- and the two things people reach for
# after reading "make it globally unique" both break it: a bare UUID
# usually starts with a digit, and urn:uuid: has colons.
NCNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")

# YYYY-MM-DD. Written unquoted, YAML hands back a date object rather than
# a string, so a setting holding one needs its own type: declaring it a
# string means every config with a bare date is rejected for having the
# wrong type, which is technically true and useless.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ConfigError(Exception):
    """A problem in a configuration or schema file, phrased for a user."""


class StrictLoader(yaml.SafeLoader):
    """A YAML loader that refuses a mapping with the same key twice.

    PyYAML keeps the last one and says nothing. That is a poor bargain
    here, because a generated configuration already contains every
    setting: a user who adds `footer:` rather than editing the `footer:`
    already in the file gets two, loses the one they wrote, and has
    nothing to go on. The whole point of writing complete files is that a
    setting cannot go missing without being mentioned.
    """


def _no_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            mark = key_node.start_mark
            raise ConfigError(
                f"{mark.name}, line {mark.line + 1}: {key!r} is set twice in "
                "the same block. YAML keeps only the last one, so the "
                "earlier setting would be silently discarded. Edit the "
                "existing line rather than adding another.")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------

class Node:
    """One schema entry: a section holding keys, or a single setting."""

    __slots__ = ("name", "path", "description", "type", "default", "values",
                 "item", "target_only", "default_from_target", "keys",
                 "stage")

    def __init__(self, name, path, raw, stage=None):
        self.name = name
        self.path = path
        self.description = " ".join(str(raw.get("description", "")).split())
        self.keys = None
        self.type = None
        self.default = None
        self.values = None
        self.item = None
        self.target_only = bool(raw.get("target_only", False))
        self.default_from_target = bool(raw.get("default_from_target", False))
        # Which step of a run a setting changes: filter (the intermediate
        # the filter writes), render (how a target writes its pages),
        # package (a whole-book output), or report. A section's stage is
        # inherited by its keys; unset means filter, the conservative
        # reading, since sharing an intermediate two targets would have
        # filtered differently is the silent failure.
        self.stage = raw.get("stage", stage) or "filter"

        if "keys" in raw:
            self.keys = {}
            for child, child_raw in (raw["keys"] or {}).items():
                child_path = f"{path}.{child}" if path else child
                self.keys[child] = Node(child, child_path, child_raw or {},
                                        self.stage)
            return

        self.type = raw.get("type")
        if self.type is None:
            raise ConfigError(f"schema entry {path!r} has neither keys nor "
                              "a type")
        if self.type not in SCALAR_TYPES + ("list", "opaque"):
            raise ConfigError(f"schema entry {path!r} has unknown type "
                              f"{self.type!r}")
        if self.type == "enum":
            self.values = [str(v) for v in (raw.get("values") or [])]
            if not self.values:
                raise ConfigError(f"schema entry {path!r} is an enum with "
                                  "no values")
        if self.type == "list":
            self.item = raw.get("item", "string")
        self.default = raw.get("default")

    @property
    def is_section(self):
        return self.keys is not None


class Schema:
    """A parsed schema file."""

    def __init__(self, root, source):
        self.root = root
        self.source = source

    @property
    def keys(self):
        return self.root.keys

    def node(self, dotted):
        """Look up a node by dotted path, or None."""
        node = self.root
        for part in dotted.split("."):
            if not node.is_section or part not in node.keys:
                return None
            node = node.keys[part]
        return node

    def defaults(self, include_target_only=True):
        """Every declared setting at its schema default."""
        return _defaults_of(self.root, include_target_only)


def _defaults_of(node, include_target_only):
    out = {}
    for name, child in node.keys.items():
        if child.is_section:
            out[name] = _defaults_of(child, include_target_only)
        elif child.target_only and not include_target_only:
            continue
        else:
            out[name] = child.default
    return out


def load_schema(path):
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if "keys" not in raw:
        raise ConfigError(f"{path} is not a schema: it has no top-level keys")
    return Schema(Node("", "", raw), path)


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------

class Document:
    """One configuration file, as read, with nothing resolved yet."""

    def __init__(self, data, source):
        self.data = data or {}
        self.source = source

    @property
    def project(self):
        return self.data.get("project") or {}

    @property
    def defaults(self):
        return self.data.get("defaults") or {}

    @property
    def targets(self):
        return self.data.get("targets") or {}


def load_document(path, schema=None):
    with open(path, encoding="utf-8") as handle:
        try:
            data = yaml.load(handle, Loader=StrictLoader)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML:\n  {exc}")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a mapping")
    unknown = sorted(set(data) - {"project", "defaults", "targets"})
    if unknown:
        # A key that is a real setting at the wrong level is the mistake a
        # v0.1 config invites, because everything used to sit at the top.
        # Saying where it belongs is more use than saying it is unexpected.
        misplaced = [k for k in unknown
                     if schema is not None and k in schema.keys]
        detail = (f"{path} has unexpected top-level key(s): "
                  f"{', '.join(unknown)}. A configuration file holds "
                  "project, defaults, and targets.")
        if misplaced:
            detail += ("\n  " + ", ".join(misplaced) + " "
                       + ("is a setting" if len(misplaced) == 1
                          else "are settings")
                       + ", so "
                       + ("it belongs" if len(misplaced) == 1
                          else "they belong")
                       + " under defaults: (or inside a target). In v0.1 "
                         "everything sat at the top level; from v0.2 it "
                         "does not.")
        raise ConfigError(detail)
    return Document(data, path)


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------

def _merge(node, base, override, source, problems, warnings=None):
    """Rules 2, 3 and 4. Returns a new dict; neither argument is modified.

    When warnings is given, a key the schema does not declare is kept and
    reported rather than refused. Keeping it matters as much as reporting
    it: the reason to tolerate an unknown key is that the config may have
    been written for a newer version of the tools, and a reader that drops
    what it does not understand and then rewrites the file destroys
    exactly the settings it was being lenient about.
    """
    out = dict(base)
    if not isinstance(override, dict):
        problems.append(f"{source}: {node.path or 'the config'} should be a "
                        f"block of settings, not {type(override).__name__}")
        return out

    for key, value in override.items():
        child = node.keys.get(key) if node.is_section else None
        if child is None:
            if warnings is None:
                problems.append(_unknown_key(node, key, source))
            else:
                warnings.append(_unknown_key(node, key, source)
                                + " (kept, not used)")
                out[key] = value
            continue
        if child.is_section:
            out[key] = _merge(child, base.get(key) or {}, value or {},
                              source, problems, warnings)
        elif value is None:
            # Rule 4: an explicit null clears, falling back to the schema
            # default. Distinguishable from an absent key because YAML
            # gives us None for "footer:" and nothing at all for a line
            # that is not there.
            out[key] = child.default
        else:
            out[key] = value
    return out


def _unknown_key(node, key, source):
    known = sorted(node.keys) if node.is_section else []
    close = difflib.get_close_matches(key, known, n=1, cutoff=0.6)
    where = node.path or "the top level"
    hint = f"; did you mean {close[0]}?" if close else ""
    return f"{source}: unknown setting {key!r} in {where}{hint}"


# --------------------------------------------------------------------------
# coercion
# --------------------------------------------------------------------------

def _coerce(node, value, where, problems):
    kind = node.type

    if kind == "opaque":
        return value

    if kind == "list":
        if value is None:
            return []
        if not isinstance(value, list):
            # A single value where a list is expected is almost always
            # meant, and rejecting it would be pedantry.
            value = [value]
        item = Node(node.name, node.path,
                    {"type": node.item, "default": None})
        return [_coerce(item, v, where, problems) for v in value]

    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in TRUE_WORDS:
            return True
        if text in FALSE_WORDS:
            return False
        problems.append(f"{where}: {node.path} should be true or false, "
                        f"not {value!r}")
        return node.default

    if kind in ("int", "float"):
        caster = int if kind == "int" else float
        if isinstance(value, bool):
            problems.append(f"{where}: {node.path} should be a number, not "
                            f"{str(value).lower()}")
            return node.default
        try:
            return caster(value)
        except (TypeError, ValueError):
            problems.append(f"{where}: {node.path} should be a number, not "
                            f"{value!r}")
            return node.default

    if kind == "date":
        if isinstance(value, datetime.datetime):
            return value.date().isoformat()
        if isinstance(value, datetime.date):
            return value.isoformat()
        text = str(value).strip()
        if text == "":
            return node.default
        if not DATE_RE.match(text):
            problems.append(f"{where}: {node.path} is {value!r}; dates are "
                            "written as YYYY-MM-DD")
            return node.default
        return text

    if kind == "enum":
        text = str(value).strip().lower()
        for allowed in node.values:
            if allowed.lower() == text:
                return allowed
        problems.append(f"{where}: {node.path} is {value!r}, which is not "
                        f"one of {', '.join(node.values)}")
        return node.default

    # string, text, path, language
    if isinstance(value, bool):
        # The Norway problem: YAML 1.1 reads an unquoted no, yes, on and
        # off as booleans, so `language: no` means Norwegian to the author
        # and False to the parser. There is no safe way to guess which
        # word was written, so this is an error rather than a coercion.
        problems.append(
            f"{where}: {node.path} was read as the boolean "
            f"{str(value).lower()} because YAML treats yes, no, on and off "
            "that way. Put it in quotes.")
        return node.default
    if value is None:
        return node.default
    if not isinstance(value, str):
        # A bare 1.10 is the number 1.1 by the time it reaches us, and the
        # trailing zero is already gone, so say so rather than pretend.
        problems.append(
            f"{where}: {node.path} is the {type(value).__name__} {value!r} "
            "rather than text; quote it to keep it exactly as written.")
        value = str(value)

    if kind == "ncname" and not NCNAME_RE.match(value):
        hint = ""
        if value[:1].isdigit():
            hint = ("; it starts with a digit, which XML names may not. "
                    "Put a letter in front.")
        elif ":" in value:
            hint = "; XML names may not contain a colon."
        if not hint:
            hint = (". Use letters, digits, and . - _ only, starting with "
                    "a letter.")
        problems.append(
            f"{where}: {node.path} is {value!r}, which is not a valid XML "
            f"name{hint}")
        return node.default

    if kind == "language" and not LANGUAGE_RE.match(value):
        problems.append(f"{where}: {node.path} is {value!r}, which is not a "
                        "language tag such as en, en-US, or es-MX")
        return node.default
    return value


def _coerce_tree(node, values, where, problems):
    out = {}
    for name, child in node.keys.items():
        present = values.get(name) if isinstance(values, dict) else None
        if child.is_section:
            out[name] = _coerce_tree(child, present or {}, where, problems)
        else:
            out[name] = _coerce(child, present, where, problems)
    # Anything the schema does not declare only reaches here when unknown
    # keys were allowed. It is carried through untouched so that writing
    # the config back out does not lose it.
    if isinstance(values, dict):
        for name, value in values.items():
            if name not in node.keys:
                out[name] = value
    return out


# --------------------------------------------------------------------------
# resolving
# --------------------------------------------------------------------------

class Resolved:
    """The settled configuration for one target."""

    def __init__(self, project, settings, target, warnings):
        self.project = project
        self.settings = settings
        self.target = target
        self.warnings = warnings

    def __getitem__(self, dotted):
        node = self.settings
        for part in dotted.split("."):
            node = node[part]
        return node


def resolve(schema, project_schema, documents, target=None,
            allow_unknown=False):
    """Settle one target's configuration. Raises ConfigError on any problem.

    documents are in increasing precedence: a project file first, then the
    tool's own file. Either may carry a `project:` block, so a directory
    holding only one of them still stands alone.

    allow_unknown turns an undeclared key from an error into a warning. A
    typo that silently does nothing is the failure this schema exists to
    prevent, so refusing is the default; the flag is for reading a config
    written for a newer version of the tools.
    """
    problems, warnings = [], []
    soft = warnings if allow_unknown else None

    # ---- project layer ---------------------------------------------------
    project_raw = project_schema.defaults()
    seen = {}
    for doc in documents:
        for key, value in (doc.project or {}).items():
            if key in seen and seen[key][1] != value and value is not None:
                warnings.append(
                    f"project.{key} is set to {seen[key][1]!r} in "
                    f"{seen[key][0]} and {value!r} in {doc.source}; the "
                    f"later file wins")
            seen[key] = (doc.source, value)
        project_raw = _merge(project_schema.root, project_raw,
                             doc.project, doc.source, problems, soft)

    # ---- settings layers -------------------------------------------------
    settings_raw = schema.defaults()
    for doc in documents:
        settings_raw = _merge(schema.root, settings_raw, doc.defaults,
                              doc.source, problems, soft)

    target_block, target_source = None, None
    if target is not None:
        for doc in documents:
            if target in doc.targets:
                target_block = doc.targets[target] or {}
                target_source = doc.source
        if target_block is None:
            available = sorted({t for doc in documents for t in doc.targets})
            listed = ", ".join(available) if available else "none are defined"
            raise ConfigError(f"no target named {target!r} ({listed})")
        settings_raw = _merge(schema.root, settings_raw, target_block,
                              target_source, problems, soft)

    # A target-only setting in the defaults block would apply to every
    # target at once, which is never what it means.
    for name, child in schema.keys.items():
        if not child.target_only:
            continue
        for doc in documents:
            if name in (doc.defaults or {}):
                problems.append(
                    f"{doc.source}: {name} belongs to a target, not to "
                    "defaults, because it has to differ between them")

    if problems:
        raise ConfigError("\n".join(problems))

    where = documents[-1].source if documents else "configuration"
    project = _coerce_tree(project_schema.root, project_raw, where, problems)
    settings = _coerce_tree(schema.root, settings_raw, where, problems)
    if problems:
        raise ConfigError("\n".join(problems))

    # A setting marked default_from_target names where this target's work
    # goes, and defaults to the target's own name so that two targets in
    # the same format cannot write over each other. Driven by the schema
    # rather than by a key name, because the conversion and packaging
    # schemas each have such a setting and they are not called the same
    # thing.
    if target is not None:
        for name, child in schema.keys.items():
            if child.default_from_target and not settings.get(name):
                settings[name] = target

    return Resolved(project, settings, target, warnings)


def target_names(documents):
    """Every target defined across the documents, in declaration order."""
    names = []
    for doc in documents:
        for name in doc.targets:
            if name not in names:
                names.append(name)
    return names


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------

def _scalar(value):
    """YAML for one value, quoted whenever leaving it bare would change it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_scalar(v) for v in value) + "]"
    text = str(value)
    if text == "":
        return '""'
    # Quote anything YAML would read as something other than this string:
    # the boolean words, anything that looks numeric, and anything
    # carrying syntax.
    risky = (text.lower() in TRUE_WORDS | FALSE_WORDS | {"null", "~"}
             or re.match(r"^[-+]?[\d.]+([eE][-+]?\d+)?$", text)
             or text[0] in "&*!%@`[]{}>|#,?:-'\""
             # A comma is harmless in a plain scalar and separates items
             # inside a flow sequence, and this is used for both, so it
             # has to be quoted either way.
             or "," in text
             or ": " in text or text != text.strip())
    if risky:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _wrap_comment(text, indent, width=74):
    out, line = [], f"{indent}#"
    for word in text.split():
        if len(line) + 1 + len(word) > width:
            out.append(line)
            line = f"{indent}#"
        line += " " + word
    if line.strip() != "#":
        out.append(line)
    return out


def _write_tree(node, values, lines, depth, skip_target_only):
    indent = "  " * depth
    extra = [k for k in (values or {}) if k not in node.keys]
    if extra:
        lines.append("")
        lines += _wrap_comment(
            "Not declared by this version's schema, so it was read but not "
            "used. It is written back unchanged in case a newer version "
            "understands it.", indent)
        for name in extra:
            rendered = yaml.safe_dump({name: values[name]},
                                      default_flow_style=False,
                                      sort_keys=False, allow_unicode=True)
            lines += [indent + l for l in rendered.rstrip().splitlines()]
    for name, child in node.keys.items():
        if child.target_only and skip_target_only:
            continue
        lines.append("")
        if child.description:
            lines += _wrap_comment(child.description, indent)
        if child.is_section:
            lines.append(f"{indent}{name}:")
            _write_tree(child, (values or {}).get(name) or {}, lines,
                        depth + 1, skip_target_only)
        else:
            value = (values or {}).get(name)
            if child.type == "opaque":
                rendered = yaml.safe_dump(
                    {name: value}, default_flow_style=False,
                    sort_keys=False, allow_unicode=True).rstrip()
                lines += [indent + l for l in rendered.splitlines()]
            elif child.type == "text" and isinstance(value, str) \
                    and value.strip():
                # A block scalar for anything with real line breaks, a
                # plain one otherwise. A single line of prose that happens
                # to end in a newline would otherwise be written quoted
                # with the newline inside the quotes -- valid, and
                # miserable to edit, which matters because a footer is the
                # setting people most often change by hand.
                body = value.strip()
                if "\n" in body:
                    lines.append(f"{indent}{name}: |")
                    for l in body.splitlines():
                        lines.append(f"{indent}  {l}")
                else:
                    lines.append(f"{indent}{name}: {_scalar(body)}")
            else:
                lines.append(f"{indent}{name}: {_scalar(value)}")


def _write_target(node, overrides, target_name, lines, depth):
    """One target block: its own settings in full, its overrides as deltas.

    A setting marked target_only has no other home. It cannot go in the
    defaults block, because a format or an output directory applied to
    every target at once is not a thing anyone means. So it is written
    here complete, with its description, the same way the defaults block
    writes everything else -- otherwise five settings would exist, be
    read, and be documented nowhere a reader would look.

    Everything else is written only where the target differs from the
    defaults. Repeating every inherited setting in every target would
    make the defaults block decorative and the file unreadable.
    """
    indent = "  " * depth
    for name, child in node.keys.items():
        if not child.target_only:
            continue
        # The declared default, never the value resolving would derive
        # from it. Writing a derived value pins it: a filename worked out
        # from the book's identifier, written into the file as a literal,
        # stops following the identifier the moment either changes. An
        # empty value here re-derives on every run, and the description
        # above it says what it derives to.
        value = overrides[name] if name in overrides else child.default
        lines.append("")
        if child.description:
            lines += _wrap_comment(child.description, indent)
        lines.append(f"{indent}{name}: {_scalar(value)}")

    rest = {k: v for k, v in overrides.items()
            if k in node.keys and not node.keys[k].target_only}
    if rest:
        lines.append("")
        lines += _wrap_comment(
            "Overrides of the defaults above. Anything not named here is "
            "inherited.", indent)
        _emit_overrides(node, rest, lines, depth)
    elif not any(c.target_only for c in node.keys.values()):
        lines += _wrap_comment("Uses the defaults unchanged.", indent)


def write_config(schema, project_schema, resolved_defaults, targets, path,
                 notes=(), include_project=True):
    """Write a complete configuration file.

    Complete is the point: every declared setting appears, at its resolved
    value, with its description above it. A generated file that omits
    settings is how the old sample writer silently dropped three of them,
    and a web front end that has to round-trip a config cannot work from
    anything less.

    Targets carry only what differs from the defaults, so the defaults
    block keeps meaning something and the file stays readable.
    """
    lines = [
        f"# Configuration for {os.path.basename(schema.source)}"
        .replace("schema-", "").replace(".yaml", ""),
        "#",
        "# Written from the schema, so every setting the tools read is",
        "# below with its description. Values are your own where you set",
        "# one and the documented default otherwise.",
    ]
    lines += [f"# {note}" for note in notes]

    # The project block is written inline so a directory holding only this
    # file still stands alone. It is left out when a project.yaml is being
    # written alongside, because two copies of the same setting means one
    # of them is stale the moment either is edited -- and the one that
    # wins is not the one a reader would expect.
    if include_project:
        lines.append("")
        lines.append("project:")
        _write_tree(project_schema.root, resolved_defaults.project, lines, 1,
                    skip_target_only=True)
    else:
        lines.append("")
        lines += _wrap_comment(
            "The book's own details -- language, identifier, title, "
            "contents -- are in project.yaml, which both halves read. To "
            "use this directory on its own, copy that file's project "
            "block in here.", "")

    lines.append("")
    lines.append("defaults:")
    _write_tree(schema.root, resolved_defaults.settings, lines, 1,
                skip_target_only=True)

    lines.append("")
    lines.append("targets:")
    if not targets:
        lines += _wrap_comment(
            "No targets defined. A target names one rendering and may "
            "override any default above.", "  ")
    for name, overrides in targets.items():
        lines.append("")
        lines.append(f"  {name}:")
        _write_target(schema.root, overrides or {}, name, lines, 2)

    text = "\n".join(lines).rstrip() + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def _flatten(node, values, prefix=""):
    out = {}
    for name, value in (values or {}).items():
        child = node.keys.get(name)
        if child is None:
            continue
        if child.is_section:
            out.update(_flatten(child, value, f"{prefix}{name}."))
        else:
            out[f"{prefix}{name}"] = value
    return out


def _emit_overrides(node, values, lines, depth):
    indent = "  " * depth
    for name, value in (values or {}).items():
        child = node.keys.get(name)
        if child is None:
            continue
        if child.is_section:
            inner = _flatten(child, value)
            if not inner:
                continue
            lines.append(f"{indent}{name}:")
            _emit_overrides(child, value, lines, depth + 1)
        else:
            lines.append(f"{indent}{name}: {_scalar(value)}")
