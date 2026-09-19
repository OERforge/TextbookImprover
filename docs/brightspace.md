# How Brightspace treats an imported cartridge

Worth knowing before you import anything twice, because the behavior is
not what most people assume and one option is destructive.

Everything below was measured in Brightspace, and where noted confirmed
by D2L. Another LMS may do the same things — nothing here depends on a
Brightspace-only feature — but none of it has been tested anywhere else,
so treat it as a reason for care rather than as a description of your
own LMS.

**Structure is never merged; it's appended.** Importing a cartridge a
second time doesn't update the modules already in the course. It adds
another copy of the whole tree. That is why the pages are wrapped in one
module by default: a re-import then leaves one module to remove rather
than one per chapter, and in Brightspace modules are deleted one at a
time.

**There's one file per path, shared by everything that points at it.**
Two modules showing the same page are two references to one file, not two
copies. Brightspace offers two ways to delete a module, and the difference
matters:

- **Remove from Content** detaches the module and leaves the files.
- **Permanently delete** removes the files themselves.

So after re-importing a book, removing the older module with *Permanently
delete* empties the newer one too — its structure stays and its pages go
blank, with nothing to indicate why. Use *Remove from Content* for cleanup
after a re-import. *Permanently delete* is right only when removing a book
from the course, and the content prefix is what stops it reaching another
book's files.

**Deleting a module doesn't reclaim its images.** Measured in
Brightspace: *Permanently delete* removes the file a topic **is** and
never the files a topic **uses**. Images and other referenced files are
retained wherever they sit, directories with them, and nothing afterwards
removes either.

This isn't specific to importing. The same happens to a file inserted
through Brightspace's own HTML editor, so it's general behavior rather
than a gap in Common Cartridge handling — imports just reach it faster,
bringing hundreds of files at a time. It also means *Permanently delete*
doesn't remove everything its dialog says it does.

**D2L has confirmed all of this as intended behavior.** Reported to the
D2L Helpdesk with a test package, and reviewed by their Product Support
team, who answered that the option worded *Permanently delete both the
topic from Content and the associated file or activity from the course*
means the file the topic **is**, and that images, CSS, and other
resources referenced inside that file aren't considered associated files
of the topic because the topic doesn't track what its file pulls in.
They also confirmed the sharper case: where two topics point at the same
file, deleting either one with that option deletes the file, the other
topic is left with a broken link, Brightspace gives no warning, and it
doesn't keep the file on account of the other reference. The wording and
the missing warning were passed to their product team for consideration,
with no ticket and no commitment, so plan on the behavior staying as it
is.

That last part is worth reading twice, because a course can be broken by
one careless deletion: two modules showing the same page share one file,
and *Permanently delete* on either takes it. Prefer *Remove from Content*
whenever a page might be shared, and treat *Permanently delete* as
something to use only when a whole book is going.

Nothing in a cartridge can make an LMS delete files it doesn't consider
owned, so this is something to know rather than something to fix. It's
also a second argument for the content prefix: the leftovers sit in one
named directory you can find and clear in Manage Files, rather than
scattered among everything else at the course root. Expect to do that by
hand after removing a book, and expect the one-time migration to leave the
old, unprefixed images behind when the old module goes.

**An href is taken literally.** A cartridge's manifest names its files
by `href`, and IMS Content Packaging says an `href` is a URI, so a file
called `01 BigPicture.html` is referred to as `01%20BigPicture.html`. A
manifest written that way validates, and Brightspace imports its
structure and then reports every such page as missing when a student
opens it: it looks for a file literally named `01%20BigPicture.html`,
and the archive holds `01 BigPicture.html`. Pages whose names needed no
encoding open normally, which is what makes the failure look partial
and random. Measured with a cartridge where 320 of 361 hrefs carried a
`%20`; the 41 without one worked.

The pipeline no longer produces such a manifest: a page is named after
its source with spaces and other URI-special characters replaced
(`01 BigPicture.md` is the page `01-BigPicture`), and media a page
refers to is copied under such a name with the reference rewritten to
match, so nothing in the archive needs encoding. If you build a
cartridge by hand or from pages the pipeline did not name, keep every
file name to letters, digits, `.`, `_`, and `-`. There is no way to
make Brightspace decode an href, and it is not obvious that it should
have to; a report has been drafted for D2L.

### The content prefix

Every file in a package goes inside one directory named after the book,
unless you turn `paths.prefix_content` off. Without it, two books that
each contain `frontmatter.html` contain the same file as far as the LMS is
concerned: the second import overwrites the first, and permanently
deleting either empties the other.

The directory name is a readable portion of the title plus a short digest
of the identifier — the title so the folder means something in a file
manager, the digest because two books can share a title and the identifier
is the thing that must be unique. The version is deliberately not part of
it, so an update overwrites the same paths and pages refresh in place.

Nothing on disk moves. The prefix exists only inside the package.

### Moving an existing course to prefixed paths

Turning this on relocates every file, so an instructor with an earlier
import gets a second copy rather than an update. One time only, and the
order matters:

1. **Import the new cartridge.** Both copies now coexist.
2. **Check the new module renders.**
3. **Then permanently delete the old module.** Safe because the paths no
   longer overlap — and here *Permanently delete* is the right choice,
   since nothing else refers to those files and *Remove from Content*
   would leave them behind for good.

Deleting first would work too, but leaves a window with no content and
nothing to fall back on if the import fails.

After this, updates behave as before: same identifier, same prefix, same
paths, pages update in place, and the stale module goes with *Remove from
Content*. The instruction changes once and then changes back, which is
worth telling people or the careful ones will keep permanently deleting
and empty their own courses.
