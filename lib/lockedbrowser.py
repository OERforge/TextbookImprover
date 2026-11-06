"""
lockedbrowser.py -- pages opened in Playwright's Chromium with nothing
reachable but what they're served from: a folder, an EPUB, or files in
memory.

axecheck.py's worker opens every page it checks this way, and so would a
web front end checking pages strangers upload, which is why each of
these is here and none is left to the pages' good behavior:

- The worker takes itself off the network before Playwright starts
  (leave_network): a user namespace that maps its user to itself, with a
  network namespace in it whose only interface is a loopback that's
  down. A plain unshare --user --net maps the user to nobody, which
  keeps Chromium's sandbox from starting, so the maps are written here,
  with ctypes, since os.unshare came with Python 3.12.
- Chromium's own sandbox, which Playwright leaves off unless asked
  (launch). It can't start as root, and Ubuntu 24.04's AppArmor may stop
  it for a Chromium no profile covers; sandbox_state reads /proc for
  whether its renderers are in it.
- No name resolves (--host-resolver-rules) and no proxy is used,
  whatever the environment says.
- Each page in a context of its own, at a made-up origin, ORIGIN (.invalid
  never resolves, RFC 2606), every request answered by Visit: a file of
  the source is served, with its type from a fixed table and nosniff;
  anything else is refused; and once the page has loaded, its own
  navigation anywhere, a refresh to itself among them, gets an empty 204,
  which leaves it where it is. Refusing such a navigation outright puts
  Chromium's error page in its place, and axe-core then checks that.
- A Content Security Policy on every response (POLICY), which blocks the
  page's own scripts and anything from elsewhere. What Playwright
  evaluates isn't held to it, so axe-core still runs; turning JavaScript
  off doesn't work, since then no timer or message reaches what's
  evaluated, and axe-core never finishes. A presentation TextbookImprover
  wrote runs its own scripts, by their hashes (axecheck.py).
- A WebSocket isn't routed as other requests are: route_web_socket takes
  each one, and never connects it.
- Service workers and downloads are blocked, and no permission granted.
- Every step of opening a page, and of closing it, has a time it must
  finish in (within): a page Chromium can't open, as it couldn't one
  104,000 pixels square, is given up on rather than waited for.

The policy "local", a run on a person's own machine, uses each of the
first two the system allows and says which it couldn't; "service", for
a front end, refuses to go on without both.

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

import ctypes
import hashlib
import os
import posixpath
import sys
import zipfile
from urllib.parse import quote, unquote, urlsplit

ORIGIN = "https://textbookimprover.invalid"
POLICIES = ("local", "service")
# The most a file served may weigh: a page's video needn't be read whole
# into memory to check the page.
LIMIT = 32 * 1024 * 1024
# What every response carries, the page's scripts blocked unless a
# presentation's are named by their hashes (axecheck.py). Inline styles
# are allowed: every page TextbookImprover writes carries page.css in a
# <style> element.
POLICY = ("default-src 'none'; script-src {scripts}; style-src 'self' 'unsafe-inline'; "
          "img-src 'self' data:; font-src 'self' data:; media-src 'self'; frame-src 'self'; "
          "object-src 'none'; base-uri 'none'; form-action 'none'; connect-src 'none'; "
          "worker-src 'none'; manifest-src 'none'")
NO_SCRIPTS = "'none'"
# A file's type, by its extension; anything else is served as bytes,
# which nosniff keeps the browser from taking for a page or a script.
CONTENT_TYPES = {
    ".html": "text/html", ".htm": "text/html", ".xhtml": "application/xhtml+xml",
    ".css": "text/css", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp", ".avif": "image/avif",
    ".bmp": "image/bmp", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".oga": "audio/ogg", ".ogg": "audio/ogg",
    ".wav": "audio/wav", ".vtt": "text/vtt", ".txt": "text/plain; charset=utf-8",
}
# The browser's arguments: no name resolves, so nothing is reached by
# name whatever else lets a request through, and no proxy, which
# Chromium otherwise takes from the environment.
ARGUMENTS = ["--host-resolver-rules=MAP * ~NOTFOUND", "--no-proxy-server"]
# What of the environment Chromium is given.
ENVIRONMENT = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
               "FONTCONFIG_FILE", "FONTCONFIG_PATH", "XDG_CACHE_HOME", "XDG_CONFIG_HOME")
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy")
# Collects what the page's Content Security Policy blocked, which the
# route never sees, since the browser doesn't make the request: a
# stylesheet or a font from elsewhere, which may change the page's colors
# and sizes, and the page's own scripts. Playwright runs it in every
# document before anything of the page's, as it does what it evaluates.
VIOLATIONS = """(() => {
  const seen = [];
  Object.defineProperty(window, '__oerBlocked', {value: seen});
  document.addEventListener('securitypolicyviolation', event => {
    if (seen.length < 200) {
      seen.push([event.effectiveDirective, String(event.blockedURI).slice(0, 300)]);
    }
  }, true);
})();"""

CLONE_NEWUSER, CLONE_NEWNET = 0x10000000, 0x40000000
# How long a context has to close, in seconds, past which it's left for
# the browser's closing to take.
CLOSING = 10


class Refused(Exception):
    """A layer the policy "service" requires that couldn't be had."""


class Slow(Exception):
    """A step that didn't finish in the time it was given: what it was."""


async def within(awaitable, seconds, what):
    """awaitable's result; or when it hasn't finished after seconds, it's
    canceled, and Slow(what) raised."""
    import asyncio
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError:
        raise Slow(what) from None


# --------------------------------------------------------------------------
# off the network
# --------------------------------------------------------------------------

def leave_network():
    """Take this process, and whatever it starts, off the network: a new
    user namespace that maps this user to itself, with a new network
    namespace in it. Returns "" or why it couldn't. Comes before any
    thread is started, since unshare refuses a new user namespace to a
    process with threads, and before Playwright, whose driver and
    Chromium are then started inside."""
    if not sys.platform.startswith("linux"):
        return "only Linux has the namespaces it takes"
    uid, gid = os.geteuid(), os.getegid()
    try:
        unshare = ctypes.CDLL(None, use_errno=True).unshare
    except (OSError, AttributeError) as exc:
        return f"unshare isn't available ({exc})"
    if unshare(CLONE_NEWUSER | CLONE_NEWNET) != 0:
        return f"unshare: {os.strerror(ctypes.get_errno())}"
    # Without the maps the process is still off the network, and its files
    # still its own; Chromium's sandbox, which needs them, says so itself.
    try:
        for name, text in (("setgroups", "deny"), ("uid_map", f"{uid} {uid} 1"),
                           ("gid_map", f"{gid} {gid} 1")):
            with open(f"/proc/self/{name}", "w") as fh:
                fh.write(text)
    except OSError:
        pass
    up = [name for name in interfaces() if name != "lo"]
    if up:
        return "the new namespace has interfaces besides the loopback: " + ", ".join(up)
    return ""


def interfaces():
    """The names of this process's network interfaces, from /proc."""
    try:
        with open("/proc/self/net/dev", encoding="utf-8") as fh:
            lines = fh.read().splitlines()[2:]
    except OSError:
        return []
    return [line.split(":", 1)[0].strip() for line in lines if ":" in line]


def clean_environment():
    """This process's environment without its proxies, which Playwright's
    driver passes on, and Chromium's own, the little it needs."""
    for name in list(os.environ):
        if name.lower() in PROXIES:
            del os.environ[name]
    return {name: os.environ[name] for name in ENVIRONMENT if name in os.environ}


# --------------------------------------------------------------------------
# Chromium
# --------------------------------------------------------------------------

async def launch(play, policy="local"):
    """(browser, why) for Playwright's Chromium, started in its own
    sandbox, and why its sandbox isn't on, "" when it is. As root it
    can't be, which Chromium says with its own error, so it isn't tried;
    elsewhere it's tried first. Under the policy "service", no sandbox
    raises Refused."""
    environment = clean_environment()
    why = ""
    if os.geteuid() == 0:
        why = "it can't start for root, and the run is root's"
    else:
        try:
            return await play.chromium.launch(chromium_sandbox=True, args=ARGUMENTS,
                                              env=environment, timeout=60000), ""
        except Exception as exc:        # Playwright's Error: the launch's reason
            why = launch_reason(exc)
    if policy == "service":
        raise Refused(f"Chromium's sandbox didn't start: {why}")
    return await play.chromium.launch(chromium_sandbox=False, args=ARGUMENTS,
                                      env=environment, timeout=60000), why


def launch_reason(exc):
    """What Chromium said kept it from starting: the line of its log that
    names the sandbox, else the log's first, else the error's own."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    for line in lines:
        if "sandbox" in line.lower() and not line.lower().startswith("to avoid"):
            return line[:200]
    if "Browser logs:" in lines:
        after = lines[lines.index("Browser logs:") + 1:]
        if after:
            return after[0][:200]
    return lines[0][:200] if lines else type(exc).__name__


def sandbox_state():
    """(on, why) for the Chromium this process started, read from /proc:
    on when every renderer has seccomp filtering on (Seccomp: 2) and is
    in a user namespace other than this process's, as Chromium's
    sandbox puts it; None when no renderer could be read."""
    renderers = [pid for pid in descendants(os.getpid()) if process_type(pid) == "renderer"]
    try:
        own = os.readlink("/proc/self/ns/user")
    except OSError:
        return None, "/proc can't be read here"
    seen = 0
    for pid in renderers:
        try:
            with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
                status = dict(line.split(":", 1) for line in fh.read().splitlines()
                              if ":" in line)
            space = os.readlink(f"/proc/{pid}/ns/user")
        except OSError:
            continue                    # gone, or not ours to read
        seen += 1
        if status.get("Seccomp", "").strip() != "2":
            return False, "a renderer has no seccomp filter"
        if space == own:
            return False, "a renderer shares the worker's user namespace"
    if not seen:
        return None, "no renderer of Chromium's could be read in /proc"
    return True, ""


def descendants(root):
    """The processes started from root, at any depth."""
    children = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return []
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", encoding="utf-8", errors="replace") as fh:
                parent = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(parent, []).append(int(name))
    out, todo = [], [root]
    while todo:
        for child in children.get(todo.pop(), []):
            out.append(child)
            todo.append(child)
    return out


def process_type(pid):
    """A Chromium process's --type (renderer, zygote, utility), "" for
    the browser's own or any other process. Chromium rewrites some of its
    processes' command lines as one string, its arguments in it."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = fh.read().decode("utf-8", "replace").split("\0")
    except OSError:
        return ""
    if len([a for a in argv if a]) == 1:
        argv = argv[0].split()
    for arg in argv:
        if arg.startswith("--type="):
            return arg[len("--type="):]
    return ""


# --------------------------------------------------------------------------
# what a page is served from
# --------------------------------------------------------------------------

class Folder:
    """Files under a folder, by their path below it, and nothing outside
    it: not through .., nor through a link that leads out."""

    def __init__(self, root):
        self.root = os.path.realpath(root)

    def read(self, path):
        try:
            full = os.path.realpath(os.path.join(self.root, *path.split("/")))
            if not full.startswith(self.root + os.sep) or not os.path.isfile(full):
                return None
            if os.path.getsize(full) > LIMIT:
                return TOO_LARGE
            with open(full, "rb") as fh:
                return fh.read(LIMIT + 1)
        except (OSError, ValueError):       # unreadable, or a name with a NUL in it
            return None


class Archive:
    """An EPUB's entries, or any ZIP's, by name, read to LIMIT at most
    whatever an entry says of its size."""

    def __init__(self, path):
        self.zip = zipfile.ZipFile(path)
        self.names = set(self.zip.namelist())

    def read(self, path):
        if path not in self.names:
            return None
        try:
            with self.zip.open(path) as fh:
                data = fh.read(LIMIT + 1)
        except Exception:                   # a damaged entry; the EPUB's checks name it
            return None
        return TOO_LARGE if len(data) > LIMIT else data

    def close(self):
        self.zip.close()


class Memory:
    """Files given as {path: bytes}: the probes'."""

    def __init__(self, files):
        self.files = dict(files)

    def read(self, path):
        return self.files.get(path)


TOO_LARGE = object()


def url_of(path):
    """A page's address at ORIGIN, from its path in its source."""
    return ORIGIN + "/" + quote(path, safe="/")


def path_of(url):
    """The path in its source a URL at ORIGIN names, or None for one
    elsewhere, or one that climbs out (..)."""
    parts = urlsplit(url)
    if f"{parts.scheme}://{parts.netloc}" != ORIGIN:
        return None
    path = posixpath.normpath(unquote(parts.path))
    if not path.startswith("/") or path == "/" or "/../" in path + "/":
        return None
    return path[1:]


# --------------------------------------------------------------------------
# a page's visit
# --------------------------------------------------------------------------

class Visit:
    """One page's visit: the route that answers its every request, and
    what the route saw. served, {path: SHA-256} of what was served;
    refused, (kind, address, why) for each request refused; canceled,
    the page's own navigations, answered with a 204; documents, the
    addresses served as pages or frames. scripts: for a presentation,
    the SHA-256s of the script files it may load, each refused that
    isn't one; otherwise the policy blocks them all before they're
    asked for."""

    def __init__(self, source, path, scripts=NO_SCRIPTS, allowed=()):
        self.source, self.path, self.url = source, path, url_of(path)
        self.header = POLICY.format(scripts=scripts)
        self.allowed = set(allowed)
        self.served, self.refused, self.canceled = {}, [], []
        self.documents, self.loaded = set(), False

    def refuse(self, kind, url, why):
        if len(self.refused) < 500:
            self.refused.append((kind, url[:300], why))

    async def handle(self, route):
        try:
            await self.answer(route)
        except Exception as exc:            # anything unforeseen is a refusal
            self.refuse("?", route.request.url, f"not answered ({type(exc).__name__})")
            try:
                await route.abort("blockedbyclient")
            except Exception:
                pass

    async def answer(self, route):
        request = route.request
        url = request.url.split("#", 1)[0]
        kind = request.resource_type
        try:
            main = request.is_navigation_request() and request.frame.parent_frame is None
        except Exception:               # no frame (a service worker's, which are blocked)
            main = False
        if main:
            if self.loaded or path_of(url) != self.path:
                self.canceled.append(url[:300])
                await route.fulfill(status=204, body=b"")
                return
            self.loaded = True
        path = path_of(url)
        data = self.source.read(path) if path is not None else None
        if data is None or data is TOO_LARGE:
            self.refuse(kind, url, "elsewhere" if path is None else
                        "too large" if data is TOO_LARGE else "not there")
            await route.abort("blockedbyclient")
            return
        digest = hashlib.sha256(data).hexdigest()
        if kind == "script" and digest not in self.allowed:
            self.refuse(kind, url, "not TextbookImprover's")
            await route.abort("blockedbyclient")
            return
        self.served[path] = digest
        if kind == "document":
            self.documents.add(url)
        extension = posixpath.splitext(path)[1].lower()
        await route.fulfill(status=200, body=data, headers={
            "Content-Type": CONTENT_TYPES.get(extension, "application/octet-stream"),
            "Content-Security-Policy": self.header,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store"})

    async def socket(self, socket):
        """A WebSocket, which the route doesn't see: taken, and never
        connected to anything."""
        self.refuse("websocket", socket.url, "elsewhere")


async def open_page(browser, source, path, *, scripts=NO_SCRIPTS, allowed=(),
                    viewport=(1280, 900), load=30):
    """(context, page, visit) for the page at path in source, in a context
    of its own, each step of opening it (the context, the page, its load
    event, and its fonts) within load seconds: one that isn't raises Slow,
    or Playwright's own error for the load event. Motion is reduced, so a
    transition isn't caught partway. The caller closes the context."""
    width, height = viewport
    opening = f"Chromium hadn't opened a page for it after {load} seconds"
    context = await within(browser.new_context(
        viewport={"width": width, "height": height}, service_workers="block",
        accept_downloads=False, permissions=[], color_scheme="light",
        reduced_motion="reduce"), load, opening)
    visit = Visit(source, path, scripts, allowed)

    async def prepared():
        await context.add_init_script(VIOLATIONS)
        await context.route("**/*", visit.handle)
        await context.route_web_socket("**/*", visit.socket)
        return await context.new_page()
    try:
        page = await within(prepared(), load, opening)
        await page.goto(visit.url, wait_until="load", timeout=load * 1000)
        await within(page.evaluate("document.fonts.ready.then(() => true)"), load,
                     f"its fonts hadn't loaded after {load} seconds")
    except BaseException:
        await close_quietly(context)
        raise
    return context, page, visit


async def blank_page(browser, load=30):
    """(context, page) for a page with nothing in it, which never loads
    anything, for axe-core's finishRun: every request it might make is
    refused. Each step of opening it is within load seconds, as
    open_page's are."""
    opening = f"Chromium hadn't opened a blank page after {load} seconds"
    context = await within(browser.new_context(service_workers="block",
                                               accept_downloads=False, permissions=[]),
                           load, opening)

    async def prepared():
        await context.route("**/*", lambda route: route.abort("blockedbyclient"))
        await context.route_web_socket("**/*", lambda socket: None)
        return await context.new_page()
    try:
        return context, await within(prepared(), load, opening)
    except BaseException:
        await close_quietly(context)
        raise


async def blocked(frame):
    """What the policy blocked in a frame's document: [(directive,
    address)], as VIOLATIONS collected them."""
    try:
        return await frame.evaluate("() => (window.__oerBlocked || []).slice()")
    except Exception:
        return []


async def close_quietly(context, seconds=CLOSING):
    """Close a context, or a browser, when it closes within seconds; one
    that doesn't is left, a context for its browser's closing."""
    import asyncio
    try:
        await asyncio.wait_for(context.close(), timeout=seconds)
    except Exception:
        pass
