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
cartridge_tool="$script_dir/build-cartridge.py"

if [ ! -f "$figure_filter" ]; then
  echo "Missing $figure_filter -- save it alongside this script." >&2
  exit 1
fi

export TABLE_CAPTIONS="$script_dir/table-captions.csv"
export IMAGE_ALT="$script_dir/image-alt.csv"

missing_report="$script_dir/table-captions-missing.csv"
alt_report="$script_dir/image-alt-missing.csv"
header_report="$script_dir/table-headers-missing.csv"
unresolved_report="$script_dir/media-unresolved.csv"

# Every later step works from this list rather than from *.md. A directory
# that has been converted before also contains Markdown left over from
# earlier runs, and possibly Markdown whose .docx has since been moved
# away; globbing *.md sweeps those in and makes one document's stale state
# look like a failure of this run.
run_docs="$(mktemp)"
refs_file="$(mktemp)"
missing_rows="$(mktemp)"
alt_rows="$(mktemp)"
header_rows="$(mktemp)"
spacer_rows="$(mktemp)"
unresolved_rows="$(mktemp)"
unresolved_log="$(mktemp)"
css_header="$(mktemp)"
work_dir="$(mktemp -d)"
trap 'rm -f "$run_docs" "$refs_file" "$missing_rows" "$alt_rows" \
        "$header_rows" "$spacer_rows" "$unresolved_log" "$unresolved_rows" \
        "$css_header"; \
      rm -rf "$work_dir"' EXIT

export TABLE_CAPTIONS_MISSING="$missing_rows"
export IMAGE_ALT_MISSING="$alt_rows"
export TABLE_HEADERS_MISSING="$header_rows"
export SPACER_LOG="$spacer_rows"

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
# 0. Read conversion settings from imsmanifest.yaml
#
#    build-cartridge.py owns the config file and its parser; this step
#    asks it for the handful of settings that affect conversion rather
#    than parsing YAML in shell. Everything is written into a temporary
#    directory, so the content directory is untouched.
############################################

HEADER_MD=""
FOOTER_MD=""
SPACER_BELOW="0"
STRIP_SPACER="false"
SPACER_LOG_NAME="spacer-images.csv"
ALT_MAX_CHARS="120"
TABLE_LABEL_PREFIXES="Table"
FIGURE_LABEL_PREFIXES="Figure"

if [ -f "$cartridge_tool" ] && command -v python3 >/dev/null 2>&1; then
  python3 "$cartridge_tool" -d . --emit-conversion-config "$work_dir" || true
  if [ -f "$work_dir/settings.sh" ]; then
    # shellcheck disable=SC1091
    . "$work_dir/settings.sh"
  fi
fi

export SPACER_BELOW STRIP_SPACER ALT_MAX_CHARS
export TABLE_LABEL_PREFIXES FIGURE_LABEL_PREFIXES
spacer_report="$script_dir/$SPACER_LOG_NAME"

############################################
# 1. Convert DOCX → Markdown, extract media
#    into per-document subdirectories
#
#    Grid tables are left enabled. With -grid_tables, any table Pandoc
#    cannot express in simple Markdown -- one with multi-block cells, say
#    -- falls back to a raw HTML block, which then passes through the Lua
#    filter untouched: no caption, no scope attributes, no scroll wrapper.
#
#    --wrap=none is not cosmetic. Pandoc's default wrapping can break a
#    line in the middle of an image path, and every later grep and sed
#    here assumes one reference per line. A wrapped path turned
#    "media/image1.gif" into "media/image1.g" + "if" and produced a dead
#    link that only the media gate caught.
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
    -t markdown \
    --wrap=none \
    "$f" \
    -o "$base.md" \
    --extract-media="$base"

  printf '%s\n' "$base.md" >> "$run_docs"
done

if [ ! -s "$run_docs" ]; then
  echo "No .docx files here, so there is nothing to convert." >&2
  exit 1
fi

# Markdown with no matching .docx is not this run's output. Say so and
# leave it alone rather than treating its stale state as an error.
for md in *.md; do
  [ -e "$md" ] || continue
  grep -Fqx "$md" "$run_docs" && continue
  echo "Skipping $md: no matching .docx in this directory." >&2
  echo "  It is left over from an earlier run, or its .docx has moved." >&2
done

############################################
# 2. Resolve extracted media
#
#    Word stores images with whatever extension the DOCX declares, which
#    is often meaningless (.so, from a ContentType of
#    application/octet-stream). This step is driven by the Markdown: for
#    every media reference it locates the file actually on disk, renames
#    it to match its real content type, and rewrites the reference to
#    agree -- as one operation per reference.
#
#    Matching on the stem rather than the extension makes this idempotent
#    and self-healing: whatever state a document was left in by an earlier
#    run, re-running reconciles the file and the reference.
############################################

# Real extension for a file, from its content. Empty means "not an image
# format a browser can display".
media_extension() {
  case "$(file -b --mime-type "$1")" in
    image/png)                 echo png ;;
    image/jpeg)                echo jpg ;;
    image/gif)                 echo gif ;;
    image/svg+xml)             echo svg ;;
    image/webp)                echo webp ;;
    image/avif)                echo avif ;;
    image/bmp|image/x-ms-bmp)  echo bmp ;;
    image/tiff)                echo tiff ;;
    image/x-icon|image/vnd.microsoft.icon) echo ico ;;
    *)                         echo "" ;;
  esac
}

# `file --mime-type` calls a Word metafile application/octet-stream, which
# says nothing useful. The human-readable description names it, so use that
# in the message and to spot the formats worth naming specifically.
media_description() {
  file -b -- "$1" 2>/dev/null | head -c 60
}

media_advice() {
  case "$(media_description "$1")" in
    *Metafile*|*EMF*|*WMF*)
      echo "Word metafile (EMF/WMF): vector art no browser displays." ;;
    *)
      echo "Not an image format browsers display." ;;
  esac
}

# How many writes had to be retried before they were visible. A non-zero
# count here is the signature of a filesystem that does not present a
# consistent view -- typically a cloud-synced folder mounted into WSL.
retries=0

# Rename, then confirm the result is actually visible. One retry, because
# on a synced mount the first read after a write can still show the old
# state; a second failure is treated as real.
rename_media() {
  mv -f -- "$1" "$2" 2>/dev/null || true
  [ -f "$2" ] && return 0
  sleep 1
  retries=$((retries + 1))
  mv -f -- "$1" "$2" 2>/dev/null || true
  [ -f "$2" ]
}

# Rewrite one reference, then confirm the old one is gone. The pattern is
# escaped so a dot in a filename cannot match some other character.
rewrite_reference() {
  rewrite_md="$1"
  rewrite_from="$2"
  rewrite_to="$3"
  rewrite_re="$(printf '%s' "$rewrite_from" | sed 's/[^[:alnum:]_/-]/\\&/g')"

  sed -i "s|${rewrite_re}|${rewrite_to}|g" "$rewrite_md"
  grep -qF -- "$rewrite_from" "$rewrite_md" || return 0
  sleep 1
  retries=$((retries + 1))
  sed -i "s|${rewrite_re}|${rewrite_to}|g" "$rewrite_md"
  ! grep -qF -- "$rewrite_from" "$rewrite_md"
}

# Media references for one document, anchored to that document's own
# extraction directory. A blanket '/media/' pattern also matches ordinary
# URLs in the prose -- reference chapters cite pages such as
# https://www1.nyc.gov/site/dca/media/Face-Masks-... -- and those are not
# files this script has any business resolving. Everything outside
# [alnum]_/- is escaped so the base name cannot act as a regex.
document_media_refs() {
  md_file="$1"
  base_re="$(printf '%s' "${md_file%.md}" | sed 's/[^[:alnum:]_/-]/\\&/g')"
  grep -oE "${base_re}/media/[^ )<>\"]+" "$md_file" 2>/dev/null | sort -u || true
}

while IFS= read -r md; do
  [ -e "$md" ] || continue

  document_media_refs "$md" > "$refs_file"

  # Redirected from a file, not a pipe, so the loop runs in this shell and
  # can increment the unresolved counter.
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue

    stem="${ref%.*}"

    # Prefer the file the Markdown already points at. Otherwise take the
    # most recently written candidate: a directory converted before can
    # hold both this run's extraction and an earlier run's renamed copy,
    # and picking alphabetically would sometimes choose the stale one.
    if [ -f "$ref" ]; then
      actual="$ref"
    else
      actual="$(ls -t -- "$stem".* 2>/dev/null | head -n 1 || true)"
    fi

    if [ -z "$actual" ] || [ ! -f "$actual" ]; then
      note_unresolved "UNRESOLVED: $md references $ref" \
                      "            nothing on disk matches $stem.*"
      note_unresolved_row "$ref" "$md" "" "no file matches $stem.*"
      continue
    fi

    ext="$(media_extension "$actual")"
    if [ -z "$ext" ]; then
      described="$(media_description "$actual")"
      note_unresolved \
        "UNRESOLVED: $actual" \
        "            detected as: $described" \
        "            $(media_advice "$actual")"
      note_unresolved_row "$actual" "$md" "$described" "$(media_advice "$actual")"
      continue
    fi

    target="${stem}.${ext}"

    # Both the rename and the rewrite are checked afterwards rather than
    # trusted. mv and sed report success as soon as the kernel accepts the
    # write, which on a network or cloud-synced mount is not the same as
    # the change being visible to the next command. Without these checks a
    # lost write surfaces much later -- as a gate failure, or as HTML
    # pointing at a file that no longer exists -- with nothing to say where
    # it went wrong.
    if [ "$actual" != "$target" ]; then
      if ! rename_media "$actual" "$target"; then
        note_unresolved \
          "UNRESOLVED: renamed $actual to $target, but $target is not there" \
          "            (the filesystem did not keep the rename)"
        note_unresolved_row "$actual" "$md" "" "rename did not take effect"
        continue
      fi
    fi

    if [ "$ref" != "$target" ]; then
      if ! rewrite_reference "$md" "$ref" "$target"; then
        note_unresolved \
          "UNRESOLVED: rewrote $ref to $target in $md, but $md still" \
          "            references $ref (the filesystem did not keep the edit)"
        note_unresolved_row "$ref" "$md" "" "rewrite did not take effect"
        continue
      fi
    fi

    # Drop any other copy of the same image left by an earlier run, so the
    # ambiguity above cannot build up over time.
    for sibling in "$stem".*; do
      [ -f "$sibling" ] || continue
      [ "$sibling" = "$target" ] || rm -f -- "$sibling"
    done
  done < "$refs_file"
done < "$run_docs"

############################################
# 3. Verify every media reference resolves
#
#    A dead image link is invisible in the generated HTML -- Pandoc emits
#    an <embed> rather than an <img> for an extension it does not
#    recognise. Stopping here is deliberate: broken output that looks
#    fine is worse than no output.
############################################

while IFS= read -r md; do
  [ -e "$md" ] || continue
  document_media_refs "$md" > "$refs_file"
  while IFS= read -r ref; do
    [ -n "$ref" ] || continue
    [ -f "$ref" ] && continue
    note_unresolved \
      "UNRESOLVED: $md still references missing $ref after resolution."
    note_unresolved_row "$ref" "$md" "" "still missing after resolution"
  done < "$refs_file"
done < "$run_docs"

# A retry only ever succeeds when the first attempt was lost, so any count
# above zero says the working directory is not giving a consistent view of
# its own writes.
if [ "$retries" -gt 0 ]; then
  echo "" >&2
  echo "Note: $retries media write(s) had to be retried before the change" >&2
  echo "  was visible. That is a filesystem symptom, not a conversion one." >&2
  echo "  A cloud-synced folder (Google Drive, OneDrive, Dropbox) mounted" >&2
  echo "  into WSL is the usual cause. Converting on the Linux filesystem" >&2
  echo "  and copying the finished cartridge back avoids it." >&2
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
    echo "and rename the result to the name the Markdown expects." >&2
  fi

  echo "No HTML was generated." >&2
  exit 1
fi

# Past the gate, this run will finish and step 6 will write whatever is
# outstanding. Clear the reports now so that one left behind by an earlier
# run cannot survive into a run that has nothing to report. Doing it here
# rather than at the top means a run that stops at the gate leaves the
# previous reports intact, since they are still the best list available.
rm -f "$missing_report" "$alt_report" "$header_report" "$spacer_report"

############################################
# 4. Render the header and footer fragments
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
# 5. Convert Markdown → HTML5
#
#    --lua-filter  rewrites DOCX layout tables into <figure>/<figcaption>,
#                  gives data tables a real <caption> plus scope="col"
#                  headers and a scroll wrapper, replaces image alt text
#                  from the sidecar, applies the spacer rule, and promotes
#                  the leading H1 to the page title
#    -M lang=en    sets the html lang attribute (WCAG 3.1.1)
#
#    -implicit_figures stops Pandoc wrapping every standalone image in a
#    <figure> captioned with a copy of its own alt text. Word stores some
#    equations as pictures with MathSpeak alt text, so that caption printed
#    strings like "StartLayout 1st Row 1st Column upper C u s t o m e r ..."
#    as visible body copy. Figures built by the Lua filter are unaffected --
#    it constructs them directly and does not rely on this extension.
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
  base="${f%.md}"

  pandoc_args=(
    -f markdown-implicit_figures
    -t html5
    "$f"
    -o "$base.html"
    --standalone
    --ascii
    --mathml
    --lua-filter="$figure_filter"
    --include-in-header="$css_header"
    -M lang=en
  )
  [ -n "$header_html" ] && pandoc_args+=(--include-before-body="$header_html")
  [ -n "$footer_html" ] && pandoc_args+=(--include-after-body="$footer_html")

  pandoc "${pandoc_args[@]}"
done < "$run_docs"

############################################
# 6. Report items still needing human input
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
# 7. Build the Common Cartridge manifest
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
