"""Latin composer checks counted against Catullus's own hendecasyllables (docs/prd/catullan-hendecasyllable-checks.md).

L13 `check`: Phalaecian manner (base, word-ends, elisions, line-end word), each with the share of Catullus's lines
that do the same; never blocks. L8 `check_elision`: elision, prodelision and hiatus read off the scanner's own parse
(elision is a parse branch in backend/scansion/metre.py); hiatus blocks unless of a kind found in Catullus.

The numbers come from data/open/latin/phalaecian-profile/profile.json (scripts/build_phalaecian_profile.py, counted
from the Hypotactic hand scansion). `line_features` is the one feature reader: the profile is built with it from the
gold and a draft is read with it from the scanner's parse, so the two are counted the same way. Nothing here raises;
without the profile a check returns ok True with detail "unavailable: ...".
"""
from __future__ import annotations

import json
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

from .scansion.latin import ALWAYS_DIPHTHONG, ELISION_MARKS, INTERJECTIONS, MACRON, VOWELS, key as la_key

BASES = {"LL": "spondee", "LS": "trochee", "SL": "iamb", "SS": "pyrrhic"}
EST = ("est", "es")
PUNCT = ",.;:!?"
ELIDED_KINDS = ("short vowel", "long vowel or diphthong", "-m")
DECASYLLABLE = {"phalaecian": "phalaecian_decasyllable"}      # the per-line alternative of Catullus 55 and 58b


def profile_path() -> Path:
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "open" / "latin" / "phalaecian-profile" / "profile.json"


@lru_cache(maxsize=4)
def _load(path: str) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def profile() -> dict | None:
    return _load(str(profile_path()))


# ------------------------------------------------------------------------------------------------ features

def _letters(form: str) -> str:
    return "".join(ch for ch in la_key(form) if ch.isalpha())


def _ends_long(form: str) -> bool:
    """The form as written ends in a vowel carrying a macron (Hypotactic prints them; a draft may)."""
    nfd = unicodedata.normalize("NFD", form).rstrip(PUNCT + ELISION_MARKS + "\"”“‘) ")
    return nfd.endswith(MACRON)


def elided_kind(form: str, long: bool | None = None) -> str:
    k = _letters(form)
    if k.endswith("m"):
        return "-m"
    if k[-2:] in ALWAYS_DIPHTHONG or (long if long is not None else _ends_long(form)):
        return "long vowel or diphthong"
    return "short vowel"


def _sounded(word: dict) -> int:
    return sum(1 for s in word["syl"] if s["q"] != "E")


def _ends_elided(word: dict) -> bool:
    return bool(word["syl"]) and word["syl"][-1]["q"] == "E"


def _punct_after(form: str) -> bool:
    return form.rstrip("\"”“‘’') ")[-1:] in PUNCT


def hiatus_kind(word: dict, nxt: dict | None, flags: list[str]) -> str:
    """Kinds are read off the forms: an interjection on either side, a long monosyllable kept short (semihiatus),
    punctuation between the words, or none of these (plain)."""
    if _letters(word["form"]) in INTERJECTIONS or (nxt is not None and _letters(nxt["form"]) in INTERJECTIONS):
        return "beside an interjection"
    if "semihiatus" in flags:
        return "semihiatus of a long monosyllable"
    if _punct_after(word["form"]):
        return "at punctuation"
    return "plain"


def line_features(words: list[dict]) -> dict:
    """Features of one scanned line. `words` has the gold's shape: [{"form", "syl": [{"t", "q": L/S/E, "f": [...]}]}];
    an elided syllable is E; prodelision is written the gold's way (the syllable before est / es is E, est is long).
    Syllable numbers count sounded syllables from 1."""
    words = [w for w in words if w.get("syl")]
    total = sum(_sounded(w) for w in words)
    qs = [s["q"] for w in words for s in w["syl"] if s["q"] != "E"]
    clean, bridged, elisions, prodelisions, hiatus = [], [], [], [], []
    c = 0
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        for s in w["syl"]:
            if s["q"] != "E":
                c += 1
            fl = [f for f in s.get("f", []) if f in ("hiatus", "semihiatus")]
            if fl:
                hiatus.append({"word": w["form"], "next": nxt["form"] if nxt else "", "after": c,
                               "kind": hiatus_kind(w, nxt, fl)})
        prod = _ends_elided(w) and nxt is not None and _letters(nxt["form"]) in EST
        if _ends_elided(w):
            e = {"word": w["form"], "next": nxt["form"] if nxt else "", "at": c + 1,
                 "kind": elided_kind(w["form"], w["syl"][-1].get("long")), "monosyllable": len(w["syl"]) == 1,
                 "length_uncertain": bool(w["syl"][-1].get("uncertain")) and not _letters(w["form"]).endswith("m")}
            (prodelisions if prod else elisions).append(e)
        if nxt is None or prod:
            continue                                   # gratum est = gratumst: no word-end inside it
        if 0 < c < total:
            (bridged if _ends_elided(w) else clean).append(c)
    clean = sorted(set(clean))
    bridged = sorted(set(bridged) - set(clean))
    last = words[-1] if words else {"form": "", "syl": []}
    final_prod = len(words) >= 2 and _letters(last["form"]) in EST and _ends_elided(words[-2])
    final_n = _sounded(last) + (_sounded(words[-2]) if final_prod else 0)
    strip = lambda s: s.strip(PUNCT + "\"”“‘’'() ")  # noqa: E731
    f = {"sounded": total, "base": BASES.get("".join(qs[:2]), "other"), "word_ends": clean, "word_ends_elided": bridged,
         "break": ("both" if 5 in clean and 6 in clean else "5th" if 5 in clean else "6th" if 6 in clean else "neither"),
         "break_with_elision": _break(set(clean) | set(bridged)),
         "elisions": elisions, "prodelisions": prodelisions, "hiatus": hiatus,
         "final_word": {"form": (strip(words[-2]["form"]) + " " if final_prod else "") + strip(last["form"]), "syllables": final_n,
                        "prodelided_est": final_prod}}
    f["keys"] = feature_keys(f)
    return f


def _break(ends: set[int]) -> str:
    return "both" if 5 in ends and 6 in ends else "5th" if 5 in ends else "6th" if 6 in ends else "neither"


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def feature_keys(f: dict) -> list[tuple[str, str]]:
    """(key, plain label) for every countable feature of the line. Word-end and break keys only for 11 syllables:
    the decasyllable's positions are not the hendecasyllable's."""
    keys = [("length:%d" % f["sounded"], "%d syllables" % f["sounded"]), ("base:" + f["base"], f["base"] + " base")]
    if f["sounded"] == 11:
        keys += [("word_end:%d" % k, "word-end after the " + ordinal(k)) for k in f["word_ends"]]
        keys.append(("break:" + f["break"], {"5th": "main break after the 5th", "6th": "main break after the 6th",
                                              "both": "word-end after both the 5th and the 6th",
                                              "neither": "no word-end after the 5th or the 6th"}[f["break"]]))
    n = len(f["elisions"])
    keys.append(("elisions:%d" % n, "%d elision%s in the line" % (n, "" if n == 1 else "s")))
    for e in f["elisions"]:
        keys.append(("elision_at:%d" % e["at"], "elision at the " + ordinal(e["at"]) + " syllable"))
        keys.append(("elision_kind:" + e["kind"], "elision of a " + e["kind"] if e["kind"] != "-m" else "elision of -m"))
        if e["monosyllable"]:
            keys.append(("elision_monosyllable", "elision of a monosyllable"))
    if f["prodelisions"]:
        keys.append(("prodelision", "prodelision of est / es"))
    for h in f["hiatus"]:
        keys.append(("hiatus:" + h["kind"], "hiatus " + h["kind"]))
    keys.append(("final_syllables:%d" % f["final_word"]["syllables"],
                 "line-end word of %d syllable%s" % (f["final_word"]["syllables"], "" if f["final_word"]["syllables"] == 1 else "s")))
    if f["final_word"]["prodelided_est"]:
        keys.append(("final_prodelided_est", "line ending in prodelided est"))
    seen, out = set(), []
    for k in keys:
        if k[0] not in seen:
            seen.add(k[0])
            out.append(k)
    return out


# ------------------------------------------------------------------------------------------------ a draft's parse

def _draft_lines(text: str, metre_name: str, alt_when: str = "not_ok") -> list[dict]:
    """One record per non-empty line: the scanner's units, the fit, and (when the line parses) the words in the gold's
    shape with the parse's weights. A kept unit in an elision environment (ELI-* / PROD-* flag) is flagged hiatus.
    The decasyllabic alternative is tried when the named metre's fit is not ok (L13), or only when it has no parse
    at all (`alt_when="no_parse"`, L8: a line that scans as a hendecasyllable with hiatus is judged as that)."""
    from .scansion import metre
    from .scansion.quantity_la import default_scanner
    from .scansion.syllabify_la import words_of
    sc = default_scanner()
    out = []
    for n, raw in enumerate((l for l in str(text or "").splitlines() if l.strip()), 1):
        units = sc.scan(raw)
        fit = metre.fit_line(units, metre_name) if units else None
        name = metre_name
        alt = DECASYLLABLE.get(metre_name)
        if fit is not None and alt in metre.TEMPLATES and not (fit.ok if alt_when == "not_ok" else fit.assignment):
            f2 = metre.fit_line(units, alt)
            if f2.ok:
                fit, name = f2, alt
        rec = {"line": n, "text": raw.strip(), "fit": fit, "metre": name, "words": None}
        out.append(rec)
        if fit is None or not fit.assignment:
            continue
        weight = {}
        for a in fit.assignment:
            ids = a["syllables"]
            weight[ids[0]] = "E" if a.get("elided") else a["weight"]
            for extra in ids[1:]:
                weight[extra] = "-"                      # second half of a synizesis: no syllable of its own
        ws = words_of(raw, spelling=sc.spelling)
        words = []
        for j, w in enumerate(ws):
            form = raw[w.start:(ws[j + 1].start if j + 1 < len(ws) else len(raw))].strip()
            syl = []
            for u in units:
                if u.word != w.index or weight.get(u.index, "-") == "-":
                    continue
                cand = any(fl["id"].startswith(("ELI-", "PROD")) and fl["id"] != "ELI-1" for fl in u.flags)
                syl.append({"t": u.text, "q": weight[u.index], "f": [], "long": u.vowel.get("p_long", 0.5) > 0.5,
                            "uncertain": 0.1 < u.vowel.get("p_long", 0.5) < 0.9,
                            "candidate": cand, "written_elided": bool(getattr(w, "elided", False))})
            words.append({"form": form, "syl": syl})
        words = [w for w in words if w["syl"]]
        for j, w in enumerate(words):                    # prodelision the gold's way: -um E, est long
            if j and _letters(w["form"]) in EST and len(w["syl"]) == 1 and w["syl"][0]["q"] == "E" \
                    and words[j - 1]["syl"][-1]["q"] != "E":
                words[j - 1]["syl"][-1]["q"], w["syl"][0]["q"] = "E", "L"
                w["syl"][0]["candidate"] = False
        for j, w in enumerate(words[:-1]):
            last = w["syl"][-1]
            if last["candidate"] and last["q"] != "E":
                mono_long = len(w["syl"]) == 1 and last["long"] and not _letters(w["form"]).endswith("m")
                last["f"] = ["semihiatus" if mono_long else "hiatus"]
        rec["words"] = words
    return out


def _share(p: dict, key: str) -> dict:
    """Catullus's count for one feature key; a key he never has counts 0 of the lines it could stand in."""
    row = (p.get("features") or {}).get(key)
    if row:
        return row
    of = p.get("denominators", {}).get("hendecasyllables" if key.startswith(("word_end:", "break:")) else "lines", 0)
    return {"lines": 0, "of": of, "share": 0.0, "rare": True, "loci": []}


def _pct(row: dict) -> str:
    return f"{100 * row['share']:.1f} % of Catullus's lines"


def _unavailable(cid: str, name: str, blocking: bool, why: str) -> dict:
    return {"id": cid, "name": name, "ok": True, "blocking": blocking, "detail": "unavailable: " + why, "evidence": []}


# ------------------------------------------------------------------------------------------------ L13

def check(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L13 Phalaecian manner: each fitting line's base, word-ends, elisions and line-end word with Catullus's
    measured share, and a warning with loci for any feature in under the profile's rare threshold of his lines."""
    cid, name = "L13", "Phalaecian manner"
    try:
        p = profile()
        if p is None:
            return _unavailable(cid, name, False, "no Phalaecian profile (run scripts/build_phalaecian_profile.py)")
        if metre_name not in ("phalaecian", "phalaecian_decasyllable"):
            return _unavailable(cid, name, False, f"the profile is of Catullus's Phalaecians, not {metre_name}")
        rare_at = p.get("rare_threshold", 0.02)
        parts, warnings, evidence = [], [], []
        for rec in _draft_lines(text, metre_name):
            fit = rec["fit"]
            if fit is None or not fit.ok or not rec["words"]:
                parts.append(f"line {rec['line']}: does not fit the metre (see L7), not profiled")
                evidence.append({"line": rec["line"], "text": rec["text"], "fits": False})
                continue
            f = line_features(rec["words"])
            rows = [{"key": k, "label": label, **{x: _share(p, k)[x] for x in ("lines", "of", "share", "loci")}}
                    for k, label in f["keys"]]
            by = {r["key"]: r for r in rows}
            bits = [f"{f['base']} base ({_pct(by['base:' + f['base']])})"]
            if f["sounded"] == 11:
                bits.append("word-ends after " + (", ".join(f"the {ordinal(k)} ({100 * by['word_end:%d' % k]['share']:.0f} %)"
                                                            for k in f["word_ends"]) or "no syllable"))
                bits.append(by["break:" + f["break"]]["label"] + f" ({_pct(by['break:' + f['break']])})")
            else:
                poems = sorted({d["locus"].split(".")[0] for d in p.get("decasyllable_lines", [])})
                bits.append(f"decasyllable ({_pct(by['length:%d' % f['sounded']])}; only in poems {', '.join(poems)})")
                warnings.append(f"line {rec['line']}: a decasyllable: Catullus has {by['length:10']['lines']} in "
                                f"{by['length:10']['of']} lines, all in poems {', '.join(poems)}")
            n = len(f["elisions"])
            bits.append(f"{n} elision{'' if n == 1 else 's'} ({_pct(by['elisions:%d' % n])})"
                        + "".join(f"; {e['word']} elided at the {ordinal(e['at'])} "
                                  f"({100 * by['elision_at:%d' % e['at']]['share']:.1f} %)" for e in f["elisions"]))
            fw = f["final_word"]
            bits.append(f"line-end word {fw['form']}, {fw['syllables']} syllable{'' if fw['syllables'] == 1 else 's'} "
                        f"({_pct(by['final_syllables:%d' % fw['syllables']])})")
            parts.append(f"line {rec['line']}: " + "; ".join(bits))
            rare = [r for r in rows if r["share"] < rare_at]
            for r in rare:
                loci = ", ".join(r["loci"][:5])
                warnings.append(f"line {rec['line']}: {r['label']} is rare in Catullus: {r['lines']} of {r['of']} lines "
                                f"({100 * r['share']:.1f} %, under {100 * rare_at:.0f} %)" + (f": {loci}" if loci else ""))
            evidence.append({"line": rec["line"], "text": rec["text"], "fits": True, "metre": rec["metre"],
                             "pattern": fit.pattern, "base": f["base"], "word_ends": f["word_ends"],
                             "word_ends_in_elision": f["word_ends_elided"], "break": f["break"],
                             "elisions": f["elisions"], "prodelisions": f["prodelisions"], "final_word": fw,
                             "features": rows, "rare": [r["key"] for r in rare]})
        detail = "; ".join(parts) if parts else "no lines"
        if warnings:
            detail += " | WARNINGS: " + "; ".join(warnings)
        return {"id": cid, "name": name, "ok": True, "blocking": False, "detail": detail, "evidence": evidence,
                "warnings": warnings}
    except Exception as exc:  # noqa: BLE001  (contract: nothing raises)
        return _unavailable(cid, name, False, f"{type(exc).__name__}: {exc}")


# ------------------------------------------------------------------------------------------------ L8

def _restore(form: str) -> list[str]:
    """Full forms for a form written elided (dict', atqu') or fused with est (malest, dictumst): the stem plus each
    elidable ending (a vowel, or a vowel + m) that the quantity lexicon knows; X + st as X est / Xs est."""
    try:
        from .scansion.quantity_la import default_scanner
        lex = default_scanner().lexicon
        if lex is None:
            return []
        k = _letters(form)
        raw = form.rstrip(PUNCT + "\"”“‘) ")
        if raw[-1:] in ELISION_MARKS:
            return [k + v + m for v in sorted(VOWELS) for m in ("", "m") if lex.rows(k + v + m)]
        if k.endswith("st") and len(k) > 3 and not lex.rows(k):
            return [x + " est" for x in (k[:-2], k[:-2] + "s") if lex.rows(x)][:1]
    except Exception:  # noqa: BLE001
        pass
    return []


def _shown(e: dict) -> str:
    """atque amemus -> atqu(e) amemus: the letters that drop out, in brackets."""
    w = e["word"].rstrip(PUNCT + "\"”“‘’') ")
    cut = 2 if _letters(w).endswith("m") else 1
    if _letters(w)[-2:] in ALWAYS_DIPHTHONG:
        cut = 2
    return f"{w[:-cut]}({w[-cut:]}) {e['next']}"


def check_elision(text: str, *, metre_name: str = "phalaecian", author: str = "Catullus") -> dict:
    """L8 elision and hiatus, from the scanner's best parse of each line. Hiatus blocks unless Catullus has the kind
    (the profile's `hiatus` list, shown with its locus); each elision is listed with its kind and Catullus's count."""
    cid, name = "L8", "elision and hiatus"
    try:
        p = profile()
        if p is None:
            return _unavailable(cid, name, True, "no Phalaecian profile (run scripts/build_phalaecian_profile.py)")
        el = p.get("elision", {})
        kinds, monos = el.get("kinds", {}), el.get("monosyllables", {})
        n_el, n_lines = el.get("total", 0), p.get("denominators", {}).get("lines", 0)
        allowed = {}
        for h in p.get("hiatus", []):
            allowed.setdefault(h["kind"], []).append(h)
        parts, failures, warnings, evidence = [], [], [], []
        for rec in _draft_lines(text, metre_name, alt_when="no_parse"):
            if not rec["words"]:
                parts.append(f"line {rec['line']}: no parse in this metre (see L7), elision not judged")
                continue
            f = line_features(rec["words"])
            written = {w["form"]: _restore(w["form"]) for w in rec["words"]
                       if w["form"].rstrip(PUNCT)[-1:] in ELISION_MARKS or _letters(w["form"]).endswith("st")}
            for form, full in written.items():
                if full:
                    parts.append(f"line {rec['line']}: {form} restored: {' or '.join(full)}")
                    evidence.append({"line": rec["line"], "type": "restored", "word": form, "restored": full})
            for e in f["elisions"]:
                k = kinds.get(e["kind"], {"n": 0})
                row = _share(p, "elision_kind:" + e["kind"])
                msg = (f"line {rec['line']}: {_shown(e)}: elision of {'a ' if e['kind'] != '-m' else ''}{e['kind']} at the "
                       f"{ordinal(e['at'])} syllable ({k['n']} of Catullus's {n_el} elisions; in {100 * row['share']:.1f} % of his lines)"
                       + ("; the scanner cannot tell this final vowel's length" if e.get("length_uncertain") else ""))
                ev = {"line": rec["line"], "type": "elision", **e, "shown": _shown(e),
                      "catullus": {"kind_elisions": k["n"], "elisions": n_el, "kind_lines": row["lines"], "lines": row["of"]}}
                if e["monosyllable"]:
                    m = monos.get(_letters(e["word"]))
                    if m:
                        msg += f"; the monosyllable {_letters(e['word'])} is elided {m['n']} times in Catullus ({', '.join(m['loci'][:3])})"
                    else:
                        has = ", ".join(f"{w} {v['n']}" for w, v in sorted(monos.items(), key=lambda t: -t[1]["n"]))
                        warn = (f"line {rec['line']}: Catullus never elides the monosyllable {_letters(e['word'])} in his "
                                f"{n_lines} hendecasyllables (he elides: {has})")
                        warnings.append(warn)
                    ev["catullus"]["monosyllable"] = m
                parts.append(msg)
                evidence.append(ev)
            for e in f["prodelisions"]:
                row = _share(p, "prodelision")
                w = e["word"].rstrip(PUNCT)
                parts.append(f"line {rec['line']}: {w} {e['next']} read {w}st (prodelision; {row['lines']} of {row['of']} of Catullus's lines)")
                evidence.append({"line": rec["line"], "type": "prodelision", **e, "shown": w + "st",
                                 "catullus": {"lines": row["lines"], "of": row["of"]}})
            for h in f["hiatus"]:
                seen = allowed.get(h["kind"], [])
                ev = {"line": rec["line"], "type": "hiatus", **h, "catullus": seen[:5], "allowed": bool(seen)}
                evidence.append(ev)
                where = f"{h['word']} | {h['next']}"
                if seen:
                    loci = ", ".join(f"{x['locus']} ({x['word']} {x['next']})" for x in seen[:5])
                    parts.append(f"line {rec['line']}: hiatus {where} ({h['kind']}): Catullus has this {len(seen)} time"
                                 f"{'' if len(seen) == 1 else 's'} in {n_lines} lines: {loci}")
                else:
                    failures.append(f"line {rec['line']}: hiatus {where} ({h['kind']}): not once in Catullus's {n_lines} "
                                    f"hendecasyllables; elide, or reorder so a consonant stands between")
        detail = "; ".join(failures + warnings + parts) or "no elision, prodelision or hiatus"
        return {"id": cid, "name": name, "ok": not failures, "blocking": True, "detail": detail, "evidence": evidence,
                "warnings": warnings}
    except Exception as exc:  # noqa: BLE001  (contract: nothing raises)
        return _unavailable(cid, name, True, f"{type(exc).__name__}: {exc}")
