"""Derive compact Melos tables from GLAUx (Keersmaekers; github.com/alekkeersmaekers/glaux,
Zenodo 10.5281/zenodo.10948374), open-licence texts only.

Pinned commit: b077d8f6ff429a5c7245954bc16bb7d1d7948823 (2026-02-19).
Output (into --out):
  texts_selected.json          selected + excluded candidate texts with metadata and reasons
  lyric_tokens.jsonl.gz        tokens of selected texts (open SOURCE_LICENSE only)
  manifest.json                provenance, licence quotes, hashes, row counts, selection, coverage

Two ways to run:
  (a) laptop, downloading only the needed files from raw.githubusercontent.com at the pinned commit:
      python -I scripts/ingest_open_glaux.py --download-dir <new empty dir> --out data/open/glaux \
          --forms data/lexica/forms.jsonl
  (b) Basecamp, from the clone ~/storagebox/archive/melos-open/glaux/repo (checked out at the pinned commit):
      python3 -I scripts/ingest_open_glaux.py --repo ~/storagebox/archive/melos-open/glaux/repo --out <dir>
GLAUx XML is NFD; every form/lemma written here is NFC.
"""
import argparse, collections, csv, gzip, hashlib, json, os, re, sys, unicodedata, urllib.request
import xml.etree.ElementTree as ET

COMMIT = "b077d8f6ff429a5c7245954bc16bb7d1d7948823"
RAW = f"https://raw.githubusercontent.com/alekkeersmaekers/glaux/{COMMIT}/"
UA = "Melos/1.0 (+https://greeklyric.com)"

# SOURCE_LICENSE values seen in metadata.txt at COMMIT -> decision
LICENCE_MAP = {
    "CC BY-SA 4.0": "open", "CC-BY-SA 3.0": "open", "CC BY 4.0": "open",
    "CC BY-SA 2.0": "open", "CC BY-SA 2.5": "open",
    "NA": "exclude: no licence stated",
    "CC BY-NC-SA 4.0": "exclude: NC", "CC BY-NC-ND 4.0": "exclude: NC/ND", "CC BY-NC-ND 3.0": "exclude: NC/ND",
    "CC BY-NC-ND 2.0": "exclude: NC/ND",
    "OpenEdition Books License": "exclude: not CC BY/BY-SA/PD (licence terms not verified)",
    "GNU General Public License": "exclude: GPL is not CC BY/BY-SA/PD (outside selection rule)",
}
# Manual-annotation projects (TREEBANK_ANNOTATIONS) and their licences as stated in the GLAUx README
TREEBANK_MAP = {
    "NA": "none",
    "Perseus Ancient Greek Dependency Treebank": "open",       # CC BY-SA 3.0
    "Pedalion Trees": "open",                                  # CC BY-SA 4.0 (per GLAUx README)
    "Harrington Trees": "open",                                # CC BY-SA 4.0
    "PROIEL": "drop-manual: CC BY-NC-SA 3.0",
    "Vanessa Gorman's Ancient Greek Prose Dependency Treebanks": "drop-manual: CC BY-NC-SA 4.0",
}
MELOS_AUTHORS = {  # Melos name -> exact GLAUx AUTHOR_STANDARD
    "Sappho": "Sappho", "Alcaeus": "Alcaeus", "Alcman": "Alcman", "Anacreon": "Anacreon",
    "Anacreontea": "Anacreontea", "Archilochus": "Archilochus", "Hipponax": "Hipponax",
    "Semonides": "Semonides", "Mimnermus": "Mimnermus", "Tyrtaeus": "Tyrtaeus", "Solon": "Solon",
    "Theognis": "Theognis", "Phocylides": "Phocylides", "Simonides": "Simonides", "Pindar": "Pindarus",
    "Bacchylides": "Bacchylides", "Stesichorus": "Stesichorus", "Ibycus": "Ibycus", "Corinna": "Corinna",
    "Callinus": "Callinus", "Xenophanes": "Xenophanes", "Hesiod": "Hesiodus",
    "Homeric Hymns": "Hymni Homerici", "Theocritus": "Theocritus", "Callimachus": "Callimachus",
    "Apollonius": "Apollonius Rhodius",
}
BY_GLAUX = {v: k for k, v in MELOS_AUTHORS.items()}
SELECT_GENRES = {"Lyric poetry"}  # GLAUx GENRE_STANDARD (covers lyric, elegy, iambus, epigram)


def nfc(s):
    return unicodedata.normalize("NFC", s) if s else s


def sha256b(b):
    return hashlib.sha256(b).hexdigest()


def fetch(path, dl_dir):
    dst = os.path.join(dl_dir, path.replace("/", os.sep))
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        req = urllib.request.Request(RAW + path, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        with open(dst, "wb") as f:
            f.write(data)
    return open(dst, "rb").read()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--repo"); g.add_argument("--download-dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--forms")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    read = (lambda p: open(os.path.join(a.repo, p), "rb").read()) if a.repo else (lambda p: fetch(p, a.download_dir))

    meta_b = read("metadata.txt")
    rows = list(csv.DictReader(meta_b.decode("utf8").splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    lic_seen = collections.Counter(r["SOURCE_LICENSE"] for r in rows)
    unknown = [k for k in lic_seen if k not in LICENCE_MAP]
    if unknown:
        sys.exit(f"unmapped SOURCE_LICENSE values {unknown}; extend LICENCE_MAP")
    tb_unknown = {r["TREEBANK_ANNOTATIONS"] for r in rows} - set(TREEBANK_MAP)
    if tb_unknown:
        sys.exit(f"unmapped TREEBANK_ANNOTATIONS {tb_unknown}")

    selected, excluded = [], []
    for r in rows:
        melos = BY_GLAUX.get(r["AUTHOR_STANDARD"])
        if not (r["GENRE_STANDARD"] in SELECT_GENRES or melos):
            continue
        rec = {k.lower(): r[k] for k in ("GLAUX_TEXT_ID", "TLG", "STARTDATE", "ENDDATE", "AUTHOR_STANDARD",
                                         "TITLE_STANDARD", "GENRE_STANDARD", "DIALECT", "SOURCE",
                                         "SOURCE_LICENSE", "TOKENS", "TREEBANK_ANNOTATIONS")}
        rec["melos_author"] = melos
        decision = LICENCE_MAP[r["SOURCE_LICENSE"]]
        if decision != "open":
            rec["reason"] = decision
            excluded.append(rec)
        else:
            selected.append(rec)

    tok_path = os.path.join(a.out, "lyric_tokens.jsonl.gz")
    n_tok = n_dropped_manual = 0
    author_tokens = collections.Counter(); author_forms = collections.defaultdict(set)
    ann = collections.Counter(); raw_files = {}
    with gzip.open(tok_path, "wt", encoding="utf8", compresslevel=9) as out:
        for rec in selected:
            path = f"xml/{rec['tlg']}.xml"
            b = read(path)
            raw_files[path] = {"sha256": sha256b(b), "bytes": len(b), "url": RAW + path}
            tb = TREEBANK_MAP[rec["treebank_annotations"]]
            key = rec["melos_author"] or rec["author_standard"]
            nt = 0
            for s in ET.fromstring(b).iter("sentence"):
                kind = s.get("analysis") or ""
                if kind == "manual" and tb.startswith("drop-manual"):
                    n_dropped_manual += sum(1 for _ in s.iter("word"))
                    continue
                for i, w in enumerate(s.iter("word"), 1):
                    f = nfc(w.get("form"))
                    out.write(json.dumps({
                        "text_id": rec["glaux_text_id"], "tlg": rec["tlg"], "sentence_id": s.get("id"),
                        "token_id": w.get("id"), "position": i, "line": w.get("line"),
                        "form": f, "lemma": nfc(w.get("lemma")), "postag": w.get("postag"),
                        "head": w.get("head"), "relation": w.get("relation"),
                        "annotation": kind,
                        "manual_source": rec["treebank_annotations"] if kind == "manual" else "",
                    }, ensure_ascii=False) + "\n")
                    n_tok += 1; nt += 1; ann[kind] += 1
                    if any(ch.isalpha() for ch in f):
                        author_tokens[key] += 1
                        author_forms[key].add(f)
            rec["tokens_written"] = nt
            print(path, nt, file=sys.stderr)

    with open(os.path.join(a.out, "texts_selected.json"), "w", encoding="utf8") as f:
        json.dump({"selected": selected, "excluded": excluded}, f, ensure_ascii=False, indent=1)

    cov = coverage_vs_forms(a.forms, author_forms) if a.forms else None
    found = sorted({r["melos_author"] for r in selected + excluded if r["melos_author"]})
    m = {
        "dataset": "GLAUx (the Greek Language AUtomated)",
        "creator": "Alek Keersmaekers",
        "source_urls": ["https://github.com/alekkeersmaekers/glaux", RAW + "metadata.txt", RAW + "README.md"],
        "zenodo_doi": "10.5281/zenodo.10948374 (Zenodo API returned an empty response on 2026-10-09; not re-verified)",
        "commit": COMMIT, "commit_date": "2026-02-19T17:15:08+01:00",
        "licence": {
            "repo_licence_file": "none (no LICENSE file; GitHub API license = null)",
            "readme_quote_license_section": "GLAUx is generally available under a [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) license. Please note though that some of the texts and/or the manual annotations may have a more restrictive license.",
            "readme_quote_intro": "Most of the data is available under a CC BY-SA license but some texts are more restrictive (e.g. CC BY-NC): the license of each source text is also specified in the metadata file.",
            "url": RAW + "README.md",
            "source_license_field": "metadata.txt column SOURCE_LICENSE gives the licence of the source text each GLAUx file was built from; it overrides the general CC BY-SA 4.0 for that text.",
            "source_license_values_seen": dict(lic_seen.most_common()),
            "mapping": LICENCE_MAP,
            "manual_annotation_projects": TREEBANK_MAP,
            "manual_annotation_rule": "sentences with analysis=\"manual\" in texts whose TREEBANK_ANNOTATIONS project is NC (PROIEL, Gorman) are dropped",
        },
        "attribution_required": "Keersmaekers, A. GLAUx: the Greek Language AUtomated, github.com/alekkeersmaekers/glaux "
                                f"(commit {COMMIT}), CC BY-SA 4.0; plus the SOURCE and, for manual parses, the "
                                "treebank project and annotators named per text in metadata.txt "
                                "(Perseus AGDT CC BY-SA 3.0; Pedalion Trees CC BY-SA 4.0; Harrington Trees CC BY-SA 4.0).",
        "raw_archive": {
            "basecamp_clone": "~/storagebox/archive/melos-open/glaux/repo (git clone --depth 1, HEAD " + COMMIT + ", 3.6 GB)",
            "metadata.txt": {"sha256": sha256b(meta_b), "bytes": len(meta_b), "url": RAW + "metadata.txt"},
            "xml_files_used": raw_files,
        },
        "selection_rules": {
            "genre": sorted(SELECT_GENRES), "melos_author_exact_AUTHOR_STANDARD": MELOS_AUTHORS,
            "rule": "candidate if GENRE_STANDARD == 'Lyric poetry' OR AUTHOR_STANDARD in the Melos list; kept only if SOURCE_LICENSE maps to open",
        },
        "melos_authors_present_in_glaux": found,
        "melos_authors_absent_from_glaux": [k for k, v in MELOS_AUTHORS.items() if k not in found],
        "selected_texts": len(selected), "excluded_candidates": [
            {k: e[k] for k in ("glaux_text_id", "tlg", "author_standard", "title_standard", "source_license", "tokens", "reason")}
            for e in excluded],
        "annotation_counts": dict(ann), "manual_tokens_dropped_nc": n_dropped_manual,
        "tokens_per_author_word_tokens": dict(author_tokens.most_common()),
        "coverage_vs_forms_jsonl": cov,
        "corpus_wide_form_lemma_postag_counts": "PENDING - needs Basecamp (3.4 GB of XML); run this table from "
                                                "~/storagebox/archive/melos-open/glaux/repo once SSH is available",
        "files": {},
        "date": "2026-10-09", "user_agent": UA, "script": "scripts/ingest_open_glaux.py",
    }
    for name, n in (("texts_selected.json", len(selected) + len(excluded)), ("lyric_tokens.jsonl.gz", n_tok)):
        p = os.path.join(a.out, name)
        m["files"][name] = {"sha256": sha256b(open(p, "rb").read()), "bytes": os.path.getsize(p), "rows": n}
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


ELISION = str.maketrans({"’": "᾽", "'": "᾽", "ʼ": "᾽"})


def coverage_vs_forms(forms_path, author_forms):
    known = set()
    with open(forms_path, encoding="utf8") as f:
        for line in f:
            known.add(nfc(json.loads(line)["form"]))
    kf = {k.translate(ELISION) for k in known}
    res, allf = {}, set()
    for a, fs in sorted(author_forms.items()):
        allf |= fs
        res[a] = {"distinct_forms": len(fs), "not_in_forms_jsonl_exact_nfc": len(fs - known),
                  "not_in_forms_jsonl_elision_folded": sum(1 for x in fs if x.translate(ELISION) not in kf)}
    res["ALL_SELECTED"] = {"distinct_forms": len(allf), "not_in_forms_jsonl_exact_nfc": len(allf - known),
                           "not_in_forms_jsonl_elision_folded": sum(1 for x in allf if x.translate(ELISION) not in kf)}
    res["forms_jsonl_distinct_nfc_forms"] = len(known)
    res["note"] = "exact = NFC equality; elision_folded maps U+2019/U+0027/U+02BC to U+1FBD. Tokens without letters excluded."
    return res


if __name__ == "__main__":
    main()
