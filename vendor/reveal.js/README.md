# reveal.js 6.0.2

What a `revealjs` target's presentations load, copied beside each one (`REVEALJS_FILES` in `lib/revealtarget.py`). It's here, not downloaded, so that the target needs nothing installed, and so that the presentations load the release `bin/oer-reveal.js` was written against and the decks suite tests in a browser. That script depends on reveal.js's internals: the live region's class, the progress bar and the controls, the `disableLayout` and `keyboardCondition` settings, and how reveal.js lays a slide out. A later release could change any of them. `REVEALJS_DIR`, naming the folder of another copy of reveal.js 6, takes this one's place, and the run notes a version other than this one.

## What's here

These files from reveal.js 6.0.2's package on the npm registry, byte for byte, at the paths the package gives them:

- `dist/reveal.js`, `dist/reveal.css`, and `dist/reset.css`, reveal.js itself;
- `dist/theme/white.css`, the white theme, which embeds Adobe's Source Sans Pro;
- `dist/plugin/notes.js`, `search.js`, and `zoom.js`, the plugins Pandoc's template loads;
- `package.json`, which names the version;
- `LICENSE`, reveal.js's license, and `css/theme/fonts/source-sans-pro/LICENSE`, the font's.

The package is `https://registry.npmjs.org/reveal.js/-/reveal.js-6.0.2.tgz`, published 2026-09-10, whose `integrity` on the registry is `sha512-JYIg5D9aoxoaLeb84O+OvAwsKWdIavVgEDScxtYEXFCT6t6TQrhNtSgogcjdCpdLsWglhJn3zyE3fUOwiH5KEg==`. The rest of it, reveal.js's sources, demos, and other themes, isn't needed.

## Licenses

reveal.js is MIT-licensed, by Hakim El Hattab and its contributors, which allows copying it with its license: `LICENSE` goes with it, here and beside every presentation. Source Sans Pro is under the SIL Open Font License 1.1, whose full text is inside each font the theme embeds (the font's license field) and in the font's `LICENSE`, which goes beside every presentation too. Both allow this redistribution with the notices kept; MIT is compatible with this project's GPL. Keep the files unmodified: a changed file isn't the release named here, and the package's hash no longer vouches for it.

## Updating

When preparing a release of TextbookImprover, see whether reveal.js has a newer one (`curl -s https://registry.npmjs.org/reveal.js/latest`, its `version`). For a new one:

1. Download its package from the registry, as `docs/installation.md` does, and check its SHA-512 against the `integrity` the registry gives for it.
2. Replace these files with the package's, and update the version, address, and hash above.
3. Read what changed against what `bin/oer-reveal.js` relies on, which its comments name.
4. Run every suite, with Playwright and its Chromium installed so that the decks suite's checks in a browser run too.

A new major version needs a Pandoc whose template loads it, as reveal.js 6's plugin paths came with Pandoc 3.12, and `REVEALJS_MAJOR` changed to match.
