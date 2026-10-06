# Iterating on a package while a skill uses it

How to change `packages/<x>` without a release for every edit, and how to
release once the behaviour settles. Adapted from atlas-skills; the release
step differs (see the end).

The `--from` pin in SKILL.md is the only thing that selects a package version.
`plugin.json`'s version selects which copy of the *plugin* an installed user
has: Claude Code refreshes an installed plugin only when that string changes.
So bumping the plugin does not pull new package code, but not bumping it means
nobody already installed receives the new pin.

Three loops, in increasing cost:

**Skill text or an agent prompt.** Load the plugin from your worktree for one
session, no install needed:

```
claude --plugin-dir plugins/author-annotation-columns
```

Bump `plugin.json` when you open the PR; `version-bumps` will insist.

**Package code, while the behaviour is still moving.** Use an editable install
and call the binary directly:

```
uv venv && uv pip install -e "packages/h5ad-obs[test]"
.venv/bin/h5ad-obs <url> --out obs.parquet
```

Do **not** point the `--from` pin at a local directory instead. `uvx` caches the
build: editing the source and re-running gives the stale version back, silently.

**Releasing.** Two PRs, because the package tag is cut on merge:

1. Bump `packages/<x>/pyproject.toml`. Merge. `release` tags `pkg-<x>--vX.Y.Z`.
2. Move the pin in every skill that should adopt it, bump those plugins'
   versions, regenerate `docs/pins.md`. Merge. `release` tags the plugins.

A plugin that should stay on the old package simply is not part of step 2.

A pin must resolve for someone with a cold cache. Check it the way CI does:

```
uvx --no-cache --from "git+https://github.com/Cellular-Semantics/atlas-skills-sandbox@<tag>#subdirectory=packages/<dir>" <dir> --version
```

### Quoting

Skills must write the full quoted command, not `CMD="uvx …"` then `$CMD`.
Unquoted parameters do not word-split under zsh, the macOS default shell, so
the variable form fails with `command not found: uvx --from …`.
