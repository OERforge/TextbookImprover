"""
parallel.py -- run a suite's cases side by side, a process each.

The convert, LaTeX, and EPUB suites hand their lists of cases here. Each
case writes in a directory of its own and reads nothing another writes,
so with more than one job each runs in a process of its own: the suite's
script again, told which case by its place in the list. A case's lines
are printed whole, in the list's order, as the cases before it finish,
so the output reads as it does one case at a time.

The default is half the processors this process may use (at least one),
which leaves room for the rest of the machine; -j says otherwise, -j 1
running the cases one after another in the suite's own process.

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

import argparse
import concurrent.futures
import os
import subprocess
import sys

# A process's exit status holds a count of failed checks up to this.
MOST = 125


def processors():
    """The processors this process may run on."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):         # macOS and Windows have no affinity
        return os.cpu_count() or 1


def default_jobs():
    return max(1, processors() // 2)


def add_options(parser):
    """-j, and the option a suite's own process is told its case with."""
    parser.add_argument("-j", "--jobs", type=int, default=default_jobs(), metavar="N",
                        help="run N cases at once (default: half the processors, "
                             f"{default_jobs()} here); -j 1 runs them one after another")
    parser.add_argument("--case-index", type=int, default=None, help=argparse.SUPPRESS)


def run(script, cases, chosen, jobs, extra=(), first=()):
    """Run the cases of the list `cases` whose labels are in `chosen`
    (every one when it's empty), `jobs` at a time, each as its own process
    of `script` given --case-index and `extra`; print each one's output in
    the list's order; return how many checks failed. Cases whose labels
    are in `first` start before the rest, so a run isn't left waiting on
    one long case at its end."""
    indexes = [i for i, (label, _) in enumerate(cases) if not chosen or label in chosen]
    order = sorted(indexes, key=lambda i: cases[i][0] not in first)

    def one(index):
        done = subprocess.run([sys.executable, script, "--case-index", str(index)]
                              + list(extra), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout

    print(f"{len(indexes)} case(s), {jobs} at a time (-j 1 for one at a time)")
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {index: pool.submit(one, index) for index in order}
        for index in indexes:
            status, output = futures[index].result()
            sys.stdout.write(output)
            if status < 0:
                print(f"  ERROR {cases[index][0]}: stopped by signal {-status}")
                failed += 1
            else:
                failed += status
            sys.stdout.flush()
    return failed
