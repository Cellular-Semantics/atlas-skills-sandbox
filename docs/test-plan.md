# Test plan

What to try, in order, and what each step proves. Steps 1–4 exercise CI;
5–8 exercise installs and need two scratch project directories, called
`proj-latest` and `proj-pinned` below. Record what happened in the last
column, so the result can carry back to atlas-skills.

| # | Do | Expect | Proves | Result |
|---|---|---|---|---|
| 1 | Push the initial commit to main | `test` green; then `release` creates `pkg-h5ad-obs--v0.3.0`, `atlas-tools--v0.1.0`, `author-annotation-columns--v0.4.0`, each with a GitHub Release | release automation (A3), `claude plugin tag` in CI, packages tagged before the plugin pinning them | |
| 2 | PR: edit a word in SKILL.md, no version bump | `version-bumps` fails, naming `plugin.json` | the bump check (A2) | |
| 3 | PR **1 of the D2 change**: on branch `d2-pin-deps`, exact-pin h5ad-obs's direct dependencies, version 0.3.1. Merge | `release` tags only `pkg-h5ad-obs--v0.3.1`; plugin untouched | package releases independently of the plugin | |
| 4 | PR 2: move the skill's pin to `pkg-h5ad-obs--v0.3.1`, plugin to 0.4.1, regenerate `docs/pins.md`. Merge | `skill-pins-resolve` green; `release` tags `author-annotation-columns--v0.4.1`; its Release notes list the new pin | two plugin releases on two package releases | |
| 5 | `proj-pinned`: settings with `"ref": "author-annotation-columns--v0.4.0"`. `proj-latest`: no ref. Open each, run `/plugin` and `claude plugin list` | pinned shows 0.4.0, latest shows 0.4.1; the skill in each shows its own `pkg-h5ad-obs` pin | tag-pinned install (B4) | |
| 6 | Same machine, both projects open one after the other, then both at once | each keeps its own version — **or** a conflict on the shared marketplace name. If it conflicts, the fix is a second marketplace name (a stable channel) | the open question from planning | |
| 7 | In each project, ask the skill to read an h5ad; then `ls ~/.cache/uv/` (or `uv cache dir`) | two separate h5ad-obs environments, no conflict | uvx per-pin isolation | |
| 8 | Install `atlas-tools@atlas-skills-sandbox` in a third project after step 4 | `claude plugin list` shows author-annotation-columns at a `0.4.1-<sha>` version — the highest tag in `~0.4.0` | bundle version ranges resolve against plugin tags (A4) | |
| 9 | Actions → nightly → Run workflow | summary shows the table with 0.4.0 and 0.4.1; both package tags' tests pass | nightly window (C2–C4) | |
| 10 | PR: bump the plugin to 0.4.0 again (an already-tagged version) | `version-bumps` fails: tag already exists | released versions are immutable | |

## The D2 change, for step 3

uvx ignores `uv.lock`, so the only way to freeze what a tag installs is in
`pyproject.toml`. Pin direct dependencies exactly, except:

- **certifi**: keep a floor, not a pin. A frozen CA bundle goes stale, and a
  stale CA bundle is a security fault rather than a reproducibility win.
- **numpy**: one exact version must have wheels for every supported Python.
  On 2026-10-06 uv resolved 2.4.6 for 3.11 and 2.5.3 for 3.13; 2.4.6 covers
  both.

Transitive dependencies still float. The nightly run is what notices when one
breaks an old tag.
