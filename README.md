# atlas-skills-sandbox

A cut-down copy of [atlas-skills](https://github.com/Cellular-Semantics/atlas-skills)
for trying out its release process before adopting it there. It holds two
plugins that run the same package at **different versions**, that package, and
a bundle — enough to exercise every versioning rule, and small enough that a
mistake costs nothing.

**Not for analysis work.** Use atlas-skills for that. The skill text is copied
from the parent with only the pinned commands changed, so it still links to
atlas-skills' benchmark and mentions `cap-tools`; those refer to the parent.

```
.claude-plugin/marketplace.json    the marketplace (one file, in this repo)
plugins/remote-h5ad-obs/           read obs from a remote h5ad   -> h5ad-obs 0.3.0
plugins/author-annotation-columns/ the skill + two picker agents -> h5ad-obs 0.3.1
plugins/atlas-tools/               bundle: installs author-annotation-columns
packages/h5ad-obs/                 the CLI the skill calls through uvx
scripts/versions.py                bump check, release planning, pin report
docs/pins.md                       plugin -> package pins on main (generated)
docs/test-plan.md                  what to try, and what each step proves
```

Same structure and rules as the parent: a skill calls code through a CLI and
never contains non-trivial code; deterministic, testable logic goes in a
package with tests.

## Two kinds of version, and how they connect

| | Plugin | Package |
|---|---|---|
| Version lives in | `plugins/<p>/.claude-plugin/plugin.json` | `packages/<d>/pyproject.toml` |
| Tag | `<plugin>--v<version>` | `pkg-<dir>--v<version>` |
| Who reads the tag | a ref-pinned marketplace | the `uvx --from …@<tag>` line in a skill |

A plugin tag freezes its SKILL.md, and the SKILL.md holds the package pin. So
**a plugin release determines its package release** — read the skill at the
plugin tag and you know exactly which package it runs. `docs/pins.md` shows
the mapping for main; the nightly run's summary shows it for every supported
tag.

### Two plugins, two package versions, one session

`remote-h5ad-obs` pins h5ad-obs 0.3.0 and `author-annotation-columns` pins
0.3.1, and both can be enabled in one project and used in one session. Each
skill's command names its exact package tag; `uvx` builds one cached
environment per exact spec and runs the CLI from it, so the two versions never
share an install and nothing lands on `PATH`. This holds as long as:

- **every call in a skill is the full pinned command** — a bare `h5ad-obs …`
  runs whatever is on `PATH`, or nothing;
- **the pin names the extras the call needs** —
  `"h5ad-obs[parquet] @ git+…@<tag>#subdirectory=…"`, since parquet output needs
  pyarrow and the bare package does not bring it;
- **files passed between skills keep their format** across the versions in use;
  changing what the CLI writes is a contract change like any other;
- **nobody `uv tool install`s these CLIs** — that puts a single version on `PATH`
  for the whole machine.

## Installing

### Track the latest release

```json
{
  "extraKnownMarketplaces": {
    "atlas-skills-sandbox": {
      "source": { "source": "github", "repo": "Cellular-Semantics/atlas-skills-sandbox" }
    }
  },
  "enabledPlugins": { "author-annotation-columns@atlas-skills-sandbox": true }
}
```

Commit that as `.claude/settings.json` in a project. It enables the plugin but
does not download it: each person runs, once per project,

```sh
claude plugin install author-annotation-columns@atlas-skills-sandbox --scope project
```

It follows main, and an installed copy refreshes when the plugin's version
string changes and someone runs `claude plugin update` (auto-update is off by
default for marketplaces outside Anthropic's own).

### Pin a release

Add a `ref` naming a plugin tag:

```json
"source": {
  "source": "github",
  "repo": "Cellular-Semantics/atlas-skills-sandbox",
  "ref": "author-annotation-columns--v0.4.0"
}
```

Claude Code reads the marketplace from that tag, and the plugin's relative
path from the same checkout, so the project gets that release exactly —
including the package pin in its skill. Each GitHub Release's notes carry
this snippet with its own tag filled in.

Two things to know about pinning:

- The tag snapshots the whole repo. A project pinned to a plugin tag gets every
  other plugin as it stood at that commit; enable only the one you pinned.
- **One registration per marketplace name per machine.** Claude Code keeps a
  single entry for `atlas-skills-sandbox` in `~/.claude/plugins/known_marketplaces.json`,
  not one per project; a project's `ref` rewrites that shared entry. Tested
  (test plan, step 6): a pinned project registered the tag, then an unpinned
  project on the same machine installed the *pinned* version and overwrote the
  registration. So a ref pin is reliable only where a machine needs one version
  of the plugin. Two versions of the *same plugin* for one person needs a second
  marketplace name (a "stable" channel). Two *different* plugins on different
  package versions — the case above — needs nothing extra.

### Bundles take no version range

A bundle's dependency can carry a range (`{"name": …, "version": "~0.4.0"}`),
and the Claude Code docs say it installs the highest tag in that range. Tested
on Claude Code 2.1.291 (test plan, step 8), it did not: with
`author-annotation-columns` at 0.5.0 on main and `--v0.4.2` tagged, a fresh
install of the bundle took main's 0.5.0, then refused to load the bundle —
`Requires … ~0.4.0, installed 0.5.0`. The range only checks; it never holds a
plugin back. So `atlas-tools` lists its plugin unversioned, and a range would
break it at every minor release. Holding a plugin at a tested version needs a
separate marketplace name, not a range.

### Supported releases

The newest **3** tags of each plugin are supported: the nightly workflow
re-installs every package they pin and runs that package's tests at its tag.
Older tags still install, but nothing checks that they still work.

## Releasing

Releases are cut by CI from main, never by hand.

1. **Change a package**: edit, bump `pyproject.toml`'s version.
   `version-bumps` fails if the code changed and the version did not.
2. **Adopt it in a plugin** — same PR or a later one: move the skill's pin to
   the new package tag, bump `plugin.json`, regenerate `docs/pins.md`.
3. Merge. Once `test` is green on main, `release` tags `pkg-<dir>--v<new>`,
   checks it installs from a cold cache, then runs `claude plugin tag` —
   which validates the plugin and checks it against the marketplace entry —
   and writes a GitHub Release listing the plugin's package pins.

A pin to a package tag that does not exist yet would normally fail
`skill-pins-resolve`. The exception is the tag this very commit's release will
cut (the package's current version, untagged): that is checked at the commit
instead, since the tag can only appear after merge. Without the exception, the
first release of any package deadlocks — `test` waits for a tag that only
`release` makes, and `release` waits for `test`. Any other missing tag still
fails.

For the few minutes between merge and `release` finishing, main pins a tag that
does not exist yet. A project tracking main that installs in that window gets
a failed `uvx` call until the tag lands. (The parent repo avoids the window by
pushing the package tag from a branch before merging; that puts an unreviewed
commit behind a tag users install.)

A plugin-only change — skill wording, an agent prompt — is step 2 alone.

## Rules for changes

- Deterministic and testable → a package, with tests. About when/how/why → skill text.
- CLI output for agents is JSON-shaped with stable field names, and every CLI
  supports `--version`. The CLI is named after its package directory.
- **Any change under `plugins/<p>/` bumps that plugin's version.** Installed
  copies refresh only when the version string changes; an unbumped edit
  never reaches anyone who already has the plugin. CI enforces this.
- **Any change to a package's code or `pyproject.toml` bumps its version.**
  Tests and README do not. CI enforces this.
- A released version never changes. CI refuses a bump to a version that is
  already tagged.
- Changing a CLI contract is a breaking change: bump the package's major
  version (minor while 0.x) and move each pinning skill deliberately.
- Pin skills to package tags, never to a branch or commit. Every call in a
  skill is the full pinned `uvx --from` command, with the extras it needs.
- One skill per plugin, unless two genuinely cannot be used apart.

## CI

| Workflow | When | What |
|---|---|---|
| `test` | every PR and push | lint; `claude plugin validate`; package and tooling tests on 3.11–3.13; `docs/pins.md` current; every package installs from git at the PR head; every pin on the branch resolves; on PRs, `version-bumps` |
| `release` | after `test` passes on main | tag every untagged package, then plugin; GitHub Release each |
| `nightly` | 03:17 UTC daily | every pin on main and at the supported tags installs; each pinned package tag's tests pass on a fresh install |

Why nightly: `h5ad-obs` declares dependency ranges, and `uvx --from git+…`
resolves them fresh — it ignores `uv.lock` (checked with uv 0.6.13: a lock
pinning `six==1.15.0` installed 1.17.0). A tag that worked when it was cut can
break later without any commit.

## Development

```sh
./dev.sh              # package tests, tooling tests, pins report, validation
python3 scripts/versions.py check-bumps --base origin/main   # before pushing
python3 scripts/versions.py report > docs/pins.md            # after moving a pin
```
