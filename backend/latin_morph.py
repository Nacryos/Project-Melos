"""Morphological readings of a Latin form, from data/morph_la.sqlite (scripts/build_morph_la.py; docs/latin/grammar-check.md).

analyses(form) unites every reading the sources give: LASLA's hand tags for the forms Catullus and Horace print
(source 'lasla'), the Morpheus readings of Winge's table (source 'morpheus': the forms of a large corpus, about half
of a regular paradigm), and Collatinus (source 'collatinus': lemmata + paradigm models, so every inflected form of
82 k lemmata is read; the pure-Python port pycollatinus, GPL, loaded on first use and skipped when not installed).
A form with no reading of its own that ends in -que, -ne, -ve or -cum is read as host + enclitic (key 'enclitic');
with MELOS_LATINCY_URL set, the LatinCy sidecar reads what is still unread (source 'latincy').
Values: pos NOUN PROPN ADJ DET PRON NUM VERB ADV ADP CONJ PART INTJ; case nom gen dat acc abl voc loc; number sg pl;
gender m f n; person 1 2 3; tense pres impf fut perf plup futp; mood ind subj imp inf part gerund gerundive supine;
voice act pass; degree comp sup; '' where a category does not apply.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from .latin_text import normalize_la

_local = threading.local()
KEYS = ("lemma", "pos", "case", "number", "gender", "person", "tense", "mood", "voice", "degree", "source")
ENCLITICS = ("que", "ne", "ue", "cum")
_UD_POS = {"AUX": "VERB", "CCONJ": "CONJ", "SCONJ": "CONJ"}
_UD = {"Case": ("case", {"Nom": "nom", "Gen": "gen", "Dat": "dat", "Acc": "acc", "Abl": "abl", "Voc": "voc", "Loc": "loc"}),
       "Number": ("number", {"Sing": "sg", "Plur": "pl"}), "Gender": ("gender", {"Masc": "m", "Fem": "f", "Neut": "n"}),
       "Person": ("person", {"1": "1", "2": "2", "3": "3"}), "Mood": ("mood", {"Ind": "ind", "Sub": "subj", "Imp": "imp"}),
       "VerbForm": ("mood", {"Part": "part", "Inf": "inf", "Ger": "gerund", "Gdv": "gerundive", "Sup": "supine"}),
       "Voice": ("voice", {"Act": "act", "Pass": "pass"}), "Degree": ("degree", {"Cmp": "comp", "Abs": "sup", "Sup": "sup"}),
       "Tense": ("tense", {"Pres": "pres", "Past": "perf", "Imp": "impf", "Fut": "fut", "Pqp": "plup"})}


def morph_path() -> Path:
    if os.environ.get("MELOS_MORPH_LA"):
        return Path(os.environ["MELOS_MORPH_LA"])
    data = Path(os.environ.get("MELOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    return data / "morph_la.sqlite"


def available() -> bool:
    return morph_path().exists()


def _db() -> sqlite3.Connection:
    db = getattr(_local, "db", None)
    if db is None or getattr(_local, "path", None) != str(morph_path()):
        db = sqlite3.connect(f"file:{morph_path().as_posix()}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        _local.db, _local.path = db, str(morph_path())
    return db


@lru_cache(maxsize=65536)
def _rows(key: str) -> tuple[tuple, ...]:
    if not key or not available():
        return ()
    return tuple(_db().execute("SELECT lemma, pos, cas, number, gender, person, tense, mood, voice, degree, source, enclitic "
                               "FROM m WHERE key=?", (key,)))


_FR = {"nominatif": ("case", "nom"), "vocatif": ("case", "voc"), "accusatif": ("case", "acc"), "génitif": ("case", "gen"),
       "datif": ("case", "dat"), "ablatif": ("case", "abl"), "locatif": ("case", "loc"), "singulier": ("number", "sg"),
       "pluriel": ("number", "pl"), "masculin": ("gender", "m"), "féminin": ("gender", "f"), "neutre": ("gender", "n"),
       "1ère": ("person", "1"), "2ème": ("person", "2"), "3ème": ("person", "3"), "indicatif": ("mood", "ind"),
       "subjonctif": ("mood", "subj"), "impératif": ("mood", "imp"), "infinitif": ("mood", "inf"),
       "participe": ("mood", "part"), "gérondif": ("mood", "gerund"), "supin": ("mood", "supine"),
       "présent": ("tense", "pres"), "imparfait": ("tense", "impf"), "futur": ("tense", "fut"),
       "parfait": ("tense", "perf"), "PQP": ("tense", "plup"), "actif": ("voice", "act"), "passif": ("voice", "pass"),
       "comparatif": ("degree", "comp"), "superlatif": ("degree", "sup")}
_C_POS = {"n": "NOUN", "a": "ADJ", "v": "VERB", "d": "ADV", "c": "CONJ", "r": "ADP", "p": "PRON", "i": "INTJ",
          "e": "INTJ", "m": "NUM"}
_collatinus_lock = threading.Lock()
_collatinus_state: dict = {}


def _collatinus_engine():
    """The pycollatinus analyser and a lemma -> gender map from Collatinus's lemmata; None when not installed."""
    with _collatinus_lock:
        if "engine" not in _collatinus_state:
            engine, genders = None, {}
            try:
                import collections
                import collections.abc
                import warnings
                if not hasattr(collections, "Callable"):          # pycollatinus 0.1.6 predates Python 3.10
                    collections.Callable = collections.abc.Callable
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    import pycollatinus
                    engine = pycollatinus.Lemmatiseur()
                data = Path(pycollatinus.__file__).parent / "data"
                for name in ("lem_ext.la", "lemmes.la"):
                    for line in (data / name).read_text(encoding="utf-8").splitlines():
                        parts = line.split("|")
                        if len(parts) > 4 and not line.startswith("!"):
                            g = next((x for x in ("m", "f", "n") if f", {x}." in parts[4] or parts[4].startswith(f"{x}.")), "")
                            if g:
                                genders[normalize_la(parts[0].split("=")[0]).rstrip("0123456789")] = g
            except Exception:  # noqa: BLE001 - the generator is optional
                engine = None
            _collatinus_state.update(engine=engine, genders=genders)
        return _collatinus_state["engine"], _collatinus_state["genders"]


@lru_cache(maxsize=65536)
def _collatinus(key: str) -> tuple[tuple, ...]:
    engine, genders = _collatinus_engine()
    if engine is None:
        return ()
    out = []
    try:
        with _collatinus_lock:
            found = list(engine.lemmatise(key, pos=True, get_lemma_object=False))
    except Exception:  # noqa: BLE001
        return ()
    for r in found:
        d = dict.fromkeys(KEYS, "")
        d["lemma"] = normalize_la(r.get("lemma", "")).rstrip("0123456789")
        morph = str(r.get("morph", ""))
        for w in morph.split():
            if w in _FR:
                d[_FR[w][0]] = _FR[w][1]
        if "futur antérieur" in morph:
            d["tense"] = "futp"
        if "adjectif verbal" in morph:
            d["mood"] = "gerundive"
        own = normalize_la(str(r.get("radical", "")) + str(r.get("desinence", "")))
        encl = next((e for e in ENCLITICS[:3] if key.endswith(e) and own == key[: -len(e)]), "")
        for letter in str(r.get("pos", "")) or " ":
            pos = _C_POS.get(letter, "")
            if not pos:
                continue
            gender = d["gender"] or (genders.get(d["lemma"], "") if pos == "NOUN" and d["case"] else "")
            out.append((d["lemma"], pos, d["case"], d["number"], gender, d["person"], d["tense"], d["mood"], d["voice"],
                        d["degree"], "collatinus", encl))
    return tuple(out)


def _all(key: str) -> tuple[tuple, ...]:
    return _rows(key) + _collatinus(key)


def _dicts(rows, enclitic: str | None = None) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        d = dict(zip(KEYS, r[:11]))
        if enclitic or r[11]:
            d["enclitic"] = enclitic or r[11]
        k = tuple(d.items())
        if k not in seen:
            seen.add(k)
            out.append(d)
    return out


def analyses(form: str) -> list[dict]:
    """Every reading of a form: [{lemma, pos, case, number, gender, person, tense, mood, voice, degree, source}], with
    'enclitic' added when the reading is of the host of -que / -ne / -ve / -cum. [] when no source reads the form."""
    key = normalize_la(form)
    if not key.isalpha():
        return []
    out = _dicts(_all(key))
    if not out:
        for e in ENCLITICS:
            if key.endswith(e) and len(key) > len(e) + 1:
                host = [r for r in _all(key[: -len(e)]) if not r[11]]
                if e == "cum":                                   # mecum, quibuscum: an ablative pronoun only
                    host = [r for r in host if r[1] == "PRON" and r[2] == "abl"]
                out += _dicts(host, e)
    if not out:
        out = _latincy(form)
    return out


def lexical(form: str) -> bool:
    """True when the form has a reading of its own, without splitting an enclitic off (atque, neque, quoque, bene)."""
    return any(not r[11] for r in _all(normalize_la(form)))


def enclitic_of(form: str) -> tuple[str, str] | None:
    """(host, enclitic) when the form can be read as host + -que / -ne / -ve and the host has a reading; else None."""
    key = normalize_la(form)
    for e in ENCLITICS[:3]:
        if key.endswith(e) and len(key) > len(e) + 1 and any(not r[11] for r in _all(key[: -len(e)])):
            return key[: -len(e)], e
    return None


def _latincy(form: str) -> list[dict]:
    from . import latin_lemma
    out = []
    for t in latin_lemma.latincy_readings(form):
        d = dict.fromkeys(KEYS, "")
        d.update(lemma=normalize_la(t.get("lemma", "")), pos=_UD_POS.get(t.get("upos", ""), t.get("upos", "")), source="latincy")
        for part in str(t.get("morph", "")).split("|"):
            name, _, value = part.partition("=")
            if name in _UD and value in _UD[name][1]:
                d[_UD[name][0]] = _UD[name][1][value]
        out.append(d)
    return out


@lru_cache(maxsize=4)
def word_order_counts() -> dict:
    """Counts made by the build from the punctuated corpus text: postpositive candidates (total, sentence-first, in
    Catullus and Horace), prepositions in Catullus (total, sentence-last), enclitic hosts by final letter."""
    if not available():
        return {}
    row = _db().execute("SELECT v FROM meta WHERE k='word_order'").fetchone()
    return json.loads(row[0]) if row else {}
