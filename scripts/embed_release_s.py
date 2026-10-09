"""Release S: batch-embed the searchable passages with a candidate sentence encoder (offline, GPU or CPU).

  python scripts/embed_release_s.py --model sphilberta --corpus data/corpus.sqlite \
      --rows data/embeddings/rows-<O>.json --out data/embeddings-s/sphilberta
  python scripts/embed_release_s.py --model notes --notes data/commentary_context.sqlite ...   # commentary notes

The passage set and order are release O's BGE-M3 rows (116,428 records: Greek text, English and Modern
Greek translations, English and Greek commentary), so every model indexes exactly the same records and
the rows file is shared. A passage longer than WINDOW_WORDS whitespace words is split into consecutive
windows; window vectors are averaged with word-count weights and normalised (the release O pooling,
counted in words so it is the same for every tokenizer). Vectors are stored as float16; the manifest
records the model, revision, prompt, pooling and the corpus file it was built from.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.encoders import MODELS, Encoder  # noqa: E402

WINDOW_WORDS = 160


def windows(text):
    words = text.split()
    if not words:
        return [("", 1)]
    return [(" ".join(words[i:i + WINDOW_WORDS]), len(words[i:i + WINDOW_WORDS])) for i in range(0, len(words), WINDOW_WORDS)]


def embed_texts(encoder, texts, batch_size):
    """Pooled vectors for whole texts (window split, word-weighted mean, normalised)."""
    pieces, owner, weight = [], [], []
    for i, text in enumerate(texts):
        for piece, n in windows(text):
            pieces.append(piece)
            owner.append(i)
            weight.append(n)
    # Length-sorted batches: far less padding.
    order = sorted(range(len(pieces)), key=lambda j: len(pieces[j]))
    vectors = None
    started = time.time()
    for start in range(0, len(order), batch_size * 16):
        chunk = order[start:start + batch_size * 16]
        vec = encoder.encode([pieces[j] for j in chunk], batch_size=batch_size)
        if vectors is None:
            vectors = np.zeros((len(pieces), vec.shape[1]), np.float32)
        vectors[chunk] = vec
        if (start // (batch_size * 16)) % 20 == 0:
            print(f"  {start + len(chunk)}/{len(pieces)} windows {time.time() - started:.0f}s", flush=True)
    pooled = np.zeros((len(texts), vectors.shape[1]), np.float32)
    np.add.at(pooled, np.asarray(owner), vectors * np.asarray(weight, np.float32)[:, None])
    pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
    return pooled, len(pieces)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, choices=sorted(MODELS))
    p.add_argument("--corpus", required=True)
    p.add_argument("--rows", required=True, help="release O rows file: the passage set and order")
    p.add_argument("--out", required=True)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--limit", type=int, default=0, help="first N rows only (a timing run)")
    args = p.parse_args()
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[:args.limit]
    con = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    texts = []
    for row in rows:
        found = con.execute("SELECT text FROM passages WHERE id=?", (row["id"],)).fetchone()
        texts.append((found[0] or "") if found else "")
    missing = sum(1 for t in texts if not t)
    encoder = Encoder(args.model, cache_dir=args.cache_dir)
    started = time.time()
    vectors, n_windows = embed_texts(encoder, texts, args.batch_size)
    seconds = time.time() - started
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows_bytes = Path(args.rows).read_bytes()
    tag = hashlib.sha256(rows_bytes).hexdigest()[:16] + "-" + args.model
    np.save(out / f"vectors-{tag}.npy", vectors.astype(np.float16))
    (out / f"rows-{tag}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    # The corpus stamp the API checks is the one release O's index was built against (the same file on the
    # box; a laptop copy has another mtime), read from the manifest beside the rows file.
    o_manifest = Path(args.rows).with_name("manifest.json")
    stamp = json.loads(o_manifest.read_text(encoding="utf-8")) if o_manifest.exists() else {}
    stat = Path(args.corpus).stat()
    hub, revision, qp, dp, max_tokens, _ = MODELS[args.model]
    manifest = {"index_version": 1, "model": hub, "model_revision": revision, "model_key": args.model,
                "precision": "float16", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "count": len(rows), "eligible_count": len(rows), "missing_text": missing,
                "corpus_mtime_ns": stamp.get("corpus_mtime_ns", stat.st_mtime_ns),
                "corpus_size": stamp.get("corpus_size", stat.st_size),
                "dimensions": int(vectors.shape[1]), "max_seq_length": max_tokens,
                "pooling_method": f"word_windows_{WINDOW_WORDS}_weighted_mean_s1", "total_windows": n_windows,
                "query_prompt": qp, "document_prompt": dp, "encode_seconds": round(seconds, 1),
                "device": encoder.device, "rows_file": f"rows-{tag}.json", "vectors_file": f"vectors-{tag}.npy",
                "rows_source_sha256": hashlib.sha256(rows_bytes).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("model", "count", "total_windows", "encode_seconds", "dimensions")}))


if __name__ == "__main__":
    main()
