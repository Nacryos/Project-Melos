"""Random-span quality sampler over every Campbell GLP poem (read-only).

Draws random spans of 1-6 consecutive words from random poems across all
campbell-glp passages, stratified by dialect group and then poet, sends each
to /api/analyze-passage (one request at a time, at most ~1 request/second,
no machine fetches unless asked) and scores every word row on:

  (a) parse   complete parse fields (feature_coverage, as check_span_parses.py)
  (b) lemma   a lemma is present (selected, or shared by the top-ranked parses)
  (c) gloss   a short gloss (gloss.short_text) is present
  (d) plausible_gloss  the short gloss passes the plausibility checks below
  (e) plausible_lemma  the lemma shares letters with the printed form after
      accent/breathing folding (suppletive and pronominal lemmas exempt)

Gloss checks: part of speech mismatch (a "to ..." verb gloss on a nominal parse,
an article-led noun gloss on a finite verb), a letter or numeral sense on a
non-numeral, more than five words, a cross-reference ("see X", "= X",
"Dor. for X", Greek in the gloss), empty or article-only.

Every failing row gets failure classes (lacuna-adjacent, elision, crasis,
proper name, parser lemma format, parser cache miss, dialect spelling,
homograph, missing headword, no English definition, gloss flags ...).

  python scripts/sample_glp_quality.py --base https://greeklyric.com --seed 101 --spans 120 --out runtime/dev/sample/prod-101.jsonl
  python scripts/sample_glp_quality.py --report runtime/dev/sample/prod-101.jsonl

Use separate development seeds and keep one held-out seed for the final report;
``--no-print`` writes the results without showing them.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.passage_analysis import tokenize_span  # noqa: E402
from backend.short_gloss import LETTER_OR_NUMERAL, meaningful, metalanguage_only  # noqa: E402
from scripts.audit_alcaeus_occurrences import feature_coverage  # noqa: E402

RECORDS = ROOT / "data/campbell_glp/campbell_glp.jsonl"
FIVE = [f"campbell-glp:alcaeus:{n}" for n in ("34a", "129", "130b", "326", "350")]
# Literary dialect of each poet's poems in the anthology (coarse groups for
# stratification only; a poem may mix dialects).
DIALECT = {
    "aeolic": ("sappho", "alcaeus"),
    "doric_choral": ("alcman", "stesichorus", "ibycus", "simonides", "bacchylides", "pratinas",
                     "timocreon", "praxilla", "corinna"),
    "ionic_elegy_iambus": ("archilochus", "semonides", "hipponax", "anacreon", "xenophanes", "callinus",
                           "tyrtaeus", "mimnermus", "solon", "theognis", "phocylides", "demodocus"),
    "attic_popular": ("scolia", "carmina-popularia"),
}
POET_DIALECT = {poet: group for group, poets in DIALECT.items() for poet in poets}
GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
CROSS_REF = re.compile(
    r"^\s*(?:see|v\.|cf\.|=)\s|^\s*=|\b(?:Dor|Ep|Ion|Aeol|Att|poet|Lacon|Boeot|Lesb|late|old|later|Hom)\.?\s+(?:for|=)\b"
    r"|\bform\s+of\b|\bfor\s+[Ͱ-Ͽἀ-῿]", re.I)
ELISION = "’᾽'ʼ"
# Lemmas whose stems legitimately differ from their inflected forms.
SUPPLETIVE = {"ερχομαι", "φερω", "οραω", "λεγω", "φημι", "αγω", "εσθιω", "τρεχω", "αιρεω", "πινω", "πασχω", "ειμι",
              "αγαθος", "κακος", "πολυς", "μεγας", "ολιγος", "μικρος", "εγω", "συ", "ου", "ος", "ο", "αυτος",
              "ουτος", "εκεινος", "ημεις", "υμεις", "τις", "ειδον", "οιδα", "εχω", "διδωμι", "τιθημι", "ιημι",
              "ιστημι", "γιγνομαι", "γινομαι", "γυνη", "ανηρ", "ζευς", "θνησκω", "βαινω", "πιπτω", "αποθνησκω",
              "μανθανω", "λαμβανω", "τυγχανω", "φευγω", "ωνεομαι", "ειπον", "βαλλω", "ορνυμι", "καλος", "νηυς", "ναυς"}
NOMINAL = {"NOUN", "PROPN", "ADJ"}


def fold(text):
    """Letters only, lower case, no accents/breathings/iota subscript, σ for ς."""
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    letters = "".join(c for c in decomposed if unicodedata.category(c).startswith("L")).lower()
    return letters.replace("ς", "σ").replace("ξ", "κσ").replace("ψ", "πσ")


def _common_substring(a, b):
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


# Dialect vowel correspondences applied to both sides before comparison
# (Doric/Aeolic ᾱ for Attic-Ionic η, Ionic η for ᾱ, ου/ω, ει/η).
_DIALECT_FOLD = (("ει", "η"), ("ου", "ο"), ("ω", "ο"), ("η", "α"), ("ζ", "δ"), ("σσ", "σ"), ("ττ", "τ"))


def dialect_fold(text):
    value = fold(text)
    for old, new in _DIALECT_FOLD:
        value = value.replace(old, new)
    return re.sub(r"(.)\1", r"\1", value)


def lemma_plausible(form, lemma, pos):
    if not lemma:
        return None
    if pos in {"PRON", "DET"} or fold(lemma) in SUPPLETIVE:
        return True
    if lemma[-1] in ELISION:
        return False  # an elided lemma is a printed form, not a headword
    a, b = dialect_fold(form), dialect_fold(re.sub(r"[\d\-,]", "", lemma))
    if not a or not b:
        return False
    need = 2 if min(len(a), len(b)) <= 4 else 3
    return _common_substring(a, b) >= min(need, len(a), len(b))


def gloss_flags(short, full, pos, verbform):
    flags = []
    if not short or not meaningful(short):
        return ["empty_or_article_only"]
    words = [w for w in short.split() if w != "…"]
    if len(words) > 5:
        flags.append("too_long")
    if GREEK.search(short) or CROSS_REF.search(short) or CROSS_REF.search((full or "")[:60]) and not meaningful(
            CROSS_REF.split((full or "")[:60])[0]):
        flags.append("cross_reference")
    if pos != "NUM" and (LETTER_OR_NUMERAL.search(full or "") or re.search(r"\bletter\b|\bnumeral\b", short, re.I)):
        flags.append("letter_or_numeral")
    lowered = short.lower()
    if metalanguage_only(short.rstrip(" .…")):
        flags.append("grammar_label")
    if pos in NOMINAL and re.match(r"to\s+[a-z]", lowered) and not re.match(r"to\s+(?:the|a|an)\b", lowered):
        flags.append("pos_mismatch_verb_gloss_on_nominal")
    if pos in {"VERB", "AUX"} and verbform not in {"Part"} and re.match(r"(?:a|an|the)\s", lowered):
        flags.append("pos_mismatch_noun_gloss_on_verb")
    return flags


def _crasis(text):
    """A breathing (coronis) on a vowel that follows a consonant: κἀγώ, τοὔνομα, χὠ."""
    decomposed = unicodedata.normalize("NFD", text)
    previous = []
    for char in decomposed:
        if unicodedata.category(char).startswith("L"):
            previous.append(char.lower())
        elif char in ("̓", "̔") and len(previous) >= 2:
            # the breathing sits on previous[-1]; crasis when a consonant precedes
            # that vowel (or the diphthong it closes)
            before = previous[-2] if previous[-2] not in "αεηιουω" or len(previous) < 3 else previous[-3]
            if before not in "αεηιουω":
                return True
    return False


def _row_lemma(row):
    if row.get("lemma"):
        return row["lemma"], "selected"
    info = (row.get("gloss") or {}).get("lemma_dictionary") or {}
    if info.get("lemma"):
        return info["lemma"], "lemma_dictionary"
    ranking = row.get("morphology_ranking") or []
    if ranking and isinstance(ranking[0].get("score"), (int, float)):
        top = ranking[0]["score"]
        lemmas = {item.get("lemma") for item in ranking if item.get("lemma")
                  and isinstance(item.get("score"), (int, float)) and top - item["score"] < 0.5}
        if len(lemmas) == 1:
            return lemmas.pop(), "top_ranked_shared"
    return None, None


def extract(row, token, text):
    """The fields of one interlinear row (and its token) that scoring needs."""
    gloss = row.get("gloss") or {}
    lemma, lemma_basis = _row_lemma(row)
    info = gloss.get("lemma_dictionary") or {}
    machine = token.get("machine") or {}
    return {"text": row.get("text") or "", "form": token.get("form") or row.get("text") or "",
            "features": row.get("features") or {}, "parse_short": row.get("parse_short"),
            "selection_basis": row.get("selection_basis"), "lemma": lemma, "lemma_basis": lemma_basis,
            "short": gloss.get("short_text"), "full": gloss.get("full_text") or gloss.get("text"),
            "gloss_source": gloss.get("source"), "gloss_basis": gloss.get("selection_basis"),
            "lemma_dictionary": {k: info.get(k) for k in ("status", "headword_queried", "headword_match", "skipped",
                                                           "cross_reference")} if info else None,
            "machine_status": machine.get("status"),
            "normalisation_rules": sorted({c.get("normalisation_rule") for c in machine.get("machine_candidates") or []
                                           if c.get("normalisation_rule")}),
            "ranking": [(item.get("lemma"), item.get("score"), item.get("parse_short")) for item in
                        (row.get("morphology_ranking") or [])[:5]],
            "token_flags": [k for k in ("lacuna_boundary_uncertain", "editorial_reconstruction", "uncertain_letters",
                                        "open_supplement") if token.get(k)],
            "around": text[max(0, token.get("start", 0) - 2):token.get("end", 0) + 2]}


def score_row(raw, poet):
    features = raw["features"]
    pos = features.get("POS")
    coverage = feature_coverage(features)
    lemma, short, full = raw["lemma"], raw["short"], raw["full"]
    flags = gloss_flags(short, full, pos, features.get("VerbForm")) if short else []
    form = raw["form"]
    plausible_lemma = lemma_plausible(form, lemma, pos)
    metrics = {"parse": coverage["status"] == "complete_fields", "lemma": bool(lemma), "gloss": bool(short),
               "plausible_gloss": bool(short) and not flags, "plausible_lemma": bool(plausible_lemma)}
    status = raw["machine_status"]
    info = raw.get("lemma_dictionary") or {}
    classes = []
    printed = raw["text"]
    if raw["token_flags"] or re.search(r"[\[\]…†]|\.\s?\.", raw["around"]):
        classes.append("lacuna_adjacent")
    if printed and printed[-1] in ELISION:
        classes.append("elision")
    if _crasis(printed):
        classes.append("crasis")
    if lemma and re.search(r"[\d\-,]|[A-Za-z]|[" + ELISION + "]$", lemma):
        classes.append("parser_lemma_format")
    if printed[:1] != printed[:1].lower():
        classes.append("proper_name")
    if status == "cache_miss" and not any(metrics.values()):
        classes.append("parser_cache_miss")
    elif status == "cache_miss":
        classes.append("parser_cache_miss_source_only")
    if status == "ok_normalised":
        classes.append("dialect_spelling_normalised")
    if status == "no_analyses":
        classes.append("dialect_spelling" if POET_DIALECT.get(poet) != "attic_popular" else "unknown_to_parser")
    if status == "ok_pattern":
        classes.append("pattern_only")
    skipped = info.get("skipped") or []
    if any(item.get("reason") == "homograph_entries_unresolved" for item in skipped) or \
            raw.get("gloss_basis") == "unresolved_dictionary_entries_not_contextual":
        classes.append("homograph")
    if info.get("status") == "no_headword":
        classes.append("missing_headword")
    elif info.get("status") == "unresolved" and "homograph" not in classes:
        classes.append("no_english_definition")
    if not lemma and coverage["status"] == "complete_fields":
        classes.append("parse_without_lemma")
    if not lemma and coverage["status"] != "complete_fields":
        classes.append("no_parse")
    for flag in flags:
        classes.append("gloss_" + flag)
    if lemma and not plausible_lemma:
        classes.append("lemma_implausible")
    failed = [name for name, ok in metrics.items() if not ok]
    return {"pos": pos, "parse_missing": coverage.get("missing"), "flags": flags, "metrics": metrics,
            "failed": failed, "classes": classes if failed else []}


def analyze(base, pid, text, start, end, fetch_machine):
    body = {"passage_id": pid, "start": start, "end": end, "offset_unit": "codepoint",
            "selected_text": text[start:end], "rerank": False, "fetch_machine": fetch_machine}
    req = urllib.request.Request(base + "/api/analyze-passage", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept-Encoding": "identity"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def passage_ids():
    ids = [json.loads(line)["id"] for line in RECORDS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return sorted(set(ids) | set(FIVE))


def draw(rng, spans, ids):
    by_poet = defaultdict(list)
    for pid in ids:
        by_poet[pid.split(":")[1]].append(pid)
    groups = [g for g in DIALECT if any(p in by_poet for p in DIALECT[g])]
    plan = []
    for index in range(spans):
        group = groups[index % len(groups)]
        poet = rng.choice([p for p in DIALECT[group] if p in by_poet])
        plan.append((group, poet, rng.choice(by_poet[poet]), rng.randint(1, 6), rng.random()))
    return plan


class Pacer:
    def __init__(self, interval):
        self.interval, self.last = interval, 0.0

    def wait(self):
        delay = self.last + self.interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.last = time.monotonic()


def run(args):
    rng = random.Random(args.seed)
    plan = draw(rng, args.spans, passage_ids())
    pacer, texts = Pacer(args.interval), {}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    errors = 0
    with out.open("w", encoding="utf-8") as handle:
        for number, (group, poet, pid, size, position) in enumerate(plan):
            if pid not in texts:
                for _ in range(3):
                    pacer.wait()
                    try:
                        texts[pid] = json.load(urllib.request.urlopen(
                            args.base + "/api/passage?id=" + urllib.parse.quote(pid), timeout=120))["text"]
                        break
                    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                        time.sleep(15)
                if pid not in texts:
                    handle.write(json.dumps({"span": number, "pid": pid, "error": "passage_unavailable"}) + "\n")
                    errors += 1
                    continue
            text = texts[pid]
            words = [t for t in tokenize_span(text, 0, len(text)) if t["kind"] == "word"]
            if not words:
                continue
            first = int(position * max(1, len(words) - size + 1))
            chosen = words[first:first + size]
            start, end = chosen[0]["start"], chosen[-1]["end"]
            result = None
            for attempt in range(4):
                pacer.wait()
                try:
                    result = analyze(args.base, pid, text, start, end, args.fetch_machine)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code == 429 and attempt < 3:
                        time.sleep(10 * (attempt + 1))
                        continue
                    handle.write(json.dumps({"span": number, "pid": pid, "error": exc.code,
                                             "selection": text[start:end]}, ensure_ascii=False) + "\n")
                    errors += 1
                    break
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                    # Dropped connections and truncated bodies are retried once
                    # after a pause, then recorded as an error for the span.
                    if attempt < 1:
                        time.sleep(15)
                        continue
                    handle.write(json.dumps({"span": number, "pid": pid, "error": repr(exc)[:300],
                                             "selection": text[start:end]}, ensure_ascii=False) + "\n")
                    errors += 1
                    break
            if result is None:
                continue
            tokens = {t["id"]: t for t in result.get("tokens") or []}
            for row in result["interlinear"]["readings"][0]["tokens"]:
                if row.get("kind") != "word":
                    continue
                token = tokens.get(row.get("token_id")) or {}
                if row.get("damaged_piece") or token.get("damaged_piece"):
                    kind = "damaged_piece"
                elif row.get("status") == "partial_word" or row.get("selection_basis") == "partial_word" \
                        or token.get("partial_word") or token.get("editorial_fragment"):
                    kind = "fragment"
                else:
                    kind = "word"
                record = {"span": number, "pid": pid, "poet": poet, "dialect": group, "selection": text[start:end],
                          "kind": kind}
                if kind == "word":
                    record.update(extract(row, token, text))
                else:
                    record["text"] = row.get("text")
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            if not args.no_print and number % 10 == 9:
                print(f"{number + 1}/{len(plan)} spans", file=sys.stderr, flush=True)
    summary = report(out, show=not args.no_print)
    Path(str(out) + ".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


METRICS = ("parse", "lemma", "gloss", "plausible_gloss", "plausible_lemma")


def report(path, show=True, examples=4):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    words = [r for r in rows if r.get("kind") == "word"]
    for r in words:
        r.update(score_row(r, r["poet"]))
    errors = [r for r in rows if "error" in r]
    summary = {"file": str(path), "spans": len({r["span"] for r in rows}), "word_rows": len(words),
               "damaged_pieces": sum(r.get("kind") == "damaged_piece" for r in rows),
               "fragments": sum(r.get("kind") == "fragment" for r in rows), "http_errors": len(errors),
               "rates": {m: round(sum(r["metrics"][m] for r in words) / max(1, len(words)), 4) for m in METRICS},
               "all_ok": round(sum(not r["failed"] for r in words) / max(1, len(words)), 4)}
    by_dialect = defaultdict(list)
    for r in words:
        by_dialect[r["dialect"]].append(r)
    summary["by_dialect"] = {d: {"rows": len(rs), **{m: round(sum(r["metrics"][m] for r in rs) / len(rs), 3)
                                                      for m in METRICS}} for d, rs in sorted(by_dialect.items())}
    classes, samples = Counter(), defaultdict(list)
    for r in words:
        for name in r["classes"]:
            classes[name] += 1
            if len(samples[name]) < examples:
                samples[name].append(f"{r['text']} [{r.get('lemma')}] {r.get('parse_short')} -> {r.get('short')!r} "
                                     f"({','.join(r['failed'])}; {r['pid'].split(':', 1)[1]})")
    summary["classes"] = dict(classes.most_common())
    summary["examples"] = {k: samples[k] for k, _ in classes.most_common()}
    if show:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="https://greeklyric.com")
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--spans", type=int, default=120)
    parser.add_argument("--interval", type=float, default=1.0, help="minimum seconds between request starts")
    parser.add_argument("--fetch-machine", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-print", action="store_true", help="write results without printing them (held-out seed)")
    parser.add_argument("--report", default=None, help="summarise an existing result file")
    args = parser.parse_args()
    if args.report:
        report(args.report)
        return
    if not args.out:
        parser.error("--out is required")
    run(args)


if __name__ == "__main__":
    main()
