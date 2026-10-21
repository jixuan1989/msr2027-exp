# Final experiments: data, methods, expected results, and figures

This document describes the final RQ1–RQ3 experiments in the manuscript.

## 1. Scope and entry points

The main experiments compare **All-known and Human-only** under fixed task rules.

- **All-known:** participation records from accounts with resolved types, including humans, bots, and AI-agent accounts.
- **Human-only:** human executing accounts or human reviewer candidates, according to the task.
- Bot and service-account labels are combined as bots for reporting. A PR-level AI tool label records the tool category; the author's identity is determined by its account-type label.
- Existing dataset and derived account labels are treated as working assumptions.

Run the local main entries from the repository root after installing the documented dependencies:

```sh
python scripts/build_role_aware_network.py --events data/processed/actor_pr_events.parquet --actor-labels data/processed/actor_labels.parquet --out outputs/role_aware_network
python scripts/run_rq1.py
python scripts/run_rq2.py
python scripts/run_rq3.py
python scripts/check_results.py --result-dir outputs
```

The graph-building command prepares RQ1's input. The three `run_rq*.py` commands write their results under `outputs/rq1`, `outputs/rq2`, and `outputs/rq3`. The checker compares generated main results with the documented reference numbers. Consult the repository README for dependency installation, available CLI options, resource estimates, and current run status.

The main entry points compute the two account scopes reported in the final paper.

## 2. Processed inputs and graph construction

The numerical analyses use:

- `data/processed/actor_pr_events.parquet`: 4,222,224 saved participation/tool-label records.
- `data/processed/actor_labels.parquet`: account-type resolution information, with 425,548 label records in its source universe.

The package retains the public AIDev account, PR, and repository identifiers, account logins, and repository URLs. Original row order, identifier order, timestamps, and graph structure are preserved.

Required event fields include PR/repository identifiers, executing-account identifiers and types, relation labels, and event times. Required label information maps a stable account key to its account type. The three experiments run locally using these processed event and label tables.

The processed snapshot covers 25,402 repositories and 361,296 PRs. The selected records involve 45,592 account identifiers: 44,871 human, 607 bot, and 114 AI-agent accounts. The bot total combines 592 automation-bot and 15 service-account identifiers. The source-object inventory contains 685,948 distinct `(repository, commit SHA)` pairs; no Issue records are used.

The input-row decomposition is:

| Stored record source | Rows |
|---|---:|
| PR author | 361,296 |
| PR tool label | 361,296 |
| General PR comment | 373,549 |
| Inline review comment | 289,769 |
| Submitted review | 281,152 |
| Commit participation | 719,920 |
| Timeline actor | 1,633,775 |
| Timeline assignee | 201,467 |
| **Total** | **4,222,224** |

Commit participation includes 700,176 author records and 19,744 records for a distinct committer. A commit object and an account's participation in that commit are different counting units.

RQ1 requires the role-aware relation edges. Generate the graph with the explicit command above; its output location is `outputs/role_aware_network`. RQ2 and RQ3 read the processed event data directly. The expected graph has 45,598 account-class nodes, 361,296 PR nodes, 4,222,224 event nodes, and 8,444,448 directed unit-weight relations. Every stored record produces an account→event→PR path. The extra six account-class nodes correspond to tool-source identifiers.

## 3. RQ1: account scope and community membership

### Question and input selection

Does including non-human accounts change which **shared human accounts** are assigned to the same collaboration group?

Use the full selected event snapshot. Retain PR creation (`author`), submitted reviews (`review`), inline review comments (`review_comment`), and general comments (`comment`); exclude commit, timeline, assignment, and synthetic tool-label relations.

Determine active accounts separately within each scope. An account is active if it participates in at least one author–reviewer or author–commenter interaction between distinct accounts in that scope. Build an undirected account–PR bipartite graph using the retained active accounts. Each selected record adds one unit to its account–PR edge weight, accumulating the original event counts.

Both account and PR vertices are clustered. Partition agreement is evaluated on human accounts shared by the two complete graphs. Activity is determined separately within each account scope, so the retained human accounts and PRs vary with the interaction filters.

### Detector, seeds, and metrics

- Detector: Leiden with `ModularityVertexPartition`, ordinary weighted modularity, and default settings.
- Seeds: `0, 1, 2, 3, 4, 42, 123, 2024`.
- Preserve canonical sorted vertex identifiers and the source edge insertion order.
- NMI: normalized mutual information with scikit-learn's default arithmetic normalization.
- ARI: adjusted Rand index.
- Report the mean and **population standard deviation** (`statistics.pstdev`) over the eight seeds as “mean ± population standard deviation.”

The saved reference used Python 3.11.3, python-igraph 1.0.0, leidenalg 0.12.0, and scikit-learn 1.7.2. Reproduction uses fixed dependency versions and the original public identifier order for graph construction and score tie breaks.

### Expected main results

| Result | All-known | Human-only |
|---|---:|---:|
| Account vertices | 25,573 | 10,808 |
| PR vertices | 268,510 | 127,698 |
| Total vertices | 294,083 | 138,506 |
| Account–PR edges | 546,167 | 151,925 |

There are 10,808 shared human accounts. On these accounts:

| Metric | Expected mean | Expected population SD |
|---|---:|---:|
| NMI | 0.7571731968625485 | 0.0039056206469186843 |
| ARI | 0.10174317476179824 | 0.002417013178965648 |

The paper rounds these to NMI `0.7572 ± 0.0039` and ARI `0.1017 ± 0.0024`. Generated outputs are `outputs/rq1/summary.json` and `outputs/rq1/per_seed.csv`; archived reference evidence is under `results/reference/rq1`.

### Figures and interpretation

- Figure 3, `fig:rq1-global-identity`: `fig_rq1_global_horizontal_focus_v3.pdf`. Both panels reuse force-directed coordinates calculated from the All-known graph's actual weighted edges and the same viewport. Colors are aligned by membership overlap among shared humans. The window contains 96.4% and 94.4% of the respective complete graphs' vertices, with all vertices and edges within the window drawn. Empty regions reflect excluded vertices and incident edges.
- Figure 4, `fig:rq1-local-identity`: `fig_rq1_local_horizontal_v2.pdf`. The illustrative case contains 19 shared humans, three bots, and 16 PRs. Full-graph labels place these humans in one All-known community and in two Human-only communities of 11 and 8 people. The displayed subgraph changes from one connected component with 61 edges to two components with 40 edges. The fixed 19-human membership correspondence persists across all eight seeds.

The local case illustrates these grouping differences, using community labels taken directly from the complete graphs.

## 4. RQ2: non-human positions in reviewer candidate lists

### Frozen history and targets

- Historical cutoff: **2026-01-01 00:00:00 UTC**.
- Historical PR creation and review event times must both be strictly before the cutoff. The entire evaluation block uses the same pre-cutoff history.
- Target PR creation interval: **[2026-01-01, 2026-03-01) UTC**, i.e., January–February 2026.
- Targets for each PR: distinct human reviewers observed in **[creation, creation + 30 days)**, selecting accounts other than the PR author.
- Keep PRs with at least one such observed human reviewer. The reference contains 15,899 eligible PRs in 3,012 repositories; 95,454 PRs in the target interval have no such observed target and are excluded from this evaluation.

Select `review` and `review_comment` for historical evidence and targets. For each `(PR, reviewer)` pair, first select its earliest valid event, then retain the pair when that event occurs at or after PR creation. When source repository metadata disagrees, use the repository in the PR creation record.

### Candidate score and account scopes

For each target PR, score a candidate by the number of distinct pre-cutoff PRs that candidate reviewed in the same repository. Sort by decreasing score and then increasing stable account key; exclude the target PR author.

All-known permits known human and non-human candidates, while Human-only permits human candidates. Eligibility depends on the reviewing account's type, and human reviews of historical PRs by non-human authors contribute to the score. Under this repository-frequency score, human candidates retain their relative order after filtering.

The method section also defines an author-specific collaboration score. The final RQ2 experiment uses the repository-frequency score.

### Evaluation and expected results

Evaluate `k = 1, 3, 5, 10, 20`:

- **Hit@k:** whether at least one observed target reviewer appears in the first k candidates.
- **Recall@k:** fraction of the PR's observed target reviewers appearing in the first k candidates.
- **MRR@10:** reciprocal rank of the first observed target reviewer if it appears in the first ten, otherwise zero.

Accuracy metrics are unweighted means over the 15,899 eligible PRs. Empty candidate lists contribute zero. The non-human position fraction instead divides the total non-human returned positions by **all actually returned top-ten positions**.

| Metric | All-known | Human-only |
|---|---:|---:|
| Hit@10 | 0.6097867790427071 | 0.6170828353984528 |
| Recall@10 | 0.5711480805920707 | 0.579449591019501 |
| MRR@10 | 0.4322625112690526 | 0.49252014452341514 |
| Non-human top-ten position fraction | 0.28621163087182505 | 0 |
| Hit@1 | 0.3529152776904208 | 0.4268821938486697 |
| Hit@20 | 0.6319265362601422 | 0.6336247562739795 |

The 28.62% result is **23,348 / 81,576 returned positions**, aggregated over the 81,576 positions actually returned in top-ten lists.

Generated results are `outputs/rq2/reviewer_metrics.csv` and `outputs/rq2/summary.json`. Archived reference evidence is under `results/reference/rq2`.

### Table, figures, and interpretation

- `tab:reviewer` (currently Table III): the two repository-frequency scope rows above; the main reference CSV selector is `split=final_test`, `scope=micro`.
- Figure 5, `fig:reviewer-candidate-audit`: `fig_reviewer_candidate_lists_v2.pdf`. The saved real example has two non-human Copilot accounts at the top; an observed human reviewer moves from fourth to second after filtering. The post-filter and Human-only saved candidate records agree.
- Figure 6, `fig:rq3-curves`: `fig_reviewer_identity_k_compact_v2.pdf`. This legacy label belongs to RQ2. Plot Hit@k and Recall@k directly from the metric values for the same final-test PRs and historical cutoff.

This experiment compares candidate eligibility and visibility within a limited recommendation list.

## 5. RQ3: collaboration and maintenance measurements

### Record eligibility and denominators

From the 4,222,224 stored input records, select known-type activity records with an executing account and valid timestamp, excluding synthetic PR tool-label records. This yields **2,721,064 maintenance-eligible activity records**.

| Record category | Human | Non-human | Total |
|---|---:|---:|---:|
| Maintenance-eligible activity | 1,419,177 | 1,301,887 | 2,721,064 |
| Review plus inline review comment | 264,270 | 306,651 | 570,921 |

Non-human activity accounts for 47.84% of maintenance-eligible records, with a denominator of 2,721,064. Non-human review activity accounts for 53.71% of review interaction records, with a denominator of 570,921.

The analysis covers 25,402 repositories, 361,296 PRs, 54,065 repository-month rows, and 17 months from December 2024 through April 2026.

### Five metrics

1. **Active account count:** distinct executing accounts in a repository/event month.
2. **Reviewer count:** distinct accounts producing `review` or `review_comment` in that repository/event month.
3. **Review concentration (HHI):** sum of squared account shares of submitted-review and inline-comment records, counted row by row.
4. **k50:** minimum number of accounts, ordered by descending review count, covering at least half of review records.
5. **Time to first submitted review:** elapsed hours from PR creation to the earliest valid `review` by an account in the selected scope, grouped by PR creation month. Submitted reviews are identified by the `review` relation. The calculation uses all valid submitted reviews in the snapshot, including self-reviews by the author.

Zero account/reviewer counts remain valid observations. HHI and k50 are calculated for cells containing review records; other cells are recorded as missing. Response time is calculated for PRs with an observed qualifying submitted review; other PRs are recorded as missing.

### Aggregation and expected results

For each of the first four headline metrics, retain months valid in both scopes within each repository, average those months for each scope, then take the unweighted mean across eligible repositories. Paired differences are All-known minus Human-only. Point estimates use all eligible observations.

| Headline metric | All-known mean | Human-only mean | Paired mean difference |
|---|---:|---:|---:|
| Active accounts | 2.180274648889759 | 1.4022276123293815 | +0.7780470365603773 |
| Reviewers | 0.6051421640474958 | 0.3331478922084629 | +0.27199427183903274 |
| HHI | 0.67302705519254 | 0.8631452959052891 | -0.19011824071274908 |
| k50 | 1.210067980282102 | 1.0534363135943559 | +0.15663166668774622 |

Account/reviewer means use 25,402 repository pairs and 54,065 month pairs. HHI/k50 use 7,846 repository pairs and 16,083 month pairs. Reference values come from the final v2 snapshot.

Response time is summarized over individual responding PRs, separately by scope:

| Response sample | PRs | Expected pooled median hours |
|---|---:|---:|
| Any qualifying account | 83,074 | 0.5266666666666666 |
| Human account | 59,694 | 1.353888888888889 |

Any-account and human response times are summarized over their respective observed-response PR samples. Exact historical quantiles select `sorted(values)[int(round(q * (n - 1)))]`, using Python round-to-even. For an even sample size, this selects one middle order statistic.

Generated results are `outputs/rq3/summary.json` and `outputs/rq3/monthly_metrics.csv`; archived reference evidence is under `results/reference/rq3`.

### Monthly figure and interpretation

Figure 7, `fig:governance`, uses `fig_rq3_monthly_metrics_v3.pdf`. For each month and each of its first four panels, average across repositories with valid measurements in both scopes. The final panel takes a PR-level median response time grouped by PR creation month. Headline metrics first average within repositories; monthly metrics average across repositories valid in that month.

Expected direction checks:

- All-known has more active accounts and reviewers and lower HHI in all 17 months.
- k50 is higher in 15 months and equal in two.
- Any-account median response is shorter in all 16 months with valid responses.
- April 2026 has zero valid response observations; response time remains missing.

The repositories and PRs covered vary across months. The curves summarize the current snapshot month by month.

## 6. Result and plotting provenance

Saved expected results are retained under `results/reference/rq1`, `rq2`, and `rq3`, trimmed to final main-experiment fields. Their source basenames identify which historical snapshot supports each result:

| Experiment / artifact | Verified source basename | Source generator basename |
|---|---|---|
| RQ1 graph counts and per-seed agreement | `summary.json` from the saved RQ1 partition export | `paper1_identity_role_factor.py`, `export_rq1_visual_partitions.py` |
| RQ1 global figure | graph pickles and frozen full-graph coordinate cache | `plot_rq1_global_horizontal_v3.py` |
| RQ1 local figure | fixed local node/edge tables and complete-graph memberships | `plot_rq1_local_graph_paper.py`, `plot_rq1_local_horizontal_v2.py` |
| RQ2 accuracy and k curves | `paper1_reviewer_temporal_metrics.csv`, final-test micro rows | `paper1_reviewer_temporal.py`, `plot_reviewer_identity_k_compact_v2.py` |
| RQ2 position fraction and real example | `reviewer_candidate_audit.json`, `reviewer_candidate_audit_example.csv` | `paper1_reviewer_candidate_audit.py`, `plot_reviewer_candidate_lists_v2.py` |
| RQ3 base repository-month records | `governance_repo_month.csv`, known-only snapshot | `paper1_governance_metrics.py` |
| RQ3 headline paired means | `governance_paired_effects_summary.json`, final v2 | `paper1_governance_paired_effects.py` |
| RQ3 monthly PR-level figure data | `monthly_metrics.csv`, final monthly-v3 snapshot | `build_rq3_monthly_metrics_v3.py`, `plot_rq3_monthly_metrics_v3.py` |

The three `run_rq*.py` wrappers are the main experiment entry points; the table records their historical code sources. Frozen plotting inputs are under `data/plot`, and final figure assets are under `figures`. The plotting entry point is:

```sh
python scripts/render_figures.py
# Optional: render selected figures only.
python scripts/render_figures.py --figures 3 4 5 6 7
```

It reads `data/plot/rq1_global`, `data/plot/rq1_local`, `data/plot/rq2_candidates`, `data/plot/rq2_curves.csv`, and `data/plot/rq3_monthly.csv`, and writes `outputs/figures/figure_generation_summary.json`. The plotting entry point redraws the frozen visual inputs, and the three experiment entry points recompute the main numerical results. See the package inventory for individual files.

