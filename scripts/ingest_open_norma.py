#!/usr/bin/env python3
"""Ingest HuggingFace dataset Macronizer/norma (Norma Syllabarum Graecarum; card licence gpl-3.0).

Downloads README + data files at a pinned revision via the HF resolve URL (User-Agent rule), stores them as-is in
data/open/norma/raw/, writes a normalised norma.jsonl.gz: {id, split, source, work, task, marked, text}.
`marked` is the dataset's own markup (verbatim); `text` = marked with only the documented markup characters removed
(macronize: ^ and _ ; syllabify: [ ] { } and the card's '**' emphasis) - no other edits.
"""
import collections, gzip, hashlib, json, os, re, sys, urllib.request

UA = "Melos/1.0 (+https://greeklyric.com)"
REPO = "Macronizer/norma"
REV = "3b4f79fadd4fbe76143adac1329fc041d4447b82"
DATE = "2026-10-09"
FILES = ["README.md", "data/test.jsonl", "data/validation.jsonl"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "open", "norma")
# source key -> work label, copied from the dataset card's author list (README.md) where the card names the work.
WORK = {"partheneion": "Alcman, Louvre Partheneion 36-49", "bacchylides": "Bacchylides, Epinikion 5",
        "acharnenses": "Aristophanes, Acharnenses 1-16", "aristophanes": "Aristophanes, responding lyric songs (card)",
        "oedipus": "Sophocles, Oedipus Tyrannus 1-20", "cyclops": "(card lists Euripides, Bacchae 1-20; source key is 'cyclops' - unreconciled)",
        "dionysiaca": "Nonnus, Dionysiaca 1-20", "quintus": "Quintus, Posthomerica 1-20", "thucydides": "Thucydides 1.1.1.1-1.2.2.1",
        "cratylus": "Plato, Cratylus 383-384a5", "plutarchus": "Plutarch, Stoicos absurdiora poetis dicere",
        "enchiridion": "Epictetus, Enchiridion 1.1.1-1.5.1", "dioscorides": "Dioscorides, Anthologia Graeca 5.55", "supplices": "Aeschylus, Supplices 1-10", "contracelsum": "Origenes, Contra Celsum 1.1-1.20"}


def sha(b): return hashlib.sha256(b).hexdigest()


def strip_marks(s, task):
    if task == "macronize": return s.replace("^", "").replace("_", "")
    return re.sub(r"[\[\]{}]|\*\*", "", s)


def main():
    raw = os.path.join(OUT, "raw"); os.makedirs(raw, exist_ok=True)
    ins = {}
    for f in FILES:
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{REV}/{f}"
        b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read()
        p = os.path.join(raw, f.replace("/", "_")); open(p, "wb").write(b)
        ins[f] = {"url": url, "sha256": sha(b), "bytes": len(b)}
    card = open(os.path.join(raw, "README.md"), encoding="utf8").read()
    recs = []; cnt = collections.Counter(); unk = collections.Counter()
    for split, f in (("test", "data/test.jsonl"), ("validation", "data/validation.jsonl")):
        for i, l in enumerate(open(os.path.join(raw, f.replace("/", "_")), encoding="utf8")):
            r = json.loads(l)
            if r["source"] not in WORK: unk[r["source"]] += 1
            recs.append({"id": f"norma:{split}:{i}", "split": split, "source": r["source"], "work": WORK.get(r["source"], ""),
                         "task": r["task"], "marked": r["text"], "text": strip_marks(r["text"], r["task"])})
            cnt[(r["source"], r["task"], split)] += 1
    with gzip.open(os.path.join(OUT, "norma.jsonl.gz"), "wt", encoding="utf8", newline="\n") as o:
        for r in recs: o.write(json.dumps(r, ensure_ascii=False) + "\n")
    # pairing check: macronize vs syllabify rows of the same source should share plain text
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in recs: by[(r["split"], r["source"])][r["task"]].append(re.sub(r"\s+", "", r["text"]))
    pair = {f"{k[0]}/{k[1]}": {t: len(v) for t, v in d.items()} for k, d in by.items()}
    same = {f"{k[0]}/{k[1]}": d.get("macronize") == d.get("syllabify") for k, d in by.items() if "syllabify" in d}
    lic = card.split("---")[1].strip()
    man = {"name": "Norma Syllabarum Graecarum (Macronizer/norma)", "date": DATE, "user_agent": UA,
           "source_url": f"https://huggingface.co/datasets/{REPO}", "revision": REV,
           "licence": {"name": "GPL-3.0", "verbatim_card_front_matter": lic, "url": "https://www.gnu.org/licenses/gpl-3.0.html",
                       "note": "licence appears only in the card YAML front matter; the repo has no LICENSE file and the card states no origin/provenance of the underlying Greek texts or of who marked them"},
           "required_attribution": "Norma Syllabarum Graecarum, HuggingFace Macronizer/norma (author not named on the card), GPL-3.0",
           "inputs": ins, "outputs": {"norma.jsonl.gz": {"sha256": sha(open(os.path.join(OUT, "norma.jsonl.gz"), "rb").read())}},
           "counts": {"rows": len(recs), "by_source_task_split": {"|".join(k): v for k, v in sorted(cnt.items())},
                      "unmapped_sources": dict(unk), "rows_per_source": dict(collections.Counter(r["source"] for r in recs)),
                      "task_pairs_same_plain_text": same},
           "work_map_note": "work labels are hand-copied from the dataset card's author list; 'cyclops' source has no matching card entry"}
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(len(recs), dict(unk), same)


if __name__ == "__main__":
    main()
