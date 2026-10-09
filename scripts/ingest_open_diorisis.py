"""Derive compact Melos tables from the Diorisis Ancient Greek Corpus (Vatri & McGillivray 2018).

Input : Diorisis.zip exactly as published on figshare (doi 10.6084/m9.figshare.6187256.v1,
        https://ndownloader.figshare.com/files/11296247, md5 f3a26efa7e7d2b93d1bcca26900d180a).
Output (into --out):
  texts.json                     every text: author, title, TLG ids, genre, date, licence, token counts
  poetry_tokens.jsonl.gz         every word token of the selected poetry / Melos-author texts
  form_lemma_pos_counts.tsv.gz   corpus-wide (all 820 texts) form -> lemma -> POS counts
  manifest.json                  provenance, licences, hashes, row counts, selection, coverage

Run (laptop or Basecamp; only needs the `betacode` package, pip install betacode==1.1):
  python -I scripts/ingest_open_diorisis.py --zip <path>/Diorisis.zip --out data/open/diorisis \
      --forms data/lexica/forms.jsonl
On Basecamp the archived zip is ~/storagebox/archive/melos-open/diorisis/Diorisis.zip.

Diorisis stores word forms in TLG Beta Code (lower-case, `*` = capital). `form_betacode` is the
verbatim attribute; `form` is betacode.conv.beta_to_uni (PyPI `betacode` 1.1, an implementation of the
TLG Beta Code Manual, https://www.tlg.uci.edu/encoding/BCM.pdf) followed by Unicode NFC.
Lemmas (`entry`) are already Unicode in the source and are only NFC-normalised.
"""
import argparse, collections, gzip, hashlib, json, os, re, sys, unicodedata, zipfile
import xml.etree.ElementTree as ET
import betacode.conv

ZIP_MD5 = "f3a26efa7e7d2b93d1bcca26900d180a"
# Melos author list, matched against the Diorisis <author> header (exact strings, case-sensitive).
# "Hymns" is the Diorisis author label of the Homeric Hymns (TLG 0013).
MELOS_AUTHORS = ["Sappho", "Alcaeus", "Alcman", "Anacreon", "Anacreontea", "Archilochus", "Hipponax",
                 "Semonides", "Mimnermus", "Tyrtaeus", "Solon", "Theognis", "Phocylides", "Simonides",
                 "Pindar", "Bacchylides", "Stesichorus", "Ibycus", "Corinna", "Callinus", "Xenophanes",
                 "Hesiod", "Homeric Hymns", "Theocritus", "Callimachus", "Apollonius"]
AUTHOR_MATCH = {  # Melos name -> regex over Diorisis author header
    **{a: re.compile(r"^%s\b" % a) for a in MELOS_AUTHORS},
    "Homeric Hymns": re.compile(r"^Hymns$"),
    "Apollonius": re.compile(r"^Apollonius Rhodius$"),
}
SELECT_GENRES = {"Poetry"}  # Diorisis <xenoData><genre>; there is no separate "Lyric" genre in Diorisis


def nfc(s):
    return unicodedata.normalize("NFC", s) if s else s


_bc = {}
def beta(s):
    u = _bc.get(s)
    if u is None:
        u = _bc[s] = nfc(betacode.conv.beta_to_uni(s))
    return u


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def header(root):
    h = root.find("teiHeader")
    lic = h.find("fileDesc/publicationStmt/licence/ref")
    src = h.find("fileDesc/sourceDesc/ref")
    return {
        "author": h.findtext("fileDesc/titleStmt/author"),
        "title": h.findtext("fileDesc/titleStmt/title"),
        "tlg_author": h.findtext("fileDesc/titleStmt/tlgAuthor"),
        "tlg_work": h.findtext("fileDesc/titleStmt/tlgId"),
        "date": h.findtext("profileDesc/creation/date"),
        "genre": h.findtext("xenoData/genre"),
        "subgenre": h.findtext("xenoData/subgenre"),
        "source_name": src.text if src is not None else None,
        "source_url": src.get("target") if src is not None else None,
        "licence": lic.text if lic is not None else None,
        "licence_url": lic.get("target") if lic is not None else None,
    }


def melos_author(author):
    for name, rx in AUTHOR_MATCH.items():
        if author and rx.search(author):
            return name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--forms", help="data/lexica/forms.jsonl for the coverage check")
    ap.add_argument("--archive-note", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    zsha = sha256(a.zip)
    zmd5 = hashlib.md5(open(a.zip, "rb").read()).hexdigest()
    if zmd5 != ZIP_MD5:
        sys.exit(f"Diorisis.zip md5 {zmd5} != figshare {ZIP_MD5}; refusing to continue")

    z = zipfile.ZipFile(a.zip)
    texts, counts = [], collections.Counter()
    tok_path = os.path.join(a.out, "poetry_tokens.jsonl.gz")
    n_tok = 0
    author_tokens = collections.Counter()
    lyric_forms = collections.defaultdict(set)  # melos author -> set of NFC forms
    with gzip.open(tok_path, "wt", encoding="utf8", compresslevel=9) as out:
        for member in sorted(z.namelist()):
            if not member.endswith(".xml"):
                continue
            root = ET.fromstring(z.read(member))
            t = header(root)
            t["file"] = member
            t["text_id"] = f"tlg{t['tlg_author']}.tlg{t['tlg_work']}"
            t["melos_author"] = melos_author(t["author"])
            sel = t["genre"] in SELECT_GENRES or t["melos_author"] is not None
            t["selected"] = sel
            t["selection_reason"] = ("genre=" + t["genre"] if t["genre"] in SELECT_GENRES else "") + \
                ((";" if t["genre"] in SELECT_GENRES else "") + "author=" + t["melos_author"] if t["melos_author"] else "")
            nw = npunct = nunlem = 0
            for s in root.iter("sentence"):
                sid, loc, pos = s.get("id"), s.get("location"), 0
                for el in s:
                    if el.tag == "punct":
                        npunct += 1
                        continue
                    if el.tag != "word":
                        continue
                    nw += 1
                    pos += 1
                    fb = el.get("form")
                    le = el.find("lemma")
                    lemma = nfc(le.get("entry")) if le is not None and le.get("entry") else ""
                    p = le.get("POS", "") if le is not None else ""
                    if not lemma:
                        nunlem += 1
                    f = beta(fb)
                    counts[(fb, lemma, p)] += 1
                    if sel:
                        out.write(json.dumps({
                            "text_id": t["text_id"], "sentence_id": sid, "location": loc,
                            "token_id": el.get("id"), "position": pos,
                            "form_betacode": fb, "form": f, "lemma": lemma,
                            "lemma_id": le.get("id") if le is not None else "", "pos": p,
                            "morph": [x.get("morph") for x in le.findall("analysis")] if le is not None else [],
                            "disambiguated": le.get("disambiguated") if le is not None else "",
                            "treetagger": le.get("TreeTagger") if le is not None else "",
                        }, ensure_ascii=False) + "\n")
                        n_tok += 1
                        key = t["melos_author"] or t["author"]
                        author_tokens[key] += 1
                        lyric_forms[key].add(f)
            t.update(words=nw, punct=npunct, unlemmatized_words=nunlem)
            texts.append(t)
            print(member, nw, file=sys.stderr)

    with open(os.path.join(a.out, "texts.json"), "w", encoding="utf8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=1)

    cnt_path = os.path.join(a.out, "form_lemma_pos_counts.tsv.gz")
    with gzip.open(cnt_path, "wt", encoding="utf8", compresslevel=9) as f:
        f.write("form\tform_betacode\tlemma\tpos\tcount\n")
        for (fb, l, p), c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            f.write(f"{beta(fb)}\t{fb}\t{l}\t{p}\t{c}\n")

    coverage = None
    if a.forms:
        coverage = coverage_vs_forms(a.forms, lyric_forms)

    sel_texts = [t for t in texts if t["selected"]]
    found = sorted({t["melos_author"] for t in texts if t["melos_author"]})
    manifest = {
        "dataset": "Diorisis Ancient Greek Corpus",
        "creators": ["Alessandro Vatri", "Barbara McGillivray"],
        "doi": "10.6084/m9.figshare.6187256.v1",
        "source_urls": ["https://doi.org/10.6084/m9.figshare.6187256.v1",
                        "https://api.figshare.com/v2/articles/6187256",
                        "https://ndownloader.figshare.com/files/11296247"],
        "licence": {
            "dataset_licence_figshare": "CC BY 4.0",
            "dataset_licence_figshare_quote": "\"license\": {\"value\": 1, \"name\": \"CC BY 4.0\", \"url\": \"https://creativecommons.org/licenses/by/4.0/\"}",
            "dataset_licence_url": "https://creativecommons.org/licenses/by/4.0/",
            "dataset_licence_checked_at": "https://api.figshare.com/v2/articles/6187256",
            "per_text_licence_in_xml_headers": sorted({(t["licence"], t["licence_url"]) for t in texts}),
            "note": "figshare labels the dataset CC BY 4.0, but every one of the 820 XML headers carries "
                    "<licence><ref target=\"https://creativecommons.org/licenses/by-sa/3.0/us/\">Creative Commons "
                    "Attribution-ShareAlike 3.0 United States License</ref></licence> (the texts derive from Perseus "
                    "canonical-greekLit etc.). Treat derived files as CC BY-SA 3.0 US with attribution to Diorisis "
                    "and to the text source named in each texts.json row.",
        },
        "attribution_required": "Vatri, Alessandro; McGillivray, Barbara (2018). The Diorisis Ancient Greek Corpus. "
                                "figshare. Dataset. https://doi.org/10.6084/m9.figshare.6187256.v1 -- texts from "
                                "Perseus canonical-greekLit (Trustees of Tufts University), The Little Sailing and "
                                "Bibliotheca Augustana as named per text (texts.json source_name/source_url); "
                                "licensed CC BY-SA 3.0 US.",
        "raw_archive": {"file": "Diorisis.zip", "bytes": os.path.getsize(a.zip), "sha256": zsha, "md5": zmd5,
                        "md5_matches_figshare_computed_md5": True, "note": a.archive_note},
        "transform": "form = NFC(betacode.conv.beta_to_uni(form_betacode)) with PyPI betacode 1.1 "
                     "(TLG Beta Code Manual); lemma = NFC(entry). No other changes.",
        "selection_rules": {
            "genre": sorted(SELECT_GENRES),
            "melos_author_regex_on_author_header": {k: v.pattern for k, v in AUTHOR_MATCH.items()},
            "rule": "text selected if genre == 'Poetry' OR author header matches a Melos author regex",
        },
        "melos_authors_found": found,
        "melos_authors_absent": [x for x in MELOS_AUTHORS if x not in found],
        "selected_texts": len(sel_texts),
        "texts_not_selected": len(texts) - len(sel_texts),
        "files": {},
        "tokens_per_author_in_selection": dict(author_tokens.most_common()),
        "coverage_vs_forms_jsonl": coverage,
        "corpus_totals": {"texts": len(texts), "words": sum(t["words"] for t in texts),
                          "unlemmatized_words": sum(t["unlemmatized_words"] for t in texts)},
        "date": "2026-10-09",
        "user_agent": "Melos/1.0 (+https://greeklyric.com)",
        "script": "scripts/ingest_open_diorisis.py",
    }
    for name, rows in (("texts.json", len(texts)), ("poetry_tokens.jsonl.gz", n_tok),
                       ("form_lemma_pos_counts.tsv.gz", len(counts))):
        p = os.path.join(a.out, name)
        manifest["files"][name] = {"sha256": sha256(p), "bytes": os.path.getsize(p), "rows": rows}
    return manifest


ELISION = str.maketrans({"’": "᾽", "'": "᾽", "ʼ": "᾽"})


def coverage_vs_forms(forms_path, author_forms):
    known = set()
    with open(forms_path, encoding="utf8") as f:
        for line in f:
            known.add(nfc(json.loads(line)["form"]))
    known_fold = {k.translate(ELISION) for k in known}
    res, allf = {}, set()
    for a, fs in sorted(author_forms.items()):
        fs = {x for x in fs if any(ch.isalpha() for ch in x)}
        allf |= fs
        res[a] = {"distinct_forms": len(fs), "not_in_forms_jsonl_exact_nfc": len(fs - known),
                  "not_in_forms_jsonl_elision_folded": sum(1 for x in fs if x.translate(ELISION) not in known_fold)}
    res["ALL_SELECTED"] = {"distinct_forms": len(allf), "not_in_forms_jsonl_exact_nfc": len(allf - known),
                           "not_in_forms_jsonl_elision_folded": sum(1 for x in allf if x.translate(ELISION) not in known_fold)}
    res["forms_jsonl_distinct_nfc_forms"] = len(known)
    res["note"] = ("exact = NFC string equality; elision_folded maps U+2019/U+0027/U+02BC to U+1FBD "
                   "(forms.jsonl writes elision with U+1FBD, betacode emits U+2019). Tokens without any letter excluded.")
    return res


if __name__ == "__main__":
    m = main()
    out = sys.argv[sys.argv.index("--out") + 1]
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
