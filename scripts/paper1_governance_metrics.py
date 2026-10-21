#!/usr/bin/env python3
"""Role-aware governance/health measurement audit for Paper 1.

This is a descriptive measurement experiment.  It treats the AIDev-derived
labels as working truth and performs a complete-case analysis: events whose
actor type is ``unknown`` or unresolved are removed before aggregation.  It
compares a naive all-known-account view with human-only and typed activity and
does not estimate causal effects on community health.

Inputs are the compact actor_pr_events network and actor_labels table.  We
exclude the synthetic ``agent_authored``/``llm_agent_label`` rows from account
activity; those rows are reported separately as AI-label exposure.  Review
concentration uses raw ``review`` and ``review_comment`` interactions, while
response time uses formal ``review`` events and is grouped by PR-open month.
Activity and concentration are row-based measurements: compact-network rows
are assigned unit weight (synthetic label rows are excluded), so repeated
export rows contribute multiplicity. Response time keeps the earliest valid
formal-review timestamp per PR. This is intentionally different from the
Reviewer replay, which deduplicates PR--reviewer pairs.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, platform, statistics, subprocess, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pyarrow.parquet as pq

KNOWN_NONHUMAN = {"llm_agent_account", "automation_bot", "service_account", "organization"}
KNOWN_TYPES = KNOWN_NONHUMAN | {"human_user"}
ROLE_ORDER = ("human", "known_nonhuman")
REVIEW_RELATIONS = {"review", "review_comment"}
META_RELATIONS = {"agent_authored"}
UTC = timezone.utc

def norm(v: Any) -> str:
    return "" if v is None else str(v).strip()

def parse_ts(v: Any) -> float | None:
    s = norm(v)
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except (TypeError, ValueError, OverflowError): return None

def month(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m") if ts is not None else None

def batches(path: Path, cols: list[str], size: int = 131072):
    for b in pq.ParquetFile(path).iter_batches(batch_size=size, columns=cols, use_threads=False):
        yield b.to_pydict()

def role(stype: str) -> str:
    stype = norm(stype)
    if stype == "human_user": return "human"
    if stype in KNOWN_NONHUMAN: return "known_nonhuman"
    return "unknown"


def resolve_type(source: str, stype: str, actor_types: dict[str, str]) -> str:
    value = norm(stype)
    if not value and source.startswith("actor:"):
        value = actor_types.get(source[6:], "")
    return value

def hhi(counter: Counter) -> float | None:
    n = sum(counter.values())
    return sum((v / n) ** 2 for v in counter.values()) if n else None

def top_share(counter: Counter, k: int = 3) -> float | None:
    n = sum(counter.values())
    return sum(sorted(counter.values(), reverse=True)[:k]) / n if n else None

def bus_factor50(counter: Counter) -> int | None:
    n = sum(counter.values())
    if not n: return None
    target = 0.5 * n
    cur = 0
    for i, v in enumerate(sorted(counter.values(), reverse=True), 1):
        cur += v
        if cur >= target: return i
    return len(counter)

def quant(vals: list[float], q: float) -> float | None:
    if not vals: return None
    a = sorted(vals); idx = min(len(a)-1, max(0, int(round(q*(len(a)-1)))))
    return float(a[idx])

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20), b""): h.update(b)
    return h.hexdigest()

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--network", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args=ap.parse_args(); out=args.out_dir; out.mkdir(parents=True, exist_ok=True)
    # Read actor labels both for provenance and to resolve blank source_type
    # values. Unknown labels are not used as a role.
    actor_label_counts=Counter()
    actor_types={}
    for b in batches(args.labels,["actor_type"],65536):
        actor_label_counts.update(norm(x) or "unknown" for x in b["actor_type"])
    for b in batches(args.labels,["actor_key","actor_type"],65536):
        for key, typ in zip(b["actor_key"], b["actor_type"]):
            if norm(key) and norm(typ) in KNOWN_TYPES:
                actor_types[norm(key)] = norm(typ)
    prs={}  # pr_id -> repo_id, repo_url, created timestamp
    malformed=Counter()
    cols=["pr_id","repo_id","repo_url","source_node","source_type","relation","event_time"]
    # Pass 1: PR creation rows.
    for b in batches(args.network, cols):
        for pid,rid,url,src,stype,rel,when in zip(*(b[c] for c in cols)):
            if norm(rel)!="author": continue
            try: pid=int(pid); rid=int(rid)
            except (TypeError,ValueError): malformed["invalid_author_id"]+=1; continue
            ts=parse_ts(when)
            stype=resolve_type(norm(src), norm(stype), actor_types)
            if stype not in KNOWN_TYPES:
                malformed["unknown_author_dropped"]+=1
                continue
            if ts is None: malformed["author_missing_time"]+=1; continue
            prs.setdefault(pid,(rid,norm(url),ts))
    # Per repo-month state. Sets are role-separated, avoiding double counting.
    st={}
    def get(key):
        if key not in st:
            st[key]={"repo_id":key[0],"month":key[1],"repo_url":"","events":Counter(),"active":{r:set() for r in ROLE_ORDER},"reviewers":{r:set() for r in ROLE_ORDER},"review_counts":{r:Counter() for r in ROLE_ORDER},"first_review_all":[],"first_review_human":[],"pr_ids":set(),"ai_label_rows":0}
        return st[key]
    first_all={}; first_human={}
    # Pass 2: account activity, review concentration, response-time evidence.
    for b in batches(args.network, cols):
        for pid_raw,rid_raw,url,src_raw,stype_raw,rel_raw,when_raw in zip(*(b[c] for c in cols)):
            rel=norm(rel_raw); src=norm(src_raw); stype=norm(stype_raw); ts=parse_ts(when_raw)
            try: pid=int(pid_raw); rid=int(rid_raw)
            except (TypeError,ValueError): malformed["invalid_event_id"]+=1; continue
            if rel in META_RELATIONS or stype=="llm_agent_label":
                if ts is not None:
                    k=(rid,month(ts)); get(k)["ai_label_rows"]+=1
                continue
            if not src or ts is None: malformed["event_missing_source_or_time"]+=1; continue
            stype=resolve_type(src, stype, actor_types)
            if stype not in KNOWN_TYPES:
                malformed["unknown_event_dropped"]+=1; continue
            m=month(ts); key=(rid,m); x=get(key); x["repo_url"] = norm(url) or x["repo_url"]
            rr=role(stype); x["events"][rr]+=1; x["active"][rr].add(src)
            if rel=="author": x["pr_ids"].add(pid)
            if rel in REVIEW_RELATIONS:
                x["reviewers"][rr].add(src); x["review_counts"][rr][src]+=1
            if rel=="review":
                pr=prs.get(pid)
                if pr is not None and ts>=pr[2]:
                    delta=(ts-pr[2])/3600.0
                    if pid not in first_all or ts<first_all[pid]: first_all[pid]=ts
                    if rr=="human" and (pid not in first_human or ts<first_human[pid]): first_human[pid]=ts
    # Response-time lists grouped by PR creation month (same denominator for models).
    resp=defaultdict(lambda:{"all":[],"human":[]})
    for pid,(rid,url,created) in prs.items():
        cm=month(created)
        if pid in first_all: resp[(rid,cm)]["all"].append((first_all[pid]-created)/3600.0)
        if pid in first_human: resp[(rid,cm)]["human"].append((first_human[pid]-created)/3600.0)
    rows=[]
    for key,x in sorted(st.items()):
        rid,m=key; row={"repo_id":rid,"repo_url":x["repo_url"],"month":m,"pr_count":len(x["pr_ids"]),"ai_label_rows":x["ai_label_rows"]}
        total=sum(x["events"].values()); row["event_count_all"]=total
        for r in ROLE_ORDER:
            row[f"active_accounts_{r}"]=len(x["active"][r]); row[f"event_count_{r}"]=x["events"][r]
            row[f"activity_share_{r}"]=x["events"][r]/total if total else None
            row[f"reviewer_count_{r}"]=len(x["reviewers"][r]); row[f"review_event_count_{r}"]=sum(x["review_counts"][r].values())
            row[f"review_hhi_{r}"]=hhi(x["review_counts"][r]); row[f"review_top3_share_{r}"]=top_share(x["review_counts"][r]); row[f"review_bus_factor50_{r}"]=bus_factor50(x["review_counts"][r])
        row["active_accounts_all"]=sum(row[f"active_accounts_{r}"] for r in ROLE_ORDER)
        row["reviewer_count_all"]=sum(row[f"reviewer_count_{r}"] for r in ROLE_ORDER)
        row["review_event_count_all"]=sum(row[f"review_event_count_{r}"] for r in ROLE_ORDER)
        all_review_counts=Counter()
        for r in ROLE_ORDER: all_review_counts.update(x["review_counts"][r])
        row["review_hhi_all"]=hhi(all_review_counts); row["review_top3_share_all"]=top_share(all_review_counts); row["review_bus_factor50_all"]=bus_factor50(all_review_counts)
        rv=resp.get(key,{"all":[],"human":[]})
        row["response_n_all"]=len(rv["all"]); row["response_median_hours_all"]=quant(rv["all"],.5); row["response_p75_hours_all"]=quant(rv["all"],.75)
        row["response_n_human"]=len(rv["human"]); row["response_median_hours_human"]=quant(rv["human"],.5); row["response_p75_hours_human"]=quant(rv["human"],.75)
        rows.append(row)
    fields=list(rows[0].keys()) if rows else []
    with (out/"governance_repo_month.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    # Aggregate monthly and repo-level views, with weighted activity shares and median across groups.
    def agg(group_key):
        groups=defaultdict(list)
        for r in rows: groups[r[group_key]].append(r)
        outrows=[]
        for g,rr in sorted(groups.items(),key=lambda kv:str(kv[0])):
            z={group_key:g,"repo_months":len(rr),"repos":len({int(q["repo_id"]) for q in rr}),"pr_count":sum(int(q["pr_count"]) for q in rr),"active_accounts_sum":sum(int(q["active_accounts_all"]) for q in rr)}
            total_events=sum(int(q["event_count_all"]) for q in rr)
            total_reviews=sum(int(q["review_event_count_all"]) for q in rr)
            for rolekey in ROLE_ORDER:
                z[f"event_count_{rolekey}"]=sum(int(q[f"event_count_{rolekey}"]) for q in rr); z[f"activity_share_{rolekey}"]=z[f"event_count_{rolekey}"]/total_events if total_events else None
                z[f"reviewer_count_{rolekey}_median"]=quant([float(q[f"reviewer_count_{rolekey}"]) for q in rr],.5)
                z[f"review_hhi_{rolekey}_median"]=quant([float(q[f"review_hhi_{rolekey}"]) for q in rr if q[f"review_hhi_{rolekey}"] is not None],.5)
                z[f"review_bus_factor50_{rolekey}_median"]=quant([float(q[f"review_bus_factor50_{rolekey}"]) for q in rr if q[f"review_bus_factor50_{rolekey}"] is not None],.5)
            z["review_event_count_all"]=total_reviews; z["reviewer_count_all_median"]=quant([float(q["reviewer_count_all"]) for q in rr],.5)
            for typ in ["all","human"]:
                vals=[float(q[f"response_median_hours_{typ}"]) for q in rr if q[f"response_median_hours_{typ}"] is not None]
                z[f"response_median_hours_{typ}_repo_median"]=quant(vals,.5)
            outrows.append(z)
        return outrows
    monthly=agg("month"); repo=agg("repo_id")
    # Correct repo-level response statistics from the PR-open-month denominator,
    # rather than the event-month rows used for activity metrics.
    rrepo=defaultdict(lambda:{"all":[],"human":[]})
    for (rid,cm), vals in resp.items():
        rrepo[rid]["all"].extend(vals["all"]); rrepo[rid]["human"].extend(vals["human"])
    for q in repo:
        rv=rrepo[int(q["repo_id"])]
        q["response_median_hours_all_repo_median"]=quant(rv["all"],.5)
        q["response_median_hours_human_repo_median"]=quant(rv["human"],.5)
    # Response-time view is grouped by PR-open month (its own denominator),
    # rather than event month. This avoids assigning a review to a month after
    # the PR was opened.
    response_rows=[]
    for (rid,cm), vals in sorted(resp.items(), key=lambda kv:(kv[0][0], kv[0][1])):
        response_rows.append({"repo_id":rid,"month":cm,"n_all":len(vals["all"]),"median_hours_all":quant(vals["all"],.5),"p75_hours_all":quant(vals["all"],.75),"n_human":len(vals["human"]),"median_hours_human":quant(vals["human"],.5),"p75_hours_human":quant(vals["human"],.75)})
    with (out/"governance_response_open_month.csv").open("w",newline="",encoding="utf-8") as f:
        rf=list(response_rows[0].keys()) if response_rows else ["repo_id","month","n_all","median_hours_all","p75_hours_all","n_human","median_hours_human","p75_hours_human"]
        csv.DictWriter(f,fieldnames=rf).writeheader(); csv.DictWriter(f,fieldnames=rf).writerows(response_rows)
    # Add correctly grouped response medians to the monthly table.
    rmonth=defaultdict(lambda:{"all":[],"human":[]})
    for q in response_rows:
        if q["median_hours_all"] is not None: rmonth[q["month"]]["all"].extend([float(q["median_hours_all"])])
        if q["median_hours_human"] is not None: rmonth[q["month"]]["human"].extend([float(q["median_hours_human"])])
    for q in monthly:
        q["response_median_hours_all_repo_median"] = quant(rmonth[q["month"]]["all"], .5)
        q["response_median_hours_human_repo_median"] = quant(rmonth[q["month"]]["human"], .5)
    for name,data in [("governance_monthly.csv",monthly),("governance_repo_summary.csv",repo)]:
        fs=list(data[0].keys()) if data else []
        with (out/name).open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=fs).writeheader(); csv.DictWriter(f,fieldnames=fs).writerows(data)
    # Summary statistics are deliberately descriptive and report denominators.
    def weighted_share(rolekey):
        den=sum(int(r["event_count_all"]) for r in rows); num=sum(int(r[f"event_count_{rolekey}"]) for r in rows); return num/den if den else None
    summary={"assumption":"AIDev native/derived labels are working truth; unknown or unresolved rows are excluded before aggregation; no manual gold labels used.","scope":{"repo_month_rows":len(rows),"repos":len({r['repo_id'] for r in rows}),"months":len({r['month'] for r in rows}),"prs_with_author_rows":len(prs),"network_event_rows":sum(sum(x['events'].values()) for x in st.values())},"actor_label_counts":dict(actor_label_counts),"weighted_activity_share":{"human":weighted_share('human'),"known_nonhuman":weighted_share('known_nonhuman')},"monthly":monthly,"files":{"network":str(args.network),"labels":str(args.labels)},"malformed":dict(malformed),"unknown_policy":"drop unknown or unresolved author/event rows"}
    # Compact headline distributions for paper tables.
    for r in ROLE_ORDER:
        vals=[float(x[f"active_accounts_{r}"]) for x in rows]
        summary[f"repo_month_active_accounts_{r}"]={"median":quant(vals,.5),"p90":quant(vals,.9),"mean":statistics.fmean(vals) if vals else None}
    for metric in ["review_hhi_all","review_hhi_human","review_top3_share_all","review_top3_share_human","review_bus_factor50_all","review_bus_factor50_human"]:
        vals=[float(x[metric]) for x in rows if x.get(metric) is not None]
        summary[metric]={"n":len(vals),"median":quant(vals,.5),"p90":quant(vals,.9)}
    all_resp=[v for z in resp.values() for v in z["all"]]
    human_resp=[v for z in resp.values() for v in z["human"]]
    summary["response_time_hours"]={"all":{"n":len(all_resp),"median":quant(all_resp,.5),"p75":quant(all_resp,.75),"p90":quant(all_resp,.9)},"human":{"n":len(human_resp),"median":quant(human_resp,.5),"p75":quant(human_resp,.75),"p90":quant(human_resp,.9)}}
    (out/"governance_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    commit=""
    try: commit=subprocess.check_output(["git","rev-parse","HEAD"],text=True,stderr=subprocess.DEVNULL).strip()
    except Exception: pass
    manifest={"script":"paper1_governance_metrics.py","command":" ".join(sys.argv),"python":sys.version,"platform":platform.platform(),"git_commit":commit,"inputs":{"network_sha256":sha256(args.network),"labels_sha256":sha256(args.labels)},"definition":{"account_activity":"all known-type network rows except synthetic agent_authored/llm_agent_label rows","review_concentration":"raw review+review_comment source events","response_time":"first formal review minus PR creation; grouped by PR-open month","event_weight":"one per compact-network row; repeated export rows contribute multiplicity","event_grouping_key_fields":["repo_id","pr_id","relation","event","source_node","target_node","event_time"],"event_id_semantics":"The compact grouping key is not a unique semantic event ID; counts retain compact-row multiplicity.","reviewer_pair_dedup":"not applied; concentration counts raw rows","response_time_dedup":"earliest valid formal-review timestamp per PR","unknown":"dropped before aggregation"}}
    (out/"governance_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    md=[]; md.append("# Governance and community-health measurement audit (E5)\n")
    md.append("本实验将 AIDev 原始/派生标签视为工作真值；unknown 或无法解析身份的行在聚合前清理。结果是描述性测量审计，不用于因果健康结论。")
    md.append(f"\n- repo-month rows: **{len(rows):,}**; repositories: **{len({r['repo_id'] for r in rows}):,}**; PRs with author rows: **{len(prs):,}**")
    md.append("- 活动事件按 role 汇总，排除 synthetic `agent_authored` 标签行；AI 标签行另计。")
    md.append("\n## Weighted activity composition\n")
    md.append("|role|event share|")
    md.append("|---|---:|")
    for r in ROLE_ORDER: md.append(f"|{r}|{weighted_share(r):.4f}|")
    md.append("\n## Interpretation boundary\n")
    md.append("这些差异说明将非人类节点并入普通开发者会改变活跃账号、reviewer 数量、集中度和响应时间的测量口径；它们不证明 AI 导致社区健康变化，也不等同于项目风险预测。正式论文应报告覆盖范围、时间窗口、事件定义和 complete-case 清理规则，并把人工金样本作为后续验证。")
    (out/"governance_summary.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print(json.dumps({"rows":len(rows),"prs":len(prs),"out":str(out),"weighted_activity_share":summary["weighted_activity_share"]},ensure_ascii=False))
if __name__ == "__main__": main()
