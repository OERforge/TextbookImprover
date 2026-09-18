# Troubleshooting and known limits

## Converting on a cloud-synced drive

Both the rename and the reference rewrite in step 2 are checked after the
fact rather than trusted. `mv` and `sed` report success as soon as the
kernel accepts the write, which on a network or cloud-synced mount isn't
the same as the change being visible to the next command. Each is retried
once, and the run reports how often that was needed:

```
Note: 3 media write(s) had to be retried before the change
  was visible. That is a filesystem symptom, not a conversion one.
```

Any count above zero means the working directory isn't giving a
consistent view of its own writes. A Google Drive, OneDrive or Dropbox
folder mounted into WSL (`/mnt/h/...`) is the usual cause, and the
symptoms are erratic: a run fails, the next run fails differently, the
third succeeds. **Convert on the Linux filesystem** (`~/work`, not
`/mnt/...`) and copy the finished `.imscc` back.

If a write is lost twice, the run stops naming the exact file and
operation rather than letting it surface later as a missing image.

## Troubleshooting

**`set: Illegal option -o pipefail`** — the script is running under dash.
Use `bash convert.sh` or `./convert.sh`, not `sh convert.sh`. It re-execs
itself under bash, so this should only appear with a very old copy.

**`\r: not found`, then syntax errors** — CRLF line endings from a Windows
editor. `sed -i 's/\r$//' convert.sh`, and set
`git config --global core.autocrlf input`.

**`couldn't unpack docx container`** — a file that isn't a DOCX. Word lock
files (`~$Name.docx`), empty cloud placeholders and renamed `.doc` files
are skipped by name, size and signature; anything else reaching Pandoc is
genuinely malformed.

**`Stopping: N media reference(s) could not be resolved`** — see
`media-unresolved.csv`. Usually EMF/WMF.

**A page appears in no report but looks wrong** — check
`packaging-sample.yaml`. If a run worked out an ordering, the sample
holds what it decided.

**Keys like `page#table-3` don't match what you see** — the number counts
data tables only, in reading order; image-only tables become figures and
aren't counted. The `Excerpt` column identifies the row.

**Reports keep listing things you fixed** — check the sidecar key. Table
descriptions key on the label (`Table 2.1`) or a positional key; image alt
keys on the media path ignoring its extension.

## Known limits

- **Header row text can't be invented.** A table whose cells hold nothing
  that could be a header -- a grid of measurements -- is reported as
  `needs-word` in `table-headers-report.csv`, not fixed. Add the header in
  Word, where it benefits every downstream format. Where the header text is
  there and only unmarked, a value in `table-headers.csv` is enough.
- **Equation images stay images.** Rejoining MathSpeak identifiers is a
  mitigation. The real fix is authoring them as Word equations, which
  convert to MathML.
- **Identical files in different media directories are separate files.**
  Each page gets its own copy from Word. Content-level deduplication would
  require rewriting page markup, which would break the read-only guarantee.
- **Cross-page links aren't rewritten** for the LMS's internal link
  format, so links between sections may not resolve after import.
- **Strikethrough conveys meaning visually.** `<del>` isn't announced by
  most screen readers by default, so a before-and-after table should say so
  in its column heading or caption.
- **Complex tables are reported, not fixed.** A table with stacked column
  headers, or with a header row and a header column, needs `headers`/`id`
  associations that no current setting can express. See the roadmap.
- **Word's "Mark as layout table" doesn't mark anything.** Word's
  Accessibility Checker flags a table with no header row and offers
  "Mark as layout table" as the fix. Taking that offer removes the
  table's `w:tblStyle` reference and resets `w:tblLook`, and writes no
  record of the claim: no `w:tblCaption`, no `w:tblDescription`, no
  element in any namespace, nothing in `settings.xml`. So the conversion
  can't see the declaration, can't honor it, and can't warn about it.
  What it can do is lose the evidence: a header row whose shading came
  from the table style rather than from direct formatting stops looking
  like a header row, and the table converts as though it never had one.
  If a table genuinely presents data with nothing to relate -- a grid of
  measurements laid out to fit the page -- it needs no header cells to
  conform, and the useful thing to add is a caption, not a layout
  marking.
- **Two PAC errors on a tagged PDF are the validator's, not the file's.**
  This matters only once PDF is an output (roadmap item 8), but it's
  worth recognizing rather than chasing. *Table header cell has no
  associated subcells* is raised because `latex-lab` sets `Scope` through
  an attribute class and PAC doesn't resolve `/ClassMap` references:
  rewriting the same value as an inline `/A` dictionary makes PAC pass
  with no change to the content, veraPDF never raises it, and
  [tagging-project discussion #930](https://github.com/latex3/tagging-project/discussions/930)
  has the maintainers declining to change the implementation, since the
  class is what makes `TH-both` expressible for a cell that heads both a
  row and a column. *Invalid use of a TR structure element* is raised
  because PAC rejects `Artifact` as a child of `Table`, which is how a
  repeated `longtable` header row is represented; ISO 32000-2 Annex L,
  Table L.2 permits it, so the file conforms, and
  [tagging-project issue #1583](https://github.com/latex3/tagging-project/issues/1583)
  says the same. It has been reported to PAC; there's no public ticket to
  watch.
- **One conversion target, one package.** The configuration is shaped for
  several of each, and the tools resolve them correctly, but only `html`
  and `common-cartridge` are implemented.
- **`cartridge-files.txt` can't build a prefixed package.** `zip -@`
  names each member after the path it read, so it can't place files under
  a directory. Use `--zip`; the file list says so in its header when a
  prefix is in effect.
- **`compare-output.py` matches tables by position**, so inserting one
  table reports every later table on that page as changed. It also flags a
  `.docx` and its `.json` intermediate as a duplicated filename, which is
  noise rather than a finding.
