"""Publish only source-hash-verified Greek excerpt crops from the supplied PDF.

No transcription is authored here. The image bytes are copied unchanged from
the extraction receipts; the complete book and private OCR receipts stay local.
"""
from pathlib import Path
import hashlib
import html
import json
import shutil
from urllib.parse import quote
import fitz

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "runtime/campbell-assignment"
FRAGMENTS = ("34a", "129", "130b", "326", "350")


def main():
    receipts = json.loads((SOURCE / "ocr-receipts.json").read_text(encoding="utf-8"))
    evidence = json.loads((SOURCE / "source-evidence.json").read_text(encoding="utf-8"))
    source_pdf = Path(evidence["source_path"])
    if hashlib.sha256(source_pdf.read_bytes()).hexdigest() != evidence["source_sha256"]:
        raise ValueError("Original source PDF changed")
    pdf = fitz.open(source_pdf)
    # Independent source-image review identified terminal lacunae/notices just
    # below OCR crops. Widen the facsimile only; immutable OCR inputs stay intact.
    extended_bottom = {("34a", 86): 135, ("130b", 90): 287.5, ("129", 89): 290}
    assets = ROOT / "assets/edition-excerpts"
    pages = ROOT / "sources/campbell-alcaeus"
    assets.mkdir(parents=True, exist_ok=True)
    pages.mkdir(parents=True, exist_ok=True)
    manifest = []
    for fragment in FRAGMENTS:
        sections, seen = [], set()
        for item in receipts:
            if item["fragment"] != fragment or item["image_file"] in seen:
                continue
            seen.add(item["image_file"])
            if item["source_sha256"] != evidence["source_sha256"]:
                raise ValueError("Source PDF hash mismatch")
            image = SOURCE / item["image_file"]
            if image.parent != SOURCE or hashlib.sha256(image.read_bytes()).hexdigest() != item["image_sha256"]:
                raise ValueError("Excerpt image hash mismatch")
            bounds = list(item["pdf_crop_points"])
            bottom = extended_bottom.get((fragment, item["pdf_page"]))
            if bottom:
                bounds[3] = bottom
                content = pdf[item["pdf_page"] - 1].get_pixmap(matrix=fitz.Matrix(4, 4), clip=fitz.Rect(bounds)).tobytes("png")
                digest = hashlib.sha256(content).hexdigest()
                name = f"{image.stem}-facsimile.{digest[:12]}.png"
                (assets / name).write_bytes(content)
            else:
                digest = item["image_sha256"]
                name = f"{image.stem}.{digest[:12]}.png"
                shutil.copyfile(image, assets / name)
            label = "Intervening prose quotation" if item["chunk_kind"] == "quotation-prose" else "Greek verse excerpt"
            sections.append(f'<figure><figcaption>{label} · PDF page {item["pdf_page"]}</figcaption>'
                            f'<img src="/assets/edition-excerpts/{name}" alt="{label} for Alcaeus {fragment}, scanned from Campbell" loading="lazy" decoding="async"></figure>')
            manifest.append({"fragment": fragment, "asset": f"assets/edition-excerpts/{name}",
                             "sha256": digest, "pdf_page": item["pdf_page"],
                             "crop_points": bounds, "source_sha256": item["source_sha256"]})
        if not sections:
            raise ValueError(f"No excerpt images for {fragment}")
        identifier = quote(f"campbell-glp:alcaeus:{fragment}", safe="")
        note = (' Campbell prints this selection as fragment 130; the assignment calls it 130b.' if fragment == "130b" else "")
        if fragment == "34a":
            note += " Tiny marks in the scan remain ambiguous; compare these pixels when checking the transcription's diacritics."
        if fragment == "350":
            note += " The prose between the verse quotations is shown separately, not treated as verse."
        document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alcaeus {fragment} · Campbell source · Melos</title>
<link rel="icon" href="/assets/branding/melos-favicon-white.svg" type="image/svg+xml">
<style>body{{margin:0;background:#fff;color:#353b42;font:18px/1.55 Georgia,serif}}main{{max-width:820px;margin:auto;padding:32px 20px 64px}}a{{color:#243c52;text-underline-offset:4px}}h1{{font-weight:normal;line-height:1.2}}.source{{font-size:15px;color:#52616e}}figure{{margin:32px 0}}figcaption{{font:14px/1.5 Georgia,serif;color:#52616e;margin-bottom:8px}}img{{display:block;width:100%;height:auto}}.note{{border:1px solid #243c5230;padding:14px;background:#f9fbfd}}code{{font-size:11px;overflow-wrap:anywhere}}</style>
</head><body><main><a href="/?id={identifier}">Return to the reader</a>
<h1>Alcaeus · Fragment {fragment}</h1>
<p class="source">David A. Campbell, <em>Greek Lyric Poetry: A Selection of Early Greek Lyric, Elegiac and Iambic Poetry</em>, Macmillan, first edition 1967. Excerpts from the user-supplied scan.</p>
<p class="note">These are source-image excerpts, not generated reconstructions.{html.escape(note)}</p>
{''.join(sections)}
<p class="source">The full book is not hosted here. PDF source SHA-256:<br><code>{evidence['source_sha256']}</code></p>
</main></body></html>'''
        (pages / f"{fragment}.html").write_text(document, encoding="utf-8")
    (SOURCE / "facsimile-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    pdf.close()
    print(f"Built {len(FRAGMENTS)} source pages with {len(manifest)} source-rendered excerpt images.")


if __name__ == "__main__":
    main()
