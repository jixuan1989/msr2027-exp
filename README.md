# Account Scope in Role-Aware Collaboration Networks

[中文说明](README.zh-CN.md)

This artifact contains the data, executable experiments, reference results, and plotting code for **Auditing Account Scope in Collaboration Measurements via Role-Aware Networks**. It covers the three comparisons retained in the final manuscript: community membership (RQ1), reviewer candidate rankings (RQ2), and project collaboration and maintenance measurements (RQ3).

The primary reproduction route starts from a fixed selection of AIDev event records bundled here. Original public account, PR, and repository identifiers are retained.

## What is included

| Location | Contents |
|---|---|
| `data/processed/` | All 4,222,224 selected event records; the 425,548-row account-type registry; release data checksums and schema |
| `data/plot/` | Minimal inputs for the five final experimental figures: two saved graphs, shared coordinates, local case, public candidate-list example, and aggregate tables |
| `scripts/build_role_aware_network.py` | Streaming construction of account–event–PR nodes and directed relations |
| `scripts/run_rq1.py` | Two account scopes, unit event weights, eight-seed Leiden comparison |
| `scripts/run_rq2.py` | Frozen-history repository-frequency rankings and all eligible test PRs |
| `scripts/run_rq3.py` | Paired repository measurements and five monthly metric series |
| `scripts/render_figures.py` | Redraw Figures 3–7 from their saved inputs |
| `scripts/upstream/` | Optional original download, labeling, event construction, filtering, and inventory code |
| `results/reference/` | Original main-experiment results used to check new executions |
| `figures/` | Reference PDF, PNG, and SVG experimental figures |
| `validation/` | Recorded full-data reproduction checks and figure verification |
| `environment/` | Exact package versions used for validation |

The account-type registry covers more accounts than those involved in the selected events. The event graph contains 45,592 account identifiers and six tool-source identifiers, giving 45,598 account-class nodes.

## Install

Use Python 3.11 and an environment with the versions in `requirements.txt`:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run commands from the repository root. All primary inputs are included; newly generated files go into `outputs/`.

## Verify, rerun, and redraw

Check the release file list, SHA-256 checksums, data counts, and package contents:

```sh
python scripts/reproduce.py --stage verify
```

Run graph construction, all three full-data experiments, numerical checks, and plotting:

```sh
python scripts/reproduce.py --stage all
```

To run stages individually:

```sh
python scripts/reproduce.py --stage graph
python scripts/reproduce.py --stage rq1
python scripts/reproduce.py --stage rq2
python scripts/reproduce.py --stage rq3
python scripts/reproduce.py --stage check
python scripts/reproduce.py --stage figures
```

RQ1 requires graph construction first. RQ2 and RQ3 read the same selected events directly. For a quick figure-only review:

```sh
python scripts/render_figures.py --out-dir outputs/figures
```

All stages run on the CPU. Graph construction and community analysis store large structures in memory. The full-data run creates graph, table, and figure files in `outputs/`. The validation environment and verification results are included.

## Main results and validation

| Comparison | Reference result |
|---|---|
| RQ1, 10,808 shared humans | NMI `0.7572 ± 0.0039`; ARI `0.1017 ± 0.0024` across eight seeds |
| RQ2, 15,899 PRs / 3,012 repositories | All-known/Human-only MRR@10 `0.4323 / 0.4925`; non-human accounts occupy `23,348 / 81,576 = 28.62%` of returned All-known top-ten positions |
| RQ3, paired repository means | All-known minus Human-only: active accounts `+0.7780`, reviewers `+0.2720`, HHI `−0.1901`, and review-activity k50 `+0.1566` |
| RQ3, responding PRs | Median hours to first submitted review: `0.5267 / 1.3539`, on `83,074 / 59,694` PRs |

The full-data rerun was checked against the archived final results. See `validation/reproduction_checks.json` for the individual checks.

## Detailed documentation

- [Experiment methods, parameters, exact expected values, and figure mapping](docs/EXPERIMENTS.en.md)
- [Dataset schema, counts, original identifiers, and field selection](docs/DATASET.en.md)
- [Upstream sources, attribution, and optional reconstruction](docs/UPSTREAM_SOURCES.md)
- [Code provenance](docs/CODE_PROVENANCE.json)
- [Study snapshot and inventory](docs/STUDY_SNAPSHOT.json)
- [Data and third-party notices](NOTICE.md)

## Public data and package scope

AIDev is a public dataset. This artifact retains its original public account identifiers, GitHub usernames, PR and repository identifiers, and repository URLs. The export selects the fields needed by the experiments and preserves their values and row order.

The package contains the data fields, code, documentation, and results needed by the experiments. Credentials, host configuration, local filesystem paths, execution logs, Git history, review and comment bodies, and full profiles are excluded.

The package provides a fixed event snapshot for reproducing the main results. Distinct source commit, comment, and other object counts are retained as an aggregate inventory; the full AIDev source tables are available upstream.
