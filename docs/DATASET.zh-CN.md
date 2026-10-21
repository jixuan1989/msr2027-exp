# 保留公开标识的精简实验数据说明

本包提供正文三个研究问题所使用的完整规范事件输入。主复现入口读取包内固定快照，在本地执行网络构建、RQ1—RQ3 实验和绘图。

## 数据文件

| 文件 | 行数 | 用途 |
|---|---:|---|
| `data/processed/actor_pr_events.parquet` | 4,222,224 | 保持原始行序的完整事件输入 |
| `data/processed/actor_labels.parquet` | 425,548 | 全部保留账号类型标签，包括未参与所选 PR 的账号 |
| `data/processed/release_data_manifest.json` | — | 文件哈希、字节数、模式、标签规模与导出核验结果 |

事件涉及 25,402 个仓库和 361,296 个 PR；其中执行节点包含 45,592 个账号标识和 6 个工具来源标识。标签表覆盖范围更大的 AIDev 账号登记表，实验网络的参与账号规模按事件中的执行节点统计。

事件输入保留全部行，包括重复观测、工具标签记录及时间缺失记录。各实验按原有规则选择关系、账号范围和时间。导出过程裁剪实验所需字段并重新压缩 Parquet，保留所选字段的原值、空值和行序。

## 事件字段

| 字段 | 含义 |
|---|---|
| `pr_id` | 原始公开 PR 整数标识 |
| `repo_id` | 原始公开仓库整数标识 |
| `repo_url` | 原始公开仓库 URL |
| `agent` | PR 的原始工具来源类别 |
| `source_node` | 原始执行账号标识，或公开工具来源标识 |
| `target_node` | 原始 `pr:<pr_id>` 工件标识 |
| `source_type` | 原有账号或来源类型 |
| `target_type` | `pull_request` |
| `relation` | 原始参与关系标签 |
| `event` | 原始操作标签 |
| `event_time` | 原时间字符串或缺失值 |
| `direct_user_type` | 原来源表提供的账号类型，如 `User`、`Bot` 或缺失值 |
| `evidence_source` | 八种固定表名或字段名之一 |

八种来源枚举为：`pull_request.user`、`AIDev.agent`、`pr_comments.parquet`、`pr_reviews.parquet`、`pr_review_comments.parquet`、`pr_commits.parquet`、`pr_timeline.actor`、`pr_timeline.assignee`。

账号类型表由原始的 `actor_key`、`login`、`actor_type`、`actor_subtype` 四列组成。`actor_key` 与事件 `source_node` 去掉 `actor:` 前缀后对应；公开账号标识、账号名、类型及子类型的值均保持不变。

六个公开工具来源标识为 `agent:Claude_Code`、`agent:Copilot`、`agent:Cursor`、`agent:Devin`、`agent:Google_Jules`、`agent:OpenAI_Codex`，用于记录 PR 的工具来源类别。

## 保持公开标识和原始顺序

数据源自公开的 AIDev 记录。本包保留原始账号标识及账号名、PR 和仓库 ID、仓库 URL，以及所有所选字段的原值。

保持原始标识和行序，也就保持了审阅人推荐中的账号字符串同分排序、Leiden 的顶点排序和边插入顺序。导出后逐列逐批对照规范源文件，核验所有保留事件与标签字段、原始空值和行序均完全一致。

## 可选的导出重建

包内 Parquet 可直接用于实验。若持有规范输入，可选用以下命令重新生成：

```sh
python scripts/prepare_release_data.py \
  --events /data/filtered_known/actor_pr_events.parquet \
  --labels /data/filtered_known/actor_labels.parquet \
  --out-dir data/processed
```

脚本使用显式指定的输入路径，将结果写入独立的输出目录。manifest 通过文件名、哈希、规模和模式记录数据版本；源文件保持原样。

## 实验口径

- **角色感知网络：** 每条输入记录生成一个事件节点和两条权重为 1 的有向边，预期为 45,598 个账号类节点、361,296 个 PR 节点、4,222,224 个事件节点、8,444,448 条边。节点和边文件可由包内事件输入重建。
- **RQ1：** 按正文活跃条件保留作者、正式审阅、行级评论及普通评论关系，边权为事件次数。全账号图含 25,573 个账号、268,510 个 PR 和 546,167 条边；仅人类图含 10,808 个账号、127,698 个 PR 和 151,925 条边。按正文八个种子运行，在共同 10,808 个人类账号上比较分区。
- **RQ2：** 每个 PR—审阅人组合保留最早的有效正式审阅或行级评论时间，历史冻结在 2026 年 1 月 1 日，评价 2026 年 1—2 月创建且随后完整 30 天中观察到人类审阅人的 PR。主要评价包含 3,012 个仓库中的 15,899 个 PR。原有账号字符串同分排序与评分均保持不变。
- **RQ3：** 按原始有效事件行计数。前四项指标按事件月份计算，首次正式审阅等待时间按 PR 创建月份归组。在每个 PR 创建月份内，对有效 PR 级等待时间取中位数；分位数沿用原有次序统计量与 Python 的取整规则。

账号类型标签随实验输入一同提供，由原标签管线依据已有 `user_type`、账号命名规则、工具词典和 AIDev 账号表生成。实验直接读取这些标签，比较全账号与仅人类两种账号范围：全账号包含人类、机器人和 AI 代理，仅人类范围保留人类账号。

源对象规模统计读取原始表中的 commit SHA 和评论／审阅对象 ID，计算去重 commit、评论和审阅对象的数量。所需原始文件见 [UPSTREAM_SOURCES.md](UPSTREAM_SOURCES.md)。
