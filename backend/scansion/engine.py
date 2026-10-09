"""Interpreter for the scansion meta-grammar (backend/scansion/rules.yaml).

The rules file holds two decision trees (`vowel`, `unit`) and a list of `flags`. Conditions and
formulas are written in a small expression language: feature and parameter names, string and
number literals, == != < <= > >= in / not in, and / or / not, parentheses, + - *. They are parsed
with Python's `ast` module and only those node types are accepted, so a rules file cannot run code.
"""
from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parent / "rules.yaml"

# Every feature a condition may use, with its meaning (rendered in docs and on rules.html).
FEATURES: dict[str, str] = {
    "nucleus": 'kind of nucleus: "diphthong", "long" (η ω), "short" (ε ο), "dichronon" (α ι υ)',
    "vowel": "base letter of a single-vowel nucleus (empty for a diphthong)",
    "adscript": "ι written beside η, ω or circumflexed α (counts as iota subscript)",
    "iota_sub": "the vowel has iota subscript",
    "circumflex": "the nucleus carries the circumflex",
    "crasis": "coronis on a vowel inside the word (crasis)",
    "consonants": "consonants in the interval after the nucleus (ζ ξ ψ count two)",
    "double": "the interval contains ζ, ξ or ψ",
    "mcl": "the interval is exactly a stop followed by a liquid or nasal, not split by a word boundary",
    "stop": 'class of that stop: "voiceless", "aspirate", "voiced" (empty otherwise)',
    "liquid": 'class of that liquid: "liquid" (λ ρ), "nasal" (μ ν) (empty otherwise)',
    "boundary_inside_interval": "a word boundary falls between the interval's consonants",
    "interval_opens_next_word": "all the interval's consonants belong to the next word",
    "final_consonant_before_vowel": "one consonant ends this word and the next word begins with a vowel",
    "hiatus": '"external" (vowel before the next word\'s vowel), "internal" (vowel before vowel in the word), "none"',
    "next_initial": "first letter of the next word on the line (empty at line end)",
    "next_digamma": "the next word once began with ϝ (Monro §§390-395 list)",
    "word_final": "the nucleus is the last one of its word",
    "word_initial": "the nucleus is the first one of its word",
    "line_final": "the last unit of the line",
    "elided": "the word ends in an elision mark",
    "is_ultima": "the nucleus is the word's last vowel",
    "is_penult": "the nucleus is the word's second-last vowel",
    "accent": 'where the word\'s (first) accent stands: "antepenult_acute", "penult_acute", "penult_circumflex", '
              '"ultima_acute", "ultima_circumflex", "none" (elided words: "none")',
    "penult_long_by_nature": "the word's penult is η, ω, a diphthong, or has iota subscript or circumflex",
    "ultima_short_by_nature": "the word's ultima is a bare ε or ο",
    "ultima_ai_oi": "the word ends in -αι or -οι (count short for the accent)",
    "enclitic_compound": "the word ends in an enclitic written with it (οὔτι, ὥστε, ὅδε): its accent is the first word's (Smyth §186)",
    "lex": 'lexical evidence for this α ι υ: "L", "S", "conflict", "ending", "unmarked", "none" (no lexicon)',
    "lex_sources": 'which sources marked it: "both" (dictionary and Morpheus), "dict", "morph", ""',
    "p_vowel": "probability the nucleus is long (set by the vowel tree)",
}

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


class RuleError(ValueError):
    pass


class Expr:
    """A compiled condition or formula."""

    def __init__(self, source, known: set[str]):
        self.source = str(source).strip() if not isinstance(source, bool) else ("true" if source else "false")
        text = {"true": "True", "false": "False"}.get(self.source, self.source)
        text = text.replace(" true", " True").replace(" false", " False")
        try:
            self.tree = ast.parse(text, mode="eval").body
        except SyntaxError as exc:
            raise RuleError(f"cannot read `{self.source}`: {exc.msg}") from None
        self.names: set[str] = set()
        self._check(self.tree, known)

    def _check(self, node, known):
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                self._check(v, known)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub)):
            self._check(node.operand, known)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            self._check(node.left, known)
            self._check(node.right, known)
        elif isinstance(node, ast.Compare) and all(type(op) in _CMP for op in node.ops):
            self._check(node.left, known)
            for c in node.comparators:
                self._check(c, known)
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for e in node.elts:
                self._check(e, known)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
            pass
        elif isinstance(node, ast.Name):
            if node.id not in known:
                raise RuleError(f"unknown name `{node.id}` in `{self.source}`")
            self.names.add(node.id)
        else:
            raise RuleError(f"not allowed in `{self.source}`: {type(node).__name__}")

    def __call__(self, env: dict):
        return _eval(self.tree, env)


def _eval(node, env):
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, env) for v in node.values)
        return any(_eval(v, env) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        return (not v) if isinstance(node.op, ast.Not) else -v
    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return tuple(_eval(e, env) for e in node.elts)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    raise RuleError(type(node).__name__)


@dataclass
class Node:
    id: str
    when: Expr
    reason: str
    cite: str
    p: Expr | None = None
    children: list["Node"] = field(default_factory=list)
    path: str = ""

    def as_dict(self) -> dict:
        d = {"id": self.id, "when": self.when.source, "reason": self.reason, "cite": self.cite}
        if self.p is not None:
            d["p"] = self.p.source
        if self.children:
            d["then"] = [c.as_dict() for c in self.children]
        return d


@dataclass
class Grammar:
    params: dict[str, float]
    vowel: list[Node]
    unit: list[Node]
    flags: list[Node]
    source: str

    def all_nodes(self):
        def walk(nodes):
            for n in nodes:
                yield n
                yield from walk(n.children)
        yield from walk(self.vowel)
        yield from walk(self.unit)
        yield from walk(self.flags)

    def decide(self, tree: list[Node], env: dict) -> tuple[float, list[Node]]:
        """First matching node at each level; returns (probability, path of matched nodes)."""
        path: list[Node] = []
        nodes = tree
        while True:
            for n in nodes:
                if n.when(env):
                    path.append(n)
                    if n.children:
                        nodes = n.children
                        break
                    value = float(n.p(env))
                    return min(max(value, 0.0), 1.0), path
            else:
                raise RuleError(f"no rule matched under {path[-1].id if path else 'the top level'}")

    def as_dict(self) -> dict:
        return {"params": self.params, "vowel": [n.as_dict() for n in self.vowel],
                "unit": [n.as_dict() for n in self.unit], "flags": [n.as_dict() for n in self.flags],
                "features": FEATURES}


def load(path: Path | str | None = None, text: str | None = None,
         param_overrides: dict | None = None) -> tuple[Grammar | None, list[str]]:
    """Parse and validate a rules file. Returns (grammar or None, list of error messages)."""
    import yaml
    path = Path(path or DEFAULT_RULES)
    errors: list[str] = []
    try:
        doc = yaml.safe_load(text if text is not None else path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"YAML: {exc}"]
    if not isinstance(doc, dict):
        return None, ["the file must be a mapping with params, vowel, unit, flags"]
    params = dict(doc.get("params") or {})
    for k, v in params.items():
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            errors.append(f"params.{k}: must be a number from 0 to 1 (got {v!r})")
    params.update(param_overrides or {})
    known_vowel = set(FEATURES) - {"p_vowel"} | set(params)
    known_unit = set(FEATURES) | set(params)
    seen: set[str] = set()

    def build(items, where, known, need_p=True):
        out = []
        if not isinstance(items, list) or not items:
            errors.append(f"{where}: must be a non-empty list of rules")
            return out
        for k, raw in enumerate(items):
            loc = f"{where}[{k}]"
            if not isinstance(raw, dict):
                errors.append(f"{loc}: must be a mapping")
                continue
            rid = str(raw.get("id") or "")
            loc = f"{where} › {rid or k}"
            if not rid:
                errors.append(f"{loc}: missing id")
            elif rid in seen:
                errors.append(f"{loc}: duplicate id {rid}")
            seen.add(rid)
            for req in ("when", "reason", "cite"):
                if raw.get(req) in (None, ""):
                    errors.append(f"{loc}: missing `{req}`")
            try:
                when = Expr(raw.get("when", True), known)
            except RuleError as exc:
                errors.append(f"{loc}: when: {exc}")
                when = Expr(True, known)
            node = Node(rid, when, str(raw.get("reason", "")), str(raw.get("cite", "")), path=loc)
            if "then" in raw:
                node.children = build(raw["then"], loc, known, need_p)
                if "p" in raw:
                    errors.append(f"{loc}: a rule has either `p` or `then`, not both")
            elif "p" in raw:
                try:
                    node.p = Expr(raw["p"], known)
                    if isinstance(node.p.tree, ast.Constant) and not 0 <= float(node.p.tree.value) <= 1:
                        errors.append(f"{loc}: p must be between 0 and 1")
                except (RuleError, ValueError) as exc:
                    errors.append(f"{loc}: p: {exc}")
            elif need_p:
                errors.append(f"{loc}: needs `p` (a probability) or `then` (sub-rules)")
            out.append(node)
        if need_p and items and isinstance(items, list):
            last = items[-1] if isinstance(items[-1], dict) else {}
            if str(last.get("when", "")).strip().lower() != "true" and where not in ("vowel", "unit"):
                errors.append(f"{where}: the last sub-rule should have `when: true` so every case is covered")
        return out

    vowel = build(doc.get("vowel"), "vowel", known_vowel)
    unit = build(doc.get("unit"), "unit", known_unit)
    flags = build(doc.get("flags") or [], "flags", known_unit, need_p=False) if doc.get("flags") else []
    if errors:
        return None, errors
    return Grammar(params, vowel, unit, flags, str(path)), []
