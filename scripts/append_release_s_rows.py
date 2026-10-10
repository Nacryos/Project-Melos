"""Append a few passages to a release S dense index without re-encoding the rest (release X, 2026-10-10).

  encode   (any machine) python scripts/append_release_s_rows.py encode --model shlm --todo todo.json --out shlm-addition.npy
  assemble (box)         python scripts/append_release_s_rows.py assemble --model shlm --index data/embeddings-s/shlm \
                             --todo todo.json --vectors shlm-addition.npy --corpus NEW.sqlite --out NEW/embeddings-s/shlm
  rebind   (box)         python scripts/append_release_s_rows.py rebind --o-manifest NEW/embeddings/manifest.json \
                             --container-dir /app/data/embeddings --out NEW/embeddings-s/bge-m3

The todo file is release O's export (scripts/embed_release_o.py export): the appended rows, in order. `encode` uses
the release S pooling (scripts/embed_release_s.py: word windows, weighted mean, float16) with the pinned model; the
receipt records the device and text hashes. `assemble` copies the existing rows and vectors, appends the addition in
todo order after checking the texts are unchanged, and writes a manifest stamped to the new corpus. `rebind` writes
the bge-m3 S manifest, which shares release O's rows and vectors, pointing at O's new files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIELDS = ("id", "source", "language", "kind", "author", "parent_id")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def encode(args):
    os.environ.setdefault("USE_TF", "0")
    from backend.encoders import MODELS, Encoder
    from scripts.embed_release_s import WINDOW_WORDS, embed_texts
    todo = json.loads(Path(args.todo).read_text(encoding="utf-8"))
    encoder = Encoder(args.model, cache_dir=args.cache_dir)
    started = time.time()
    vectors, n_windows = embed_texts(encoder, [r["text"] for r in todo], args.batch_size)
    if vectors.shape[0] != len(todo) or not np.isfinite(vectors).all():
        raise SystemExit("unexpected vector shape")
    np.save(args.out, vectors.astype(np.float16))
    hub, revision = MODELS[args.model][:2]
    Path(args.out).with_suffix(".receipt.json").write_text(json.dumps({
        "model": hub, "model_revision": revision, "model_key": args.model, "precision": "float16",
        "device": encoder.device, "pooling_method": f"word_windows_{WINDOW_WORDS}_weighted_mean_s1",
        "created_at": datetime.now(timezone.utc).isoformat(), "encode_seconds": round(time.time() - started, 1),
        "windows": n_windows, "rows": [{"id": r["id"], "text_sha256": r["text_sha256"]} for r in todo]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("encoded", vectors.shape, "windows", n_windows, "device", encoder.device)


def assemble(args):
    index = Path(args.index)
    manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("model_key") != args.model:
        raise SystemExit("index is not " + args.model)
    rows = json.loads((index / manifest["rows_file"]).read_text(encoding="utf-8"))
    vectors = np.load(index / manifest["vectors_file"], mmap_mode="r")
    todo = json.loads(Path(args.todo).read_text(encoding="utf-8"))
    receipt = json.loads(Path(args.vectors).with_suffix(".receipt.json").read_text(encoding="utf-8"))
    addition = np.load(args.vectors)
    if receipt["model_key"] != args.model or receipt["model_revision"] != manifest["model_revision"]:
        raise SystemExit("addition was encoded with another model or revision")
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    present = {row["id"] for row in rows}
    for record, rec in zip(todo, receipt["rows"]):
        text = con.execute("SELECT text FROM passages WHERE id=?", (record["id"],)).fetchone()[0]
        if rec["id"] != record["id"] or sha(text) != rec["text_sha256"]:
            raise SystemExit(f"text changed since encoding: {record['id']}")
        if record["id"] in present:
            raise SystemExit(f"already indexed: {record['id']}")
    if addition.shape != (len(todo), vectors.shape[1]):
        raise SystemExit("addition shape mismatch")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex[:16] + "-" + args.model
    total = len(rows) + len(todo)
    new = np.lib.format.open_memmap(out / f"vectors-{stem}.npy", mode="w+", dtype=vectors.dtype, shape=(total, vectors.shape[1]))
    for start in range(0, len(rows), 8192):
        end = min(start + 8192, len(rows))
        new[start:end] = vectors[start:end]
    new[len(rows):] = addition.astype(vectors.dtype)
    new.flush()
    del new
    new_rows = [dict(row) for row in rows] + [{**{f: r.get(f) for f in FIELDS}, "context_authors": [], "windows": 1} for r in todo]
    (out / f"rows-{stem}.json").write_text(json.dumps(new_rows, ensure_ascii=False), encoding="utf-8")
    stat = os.stat(args.corpus)
    m = dict(manifest)
    m.update(count=len(new_rows), eligible_count=len(new_rows), corpus_mtime_ns=stat.st_mtime_ns, corpus_size=stat.st_size,
             total_windows=int(manifest.get("total_windows") or 0) + int(receipt.get("windows") or len(todo)),
             rows_file=f"rows-{stem}.json", vectors_file=f"vectors-{stem}.npy",
             release_x={"script": "scripts/append_release_s_rows.py", "assembled_at": datetime.now(timezone.utc).isoformat(),
                        "appended": [r["id"] for r in todo], "encoder_receipt": receipt["created_at"],
                        "encode_device": receipt["device"], "base_rows_file": manifest["rows_file"],
                        "base_vectors_file": manifest["vectors_file"]})
    (out / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"rows": len(new_rows), "appended": len(todo)}))


def rebind(args):
    """The bge-m3 S index shares release O's files: point its manifest at O's new rows and vectors."""
    o = json.loads(Path(args.o_manifest).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    m = {k: v for k, v in o.items() if k not in ("counts_by_source", "corpus_rebinding", "release_o")}
    m.update(rows_file=f"{args.container_dir.rstrip('/')}/{o['rows_file']}",
             vectors_file=f"{args.container_dir.rstrip('/')}/{o['vectors_file']}", model_key="bge-m3",
             release_x={"rebound_from": str(args.o_manifest), "at": datetime.now(timezone.utc).isoformat()})
    (out / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"rows_file": m["rows_file"], "count": m["count"]}))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["encode", "assemble", "rebind"])
    for name in ("model", "todo", "out", "index", "vectors", "corpus", "cache-dir", "o-manifest", "container-dir"):
        p.add_argument("--" + name.replace("_", "-"), dest=name.replace("-", "_"))
    p.add_argument("--batch-size", type=int, default=16)
    args = p.parse_args()
    {"encode": encode, "assemble": assemble, "rebind": rebind}[args.step](args)


if __name__ == "__main__":
    main()
