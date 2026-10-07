"""EXPERIMENTAL lab script (not used by the server): exact vs quantised dense scan.

Measures, on the existing BGE-M3 index and with BLAS limited to the production
box's two cores, how fast a full float32 scan is and how much of its top-k a
int8 scan or a binary scan with float32 rescoring keeps. Query vectors are the
index's own English translation vectors (a cross-lingual stand-in for encoded
queries); each query's own row is excluded. No model is loaded and nothing is
written except the optional JSON report.

  py -3.13 scripts/lab_vector_bench.py --queries 200 --k 100 --out output/lab/vector-bench.json
"""
from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

import argparse
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def topk(scores: np.ndarray, k: int) -> np.ndarray:
    part = np.argpartition(-scores, k)[:k]
    return part[np.argsort(-scores[part], kind="stable")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, default=ROOT / "data/embeddings")
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--k", type=int, default=100)
    parser.add_argument("--rescore", type=int, default=400, help="binary candidates rescored in float32")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.index / "manifest.json").read_text(encoding="utf-8"))
    rows = json.loads((args.index / manifest["rows_file"]).read_text(encoding="utf-8"))
    started = time.perf_counter()
    vectors = np.asarray(np.load(args.index / manifest["vectors_file"], mmap_mode="r"), dtype=np.float32)
    load_s = time.perf_counter() - started
    query_rows = [i for i, row in enumerate(rows) if row.get("language") == "eng" and row.get("kind") == "translation"]
    rng = np.random.default_rng(0)
    picks = rng.choice(query_rows, size=min(args.queries, len(query_rows)), replace=False)

    scale = np.abs(vectors).max(axis=0) / 127.0  # per-dimension symmetric int8 scale
    q8 = np.round(vectors / scale).astype(np.int8)
    bits = np.packbits(vectors > 0, axis=1)
    popcount = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)

    timings = {"float32": [], "int8": [], "binary_rescore": []}
    overlap = {"int8": [], "binary_rescore": []}
    for qi in picks:
        query = vectors[qi]
        t = time.perf_counter(); exact = vectors @ query; exact[qi] = -9; ref = topk(exact, args.k); timings["float32"].append(time.perf_counter() - t)
        t = time.perf_counter(); s8 = q8.astype(np.float32, copy=False) @ (query * scale); s8[qi] = -9; got8 = topk(s8, args.k); timings["int8"].append(time.perf_counter() - t)
        t = time.perf_counter()
        qbits = np.packbits(query > 0)
        hamming = popcount[np.bitwise_xor(bits, qbits)].sum(axis=1, dtype=np.int32)
        hamming[qi] = 10**6
        cand = np.argpartition(hamming, args.rescore)[:args.rescore]
        rescored = vectors[cand] @ query
        gotb = cand[np.argsort(-rescored, kind="stable")[:args.k]]
        timings["binary_rescore"].append(time.perf_counter() - t)
        overlap["int8"].append(len(set(ref) & set(got8)) / args.k)
        overlap["binary_rescore"].append(len(set(ref) & set(gotb)) / args.k)

    report = {
        "experimental": True,
        "vectors": list(vectors.shape), "float32_mb": round(vectors.nbytes / 2**20, 1),
        "int8_mb": round(q8.nbytes / 2**20, 1), "binary_mb": round(bits.nbytes / 2**20, 1),
        "load_seconds": round(load_s, 2), "queries": int(len(picks)), "k": args.k, "rescore_pool": args.rescore,
        "median_ms": {name: round(1000 * float(np.median(values)), 1) for name, values in timings.items()},
        "mean_overlap_at_k_vs_float32": {name: round(float(np.mean(values)), 4) for name, values in overlap.items()},
        "note": "int8 timing here dequantises in numpy; a native int8 kernel (usearch/sqlite-vec) would be faster. Overlap is agreement with the exact scan, not relevance.",
    }
    print(json.dumps(report, indent=1))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
