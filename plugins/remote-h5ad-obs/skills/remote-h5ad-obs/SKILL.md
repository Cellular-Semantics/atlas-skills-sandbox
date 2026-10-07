---
name: remote-h5ad-obs
description: Read the `obs` table out of a remote .h5ad over HTTP range requests, without downloading the expression matrix. Works against any host honouring range requests — GCS, S3, Sanger COG, the CELLxGENE CDN, plain static hosts. Use when you need per-cell annotations, cell-type assignments or ontology term ids from a published atlas that is too large to download.
---

# remote-h5ad-obs

Pull `obs` from a remote h5ad by fetching only the byte ranges that back it. `X`,
`layers`, `obsm`, `var` and `raw` are never read. On a 476 MB atlas this
transfers ~27 MB in ~8-13 s.

## When to invoke

- "get the obs / cell metadata from this h5ad URL"
- "what cell types are in \<atlas URL\>" (per-cell assignments)
- needing ontology term ids, donor/tissue/assay covariates, or curator rationale
  fields that live in `obs`

**Not** for expression values: those mean reading `X`, which is a real download.
**Not** for a portal *page* — see "This takes a file URL" below.

## Command

```sh
uvx --from "h5ad-obs[parquet] @ git+https://github.com/Cellular-Semantics/atlas-skills-sandbox@pkg-h5ad-obs--v0.3.0#subdirectory=packages/h5ad-obs" \
    h5ad-obs <url> [options]
```

Needs `uv` and, on first run, network access to GitHub. Expect the first
invocation to take a minute while uv builds h5py, pandas and aiohttp; cached
thereafter. Expects `h5ad-obs` 0.2.0 or later (`h5ad-obs --version`), the release
that added `--profile`.

**Options:**

- `--list-columns` — print obs columns and their encodings, then exit.
- `--columns COL ...` — read only these. Saves less than you would expect; see
  "Cost".
- `--out FILE`, `--format {parquet,csv,tsv}` (default parquet, which needs
  `pyarrow`; csv and tsv need nothing extra).
- `--block-size MB` — default 2. **Tune this** (see below).
- `--no-preflight` — skip the range-support check.
- `--profile [json|text]` — print a per-column summary (kind, cardinality,
  spread sample values) instead of reading obs. Also works on an obs table
  already on disk, which costs nothing. The `author-annotation-columns` skill is
  built on it, and installs separately.

stdout is a JSON summary — row and column counts, skipped columns, and byte
accounting (`range_requests`, `mb_fetched`, `file_bytes`). The obs table itself
goes to the output file, because it is usually large.

## Tune `--block-size` to the file

The 2 MB default is tuned for 400 MB+ atlases. On a small file it overshoots
badly — measured on a 30.6 MB CELLxGENE dataset:

| `--block-size` | requests | fetched | % of file |
|---|---|---|---|
| 2 (default) | 5 | 10.5 MB | 34% |
| 0.5 | 6 | 3.1 MB | 10% |
| 0.125 | 9 | 1.2 MB | 3.9% |

Smaller fetches fewer bytes but makes more round trips, so on a high-latency link
larger is faster. Under ~100 MB, start at 0.25.

## Cost

Measured on a 476 MB atlas, 49,387 cells x 51 obs columns:

| request | range requests | fetched | time |
|---|---|---|---|
| all 51 columns | 13 | 27.3 MB | ~8-13 s |
| `--list-columns` | 10 | 21.0 MB | ~7 s |
| 1 column | 10 | 21.0 MB | ~7 s |

The floor is ~21 MB because HDF5 metadata — superblock, B-trees, object headers —
is scattered through the file and must be walked before any column is readable.
**Reading one column costs nearly as much as reading all of them**, so pull the
whole table once and subset locally. `--columns` trims the output, not the
transfer.

## What you get back

Column order comes from `obs.attrs["column-order"]`, with any columns present in
the group but missing from that attribute appended. Three AnnData encodings are
handled: plain arrays (bytes decoded to str), categorical (`categories`/`codes`),
and nullable masked (`values`/`mask`, where masked entries come back as null, not
`False`). An unrecognised encoding is skipped and named in `skipped_columns`
rather than aborting the run.

## This takes a file URL, not a portal page

Resolving a portal's dataset page to its underlying h5ad is a per-portal job and
lives elsewhere. Handing a known portal URL here fails immediately with the
command to run instead, rather than trying to parse HTML as HDF5.

**CAP** (`celltype.info`) — use `cap h5ad-url` from the `cap-tools` plugin:

```sh
uvx --from "h5ad-obs[parquet] @ git+https://github.com/Cellular-Semantics/atlas-skills-sandbox@pkg-h5ad-obs--v0.3.0#subdirectory=packages/h5ad-obs" \
    h5ad-obs "$(cap h5ad-url https://celltype.info/project/934/dataset/3016 --format text)"
```

Many CAP datasets expose no public h5ad at all, and then this route is closed;
`cap expression --list-obs-columns` still reports what obs contains.

**CELLxGENE** — the asset URL is on the dataset page, or from the API:

```sh
curl -s "https://api.cellxgene.cziscience.com/curation/v1/collections/<collection_id>/datasets/<dataset_id>" \
  | jq -r '.assets[] | select(.filetype=="H5AD") | .url'
```

That URL embeds a dataset *version* id which changes when the dataset is revised,
so resolve it rather than storing it if you need the current version.

## Traps

- **Range support is mandatory.** The preflight `HEAD` requires
  `accept-ranges: bytes` and stops with that message rather than silently pulling
  gigabytes. A host without it means the file must be downloaded whole.
- **`cache_type="blockcache"` is not optional** in the implementation. fsspec's
  default `readahead` cache holds only the current block, so h5py's scattered
  chunk reads refetch endlessly — the read that takes 8 s with blockcache ran 10+
  minutes without finishing a single column. If you adapt this pattern elsewhere,
  carry that setting with it.
- **An explicit certifi SSL context is required.** aiohttp does not read the macOS
  keychain, so GCS/S3 otherwise fail with `CERTIFICATE_VERIFY_FAILED`.
- 401/403 means the store needs credentials. This does not handle auth; report it.

## Verified against

- **CELLxGENE CDN**, 385-cell Patch-seq dataset (30.6 MB): 45 obs columns,
  `385 x 45`, no skipped encodings, 1.2 MB fetched at `--block-size 0.125`. This
  is the live test, resolved through the CELLxGENE API at run time so an upstream
  revision does not break it.
- **GCS**, a 476 MB atlas: full obs `49,387 x 51` in 27.3 MB; `--columns`,
  `--list-columns`, csv and tsv output.
- Preflight correctly refuses a host without range support.
- The offline suite runs the whole path against a localhost range server,
  including a check that the matrix's byte ranges are never touched.

Not yet exercised against **S3** or **Sanger COG**. An earlier one-off script does
read a 92.8 GB Sanger COG h5ad this way, so the pattern holds there — but it
predates the `blockcache` finding and uses fsspec's default cache, so it is likely
far slower than it needs to be. Treat those two hosts as expected-to-work rather
than tested.
