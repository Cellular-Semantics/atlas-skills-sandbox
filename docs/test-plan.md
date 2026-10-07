# Test plan

What to try, in order, and what each step proves. **Step 11 answers the main
question** — two plugins on two package versions in one session. Steps 1–4
exercise CI; 5–8 exercise installs and need scratch project directories, called
`proj-latest` and `proj-pinned` below. Record what happened in the last
column, so the result can carry back to atlas-skills.

| # | Do | Expect | Proves | Result |
|---|---|---|---|---|
| 1 | Push the initial commit to main | `test` green; then `release` creates `pkg-h5ad-obs--v0.3.0`, `atlas-tools--v0.1.0`, `author-annotation-columns--v0.4.0`, each with a GitHub Release | release automation (A3), `claude plugin tag` in CI, packages tagged before the plugin pinning them | Passed 2026-10-07 after PR #1 broke a first-release deadlock (test waited for a tag only release makes). Three tags, three Releases. |
| 2 | PR: edit a word in SKILL.md, no version bump | `version-bumps` fails, naming `plugin.json` | the bump check (A2) | Passed (PR #2): version-bumps failed alone. It also printed a redundant "tag already exists" line; fixed in PR #3. |
| 3 | PR **1 of the D2 change**: on branch `d2-pin-deps`, exact-pin h5ad-obs's direct dependencies, version 0.3.1. Merge | `release` tags only `pkg-h5ad-obs--v0.3.1`; plugin untouched | package releases independently of the plugin | Passed (PR #3): only `pkg-h5ad-obs--v0.3.1`. Used `~=` patch ranges rather than exact pins (security fixes must reach old tags). |
| 4 | PR 2: move the skill's pin to `pkg-h5ad-obs--v0.3.1`, plugin to 0.4.1, regenerate `docs/pins.md`. Merge | `skill-pins-resolve` green; `release` tags `author-annotation-columns--v0.4.1`; its Release notes list the new pin | two plugin releases on two package releases | Passed (PR #4): `author-annotation-columns--v0.4.1`, notes list `pkg-h5ad-obs--v0.3.1`. |
| 5 | `proj-pinned`: settings with `"ref": "author-annotation-columns--v0.4.0"`. `proj-latest`: no ref. Open each, run `/plugin` and `claude plugin list` | pinned shows 0.4.0, latest shows 0.4.1; the skill in each shows its own `pkg-h5ad-obs` pin | tag-pinned install (B4) | Pinned project: 0.4.0 → h5ad-obs 0.3.0, passed. Latest project got 0.4.0 too — see step 6. Install needed `claude plugin install … --scope project`; settings alone do not download. |
| 6 | Same machine, both projects open one after the other, then both at once | each keeps its own version — **or** a conflict on the shared marketplace name. If it conflicts, the fix is a second marketplace name (a stable channel) | the open question from planning | **Conflicts.** One registration per marketplace name per machine; the unpinned project installed the pinned version, then overwrote the registration. Ref pins work only where a machine needs one version of a plugin. |
| 7 | In each project, ask the skill to read an h5ad; then `ls ~/.cache/uv/` (or `uv cache dir`) | two separate h5ad-obs environments, no conflict | uvx per-pin isolation | |
| 8 | Install `atlas-tools@atlas-skills-sandbox` in a third project after step 4 | `claude plugin list` shows author-annotation-columns at a `0.4.1-<sha>` version — the highest tag in `~0.4.0` | bundle version ranges resolve against plugin tags (A4) | |
| 9 | Actions → nightly → Run workflow | summary shows the table with 0.4.0 and 0.4.1; both package tags' tests pass | nightly window (C2–C4) | |
| 10 | PR: bump the plugin to 0.4.0 again (an already-tagged version) | `version-bumps` fails: tag already exists | released versions are immutable | |
| 11 | One project, `.claude/settings.json` enabling **both** `remote-h5ad-obs` and `author-annotation-columns` from the unpinned marketplace; install both. In one session, have each skill run its own command with `--version`, then use both on one real h5ad (read obs with one, find author columns with the other) | `h5ad-obs 0.3.0` from one, `0.3.1` from the other, in the same session; both finish; no `ModuleNotFoundError: pyarrow` | **the main concern**: two plugins, two versions of one package, one session | |
