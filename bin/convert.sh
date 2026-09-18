#!/usr/bin/env bash

# Copyright 2026 Robert Szarka
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

# This script needs bash. If it was started as `sh convert.sh`, WSL runs it
# under dash, which has no `pipefail` and no BASH_SOURCE -- re-exec under bash
# so it works either way. Must stay POSIX-parseable and above the `set` line.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail
set -x

# Directory this script lives in, so its companions are found regardless of cwd.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
figure_filter="$script_dir/figures-and-tables.lua"
media_filter="$script_dir/media-extensions.lua"
config_reader="$script_dir/read-conversion-config.py"
cartridge_tool="$script_dir/build-cartridge.py"
headers_tool="$script_dir/table-headers.py"

for required in "$figure_filter" "$media_filter"; do
  if [ ! -f "$required" ]; then
    echo "Missing $required -- save it alongside this script." >&2
    exit 1
  fi
done

# Pandoc 3.9 introduced the options this script relies on. Earlier
# versions accept most of the command line and quietly do something else:
# 3.6 and older write grid tables without cell spans, so a table with
# merged cells loses them without any warning.
# Python 3 is required, not optional. It reads the configuration, and
# step 2 reads image references out of the JSON with it. In v0.1 it was
# needed only for the manifest and the cartridge, and both of those steps
# checked for it; step 2 arrived in v0.2 without a check, so a machine
# without Python failed part-way through a run having already written the
# intermediates. Saying so before any work starts is cheaper.
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. It reads the configuration and inspects the" >&2
  echo "  conversion intermediates, so it is required:" >&2
  echo "    sudo apt install python3 python3-yaml" >&2
  exit 1
fi

pandoc_version="$(pandoc --version | head -1 | awk '{print $2}')"
if [ "$(printf '%s\n3.9\n' "$pandoc_version" | sort -V | head -1)" != "3.9" ]; then
  echo "Pandoc $pandoc_version is too old; 3.9 or later is required." >&2
  exit 1
fi

# Every later step works from this list rather than from *.json. A
# directory that has been converted before also contains intermediates
# left over from earlier runs, and possibly intermediates whose .docx has
# since been moved away; globbing sweeps those in and makes one document's
# stale state look like a failure of this run.
run_docs="$(mktemp)"
refs_file="$(mktemp)"
missing_rows="$(mktemp)"
alt_rows="$(mktemp)"
header_rows="$(mktemp)"
spacer_rows="$(mktemp)"
unresolved_rows="$(mktemp)"
unresolved_log="$(mktemp)"
media_rows="$(mktemp)"
css_header="$(mktemp)"
work_dir="$(mktemp -d)"
trap 'rm -f "$run_docs" "$refs_file" "$missing_rows" "$alt_rows" \
        "$header_rows" "$spacer_rows" "$unresolved_log" "$unresolved_rows" \
        "$media_rows" "$css_header"; \
      rm -rf "$work_dir"' EXIT

export TABLE_CAPTIONS_MISSING="$missing_rows"
export IMAGE_ALT_MISSING="$alt_rows"
export TABLE_HEADERS_MISSING="$header_rows"
export SPACER_LOG="$spacer_rows"
export MEDIA_UNRESOLVED="$media_rows"


unresolved=0

# Media problems are reported the moment they are found, but with `set -x`
# on, that can be thousands of trace lines before the run stops. Keep a
# copy so the summary at the end can repeat them together.
note_unresolved() {
  printf '%s\n' "$@" >> "$unresolved_log"
  printf '%s\n' "$@" >&2
  unresolved=$((unresolved + 1))
}

# The same failure as one CSV row, so there is a list to work from rather
# than only a block of prose in the terminal.
note_unresolved_row() {
  printf '%s,%s,%s,%s\n' "$1" "$2" "$(printf '%s' "$3" | tr ',' ';')" \
    "$(printf '%s' "$4" | tr ',' ';')" >> "$unresolved_rows"
}

############################################
# 0. Read conversion settings from conversion.yaml
#
#    read-conversion-config.py resolves the config against a schema and
#    writes shell assignments here, so this script never parses YAML.
#    Everything goes into a temporary directory; the content directory is
#    untouched.
#
#    In v0.1 this asked build-cartridge.py, which meant a folder of
#    documents could not be converted without the packaging tool present.
#    Both halves now use the same configuration library and neither needs
#    the other.
############################################

# The schema's own defaults, repeated here so that a bare folder of
# documents converts with no configuration at all. Anything the config
# says overrides these; anything it does not mention keeps them.
LANGUAGE="en"
HEADER_MD=""
FOOTER_MD=""
PROMOTE_H1_TO_TITLE="always"
AUTHOR_BYLINE="meta"
SPACER_BELOW="0"
STRIP_SPACER="false"
ALT_MAX_CHARS="120"
RESPONSIVE_IMAGES="true"
WRAP_TABLES="true"
MEDIA_STRICT=""
TABLE_LABEL_PREFIXES="Table"
FIGURE_LABEL_PREFIXES="Figure"
TABLE_CAPTIONS_NAME="table-captions.csv"
IMAGE_ALT_NAME="image-alt.csv"
TABLE_CAPTIONS_MISSING_NAME="table-captions-missing.csv"
IMAGE_ALT_MISSING_NAME="image-alt-missing.csv"
TABLE_HEADERS_NAME="table-headers.csv"
TABLE_HEADERS_MISSING_NAME="table-headers-missing.csv"
TABLE_HEADERS_NEW_NAME="table-headers-new.csv"
TABLE_HEADERS_REPORT_NAME="table-headers-report.csv"
MEDIA_UNRESOLVED_NAME="media-unresolved.csv"
SPACER_LOG_NAME="spacer-images.csv"

if [ -f "imsmanifest.yaml" ] && [ ! -f "conversion.yaml" ]; then
  echo "imsmanifest.yaml is the v0.1 configuration and is no longer read." >&2
  echo "  Split it into project.yaml, conversion.yaml and packaging.yaml:" >&2
  echo "    python3 $script_dir/../util/migrate-config.py -d ." >&2
  echo "  It reports what it will do first with --dry-run, and never" >&2
  echo "  changes the original." >&2
  exit 1
fi

if [ -f "$config_reader" ]; then
  # A directory with no configuration converts with the defaults above.
  # A configuration that exists and cannot be read is a different matter,
  # and stops the run: the alternative is converting a whole book with
  # settings the user thought they had changed, which looks like success
  # and is not. v0.2.0 tolerated both cases alike, so a footer written at
  # the top level -- where v0.1 put it -- was reported and then ignored.
  if ! python3 "$config_reader" -d . "$work_dir"; then
    if [ -f "conversion.yaml" ] || [ -f "project.yaml" ]; then
      echo "" >&2
      echo "Stopping: the configuration could not be read." >&2
      echo "  Nothing was converted. Fix the problem above and re-run," >&2
      echo "  or move the file aside to convert with the defaults." >&2
      exit 1
    fi
  fi
  if [ -f "$work_dir/settings.sh" ]; then
    # shellcheck disable=SC1091
    . "$work_dir/settings.sh"
  fi
fi

export SPACER_BELOW STRIP_SPACER ALT_MAX_CHARS
export RESPONSIVE_IMAGES WRAP_TABLES MEDIA_STRICT
export TABLE_LABEL_PREFIXES FIGURE_LABEL_PREFIXES
export AUTHOR_BYLINE PROMOTE_H1_TO_TITLE
# Reports are written by the run and regenerated every time, so they
# belong beside the book they describe. In v0.1 that was also where the
# scripts were, because the scripts were copied into the content
# directory; from v0.2 the tools stay where they were cloned, and leaving
# the reports there would mean two books overwriting each other's.
#
# Sidecars are different, and the difference matters: they are read, never
# written, and they hold work no script can reproduce. A relative name
# resolves against the content directory, which is the convenient default.
# An absolute path is used as given, so corrections can live somewhere
# version-controlled instead of among the generated files. Resolving
# "$PWD/$name" unconditionally turned an absolute setting into
# "/book//home/you/sidecars/table-captions.csv", which no filter could
# read and nothing reported except an instruction to append your work to
# a path that did not exist.
#
# Their names come from the config, so these cannot be resolved until
# step 0 has run.
resolve_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
     *) printf '%s' "$PWD/$1" ;;
  esac
}

export TABLE_CAPTIONS="$(resolve_path "$TABLE_CAPTIONS_NAME")"
export IMAGE_ALT="$(resolve_path "$IMAGE_ALT_NAME")"
export TABLE_HEADERS="$(resolve_path "$TABLE_HEADERS_NAME")"

# A sidecar the config names but the filter cannot read is almost always a
# wrong path rather than a deliberately empty one, and the run would
# otherwise succeed while silently discarding every correction in it. The
# default names are exempt: not having written one yet is the normal
# starting state.
check_sidecar() {
  local path="$1" setting="$2" default="$3"
  [ -e "$path" ] && return 0
  [ "$(basename "$path")" = "$default" ] && [ "${path%/*}" = "$PWD" ] && return 0
  printf 'ERROR: %s is set to %s, which does not exist.\n' "$setting" "$path" >&2
  printf '       A relative name resolves against %s.\n' "$PWD" >&2
  printf '       Create the file, or remove the setting to use ./%s.\n' \
    "$default" >&2
  exit 1
}

check_sidecar "$TABLE_CAPTIONS" 'sidecars.table_captions' 'table-captions.csv'
check_sidecar "$IMAGE_ALT" 'sidecars.image_alt' 'image-alt.csv'
check_sidecar "$TABLE_HEADERS" 'sidecars.table_headers' 'table-headers.csv'

missing_report="$(resolve_path "$TABLE_CAPTIONS_MISSING_NAME")"
alt_report="$(resolve_path "$IMAGE_ALT_MISSING_NAME")"
header_report="$(resolve_path "$TABLE_HEADERS_MISSING_NAME")"
headers_new="$(resolve_path "$TABLE_HEADERS_NEW_NAME")"
headers_report="$(resolve_path "$TABLE_HEADERS_REPORT_NAME")"
unresolved_report="$(resolve_path "$MEDIA_UNRESOLVED_NAME")"
spacer_report="$(resolve_path "$SPACER_LOG_NAME")"

############################################
# 0.5. The table-headers pre-pass
#
#    Runs on the .docx files, before Pandoc sees them, because the
#    evidence the guess reads -- repeat-header rows, bold, shading -- does
#    not survive Pandoc's reader. For every data table it computes the
#    sidecar key, reads what the sidecar declares, guesses the rest, and
#    writes table-headers-report.csv. Tables with no sidecar row get a
#    prefilled row in table-headers-new.csv, in the sidecar's own format,
#    ready to paste in.
#
#    Nothing downstream consumes the result yet; that is the next step
#    of roadmap item 1. What this step establishes is the sidecar, the
#    key, and the report, so a book can start carrying declarations now.
#
#    A sidecar row whose key matches no table stops the run. A correction
#    that silently does not apply destroys work invisibly, and the report
#    lists the unmatched rows beside the tables no row claimed.
############################################
docx_files=()
for f in *.docx; do
  [ -e "$f" ] || continue
  case "$f" in '~$'*) continue ;; esac   # Word's owner file, not a document
  docx_files+=("$f")
done
if [ "${#docx_files[@]}" -gt 0 ]; then
  if ! python3 "$headers_tool" "${docx_files[@]}" --sidecar "$TABLE_HEADERS" \
       --new "$headers_new" --report "$headers_report"; then
    exit 1
  fi
fi

############################################
# 1. Convert DOCX -> a filtered JSON intermediate, extract media
#
#    JSON rather than Markdown. Markdown is a format with opinions, and
#    everything has to survive its grammar: it has no syntax for a cell
#    attribute or for a header column, which are precisely what the
#    remediation produces. It also picks the simplest table layout that
#    fits, which silently destroys a table whose cells are all empty --
#    three of them in these books, where a blank worksheet table came back
#    as a paragraph break. The JSON is Pandoc's own AST, so nothing is
#    lost, and `pandoc -f json -t markdown` renders it back to something
#    readable whenever a human wants to look.
#
#    The media filter runs here rather than afterwards. Word stores images
#    with whatever content type the DOCX declares, which is routinely
#    application/octet-stream; Pandoc turns that into a ".so" extension
#    and then writes <embed> instead of <img> -- a page that validates and
#    shows nothing. Renaming inside the mediabag, before --extract-media
#    writes anything, means the file and the reference cannot disagree.
#    v0.1 did this afterwards by walking the Markdown with grep and sed,
#    because by then it was the only option left.
#
#    --extract-media has to be on this run for the same reason: it is what
#    rewrites each src to "<base>/media/...", and that path is the key the
#    alt-text sidecar is stored under.
############################################
for f in *.docx; do
  [ -e "$f" ] || continue

  # Word writes an owner file beside any document it has open: the same
  # name prefixed with "~$", the same extension, and not a zip at all.
  # Pandoc fails on it and takes the whole run down with it.
  case "$f" in
    '~$'*)
      echo "Skipping $f: Word lock file, not a document." >&2
      echo "  Close the document in Word, or delete the file." >&2
      continue
      ;;
  esac

  if [ ! -s "$f" ]; then
    echo "Skipping $f: empty file." >&2
    echo "  On a cloud-synced drive this is usually a placeholder that has" >&2
    echo "  not been downloaded yet." >&2
    continue
  fi

  # A .docx is a zip, so it starts with "PK". An old .doc renamed to .docx
  # does not, and neither does a cloud-storage placeholder.
  if [ "$(head -c 2 -- "$f")" != "PK" ]; then
    echo "Skipping $f: not a .docx (no zip signature)." >&2
    echo "  An older .doc renamed to .docx looks like this. Open it in Word" >&2
    echo "  and use Save As to convert it." >&2
    continue
  fi

  base="${f%.docx}"

  pandoc \
    -f docx \
    -t json \
    "$f" \
    -o "$base.json" \
    --lua-filter="$media_filter" \
    --extract-media="$base"

  printf '%s\n' "$base.json" >> "$run_docs"
done

if [ ! -s "$run_docs" ]; then
  echo "No .docx files here, so there is nothing to convert." >&2
  exit 1
fi

# An intermediate with no matching .docx is not this run's output. Say so
# and leave it alone rather than treating its stale state as an error.
for stale in *.json; do
  [ -e "$stale" ] || continue
  grep -Fqx "$stale" "$run_docs" && continue
  echo "Skipping $stale: no matching .docx in this directory." >&2
  echo "  It is left over from an earlier run, or its .docx has moved." >&2
done

# Markdown from a v0.1 run is no longer read by anything. Leaving it in
# place is quietly misleading -- it looks like current output and is not --
# so it is named rather than removed, since deleting a user's files is not
# this script's decision to make.
for old in *.md; do
  [ -e "$old" ] || continue
  case "$old" in
    "$HEADER_MD"|"$FOOTER_MD") continue ;;
  esac
  echo "Note: $old is left over from a v0.1 run and is no longer read." >&2
done

############################################
# 2. Verify every media reference resolves
#
#    A dead image link is invisible in the generated HTML -- Pandoc emits
#    an <embed> rather than an <img> for an extension it does not
#    recognise. Stopping here is deliberate: broken output that looks fine
#    is worse than no output.
#
#    v0.1 spent this step repairing as well as checking, because the
#    renaming happened after extraction and the two could drift apart.
#    They cannot now, so what is left is a check. It is kept as a check
#    rather than dropped because the failure it guards against is silent,
#    and because the media filter still cannot identify every format Word
#    stores: EMF and WMF have no browser-renderable equivalent and have to
#    go back to the author.
############################################
# Every media path the intermediate refers to, one per line. Read out of
# the JSON with python3 rather than grep, because the AST is structured
# and an image path that happens to appear in prose is not a reference.
document_media_refs() {
  python3 - "$1" <<'PYEOF'
import json
import sys

def walk(node, out):
    if isinstance(node, dict):
        if node.get("t") == "Image":
            try:
                out.append(node["c"][2][0])
            except (KeyError, IndexError, TypeError):
                pass
        for value in node.values():
            walk(value, out)
    elif isinstance(node, list):
        for value in node:
            walk(value, out)

refs = []
with open(sys.argv[1], encoding="utf-8") as handle:
    walk(json.load(handle), refs)
for ref in sorted(set(refs)):
    # An absolute URL is not this script's to resolve.
    if not ref.startswith(("http://", "https://", "//", "data:")):
        print(ref)
PYEOF
}

while IFS= read -r doc; do
  [ -e "$doc" ] || continue
  document_media_refs "$doc" > "$refs_file"
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    [ -f "$ref" ] && continue
    note_unresolved "UNRESOLVED: $doc references missing $ref."
    note_unresolved_row "$ref" "$doc" "" "referenced but not on disk"
  done < "$refs_file"
done < "$run_docs"

# Anything the media filter could not identify. Its rows are already in the
# right shape, so they are folded in here and one gate covers both.
if [ -s "$media_rows" ]; then
  while IFS= read -r row; do
    [ -n "$row" ] || continue
    printf '%s\n' "$row" >> "$unresolved_rows"
    note_unresolved "UNRESOLVED: ${row%%,*} could not be identified."
  done < "$media_rows"
fi

if [ "$unresolved" -gt 0 ]; then
  # Repeat every reason here. With set -x the originals are far back in the
  # trace, and the summary on its own says nothing about what went wrong.
  { set +x; } 2>/dev/null
  echo "" >&2
  echo "===================================================" >&2
  cat "$unresolved_log" >&2
  echo "===================================================" >&2
  echo "Stopping: $unresolved media reference(s) could not be resolved." >&2

  { printf 'File,Source,Detected,Problem\n'; sort -u "$unresolved_rows"; } \
    > "$unresolved_report"
  echo "Written to $unresolved_report." >&2

  if grep -qi 'metafile\|EMF\|WMF' "$unresolved_rows"; then
    echo "" >&2
    echo "EMF/WMF are Word's vector formats, used for equations, SmartArt" >&2
    echo "and pasted Office charts. No browser renders them, so they have" >&2
    echo "to be replaced. In Word: right-click the image, Save as Picture," >&2
    echo "choose PNG, then re-insert. Or convert in place:" >&2
    echo "  libreoffice --headless --convert-to png --outdir DIR FILE" >&2
    echo "and rename the result to the name the document expects." >&2
  fi

  echo "No HTML was generated." >&2
  exit 1
fi

# Past the gate, this run will finish and the reports at the end will be
# written with whatever is outstanding. Clear them now so one left behind
# by an earlier run cannot survive into a run that has nothing to report.
# Doing it here rather than at the top means a run that stops at the gate
# leaves the previous reports intact, since they are still the best list
# available.
rm -f "$missing_report" "$alt_report" "$header_report" "$spacer_report"

############################################
# 3. Render the header and footer fragments
#
#    Pandoc's --include-before-body and --include-after-body take HTML, so
#    Markdown from the config is rendered once here and reused for every
#    page. The fragment is inserted by the template, after the Lua filter
#    has run, which is why promoting the leading H1 to the page title
#    still works -- but also why nothing in the fragment is processed by
#    the filter. Author its images with explicit alt text.
############################################

header_html=""
footer_html=""

render_fragment() {
  src="$1"
  out="$2"
  [ -n "$src" ] && [ -f "$src" ] || return 0
  pandoc \
    -f markdown-implicit_figures \
    -t html5 \
    --ascii \
    "$src" \
    -o "$out"
  printf '%s' "$out"
}

if [ -n "$HEADER_MD" ]; then
  header_html="$(render_fragment "$HEADER_MD" "$work_dir/header.frag.html")"
fi
if [ -n "$FOOTER_MD" ]; then
  footer_html="$(render_fragment "$FOOTER_MD" "$work_dir/footer.frag.html")"
fi

############################################
# 4. Convert the JSON intermediate → HTML5
#
#    --lua-filter  rewrites DOCX layout tables into <figure>/<figcaption>,
#                  gives data tables a real <caption> plus scope="col"
#                  headers and a scroll wrapper, replaces image alt text
#                  from the sidecar, applies the spacer rule, and promotes
#                  the leading H1 to the page title
#    -M lang       sets the html lang attribute (WCAG 3.1.1), from the
#                  project's declared language. v0.1 hardcoded "en" while
#                  the manifest read its own separate setting, so a book
#                  in any other language shipped pages that disagreed with
#                  the package describing them, and nothing checked.
#
#    -implicit_figures is gone with the Markdown. It existed because the
#    Markdown reader wrapped every standalone image in a <figure>
#    captioned with a copy of its own alt text, and Word stores some
#    equations as pictures with MathSpeak alt text, so that caption
#    printed strings like "StartLayout 1st Row 1st Column upper C u s t o
#    m e r ..." as visible body copy. Reading JSON there is no such
#    reader extension to disable. Figures built by the Lua filter are
#    unaffected either way -- it constructs them directly.
#
#    --math-method=mathml rather than --mathml, which Pandoc 3.11
#    deprecated. MathML is now the default, so the option is stated only
#    to keep the intent visible.
#
#    --embed-resources is deliberately NOT used. Base64 data URIs inflate
#    every page and Brightspace does not render them reliably from an
#    imported Common Cartridge, so each page links to its extracted images
#    at <page>/media/... instead.
############################################

cat > "$css_header" <<'CSS'
<style>
/* Caption contrast -- WCAG 1.4.3 / 1.4.6.
   Pandoc's stylesheet sets no colour on captions, so they fall back to
   inheritance or the browser default and can land well under 4.5:1.
   #555 on Pandoc's #fdfdfd background measures 7.33:1, which clears AAA
   while staying visibly lighter than the #1a1a1a body text. Note that the
   familiar "accessible grey" #767676 is only 4.47:1 here -- it is computed
   against pure white, and Pandoc's background is not pure white. */
figcaption,
table caption {
  color: #555;
}

/* Pandoc's stylesheet sets `display: block` on tables so they can scroll
   sideways. That silently strips the table role from the browser
   accessibility tree, so screen readers stop exposing rows, columns and
   header associations -- WCAG 1.3.1. Restore real table display and move
   the scrolling onto the wrapper the Lua filter adds. */
table {
  display: table;
  width: 100%;
}
.table-wrapper {
  overflow-x: auto;
  margin: 1em 0;
}
.table-wrapper:focus-visible {
  outline: 2px solid #1a1a1a;
  outline-offset: 2px;
}

/* Word puts the "Table 2.1" label below the table; keep it there. */
table caption {
  caption-side: bottom;
  margin-top: 0.75em;
  margin-bottom: 0;
  text-align: left;
}

figure { margin: 1.5em 0; }
figure img { height: auto; }
figcaption {
  font-size: 0.9em;
  line-height: 1.4;
  margin-top: 0.5em;
}

/* Pandoc's print block forces the body to black; keep captions in step so
   they do not print lighter than the surrounding text. */
@media print {
  figcaption,
  table caption {
    color: black;
  }
}
</style>
CSS

while IFS= read -r f; do
  [ -e "$f" ] || continue
  base="${f%.json}"

  pandoc_args=(
    -f json
    -t html5
    "$f"
    -o "$base.html"
    --standalone
    --ascii
    --math-method=mathml
    --lua-filter="$figure_filter"
    --include-in-header="$css_header"
    -M "lang=$LANGUAGE"
  )
  [ -n "$header_html" ] && pandoc_args+=(--include-before-body="$header_html")
  [ -n "$footer_html" ] && pandoc_args+=(--include-after-body="$footer_html")

  pandoc "${pandoc_args[@]}"
done < "$run_docs"

############################################
# 5. Report items still needing human input
############################################

# Sort and deduplicate the collected rows into a report, or remove a stale
# report when nothing is outstanding -- the file existing at all is the
# signal that there is work to do.
write_report() {
  rows_file="$1"
  report="$2"
  header="$3"
  noun="$4"
  sidecar="${5:-}"
  hint="${6:-}"   # optional; set -u would otherwise abort on shorter calls

  if [ ! -s "$rows_file" ]; then
    rm -f "$report"
    return 0
  fi

  { printf '%s\n' "$header"; sort -u "$rows_file"; } > "$report"
  count=$(sort -u "$rows_file" | wc -l)
  echo "Wrote $report ($count $noun)." >&2
  [ -n "$sidecar" ] && \
    echo "Fill in the second column, then append the rows to $sidecar." >&2
  [ -n "$hint" ] && echo "$hint" >&2
  return 0
}

write_report "$missing_rows" "$missing_report" \
  'Label,Description,Source,Excerpt' 'table(s) needing a description' "$TABLE_CAPTIONS"

write_report "$alt_rows" "$alt_report" \
  'Image,Alt,Source,Reason,CurrentAlt' 'image(s) needing alt text' "$IMAGE_ALT" \
  'Use [decorative] in the Alt column for images that carry no meaning.'

write_report "$spacer_rows" "$spacer_report" \
  'Image,Source,Width,Action' 'spacer image(s) handled'

# No sidecar for this one: header text has to come from the DOCX, so the
# report names the tables and the fix is made in Word.
if [ -s "$header_rows" ]; then
  { printf 'Table,Source,Rows,Columns\n'; sort -u "$header_rows"; } > "$header_report"
  count=$(sort -u "$header_rows" | wc -l)
  echo "Wrote $header_report ($count data table(s) with no header row)." >&2
  echo "Fix in Word: select the header row, Table Properties > Row >" >&2
  echo "  'Repeat as header row at the top of each page'. Where a table has" >&2
  echo "  no header row at all, one has to be written." >&2
else
  rm -f "$header_report"
fi

if [ -s "$missing_rows" ]; then
  rows=$(sort -u "$missing_rows" | wc -l)
  labels=$(sort -u "$missing_rows" | cut -d, -f1 | sort -u | wc -l)
  if [ "$labels" -lt "$rows" ]; then
    # The sidecar is keyed on the label alone, so one description would be
    # applied to every table sharing that label -- worth knowing about.
    echo "Note: the same label appears in more than one document." >&2
    echo "Only one description can apply per label; check the Source column." >&2
  fi
fi

############################################
# 6. Build the Common Cartridge manifest
#
#    Handed off to build-cartridge.py, which is read-only with respect to
#    page content and can be run on its own against any directory of HTML.
#    Arguments given to convert.sh are passed straight through, so
#    `./convert.sh --zip` builds the archive too.
############################################

if [ ! -f "$cartridge_tool" ]; then
  echo "No $cartridge_tool, so skipping the manifest." >&2
elif ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found, so skipping the manifest." >&2
else
  python3 "$cartridge_tool" -d . "$@"
fi
