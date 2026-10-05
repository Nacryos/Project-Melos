"""Explicit, offline-after-setup OdyCy acquisition; never called by the API.

Run --download, review the raw artifacts, then --extract.  The upstream wheel is
treated as an archive of model data: its Python/custom factory code is not run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

MODEL = "chcaa/grc_odycy_joint_trf"
REVISION = "83046e93fa6b5dee122c3ca7cff1377512928143"
WHEEL = "grc_odycy_joint_trf-0.7.0-py3-none-any.whl"
SHA256 = "8a828bb5d105e0f2d85d22479ab487fd9b5bacb9fdfb7098245e5e5aaefecd5e"
SIZE = 497296758
BASE = f"https://huggingface.co/{MODEL}/resolve/{REVISION}"
CODE_LICENSE = "https://raw.githubusercontent.com/centre-for-humanities-computing/odyCy/8ae05e7e26de60f0d2c56a5235f50a46849dfedc/LICENSE"
DEFAULT = Path(__file__).resolve().parents[1] / "runtime/models/odycy"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url: str, path: Path, limit: int) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    temporary = path.with_suffix(path.suffix + ".partial")
    total = 0
    with urllib.request.urlopen(url, timeout=90) as response, temporary.open("xb") as out:
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > limit:
                raise ValueError("Upstream artifact exceeds download limit")
            out.write(block)
    temporary.rename(path)


def download(root: Path) -> None:
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    artifacts = [(f"https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true", "model-api.json", 2_000_000),
                 (f"{BASE}/README.md", "README.md", 2_000_000),
                 (CODE_LICENSE, "code-LICENSE.txt", 50_000),
                 (f"{BASE}/{WHEEL}", WHEEL, SIZE)]
    for url, name, limit in artifacts:
        dest = raw / name
        if not dest.exists():
            print(f"Downloading {name}", flush=True)
            fetch(url, dest, limit)
    wheel = raw / WHEEL
    if wheel.stat().st_size != SIZE or digest(wheel) != SHA256:
        raise ValueError("Downloaded model wheel fails pinned size/SHA256 verification")
    api = json.loads((raw / "model-api.json").read_text(encoding="utf-8"))
    item = next(x for x in api["siblings"] if x["rfilename"] == WHEEL)
    if api["sha"] != REVISION or item["lfs"]["sha256"] != SHA256:
        raise ValueError("Raw upstream metadata disagrees with pinned release")
    raw_receipt = {"verified_at_utc": datetime.now(timezone.utc).isoformat(),
                   "artifacts": [{"url": url, "path": name, "bytes": (raw/name).stat().st_size,
                                  "sha256": digest(raw/name)} for url, name, _ in artifacts]}
    (raw / "download-receipt.json").write_text(json.dumps(raw_receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Download verified: {SHA256}", flush=True)


def extract(root: Path) -> None:
    wheel = root / "raw" / WHEEL
    if digest(wheel) != SHA256:
        raise ValueError("Refusing to extract unverified wheel")
    target = root / "pipeline"
    files = []
    with zipfile.ZipFile(wheel) as archive:
        config = [x for x in archive.namelist() if x.endswith("/config.cfg")]
        if len(config) != 1:
            raise ValueError("Expected exactly one pipeline")
        prefix = config[0].removesuffix("config.cfg")
        for member in archive.infolist():
            if not member.filename.startswith(prefix) or member.is_dir():
                continue
            relative = Path(member.filename.removeprefix(prefix))
            if relative.is_absolute() or ".." in relative.parts or relative.suffix == ".py":
                raise ValueError("Unexpected executable or unsafe model member")
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                with archive.open(member) as src:
                    expected = hashlib.file_digest(src, "sha256").hexdigest()
                if digest(dest) != expected:
                    raise ValueError(f"Refusing to overwrite changed installed file: {dest}")
            else:
                with archive.open(member) as src, dest.open("xb") as out:
                    shutil.copyfileobj(src, out)
            files.append({"path": relative.as_posix(), "bytes": dest.stat().st_size, "sha256": digest(dest)})
        licenses = [x for x in archive.namelist() if ".dist-info/" in x and "LICENSE" in x.upper()]
        for i, name in enumerate(licenses):
            (root / "raw" / f"LICENSE-{i}.txt").write_bytes(archive.read(name))
    metadata = json.loads((target / "meta.json").read_text(encoding="utf-8"))
    api = json.loads((root / "raw/model-api.json").read_text(encoding="utf-8"))
    receipt = {"provider": "odycy", "model": MODEL, "model_version": metadata["version"],
               "revision": REVISION, "source_url": f"https://huggingface.co/{MODEL}/tree/{REVISION}",
               "artifact_url": f"{BASE}/{WHEEL}", "artifact_sha256": SHA256,
               "license": api["cardData"]["license"], "annotation_scheme": "Universal Dependencies",
               "download": json.loads((root / "raw/download-receipt.json").read_text(encoding="utf-8")),
               "license_basis": "License declaration in pinned HF model card/API (wheel meta.json license is empty); separate upstream code license retained in raw/.",
               "excluded_components": ["frequency_lemmatizer"], "files": files}
    (target / "melos-provenance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(files)} verified files to {target}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--download", action="store_true")
    operation.add_argument("--extract", action="store_true")
    args = parser.parse_args()
    (download if args.download else extract)(args.root.resolve())
