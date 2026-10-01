"""Copy the independently audited QA22 raw responses; no requests or data authoring."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".benchmarks/qa22-morpheus"
REPORT_SHA = "309971d893a9ed954222ada369abe8bed3fd747285b3ecfdba521ad70af9a9e9"


def main():
    report_raw = (SOURCE / "report.json").read_bytes()
    if hashlib.sha256(report_raw).hexdigest() != REPORT_SHA:
        raise ValueError("QA22 audited report hash mismatch")
    report = json.loads(report_raw)
    out = ROOT / "tests/fixtures/machine_morphology"
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for i, sample in enumerate(report["samples"]):
        response = sample["response"]
        raw = (ROOT / response["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != response["raw_sha256"]:
            raise ValueError("Audited raw response hash mismatch")
        name = f"response-{i:02}.json"
        target = out / name
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Refusing to replace differing fixture")
        target.write_bytes(raw)
        records.append({"file": name, **sample})
    manifest = {"provenance": "Audited QA22 public Alpheios service diagnostic; machine analyses, not attestations.",
                "report_sha256": REPORT_SHA, "engine_revision": None, "samples": records,
                "limitations": report["limitations"]}
    negative_dir = ROOT / ".benchmarks/qa23-negative"
    negative_report = (negative_dir / "report.json").read_bytes()
    if hashlib.sha256(negative_report).hexdigest() != "3b549f0d348361f3899059704df8ff1e0bb62c7aef0d2106a42cac383749cf7a":
        raise ValueError("QA23 audited negative report hash mismatch")
    negative = json.loads(negative_report)
    raw = (negative_dir / "response.raw").read_bytes()
    if hashlib.sha256(raw).hexdigest() != negative["raw_sha256"]:
        raise ValueError("Negative response hash mismatch")
    (out / "negative-control.json").write_bytes(raw)
    manifest["negative_control"] = {"file": "negative-control.json", **negative}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(f"Copied {len(records)} verified raw responses")


if __name__ == "__main__":
    main()
