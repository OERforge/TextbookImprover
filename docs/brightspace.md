# How Brightspace treats an imported cartridge

Worth knowing before you import anything twice, because the behavior is
not what most people assume and one option is destructive.

Everything below was measured in Brightspace, and where noted confirmed
by D2L. Another LMS may do the same things — nothing here depends on a
Brightspace-only feature — but none of it has been tested anywhere else,
so treat it as a reason for care rather than as a description of your
own LMS.

**Structure is never merged; it is appended.** Importing a cartridge a
second time does not update the modules already in the course. It adds
another copy of the whole tree. That is why the pages are wrapped in one
module by default: a re-import then leaves one module to remove rather
than one per chapter, and in Brightspace modules are deleted one at a
time.

**There is one file per path, shared by everything that points at it.**
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

**Deleting a module does not reclaim its images.** Measured in
Brightspace: *Permanently delete* removes the file a topic **is** and
never the files a topic **uses**. Images and other referenced files are
retained wherever they sit, directories with them, and nothing afterwards
removes either.

This is not specific to importing. The same happens to a file inserted
through Brightspace's own HTML editor, so it is general behavior rather
than a gap in Common Cartridge handling — imports just reach it faster,
bringing hundreds of files at a time. It also means *Permanently delete*
does not remove everything its dialog says it does.

**D2L has confirmed all of this as intended behavior.** Reported to the
D2L Helpdesk with a test package, and reviewed by their Product Support
team, who answered that the option worded *Permanently delete both the
topic from Content and the associated file or activity from the course*
means the file the topic **is**, and that images, CSS, and other
resources referenced inside that file are not considered associated files
of the topic because the topic does not track what its file pulls in.
They also confirmed the sharper case: where two topics point at the same
file, deleting either one with that option deletes the file, the other
topic is left with a broken link, Brightspace gives no warning, and it
does not keep the file on account of the other reference. The wording and
the missing warning were passed to their product team for consideration,
with no ticket and no commitment, so plan on the behavior staying as it
is.

That last part is worth reading twice, because a course can be broken by
one careless deletion: two modules showing the same page share one file,
and *Permanently delete* on either takes it. Prefer *Remove from Content*
whenever a page might be shared, and treat *Permanently delete* as
something to use only when a whole book is going.

Nothing in a cartridge can make an LMS delete files it does not consider
owned, so this is something to know rather than something to fix. It is
also a second argument for the content prefix: the leftovers sit in one
named directory you can find and clear in Manage Files, rather than
scattered among everything else at the course root. Expect to do that by
hand after removing a book, and expect the one-time migration to leave the
old, unprefixed images behind when the old module goes.

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
