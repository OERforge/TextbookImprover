# Making a WARC of a book's website

A WARC holds every URL a crawl fetched with the bytes the server sent, before any script ran. It's the best thing to give [`unpack-site.py`](site-input.md): the links are the site's own, nothing was renamed, and math written for MathJax is still TeX. A browser's "Save page as" keeps the page as it stood after its scripts ran, and an `.mhtml` save keeps no scripts at all, so a page's equations can be lost.

Look for the book's source first. A book built from Markdown, AsciiDoc, or LaTeX in a public repository converts better from that than from any copy of its website.

Two ways to make one follow. Use wget unless the site builds its pages with JavaScript: a crawler that runs a browser is slower, needs Docker, and records the same bytes for a static site.

## wget

wget fetches pages the way a script does, without running the page's JavaScript, and writes a WARC as it goes. It's on most Linux systems and in WSL's Ubuntu.

```bash
wget --version | head -1        # anything from 1.14 writes WARCs
sudo apt install wget           # if that said "command not found"
```

The two commands below are examples: they're the ones used for the two books these instructions were tested on. For another book, change the URL, the working directory, and the WARC's name. What matters is where the crawl starts, since `--no-parent` keeps it inside the directory of its starting URL: start at the directory that holds the book, its home page or, for a site that keeps several editions, the edition's own contents page.

Make a working directory, then crawl. For *CS 168*:

```bash
mkdir -p ~/warcs/cs168 && cd ~/warcs/cs168
wget --recursive --level=inf --no-parent --page-requisites \
     --wait=0.5 --random-wait --no-verbose \
     --warc-file=cs168 \
     https://textbook.cs168.io/
```

For *A Data-Centric Introduction to Computing*, start at the edition's contents page, so `--no-parent` keeps the crawl inside that edition's directory:

```bash
mkdir -p ~/warcs/dcic && cd ~/warcs/dcic
wget --recursive --level=inf --no-parent --page-requisites \
     --wait=0.5 --random-wait --no-verbose \
     --warc-file=dcic \
     https://dcic-world.org/2025-08-27/index.html
```

What the options do:

- `--recursive --level=inf` follows links to every page it can reach, and `--no-parent` stops it climbing above the directory it started in.
- `--page-requisites` fetches what each page needs to show itself: images and stylesheets.
- `--wait=0.5 --random-wait` pauses between requests, which is the polite way to crawl someone else's site.
- `--warc-file=cs168` writes `cs168.warc.gz` beside the copy of the site wget also writes (in a directory named for the host). The copy can be deleted afterwards; the WARC is what counts.

Don't use `--mirror`. It turns on timestamping, which wget can't combine with a WARC, and it says so and turns it off again.

wget stays on the host it started on. `--page-requisites` fetches what a page needs from that host and records a reference to anything elsewhere without fetching it. A browser's save fetches everything a page shows, wherever it lives, which is why the two can differ. *CS 168*'s front page shows the Creative Commons license badge from `i.creativecommons.org`, so its save has the badge and its crawl doesn't. `unpack-site.py` reports such a file as `resource-not-held`; the book's HTML then points at the badge online, and its EPUB, which can't hold an image from another server, links to it by its alt text instead. To fetch images from another host as well, let wget leave the starting host and name the hosts it may go to:

```bash
wget --recursive --level=inf --no-parent --page-requisites \
     --span-hosts --domains=textbook.cs168.io,i.creativecommons.org \
     --wait=0.5 --random-wait --no-verbose \
     --warc-file=cs168 \
     https://textbook.cs168.io/
```

List only the hosts that serve the book's own files: `--span-hosts` applies to the links wget follows as well as to what pages show, and `--domains` is what keeps it from wandering. This variant hasn't been run against either book.

wget obeys the site's `robots.txt`. If the crawl stops after the first page and the site's rules forbid crawlers, ask the site's owners before adding `-e robots=off`.

If wget stops at once with `ERROR 403: Forbidden`, the site is refusing it: some sites, or the services in front of them, turn away anything that doesn't identify itself as a browser. wget could claim to be one (`--user-agent`), but that's getting around a choice the site's owners made, as ignoring `robots.txt` is. What to try instead, in order:

- **The publisher's own exports.** A platform like Pressbooks offers EPUB and PDF, and often XHTML or HTMLBook, in a book's "Download this book" menu. An EPUB goes to [`unpack-epub.py`](epub-input.md) and is usually the cleaner source anyway.
- **A capture in a real browser**, with ArchiveWeb.page ([below](#archivewebpage-recording-as-you-read)) or Browsertrix Crawler. A site that serves its readers serves these too.
- **The site's owners**, for a copy or for permission to crawl.

Two sites these instructions were tested against refused wget this way. For the Pressbooks one, its EPUB was the source used; for the OER Commons one, whose EPUB had no images, ArchiveWeb.page was.

To see what the crawl got:

```bash
ls -lh *.warc.gz
zcat cs168.warc.gz | grep -c '^WARC-Type: response'
```

## ArchiveWeb.page, recording as you read

[ArchiveWeb.page](https://github.com/webrecorder/archiveweb.page) is a browser extension from Webrecorder, the makers of Browsertrix. While it's recording, it keeps every request the browser makes and every response it gets, and it saves them as a WACZ. It's the tool for a site that refuses wget, one that builds its pages with JavaScript, or one that shows its content only to someone signed in, because what it records is exactly what a reader's browser receives.

It runs in Chrome and in browsers built on Chrome's engine (Edge, Brave). Install it from the Chrome Web Store (search for ArchiveWeb.page, published by Webrecorder) and pin it to the toolbar so its icon is at hand. It needs nothing else: no Docker, no command line.

1. **Open the book's first page**, and sign in first if the site shows the book only to signed-in readers.
2. **Start recording** from the extension's icon. It records the tab you're in, into an archive that it names "My Archiving Session" unless you give it another name.
3. **Visit every page of the book.** Follow the book's own menu page by page rather than jumping around, and let each page finish loading. Scroll to the bottom of a long page, since many sites fetch an image only when it comes into view. Videos don't need to be played: a frame keeps pointing at the video wherever it lives, so the player isn't needed in the archive.
4. **Stop recording**, then open the extension's list of archives, select the one you recorded, and download it as a WACZ.
5. **Unpack it** as you would a WARC (next section), and read `unpack-report.csv`. The `order` row says how many of the book's pages the menu reached, and a `resource-not-held` row names anything a page showed that the archive doesn't hold. Record a page again, in a new session, to fill a gap.

A site that fetches its sections into one page by script, as OER Commons does, is still one page per section after unpacking: the unpacker takes each section's HTML from the data the page fetched. *Business Communication* on OER Commons came out as its 16 chapters and its title page, with 213 of the pages' 214 images held. The one missing, the title page's cover, has no response in the archive at all, and was missing when the site was viewed as well. Its publisher's EPUB had none of the images: 121 of its "images" are a web server's refusal.

These steps say what to do rather than quoting the extension's buttons, whose wording changes between versions; the test capture was made with version 0.17.1.

## Browsertrix Crawler, for a site built by JavaScript

[Browsertrix Crawler](https://github.com/webrecorder/browsertrix-crawler) runs a real browser in a Docker container and records everything it fetched, into a WACZ: WARCs in a zip, which `unpack-site.py` reads as well. It's what to use when a page's content only appears once its scripts run.

It needs Docker. On Windows, install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) and turn on its WSL integration for your Ubuntu distribution (Settings, Resources, WSL integration). On Ubuntu itself:

```bash
sudo apt install docker.io
sudo usermod -aG docker "$USER"   # then log out and back in
docker run hello-world            # checks that Docker works
```

Then crawl, which downloads the crawler's image the first time:

```bash
mkdir -p ~/warcs/browsertrix && cd ~/warcs/browsertrix
docker run -v "$PWD/crawls:/crawls/" -it webrecorder/browsertrix-crawler \
  crawl --url https://textbook.cs168.io/ --scopeType prefix \
  --collection cs168 --generateWACZ --workers 2
```

The WACZ is written to `crawls/collections/cs168/cs168.wacz`. `--scopeType prefix` keeps the crawl to URLs that begin with the starting one; `--limit 20` stops it after twenty pages, which is a sensible first try.

The crawler's options are from its documentation, and I couldn't run Docker where these instructions were written: if one of them has been renamed, `docker run webrecorder/browsertrix-crawler crawl --help` lists the current ones.

## What a WARC gave that a save didn't

Both books were crawled with the wget commands above and compared with the browser saves of the same sites.

*A Data-Centric Introduction to Computing*: 80 pages either way, but the crawl's HTML still holds the TeX of 397 formulas that the `.mhtml` save had only as MathJax's rendering, so the EPUB has real MathML. The crawl is also smaller: 12 MB of responses against the save's 22 MB (8.7 MB against 11 MB compressed), since a save stores its own copy of an image in every page that shows it.

*CS 168*: the same 62 pages with the same names and the same order, one asset fewer (the license badge from another host, described above), and the order read from the site's real `<ul>` rather than what its scripts had built. Nine pages differ in their text, images, and formulas, because the book itself changed between the save and the crawl: a page that read "there are $p$ nodes" now reads "$D$".

## Converting it

Conversion is two steps. `convert.py` converts a directory of sources and doesn't read a WARC; `unpack-site.py` reads the WARC and writes that directory:

```bash
python3 $T/bin/unpack-site.py ~/warcs/cs168/cs168.warc.gz -o ~/books/cs168
cd ~/books/cs168
python3 $T/bin/convert.py
```

A WACZ from Browsertrix is unpacked the same way (`unpack-site.py crawls/collections/cs168/cs168.wacz -o …`), and the file is recognized by what it holds, whatever it's called.

The directory is the book from then on. It holds the pages, their images once each, and a `project.yaml` with the order the site's menus gave, and it's where your corrections go: `project.yaml`, the sidecars, a `_pt/` of finished pages. Converting again reads the directory, not the WARC. Keep the WARC as the record of what was fetched and when. To start from a newer crawl, unpack it into a new directory (the unpacker won't write into one that isn't empty) and copy your `project.yaml` and sidecars across; `table-headers.csv` and `image-alt.csv` are keyed on a table's content and an image's path, so their rows still apply wherever those are unchanged.
