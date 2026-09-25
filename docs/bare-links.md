# Bare links

A bare link is one whose text is its own address, as in a reference list:

    Seidel, G. E. 2014. "Update on Sexed Semen Technology in Cattle." Animal 8:160-64. https://doi.org/10.1017/S1751731114000202.

A screen reader reads the whole address aloud, and the statistics textbook's longest runs to 132 characters. This page is about what a book can do about that, and why the pipeline offers what it does.

## What the pipeline does

Every run finds the bare links (a link whose text, without `https://`, a trailing slash, or percent-encoding, is its own address, for `http`, `https`, or `ftp`) and writes the undecided ones to `bare-links-new.csv`, one row per address:

```
URL,Replacement,Title,Source,Context
https://doi.org/10.1080/08913810508443640,,,refs,"Klein and Stern. 2005. “Professors and Their Politics.”"
```

`Source` names the pages the address is on, and `Context` is the text before its first use, usually the citation. Copy the rows into `bare-links.csv` and decide each one:

- **A Replacement that is a URL** (`http`, `https`, or `ftp`) replaces the link's address and its text: `https://doi.org/10/b8xx35` for the DOI above. That's how a shortDOI goes in.
- **Any other Replacement** replaces only the text, and the link isn't bare any more: `The Data and Story Library's cars data`.
- **A Title** becomes the link's title: a tooltip in HTML and EPUB, a ScreenTip in Word once there's Word output. A blank Title keeps whatever title the source gave the link.
- **A row with both columns blank** keeps the link as it is. That's a decision too, and the link leaves the report.

The replacement happens on the way through the filter, so the sources keep their addresses and a row keeps matching on every run. A row matching no bare link in the book is named at the end of the run, as a mistyped address would be. [Sidecar files](sidecars.md) has what all the sidecars share.

## shortDOIs

[APA allows a shortDOI](https://apastyle.apa.org/style-grammar-guidelines/references/dois-urls) where a DOI is long or complex: `https://doi.org/10/b8xx35` for `https://doi.org/10.1080/08913810508443640`, which resolves to the same place. `util/shortdoi.py` fills them in, asking the International DOI Foundation's [shortDOI service](https://shortdoi.org/) for each DOI in the sidecar with no Replacement yet:

```bash
python3 $T/util/shortdoi.py bare-links.csv --dry-run      # what it would look up
python3 $T/util/shortdoi.py bare-links.csv                # look up and write
python3 $T/util/shortdoi.py bare-links.csv --min-length 40  # only the long ones
```

It asks one a second (`--wait` changes that), waits out a busy service, never changes a Replacement already there, and keeps the sidecar as it was beside it as `bare-links.csv.bak`. Asking for a DOI that has no shortDOI yet creates one, which it counts. A shortDOI is opaque, which is its cost: the publisher's prefix in `10.1080/...` is gone, so keep full DOIs where readers use them to recognize a source.

Shortening other addresses with a URL shortener, and addresses written as plain text rather than links, are left for later: see the [roadmap](../ROADMAP.md).

## Why this, and not something else

The question looks simple: give the link a better name for screen readers. It isn't, because of three WCAG criteria. A reference list's bare URLs already conform at Level AA: **2.4.4** (Link Purpose, In Context, Level A) accepts the citation around a link as its context. A description would add **2.4.9** (Link Purpose, Link Only, AAA). And **2.5.3** (Label in Name, Level A) requires a link's accessible name to contain its visible text, so that a speech-input user who says what's on the screen reaches the link. Anything replacing the name of a link whose text is a URL fails a Level A criterion to gain an AAA one.

These were considered, and tested with NVDA in Chrome on a page of seven variants:

- **An `aria-label` holding a description** ("DOI for Klein and Stern 2005") is what NVDA users would find easiest: it's the only variant that doesn't read the URL. It fails 2.5.3, so a book that conforms at AA with bare URLs would stop conforming.
- **An `aria-label` holding the URL and then the description** passes 2.5.3, but NVDA reads the whole URL first, and the citation beside it already says what the description would.
- **A `title`, or `aria-describedby`** (to a hidden description or to the citation) makes the description the link's accessible description, not its name, so 2.5.3 holds. NVDA reads it after the whole URL, on Tab and line by line, so it adds words without saving any. The title is still kept through every source and target for its tooltip, and the sidecar's Title column fills it.
- **Linking the work's title instead of showing its address** is APA's alternative for work published only online. It loses the address in print and the DOI a reader copies, and reference formats expect the address. A text Replacement does it for a book that wants it.
- **Linking the title and keeping the address as plain text** (as some OER guides do) keeps print and copying, but the address stops being a live link, which APA's live DOIs don't allow, and NVDA still reads it in continuous reading.

What does shorten the reading is a shorter address, which APA already allows, and which keeps the link bare, visible, live, and correct in print. That's the Replacement column and the shortDOI helper. Everything else in the list stays possible through the same sidecar, one row at a time, where an author decides it's worth the cost.
