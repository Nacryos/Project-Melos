"""Layer 2 (optional): fit metre-free syllable probabilities to a metre, or to an antistrophe.

A template is a string of position symbols:

  -  long            u  short            x  anceps (either)        F  line end (brevis in longo)
  D  biceps: one long or two shorts (dactylic)
  R  resolvable long: one long, or two shorts at a cost (iambic/trochaic resolution)
  X  resolvable anceps: one syllable of either length, or two shorts at a cost

Every parse of a line against a template has the probability  Π p(weight of each syllable) ×
template priors (resolution, spondaic 5th foot, synizesis). The best parse is reported; the
posterior longness of every syllable is the probability-weighted share of parses in which it is
long. Positions where the best parse contradicts a near-certain layer-1 value are reported as
violations with the layer-1 rule. Layer 1's own probabilities are returned unchanged beside the
metrical ones.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from .quantity import SyllableResult

LATIN_METRES = Path(__file__).resolve().parent / "metres_la.yaml"

P_FLOOR = 0.003            # a "certain" layer-1 value can still be overruled, at a visible cost
VIOLATION = 0.05           # best parse uses a weight the scanner gave at most this probability
PRIOR = {
    "resolution": 0.08,    # one long position realised as two shorts (R, X)
    "spondee5": 0.05,      # spondaic fifth foot of the hexameter
    "split_word": 0.02,    # a verse end inside a word (only when segmenting running text)
}

TEMPLATES: dict[str, list[str]] = {
    "hexameter": ["-D-D-D-D-D-F"],
    "pentameter": ["-D-D--uu-uuF"],
    "elegiac": ["-D-D-D-D-D-F", "-D-D--uu-uuF"],
    "iambic_trimeter": ["XRuRXRuRXRuF"],
    "trochaic_tetrameter": ["RuRXRuRXRuRXRuF"],
    "sapphic_hendecasyllable": ["-u-x-uu-u-F"],
    "adonean": ["-uu-F"],
    "sapphic": ["-u-x-uu-u-F", "-u-x-uu-u-F", "-u-x-uu-u-F", "-uu-F"],
    "alcaic_hendecasyllable": ["x-u-x-uu-uF"],
    "alcaic_enneasyllable": ["x-u-x-u-F"],
    "alcaic_decasyllable": ["-uu-uu-u-F"],
    "alcaic": ["x-u-x-uu-uF", "x-u-x-uu-uF", "x-u-x-u-F", "-uu-uu-u-F"],
    "glyconic": ["xx-uu-uF"],
    "pherecratean": ["xx-uu-F"],
    "hipponactean": ["xx-uu-u-F"],
    "telesillean": ["x-uu-uF"],
    "reizianum": ["x-uu-F"],
    "aristophanean": ["-uu-u-F"],
    "lesser_asclepiad": ["xx-uu--uu-uF"],
    "greater_asclepiad": ["xx-uu--uu--uu-uF"],
}
AUTO = ["hexameter", "pentameter", "iambic_trimeter", "trochaic_tetrameter", "sapphic_hendecasyllable",
        "adonean", "alcaic_hendecasyllable", "alcaic_enneasyllable", "alcaic_decasyllable", "glyconic",
        "pherecratean", "hipponactean", "telesillean", "reizianum", "aristophanean", "lesser_asclepiad",
        "greater_asclepiad"]
TEMPLATE_INFO: dict[str, dict] = {}          # Latin metres: label, caesura, cite (from metres_la.yaml)
BASE_PRIORS: dict[str, dict[str, float]] = {}   # template string -> realisation of the first two positions -> prior
AUTO_BY_LANGUAGE: dict[str, list[str]] = {"grc": AUTO}
LANGUAGE_OF: dict[str, set[str]] = {"grc": set(TEMPLATES)}
METRE_PARAMS = {"hiatus_violation_min": 0.9}


def load_latin_metres(path: Path | None = None) -> list[str]:
    """Add the Latin metres (metres_la.yaml) to the shared tables. Returns validation errors (empty when fine)."""
    import yaml
    doc = yaml.safe_load((path or LATIN_METRES).read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    la: set[str] = set()
    for name, spec in (doc.get("templates") or {}).items():
        lines = spec.get("lines") if isinstance(spec, dict) else spec
        if not isinstance(lines, list) or not lines or any(set(x) - set("-uxFDRX") for x in lines):
            errors.append(f"templates.{name}: lines must use the symbols - u x F D R X")
            continue
        if any(not x.endswith("F") for x in lines):
            errors.append(f"templates.{name}: every line template ends with F")
            continue
        TEMPLATES[name] = list(lines)
        TEMPLATE_INFO[name] = {k: v for k, v in (spec.items() if isinstance(spec, dict) else []) if k != "lines"}
        la.add(name)
    for name in doc.get("shared") or []:
        if name not in TEMPLATES:
            errors.append(f"shared: unknown metre {name}")
        else:
            la.add(name)
    for tpl, pri in (doc.get("base_priors") or {}).items():
        if not isinstance(pri, dict) or any(k not in ("--", "-u", "u-", "uu") or not 0 <= float(v) <= 1 for k, v in pri.items()):
            errors.append(f"base_priors[{tpl}]: keys --, -u, u-, uu with values 0..1")
        else:
            BASE_PRIORS[tpl] = {k: float(v) for k, v in pri.items()}
    auto = [n for n in (doc.get("auto") or []) if n in TEMPLATES]
    AUTO_BY_LANGUAGE["la"] = auto
    LANGUAGE_OF["la"] = la
    for k, v in (doc.get("params") or {}).items():
        METRE_PARAMS[k] = float(v)
    return errors


_LATIN_ERRORS = load_latin_metres()


@dataclass
class Unit:
    """One syllable, or a synizesis merger of two, as the metre sees it."""
    first: int
    last: int
    p_long: float
    prior: float           # probability of choosing this unit shape (merge / not merge)


@dataclass
class Fit:
    metre: str
    template: str
    ok: bool
    log_likelihood: float
    per_syllable: float
    pattern: str
    assignment: list[dict] = field(default_factory=list)
    posterior: list[float] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    message: str = ""
    elided: list[float] | None = None      # Latin: posterior probability that each unit is elided

    def as_dict(self) -> dict:
        finite = math.isfinite(self.log_likelihood)    # a line that does not parse has -inf: JSON null
        d = {"metre": self.metre, "template": self.template, "ok": self.ok,
             "log_likelihood": round(self.log_likelihood, 3) if finite else None,
             "per_syllable": round(self.per_syllable, 4) if finite else None,
             "pattern": self.pattern, "assignment": self.assignment,
             "posterior_p_long": [round(p, 3) for p in self.posterior], "violations": self.violations,
             "message": self.message}
        if self.elided is not None:
            d["posterior_elided"] = self.elided
        return d


def _clamp(p: float) -> float:
    return min(max(p, P_FLOOR), 1 - P_FLOOR)


def _merge_p(s: SyllableResult) -> float | None:
    for f in s.flags:
        if f["id"] == "SYN-CAND" and f.get("p") is not None:
            return f["p"]
    return None


def parses(sylls: list[SyllableResult], template: str, limit: int = 20000):
    """Yield (probability, [(unit_first, unit_last, weight 'L'/'S'/'E', position index, symbol)]).

    Weight 'E' marks a unit the parse elides (Latin): it takes no template position (symbol 'E', position -1).
    Prodelision (the unit before *est* / *es*) keeps that unit, long by position, and elides the next one."""
    n = len(sylls)
    merge = [_merge_p(s) for s in sylls]
    elide = [min(max(getattr(s, "elision", 0.0) or 0.0, 0.0), 1.0) for s in sylls]
    prod = [getattr(s, "prodelision", None) for s in sylls]
    base = BASE_PRIORS.get(template)
    out = []

    def unit_choices(i):
        """(next index, p_long of the unit, prior, first, last)."""
        pm = merge[i] if i + 1 < n and sylls[i + 1].line == sylls[i].line else None
        if pm is None:
            yield i + 1, sylls[i].p_long, 1.0, i, i
        else:
            yield i + 1, sylls[i].p_long, 1 - pm, i, i
            yield i + 2, 1.0, pm, i, i + 1

    def assign(ni, j, prob, acc, pl, prior, a, b, tail=()):
        """Place one unit (a..b, longness pl) at template position j, then recurse."""
        sym = template[j]
        pl = _clamp(pl)
        tail = list(tail)

        def go(w, p):
            entry = [(a, b, w, j, sym)] + tail
            if base is not None and j == 1:
                first = next((e[2] for e in reversed(acc) if e[2] in "LS"), None)
                if first is not None:
                    p = p * base.get(("-" if first == "L" else "u") + ("-" if w == "L" else "u"), 1.0)
            rec(ni, j + 1, p, acc + entry)

        if sym in "-RD":
            go("L", prob * prior * pl * (PRIOR["spondee5"] if sym == "D" and _foot(template, j) == 5 else 1.0))
        if sym == "u":
            go("S", prob * prior * (1 - pl))
        if sym in "xX":
            go("L", prob * prior * pl)
            go("S", prob * prior * (1 - pl))
        if sym == "F":
            go("L" if pl >= 0.5 else "S", prob * prior)

    def rec(i, j, prob, acc):
        if len(out) >= limit or prob == 0.0:
            return
        if j == len(template):
            if i == n:
                out.append((prob, list(acc)))
            return
        if i >= n:
            return
        keep = 1.0
        e = elide[i]
        if e > 0:
            rec(i + 1, j, prob * e, acc + [(i, i, "E", -1, "E")])
            keep *= 1 - e
        pd = prod[i]
        if pd and i + 1 < n and sylls[i + 1].line == sylls[i].line:
            assign(i + 2, j, prob * keep * float(pd.get("p", 0)), acc, float(pd.get("p_long", 1.0)), 1.0, i, i,
                   tail=[(i + 1, i + 1, "E", -1, "E")])
            keep *= 1 - float(pd.get("p", 0))
        if keep <= 0:
            return
        for ni, pl, prior, a, b in unit_choices(i):
            assign(ni, j, prob, acc, pl, prior * keep, a, b)
        sym = template[j]
        if sym in "DRX" and i + 1 < n and sylls[i + 1].line == sylls[i].line:
            p1, p2 = _clamp(sylls[i].p_long), _clamp(sylls[i + 1].p_long)
            pri = 1.0 if sym == "D" else PRIOR["resolution"]
            if sym == "D" and _foot(template, j) == 5:
                pri = 1 - PRIOR["spondee5"]
            rec(i + 2, j + 1, prob * keep * pri * (1 - p1) * (1 - p2),
                acc + [(i, i, "S", j, sym), (i + 1, i + 1, "S", j, sym)])

    rec(0, 0, 1.0, [])
    return out


def _foot(template: str, j: int) -> int:
    """Dactylic foot number (1-based) of position j (feet are '-' + 'D')."""
    return template[: j + 1].count("-") if template[0] == "-" else 0


def fit_line(sylls: list[SyllableResult], metre: str, template: str | None = None) -> Fit:
    template = template or TEMPLATES[metre][0]
    ps = parses(sylls, template)
    if not ps:
        lo, hi = _length_range(template)
        elidable = sum(1 for s in sylls if (getattr(s, "elision", 0.0) or 0.0) >= 0.5)
        msg = (f"{len(sylls)} syllables" + (f" ({elidable} elidable)" if elidable else "") + f"; {metre} needs {lo}"
               + (f"-{hi}" if hi != lo else "") + " (after possible synizesis" + (" and elision" if elidable else "") + ")")
        return Fit(metre, template, False, float("-inf"), float("-inf"), "", message=msg)
    total = sum(p for p, _ in ps)
    best_p, best = max(ps, key=lambda t: t[0])
    post_long = [0.0] * len(sylls)
    post_elided = [0.0] * len(sylls)
    for p, acc in ps:
        for a, b, w, _, _ in acc:
            if w == "L":
                for k in range(a, b + 1):
                    post_long[k] += p
            elif w == "E":
                post_elided[a] += p
    posterior = [x / total for x in post_long]
    assignment, violations, pattern = [], [], []
    hiatus_min = METRE_PARAMS.get("hiatus_violation_min", 0.9)
    for a, b, w, j, sym in best:
        s = sylls[a]
        entry = {"syllables": list(range(sylls[a].index, sylls[b].index + 1)), "weight": w, "position": j,
                 "symbol": sym}
        if w == "E":
            entry["elided"] = True
            assignment.append(entry)
            continue
        if b > a:
            entry["synizesis"] = True
        assignment.append(entry)
        pattern.append("–" if w == "L" else "⏑")
        if sym != "F" and b == a:
            p_w = s.p_long if w == "L" else 1 - s.p_long
            if p_w <= VIOLATION:
                violations.append({"syllable": s.index, "text": s.text, "needs": "long" if w == "L" else "short",
                                   "scanner": s.label, "p_long": round(s.p_long, 3), "rule": s.rule,
                                   "reason": (s.reasons[-1]["text"] if s.reasons else "")})
        e = getattr(s, "elision", 0.0) or 0.0
        if e >= hiatus_min and b == a:
            violations.append({"syllable": s.index, "text": s.text, "needs": "elision", "scanner": s.label,
                               "p_long": round(s.p_long, 3), "rule": "HIATUS", "kind": "hiatus",
                               "reason": "hiatus: a final vowel (or vowel + m) before a vowel normally elides"})
    ll = math.log(total)
    fit = Fit(metre, template, not violations, ll, ll / max(len(sylls), 1), "".join(pattern), assignment,
              posterior, violations, "fits" if not violations else f"{len(violations)} position(s) against the scanner")
    if any(post_elided):
        fit.elided = [round(x / total, 3) for x in post_elided]
    return fit


def _length_range(template: str) -> tuple[int, int]:
    lo = len(template)
    hi = lo + sum(1 for c in template if c in "DRX")
    return lo, hi


def fit(lines: list[list[SyllableResult]], metre: str) -> list[Fit]:
    """Fit each line to the metre; stanza metres cycle through their line templates."""
    temps = TEMPLATES[metre]
    return [fit_line(sylls, metre, temps[k % len(temps)]) for k, sylls in enumerate(lines)]


def auto(lines: list[list[SyllableResult]], top: int = 5, language: str = "grc") -> list[dict]:
    """Rank the stichic templates by mean log-likelihood per syllable over the lines that fit."""
    ranking = []
    for name in AUTO_BY_LANGUAGE.get(language, AUTO):
        fits = [fit_line(s, name) for s in lines if s]
        good = [f for f in fits if f.log_likelihood > float("-inf")]
        if not good:
            continue
        mean = sum(f.per_syllable for f in good) / len(good)
        ranking.append({"metre": name, "lines_fitting": sum(f.ok for f in fits), "lines_parsed": len(good),
                        "lines": len(fits), "mean_log_likelihood_per_syllable": round(mean, 4)})
    ranking.sort(key=lambda r: (-r["lines_fitting"], -r["lines_parsed"], -r["mean_log_likelihood_per_syllable"]))
    return ranking[:top]


def segment(sylls: list[SyllableResult], metre: str) -> list[tuple[int, int, Fit]]:
    """Divide running text (no line breaks) into verses of a stichic or stanzaic metre.

    Viterbi over syllable positions × place in the stanza; a verse may end inside a word only at a
    cost (PRIOR['split_word']). Returns [(first syllable, end, fit)]."""
    temps = TEMPLATES[metre]
    n = len(sylls)
    best: dict[tuple[int, int], tuple[float, tuple | None]] = {(0, 0): (0.0, None)}
    cache: dict[tuple[int, int, int], Fit] = {}
    for i in range(n):
        for t in range(len(temps)):
            if (i, t) not in best:
                continue
            score, _ = best[(i, t)]
            lo, hi = _length_range(temps[t])
            for j in range(i + max(lo - 2, 1), min(i + hi + 2, n) + 1):
                key = (i, j, t)
                if key not in cache:
                    cache[key] = fit_line(sylls[i:j], metre, temps[t])
                f = cache[key]
                if f.log_likelihood == float("-inf"):
                    continue
                penalty = 0.0 if j == n or sylls[j].word != sylls[j - 1].word else math.log(PRIOR["split_word"])
                cand = score + f.log_likelihood + penalty
                nk = (j, (t + 1) % len(temps))
                if nk not in best or cand > best[nk][0]:
                    best[nk] = (cand, (i, t, f))
    ends = [(v[0], k) for k, v in best.items() if k[0] == n]
    if not ends:
        return []
    _, k = max(ends)
    out = []
    while best[k][1] is not None:
        i, t, f = best[k][1]
        out.append((i, k[0], f))
        k = (i, t)
    return out[::-1]


def responsion(strophe: list[list[SyllableResult]], antistrophe: list[list[SyllableResult]],
               anceps_prior: float = 0.1) -> list[dict]:
    """Align corresponding lines of strophe and antistrophe and resolve each other's ambiguities.

    Corresponding syllables share a weight unless the position is anceps (prior anceps_prior) or
    the line end; one long may answer two shorts (resolution, PRIOR['resolution']). Returns per line
    the alignment, posterior longness for both sides, and mismatches."""
    out = []
    for k, (a, b) in enumerate(zip(strophe, antistrophe)):
        out.append(_align_pair(a, b, anceps_prior, k))
    if len(strophe) != len(antistrophe):
        out.append({"line": None, "message": f"strophe has {len(strophe)} lines, antistrophe {len(antistrophe)}"})
    return out


def _align_pair(a: list[SyllableResult], b: list[SyllableResult], anc: float, line: int) -> dict:
    na, nb = len(a), len(b)
    NEG = float("-inf")
    score = [[NEG] * (nb + 1) for _ in range(na + 1)]
    back: list[list[tuple | None]] = [[None] * (nb + 1) for _ in range(na + 1)]
    score[0][0] = 0.0
    gap = math.log(1e-4)

    def pair_p(pa, pb, final=False):
        pa, pb = _clamp(pa), _clamp(pb)
        same = pa * pb + (1 - pa) * (1 - pb)
        return 1.0 if final else (1 - anc) * same + anc

    for i in range(na + 1):
        for j in range(nb + 1):
            if score[i][j] == NEG:
                continue
            s0 = score[i][j]
            moves = []
            if i < na and j < nb:
                fin = i == na - 1 and j == nb - 1
                moves.append((i + 1, j + 1, math.log(pair_p(a[i].p_long, b[j].p_long, fin)), "match"))
            if i < na and j + 1 < nb:
                p = _clamp(a[i].p_long) * (1 - _clamp(b[j].p_long)) * (1 - _clamp(b[j + 1].p_long)) * PRIOR["resolution"]
                moves.append((i + 1, j + 2, math.log(p), "resolve_b"))
            if i + 1 < na and j < nb:
                p = _clamp(b[j].p_long) * (1 - _clamp(a[i].p_long)) * (1 - _clamp(a[i + 1].p_long)) * PRIOR["resolution"]
                moves.append((i + 2, j + 1, math.log(p), "resolve_a"))
            if i < na:
                moves.append((i + 1, j, gap, "gap_a"))
            if j < nb:
                moves.append((i, j + 1, gap, "gap_b"))
            for ni, nj, c, kind in moves:
                if s0 + c > score[ni][nj]:
                    score[ni][nj] = s0 + c
                    back[ni][nj] = (i, j, kind)
    steps = []
    i, j = na, nb
    while back[i][j] is not None:
        pi, pj, kind = back[i][j]
        steps.append((pi, pj, kind))
        i, j = pi, pj
    steps.reverse()
    post_a = [s.p_long for s in a]
    post_b = [s.p_long for s in b]
    pairs, mismatches = [], []
    for i, j, kind in steps:
        if kind == "match":
            pa, pb = _clamp(a[i].p_long), _clamp(b[j].p_long)
            final = i == na - 1 and j == nb - 1
            if not final:
                both_l = (1 - anc) * pa * pb + anc * pa * pb
                both_s = (1 - anc) * (1 - pa) * (1 - pb) + anc * (1 - pa) * (1 - pb)
                mixed_a = anc * pa * (1 - pb)
                mixed_b = anc * (1 - pa) * pb
                z = both_l + both_s + mixed_a + mixed_b
                post_a[i] = (both_l + mixed_a) / z
                post_b[j] = (both_l + mixed_b) / z
                if (pa >= 1 - VIOLATION and pb <= VIOLATION) or (pa <= VIOLATION and pb >= 1 - VIOLATION):
                    mismatches.append({"kind": "weights_differ", "strophe": a[i].index, "antistrophe": b[j].index,
                                       "strophe_text": a[i].text, "antistrophe_text": b[j].text,
                                       "note": "answering syllables differ in length (anceps position, or a fault)"})
            pairs.append({"strophe": [a[i].index], "antistrophe": [b[j].index]})
        elif kind == "resolve_b":
            post_a[i], post_b[j], post_b[j + 1] = 1.0, 0.0, 0.0
            pairs.append({"strophe": [a[i].index], "antistrophe": [b[j].index, b[j + 1].index], "resolution": True})
        elif kind == "resolve_a":
            post_b[j], post_a[i], post_a[i + 1] = 1.0, 0.0, 0.0
            pairs.append({"strophe": [a[i].index, a[i + 1].index], "antistrophe": [b[j].index], "resolution": True})
        elif kind == "gap_a":
            mismatches.append({"kind": "unanswered", "strophe": a[i].index, "strophe_text": a[i].text})
        else:
            mismatches.append({"kind": "unanswered", "antistrophe": b[j].index, "antistrophe_text": b[j].text})
    return {"line": line, "pairs": pairs, "strophe_posterior": [round(p, 3) for p in post_a],
            "antistrophe_posterior": [round(p, 3) for p in post_b], "mismatches": mismatches,
            "strophe_pattern": "".join("–" if p >= 0.5 else "⏑" for p in post_a),
            "antistrophe_pattern": "".join("–" if p >= 0.5 else "⏑" for p in post_b)}
