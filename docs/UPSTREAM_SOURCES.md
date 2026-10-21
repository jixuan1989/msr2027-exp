# Upstream sources and optional reconstruction

The main RQ1–RQ3 reproduction reads the bundled fixed snapshot of public event and account-type tables. The upstream pipeline below prepares event and account-label tables from AIDev and supports source-object counts.

## Official source

- Dataset: [hao-li/AIDev-7.6M on Hugging Face](https://huggingface.co/datasets/hao-li/AIDev-7.6M).
- Metadata API: [official dataset metadata](https://huggingface.co/api/datasets/hao-li/AIDev-7.6M).
- Current upstream revision observed on **2026-10-21**: `b3a1ad2372686526392c7c0abd104fef0606d38d`.
- [Revision-specific file tree](https://huggingface.co/datasets/hao-li/AIDev-7.6M/tree/b3a1ad2372686526392c7c0abd104fef0606d38d).
- Download URL pattern: `https://huggingface.co/datasets/hao-li/AIDev-7.6M/resolve/<revision>/<filename>?download=true`.

At the revision observed on 2026-10-21, the official API lists 13 Parquet tables totaling **22,362,540,242 bytes** (22.36 GB in decimal units). The historical downloader used mutable `main`, and the historical upstream Git revision is unrecorded. The bundled canonical inputs and their hashes identify the fixed experimental snapshot.

The current official repository contains `all_pull_request.parquet`, `all_user.parquet`, `all_repository.parquet`, `pull_request.parquet`, `repository.parquet`, `issue.parquet`, `related_issue.parquet`, `pr_comments.parquet`, `pr_reviews.parquet`, `pr_review_comments.parquet`, `pr_commits.parquet`, `pr_commit_details.parquet`, and `pr_timeline.parquet`. The event builder uses the enriched `pull_request.parquet` and related activity tables; the labeling stage also reads the larger `all_pull_request.parquet` and `all_user.parquet`. The enriched and larger PR tables cover different scopes within AIDev.

## License and attribution

The [official dataset card](https://huggingface.co/datasets/hao-li/AIDev-7.6M) and official metadata API identify the dataset license as **CC BY 4.0**. See the [license text](https://creativecommons.org/licenses/by/4.0/) for its attribution and notice conditions. When distributing derived data, retain attribution to AIDev and describe the export: it selects the experiment fields while preserving original public identifiers, account classifications, and event semantics.

Dataset citation: Hao Li, Haoxiang Zhang, and Ahmed E. Hassan, *AIDev: Studying AI Coding Agents on GitHub*, MSR 2026, [DOI](https://doi.org/10.1145/3793302.3797249). The paper's citation should be retained alongside the dataset URL and license notice.

## Optional full upstream pipeline

The development pipeline was:

1. Download AIDev tables with `download_aidev.py`, which supports parallel workers, segmented/resumable downloads, and a progress log. For an archival run, specify the official endpoint and an immutable revision.
2. Build account and PR labels with `build_aidev_labels.py`. PR tool labels and account types are distinct. The script uses provided `user_type` evidence, account-name rules, a tool lexicon, and the source account tables, and writes ambiguous accounts to a review queue.
3. Build the actor–PR event table with `build_aidev_network.py`, using `pull_request.parquet` plus comments, submitted reviews, inline comments, commits, and timeline actor/assignee records.
4. Filter records with unresolved account type using `paper1_filter_unknown.py`, producing the canonical 4,222,224-row event input and retained account-type registry.
5. Apply the release export described in [DATASET.en.md](DATASET.en.md), or use the already bundled release tables directly.
6. Construct the role-aware network with `build_role_aware_network.py`, then run the task-specific experiments and plots. RQ1 reads the saved role-aware edge table; the historical RQ2 and RQ3 implementations read the same canonical event table directly with their stated task-selection rules.

Source-object counts read commit SHAs and comment/review IDs from the original tables. The main reproduction entry point uses the bundled fixed event snapshot.

## Upstream script dependency closure

The optional preparation scripts are kept under `scripts/upstream/`:

| Script | Python dependency | Inputs or parameters |
|---|---|---|
| `download_aidev.py` | Standard library | Repository, revision, endpoint, and download settings are CLI arguments |
| `build_aidev_labels.py` | `pyarrow` | `AGENT_NAMES`, `LLM_ACCOUNT_PATTERNS`, and `SERVICE_PATTERNS` are explicit constants in this file |
| `build_aidev_network.py` | `pyarrow` | The account label Parquet produced by the preceding stage |
| `paper1_filter_unknown.py` | `pyarrow` | The label and event Parquet files produced by the preceding stages |

The preparation scripts run locally with the `pyarrow` version specified by the experiment environment. They use CLI parameters, rule constants defined in code, and Parquet outputs from preceding stages.

The original account-labeling scope covers ten tables: `all_pull_request.parquet`, `all_user.parquet`, `pull_request.parquet`, `issue.parquet`, `pr_comments.parquet`, `pr_reviews.parquet`, `pr_review_comments.parquet`, `pr_commits.parquet`, `pr_commit_details.parquet`, and `pr_timeline.parquet`. The event builder reads `pull_request.parquet`, the three PR comment/review tables, `pr_commits.parquet`, and `pr_timeline.parquet`; the remaining label-scanning tables contribute to the account registry. Repository and related-issue tables support additional source-data inventory checks.

Example commands, using an external work directory for the larger raw/intermediate files:

```sh
python scripts/upstream/download_aidev.py \
  --repo hao-li/AIDev-7.6M \
  --revision b3a1ad2372686526392c7c0abd104fef0606d38d \
  --endpoint https://huggingface.co --workers 3 --segments 4 \
  --out-dir /data/aidev-work/raw \
  --only all_pull_request.parquet all_user.parquet pull_request.parquet \
    issue.parquet pr_comments.parquet pr_reviews.parquet \
    pr_review_comments.parquet pr_commits.parquet \
    pr_commit_details.parquet pr_timeline.parquet

python scripts/upstream/build_aidev_labels.py \
  --data-dir /data/aidev-work/raw --out-dir /data/aidev-work/labels

python scripts/upstream/build_aidev_network.py \
  --data-dir /data/aidev-work/raw --labels-dir /data/aidev-work/labels \
  --out-dir /data/aidev-work/network

python scripts/upstream/paper1_filter_unknown.py \
  --labels-dir /data/aidev-work/labels \
  --network /data/aidev-work/network/actor_pr_events.parquet \
  --out-dir /data/aidev-work/filtered_known

python scripts/prepare_release_data.py \
  --events /data/aidev-work/filtered_known/actor_pr_events.parquet \
  --labels /data/aidev-work/filtered_known/actor_labels.parquet \
  --out-dir /data/aidev-work/release-check
```

These commands use the revision observed on 2026-10-21 and store raw tables, intermediate results, and the export check in the external work directory. The main reproduction reads the bundled fixed snapshot. The release export retains original public identifiers and URLs in the selected fields.
