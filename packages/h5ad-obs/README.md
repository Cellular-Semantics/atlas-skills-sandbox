# h5ad-obs

Reads the `obs` table out of a remote `.h5ad` by fetching only the byte ranges
that back it. `X`, `layers`, `obsm`, `var` and `raw` are never read.

Works against any host honouring HTTP range requests — GCS, S3, Sanger COG,
CELLxGENE's CDN, plain static hosts.

```sh
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills-sandbox@pkg-h5ad-obs--v0.3.1#subdirectory=packages/h5ad-obs" \
    h5ad-obs https://datasets.cellxgene.cziscience.com/<id>.h5ad --list-columns
```

stdout is a JSON summary including byte accounting; the obs table itself goes to
`--out` (parquet by default) because it is usually large.

## Profiling

`--profile` prints a per-column summary — storage kind, cardinality, whether the
column is a measurement, and sample values — instead of reading obs. It is what
an agent needs to decide *what a column is*.

```sh
h5ad-obs <url> --out obs.parquet       # one remote read
h5ad-obs obs.parquet --profile text    # free; also accepts .csv / .tsv
h5ad-obs <url> --profile               # JSON, straight off the wire
```

```
name | kind | n_unique | measurement | sample values
BICCN_cluster_label | categorical[33 cats] | 33 |  | 'Vip', 'L4', 'Ndnf', 'Pvalb', ...
major_dissection | categorical[1 cats] | 1 (constant) |  | 'V1', 'V1', 'V1', ...
total_reads | array int64 | ~1679 | continuous 1.1e6..4.2e7 | 23770190, 18388503, ...
Gestational_age_pcw | categorical[29 cats] | 29 | bounded 5..21 (97% numeric) | 'Not applicable', '6', '11', ...
```

Sample values are **spread across the table, not taken from the head**: obs is
routinely sorted by donor or cluster, and the first twenty rows of a sorted
column show one value. `(constant)` means the cardinality is known exactly and
is one — always determinable for a categorical, and for anything else only when
every row was scanned (`--scan-rows`, default 2000).

### Measurement

The fourth column is blank unless most of the column's distinct values parse as
numbers — strings included, because an age routinely arrives as numerals in a
category table beside a sentinel (`'6'`, `'11'`, `'Not applicable'`), and a test
that only looked at the dtype would call that text.

`bounded` means the distinct count does not grow with the cell count, so the
column is a property of a donor or a sample; `continuous` means it has roughly
as many distinct values as rows, which is what a per-cell quantity looks like.
That is the cheap thing separating a measure of age from a QC score — both are
just numbers, but one has forty distinct values and the other has one per cell.

It is a **filter, not a verdict**, and it errs in both directions. Batch
indices, cluster indices and ordinal scores are all bounded numerics; the name
and the range still decide. Going the other way, an age is `continuous` when
there are enough donors to give one distinct value per cell — a Patch-seq set
with one animal per cell, or a 2.3M-cell atlas. Measured over 73 CELLxGENE
datasets: 133 bounded numeric columns were not donor-level facts, and 3 of 315
continuous ones were real ages.

Below roughly 500 rows the test weakens further, because an absolute floor (50
distinct values) has to let small tables through.

For a categorical the range is taken from the declared category table, so a
category too rare to appear in the scan is still in it. For anything else it
comes from the scanned rows.

Profiling a URL reads less than a full obs read, but not by much, so it is
rarely worth a second trip to the network:

| obs | `--profile` | full obs |
|---|---|---|
| 1,679 x 37 | 1.3 MB, 5 requests | 1.3 MB, 5 requests |
| 115,282 x 34 | 12.6 MB, 6 requests | 16.8 MB, 8 requests |
| 2,282,447 x 70 | 180 MB, 86 requests | 306 MB, 146 requests |

Read obs once and profile the file, unless obs has millions of rows and you want
very few columns.

## Cost

On a 476 MB atlas, all 51 obs columns cost 13 range requests and 27.3 MB in
~8-13 s. The floor is ~21 MB because HDF5 metadata is scattered through the file
and must be walked before any column is readable — **reading one column costs
nearly as much as reading all of them**, so pull the whole table once and subset
locally.

`--block-size` trades bytes against round trips. The default of 2 MB suits large
files; on a small one it overshoots badly. On a 30.6 MB CELLxGENE dataset:

| `--block-size` | requests | fetched | % of file |
|---|---|---|---|
| 2 (default) | 5 | 10.5 MB | 34% |
| 0.5 | 6 | 3.1 MB | 10% |
| 0.125 | 9 | 1.2 MB | 3.9% |

## Development

```sh
./dev.sh            # offline suite; runs the whole range-read path against localhost
./dev.sh -m live    # also reads a real dataset over the network
```

The live test resolves a 385-cell CELLxGENE Patch-seq dataset through the
CELLxGENE API at run time, so a revision upstream does not break it. Override
with `H5AD_OBS_LIVE_URL=<url>` to test against your own host.

## Not a portal client

This package takes a URL to a file. Resolving a *portal page* to that URL is a
per-portal job and deliberately lives elsewhere — for CAP, `cap h5ad-url` in the
[cap_skills](https://github.com/Cellular-Semantics/cap_skills) repo:

```sh
h5ad-obs "$(cap h5ad-url https://celltype.info/project/934/dataset/3016 --format text)"
```

Handing a known portal URL to `h5ad-obs` fails immediately with a message saying
what to run instead, rather than trying to parse HTML as HDF5.
