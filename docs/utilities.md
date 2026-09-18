# Utilities

Tools in `util/` that are not part of a conversion but help before or around one: surveying a corpus, checking a source, comparing two runs.

| Tool | Purpose |
| --- | --- |
| `migrate-config.py` | One-time: splits a v0.1 `imsmanifest.yaml` into the three v0.2 files. |
| `manifest-to-yaml.py` | One-time: turns an existing `imsmanifest.xml` into `project.yaml` and `packaging.yaml`. |
| `untrack-deletions.py` | One-time source repair: turns Word tracked deletions into ordinary strikethrough. |
| `compare-output.py` | Compares two runs semantically, so a pipeline change can be checked rather than trusted. |
| `table-census.py` | Surveys table structure across a corpus of DOCX files: the command line over `lib/tablecensus.py`. |
| `table-samples.py` | Collects one real example of each table shape into a single Word document, copied from the sources rather than rebuilt. |
| `docx-compat.py` | Reads, and optionally sets, the Word compatibility mode of a DOCX. |
| `settings-reference.py` | Writes the three settings reference pages under `docs/` from the schemas; `--check` says whether they are current. |

Each takes `--help`. The census and sample tools read Word files directly and need no Pandoc; `compare-output.py` reads HTML; `docx-compat.py` touches nothing but `word/settings.xml`.

`table-census.py`, `table-samples.py`, and `docx-compat.py` are the ones to reach for before converting a book you have not seen: the census says what shapes its tables take and what the run will guess about each, the sample document shows one real example of every shape so you can see what would be lost, and the compatibility check says whether Word will open the sources in Compatibility Mode.

## Repairing tracked deletions in the source

Some authors use Word's tracked-deletion mark as *content* — a
before-and-after table showing which words to cut from a sentence. That is
revision history carrying meaning, and anything that resolves revisions
destroys it: Word's own "Accept All Changes", most converters, and Pandoc,
which accepts changes by default. A before-and-after example then shows two
identical sentences.

```bash
# Scan a directory. --check writes nothing, so -o is not needed.
for f in *.docx; do python3 untrack-deletions.py "$f" --check; done

# Repair one file.
python3 untrack-deletions.py BC-14.docx -o BC-14-fixed.docx
```

Each `<w:del>` becomes ordinary runs with `<w:strike/>`, so the appearance
is unchanged in Word but the meaning no longer depends on a revision being
left unresolved. Only `word/document.xml` is touched; every other part of
the package is copied through byte for byte. Strikethrough reaches the HTML
as `<del>`.

`--track-changes=all` on the Pandoc call is the non-destructive
alternative, but it only fixes this pipeline, leaves the document fragile
for every other consumer, and emits `<span class="deletion">` needing CSS.

## Files that are not documents

A glob of `*.docx` picks up things that are not documents, and both
`convert.sh` and `untrack-deletions.py` skip them by name with a message
rather than failing:

| What | Why it appears |
|---|---|
| `~$Name.docx` | Word's owner file, written while a document is open. Not a zip. |
| Empty file | On a cloud-synced drive, usually a placeholder not yet downloaded. |
| No `PK` signature | An older `.doc` renamed to `.docx`. Open it in Word and use Save As. |

Skipping is per file, so one bad file no longer takes the whole run down.
