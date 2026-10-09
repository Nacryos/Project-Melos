"""Citation resolution check (release P; release Q adds five numbering-scheme cases): 35 citations, each with the words its passage must contain.

    python scripts/eval_citations.py --base http://127.0.0.1:8792 --out cite-eval.json

A citation passes when /api/cite returns a passage first whose text contains the expected words
(accents, breathings and case ignored), or for the equivalence case a record whose citation prints
the number. The expected words are the well-known opening words of each passage; they test the
resolver, not the corpus text.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
import urllib.parse
import urllib.request

CASES = [
    ("Il. 1.1", "μηνιν αειδε θεα"), ("Hom. Il. 6.146", "οιη περ φυλλων γενεη"), ("Od. 1.1", "ανδρα μοι εννεπε"),
    ("Hes. Th. 116", "πρωτιστα χαος"), ("Hes. Op. 1", "μουσαι πιεριηθεν"), ("Pind. O. 1.1", "αριστον μεν υδωρ"),
    ("Pi. P. 8.95", "σκιας οναρ"), ("Pind. N. 1.1", "αμπνευμα σεμνον"), ("A.R. 1.1", "αρχομενος σεο φοιβε"),
    ("Theoc. Id. 1.1", "αδυ τι το ψιθυρισμα"), ("Nonn. D. 1.1", "ειπε θεα κρονιδαο"), ("Q.S. 1.1", "πηλειωνι δαμη"),
    ("Arat. Phaen. 1", "εκ διος αρχωμεσθα"), ("Musaeus 1", "ειπε θεα κρυφιων"), ("Lyc. Alex. 1", "λεξω τα παντα"),
    ("Opp. Hal. 1.1", "εθνεα τοι ποντοιο"), ("Bacchylides 3.1", "αριστοκαρπου σικελιας"), ("AP 7.1", "ηρωων τον αοιδον"),
    ("Eur. Med. 1", "ειθ ωφελ αργους"), ("Soph. Ant. 1", "κοινον αυταδελφον"),
    ("urn:cts:greekLit:tlg0012.tlg001:1.1", "μηνιν αειδε"), ("urn:cts:greekLit:tlg0033.tlg001:1.1", "αριστον μεν υδωρ"),
    ("urn:cts:greekLit:tlg2045.tlg001:1.1", "ειπε θεα κρονιδαο"), ("urn:cts:greekLit:tlg0012.tlg002.perseus-grc2:9.366", "ουτις"),
    ("Sappho fr. 1", "ποικιλοθρον"), ("Sappho fr. 31", "φαινεται μοι"), ("Sappho 16", "οι μεν ιππηων"),
    ("Alc. 346", "πωνωμεν"), ("Anacr. 348", "γουνουμαι σ ελαφηβολε"), ("Sappho fr. 168A LP", "#168A"),
    # release Q: numbering schemes (Voigt, Lobel-Page, Campbell) resolve to the same poems
    ("Sappho fr. 31 V", "φαινεται μοι"), ("Alc. 346 L-P", "πωνωμεν"), ("Sappho Campbell 16", "οι μεν ιππηων"),
    ("Sapph. 1 Voigt", "ποικιλοθρον"), ("Alc. 38a L.P.", "πωνε"),
]


def fold(text):
    text = unicodedata.normalize("NFD", str(text or "")).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c) and (c.isalpha() or c.isspace()))
    return " ".join(text.replace("ς", "σ").split())


def get(base, path, **params):
    url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8792")
    p.add_argument("--out", default="")
    args = p.parse_args()
    rows, passed = [], 0
    for query, expect in CASES:
        data = get(args.base, "/api/cite", q=query)
        results = data.get("results") or []
        ok, top = False, None
        if expect.startswith("#"):
            number = expect[1:].casefold()
            hits = [r for r in results if number in fold(r.get("citation"))]
            hits += [r for eq in data.get("equivalents") or [] for r in eq.get("results", [])]
            ok, top = bool(hits or any(e["number"] == number for e in data.get("equivalents") or [])), \
                (hits[0]["id"] if hits else None)
        elif results:
            top = results[0]["id"]
            text = get(args.base, "/api/passage", id=top).get("text", "")
            ok = fold(expect) in fold(text)
        passed += ok
        rows.append({"query": query, "kind": (data.get("parsed") or {}).get("kind"), "ok": ok, "top": top,
                     "top_citation": results[0].get("citation") if results else None, "total": data.get("total"),
                     "warnings": data.get("warnings")})
        print("PASS" if ok else "FAIL", query, "->", top, (results[0].get("citation") if results else ""))
    summary = {"passed": passed, "cases": len(CASES), "rows": rows}
    print(f"{passed}/{len(CASES)} citations resolved to a passage containing the expected words")
    if args.out:
        open(args.out, "w", encoding="utf-8").write(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
