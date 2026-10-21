# Inputs for experimental Figures 3–7

Run from the package root:

```sh
python scripts/render_figures.py --out-dir outputs/figures
```

The default output directory is also `outputs/figures`. This entry point redraws the five experimental figures from saved graphs, community labels, coordinates, and analysis tables. Select individual figures with `--figures 3 4 5 6 7`.

- `rq1_global/`: complete All-known/Human-only account–PR graphs with only renderer-required attributes, retaining the original public-source account and PR identifiers. Vertex order, edge order, weights, saved memberships, coordinates and color alignment are unchanged. The shared-coordinate NPZ is copied unchanged from the final paper figure's source cache.
- `rq1_local/`: the fixed 38-node local example with original `node_id`, display `alias`, edge keys and saved positions. The three Parquet tables are copied unchanged from the final paper figure's inputs. The small previous-statistics JSON supports the original renderer's consistency assertion.
- `rq2_candidates/`: the original public illustrative case displayed in the paper, comprising three ten-row lists with public GitHub account keys and usernames.
- `rq2_curves.csv`: aggregate final-test and validation metrics used by the ranking-curves renderer.
- `rq3_monthly.csv`: the 17 monthly aggregate rows, including denominators and missing response values.
- `figure_expectations.json`: input/content fingerprints and reference image-pixel fingerprints for verification. Provenance paths are package-relative.

The renderer verifies input tables, graph attributes, and public source identifiers before drawing and writes `outputs/figures/figure_generation_summary.json`. All five regenerated PNGs matched the paper's original PNG pixels in the validation environment. The graph files use Python/igraph Pickle format with the versions listed in `requirements.txt`.
