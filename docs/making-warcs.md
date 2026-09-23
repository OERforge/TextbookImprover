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

wget obeys the site's `robots.txt`. If the crawl stops after the first page and the site's rules forbid crawlers, ask the site's owners before adding `-e robots=off`.

To see what the crawl got:

```bash
ls -lh *.warc.gz
zcat cs168.warc.gz | grep -c '^WARC-Type: response'
```

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

*A Data-Centric Introduction to Computing*: 80 pages either way, but the crawl's HTML still holds the TeX of 397 formulas that the `.mhtml` save had only as MathJax's rendering, so the EPUB has real MathML. Its 143 responses also came to a tenth of the save's size, since a save stores a copy of every shared asset per page.

*CS 168*: the same 62 pages with the same names and the same order, one asset fewer (a badge on another host, which the browser had already downloaded and a crawl inside the site doesn't fetch), and the order read from the site's real `<ul>` rather than what its scripts had built. Nine pages differ in their text, images, and formulas, because the book itself changed between the save and the crawl: a page that read "there are $p$ nodes" now reads "$D$".

## Unpacking it

```bash
python3 $T/bin/unpack-site.py ~/warcs/cs168/cs168.warc.gz -o ~/books/cs168-from-warc
python3 $T/bin/unpack-site.py crawls/collections/cs168/cs168.wacz -o ~/books/cs168-from-wacz
```

Then convert as for any book: `cd` there and run `convert.py`.
