# atlas-skills-sandbox

A cut-down copy of [atlas-skills](https://github.com/Cellular-Semantics/atlas-skills)
for trying out its release process before adopting it there. It holds one
plugin, the package that plugin runs, and a bundle — enough to exercise
every versioning rule, and small enough that a mistake costs nothing.

**Not for analysis work.** Use atlas-skills for that. The skill text is copied
unchanged, so it still mentions `remote-h5ad-obs` and links to atlas-skills'
benchmark; those refer to the parent repo.

```
.claude-plugin/marketplace.json    the marketplace (one file, in this repo)
plugins/author-annotation-columns/ the skill + two picker sub-agents
plugins/atlas-tools/               bundle: author-annotation-columns ~0.4.0
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
| Who reads the tag | a ref-pinned marketplace; a bundle's version range | the `uvx --from …@<tag>` line in a skill |

A plugin tag freezes its SKILL.md, and the SKILL.md holds the package pin. So
**a plugin release determines its package release** — read the skill at the
plugin tag and you know exactly which package it runs. `docs/pins.md` shows
the mapping for main; the nightly run's summary shows it for every supported
tag.

Two plugin releases that pin different package releases can run on one machine
at once: `uvx` builds a separate cached environment per exact pin, so they never
share an install.

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

Commit that as `.claude/settings.json` in a project, and every clone gets the
plugin with no install step. It follows main, and an installed copy refreshes
when the plugin's version string changes.

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
- Whether two projects on one machine can pin the same marketplace name to
  different tags is not yet tested — see `docs/test-plan.md`, step 5.

### Supported releases

The newest **3** tags of each plugin are supported: the nightly workflow
re-installs every package they pin and runs that package's tests at its tag.
Older tags still install, but nothing checks that they still work.

## Releasing

Releases are cut by CI from main, never by hand. In order:

1. **Change a package**: edit, bump `pyproject.toml`'s version, open a PR.
   `version-bumps` fails if the code changed and the version did not.
   Merge. The `release` workflow tags `pkg-<dir>--v<new>` and checks it
   installs from a cold cache.
2. **Adopt it in a plugin**: second PR — move the skill's pin to the new tag,
   bump `plugin.json`. `skill-pins-resolve` proves the pin installs. Merge.
   `release` runs `claude plugin tag`, which validates the plugin and checks
   it against the marketplace entry, then pushes `<plugin>--v<new>` and writes a
   GitHub Release listing the package pins.

The two steps cannot share a PR: the package tag does not exist until the first
merge, so the pin has nothing to resolve to. (The parent repo pushes the package
tag from a branch and does both in one PR; that puts an unreviewed commit
behind a tag users install.)

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
- Pin skills to package tags, never to a branch or commit.
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
