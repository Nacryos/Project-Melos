#!/usr/bin/env python3
"""Ingest Virgil's hand scansion from hypotactic.com/latin (David Chamberlain, CC BY 4.0) as the second reference poet
for the prosody attestation check L12 (backend/latin_prosody.py; docs/latin/prosody-attestation.md).

Pages: aen1-aen12, geo1-geo4, eclogue1-eclogue10 (ids from https://hypotactic.com/latin/authors.html), the same
div.poem > div.line > span.word > span.syll markup as catullus.html, so the parser, the fetcher (a page is fetched only
when its raw copy is absent, one request at a time with a 1.5 s pause: under 1 request per second) and the row shape are
those of scripts/ingest_open_hypotactic_latin.py. `--extra` adds further works the same way (odes2 odes3 odes4 epodes).

Outputs (data/open/latin/hypotactic/): lines-virgil.jsonl.gz, manifest-virgil.json. lines.jsonl.gz and manifest.json
(Catullus, Horace Odes 1) are not touched. Raw pages: data/raw/latin/hypotactic/ (gitignored), sha256 in the manifest.
Usage: python -I scripts/ingest_open_hypotactic_virgil.py [--extra odes2 odes3 odes4 epodes]
"""
import argparse, gzip, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest_open_hypotactic_latin as base  # noqa: E402

VIRGIL = [f"aen{i}" for i in range(1, 13)] + [f"geo{i}" for i in range(1, 5)] + [f"eclogue{i}" for i in range(1, 11)]
LINES, MANIFEST = "lines-virgil.jsonl.gz", "manifest-virgil.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", nargs="*", default=[], help="further page ids appended after Virgil (e.g. odes2 epodes)")
    args = ap.parse_args()
    os.makedirs(base.OUT, exist_ok=True)
    about, _ = base.fetch("about")
    manifest = {"name": "Hypotactic Latin hand scansion (David Chamberlain): Virgil", "date": time.strftime("%Y-%m-%d"),
                "user_agent": base.UA, "origin": base.BASE,
                "licence": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
                            "stated_on": base.BASE + "about.html",
                            "quote": "All the data on this site is/are licensed as CC-BY 4.0 ... While I have made minor "
                                     "corrections to most texts, the versions of Plautus and Terence found here have been "
                                     "substantially modified, and can be considered my own editions.  The CC-BY licence "
                                     "therefore applies to the full text."},
                "required_attribution": "David Chamberlain, hypotactic.com",
                "use": "prosody attestation (L12) and evaluation gold; never a source for the quantity lexicon",
                "files": {"about.html": {"url": base.BASE + "about.html", "sha256": base.sha(about), "bytes": os.path.getsize(about)}},
                "counts": {"lines": 0, "words": 0, "lines_per_author": {}}}
    out_path = os.path.join(base.OUT, LINES)
    with gzip.open(out_path, "wt", encoding="utf-8") as out:
        for work in VIRGIL + list(args.extra):
            try:
                path, fetched = base.fetch(work)
            except Exception as exc:                      # a missing page is recorded, not fatal
                manifest["files"][work + ".html"] = {"url": base.BASE + work + ".html", "error": f"{type(exc).__name__}: {exc}"}
                print(work, "FAILED", exc, file=sys.stderr)
                continue
            p = base.P(work)
            p.feed(open(path, encoding="utf-8").read())
            metres, words = {}, 0
            for row in p.lines:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                metres[row["metre"]] = metres.get(row["metre"], 0) + 1
                words += len(row["words"])
                a = manifest["counts"]["lines_per_author"]
                a[row["author"]] = a.get(row["author"], 0) + 1
            manifest["files"][work + ".html"] = {"url": base.BASE + work + ".html", "sha256": base.sha(path),
                                                 "bytes": os.path.getsize(path), "fetched_now": fetched, "lines": len(p.lines),
                                                 "words": words, "lines_per_metre": metres}
            manifest["counts"]["lines"] += len(p.lines)
            manifest["counts"]["words"] += words
            print(work, len(p.lines), "lines,", words, "words,", metres, file=sys.stderr)
    manifest["files"][LINES] = {"sha256": base.sha(out_path), "bytes": os.path.getsize(out_path)}
    json.dump(manifest, open(os.path.join(base.OUT, MANIFEST), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
