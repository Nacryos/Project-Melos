"""Open-lexica supplement: per-source TEI reading, definition spans, dictionary
order, short head phrases, lemma -> headword glosses. Synthetic XML below is
test-only; the regression block at the end uses the real built supplement and
skips when it is not present locally."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unicodedata

import pytest

from backend import lexicon_render
from backend.interlinear import _gloss
from backend.lexicon_senses import dictionary_senses
from backend.lemma_glosses import attach_lemma_glosses
from backend.morphology import Morphology
from backend.short_gloss import DICTIONARY_ORDER, letter_or_numeral_entry, meaningful, short_head

ROOT = Path(__file__).resolve().parents[1]
ML = "Perseus Middle Liddell TEI (Hopper open-source texts)"
LOGEION = "LSJ (Logeion edition, H. Dik) TEI"
CUNLIFFE = "Perseus Cunliffe TEI via Homerica"
DODSON = "Dodson Greek Lexicon (NT; public domain)"
PERSEUS = "PerseusDL LSJ TEI"


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(lexicon_render, "RAW_ROOT", tmp_path.resolve())

    def write(name, prefix, entries, suffix):
        body = prefix.encode()
        located = []
        for fragment in entries:
            start = len(body)
            body += fragment.encode()
            located.append((start, len(body)))
            body += b"\n"
        body += suffix.encode()
        path = tmp_path / name
        path.write_bytes(body)
        return str(path), hashlib.sha256(body).hexdigest(), located
    return write


def record(source, path, digest, span, entry_id, lemma, rid):
    return {"id": rid, "entry_id": entry_id, "lemma": lemma, "source": source,
            "source_url": "https://example.invalid/" + Path(path).name, "raw_path": path,
            "raw_sha256": digest, "locator": {"byte_start": span[0], "byte_end": span[1]}, "language": "en"}


ML_ENTRIES = [
    '<entry key="e)/rxomai" type="main" id="n1"><form><orth extent="full" lang="greek">e)/rxomai</orth></form>'
    '<sense level="2" n="I" id="n1.0"><trans><tr>to come</tr> or <tr>go</tr></trans>, <usg>Hom.</usg></sense>'
    '<sense level="3" n="2" id="n1.1">c. acc. cogn., <foreign lang="greek">o(do/n</foreign> '
    '<trans><tr>to go</tr></trans> a journey, <usg>Hom.</usg></sense></entry>',
    '<entry key="a)gro/teros" type="main" id="n2"><form><orth extent="full" lang="greek">a)gro/teros</orth></form>'
    '<sense level="2" n="I" id="n2.0">poet. for <foreign lang="greek">a)/grios</foreign>, <trans><tr>wild</tr></trans>,'
    ' of animals</sense></entry>',
    '<entry key="a)kou/w" type="main" id="n3"><form><orth extent="full" lang="greek">a)kou/w</orth></form>'
    '<etym>Root <!-- ! --><foreign lang="greek">*a*k*o*v</foreign></etym><sense level="2" n="I" id="n3.0">'
    '<trans><tr>to hear</tr></trans>, <usg>Hom.</usg></sense></entry>',
    '<entry key="e)gw/" type="main" id="n4"><form><orth extent="full" lang="greek">e)gw/</orth></form>'
    '<sense level="0" n="0" id="n4.0">pron. of the first person, Lat <trans><tr>ego</tr></trans></sense></entry>',
]


def test_middle_liddell_definitions_examples_and_references(raw):
    path, digest, spans = raw("ml.xml", "<TEI.2><text><body>\n", ML_ENTRIES, "</body></text></TEI.2>")
    come = dictionary_senses(record(ML, path, digest, spans[0], "n1", "ἔρχομαι", "middle-liddell:n1"))
    assert come["dictionary_senses"][0]["text"] == "to come or go"
    wild = dictionary_senses(record(ML, path, digest, spans[1], "n2", "ἀγρότερος", "middle-liddell:n2"))
    # "poet. for ἄγριος, wild": a referenced word, not an example.
    assert [s["text"] for s in wild["dictionary_senses"]] == ["wild"]
    # An etymology preamble ("Root ...") does not disqualify the first sense;
    # a Latin equivalent ("Lat ego") is not an English definition.
    hear = dictionary_senses(record(ML, path, digest, spans[2], "n3", "ἀκούω", "middle-liddell:n3"))
    assert hear["dictionary_senses"][0]["text"] == "to hear"
    ego = dictionary_senses(record(ML, path, digest, spans[3], "n4", "ἐγώ", "middle-liddell:n4"))
    assert ego["dictionary_senses"] == []
    rendered = lexicon_render.render_source_record(record(ML, path, digest, spans[1], "n2", "ἀγρότερος", "x"))
    shown = unicodedata.normalize("NFC", rendered["rendered_entry_text"])
    assert "ἀγρότερος" in shown and "ἄγριος" in shown


def test_located_entry_identity_is_checked(raw):
    path, digest, spans = raw("ml2.xml", "<r>\n", ML_ENTRIES, "</r>")
    bad = record(ML, path, digest, spans[0], "n2", "ἔρχομαι", "middle-liddell:n2")
    assert dictionary_senses(bad)["dictionary_senses_status"] == "source_unavailable"


def test_logeion_italics_unicode_and_bare_article(raw):
    entries = [
        '<div2 id="crossmh=nis" orig_id="n1" key="mh=nis" type="main"><head lang="grc">μῆνις</head>, '
        '<gen lang="grc">ἡ</gen> (<foreign lang="grc">μᾶνις</foreign>):—<sense id="n1.0" n="" level="1">'
        '<i>wrath</i>; from <author>Hom.</author> downwds.</sense></div2>',
        '<div2 id="crossdio" orig_id="n2" key="dio" type="main"><head lang="grc">Διόνυσος</head>, ὁ, '
        '<i>a,</i> <sense id="n2.0" n="" level="1"><i>Dionysus,</i> god of wine</sense></div2>',
    ]
    path, digest, spans = raw("greatscott.xml", "<tei.2><text><div1>\n", entries, "</div1></text></tei.2>")
    wrath = dictionary_senses(record(LOGEION, path, digest, spans[0], "crossmh=nis", "μῆνις", "lsj-logeion:a"))
    assert wrath["dictionary_senses"][0]["text"] == "wrath"
    text = lexicon_render.render_source_record(record(LOGEION, path, digest, spans[0], "crossmh=nis", "μῆνις", "a"))
    assert "(μᾶνις)" in text["rendered_entry_text"]  # Unicode untouched: no Beta Code conversion
    dio = dictionary_senses(record(LOGEION, path, digest, spans[1], "crossdio", "Διόνυσος", "lsj-logeion:b"))
    assert [s["text"] for s in dio["dictionary_senses"]] == ["Dionysus"]


def test_cunliffe_and_dodson_layouts(raw):
    cun = ('<div xml:id="menis-cunliffe-lex" n="μῆνις" type="textpart"><head>μῆνις</head> ἡ. '
           '<div xml:id="menis-1" type="textpart"><head>1</head><p><gloss>Wrath, ire</gloss> : '
           '<cit><quote xml:lang="greek">μῆνιν ἄειδε</quote> <bibl n="x">Il. 1.1</bibl></cit>.</p></div>'
           '<div xml:id="menis-2" type="textpart"><head>2</head><p><gloss>Thoughtlessness.</gloss></p></div></div>')
    path, digest, spans = raw("cunliffe.xml", '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>\n', [cun],
                              "</body></text></TEI>")
    found = dictionary_senses(record(CUNLIFFE, path, digest, spans[0], "menis-cunliffe-lex", "μῆνις", "cunliffe:m"))
    assert [s["text"] for s in found["dictionary_senses"]] == ["Wrath, ire", "Thoughtlessness."]
    dod = ('<entry n="ἀβαρής | 0004"><orth>ἀβαρής, ες</orth><def role="brief">not burdensome</def>'
           '<def role="full">not burdensome, bringing no weight.</def></entry>')
    path, digest, spans = raw("dodson.xml", "<TEI>\n", [dod], "</TEI>")
    found = dictionary_senses(record(DODSON, path, digest, spans[0], "0004", "ἀβαρής", "dodson:0004"))
    assert found["dictionary_senses"][0]["text"] == "not burdensome"


def test_short_head_keeps_source_words():
    assert short_head("a piece of land cut off and assigned as an official domain")["text"] == "a piece of land"
    assert short_head("a piece of land cut off, assigned as a domain")["text"] == "a piece of land"
    assert short_head("and")["text"] == "and" and short_head("in")["text"] == "in"
    assert short_head("to come or go")["text"] == "to come or go"
    assert short_head("Wrath, ire")["text"] == "Wrath"
    long = short_head("one two three four five six")
    assert long["text"] == "one two three four …" and long["method"] == "first_words_truncated"
    assert short_head("a,") is None and not meaningful("a")


def _sense(entry, text, n):
    return {"id": f"{entry['id']}:s{n}", "lexicon_entry_id": entry["id"], "entry_id": entry["entry_id"],
            "text": text, "language": "en", "evidence_type": "dictionary_sense", "source": entry["source"],
            "source_url": "https://example.invalid/x", "source_locator": {"node_path": "/x"}, "raw_sha256": "0" * 64}


def _entry(rid, source, lemma, senses, text=""):
    entry = {"id": rid, "entry_id": rid.split(":")[-1], "lemma": lemma, "source": source,
             "source_url": "https://example.invalid/x", "rendered_entry_text": text}
    entry["dictionary_senses"] = [_sense(entry, value, i) for i, value in enumerate(senses)]
    entry["dictionary_senses_status"] = "source_structured"
    return entry


def test_gloss_prefers_middle_liddell_and_skips_letter_entry_for_particle():
    lsj = _entry("lsj:1:n9", PERSEUS, "τε", ["the eleventh or twelfth"],
                 "τε, as numeral, the eleventh letter of the Gr. alphabet")
    ml = _entry("middle-liddell:n3", ML, "τε", ["and"])
    token = {"text": "τε", "lexicon_entries": [lsj, ml]}
    particle = {"lemma": "τε", "features": {"pos": "particle"}}
    gloss = _gloss(particle, token)
    assert gloss["text"] == "and" and gloss["short_text"] == "and" and gloss["source"] == ML
    assert letter_or_numeral_entry(lsj)
    # Cunliffe ranks after LSJ, so only the letter/numeral skip makes it win.
    behind = {"text": "τε", "lexicon_entries": [lsj, _entry("cunliffe:te", CUNLIFFE, "τε", ["and"])]}
    assert _gloss(particle, behind)["text"] == "and"
    assert _gloss({"lemma": "τε", "features": {}}, behind)["text"] == "the eleventh or twelfth"


def test_short_text_for_long_first_sense():
    entry = _entry("lsj:22:n103046", PERSEUS, "τέμενος",
                   ["a piece of land cut off and assigned as an official domain"])
    gloss = _gloss({"lemma": "τέμενος", "features": {"pos": "noun"}}, {"text": "τέμενος", "lexicon_entries": [entry]})
    assert gloss["full_text"].startswith("a piece of land cut off")
    assert gloss["short_text"] == "a piece of land"


def test_lemma_headword_fallback_and_homographs():
    ml = _entry("middle-liddell:n7", ML, "κατακτείνω", ["to kill"])
    lookups = []

    def lookup(lemma):
        lookups.append(lemma)
        if lemma == "κατακτείνω":
            return {"match": "exact_headword", "entries": [ml]}
        if lemma == "ἐρύω":
            return {"match": "exact_headword", "entries": [_entry("middle-liddell:a", ML, "ἐρύω", ["to drag"]),
                                                           _entry("middle-liddell:b", ML, "ἐρύω", ["to protect"])]}
        return {"entries": []}
    reading = {"readings": [{"tokens": [
        {"kind": "word", "text": "κακκτάνοντες", "lemma": "κατακτείνω", "features": {"POS": "VERB"},
         "gloss": {"text": None}},
        {"kind": "word", "text": "ῤύεσθε", "lemma": "ἐρύω2", "features": {"POS": "VERB"}, "gloss": {"text": None}},
        {"kind": "word", "text": "Ζόννυσσον", "lemma": "Διόνυσος", "features": {}, "gloss": {"text": None}},
    ]}]}
    summary = attach_lemma_glosses(reading, lookup)
    rows = reading["readings"][0]["tokens"]
    assert rows[0]["gloss"]["text"] == "to kill"
    assert rows[0]["gloss"]["selection_basis"] == "parser_lemma_dictionary_headword_first_sense_not_contextual"
    assert rows[1]["gloss"]["text"] is None
    assert rows[1]["gloss"]["lemma_dictionary"]["skipped"][0]["reason"] == "homograph_entries_unresolved"
    assert rows[2]["gloss"]["lemma_dictionary"]["status"] == "no_headword"
    assert lookups == ["κατακτείνω", "ἐρύω", "Διόνυσος"] and summary["filled"] == 1


def test_one_explicit_cross_reference_is_followed():
    stub = _entry("lsj-logeion:crossga=", LOGEION, "γᾶ", [], "γᾶ, Dor. for γῆ (q.v.).")
    earth = _entry("middle-liddell:n1", ML, "γῆ", ["earth"])
    tables = {"γᾶ": [stub], "γῆ": [earth]}
    reading = {"readings": [{"tokens": [{"kind": "word", "text": "γᾶν", "lemma": "γᾶ", "features": {"POS": "NOUN"},
                                          "gloss": {"text": None}}]}]}
    attach_lemma_glosses(reading, lambda lemma: {"match": "exact_headword", "entries": tables.get(lemma, [])})
    gloss = reading["readings"][0]["tokens"][0]["gloss"]
    assert gloss["text"] == "earth"
    assert gloss["selection_basis"] == "parser_lemma_cross_referenced_headword_first_sense_not_contextual"
    assert gloss["lemma_dictionary"]["cross_reference"]["printed_relation"].endswith("for γῆ")


def test_parser_homograph_number_follows_lsj_key():
    first = _entry("lsj-logeion:crosse)ru/w1", LOGEION, "ἐρύω", ["drag"])
    second = _entry("lsj-logeion:crosse)ru/w2", LOGEION, "ἐρύω", ["rescue"])
    first["key"], second["key"] = "e)ru/w1", "e)ru/w2"
    ml = _entry("middle-liddell:x", ML, "ἐρύω", ["to drag along"])
    reading = {"readings": [{"tokens": [{"kind": "word", "text": "ῤύεσθε", "lemma": "ἐρύω2",
                                          "features": {"POS": "VERB"}, "gloss": {"text": None}}]}]}
    attach_lemma_glosses(reading, lambda lemma: {"match": "exact_headword", "entries": [ml, first, second]})
    gloss = reading["readings"][0]["tokens"][0]["gloss"]
    assert gloss["text"] == "rescue" and gloss["entry_id"] == "lsj-logeion:crosse)ru/w2"
    assert gloss["lemma_dictionary"]["skipped"][0]["reason"] == "parser_homograph_number_matches_lsj_key"


def test_morphology_supplement_order_and_superseded_perseus(tmp_path):
    core = tmp_path / "entries.jsonl"
    supplement = tmp_path / "supplement.jsonl"
    forms = tmp_path / "forms.jsonl"
    core.write_text(json.dumps({"id": "lsj:1:n5", "entry_id": "n5", "lemma": "μῆνις", "source": PERSEUS,
                                "gloss": "wrath", "source_url": "u"}, ensure_ascii=False) + "\n", encoding="utf-8")
    supplement.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in [
        {"id": "lsj-logeion:m", "entry_id": "m", "lemma": "μῆνις", "source": LOGEION, "gloss": "wrath",
         "perseus_lsj_id": "lsj:1:n5", "source_url": "u"},
        {"id": "dodson:1", "entry_id": "1", "lemma": "μῆνις", "source": DODSON, "gloss": "anger", "source_url": "u"},
        {"id": "middle-liddell:n9", "entry_id": "n9", "lemma": "μῆνις", "source": ML, "gloss": "wrath, anger",
         "source_url": "u"},
    ]) + "\n", encoding="utf-8")
    forms.write_text("", encoding="utf-8")
    morph = Morphology(core, forms, supplement_paths=[supplement])
    found = morph.headword_entries("μῆνις")
    assert [e["id"] for e in found["entries"]] == ["middle-liddell:n9", "lsj-logeion:m", "dodson:1"]
    assert found["match"] == "exact_headword"
    ids = [e["id"] for e in morph.analyze("μῆνις")["lexicon_entries"]]
    assert "lsj:1:n5" not in ids and ids[0] == "middle-liddell:n9"
    plain = Morphology(core, forms)
    assert [e["id"] for e in plain.headword_entries("μῆνις")["entries"]] == ["lsj:1:n5"]
    assert DICTIONARY_ORDER[0] == ML


# --- Regression on the real built supplement (Alcaeus 129 short glosses) ----

SUPPLEMENT = ROOT / "data/lexica/supplement-entries.jsonl"


@pytest.fixture(scope="module")
def real_morphology():
    if not (SUPPLEMENT.exists() and (ROOT / "data/lexica/entries.jsonl").exists()):
        pytest.skip("Built lexica supplement unavailable locally")
    return Morphology(ROOT / "data/lexica/entries.jsonl", ROOT / "data/raw/__no_forms__.jsonl",
                      supplement_paths=[SUPPLEMENT])


@pytest.mark.parametrize("lemma,pos,expected", [
    ("τε", "PART", "and"),
    ("Διόνυσος", "PROPN", "Dionysus"),
    ("τέμενος", "NOUN", "a piece of land"),
])
def test_alcaeus_129_short_glosses(real_morphology, lemma, pos, expected):
    reading = {"readings": [{"tokens": [{"kind": "word", "text": lemma, "lemma": lemma,
                                          "features": {"POS": pos}, "gloss": {"text": None}}]}]}
    attach_lemma_glosses(reading, real_morphology.headword_entries)
    gloss = reading["readings"][0]["tokens"][0]["gloss"]
    assert gloss["short_text"] == expected or gloss["short_text"].startswith(expected)
    assert gloss["source"] in (ML, "Perseus Autenrieth TEI via Homerica")
    assert gloss["source_url"] and gloss["raw_sha256"] and gloss["source_locator"]
