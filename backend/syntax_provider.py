"""Bounded local OdyCy dependency predictions, never source annotations.

Only preinstalled model data is loaded. Setup/download is a separate CLI.
Offsets are Python Unicode codepoints in the unchanged input substring. Only
CR/LF/tab are replaced with same-length spaces in the model's analysis view.
"""
from __future__ import annotations

import hashlib
import importlib.util
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import threading
import unicodedata
from typing import Any

LOG = logging.getLogger(__name__)
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "runtime/models/odycy/pipeline"
MAX_CHARS = 4096
MAX_TOKENS = 256
LIMITATIONS = [
    "Contextual machine prediction; not a source annotation or a calibrated probability.",
    "One predicted parse; alternatives and correctness are not guaranteed.",
    "Selected spans may omit their syntactic context; lyric, gaps and supplements increase uncertainty.",
    "Frequency lemmatizer excluded; published full-pipeline lemma scores do not apply.",
    "Upstream spaCy range is >=3.7.4,<3.8.0; this integration is locally tested with 3.8.7.",
]


def _token_kind(text: str) -> str:
    if text.isspace():
        return "whitespace"
    if any(unicodedata.category(char)[0] in "LN" for char in text):
        return "lexical"
    if any(char in "[]⟦⟧⟨⟩<>…†‡" for char in text) or text.count(".") >= 2:
        return "editorial"
    return "punctuation"


def _mark_nonlexical(tokens: list[dict]) -> None:
    """Preserve source boundaries; do not display spurious model grammar for them."""
    nonlexical = {t["id"] for t in tokens if _token_kind(t["text"]) in {"whitespace", "editorial"}}
    fields = ("lemma", "upos", "xpos", "features", "head", "deprel")
    for token in tokens:
        token["token_kind"] = _token_kind(token["text"])
        token["prediction_status"] = "predicted"
        token["attachment_status"] = "root" if token["head"] is None else "predicted"
        if token["id"] in nonlexical:
            token["raw_prediction"] = {key: token[key] for key in fields}
            token.update({key: {} if key == "features" else None for key in fields})
            token["prediction_status"] = "not_applicable"
            token["attachment_status"] = "not_applicable"
        elif token["head"] in nonlexical:
            token["raw_prediction"] = {"head": token["head"], "deprel": token["deprel"]}
            token["head"] = None
            token["deprel"] = None
            token["attachment_status"] = "unresolved_nonlexical_head"


class SyntaxProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SyntaxProvider:
    def __init__(self, model_path: str | Path | None = None):
        self.path = Path(model_path or os.environ.get("MELOS_SYNTAX_MODEL_PATH", DEFAULT_PATH)).resolve()
        self._lock = threading.Lock()
        self._nlp: Any = None
        self._ready = False
        self._failure: str | None = None

    def _receipt(self) -> dict:
        try:
            receipt = json.loads((self.path / "melos-provenance.json").read_text(encoding="utf-8"))
            for key in ("provider", "model", "model_version", "revision", "source_url", "artifact_sha256", "license", "annotation_scheme", "files"):
                if not receipt.get(key):
                    raise ValueError(f"Missing {key}")
            return receipt
        except (OSError, ValueError, TypeError) as exc:
            raise SyntaxProviderError("model_unavailable", "Install and verify the syntax model with scripts/setup_syntax_provider.py.") from exc

    def _metadata(self, receipt: dict) -> dict:
        return {
            "provider": receipt["provider"], "model": receipt["model"],
            "adapter_version": "odycy-local-v2",
            "model_version": receipt["model_version"], "annotation_scheme": receipt["annotation_scheme"],
            "evidence_type": "contextual_prediction", "limitations": list(LIMITATIONS),
            "provenance": {key: receipt[key] for key in ("source_url", "revision", "artifact_sha256", "license")},
            "excluded_components": ["frequency_lemmatizer"],
        }

    def status(self) -> dict:
        try:
            receipt = self._receipt()
        except SyntaxProviderError as exc:
            return {"state": "unavailable", "provider": "odycy", "reason": str(exc), "code": exc.code}
        metadata = self._metadata(receipt)
        if self._failure:
            return {**metadata, "state": "error", "reason": self._failure}
        if not all(importlib.util.find_spec(name) is not None for name in ("spacy", "spacy_transformers", "torch")):
            return {**metadata, "state": "unavailable", "code": "runtime_unavailable",
                    "reason": "Optional syntax dependencies are missing in this interpreter; install requirements-syntax.txt."}
        return {**metadata, "state": "ready" if self._ready else "available",
                "verified_in_process": self._ready}

    def _load(self, receipt: dict):
        for item in receipt["files"]:
            path = (self.path / item["path"]).resolve()
            if not path.is_relative_to(self.path) or not path.is_file():
                raise SyntaxProviderError("model_integrity", "Syntax model is incomplete or has unsafe paths.")
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            if h.hexdigest() != item["sha256"]:
                raise SyntaxProviderError("model_integrity", "Syntax model file failed its installation receipt hash.")
        import spacy
        # This is a PyTorch-only adapter. Do not initialize an unrelated optional
        # TensorFlow installation while importing the transformer implementation.
        os.environ.setdefault("USE_TF", "0")
        import spacy_transformers  # noqa: F401: registers model architectures
        spacy.require_cpu()
        # Serialized transformer/tokenizer are in the model archive. Even if a
        # future loader consults a hub identifier, these flags forbid fetching.
        nlp = spacy.load(self.path, exclude=["frequency_lemmatizer"], config={
            "components.transformer.model.tokenizer_config.local_files_only": True,
            "components.transformer.model.transformer_config.local_files_only": True,
        })
        if "parser" not in nlp.pipe_names or "morphologizer" not in nlp.pipe_names:
            raise SyntaxProviderError("model_invalid", "Syntax pipeline lacks required parser or morphology components.")
        nlp.max_length = MAX_CHARS
        return nlp

    def analyze(self, text: str, *, normalize_whitespace: bool = True) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise SyntaxProviderError("invalid_text", "Syntax input must be a nonempty string.")
        if len(text) > MAX_CHARS:
            raise SyntaxProviderError("span_too_large", f"Syntax input exceeds {MAX_CHARS} codepoints.")
        if not self._lock.acquire(blocking=False):
            raise SyntaxProviderError("provider_busy", "Syntax provider is busy; retry shortly.")
        try:
            receipt = self._receipt()
            if self._failure:
                raise SyntaxProviderError("provider_failed", self._failure)
            if self._nlp is None:
                self._nlp = self._load(receipt)
            # Position-preserving analysis view: every source character still
            # occupies exactly one codepoint. No Greek letter, combining mark,
            # punctuation or editorial sign is changed or restored.
            model_text = text.translate(str.maketrans({"\r": " ", "\n": " ", "\t": " "})) if normalize_whitespace else text
            preprocessing = {
                "name": "ascii_whitespace_to_space_v1" if normalize_whitespace else "identity",
                "position_preserving": True,
                "characters_replaced": sum(a != b for a, b in zip(text, model_text)),
                "model_input_sha256": hashlib.sha256(model_text.encode("utf-8")).hexdigest(),
            }
            doc = self._nlp.make_doc(model_text)
            if len(doc) > MAX_TOKENS:
                raise SyntaxProviderError("span_too_large", f"Syntax input exceeds {MAX_TOKENS} model tokens.")
            doc = self._nlp(doc)
            if doc.text != model_text:
                raise SyntaxProviderError("offset_mismatch", "Syntax tokenizer changed the analysis view.")
            tokens = []
            sentence_id = -1
            for token in doc:
                if token.is_sent_start:
                    sentence_id += 1
                start, end = token.idx, token.idx + len(token.text)
                if model_text[start:end] != token.text:
                    raise SyntaxProviderError("offset_mismatch", "Syntax prediction cannot be aligned to the unchanged source.")
                tokens.append({"id": token.i, "text": text[start:end], "start": start, "end": end,
                               "lemma": token.lemma_ or None, "upos": token.pos_, "xpos": token.tag_,
                               "features": token.morph.to_dict(), "head": None if token.head.i == token.i else token.head.i,
                               "deprel": token.dep_, "sentence_id": max(sentence_id, 0)})
                if text[start:end] != token.text:
                    tokens[-1]["model_text"] = token.text
            if any(t["head"] is not None and not 0 <= t["head"] < len(tokens) for t in tokens):
                raise SyntaxProviderError("invalid_heads", "Syntax provider emitted an invalid dependency head.")
            _mark_nonlexical(tokens)
            self._ready = True
            metadata = self._metadata(receipt)
            metadata["provenance"]["runtime_versions"] = {
                name: importlib.metadata.version(name)
                for name in ("spacy", "spacy-transformers", "torch", "transformers")
            }
            return {**metadata, "state": "ready", "tokens": tokens,
                    "offset_unit": "unicode_codepoint", "source_text_unchanged": True,
                    "model_input_identical": model_text == text,
                    "parser_input_preprocessing": preprocessing}
        except SyntaxProviderError as exc:
            if exc.code in {"model_integrity", "model_invalid", "offset_mismatch", "invalid_heads"}:
                self._failure = str(exc)
            raise
        except Exception as exc:
            LOG.exception("Local syntax provider failed")
            self._failure = f"Local syntax provider failed ({type(exc).__name__}); check the installed model and runtime."
            raise SyntaxProviderError("provider_failed", self._failure) from exc
        finally:
            self._lock.release()


_provider: SyntaxProvider | None = None
_provider_lock = threading.Lock()


def _get_provider() -> SyntaxProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = SyntaxProvider()
        return _provider


def status() -> dict:
    return _get_provider().status()


def analyze(text: str) -> dict:
    return _get_provider().analyze(text)
