# Auditing without converting

`audit.py` says what is wrong with a file and changes nothing. It takes Word and Markdown sources, HTML pages, EPUBs, and PDFs, in any mix, and writes two things: `audit.csv`, one finding per row, and `audit.md`, the same findings as a report a person reads.

```bash
python3 $T/bin/audit.py ~/books/nursing            # everything in a directory
python3 $T/bin/audit.py syllabus.pdf book.epub -o ~/reports --report-docx
```

It depends on `lib/` and on Pandoc, to read a source. `pypdf` (for PDFs), epubcheck, the Nu HTML checker, and veraPDF are used when present and reported as absent when not; `--quick` skips the external ones.

## What it checks, by kind of file

**A Word or Markdown source** is read by Pandoc with no filter, so the audit sees the author's file as it is, one file as one document (a `project.yaml` beside it supplies the book's language): images with no alt text and no `{.decorative}` marker, tables with no header row, no marker, and no first column that keys the rows, links whose text is their own URL and that carry no `aria-label` (with one, the accessible name is the label), headings that skip a level, raw HTML the conversion would pass through untouched, math ending in a thin space (which can't be written back as Markdown), and a missing title or language. A Word source adds what the [table census](architecture.md) can say: for each data table, the headers the run would guess and why, or that it couldn't settle them.

**An HTML page or an EPUB** goes through the [output check](checking.md) as it is, plus the validators when they're installed.

**A PDF** gets the simple report: what the file states about itself, read with `pypdf`, and what that implies. Title, author, language, dates, producer, PDF version, size and SHA-256; XMP metadata and its fields; what the file *claims* (PDF/UA-1 or -2, PDF/A) as distinct from what it is; whether it's tagged and has a structure tree, with a count of tags by type; the bookmark outline; pages with no extractable text, which are scans; fonts and whether they're embedded; encryption. A claim is reported as a claim: "claims PDF/UA-2" is a fact about the file, and whether it *is* PDF/UA-2 is veraPDF's to say, which the audit runs when it finds it. Ace stays by hand.

## What a Markdown file's YAML means to the audit

Each file is read as its own document, so a YAML block applies to the file it heads: its `title`, its `lang`, and nothing else's. A book whose files were written to be concatenated by a Pandoc command line, with one `_preamble.md` carrying the YAML for all of them, is read one file at a time here, and the other files have no YAML as far as the audit can see. The book's facts live in `project.yaml`, which the audit reads when it sits beside the files: `language` there answers the language question for every file. That is the only configuration the audit uses, and it's optional; `conversion.yaml` and `packaging.yaml` are the conversion's business. The audit could instead take the first file's YAML as the book's when `contents` gives an order, but that would make a report depend on a guess the reader can't see; `project.yaml` says the same thing in the open.

## The findings format

`audit.csv` has these columns, in this order:

`Where, Check, Detail, File, Kind, Severity, Standard, Tool, Fix`

The first three are what `output-check.csv` has always carried, so anything reading that today reads this. `Kind` is `source-docx`, `source-md`, `html`, `epub`, or `pdf`. `Severity` is `error`, `warning`, or `note`, so a validator's failure and a "worth a look" don't read the same. `Standard` names the criterion when there is one, in a form that says which standard and how strict: for WCAG, the lowest 2.x version the success criterion appears in, its number, and its level (`WCAG 2.0 SC 1.3.1 (A)`, `WCAG 2.1 SC 1.4.10 (AA)`); for PDF/UA, the clause of ISO 14289-1 (`PDF/UA-1 clause 7.1`); `EPUB 3.3`; `HTML Living Standard`. It's what turns a finding into an argument with a vendor. `Tool` is who said so: `oer`, `census`, `epubcheck`, `vnu`, `verapdf`. `Fix` is where the fix lives, `source`, `sidecar`, `manual`, or `tool`, which is the column to sort by. Every check's meaning, severity, standard, and usual fix are declared once, in `lib/findings.py`; `output-check.csv` from a conversion now uses the same columns.

## The report, and when it's stale

`audit.md` opens with the date and the tool's version, then every input with its size and SHA-256, then a summary (counts by severity and by check, each check explained), the findings grouped by file, and for each PDF its metadata and claims. The hashes are how you know a report is current: if a file's hash has changed, the report is stale for it. A stable file name, rather than one with a date in it, is what makes reports diffable and linkable; the date is inside.

The same hashes key `audit-cache.json` beside the report. Run again with nothing changed, the audit says so at the prompt (`Nothing has changed since the audit of <date>; audit.md is current`) and leaves the report alone, so its date stays the date of the audit it records; the exit code still reflects the findings. With some inputs changed, only those are read again and the report is rewritten. `--force` reads everything, `--no-cache` ignores the cache both ways. A PDF is always re-read, since its metadata section is built fresh each time.

Markdown is the report's own form. `--report-html` also writes `audit.html`, the report as a page with the pipeline's own stylesheet embedded; `--report-docx` also writes `audit.docx`, declared as the current Word format so Word treats it as a current file and its own Accessibility Checker runs on it (Pandoc's own Word output opens in Compatibility Mode, which turns that checker off). The switches are named for the report's format, not the input's: the audit reads any mix of files whatever it writes.

## `convert.py --check-only`

The conversion's own reports (media unresolved, table headers, captions, alt text, page names) come from the steps before rendering. `convert.py --check-only` runs those steps and stops: no output directory, nothing packaged. It's the audit from the conversion's point of view, with the sidecars applied; `audit.py` is the source's own view, with nothing applied.
