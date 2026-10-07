"""Extract bounded Campbell commentary evidence from the user-supplied PDF.

No authored linguistic content: source text, coordinates, and OCR receipts only.
One-based PDF pages and PDF-point bounds are explicit selection metadata.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
from pathlib import Path

import fitz

SOURCE_SHA256 = "8cbdd94c38c824b7c7eb2920cafac13ac988038cabfe74ddf4f3139e7fa33b9f"
REGIONS = [
    ("34a", 321, (24, 209, 260, 440)),
    ("34a", 322, (36, 49, 270, 286)),
    ("129", 325, (23, 355, 259, 434)),
    ("129", 326, (25, 44, 271, 440)),
    ("129", 327, (23, 43, 271, 440)),
    ("129", 328, (25, 43, 263, 119)),
    ("130b", 328, (25, 125, 263, 432)),
    ("130b", 329, (15, 40, 249, 238)),
    ("326", 330, (32, 232, 269, 434)),
    ("326", 331, (24, 39, 261, 145)),
    ("350", 334, (29, 233, 267, 434)),
    ("350", 335, (18, 43, 255, 119)),
]
PROMPT = """Act only as a diplomatic OCR engine. Transcribe ALL printed commentary in this
crop from David A. Campbell, Greek Lyric Poetry. This is image transcription, not
interpretation. Preserve English, Greek polytonic accents/breathings/underdots,
uncertainty brackets, punctuation, scholarly abbreviations and cited line numbers.
Do not correct, supplement, translate, paraphrase or use memorized material.
Output JSON {paragraphs:[{kind:'heading'|'introduction'|'metre'|'note'|'continuation',
line_label:string,lemma:string,text:string}], uncertainty:[string]}.
Use line_label only for an explicitly printed marginal note number (e.g. 1., 6-7.).
Use lemma only for explicitly printed note-heading words before a colon or equals
sign; copy those words, never infer dictionary headwords. All fields other than
kind must be copied from pixels. text must include the COMPLETE paragraph,
including its printed number and lemma. Keep distinct unnumbered lemma paragraphs
separate. A crop may start or end mid-paragraph: transcribe visible text only,
label continuation and mention any incomplete edge in uncertainty. Line-wrap
hyphens are preserved. Use U+FFFD for unreadable characters and explain; do not guess.
Do not omit prose even if it has no Greek lemma. No explanation outside JSON."""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def extract(source: Path, out: Path) -> None:
    if digest(source) != SOURCE_SHA256:
        raise ValueError("Source PDF hash mismatch")
    out.mkdir(parents=True, exist_ok=True)
    receipts = []
    with fitz.open(source) as doc:
        for fragment, page_num, bounds in REGIONS:
            page = doc[page_num-1]
            stem = f"alcaeus-{fragment}-p{page_num}"
            clip = fitz.Rect(bounds)
            image = out / f"{stem}.png"
            raw = out / f"{stem}.embedded.txt"
            blocks = out / f"{stem}.blocks.json"
            page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip).save(image)
            raw.write_text(page.get_text("text", clip=clip), encoding="utf-8")
            write_json(blocks, page.get_text("dict", clip=clip,
                flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES))
            receipts.append({"fragment": fragment, "pdf_page": page_num,
                "printed_page": page_num-32, "bounds_pdf_points": bounds,
                "source_sha256": SOURCE_SHA256, "image_file": image.name,
                "image_sha256": digest(image), "embedded_text_file": raw.name,
                "embedded_text_sha256": digest(raw), "blocks_file": blocks.name,
                "blocks_sha256": digest(blocks), "method": "PyMuPDF source-bound extraction; no repairs"})
    write_json(out / "source-receipts.json", {"source": str(source.resolve()),
        "source_sha256": SOURCE_SHA256, "license": "user_supplied_edition_excerpt",
        "regions": receipts})


def split_failed(source: Path, out: Path) -> None:
    """One explicit two-part retry; choose a blank row near each crop midpoint."""
    from PIL import Image
    if digest(source) != SOURCE_SHA256:
        raise ValueError("Source PDF hash mismatch")
    target = out / "retry-source-receipts.json"
    if target.exists():
        raise FileExistsError("Only one split retry stage is authorized")
    original = json.loads((out / "source-receipts.json").read_text(encoding="utf-8"))
    regions = []
    with fitz.open(source) as doc:
        for parent in original["regions"]:
            stem = Path(parent["image_file"]).stem
            if not (out / f"{stem}.error.json").exists():
                continue
            if (out / f"{stem}.vision.parsed.json").exists():
                raise ValueError("Failure has a parsed artifact; requires manual disposition")
            if digest(out / parent["image_file"]) != parent["image_sha256"]:
                raise ValueError("Parent image changed before split selection")
            image = Image.open(out / parent["image_file"]).convert("L")
            center = image.height // 2
            # Source geometry only: blank horizontal row avoids cutting printed glyphs.
            candidates = range(max(0, center-80), min(image.height, center+81))
            scores = [(sum(255-v for v in image.crop((0,y,image.width,y+1)).getdata()), abs(y-center), y)
                for y in candidates]
            _, _, split_row = min(scores)
            x0,y0,x1,y1 = parent["bounds_pdf_points"]
            split_y = y0 + split_row/4
            for part, bounds in enumerate(((x0,y0,x1,split_y),(x0,split_y,x1,y1)), 1):
                child = f"{stem}-retry-half{part}"
                page = doc[parent["pdf_page"]-1]
                clip = fitz.Rect(bounds)
                image_path, text_path, block_path = (out / f"{child}{suffix}" for suffix in
                    (".png", ".embedded.txt", ".blocks.json"))
                page.get_pixmap(matrix=fitz.Matrix(4,4),clip=clip).save(image_path)
                text_path.write_text(page.get_text("text",clip=clip),encoding="utf-8")
                write_json(block_path,page.get_text("dict",clip=clip,
                    flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES))
                regions.append({**parent,"bounds_pdf_points":bounds,
                    "image_file":image_path.name,"image_sha256":digest(image_path),
                    "embedded_text_file":text_path.name,"embedded_text_sha256":digest(text_path),
                    "blocks_file":block_path.name,"blocks_sha256":digest(block_path),
                    "parent_image_file":parent["image_file"],"parent_image_sha256":parent["image_sha256"],
                    "split_method":"minimum-ink horizontal row within 20 PDF points of midpoint",
                    "retry_attempt":1})
    write_json(target,{"source_sha256":SOURCE_SHA256,"regions":regions})


def vision(out: Path, model: str, only: list[str] | None, retry: bool = False) -> None:
    from dotenv import load_dotenv
    from openai import OpenAI
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    load_dotenv(root / "secrets/nature-gallery.env", encoding="utf-8-sig")
    client = OpenAI(timeout=240, max_retries=0)
    receipt_file = "retry-source-receipts.json" if retry else "source-receipts.json"
    regions = json.loads((out / receipt_file).read_text(encoding="utf-8"))["regions"]
    if only:
        regions = [r for r in regions if Path(r["image_file"]).stem in only]
        if len(regions) != len(set(only)):
            raise ValueError("Requested image not in source receipts")

    def one(r: dict) -> str:
        stem = Path(r["image_file"]).stem
        raw = out / f"{stem}.vision.raw.json"
        if raw.exists():
            raise FileExistsError(raw)
        image = out / r["image_file"]
        if digest(image) != r["image_sha256"]:
            raise ValueError("Source crop changed")
        write_json(out / f"{stem}.vision.request.json", {"model": model,
            "prompt": PROMPT, "source": r, "max_output_tokens": 6500,
            "reasoning_effort": "high", "retry_policy": "none"})
        response = client.responses.create(model=model, store=False,
            reasoning={"effort": "high"}, max_output_tokens=6500,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": PROMPT},
                {"type": "input_image", "image_url": "data:image/png;base64," +
                 base64.b64encode(image.read_bytes()).decode(), "detail": "original"}]}],
            text={"format": {"type": "json_object"}})
        raw.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        parsed = json.loads(response.output_text)
        parsed_path = out / f"{stem}.vision.parsed.json"
        write_json(parsed_path, parsed)
        write_json(out / f"{stem}.vision.receipt.json", {"source": r,
            "raw_file": raw.name, "raw_sha256": digest(raw),
            "parsed_file": parsed_path.name, "parsed_sha256": digest(parsed_path),
            "usage": response.usage.model_dump() if response.usage else None})
        return stem

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = {pool.submit(one, r): r for r in regions}
        for task in concurrent.futures.as_completed(tasks):
            try:
                print("OCR saved", task.result(), flush=True)
            except Exception as exc:
                r = tasks[task]
                failure = {"image": r["image_file"], "type": type(exc).__name__, "error": str(exc)}
                failures.append(failure)
                write_json(out / (Path(r["image_file"]).stem + ".error.json"), failure)
                print("OCR FAILED", r["image_file"], type(exc).__name__, flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} OCR requests failed; no automatic retries")


def package(out: Path, approval_path: Path | None = None, allow_pending: bool = False) -> None:
    receipts = json.loads((out / "source-receipts.json").read_text(encoding="utf-8"))
    retry_path = out / "retry-source-receipts.json"
    if retry_path.exists():
        retries = json.loads(retry_path.read_text(encoding="utf-8"))["regions"]
        ordered = []
        for original in receipts["regions"]:
            children = [r for r in retries if r["parent_image_file"] == original["image_file"]]
            ordered.extend(children or [original])
        receipts["regions"] = ordered
    approval = json.loads(approval_path.read_text(encoding="utf-8")) if approval_path else None
    if approval is not None and approval.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("Approval is not bound to the source PDF")
    grouped = {}
    pending = {}
    inherited_labels = {}
    for r in receipts["regions"]:
        stem = Path(r["image_file"]).stem
        parsed_path = out / f"{stem}.vision.parsed.json"
        if not parsed_path.exists():
            if not allow_pending:
                raise FileNotFoundError(parsed_path)
            error_path = out / f"{stem}.error.json"
            if not error_path.exists():
                raise ValueError("Cannot mark unattempted OCR as pending failure")
            pending.setdefault(r["fragment"], []).append({"source":r,
                "error_file":error_path.name,"error_sha256":digest(error_path),
                "status":"unresolved_ocr_not_for_text_display"})
            # Do not inherit a note label across an untranscribed source gap.
            inherited_labels.pop(r["fragment"], None)
            continue
        data = json.loads(parsed_path.read_text(encoding="utf-8"))
        verdict = approval.get("chunks", {}).get(parsed_path.name, {}) if approval is not None else {}
        if approval is not None and (verdict.get("verdict") != "PASS" or verdict.get("sha256") != digest(parsed_path)):
            raise ValueError(f"Missing hash-bound independent approval: {parsed_path.name}")
        paragraphs = data["paragraphs"]
        for i, paragraph in enumerate(paragraphs):
            if not isinstance(paragraph.get("text"), str) or not paragraph["text"]:
                raise ValueError(f"Missing source text: {parsed_path}, paragraph {i}")
            label = paragraph.get("line_label", "")
            if label:
                inherited_labels[r["fragment"]] = label
            paragraph["anchor_line_label"] = inherited_labels.get(r["fragment"], "")
            paragraph["anchor_method"] = "printed_label" if label else (
                "preceding_printed_note_group_not_exact_line_coverage" if paragraph["anchor_line_label"] else "poem_introduction")
            paragraph["source"] = {**r, "ocr_file": parsed_path.name,
                "ocr_sha256": digest(parsed_path), "paragraph_index": i,
                "ocr_uncertainty": data.get("uncertainty", []), "independent_audit": verdict}
        kept = [p for i, p in enumerate(paragraphs)
            if i not in verdict.get("exclude_paragraph_indices", [])]
        grouped.setdefault(r["fragment"], []).extend(kept)
    records = [{"id": f"campbell-glp:alcaeus:{fragment}:commentary",
        "assignment_fragment": fragment, "edition_fragment": "130" if fragment == "130b" else fragment,
        "source": "Campbell Greek Lyric Poetry.pdf.pdf", "source_sha256": SOURCE_SHA256,
        "license": "user_supplied_edition_excerpt", "status": "independently_audited_source_transcription" if approval else "candidate_pending_independent_audit",
        "audit_path": str(approval_path) if approval_path else None,
        "pending_sources":pending.get(fragment, []),
        "paragraphs": paragraphs} for fragment, paragraphs in grouped.items()]
    (out / "commentary-candidates.jsonl").write_text("".join(
        json.dumps(r, ensure_ascii=False)+"\n" for r in records), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=Path(r"C:\Users\alvin\Downloads\Campbell Greek Lyric Poetry.pdf.pdf"))
    p.add_argument("--output", type=Path, default=Path("runtime/campbell-commentary"))
    p.add_argument("--extract", action="store_true")
    p.add_argument("--vision", action="store_true")
    p.add_argument("--split-failed", action="store_true")
    p.add_argument("--retry", action="store_true")
    p.add_argument("--model", default="gpt-6-astra")
    p.add_argument("--only", nargs="*")
    p.add_argument("--package", action="store_true")
    p.add_argument("--approval", type=Path)
    p.add_argument("--allow-pending", action="store_true")
    args = p.parse_args()
    if args.extract:
        extract(args.source, args.output)
    if args.split_failed:
        split_failed(args.source, args.output)
    if args.vision:
        vision(args.output, args.model, args.only, args.retry)
    if args.package:
        package(args.output, args.approval, args.allow_pending)


if __name__ == "__main__":
    main()
