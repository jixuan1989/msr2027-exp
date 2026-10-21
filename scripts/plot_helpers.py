"""Small shared helpers for the published experimental figures.

Contains only graph fingerprinting, file hashing, and the original full-graph
community color alignment. No layout or community detection is run here.
"""
from pathlib import Path
import hashlib
import colorsys
import numpy as np
from scipy.optimize import linear_sum_assignment

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()

def graph_signature(graph):
    edges = np.asarray(graph.get_edgelist(), dtype=np.int32)
    weights = np.asarray(graph.es["weight"], dtype=np.float64)
    digest = hashlib.sha256(edges.tobytes() + weights.tobytes())
    digest.update("\n".join(graph.vs["name"]).encode())
    return digest.hexdigest()

def match_colours(full, human, membership):
    """Maximum-weight one-to-one colour alignment on common humans only."""
    names = full.vs["name"]
    index = {name: i for i, name in enumerate(names)}
    human_index = np.asarray([index[name] for name in human.vs["name"]])
    full_labels = np.asarray(full.vs[membership], dtype=np.int32)
    human_labels = np.asarray(human.vs[membership], dtype=np.int32)
    common_mask = np.asarray(human.vs["common_human"], dtype=bool)
    rows = np.unique(full_labels)
    columns = np.unique(human_labels)
    counts = np.zeros((len(rows), len(columns)), dtype=np.int32)
    row_lookup = {int(label): i for i, label in enumerate(rows)}
    col_lookup = {int(label): i for i, label in enumerate(columns)}
    common_indices = np.flatnonzero(common_mask)
    r = np.asarray([row_lookup[int(v)] for v in full_labels[human_index[common_indices]]])
    c = np.asarray([col_lookup[int(v)] for v in human_labels[common_indices]])
    np.add.at(counts, (r, c), 1)
    row_assignment, col_assignment = linear_sum_assignment(counts, maximize=True)
    # Largest account-containing groups receive widely separated early colours.
    full_account = np.asarray(full.vs["node_type"]) == "account"
    sizes = {int(label): int(np.sum((full_labels == label) & full_account)) for label in rows}
    order = sorted(rows, key=lambda label: (-sizes[int(label)], int(label)))
    full_rank = {int(label): rank for rank, label in enumerate(order)}
    human_rank = {}
    matches = []
    for i, j in zip(row_assignment, col_assignment):
        if counts[i, j] <= 0:
            continue
        source, target = int(rows[i]), int(columns[j])
        human_rank[target] = full_rank[source]
        matches.append({"all_known_community": source,
                        "human_only_community": target,
                        "common_human_overlap": int(counts[i, j])})
    next_rank = len(full_rank)
    for label in columns:
        if int(label) not in human_rank:
            human_rank[int(label)] = next_rank
            next_rank += 1
    # Unique categorical hues, plus brightness/saturation variation. With thousands
    # of groups, colours indicate regions rather than individually readable IDs.
    palette = np.asarray([
        colorsys.hls_to_rgb((0.58 + k * 0.6180339887498949) % 1,
                           0.42 + 0.065 * ((k // 11) % 3),
                           0.60 + 0.09 * ((k // 7) % 3))
        for k in range(next_rank)
    ])
    full_rgb = palette[[full_rank[int(v)] for v in full_labels]]
    human_rgb = palette[[human_rank[int(v)] for v in human_labels]]
    return human_index, full_rgb, human_rgb, matches, len(common_indices)


def portable_metadata(value, root):
    """Use package-relative provenance rather than local host paths."""
    if isinstance(value, dict):
        return {key: portable_metadata(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_metadata(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(Path(root).resolve()) + "/", "").replace(str(Path(root).resolve()), ".")
    return value
