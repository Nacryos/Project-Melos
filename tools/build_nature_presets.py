"""Compress the five approved landscape paintings into static header assets.

Run with Python and Pillow 12.2.0 (libwebp 1.6.0 for byte-identical output):
    python tools/build_nature_presets.py
    python tools/build_nature_presets.py --check

Only uniform resizing and WebP encoding are performed. Originals are never
modified. The reader applies its own dark overlay; none is baked into the art.
--check validates the shipped files without needing the ignored source gallery.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, __version__ as pillow_version, features


ROOT = Path(__file__).resolve().parents[1]
GALLERY = Path("output/imagegen/nature-gallery/landscape")
ASSETS = Path("assets/nature-presets")
MANIFEST = Path("data/nature-presets.json")
# Locked to the user's selections: Study 03 for sea/river, Study 01 otherwise.
APPROVED = {
    "sea_coast": (
        "sea_coast-retry-f8e7ecc07804",
        "7caa4c3705cf714f1a71d541cb8de9af290c89592db6d7a08e67016bfb79ede7",
    ),
    "garden_grove": (
        "garden_grove-landscape-01",
        "50518ee6c2801c5752049e24bd2030455a1241742bf80ca638f9bf5ea185c77b",
    ),
    "meadow_pasture": (
        "meadow_pasture-landscape-01",
        "1a0bf06089f21d7aa77dd3b79a75ea53e514fd559544db627ad94c41f6b439c9",
    ),
    "mountain_woodland": (
        "mountain_woodland-landscape-01",
        "fc313131db064d2052e01e2c71e7893961f07acf7162e12dd2154c41d1b330ab",
    ),
    "river_spring": (
        "river_spring-retry-9198a60e6c8a",
        "901e73d49f87c9dec9ec70b4ac980166320e74e5ce61d0d099e87fa1acd63974",
    ),
}
VARIANTS = ((960, 72), (480, 68))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build(root: Path = ROOT) -> dict:
    gallery = root / GALLERY
    gallery_manifest = json.loads((gallery / "manifest.json").read_text("utf-8"))
    themes = {theme["id"]: theme for theme in gallery_manifest["themes"]}
    manifest = {
        "version": 1,
        "default_preset_id": "garden_grove",
        "generator": {
            "script": "tools/build_nature_presets.py",
            "pillow": pillow_version,
            "libwebp": features.version("webp"),
            "resize": "LANCZOS; preserve complete landscape; no crop or overlay",
            "webp_method": 6,
        },
        "presets": [],
    }
    # Resolve and validate every source before writing any asset.
    sources = []
    for theme_id, (source_id, source_hash) in APPROVED.items():
        theme = themes[theme_id]
        source = next(item for item in theme["images"] if item["id"] == source_id)
        require(source["status"] == "ready", f"Source not ready: {source_id}")
        source_path = (gallery / source["path"]).resolve()
        require(source_path.is_relative_to(gallery.resolve()), "Source escaped gallery")
        source_bytes = source_path.read_bytes()
        require(digest(source_bytes) == source_hash == source["sha256"],
                f"Approved source hash mismatch: {source_id}")
        with Image.open(BytesIO(source_bytes)) as image:
            require(image.size == (1536, 1024), f"Unexpected source size: {source_id}")
            source_image = image.convert("RGB")
        sources.append((theme_id, theme, source, source_image))

    (root / ASSETS).mkdir(parents=True, exist_ok=True)
    for theme_id, theme, source, source_image in sources:
        variants = []
        for width, quality in VARIANTS:
            height = round(source_image.height * width / source_image.width)
            resized = source_image.resize((width, height), Image.Resampling.LANCZOS)
            encoded = BytesIO()
            resized.save(encoded, format="WEBP", quality=quality, method=6)
            payload = encoded.getvalue()
            checksum = digest(payload)
            filename = f"{theme_id}-{width}.{checksum[:12]}.webp"
            destination = root / ASSETS / filename
            if destination.exists():
                require(destination.read_bytes() == payload,
                        f"Content-addressed asset collision: {filename}")
            else:
                destination.write_bytes(payload)
            variants.append({
                "url": "/" + (ASSETS / filename).as_posix(),
                "width": width,
                "height": height,
                "quality": quality,
                "sha256": checksum,
                "bytes": len(payload),
            })
        manifest["presets"].append({
            "id": theme_id,
            "title": theme["title"],
            **variants[0],
            "variants": variants,
            "provenance": {
                "source_image_id": source["id"],
                "source_path": (GALLERY / source["path"]).as_posix(),
                "source_sha256": APPROVED[theme_id][1],
                "source_width": source_image.width,
                "source_height": source_image.height,
                "parent_image_id": source["parent_image_id"],
                "source_model": source["model"],
                "approval": "User-selected landscape favourite",
            },
        })
    (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return manifest


def verify(root: Path = ROOT) -> dict:
    manifest = json.loads((root / MANIFEST).read_text("utf-8"))
    require(manifest["version"] == 1, "Unexpected manifest version")
    require(manifest["default_preset_id"] == "garden_grove", "Unexpected neutral default")
    require([item["id"] for item in manifest["presets"]] == list(APPROVED),
            "Preset inventory differs from approved selection")
    for preset in manifest["presets"]:
        source_id, source_hash = APPROVED[preset["id"]]
        require(preset["provenance"]["source_image_id"] == source_id,
                f"Unexpected source for {preset['id']}")
        require(preset["provenance"]["source_sha256"] == source_hash,
                f"Unexpected source hash for {preset['id']}")
        require(all(preset[key] == preset["variants"][0][key]
                    for key in ("url", "width", "height", "quality", "sha256", "bytes")),
                "Primary asset does not match largest variant")
        require([(v["width"], v["quality"]) for v in preset["variants"]] == list(VARIANTS),
                "Unexpected variant inventory")
        for variant in preset["variants"]:
            filename = f"{preset['id']}-{variant['width']}.{variant['sha256'][:12]}.webp"
            require(variant["url"] == "/" + (ASSETS / filename).as_posix(),
                    "Unexpected content-addressed URL")
            payload = (root / ASSETS / filename).read_bytes()
            require(digest(payload) == variant["sha256"], f"Asset hash mismatch: {filename}")
            require(len(payload) == variant["bytes"] < 160_000,
                    f"Asset size mismatch or excessive transfer size: {filename}")
            with Image.open(BytesIO(payload)) as image:
                require(image.format == "WEBP", f"Unexpected asset format: {filename}")
                require(image.size == (variant["width"], variant["height"])
                        and image.width * 2 == image.height * 3,
                        f"Asset dimensions/aspect ratio mismatch: {filename}")
                image.load()
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify shipped assets only")
    args = parser.parse_args()
    if not args.check:
        build()
    result = verify()
    for item in result["presets"]:
        sizes = ", ".join(f"{v['width']}x{v['height']}: {v['bytes']:,} bytes"
                          for v in item["variants"])
        print(f"{item['id']}: {sizes}")
