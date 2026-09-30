"""Local dense retrieval over a versioned, auditable passage index.

The vectors represent the indexed record's actual text. In particular, an
English translation hit is not evidence that the model understood its Greek
parent. No corpus text is sent to a hosted embedding API.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock, RLock
from typing import Any
import unicodedata

import numpy as np

MODEL_NAME = "BAAI/bge-m3"
MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
INDEX_VERSION = 1


def _author_key(value: str) -> str:
    """Merged author key so every spelling of one poet passes the same filter."""
    try:
        from .author_aliases import canonical_key
        return canonical_key(value)
    except Exception:  # alias table unavailable: fall back to plain folding
        return unicodedata.normalize("NFC", value).casefold().strip()


class SemanticIndex:
    def __init__(self, index_dir: str | Path):
        self.index_dir = Path(index_dir)
        self._manifest: dict[str, Any] | None = None
        self._rows: list[dict[str, Any]] = []
        self._vectors: np.ndarray | None = None
        self._model: Any = None
        self._model_lock = Lock()
        self._encode_lock = Lock()
        self._state_lock = RLock()
        self._manifest_mtime_ns: int | None = None
        self._load_index()

    def _load_index(self) -> None:
        with self._state_lock:
            manifest_path = self.index_dir / "manifest.json"
            if not manifest_path.exists():
                return
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("index_version") != INDEX_VERSION:
                raise ValueError("Unsupported semantic index version; rebuild embeddings")
            rows_path = self.index_dir / manifest["rows_file"]
            vectors_path = self.index_dir / manifest["vectors_file"]
            rows = json.loads(rows_path.read_text(encoding="utf-8"))
            vectors = np.load(vectors_path, mmap_mode="r")
            if vectors.ndim != 2 or len(rows) != vectors.shape[0] or vectors.shape[1] != manifest["dimensions"]:
                raise ValueError("Semantic index files are inconsistent; rebuild embeddings")
            self._manifest = manifest
            self._rows = rows
            self._vectors = vectors
            self._manifest_mtime_ns = manifest_path.stat().st_mtime_ns

    def _refresh(self) -> None:
        path = self.index_dir / "manifest.json"
        with self._state_lock:
            if path.exists() and path.stat().st_mtime_ns != self._manifest_mtime_ns:
                self._load_index()

    @property
    def ready(self) -> bool:
        self._refresh()
        with self._state_lock:
            if self._manifest is None or self._vectors is None or not self._rows:
                return False
            corpus_path = self.index_dir.parent / "corpus.sqlite"
            if "corpus_mtime_ns" in self._manifest:
                if not corpus_path.exists():
                    return False
                stat = corpus_path.stat()
                if (stat.st_mtime_ns, stat.st_size) != (
                    self._manifest["corpus_mtime_ns"], self._manifest["corpus_size"]
                ):
                    return False
            return True

    @property
    def status(self) -> dict[str, Any]:
        if not self.ready:
            return {"ready": False, "count": 0, "method": "unavailable", "warning": "Local semantic index is absent or stale; rebuild embeddings."}
        with self._state_lock:
            manifest = self._manifest
            count = len(self._rows)
        return {
            "ready": True,
            "count": count,
            "method": "local BGE-M3 dense cosine search",
            "model": manifest["model"],
            "dimensions": manifest["dimensions"],
            "counts_by_language_kind": manifest.get("counts_by_language_kind", {}),
            "counts_by_source": manifest.get("counts_by_source", {}),
            "eligible_count": manifest.get("eligible_count", count),
            "total_windows": manifest.get("total_windows"),
            "pooling_method": manifest.get("pooling_method"),
            "warning": "Multilingual model quality on Ancient Greek has not been validated. Translation and commentary hits reflect their indexed language, not verified Greek understanding.",
        }

    def _get_model(self, manifest):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    import torch

                    device = "cuda" if torch.cuda.is_available() else "cpu"
                    model = SentenceTransformer(
                        manifest["model"],
                        revision=manifest["model_revision"],
                        device=device,
                        local_files_only=True,
                    )
                    if device == "cuda" and manifest.get("precision") == "float16":
                        model.half()
                    model.max_seq_length = int(manifest.get("max_seq_length", 512))
                    self._model = model
        return self._model

    def search(
        self,
        query: str,
        limit: int = 30,
        *,
        author: str | list[str] | None = None,
        language: str | None = None,
        include_reference: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.ready:
            raise RuntimeError("Local semantic index not built or stale")
        if not query.strip() or limit <= 0:
            return []
        with self._state_lock:
            manifest, rows, vectors = self._manifest, self._rows, self._vectors
        model = self._get_model(manifest)
        with self._encode_lock:
            query_vector = np.asarray(model.encode([query.strip()], normalize_embeddings=True)[0], dtype=np.float32)
        if query_vector.shape != (vectors.shape[1],):
            raise ValueError("Query embedding dimension differs from index; rebuild embeddings")
        scores = np.asarray(vectors @ query_vector, dtype=np.float32)
        order = np.argsort(-scores, kind="stable")
        output = []
        for index in order:
            row = rows[int(index)]
            if author:
                sought = {_author_key(label) for label in (author if isinstance(author,list) else [author])}
                labels = [row.get("author") or "", *(row.get("context_authors") or [])]
                if not any(_author_key(label) in sought for label in labels):
                    continue
            if language and row.get("language") != language:
                continue
            if not include_reference and row.get("kind") in {"reference", "apparatus"}:
                continue
            output.append({
                "id": row["id"],
                "score": round(float(scores[index]), 6),
                "indexed_language": row.get("language"),
                "indexed_kind": row.get("kind"),
                "parent_id": row.get("parent_id"),
                "context_authors": row.get("context_authors", []),
                "match_reason": (
                    "English translation embedding" if row.get("kind") == "translation" and row.get("language") == "eng"
                    else "Commentary embedding" if row.get("kind") == "commentary"
                    else "Original passage embedding"
                ),
            })
            if len(output) >= limit:
                break
        return output

    def vectors_for(self, ids: list[str]) -> tuple[list[str], np.ndarray]:
        """Return true indexed vectors for requested IDs in request order."""
        if not self.ready:
            raise RuntimeError("Local semantic index not built or stale")
        with self._state_lock:
            rows, vectors = self._rows, self._vectors
        positions = {row["id"]: index for index, row in enumerate(rows)}
        found = [passage_id for passage_id in ids if passage_id in positions]
        return found, np.asarray(vectors[[positions[passage_id] for passage_id in found]], dtype=np.float32)
