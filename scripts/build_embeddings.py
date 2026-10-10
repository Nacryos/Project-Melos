"""Build and incrementally refresh local BGE-M3 passage vectors.

Usage: py -3.13 scripts/build_embeddings.py [--db data/corpus.sqlite]
The SQLite checkpoint survives interruption; the published NumPy index is
atomically replaced only after every eligible passage has been processed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.semantic import INDEX_VERSION, MODEL_NAME, MODEL_REVISION  # noqa: E402

LYRIC_AUTHORS = {
    "alcaeus", "alcman", "anacreon", "archilochus", "bacchylides",
    "ibycus", "mimnermus", "pindar", "sappho", "simonides",
    "solon", "stesichorus", "theognis", "tyrtaeus",
}
POOLING_METHOD = "token_windows_weighted_mean_v2"


def eligible(row: sqlite3.Row) -> bool:
    return (
        bool(row["text"] and row["text"].strip())
        and row["kind"] in {"text", "translation", "commentary"}
        and (row["quality"] in {"source_text", "machine_corrected_ocr"}
             or (row["quality"] == "machine_translation" and row["kind"] == "translation"))
        and row["language"] in {"grc", "ell", "eng", "lat", "ita", "fra", "deu", "mul"}
    )


def source_rows(db_path: Path) -> list[dict]:
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        records = connection.execute(
            "SELECT id, source, text, language, kind, quality, author, data FROM passages"
        )
        rows = []
        greek_by_id: dict[str, str] = {}
        greek_by_url: dict[tuple[str, str], set[str]] = {}
        for row in records:
            if not eligible(row):
                continue
            data = json.loads(row["data"] or "{}")
            source_url = data.get("source_url")
            if row["kind"] == "text" and row["language"] == "grc" and row["author"]:
                greek_by_id[row["id"]] = row["author"]
                if source_url:
                    greek_by_url.setdefault((row['source'], source_url), set()).add(row["author"])
            rows.append({
                "id": row["id"],
                "source": row["source"],
                "text": row["text"],
                "language": row["language"],
                "kind": row["kind"],
                "author": row["author"],
                "parent_id": data.get("parent_id"),
                "source_url": source_url,
                "scope": (data.get("metadata") or {}).get("scope"),
            })
        for record in rows:
            linked = set()
            if record["kind"] in {"commentary", "translation"}:
                parent_author = greek_by_id.get(record["parent_id"])
                if parent_author:
                    linked.add(parent_author)
                if (record["kind"] == "commentary" and record["scope"] in {"page", "source_section"}
                        and record["source_url"]):
                    linked.update(greek_by_url.get((record['source'], record["source_url"]), ()))
            record["context_authors"] = sorted(linked)
        def priority(record: dict) -> tuple[int, str]:
            author = (record["author"] or "").casefold()
            is_lyric = any(name in author for name in LYRIC_AUTHORS)
            if record["source"] in {"lyric_web", "sappho"} or is_lyric:
                bucket = 0
            elif record["kind"] == "translation":
                bucket = 1
            elif record["source"] == "ogc":
                bucket = 2
            else:
                bucket = 3
            return bucket, record["id"]

        rows.sort(key=priority)
        return rows


def _checkpoint(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS embeddings ("
        "id TEXT PRIMARY KEY, text_hash TEXT NOT NULL, model TEXT NOT NULL, "
        "vector BLOB NOT NULL, windows INTEGER NOT NULL DEFAULT 1)"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(embeddings)")}
    if "windows" not in columns:
        connection.execute("ALTER TABLE embeddings ADD COLUMN windows INTEGER NOT NULL DEFAULT 1")
    connection.commit()


def encode_passage_batch(encoder, texts: list[str], batch_size: int, max_seq_length: int) -> tuple[np.ndarray, list[int]]:
    """Represent every passage token via normalized, length-weighted windows."""
    tokenizer = encoder.tokenizer
    token_budget = max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
    if token_budget <= 0:
        raise ValueError("max_seq_length leaves no room for passage tokens")
    windows: list[str] = []
    lengths: list[int] = []
    spans: list[tuple[int, int]] = []
    for value in texts:
        ids = tokenizer.encode(value, add_special_tokens=False, truncation=False)
        if not ids:
            raise ValueError("Tokenizer produced no tokens for a nonempty passage")
        first = len(windows)
        if len(ids) <= token_budget:
            windows.append(value)
            lengths.append(len(ids))
        else:
            offset = 0
            while offset < len(ids):
                size = min(token_budget, len(ids) - offset)
                while True:
                    part = ids[offset : offset + size]
                    window = tokenizer.decode(part, skip_special_tokens=True, clean_up_tokenization_spaces=False)
                    # Decoding a partial word can change token boundaries. Verify
                    # the actual text passed to SentenceTransformer fits exactly.
                    recoded = tokenizer.encode(window, add_special_tokens=False, truncation=False)
                    if len(recoded) <= token_budget:
                        break
                    size -= 1
                    if size <= 0:
                        raise ValueError("A single decoded token exceeds the model window budget")
                windows.append(window)
                lengths.append(size)
                offset += size
        spans.append((first, len(windows)))
    encoded = np.asarray(
        encoder.encode(
            windows,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ),
        dtype=np.float32,
    )
    pooled = []
    counts = []
    for first, end in spans:
        weights = np.asarray(lengths[first:end], dtype=np.float32)
        vector = np.average(encoded[first:end], axis=0, weights=weights)
        norm = np.linalg.norm(vector)
        if norm <= 0 or not np.isfinite(norm):
            raise ValueError("Invalid pooled passage embedding")
        pooled.append(vector / norm)
        counts.append(end - first)
    return np.stack(pooled), counts


def build(
    db_path: Path,
    index_dir: Path,
    *,
    batch_size: int = 32,
    max_seq_length: int = 512,
    max_passages: int = 20_000,
    use_fp16: bool = True,
    encoder=None,
) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError(f"Corpus SQLite not found: {db_path}")
    db_stat = db_path.stat()
    index_dir.mkdir(parents=True, exist_ok=True)
    rows = source_rows(db_path)
    if not rows:
        raise ValueError("No eligible source-text or translation passages in corpus SQLite")
    eligible_count = len(rows)
    if max_passages > 0:
        rows = rows[:max_passages]
    if encoder is None:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        precision = "float16" if use_fp16 and device == "cuda" else "float32"
    else:
        device = "injected"
        precision = "float16" if use_fp16 else "float32"
    hashes = {
        r["id"]: hashlib.sha256(f"{MODEL_REVISION}\0{precision}\0{POOLING_METHOD}\0{max_seq_length}\0{r['text']}".encode("utf-8")).hexdigest()
        for r in rows
    }
    checkpoint = sqlite3.connect(index_dir / "checkpoint.sqlite")
    _checkpoint(checkpoint)
    existing = {
        row[0]: row[1]
        for row in checkpoint.execute("SELECT id, text_hash FROM embeddings WHERE model=?", (MODEL_NAME,))
    }
    pending = [r for r in rows if existing.get(r["id"]) != hashes[r["id"]]]
    print(f"Eligible {len(rows)}; cached {len(rows) - len(pending)}; to encode {len(pending)}", flush=True)
    if pending and encoder is None:
        from sentence_transformers import SentenceTransformer

        print(f"Loading {MODEL_NAME} on {device} ({precision})", flush=True)
        encoder = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device=device)
        if precision == "float16":
            encoder.half()
        encoder.max_seq_length = max_seq_length
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors, window_counts = encode_passage_batch(
            encoder, [r["text"] for r in batch], batch_size, max_seq_length
        )
        if vectors.ndim != 2 or vectors.shape[0] != len(batch):
            raise ValueError("Encoder returned unexpected vector shape")
        checkpoint.executemany(
            "INSERT OR REPLACE INTO embeddings(id,text_hash,model,vector,windows) VALUES (?,?,?,?,?)",
            [(r["id"], hashes[r["id"]], MODEL_NAME, vector.tobytes(), count)
             for r, vector, count in zip(batch, vectors, window_counts)],
        )
        checkpoint.commit()
        if (start // batch_size) % 20 == 0 or start + len(batch) == len(pending):
            print(f"Encoded {start + len(batch)}/{len(pending)} new passages", flush=True)
    stored = {
        row[0]: (row[1], row[2], row[3])
        for row in checkpoint.execute("SELECT id, text_hash, vector, windows FROM embeddings WHERE model=?", (MODEL_NAME,))
    }
    selected = []
    vectors = []
    for row in rows:
        digest, raw, windows = stored[row["id"]]
        if digest != hashes[row["id"]]:
            raise ValueError(f"Stale vector for {row['id']}")
        vector = np.frombuffer(raw, dtype=np.float32)
        if not np.isfinite(vector).all() or vector.size == 0:
            raise ValueError(f"Invalid vector for {row['id']}")
        selected.append({key: row[key] for key in ("id", "source", "language", "kind", "author", "parent_id", "context_authors")} | {"windows": windows})
        vectors.append(vector)
    matrix = np.stack(vectors)
    norms = np.linalg.norm(matrix, axis=1)
    if np.any(norms < 0.99) or np.any(norms > 1.01):
        raise ValueError("Expected normalized vectors")
    current_stat = db_path.stat()
    if (current_stat.st_mtime_ns, current_stat.st_size) != (db_stat.st_mtime_ns, db_stat.st_size):
        raise RuntimeError("Corpus SQLite changed during embedding build; rerun to publish a current index")
    build_id = uuid.uuid4().hex
    rows_file = f"rows-{build_id}.json"
    vectors_file = f"vectors-{build_id}.npy"
    (index_dir / rows_file).write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")
    with (index_dir / vectors_file).open("wb") as handle:
        np.save(handle, matrix)
    manifest = {
        "index_version": INDEX_VERSION,
        "model": MODEL_NAME,
        "model_revision": MODEL_REVISION,
        "precision": precision,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "count": len(selected),
        "eligible_count": eligible_count,
        "corpus_mtime_ns": db_stat.st_mtime_ns,
        "corpus_size": db_stat.st_size,
        "dimensions": matrix.shape[1],
        "max_seq_length": max_seq_length,
        "pooling_method": POOLING_METHOD,
        "total_windows": sum(row["windows"] for row in selected),
        "counts_by_language_kind": dict(Counter(f"{r['language']}:{r['kind']}" for r in selected)),
        "counts_by_source": dict(Counter(r["source"] for r in selected)),
        "rows_file": rows_file,
        "vectors_file": vectors_file,
        "searchable_qualities": ["source_text", "machine_corrected_ocr", "machine_translation"],
        "indexed_text": "Original text from passages.text; source_text and explicitly labelled machine_corrected_ocr (not independently verified transcription); declared Ancient Greek, Modern Greek, English, Latin, Italian, French, German and multilingual text/translation/commentary; machine_translation rows (owner-commissioned literal English renderings linked to their Greek poem) as translation only",
    }
    tmp = index_dir / f"manifest-{build_id}.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, index_dir / "manifest.json")
    checkpoint.close()
    print(f"Published {len(selected)} vectors ({matrix.shape[1]} dimensions)", flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/corpus.sqlite")
    parser.add_argument("--index-dir", type=Path, default=ROOT / "data/embeddings")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--max-passages", type=int, default=20_000, help="Initial index cap; use 0 to index all eligible passages")
    parser.add_argument("--fp32", action="store_true", help="Disable CUDA half precision")
    parser.add_argument("--benchmark", action="store_true", help="Time 128 real passages at several batch sizes without changing the index")
    args = parser.parse_args()
    if args.benchmark:
        from sentence_transformers import SentenceTransformer
        import torch

        samples = [r["text"] for r in source_rows(args.db)[:128]]
        encoder = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cuda")
        encoder.max_seq_length = args.max_seq_length
        for precision, sizes in (("float32", (8,)), ("float16", (16, 32, 64))):
            if precision == "float16":
                encoder.half()
            for size in sizes:
                try:
                    torch.cuda.synchronize()
                    start = time.perf_counter()
                    encoder.encode(samples, batch_size=size, normalize_embeddings=True, show_progress_bar=False)
                    torch.cuda.synchronize()
                    elapsed = time.perf_counter() - start
                    print(f"{precision} batch={size}: {len(samples)/elapsed:.1f} passages/s ({elapsed:.1f}s)", flush=True)
                except torch.cuda.OutOfMemoryError:
                    print(f"{precision} batch={size}: CUDA out of memory", flush=True)
                    torch.cuda.empty_cache()
        return
    build(args.db, args.index_dir, batch_size=args.batch_size, max_seq_length=args.max_seq_length, max_passages=args.max_passages, use_fp16=not args.fp32)


if __name__ == "__main__":
    main()
