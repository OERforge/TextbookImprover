# axe-core 4.14.0

What `--wcag` runs on HTML pages, presentations, and an EPUB's content documents (`lib/axecheck.py`): [axe-core](https://github.com/dequelabs/axe-core), Deque's rules for what WCAG's criteria a machine can test, run in Playwright's Chromium. It's here, not downloaded, so that `--wcag` needs nothing beyond Playwright, and so that every run uses the release the suites test. `AXE_CORE_DIR`, naming the folder of another copy's `axe.min.js`, takes this one's place in a local run, and the summary names the version.

## What's here

These files from axe-core 4.14.0's package on the npm registry, byte for byte:

- `axe.min.js`, axe-core itself, 652,140 bytes;
- `package.json`, which names the version;
- `LICENSE`, axe-core's license, and `LICENSE-3RD-PARTY.txt`, the licenses of what it bundles.

The package is `https://registry.npmjs.org/axe-core/-/axe-core-4.14.0.tgz`, published 2026-10-05, whose `integrity` on the registry is `sha512-9WTZxEjsZ7b13TH8JPmbV2z8CHbl80/2hm3XPEG4JgNdQLK81IBRXmSxHfMAOkSqQeRxT/0dwNDz2GOm3zzpcQ==`. `axe.min.js`'s SHA-256 is `20c09fe157a8a34a30e241aaa1fcdade657734f08ab379ecfbeb7d45cc46e878`, which axe-core publishes in the package's `sri-history.json` (`sha256-IMCf4Veoo0ow4kGqofza3mV3NPCKs3ns++t9RcxG6Hg=`) and `AXE_SHA256` in `lib/axecheck.py` checks on every run. The rest of the package, the unminified build, its types, and its translations, isn't needed.

## Licenses

axe-core is under the Mozilla Public License 2.0, by Deque Systems, whose copyright notice stays at the head of `axe.min.js`. The MPL covers the file, not the rest of this repository. As far as can be told from the license itself, it allows distributing the file with this project, which is under the GPL: the file carries no notice making it incompatible with the GPL (the MPL's Exhibit B), so its section 3.3 allows it in a larger work under the GPL. `axe.min.js` is minified, which the MPL's section 3.2 treats as an executable form, to be distributed with word of where its source is: axe-core's source code is at [github.com/dequelabs/axe-core](https://github.com/dequelabs/axe-core), tagged `v4.14.0`, and the package above holds it unminified as `axe.js`. What axe-core bundles is under the licenses `LICENSE-3RD-PARTY.txt` gives. Keep the files unmodified: a changed file isn't the release named here, and `--wcag` won't run it.

## Updating

When preparing a release of TextbookImprover, see whether axe-core has a newer one (`curl -s https://registry.npmjs.org/axe-core/latest`, its `version`). For a new one:

1. Download its package from the registry and check its SHA-512 against the `integrity` the registry gives for it.
2. Replace these files with the package's, and update the version, address, and hashes above and `AXE_VERSION` and `AXE_SHA256` in `lib/axecheck.py`.
3. Read its changelog for rules added, retired, or retagged: which rules run follows each rule's WCAG criteria (`lib/axecheck.py`), and the unit suite checks those against axe's own level tags.
4. Run every suite, with Playwright and its Chromium installed so that the checks in a browser run too.
