"""Run-time measurement at the confirmed data scale (spec 8.5, milestone 5). SYNTHETIC data.

Usage:  uv run python scripts/benchmark_scale.py [n_blocks]
"""

import sys
import time

import numpy as np
import pandas as pd

from engine.candidates import CandidateSettings, Range, estimate_size, generate_candidates
from engine.costs import CostModel
from engine.evaluate import Target, build_context, evaluate_campaign
from engine.geometry import Thresholds
from engine.optimise import OptimiserSettings, build_candidate_matrix, optimise
from engine.schema import ClassRank


def main(n_blocks: int = 1_000_000):
    rng = np.random.default_rng(1)
    side = round(n_blocks ** (1 / 3))
    g = (np.arange(side) + 0.5) * 5.0
    x, y, z = (a.ravel() for a in np.meshgrid(g, g, -g, indexing="ij"))
    n = len(x)
    # Indicated core with Inferred/Measured elsewhere
    r = np.hypot(x - x.mean(), y - y.mean())
    cls = np.where(r < 0.25 * x.max(), ClassRank.INDICATED,
                   np.where(r < 0.4 * x.max(), ClassRank.MEASURED, ClassRank.INFERRED))
    blocks = pd.DataFrame({"block_id": np.arange(n).astype(str), "x": x, "y": y, "z": z,
                           "uploaded_class": cls.astype(np.int8), "tonnes": 125 * 2.7,
                           "metal": 125 * 2.7 * rng.uniform(0.2, 3, n) / 1000, "valid": True})
    # 1,000 existing holes, 10 samples each
    # 1,000 existing holes: dense outside the Indicated core, ~40 m spacing inside it
    hx, hy = rng.uniform(0, x.max(), 20_000), rng.uniform(0, y.max(), 20_000)
    core = np.hypot(hx - x.mean(), hy - y.mean()) < 0.25 * x.max()
    core_n = max(3, int(np.pi * (0.25 * x.max()) ** 2 / 1600))
    pick = np.r_[np.flatnonzero(core)[:core_n], np.flatnonzero(~core)[:1000 - core_n]]
    hx, hy = hx[pick], hy[pick]
    depth = np.linspace(-20, z.min(), 10)
    support = pd.DataFrame({"hole_id": np.repeat(np.arange(1000), 10).astype(str),
                            "x": np.repeat(hx, 10), "y": np.repeat(hy, 10),
                            "z": np.tile(depth, 1000)})
    # 50 sites
    sx, sy = rng.uniform(0.3, 0.7, 50) * x.max(), rng.uniform(0.3, 0.7, 50) * y.max()
    sites = pd.DataFrame({"site_id": [f"S{i}" for i in range(50)], "x": sx, "y": sy, "z": 0.0})
    cs = CandidateSettings(Range(0, 330, 30), Range(-90, -50, 10), Range(100, 300, 50))
    cost = CostModel(250.0, 5_000.0, 20_000.0)

    t = time.perf_counter()
    ctx = build_context(blocks, support, thresholds=Thresholds(), target=Target(),
                        cost_model=cost)
    print(f"blocks {n:,}, eligible {ctx.eligible.sum():,}; baseline {time.perf_counter()-t:.1f} s")
    cands = generate_candidates(sites, cs)
    est = estimate_size(len(cands), ctx.xyz[ctx.eligible], cs, 75.0)
    print(f"candidates {len(cands):,}; estimated entries {est.est_entries:,} "
          f"({est.est_bytes/1e9:.2f} GB) {est.warnings}")
    t = time.perf_counter()
    cm = build_candidate_matrix(ctx, cands)
    print(f"matrix nnz {cm.matrix.nnz:,} ({cm.matrix.data.nbytes*2/1e9:.2f} GB), useful "
          f"{cm.matrix.shape[1]:,}; built in {time.perf_counter()-t:.1f} s")
    for budget in (1e6, 5e6):
        t = time.perf_counter()
        res = optimise(cm, None, budget, cost, OptimiserSettings())
        ev = evaluate_campaign(ctx, res.holes)
        print(f"budget {budget:,.0f}: {len(res.holes)} holes, metal {ev.totals['converted_metal']:,.1f}, "
              f"cost {ev.cost.total:,.0f}; optimise+evaluate {time.perf_counter()-t:.1f} s")
        print("  " + "\n  ".join(res.log))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000)
