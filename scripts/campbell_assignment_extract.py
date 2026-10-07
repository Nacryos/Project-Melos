"""Reproducible inspection of the user-supplied Campbell source PDF.

Discovery emits source evidence. OCR trials retain raw receipts; final collector
rows require an independent per-chunk hash-bound approval and never handwritten
Greek corrections.
Page arguments use the PDF's one-based page numbers, not printed book pagination.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import subprocess
from pathlib import Path

import fitz

# Crop coordinates were inspected on the 2x rendered source, not inferred text.
# They retain editorial lacunae and verse line labels. Fragment 350 has prose
# between its first two and remaining four verse lines; preserve that as a
# distinct chunk rather than silently turning quoted prose into poetry.
CROPS_2X = [
    ("34a", 85, "verse-a", (38, 650, 538, 820)),
    ("34a", 86, "verse-b", (77, 98, 538, 265)),
    ("129", 88, "verse-a", (74, 496, 540, 839)),
    ("129", 89, "verse-b", (48, 93, 540, 550)),
    ("130b", 89, "verse-a", (47, 735, 540, 832)),
    ("130b", 90, "verse-b", (72, 95, 545, 552)),
    ("326", 91, "verse", (46, 145, 535, 439)),
    ("350", 93, "verse-a", (80, 600, 540, 652)),
    ("350", 93, "quotation-prose", (43, 651, 540, 700)),
    ("350", 93, "verse-b", (80, 695, 540, 799)),
]

DETAIL_CROPS_2X = [
    ("34a-p85-lines1-3", 85, (38, 651, 532, 723)),
    ("34a-p85-line3", 85, (38, 698, 532, 724)),
    ("129-p88-line12", 88, (74, 811, 420, 838)),
    ("130b-p89-line19", 89, (47, 800, 500, 833)),
    ("130b-p90-line31", 90, (72, 408, 545, 432)),
    ("129-p89-line24", 89, (48, 408, 540, 437)),
]

VISION_PROMPT = """Act only as a diplomatic OCR engine for this image crop of printed polytonic Ancient Greek.
Read every printed line from the pixels. Do not use memorized editions, correct dialect or spelling,
fill lacunae, restore text, normalize accents, translate, or omit a line. Preserve all brackets,
dots, daggers, accents, breathings, uncertain-letter underdots (combining U+0323), and line breaks.
Separate right-margin verse numerals from the printed text. Isolated dots marking loss are a line.
Return JSON with lines:[{text:string,margin_label:string}], uncertainty:[string].
If a character is unreadable, put U+FFFD there and explain in uncertainty; never guess missing letters.
Only transcribe what is inside the crop, not adjacent material. No prose explanation outside JSON."""


def run_vision_ocr(output: Path, model: str, details: bool = False,
                   only: list[str] | None = None, effort: str = "high") -> None:
    # Image-input API documented at https://developers.openai.com/api/docs/guides/images-vision
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    load_dotenv(Path(__file__).resolve().parents[1] / "secrets/nature-gallery.env", encoding="utf-8-sig")
    client = OpenAI(timeout=180, max_retries=0)
    if details:
        receipts = [{**row, "image_file": row["image"]} for row in
                    json.loads((output / "detail-crop-receipts.json").read_text(encoding="utf-8"))
                    if "lines1-3" not in row["image"]]
    else:
        receipts = json.loads((output / "ocr-receipts.json").read_text(encoding="utf-8"))[::2]
    if only:
        receipts = [receipt for receipt in receipts if Path(receipt["image_file"]).stem in only]
        if len(receipts) != len(set(only)):
            raise ValueError("Requested OCR crop was not found in source receipts")

    def one(receipt: dict) -> str:
        image_path = output / receipt["image_file"]
        stem = image_path.stem
        raw_path = output / f"{stem}.vision.raw.json"
        if raw_path.exists():
            raise FileExistsError(f"Refusing to overwrite OCR receipt: {raw_path}")
        image_bytes = image_path.read_bytes()
        request_meta = {"model": model, "reasoning_effort": effort, "prompt": VISION_PROMPT,
                        "image_sha256": hashlib.sha256(image_bytes).hexdigest(), "source": receipt}
        request_path = output / f"{stem}.vision.request.json"
        attempt = 1
        while request_path.exists():
            request_path = output / f"{stem}.vision.request.retry-{attempt}.json"
            attempt += 1
        request_path.write_text(json.dumps(request_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        response = client.responses.create(model=model, reasoning={"effort": effort}, store=False,
            input=[{"role": "user", "content": [{"type": "input_text", "text": VISION_PROMPT},
                {"type": "input_image", "image_url": "data:image/png;base64,"+base64.b64encode(image_bytes).decode(), "detail": "original"}]}],
            text={"format": {"type": "json_object"}}, max_output_tokens=10000)
        raw_path.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        (output / f"{stem}.vision.receipt.json").write_text(json.dumps({
            "request_file": request_path.name, "response_file": raw_path.name,
            "response_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "image_sha256": request_meta["image_sha256"]}, indent=2), encoding="utf-8")
        parsed = json.loads(response.output_text)
        (output / f"{stem}.vision.parsed.json").write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        return stem

    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(one, receipt): receipt for receipt in receipts}
        for future in concurrent.futures.as_completed(pending):
            try:
                print("VISION OCR candidate saved:", future.result(), flush=True)
            except Exception as exc:
                failure = {"image_file": pending[future]["image_file"], "error_type": type(exc).__name__,
                           "error": str(exc), "retry_policy": "no automatic retry"}
                errors.append(failure)
                failure_path = output / (Path(pending[future]["image_file"]).stem + ".vision.error.json")
                failure_path.write_text(json.dumps(failure, indent=2), encoding="utf-8")
                print("VISION OCR failure:", failure["image_file"], failure["error_type"], flush=True)
    if errors:
        raise RuntimeError(f"{len(errors)} OCR requests failed; see saved error receipts")


def run_ocr(document: fitz.Document, output: Path, source_sha: str) -> None:
    from ingest_p2_editions import find_tesseract
    exe, tessdata = find_tesseract()
    env = {**os.environ, "PATH": str(exe.parent) + os.pathsep + os.environ.get("PATH", ""),
           "TESSDATA_PREFIX": str(tessdata), "OMP_THREAD_LIMIT": "1"}
    receipts = []
    for fragment, page_number, chunk, doubled_box in CROPS_2X:
        bounds = fitz.Rect(*(value / 2 for value in doubled_box))
        stem = f"alcaeus-{fragment}-p{page_number}-{chunk}"
        image_path = output / f"{stem}.png"
        document[page_number-1].get_pixmap(matrix=fitz.Matrix(4, 4), clip=bounds).save(image_path)
        for psm in (3, 6):
            command = [str(exe), str(image_path.resolve()), "stdout", "-l", "grc", "--psm", str(psm)]
            result = subprocess.run(command, env=env, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
            text_path = output / f"{stem}.psm{psm}.txt"
            text_path.write_bytes(result.stdout)
            receipts.append({"fragment": fragment, "source_sha256": source_sha, "pdf_page": page_number,
                             "pdf_crop_points": list(bounds), "chunk_kind": chunk,
                             "image_file": image_path.name, "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                             "ocr_file": text_path.name, "ocr_sha256": hashlib.sha256(result.stdout).hexdigest(),
                             "command": command, "stderr": result.stderr.decode("utf-8", errors="replace"),
                             "quality": "unreviewed_ocr_not_for_publication"})
    (output / "ocr-receipts.json").write_text(json.dumps(receipts, ensure_ascii=False, indent=2), encoding="utf-8")


def package_approved(output: Path, approval_path: Path, source_sha: str) -> None:
    """Package only hash-bound independently accepted OCR; never repair content."""
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if approval.get("source_sha256") != source_sha:
        raise ValueError("Source PDF differs from the independently audited artifact")
    receipts = json.loads((output / "ocr-receipts.json").read_text(encoding="utf-8"))[::2]
    grouped: dict[str, list] = {}
    root = Path(__file__).resolve().parents[1]
    for receipt in receipts:
        stem = Path(receipt["image_file"]).stem
        parsed_path = output / f"{stem}.vision.parsed.json"
        payload = parsed_path.read_bytes()
        verdict = approval.get("chunks", {}).get(parsed_path.name, {})
        if verdict.get("verdict") != "PASS" or verdict.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise ValueError(f"No hash-bound independent PASS: {parsed_path.name}")
        parsed = json.loads(payload)
        parsed["audit_uncertainty"] = verdict.get("required_uncertainty", "")
        parsed["audit_scope"] = verdict.get("scope", "visual source comparison")
        parsed["audited_line_replacements"] = []
        for replacement in verdict.get("replace_line_from_candidate", []):
            candidate_path = output / replacement["candidate_file"]
            if candidate_path.resolve().parent != output.resolve():
                raise ValueError("Retry candidate must be in the source evidence directory")
            candidate_bytes = candidate_path.read_bytes()
            if hashlib.sha256(candidate_bytes).hexdigest() != replacement["sha256"]:
                raise ValueError("Audited retry candidate hash changed")
            candidate = json.loads(candidate_bytes)
            target_index = replacement["line_index"]
            candidate_line = candidate["lines"][replacement["candidate_line_index"]]
            if "\ufffd" in candidate_line["text"]:
                raise ValueError("Retry still contains unreadable OCR characters")
            parsed["audited_line_replacements"].append({**replacement,
                "original_line": parsed["lines"][target_index], "replacement_line": candidate_line,
                "candidate_path": candidate_path.resolve().relative_to(root).as_posix(),
                "candidate_uncertainty": candidate.get("uncertainty", [])})
            parsed["lines"][target_index] = candidate_line
        excluded = verdict.get("exclude_noncontent_line_indices", [])
        parsed["excluded_noncontent_lines"] = []
        for index in excluded:
            excluded_line = parsed["lines"][index]
            if not excluded_line["text"] or set(excluded_line["text"].strip()) != {"\ufffd"}:
                raise ValueError("Only independently identified replacement-only crop-edge noise may be excluded")
            parsed["excluded_noncontent_lines"].append({"index": index, **excluded_line,
                "reason": verdict.get("reason", "Independent geometry audit: adjacent clipped non-content")})
        parsed["lines"] = [line for index, line in enumerate(parsed["lines"]) if index not in excluded]
        for line in parsed["lines"]:
            if not isinstance(line["text"], str) or not isinstance(line["margin_label"], str):
                raise ValueError(f"Invalid OCR line shape: {parsed_path.name}")
            if "\ufffd" in line["text"]:
                raise ValueError(f"Unresolved OCR character: {parsed_path.name}")
        grouped.setdefault(receipt["fragment"], []).append((receipt, parsed, parsed_path))
    records = []
    for fragment, chunks in grouped.items():
        lines, prose, evidence, verse_segments = [], [], [], []
        intervening_prose = False
        for receipt, parsed, parsed_path in chunks:
            selected = [{"label": line["margin_label"], "text": line["text"]} for line in parsed["lines"]]
            if receipt["chunk_kind"] == "quotation-prose":
                prose.extend(selected)
                intervening_prose = True
            else:
                if intervening_prose:
                    lines.append({"label": "", "text": ""})
                    intervening_prose = False
                segment_start = len(lines)
                lines.extend(selected)
                verse_segments.append({"start_line_index": segment_start,
                                       "end_line_index_exclusive": len(lines),
                                       "pdf_page": receipt["pdf_page"], "source_chunk_kind": receipt["chunk_kind"]})
            evidence.append({"pdf_page": receipt["pdf_page"], "printed_page": receipt["pdf_page"]-32,
                             "crop_points": receipt["pdf_crop_points"], "chunk_kind": receipt["chunk_kind"],
                             "image_path": (output / receipt["image_file"]).resolve().relative_to(root).as_posix(),
                             "image_sha256": receipt["image_sha256"],
                             "ocr_path": parsed_path.resolve().relative_to(root).as_posix(),
                             "ocr_sha256": hashlib.sha256(parsed_path.read_bytes()).hexdigest(),
                             "transcription_uncertainty": parsed.get("uncertainty", []),
                             "audit_uncertainty": parsed["audit_uncertainty"],
                             "audit_scope": parsed["audit_scope"],
                             "excluded_noncontent_lines": parsed["excluded_noncontent_lines"],
                             "audited_line_replacements": parsed["audited_line_replacements"],
                             "lines": selected})
        bundle = {"source_pdf_filename": "Campbell Greek Lyric Poetry.pdf.pdf", "source_pdf_sha256": source_sha,
                  "edition": "David A. Campbell, Greek Lyric Poetry (1967; reprinted 1976), Macmillan",
                  "assignment_fragment": fragment, "source_excerpt_chunks": evidence}
        bundle_path = output / f"alcaeus-{fragment}.source-bundle.json"
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        citation = "Fragment 130 (assignment: Fragment 130b)" if fragment == "130b" else f"Fragment {fragment}"
        public_source_url = f"https://greeklyric.com/sources/campbell-alcaeus/{fragment}.html"
        metadata = {"assignment_fragment": fragment, "edition_fragment": "130" if fragment == "130b" else fragment,
                    "source_pdf_sha256": source_sha, "source_pdf_filename": bundle["source_pdf_filename"],
                    "source_excerpt_chunks": evidence, "source_source": "User-supplied Campbell PDF",
                    "verse_segments": verse_segments,
                    "source_facsimile_url": public_source_url,
                    "transcription_method": "image-grounded OCR with independent visual review; not certified exact-diplomatic at every glyph",
                    "transcription_uncertainty": [item["audit_uncertainty"] for item in evidence if item["audit_uncertainty"]],
                    "audit_path": approval_path.resolve().relative_to(root).as_posix()}
        if fragment == "129":
            metadata["source_note"] = "The edition marks four further verses lost after this excerpt (desunt iv versus)."
        if fragment == "130b":
            metadata["source_note"] = "Printed as fragment 130 in this edition; the displayed excerpt corresponds to lines 16–35, not a restoration of the preceding text. The printed terminal row of ellipsis dots below line 35 is visible in the source facsimile."
        if prose:
            metadata["quotation_prose_lines"] = prose
            metadata["source_note"] = "The edition presents two separate verse quotations with intervening source prose, not uninterrupted adjacent verses. A blank structural line preserves that boundary here. The intervening prose reads: " + "\n".join(line["text"] for line in prose)
        records.append({"id": f"campbell-glp:alcaeus:{fragment}", "source": "campbell_assignment",
                        "source_url": public_source_url,
                        "raw_path": bundle_path.resolve().relative_to(root).as_posix(),
                        "raw_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
                        "author": "Alcaeus", "work": "Fragments", "edition": bundle["edition"],
                        "citation": citation, "language": "grc", "kind": "text", "quality": "machine_corrected_ocr",
                        "license": "user_supplied_edition_excerpt", "text": "\n".join(line["text"] for line in lines),
                        "lines": lines, "metadata": metadata})
    if set(grouped) != {"34a", "129", "130b", "326", "350"}:
        raise ValueError("Incomplete requested fragment set")
    target = output / "campbell_assignment.jsonl"
    target.write_text("".join(json.dumps(record, ensure_ascii=False)+"\n" for record in records), encoding="utf-8")
    print("Packaged audited candidates for final output audit:", target, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(r"C:\Users\alvin\Downloads\Campbell Greek Lyric Poetry.pdf.pdf"))
    parser.add_argument("--output", type=Path, default=Path("runtime/campbell-assignment"))
    parser.add_argument("--pages", nargs="*", type=int, default=[2, 3, 5, *range(84, 95)])
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--vision-ocr", action="store_true")
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--package-approval", type=Path)
    parser.add_argument("--detail-crops", action="store_true")
    parser.add_argument("--detail-vision", action="store_true")
    parser.add_argument("--vision-only", nargs="*")
    parser.add_argument("--effort", choices=["low", "medium", "high"], default="high")
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    with fitz.open(args.source) as document:
        evidence = {"source_path": str(args.source.resolve()), "source_sha256": digest,
                    "source_bytes": len(source_bytes), "page_count": len(document),
                    "pdf_metadata": document.metadata, "extraction": "PyMuPDF get_text; original text layer, no repair",
                    "pages": []}
        for number in args.pages:
            page = document[number - 1]
            stem = f"page-{number:03d}"
            raw_text = page.get_text("text")
            (args.output / f"{stem}.txt").write_text(raw_text, encoding="utf-8")
            text_blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
            (args.output / f"{stem}.blocks.json").write_text(json.dumps(text_blocks, ensure_ascii=False, indent=2), encoding="utf-8")
            page.get_pixmap(matrix=fitz.Matrix(2, 2)).save(args.output / f"{stem}.png")
            evidence["pages"].append({"pdf_page": number, "pdf_index": number-1,
                                      "bounds": list(page.rect), "text_chars": len(raw_text),
                                      "text_file": f"{stem}.txt", "image_file": f"{stem}.png",
                                      "blocks_file": f"{stem}.blocks.json"})
        (args.output / "source-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.ocr:
            run_ocr(document, args.output, digest)
        if args.vision_ocr:
            run_vision_ocr(args.output, args.model, only=args.vision_only, effort=args.effort)
        if args.package_approval:
            package_approved(args.output, args.package_approval, digest)
        if args.detail_crops:
            details = []
            for label, number, doubled_box in DETAIL_CROPS_2X:
                bounds = fitz.Rect(*(value / 2 for value in doubled_box))
                detail_path = args.output / f"detail-{label}.png"
                document[number-1].get_pixmap(matrix=fitz.Matrix(8, 8), clip=bounds).save(detail_path)
                details.append({"pdf_page": number, "crop_points": list(bounds), "render_scale": 8,
                                "source_sha256": digest, "image": detail_path.name,
                                "image_sha256": hashlib.sha256(detail_path.read_bytes()).hexdigest()})
            (args.output / "detail-crop-receipts.json").write_text(json.dumps(details, indent=2), encoding="utf-8")
        if args.detail_vision:
            run_vision_ocr(args.output, args.model, details=True, only=args.vision_only, effort=args.effort)
    print(json.dumps({"source_sha256": digest, "pages": args.pages, "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
