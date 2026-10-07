"""Copy independently audited raw elision responses; no requests or data rows."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "runtime/elision-protocol"
OUT = Path(__file__).resolve().parent / "elision"


def main():
    raw_report = (SOURCE / "report.json").read_bytes()
    report = json.loads(raw_report)
    OUT.mkdir(exist_ok=True)
    for sample in report["samples"]:
        raw = (SOURCE / sample["raw_file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sample["receipt"]["raw_sha256"]:
            raise ValueError("Raw source hash mismatch")
        path = OUT / sample["raw_file"]
        if path.exists() and path.read_bytes() != raw:
            raise ValueError("Refusing to overwrite differing fixture")
        path.write_bytes(raw)
    target = OUT / "manifest.json"
    if target.exists() and target.read_bytes() != raw_report:
        raise ValueError("Refusing to overwrite differing manifest")
    target.write_bytes(raw_report)
    print("Copied", len(report["samples"]), "raw elision responses without changing their bytes")


if __name__ == "__main__":
    main()
