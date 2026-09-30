"""Estimate a depth map for each hero painting (near = white) for the mosaic relief.

Uses Depth Anything V2 Small via transformers; runs once, offline. Output goes to
assets/source/depth/<name>.png, which tools/build_images.py then publishes.

Run from the repo root:  python tools/build_depth.py
"""
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageFilter
from transformers import pipeline

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "source"
OUT = SRC / "depth"
MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
WIDTH = 512


def main():
    OUT.mkdir(exist_ok=True)
    pipe = pipeline("depth-estimation", model=MODEL, device=0 if torch.cuda.is_available() else -1)
    for src in sorted(SRC.glob("*.jpg")):
        im = Image.open(src).convert("RGB")
        d = pipe(im)["predicted_depth"].squeeze().float().cpu().numpy()   # relative inverse depth: larger = nearer
        lo, hi = np.percentile(d, [2, 98])
        d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        out = Image.fromarray((d * 255).astype(np.uint8), "L")
        out = out.resize((WIDTH, round(WIDTH * im.height / im.width)), Image.BICUBIC)
        out = out.filter(ImageFilter.GaussianBlur(1.2))   # soften model noise; tiles quantise it anyway
        out.save(OUT / f"{src.stem}.png")
        print(f"{src.stem}: depth {out.size}")


if __name__ == "__main__":
    main()
