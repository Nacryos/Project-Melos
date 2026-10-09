"""Sentence encoders for release S dense retrieval (offline batch encoding and query-time encoding).

Every model is pinned to a revision. ``Encoder(name).encode(texts, query=...)`` returns L2-normalised
float32 vectors. No text is sent to a hosted service: models load from a local Hugging Face cache
(``MELOS_S_MODEL_CACHE``, or the default cache when unset).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

MODELS = {
    # name: (hub id, revision, query prompt, document prompt, max tokens, loader)
    "sphilberta": ("bowphs/SPhilBerta", "5d0736d2df4063b862e186e7224e3066cd16ad2c", "", "", 512, "st"),
    "shlm": ("kevinkrahn/shlm-grc-en", "bfc43f7cdc541e7cb7f76ae1fefca54a216035e4", "", "", 256, "hlm"),
    "qwen3": ("Qwen/Qwen3-Embedding-0.6B", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
              "Instruct: Given a search query about ancient Greek poetry (an English concept, image or motif, "
              "or Greek words), retrieve Greek passages, translations or notes that contain it\nQuery: ", "", 512, "st"),
    "bge-m3": ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", "", "", 512, "st"),
}


def model_cache():
    return os.getenv("MELOS_S_MODEL_CACHE") or None


class Encoder:
    """One loaded model; ``encode(texts, query=False)`` returns L2-normalised float32 vectors."""

    def __init__(self, name, device=None, cache_dir=None, half=True):
        import torch
        hub, revision, self.query_prompt, self.doc_prompt, self.max_tokens, loader = MODELS[name]
        self.name, self.hub, self.revision, self.loader = name, hub, revision, loader
        cache_dir = cache_dir or model_cache()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        if loader == "st":
            from sentence_transformers import SentenceTransformer
            kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if (half and self.device == "cuda") else {}
            self.model = SentenceTransformer(hub, revision=revision, device=self.device, cache_folder=cache_dir, **kwargs)
            self.model.max_seq_length = self.max_tokens
        else:
            # The model's own code (pinned revision). Its tokenizer class is not registered in
            # tokenizer_config.json, so it is imported from the snapshot directly.
            import importlib.util
            from huggingface_hub import snapshot_download
            from transformers import AutoModel
            local = snapshot_download(hub, revision=revision, cache_dir=cache_dir)
            spec = importlib.util.spec_from_file_location("tokenization_hlm", Path(local) / "tokenization_hlm.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.tokenizer = module.HLMTokenizer.from_pretrained(local)
            self.model = AutoModel.from_pretrained(local, trust_remote_code=True).to(self.device).eval()

    def encode(self, texts, query=False, batch_size=32):
        prompt = self.query_prompt if query else self.doc_prompt
        texts = [prompt + t for t in texts] if prompt else list(texts)
        if self.loader == "st":
            return np.asarray(self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                                convert_to_numpy=True, show_progress_bar=False), dtype=np.float32)
        import torch
        out = []
        for start in range(0, len(texts), batch_size):
            enc = self.tokenizer(texts[start:start + batch_size], padding=True, truncation=True,
                                 max_length=self.max_tokens, return_tensors="pt")
            enc = {k: v.to(self.device) for k, v in enc.items()}
            with torch.no_grad():
                vec = self.model(**enc)[0][:, 0]  # CLS pooling, as the model card prescribes
            out.append(torch.nn.functional.normalize(vec.float(), dim=-1).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 1), np.float32)
