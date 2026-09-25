#!/usr/bin/env python3
# TextbookImprover -- tools for converting OER textbooks into accessible
# formats.
# Copyright (C) 2026 Robert Szarka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Fill in shortDOIs for the DOIs in a bare-links sidecar.

    python3 util/shortdoi.py bare-links.csv
    python3 util/shortdoi.py bare-links.csv --dry-run
    python3 util/shortdoi.py bare-links.csv --min-length 40

APA allows a shortDOI where a DOI is long or complex
(https://apastyle.apa.org/style-grammar-guidelines/references/dois-urls).
For each row whose Replacement is empty and whose URL is a DOI at doi.org
or dx.doi.org, this asks the International DOI Foundation's shortDOI
service (https://shortdoi.org/) for the DOI's short form and writes
https://doi.org/ followed by it (https://doi.org/10/b8xx35) as the
Replacement, which the sidecar then makes the link's address and text.
A row that already has a Replacement is a decision and is never changed.

Asking for a DOI that has no shortDOI yet creates one, which the service
reports (IsNew) and this counts. Requests are spaced --wait seconds
apart (one a second by default), and a 429 or a server error is retried
after a pause that doubles, or as long as the service's Retry-After asks.
The sidecar is rewritten in place, every other column and row as it was,
after a copy is kept beside it as <name>.bak.
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote, unquote

DOI_URL = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/(10\.\S+)$", re.I)
SHORT = re.compile(r"^10/[0-9A-Za-z]+$")
AGENT = ("TextbookImprover-shortdoi/1 "
         "(+https://github.com/OERforge/TextbookImprover)")


def doi_of(url):
    """The DOI a doi.org address names, decoded; None for any other."""
    m = DOI_URL.match(url.strip())
    return unquote(m.group(1)) if m else None


def lookup(service, doi, wait, retries, timeout):
    """(ShortDOI, IsNew) from the service, after retries; raises on failure."""
    url = service.rstrip("/") + "/" + quote(doi, safe="/():") + "?format=json"
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": AGENT})
    pause = max(wait, 0.5)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            short = str(data.get("ShortDOI") or "").strip()
            if not SHORT.match(short):
                raise ValueError(f"no shortDOI in the answer: {data!r}")
            return short, str(data.get("IsNew")).lower() == "true"
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500 or attempt == retries:
                raise
            after = exc.headers.get("Retry-After") if exc.headers else None
            time.sleep(float(after) if after and after.isdigit() else pause)
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
            time.sleep(pause)
        pause *= 2
    raise RuntimeError("unreachable")


def main():
    ap = argparse.ArgumentParser(
        description="Fill in shortDOIs for the DOIs in a bare-links sidecar.")
    ap.add_argument("sidecar", nargs="?", default="bare-links.csv",
                    help="the sidecar to fill in (default bare-links.csv)")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be looked up; ask nothing, write nothing")
    ap.add_argument("--min-length", type=int, default=0,
                    help="look up only DOI addresses at least this long "
                         "(APA: a long or complex DOI)")
    ap.add_argument("--wait", type=float, default=1.0,
                    help="seconds between requests (default 1)")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--service", default="https://shortdoi.org",
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not os.path.exists(args.sidecar):
        sys.exit(f"{args.sidecar}: not found. Copy bare-links-new.csv's rows "
                 "into it first.")
    with open(args.sidecar, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        sys.exit(f"{args.sidecar}: empty.")

    wanted = []
    for n, row in enumerate(rows):
        if not row or row[0].strip().lower() == "url":
            continue
        url = row[0].strip()
        replacement = row[1].strip() if len(row) > 1 else ""
        doi = doi_of(url)
        if replacement or doi is None or len(url) < args.min_length:
            continue
        wanted.append((n, url, doi))
    if not wanted:
        print(f"{args.sidecar}: no DOI without a Replacement"
              + (f" and at least {args.min_length} characters long" if args.min_length else "")
              + "; nothing to do.")
        return 0
    if args.dry_run:
        for _, url, _ in wanted:
            print("would look up", url)
        print(f"{len(wanted)} DOI(s) would be looked up at {args.service}.")
        return 0

    filled = created = 0
    failed = []
    for k, (n, url, doi) in enumerate(wanted):
        if k:
            time.sleep(args.wait)
        try:
            short, new = lookup(args.service, doi, args.wait, args.retries,
                                args.timeout)
        except Exception as exc:
            failed.append((url, str(exc)))
            print(f"  {url}: {exc}", file=sys.stderr)
            continue
        row = rows[n]
        while len(row) < 2:
            row.append("")
        row[1] = "https://doi.org/" + short
        filled += 1
        created += new
        print(f"  {url} -> {row[1]}" + ("  (created)" if new else ""))

    if filled:
        shutil.copyfile(args.sidecar, args.sidecar + ".bak")
        with open(args.sidecar, "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerows(rows)
    print(f"{filled} shortDOI(s) written to {args.sidecar}"
          + (f", {created} of them created by this request" if created else "")
          + (f"; {len(failed)} lookup(s) failed" if failed else "")
          + (f"; the original is {args.sidecar}.bak" if filled else "") + ".")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
