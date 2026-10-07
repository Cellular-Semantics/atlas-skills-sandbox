---
name: author-annotation-columns
description: Work out which obs columns in a single-cell dataset hold the authors' own annotations — cell type (`author_cell_type`, `celltype.l1/l2/l3`, `BICCN_subclass_label`), tissue (`Organ`, `Organ_part`, `Tissue_ROI`, `Region`), developmental stage (`Developmental_stage`, `Gestational_age_pcw`, `age`) or disease (`Disease`, `Clinical_diagnosis`, `COVID_status`) — as opposed to the portal's standardised fields, cluster indices, donor ids, protocol and QC. Profiles the columns, has a sub-agent judge them, and pulls the ones it picks. Use when someone wants the original labels, finer granularity than CL/UBERON/HsapDv/MONDO, or "what the authors actually recorded".
---

# author-annotation-columns

Portals standardise annotation onto ontologies — cell type onto CL, tissue onto
UBERON, stage onto HsapDv, disease onto MONDO — and that is a lossy step. The
authors' own fields, often several levels of them, survive only as extra `obs`
columns with no naming convention. There is no reliable pattern to grep for.

`author_cell_type`, `BICCN_subclass_label`, `celltype.l3`, `Organ_part`,
`Tissue_ROI`, `Gestational_age_pcw`, `Tanner Stage` and `Clinical_diagnosis` are
all real examples. So are `seurat_clusters`, `Collection_site`, `Specimen_type`,
`Batch` and `Mouse date of birth`, which look just like them and are not.

This skill profiles every obs column, hands that profile to a picker sub-agent,
and pulls what it picks.

## Field types

Ask for one or more. Default to `cell_type` when the request is unqualified.

| `field_type` | what it holds | ontology it would map to |
|---|---|---|
| `cell_type` | author cell-type, class and state labels | CL |
| `tissue` | anatomical origin, any granularity | UBERON |
| `development_stage` | life stage and measures of age | HsapDv / MmusDv |
| `other_stage` | menstrual, oestrous and cell-cycle phase | neither of the above |
| `disease` | diagnosis and health state | MONDO |

`other_stage` is separate on purpose. A menstrual phase and a cell-cycle call
are real, varying, worth picking — and they are not points in development, so a
value mapper must not send them to HsapDv. Keeping them apart at pick time is
cheaper than untangling them later.

## When to invoke

- "what did the authors call these cells", "the original annotations"
- "which tissues / regions are in this atlas", "what ages", "what diseases"
- someone wants finer granularity than the portal's standardised field
- an atlas comparison that needs author fields rather than harmonised ones

Not needed if the portal's standardised `cell_type`, `tissue`,
`development_stage` or `disease` is what the user wants — read those directly
with `remote-h5ad-obs`.

## Read obs once, then profile it locally

This is the whole shape of the skill, and the ordering matters.

```sh
# 1. one remote read -- this is the expensive step, so do it once
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills-sandbox@pkg-h5ad-obs--v0.3.1#subdirectory=packages/h5ad-obs" \
    h5ad-obs <url> --out obs.parquet --block-size 0.25

# 2. profile the file you just pulled -- free, no network
h5ad-obs obs.parquet --profile text > profile.txt
```

Profiling the **URL** instead (`h5ad-obs <url> --profile text`) also works, and
reads less, but it is almost never the right move: whatever it saves you pay
back with interest when you go to the network a second time for the columns the
picker chose. Measured on CELLxGENE:

| obs | profile the URL | read obs whole |
|---|---|---|
| 1,679 × 37 | 1.3 MB, 5 requests | 1.3 MB, 5 requests |
| 115,282 × 34 | 12.6 MB, 6 requests | 16.8 MB, 8 requests |
| 2,282,447 × 70 | 180 MB, 86 requests | 306 MB, 146 requests |

Profiling never saves more than about 40%, and a profile followed by a pull is
two trips past the same HDF5 metadata floor. **Profile the URL only when obs has
millions of rows and you are confident you want very few columns** — otherwise
read obs once and profile the parquet. (Times are not tabulated: they swing by
an order of magnitude with CDN cache state. Bytes are stable.)

`--profile` also accepts `.csv` and `.tsv`, and works on any obs table, not only
one this tool wrote.

Requires `h5ad-obs` **v0.3.0 or later** — earlier versions do not emit the
measurement column, and both pickers read it.

## What a profile looks like

```
obs profile: obs.parquet
2235448 rows x 54 columns; 2000 rows scanned per column.

name | kind | n_unique | measurement | sample values
Organ | categorical[7 cats] | 7 |  | 'Uterus', 'Fallopian Tube', 'Ovary', ...
Collection_site | categorical[16 cats] | 16 |  | 'Wellcome Sanger Institute', ...
Gestational_age_pcw | categorical[29 cats] | 29 | bounded 5..21 (97% numeric) | 'Not applicable', '6', ...
Batch | categorical[6 cats] | 6 | bounded 1..4 (67% numeric) | 'unknown', '4.0', ...
percent_mito | array float64 | ~2000 | continuous 0.0009..0.34 | 0.0328, 0.0419, ...
Sex | categorical[1 cats] | 1 (constant) |  | 'female', 'female', ...
```

Four things in there do real work:

- **Sample values are spread across the table, not taken from the head.** obs is
  routinely sorted by donor or cluster, and the first twenty rows of a sorted
  column show one value — which reads as a constant column when it is nothing of
  the kind.
- **`(constant)`** means every row was seen and they were all the same. A
  cardinality printed as an estimate (`~7`) came from a sample; `n_scanned` says
  how many rows that was. Only the explicit marker is evidence of constancy.
- **The measurement cell** is what makes stage pickable at all. `bounded` means
  the distinct values do not grow with the cell count, so the column is a
  property of a donor; `continuous` means one value per cell. An age is usually
  bounded, `percent_mito` is continuous, and without that distinction the two
  are just numbers. It is a **filter, not a verdict**, in both directions:
  across the 73-dataset fixture set, 133 bounded numeric columns were none of
  the four field types, and 3 of 315 continuous ones were real ages — `Mouse
  age` in a Patch-seq set with one animal per cell, and
  `age_or_mean_of_age_range` in a 2.3M-cell atlas. The picker knows this.
- The profile carries **no instructions**. The picking rules live in the picker
  agents and nowhere else, so the two cannot drift apart.

## Pick

Dispatch with the `Task` tool, giving the agent the path to `profile.txt`. Which
agent depends on the field types asked for; dispatch both when the request spans
them, in parallel, each seeing the same profile.

| field types | `subagent_type` | returns |
|---|---|---|
| `cell_type` | `author-celltype-picker` | `{"picks": [...], "reasoning": "..."}` |
| `tissue`, `development_stage`, `other_stage`, `disease` | `author-sample-field-picker` | `{"tissue": [...], "development_stage": [...], "other_stage": [...], "disease": [...], "reasoning": "..."}` |

Tell `author-sample-field-picker` which field types you want; it keys its answer
by field type and returns `[]` for the ones it finds nothing for.

They are separate agents because they answer differently shaped questions, not
because the profile differs. Cell type is decided by values almost alone;
tissue, stage and disease turn on distinguishing a sample-level fact from the
protocol that produced it, and for numeric ages the column *name* carries the
decision — the one place the cell-type rules would give the wrong answer.

Do not pre-filter the profile or tell an agent which columns look promising — it
gets a fresh context precisely so its judgment is independent of yours. For
several datasets, dispatch one agent per dataset in parallel; each must see only
its own profile.

`[]` is a real answer, not a failure. Some datasets genuinely have no author
cell-type column, no disease column, or — very commonly — no tissue column at
all, because the atlas is single-tissue and says so in its metadata rather than
in obs. Report that as a finding.

## Pull and report

The columns are already in `obs.parquet`; subset it.

```python
import pandas as pd
obs = pd.read_parquet("obs.parquet")
obs[["Organ", "Organ_part"]].value_counts()        # the tissue hierarchy, as used
obs[["Developmental_stage", "Postnatal_age_years"]].value_counts()
```

Tell the user: which columns were picked for which field type and why, how many
distinct values each holds, how they nest where there is more than one, and how
they line up against the portal's standardised field if there is one. A picked
`Organ_part` with 30 values against a standardised `tissue` with 7 is the point
of the exercise — say so.

For stage and disease, also say what the values *look like*, because that
decides whether they can be mapped: `Postnatal_age_years` as bare numbers needs
binning before HsapDv, `Tanner Stage` needs a lookup table, and
`Clinical_diagnosis` as free text will not resolve to MONDO cleanly.

## Traps

- **Show your working.** The cell-type picker is benchmarked on 73 CELLxGENE
  datasets against CL_KG hand curation: mean Jaccard 0.94, precision 0.96,
  recall 0.96, at least one correct column in 72/73. **The sample-field picker
  has no comparable number yet** — its gold set is one hand-curated atlas, so
  treat its picks as a proposal and name them in your answer so the user can see
  a spurious one. Do not quote the cell-type figures for tissue, stage or
  disease.
- **A numeric column with many categories is a cluster index, not a label** —
  even when the values are strings. `seurat_clusters`, `leiden`, `louvain` and
  `initial_clustering` all appear in the test set with string-typed integers.
- **...except for age, which is the one numeric field you do want.**
  `Gestational_age_pcw`, `Postnatal_age_years` and a bare `age` are picks. What
  separates them from a cluster index is the name and the range, not the values:
  `bounded 5..21` with a name saying weeks is an age; `bounded 0..29` starting
  at zero is a cluster. Age is the one field where a name outranks what you can
  see, and the one field where `continuous` does not settle it.
- **`Collection_site` is an institution.** `Wellcome Sanger Institute`,
  `University of Michigan`. It is the most reliable tissue trap there is, and
  the name is the whole of it.
- **Tissue-shaped names carrying disease values.** `Sampled_site_condition`
  (`normal`, `endometriosis`) and `Tissue_status` (`affected`, `unaffected`) are
  disease, not tissue.
- **`Specimen_type` is a method** — `biopsy`, `whole_tissue` — not a tissue.
- **Dates are not ages.** `Mouse date of birth` and collection dates are
  rejected; an age is derivable from them and that is not the same thing.
- **Experimental time is not developmental time.** `timepoint`,
  `day_in_culture`, `hours_post_treatment`.
- **Exposures are not diseases.** `Smoker`, `BMI`, `pack_years`.
- **A constant column is not an annotation.** A single-tissue atlas often
  carries a constant `Organ`, and a healthy-donor atlas a constant `Disease`.
  They read like the real thing and carry no information.
- **The portal's fields are never picks**, whatever the user asked for:
  `cell_type`, `tissue`, `development_stage`, `disease` and every
  `*_ontology_term_id`. The trap is that CxG's column is named exactly `disease`
  and the authors' is named `Disease`.
- **This takes a file URL, not a portal page.** The same rule as
  `remote-h5ad-obs`: the tool refuses a `celltype.info` or
  `cellxgene.cziscience.com` page and tells you what to run instead.

## See also

- `remote-h5ad-obs` — the same reader, for when you just want obs.
- [`packages/obs-column-eval`](https://github.com/Cellular-Semantics/atlas-skills/tree/main/packages/obs-column-eval)
  — the gold sets and metrics behind the numbers above, for all five field
  types. `obs-column-eval notes` prints the reasoning behind the awkward calls.
- [`docs/benchmark.md`](https://github.com/Cellular-Semantics/atlas-skills/blob/main/docs/benchmark.md)
  — what the benchmark measured, and what changed since.
