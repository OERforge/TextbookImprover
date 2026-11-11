"""
parallel.py -- run a suite's cases side by side, a process each, and
share one count of workers among the suites of a run.

The convert, LaTeX, EPUB, and decks suites hand their lists of cases
here. Each case writes in a directory of its own and reads nothing
another writes, so with more than one job each runs in a process of its
own: the suite's script again, told which case by its place in the
list. A case's lines are printed whole, in the list's order, as the
cases before it finish, so the output reads as it does one case at a
time.

The default is half the processors this process may use (at least one),
which leaves room for the rest of the machine; -j says otherwise, -j 1
running the cases one after another in the suite's own process.

run-all.sh starts these suites and the PDF suite side by side, and -j
is then the run's count, not each suite's: OER_TEST_SLOTS names a folder
holding a file for each worker they share, and a case, or one of the PDF
suite's builds, holds a lock on one of them while it runs (slot),
waiting while every one is held. The lock is flock's, which the system
drops when the process holding it ends, however it ends, so a suite
that's stopped takes no worker with it. A file added to the folder later
is a worker more: run-all.sh adds one when the suites it runs in turn,
which are one of the run's workers, are done. Without the variable, as
when a suite is run by itself, nothing is shared and nothing waits.

Ctrl-C stops a suite whose cases run side by side: the cases running
take it themselves, and no other is started (stop).

    python3 tests/parallel.py --default-jobs       # the default -j, for run-all.sh
    python3 tests/parallel.py SUITE.py [ARG ...]   # the suite, taking Ctrl-C

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
import contextlib
import os
import signal
import subprocess
import sys
import threading
import time

try:
    import fcntl
except ImportError:                           # Windows: nothing to share a count with
    fcntl = None

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


# The variable naming the folder of slots, one file a worker.
SLOTS = "OER_TEST_SLOTS"

# How long a wait for a slot sleeps between looks, in seconds, and how
# long between looks in the folder for a slot added since.
LOOK = 0.1
LIST = 1.0

# This process's hold on each slot. flock's lock belongs to the open
# file, which the threads here share, so one thread's lock wouldn't keep
# another's out; a lock of this process's own does, taken first.
_slots = {"lock": threading.Lock(), "folder": None, "names": [], "files": [], "mine": [],
          "listed": None}

# Set when the run is stopped (Ctrl-C): a wait for a slot gives up.
_stopped = threading.Event()


class Stopped(Exception):
    """The run was stopped while this waited for a slot."""


def stop():
    """Nothing more is to start: every wait for a slot ends in Stopped."""
    _stopped.set()


def slots():
    """How many workers the run shares, or 0 when nothing is shared;
    the folder is read again when it was last read LIST seconds ago or
    more, for a slot added since."""
    with _slots["lock"]:
        now = time.monotonic()
        if _slots["listed"] is None:
            _slots["folder"] = os.environ.get(SLOTS) if fcntl is not None else None
        elif now - _slots["listed"] < LIST:
            return len(_slots["files"])
        _slots["listed"] = now
        if _slots["folder"]:
            try:
                names = sorted(os.listdir(_slots["folder"]))
            except OSError:                   # the folder gone: a run that's over
                names = []
            for name in names:
                if name not in _slots["names"]:
                    try:
                        opened = os.open(os.path.join(_slots["folder"], name), os.O_RDWR)
                    except OSError:
                        continue
                    _slots["names"].append(name)
                    _slots["files"].append(opened)
                    _slots["mine"].append(threading.Lock())
        return len(_slots["files"])


@contextlib.contextmanager
def slot():
    """One of the run's workers, held for as long as the block runs: the
    first free one, looked for again every LOOK seconds while there's
    none. Nothing, at once, when no count is shared. Stopped is raised
    when the run is stopped before the block begins."""
    held = None
    # Each thread starts its look at a place of its own, so the waiting
    # threads of every suite aren't all after the first file.
    start = threading.get_ident()
    while held is None:
        count = slots()
        if _stopped.is_set():
            raise Stopped()
        if not count:
            break
        for step in range(count):
            index = (start + step) % count
            if not _slots["mine"][index].acquire(blocking=False):
                continue
            try:
                fcntl.flock(_slots["files"][index], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:                   # another process has it
                _slots["mine"][index].release()
                continue
            held = index
            break
        else:
            time.sleep(LOOK)
    try:
        yield
    finally:
        if held is not None:
            fcntl.flock(_slots["files"][held], fcntl.LOCK_UN)
            _slots["mine"][held].release()


def side_by_side(function, items, jobs, order=None):
    """function(item) for each of the items, `jobs` at a time, each in a
    thread: yields (item, result) in the items' order, as each is done.
    They're started in `order` (the items' own, without one). Ctrl-C
    while they run stops the rest: nothing more is started, the waits
    for a slot end, and what's left to wait for is what was running,
    whose own processes took the signal too."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
    try:
        futures = {item: pool.submit(function, item) for item in (order or items)}
        for item in items:
            yield item, futures[item].result()
    except BaseException:
        stop()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()


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
        with slot():
            done = subprocess.run([sys.executable, script, "--case-index", str(index)]
                                  + list(extra), stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout

    print(f"{len(indexes)} case(s), "
          + ("on the workers the run's suites share" if slots()
             else f"{jobs} at a time (-j 1 for one at a time)"))
    failed = 0
    for index, (status, output) in side_by_side(one, indexes, jobs, order):
        sys.stdout.write(output)
        if status < 0:
            print(f"  ERROR {cases[index][0]}: stopped by signal {-status}")
            failed += 1
        else:
            failed += status
        sys.stdout.flush()
    return failed


def main():
    """For run-all.sh: the default -j; or a suite started in this
    command's place, taking Ctrl-C."""
    arguments = sys.argv[1:]
    if arguments == ["--default-jobs"]:
        print(default_jobs())
        return 0
    if not arguments or arguments[0].startswith("-"):
        sys.exit("usage: parallel.py --default-jobs | SUITE.py [ARG ...]")
    # A shell that isn't keeping jobs starts a command it doesn't wait for
    # with Ctrl-C's signal ignored, which the command's own children
    # inherit, and Python leaves an ignored signal ignored: a suite
    # started that way would run on after its run was stopped. Caught
    # here, it's the system's default again in the program started from
    # here, so the suite takes it as it does in the foreground, and
    # cleans up after itself.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    os.execv(sys.executable, [sys.executable] + arguments)


if __name__ == "__main__":
    sys.exit(main())
