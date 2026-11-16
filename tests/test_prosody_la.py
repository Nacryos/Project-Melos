"""L12 prosody attestation (backend/latin_prosody.py; scripts/build_prosody_index_la.py; docs/latin/prosody-attestation.md).

The helper and synthetic-index tests need no data beyond the scanner's rules; the tests marked `real` run on the built
index (data/scansion/prosody_la.sqlite) and are skipped without it."""
import gzip
import importlib.util
import json
from pathlib import Path

import pytest

from backend import latin_prosody as lp

ROOT = Path(__file__).resolve().parents[1]
real = pytest.mark.skipif(not lp.available(), reason="prosody index not built (scripts/build_prosody_index_la.py)")


def _builder():
    spec = importlib.util.spec_from_file_location("build_prosody_index_la", ROOT / "scripts" / "build_prosody_index_la.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _line(id_, number, n, words):
    """A gold row as the ingesters write it; words = [(form, [(syllable, q), ...])]."""
    ws = [{"form": f, "pat": "".join({"L": "-", "S": "u", "E": "e"}[q] for _, q in syl),
           "syl": [{"t": t, "q": q, "f": []} for t, q in syl], "classes": []} for f, syl in words]
    return {"id": id_, "work_file": "catullus", "author": "Catullus", "work": "Poems", "book": "", "poem_number": number,
            "line_no": n, "metre": "hendecasyllables", "line_classes": [], "text": " ".join(f for f, _ in words), "words": ws}


GOLD = [
    _line("t:1:1", "1", 1, [("Cui", [("Cui", "L")]), ("dōnō", [("dō", "L"), ("nō", "L")]),
                            ("lepidum", [("le", "S"), ("pi", "S"), ("dum", "L")]), ("novum", [("no", "S"), ("vum", "L")]),
                            ("libellum", [("li", "S"), ("bel", "L"), ("lum", "L")])]),
    _line("t:1:2", "1", 2, [("āridā", [("ā", "L"), ("ri", "S"), ("dā", "L")]), ("modo", [("mo", "S"), ("do", "S")]),
                            ("pūmice", [("pū", "L"), ("mi", "S"), ("ce", "E")]),
                            ("expolītum?", [("ex", "L"), ("po", "S"), ("lī", "L"), ("tum?", "L")])]),
    _line("t:9:1", "9", 1, [("dōnum", [("dō", "L"), ("num", "L")]), ("patris", [("pa", "S"), ("tris", "L")]),
                            ("habet", [("ha", "S"), ("bet", "S")]), ("Obvius", [("Ob", "L"), ("vi", "S"), ("us", "S")]),
                            ("huic", [("huic", "L")])]),
]


@pytest.fixture()
def tiny(tmp_path, monkeypatch):
    src = tmp_path / "lines.jsonl.gz"
    with gzip.open(src, "wt", encoding="utf-8") as f:
        for row in GOLD:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    out = tmp_path / "prosody_la.sqlite"
    counts = _builder().build([str(src)], str(out), lemmas=False)
    monkeypatch.setenv("MELOS_PROSODY_LA", str(out))
    return counts


def test_letters_and_contexts():
    assert lp.fold("Vēnimus,") == "uenimus" and lp.fold("jocōsē") == "iocose"
    assert lp.initial_class("amor") == "V" and lp.initial_class("huic") == "V"       # h never makes position
    assert lp.initial_class("novum") == "C" and lp.initial_class("quod") == "C" and lp.initial_class("iam") == "C"
    assert lp.initial_class("tremula") == "ML" and lp.initial_class("flōs") == "ML"
    assert lp.initial_class("spēs") == "CC" and lp.initial_class("Zephyrus") == "CC"
    assert lp.mcl_after(["pa", "tris"]) == [0] and lp.mcl_after(["la", "cri", "mās"]) == [0]
    assert lp.mcl_after(["li", "bel", "lum"]) == [] and lp.mcl_after(["cas", "tra"]) == []
    # a closed final is long before any consonant; an open final tells its nature only before one consonant or mute + liquid
    assert lp.context_group(False, "CC") == "C" and lp.context_group(True, "ML") == "C" and lp.context_group(True, "CC") == "CC"
    assert lp.context_group(True, "END") == "END" and lp.context_group(False, "V") == "V"


def test_missing_index_is_unavailable_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MELOS_PROSODY_LA", str(tmp_path / "absent.sqlite"))
    r = lp.check("Cui dono lepidum novum libellum")
    assert r["id"] == "L12" and r["name"] == "prosody attestation" and r["blocking"] is True
    assert r["ok"] is True and r["detail"].startswith("unavailable:") and r["evidence"] == []
    assert lp.attested("libellum")["patterns"] == []


def test_index_rows_carry_the_context(tiny):
    assert tiny["tokens"] == 14 and tiny["lines"] == 3
    a = lp.attested("libellum")
    assert a["tokens"] == 1 and a["patterns"][0]["pattern"] == "SLL" and a["patterns"][0]["final_contexts"] == {"END": 1}
    assert a["patterns"][0]["loci"][0] == {"locus": "Catullus 1.1", "text": "Cui dōnō lepidum novum libellum",
                                           "form": "libellum", "pattern": "SLL"}
    assert lp.attested("pumice")["patterns"][0]["final_contexts"] == {"E": 1}       # elided before expolitum
    assert lp.attested("obuius")["patterns"][0]["final_contexts"] == {"V": 1}       # before huic
    assert lp._tokens("patris")[0]["mcl"] == [0]
    assert lp.attested("patris", author="Vergil")["tokens"] == 0


def test_check_confirms_conflicts_and_warns(tiny):
    good = lp.check("Cui dono lepidum novum libellum")
    assert good["ok"] is True and good["counts"] == {"confirmed": 5}
    assert [e["weights"] for e in good["evidence"]] == ["l", "lL", "SSL", "SL", "SLs"]   # l / s: anceps, shown not compared
    assert good["evidence"][2]["loci"][0]["locus"] == "Catullus 1.1"
    # dōnum is long in the gold; here the metre needs its first syllable short: the blocking case
    bad = lp.check("Cui dono lepidum donum libellum")
    assert bad["ok"] is False and bad["blocking"] is True and bad["counts"]["conflict"] == 1
    e = next(e for e in bad["evidence"] if e["verdict"] == "conflict")
    assert e["word"] == "donum" and e["syllables"][0] == e["syllables"][0] | {"syllable": 1, "weight": "S", "status": "conflict"}
    assert "donum" in bad["detail"] and "conflict" in bad["detail"]
    # with its own line left out the form is not in the gold: a warning, not a block
    alone = lp.check("Cui dono lepidum novum libellum", _exclude=frozenset(["t:1:1"]))
    assert alone["ok"] is True and alone["counts"].get("confirmed", 0) == 0
    assert {e["verdict"] for e in alone["evidence"]} <= {"unattested", "stem"}


def test_check_never_raises(tiny):
    for text in ["", "\n\n", "123 !!!", "μῆνιν ἄειδε θεά", "a", "Cui dono lepidum novum libellum\n\nnon est", "x" * 500]:
        r = lp.check(text)
        assert r["id"] == "L12" and r["ok"] in (True, False) and isinstance(r["detail"], str)
    assert lp.check("Cui dono", metre_name="no_such_metre")["ok"] is True
    assert lp.attested("")["patterns"] == [] and lp.attested("???")["patterns"] == []


@real
def test_real_index_confirms_catullus_and_catches_a_broken_quantity():
    good = lp.check("Cui dono lepidum novum libellum\narida modo pumice expolitum?")
    assert good["ok"] is True and not good["counts"].get("conflict")
    assert good["evidence"][2]["verdict"] == "confirmed" and good["evidence"][2]["loci"][0]["locus"].startswith("Catullus")
    bad = lp.check("Cui dono lepidum donum libellum")
    assert bad["ok"] is False
    e = next(e for e in bad["evidence"] if e["verdict"] == "conflict")
    assert e["word"] == "donum" and e["syllables"][0]["other"].get("Vergil", 0) >= 5


@real
def test_real_index_shows_variants_with_counts_per_poet():
    a = lp.attested("patris")
    pats = {p["pattern"]: p for p in a["patterns"]}
    assert "SL" in pats and pats["SL"]["per_poet"].get("Vergil", 0) >= 5 and len(pats["SL"]["loci"]) <= 3
    mihi = {p["pattern"] for p in lp.attested("mihi", author="Catullus")["patterns"]}
    assert {"SS", "SL"} <= mihi                                                      # iambic shortening: both in Catullus
    r = lp.check("passer, deliciae malae puellae,")
    e = next(e for e in r["evidence"] if e["key"] == "malae")
    assert r["ok"] is True and e["verdict"] == "variant" and e["syllables"][0]["other"]   # mălae / mālae: shown, not blocked


@real
def test_real_index_blocks_a_wrong_matris_and_only_warns_on_a_true_homograph():
    """mătris is no word (the lexicon's Matrae is a proper noun, not a second reading); lĕvis / lēvis are two words."""
    wrong = lp.check("Cui dono lepidum matris libellum")
    row = next(e for e in wrong["evidence"] if e["key"] == "matris")
    assert wrong["ok"] is False and row["verdict"] == "conflict" and row["weights"][0] == "S"
    assert lp._readings("matris", 1) == {}
    hom = lp.check("Cui dono lepidum levis libellum")
    row = next(e for e in hom["evidence"] if e["key"] == "leuis")
    syl = row["syllables"][0]
    assert hom["ok"] is True and row["verdict"] == "variant" and syl["cause"] == "homograph"
    assert {r["weight"] for r in syl["readings"]} == {"L", "S"} and all(r["lemmas"] and r["loci"] for r in syl["readings"])
    assert "which is meant?" in hom["detail"]


@real
def test_real_index_gives_mute_liquid_counts_for_catullus_and_virgil():
    res = lp.check("Cui dono lepidum patris libellum")
    row = next(e for e in res["evidence"] if e["key"] == "patris")
    ml = row["syllables"][0]["mute_liquid"]
    assert res["ok"] is True and set(lp.REFERENCE) <= set(ml["form"]) and ml["form"]["Vergil"]["short"] > 0
    assert "patrem" in ml["stem_forms"] and "mute + liquid: patris Catullus long" in res["detail"]


@real
def test_real_index_synizesis_is_a_variant_with_loci():
    row = lp._word("dehinc", "L", "C", False, [], "Catullus", frozenset())
    assert row["verdict"] == "variant" and row["synizesis"]["here"] == "with" and row["synizesis"]["with"]["loci"]


def test_lexicon_conflict_only_where_the_gold_is_silent(tiny, monkeypatch):
    """A stem / unattested word whose weight goes against the quantity lexicon gets lexicon-conflict; an attested one keeps its verdict."""
    hit = [{"syllable": 1, "weight": "S", "lexicon": "L", "sources": "winge"}]
    monkeypatch.setattr(lp, "_lexicon_conflicts", lambda *a, **k: hit)
    gone = lp._word("zzzum", "SL", "C", False, [], "Catullus", frozenset(), [1, 4])
    assert gone["verdict"] == "lexicon-conflict" and "winge" in lp._describe(gone)
    here = lp._word("libellum", "SLs", "END", True, [], "Catullus", frozenset(), [1, 3, 6])
    assert here["verdict"] != "lexicon-conflict" and here["lexicon_disagrees"] == hit


def test_cli_prints_patterns(tiny, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("la_prosody", Path(__file__).resolve().parents[1] / "scripts" / "la_prosody.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.show("libellum")
    assert "libellum" in out and "pattern" in out and "Catullus" in out
    assert "not in the gold" in mod.show("zzzum")
