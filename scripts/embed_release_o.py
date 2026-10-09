"""Release O meaning-search vectors: the 232 Campbell GLP poems still pending, and the passages
whose stored text changed in the O corpus (leading edition sign removed), encoded with the
published contract (BAAI/bge-m3 at the pinned revision, float16 on CUDA, token windows,
weighted mean v2). Other vectors are copied unchanged.

  export   (box)   python scripts/embed_release_o.py export --corpus O.sqlite --manifest L/manifest.json --stage stage-corpus-o.json --out todo.json
  encode   (CUDA)  python scripts/embed_release_o.py encode --todo todo.json --out addition.npy
  assemble (box)   python scripts/embed_release_o.py assemble --corpus O.sqlite --manifest L/manifest.json --embeddings DIR --todo todo.json --vectors addition.npy --out OUTDIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FIELDS = ("id", "source", "language", "kind", "author", "parent_id")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def export(args):
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    stage = json.loads(Path(args.stage).read_text(encoding="utf-8"))
    rows = json.loads((Path(args.manifest).parent / manifest["rows_file"]).read_text(encoding="utf-8")) \
        if (Path(args.manifest).parent / manifest["rows_file"]).exists() else \
        json.loads((Path(args.embeddings) / manifest["rows_file"]).read_text(encoding="utf-8"))
    indexed = {row["id"] for row in rows}
    wanted = list(dict.fromkeys(list(manifest.get("pending_embedding_ids", [])) +
                                [i for i in stage.get("leading_sign_removed", []) if i in indexed]))
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    out = []
    for identifier in wanted:
        row = con.execute("SELECT id,source,language,kind,author,json_extract(data,'$.parent_id'),text FROM passages WHERE id=?",
                          (identifier,)).fetchone()
        if row is None:
            raise SystemExit(f"missing passage {identifier}")
        record = dict(zip(FIELDS, row[:6]))
        record.update(text=row[6], text_sha256=sha(row[6]),
                      reason="pending_glp" if identifier not in indexed else "text_changed_in_release_o")
        out.append(record)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(len(out), "records;", sum(r["reason"] == "pending_glp" for r in out), "pending GLP")


def encode(args):
    os.environ.setdefault("USE_TF", "0")
    import torch
    from sentence_transformers import SentenceTransformer
    from scripts.build_embeddings import encode_passage_batch, MODEL_NAME, MODEL_REVISION
    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable: the published contract is float16 on CUDA")
    todo = json.loads(Path(args.todo).read_text(encoding="utf-8"))
    model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cuda", local_files_only=True)
    model.half()
    model.max_seq_length = 512
    matrix, windows = encode_passage_batch(model, [r["text"] for r in todo], 16, 512)
    if matrix.shape != (len(todo), 1024) or not np.isfinite(matrix).all():
        raise SystemExit("unexpected vector shape")
    np.save(args.out, matrix.astype(np.float16) if matrix.dtype != np.float16 else matrix)
    Path(args.out).with_suffix(".receipt.json").write_text(json.dumps({
        "model": MODEL_NAME, "model_revision": MODEL_REVISION, "precision": "float16", "device": "cuda",
        "created_at": datetime.now(timezone.utc).isoformat(), "dtype": str(matrix.dtype),
        "rows": [{"id": r["id"], "text_sha256": r["text_sha256"], "windows": n} for r, n in zip(todo, windows)]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("encoded", matrix.shape, matrix.dtype)


def assemble(args):
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    emb = Path(args.embeddings)
    rows = json.loads((emb / manifest["rows_file"]).read_text(encoding="utf-8"))
    vectors = np.load(emb / manifest["vectors_file"], mmap_mode="r")
    todo = json.loads(Path(args.todo).read_text(encoding="utf-8"))
    receipt = json.loads(Path(args.vectors).with_suffix(".receipt.json").read_text(encoding="utf-8"))
    addition = np.load(args.vectors)
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    for record, rec in zip(todo, receipt["rows"]):
        text = con.execute("SELECT text FROM passages WHERE id=?", (record["id"],)).fetchone()[0]
        if rec["id"] != record["id"] or sha(text) != rec["text_sha256"]:
            raise SystemExit(f"text changed since encoding: {record['id']}")
    if addition.dtype != vectors.dtype:
        addition = addition.astype(vectors.dtype)
    position = {row["id"]: i for i, row in enumerate(rows)}
    replaced = [r for r in todo if r["id"] in position]
    appended = [r for r in todo if r["id"] not in position]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex
    total = len(rows) + len(appended)
    new = np.lib.format.open_memmap(out_dir / f"vectors-{stem}.npy", mode="w+", dtype=vectors.dtype, shape=(total, vectors.shape[1]))
    for start in range(0, len(rows), 8192):
        end = min(start + 8192, len(rows))
        new[start:end] = vectors[start:end]
    windows = {rec["id"]: rec["windows"] for rec in receipt["rows"]}
    index_of = {r["id"]: i for i, r in enumerate(todo)}
    new_rows = [dict(row) for row in rows]
    for record in replaced:
        new[position[record["id"]]] = addition[index_of[record["id"]]]
        new_rows[position[record["id"]]]["windows"] = windows[record["id"]]
    for k, record in enumerate(appended):
        new[len(rows) + k] = addition[index_of[record["id"]]]
        new_rows.append({**{f: record.get(f) for f in FIELDS}, "context_authors": [], "windows": windows[record["id"]]})
    new.flush()
    del new
    (out_dir / f"rows-{stem}.json").write_text(json.dumps(new_rows, ensure_ascii=False), encoding="utf-8")
    stat = os.stat(args.corpus)
    m = dict(manifest)
    for key in ("search_only_rebind", "pending_embedding_ids"):
        m.pop(key, None)
    counts = {}
    for row in new_rows:
        key = f"{row['language']}:{row['kind']}"
        counts[key] = counts.get(key, 0) + 1
    m.update(rows_file=f"rows-{stem}.json", vectors_file=f"vectors-{stem}.npy", count=len(new_rows),
             corpus_mtime_ns=stat.st_mtime_ns, corpus_size=stat.st_size, counts_by_language_kind=counts,
             total_windows=sum(int(r.get("windows") or 1) for r in new_rows),
             release_o={"script": "scripts/embed_release_o.py", "assembled_at": datetime.now(timezone.utc).isoformat(),
                        "appended": [r["id"] for r in appended], "re_encoded": [r["id"] for r in replaced],
                        "encoder_receipt": receipt["created_at"], "base_rows_file": manifest["rows_file"],
                        "base_vectors_file": manifest["vectors_file"]})
    (out_dir / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(new_rows), "appended": len(appended), "re_encoded": len(replaced)}))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["export", "encode", "assemble"])
    for name in ("corpus", "manifest", "stage", "embeddings", "todo", "vectors", "out"):
        p.add_argument("--" + name)
    args = p.parse_args()
    {"export": export, "encode": encode, "assemble": assemble}[args.step](args)


if __name__ == "__main__":
    main()
