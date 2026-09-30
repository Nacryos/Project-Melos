"""Lazy, project-local Qwen3 adapter for evidence-bound candidate selection.

Importing this module and checking status never loads the model. Weights load
only when decide() is called, and are never downloaded by a request handler.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data/cache/local_models/qwen3-1.7b-70d244c"
MODEL_ID = "Qwen/Qwen3-1.7B"
REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
MODEL_LABEL = f"{MODEL_ID}@{REVISION}"
MAX_INPUT_TOKENS = 4096
MAX_OUTPUT_TOKENS = 128

_lock = threading.Lock()
_model: Any = None
_tokenizer: Any = None
_device: str | None = None


def local_model_status() -> dict[str, Any]:
    required = ("model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors",
                "model.safetensors.index.json", "config.json", "tokenizer.json")
    return {
        "model": MODEL_LABEL,
        "installed": all((MODEL_DIR / name).is_file() for name in required),
        "loaded": _model is not None,
        "device": _device,
        "license": "Apache-2.0",
        "validated": False,
        "recommended": False,
        "reason": "Exploratory source-backed pilot is too small to validate Ancient Greek decisions; explicit opt-in only.",
    }


def _load_model() -> tuple[Any, Any, str]:
    global _model, _tokenizer, _device
    if _model is not None:
        return _tokenizer, _model, _device
    if not local_model_status()["installed"]:
        raise RuntimeError("Local Qwen3 model is not installed in project cache")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        free_bytes, _ = torch.cuda.mem_get_info()
        if free_bytes < 5_000_000_000:
            raise RuntimeError("Insufficient free GPU memory for local classifier")
    dtype = torch.float16 if device == "cuda" else torch.float32
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
        )
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
            dtype=dtype, low_cpu_mem_usage=True,
        ).to(device).eval()
    except (RuntimeError, OSError, ValueError) as exc:
        if device == "cuda":
            torch.cuda.empty_cache()
        raise RuntimeError(f"Could not load local classifier: {exc}") from exc
    _tokenizer, _model, _device = tokenizer, model, device
    return tokenizer, model, device


def _parse_choice(output: str, valid_ids: set[str]) -> str:
    # Chat models sometimes wrap otherwise valid JSON in one fenced block.
    # Strip only that exact wrapper; never mine a larger response for a choice.
    if output.startswith("```json\n") and output.endswith("\n```"):
        output = output[len("```json\n"):-len("\n```")]
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Local classifier returned invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("choice"), str):
        raise RuntimeError("Local classifier returned no string choice")
    choice = value["choice"]
    if choice not in valid_ids | {"abstain"}:
        raise RuntimeError("Local classifier selected an unknown candidate")
    return choice


class LocalModelProvider:
    """DecisionProvider-compatible adapter, with bounded local-only inference."""

    def decide(self, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        candidate_ids = {str(c["id"]) for c in packet["candidates"]}
        if not candidate_ids:
            raise RuntimeError("No candidate IDs supplied")
        task = (
            "Choose the best candidate for the exact Greek passage and form, using "
            "only the supplied source evidence. Source claims may conflict and a "
            "dictionary entry does not prove passage attestation. If the evidence "
            "cannot distinguish candidates, choose abstain. Output exactly one JSON "
            "object with a choice string equal to an existing candidate ID or abstain. "
            "No explanation or markdown.\n"
            + json.dumps(packet, ensure_ascii=False, default=str)
        )
        with _lock:
            tokenizer, model, device = _load_model()
            prompt = tokenizer.apply_chat_template(
                [{"role": "system", "content": "You are a cautious Ancient Greek evidence reranker."},
                 {"role": "user", "content": task}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
            inputs = tokenizer(prompt, return_tensors="pt").to(device)
            count = int(inputs.input_ids.shape[1])
            if count > MAX_INPUT_TOKENS:
                raise RuntimeError(f"Evidence packet is {count} tokens; maximum is {MAX_INPUT_TOKENS}")
            import torch
            before = time.perf_counter()
            try:
                with torch.inference_mode():
                    generated = model.generate(
                        **inputs, max_new_tokens=MAX_OUTPUT_TOKENS,
                        do_sample=False, pad_token_id=tokenizer.eos_token_id,
                    )
                if device == "cuda":
                    torch.cuda.synchronize()
            except torch.cuda.OutOfMemoryError as exc:
                torch.cuda.empty_cache()
                raise RuntimeError("Local classifier ran out of GPU memory") from exc
            elapsed = time.perf_counter() - before
            completion = generated[0, count:]
            output = tokenizer.decode(completion, skip_special_tokens=True).strip()
        choice = _parse_choice(output, candidate_ids)
        return {"choice": choice, "model": MODEL_LABEL, "raw_output": output,
                "usage": {"input_tokens": count,
                          "output_tokens": int(completion.shape[0]),
                          "seconds": round(elapsed, 3), "device": device}}


__all__ = ["LocalModelProvider", "local_model_status"]
