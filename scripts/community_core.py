"""Community construction and Leiden functions used by the final RQ1.

Extracted from the study implementation; only unit event weights are used.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import igraph as ig
import leidenalg
import pyarrow.parquet as pq
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

KNOWN_TYPES = {
    "human_user",
    "llm_agent_account",
    "automation_bot",
    "service_account",
    "organization",
}


RELATIONS = {"author", "review", "review_comment", "comment"}


SEEDS_DEFAULT = (0, 1, 2, 3, 4, 42, 123, 2024)


def norm(x: Any) -> str:
    return "" if x is None else str(x).strip()


def batches(path: Path, columns: list[str], size: int = 131_072):
    for batch in pq.ParquetFile(path).iter_batches(
        batch_size=size, columns=columns, use_threads=False
    ):
        yield batch.to_pydict()


def load_edges(path: Path):
    cols = ["edge_type", "pr_id", "src_id", "source_type", "relation", "role"]
    role_counts: Counter[str] = Counter()
    rows: list[tuple[str, str, str, str]] = []
    for d in batches(path, cols):
        for edge_type, pid, src, stype, relation, role in zip(*(d[c] for c in cols)):
            edge_type, src, stype, relation, role = map(norm, (edge_type, src, stype, relation, role))
            if edge_type != "participates_as" or not src or stype not in KNOWN_TYPES or relation not in RELATIONS:
                continue
            role = role or relation
            src_key = src if src.startswith("actor:") else f"actor:{src}"
            rows.append((src_key, f"pr:{int(pid)}", stype, role, relation))
            role_counts[role] += 1
    return rows, role_counts


def make_edges(rows, role_counts, allowed, balanced):
    n_roles = len(role_counts)
    weights: Counter[tuple[str, str]] = Counter()
    for actor, pr, stype, role, _relation in rows:
        if stype not in allowed:
            continue
        w = n_roles / role_counts[role] if balanced else 1.0
        weights[(actor, pr)] += w
    return weights


def make_graph(edges: Counter[tuple[str, str]]):
    nodes = sorted({x for pair in edges for x in pair})
    idx = {n: i for i, n in enumerate(nodes)}
    tuples = [(idx[u], idx[v]) for u, v in edges]
    g = ig.Graph(n=len(nodes), edges=tuples, directed=False)
    g.vs["name"] = nodes
    g.vs["node_type"] = ["account" if n.startswith("actor:") else "pull_request" for n in nodes]
    g.es["weight"] = [float(edges[e]) for e in edges]
    return g, nodes


def leiden(g: ig.Graph, seed: int):
    part = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition, weights=g.es["weight"], seed=seed)
    return list(part.membership)


def account_partition(nodes, membership):
    return {n: int(membership[i]) for i, n in enumerate(nodes) if n.startswith("actor:")}


def summarize(nodes, membership):
    ap = account_partition(nodes, membership)
    sizes = Counter(ap.values())
    singleton = sum(v == 1 for v in sizes.values()) / len(sizes) if sizes else None
    return {
        "nodes": len(nodes),
        "account_nodes": len(ap),
        "pr_nodes": len(nodes) - len(ap),
        "communities": len(set(membership)),
        "account_communities": len(sizes),
        "singleton_share": singleton,
    }


def pair_metrics(a, b, common):
    ids = sorted(common & set(a) & set(b))
    if not ids:
        return {"common_accounts": 0, "nmi": None, "ari": None}
    x = [a[k] for k in ids]
    y = [b[k] for k in ids]
    return {
        "common_accounts": len(ids),
        "nmi": float(normalized_mutual_info_score(x, y)),
        "ari": float(adjusted_rand_score(x, y)),
    }


def active_accounts(rows, allowed):
    authors = {}
    interactions = defaultdict(set)
    for actor, pr, stype, _role, relation in rows:
        if stype not in allowed:
            continue
        if relation == "author":
            authors.setdefault(pr, (actor, stype))
        elif relation in {"review", "review_comment", "comment"}:
            interactions[pr].add((actor, stype))
    pairs = set()
    for pr, (author, _stype) in authors.items():
        for actor, _itype in interactions.get(pr, set()):
            if author != actor:
                pairs.add((author, actor))
    return {x for pair in pairs for x in pair}, pairs


