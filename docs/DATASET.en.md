# Field-minimized public experimental data

The artifact provides the complete canonical event input used by the three reported research questions. The main reproduction entry point reads the bundled fixed snapshot and runs network construction, RQ1–RQ3, and figure generation locally.

## Files

| File | Rows | Purpose |
|---|---:|---|
| `data/processed/actor_pr_events.parquet` | 4,222,224 | Full event input, in the original row order |
| `data/processed/actor_labels.parquet` | 425,548 | All retained account-type labels, including accounts not involved in the selected PRs |
| `data/processed/release_data_manifest.json` | — | File hashes, sizes, schema, label counts, and export checks |

The events cover 361,296 PRs in 25,402 repositories. Their source nodes include 45,592 account identifiers and six tool-source identifiers. The label table covers the wider AIDev account registry; participating accounts in the experimental network are counted from the event source nodes.

The event input retains all rows, including repeated observations, tool-label records, and records with missing timestamps. Each experiment applies its existing relation, account-scope, and time-selection rules. The export selects the fields required by the experiment scripts and recompresses the Parquet files, preserving the original selected values, nulls, and row order.

## Event schema

| Column | Meaning |
|---|---|
| `pr_id` | Original public PR identifier, stored as an integer |
| `repo_id` | Original public repository identifier, stored as an integer |
| `repo_url` | Original public repository URL |
| `agent` | Original PR tool-source category |
| `source_node` | Original acting-account identifier, or a public tool-source identifier |
| `target_node` | Original `pr:<pr_id>` artifact identifier |
| `source_type` | Original account/provenance type |
| `target_type` | `pull_request` |
| `relation` | Original participation-relation label |
| `event` | Original operation label |
| `event_time` | Original timestamp string or missing value |
| `direct_user_type` | Original source-provided account type, such as `User` or `Bot`, or missing value |
| `evidence_source` | One of eight fixed source-field/table names |

The eight source values are `pull_request.user`, `AIDev.agent`, `pr_comments.parquet`, `pr_reviews.parquet`, `pr_review_comments.parquet`, `pr_commits.parquet`, `pr_timeline.actor`, and `pr_timeline.assignee`.

The account table consists of four original columns: `actor_key`, `login`, `actor_type`, and `actor_subtype`. Its account keys match `source_node` after removing the `actor:` prefix. Public account keys, login names, account types, and subtypes are preserved exactly.

The six public tool-source identifiers are `agent:Claude_Code`, `agent:Copilot`, `agent:Cursor`, `agent:Devin`, `agent:Google_Jules`, and `agent:OpenAI_Codex`. They record PR tool-source categories.

## Unchanged public identifiers and ordering

The inputs derive from public AIDev records. Account keys and login names, PR and repository IDs, repository URLs, and all selected field values are retained in their original form.

Preserving original identifiers and row order also preserves account-string tie-breaking in reviewer rankings, sorted vertex order for Leiden, and edge-insertion order. The export checks every retained event and label column against the canonical source, batch by batch, including original null values and row order.

## Rebuilding the data export

The bundled Parquet files are ready for the experiment scripts. The following optional command recreates them from the canonical inputs:

```sh
python scripts/prepare_release_data.py \
  --events /data/filtered_known/actor_pr_events.parquet \
  --labels /data/filtered_known/actor_labels.parquet \
  --out-dir data/processed
```

The exporter reads explicitly specified input paths and writes results to a separate output directory. The manifest records the data version using filenames, hashes, counts, and schemas; the source files remain unchanged.

## Experiment semantics

- **Role-aware network:** one event node and two directed unit-weight relations per input row. The expected sizes are 45,598 account nodes, 361,296 PR nodes, 4,222,224 event nodes, and 8,444,448 edges. Node and edge files can be reconstructed from the bundled event input.
- **RQ1:** retains author, review, inline-review-comment, and general-comment relations, with the activity criteria specified in the paper and event-count edge weights. The All-known graph has 25,573 account nodes, 268,510 PR nodes, and 546,167 edges; Human-only has 10,808 account nodes, 127,698 PR nodes, and 151,925 edges. Partitions are compared on the 10,808 shared human accounts over the eight seeds specified in the paper.
- **RQ2:** deduplicates each PR–reviewer pair at its earliest valid submitted-review or inline-review-comment timestamp, freezes history at January 1, 2026, and evaluates January–February PRs with an observed human reviewer in the following complete 30-day window. The primary evaluation contains 15,899 PRs in 3,012 repositories. Original account-string tie-breaking and scores are unchanged.
- **RQ3:** counts raw qualifying event rows. The first four metrics use event month; time to first submitted review is grouped by PR creation month. Within each creation month, the response median is computed over valid PR-level waiting times. Quantiles retain the original order-statistic selection and Python rounding rule.

Account-type labels are supplied with the experimental inputs. The original labeling pipeline derives them from existing `user_type` evidence, account-name rules, a tool lexicon, and AIDev account tables. The experiments read these labels directly and compare two account scopes: All-known includes humans, bots, and AI agents, while Human-only retains human accounts.

Source-object counts use commit SHAs and comment/review object IDs from the original tables to count distinct commits, comments, and reviews. The required source files are listed in [UPSTREAM_SOURCES.md](UPSTREAM_SOURCES.md).
