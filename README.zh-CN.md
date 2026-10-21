# 角色感知协作网络中的账号范围

[English documentation](README.md)

本材料对应论文 **Auditing Account Scope in Collaboration Measurements via Role-Aware Networks**，收录最终保留的三个实验：社区成员关系（RQ1）、审阅人候选排序（RQ2）、项目协作与维护指标（RQ3），包括数据、可运行代码、参考结果及绘图代码。

主复现路线从包内固定的 AIDev 选定事件快照开始，保留原始公开账号、PR 和仓库标识。

## 材料清单

| 目录或文件 | 内容 |
|---|---|
| `data/processed/` | 全部 4,222,224 条选定事件、425,548 行账号类型注册表，以及数据结构和哈希清单 |
| `data/plot/` | 五张最终实验图的最小输入：两个已保存的图、共享坐标、局部案例、公开候选列表案例和汇总表 |
| `scripts/build_role_aware_network.py` | 流式生成账号—事件—PR 节点及有向关系 |
| `scripts/run_rq1.py` | 两种账号范围、事件单位权重、八种子的 Leiden 社区对比 |
| `scripts/run_rq2.py` | 固定历史截止时间的仓库频次排序及全量合格测试 PR 评价 |
| `scripts/run_rq3.py` | 配对仓库统计及五项指标的逐月序列 |
| `scripts/render_figures.py` | 从保存的输入重画图 3—7 |
| `scripts/upstream/` | 可选的原始下载、标签生成、事件构建、过滤及规模统计代码 |
| `results/reference/` | 用于核对新执行结果的原始主实验参考结果 |
| `figures/` | 实验图的 PDF、PNG、SVG 参考文件 |
| `validation/` | 全量重跑的数值核验及绘图核验记录 |
| `environment/` | 验证时使用的软件包版本 |

账号类型注册表的范围大于选定事件涉及的账号范围。事件图实际涉及 45,592 个账号标识，以及 6 个工具来源标识，共 45,598 个账号类节点。

## 安装环境

使用 Python 3.11，按 `requirements.txt` 安装验证时使用的版本：

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

下列命令均在仓库根目录执行。主路线所需输入已经包含在包内；新生成的文件写入 `outputs/`。

## 核验、重跑和绘图

核对待发布文件清单、SHA-256、数据规模及发布内容：

```sh
python scripts/reproduce.py --stage verify
```

执行构图、三个全量实验、数值对照和绘图：

```sh
python scripts/reproduce.py --stage all
```

也可以分步执行：

```sh
python scripts/reproduce.py --stage graph
python scripts/reproduce.py --stage rq1
python scripts/reproduce.py --stage rq2
python scripts/reproduce.py --stage rq3
python scripts/reproduce.py --stage check
python scripts/reproduce.py --stage figures
```

RQ1 必须先构图；RQ2、RQ3 直接读取同一批选定事件。只想快速查看图的生成效果，可执行：

```sh
python scripts/render_figures.py --out-dir outputs/figures
```

所有步骤使用 CPU。构图和社区分析需要在内存中保存较大的结构。全量复现会在 `outputs/` 中额外生成图、表和图片。包内记录了验证环境和核验结果。

## 主要结果与核验

| 对比 | 参考结果 |
|---|---|
| RQ1，10,808 个共同人类账号 | 八种子 NMI `0.7572 ± 0.0039`，ARI `0.1017 ± 0.0024` |
| RQ2，15,899 个 PR、3,012 个仓库 | 全账号／仅人类的 MRR@10 为 `0.4323 / 0.4925`；全账号实际返回的前十候选位置中，非人类占 `23,348 / 81,576 = 28.62%` |
| RQ3，配对仓库均值 | 全账号减仅人类：活跃账号 `+0.7780`、审阅人数 `+0.2720`、HHI `−0.1901`、审阅活动 k50 `+0.1566` |
| RQ3，得到响应的 PR | 首次提交审阅的小时中位数为 `0.5267 / 1.3539`，分别对应 `83,074 / 59,694` 个 PR |

已使用全量数据重跑，并与归档的最终实验结果核对；逐项记录见 `validation/reproduction_checks.json`。

## 详细说明

- [实验方法、参数、精确参考值和图表对应关系](docs/EXPERIMENTS.zh-CN.md)
- [数据结构、规模、原始公开标识及字段选择](docs/DATASET.zh-CN.md)
- [上游来源、归属说明和可选原始重建路线](docs/UPSTREAM_SOURCES.md)
- [代码来源记录](docs/CODE_PROVENANCE.json)
- [论文快照及规模清单](docs/STUDY_SNAPSHOT.json)
- [数据与第三方材料说明](NOTICE.md)

## 公开数据与发布范围

AIDev 是公开数据集。本包保留原始公开账号标识、GitHub 用户名、PR 和仓库标识及仓库 URL。导出只选取实验需要的字段，保留原字段值和行序。

发布范围限于实验所需的数据字段、代码、文档和结果。凭据、机器配置、本机文件路径、执行日志、Git 历史、审阅与评论正文以及完整个人资料均排除在外。

本包提供复现本文主结果的固定事件快照。原始 commit、comment 等对象的去重数量以汇总清单保留；全量 AIDev 原始表由上游提供。
