"""Release Q: a source edition's printed date is used only when its quote is verified in the corpus."""
import importlib.util
from pathlib import Path

from backend.author_catalogue import date_fields

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collect_chronology", ROOT / "scripts/collect_chronology.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def _texts(name):
    entry = cc.EDITION_DATES[name]
    out = {entry["passage_id"]: "x\n" + entry["quote"].replace(" ", "\n", 2) + "\ny"}
    for also in entry.get("also", []):
        out[also["passage_id"]] = also["quote"]
    return out


def test_verified_quote_gives_dated_claim():
    claim = cc.edition_chronology("Anacreontea", _texts("Anacreontea"))
    assert claim["type"] == "edition_date_statement"
    assert (claim["sort_start"], claim["sort_end"]) == tuple(cc.EDITION_DATES["Anacreontea"]["interval"])
    assert claim["source_passage_ids"] == [cc.EDITION_DATES["Anacreontea"]["passage_id"]]
    date, period = date_fields(claim)
    assert date["approximate"] and date["edition_statement"]["quote_ocr"]


def test_unverified_or_missing_corpus_gives_nothing():
    assert cc.edition_chronology("Anacreontea", None) is None
    assert cc.edition_chronology("Anacreontea", {cc.EDITION_DATES["Anacreontea"]["passage_id"]: "other text"}) is None
    # every quote of an entry must be found (the second edition page too)
    texts = _texts("Homeric Hymns")
    texts.pop(cc.EDITION_DATES["Homeric Hymns"]["also"][0]["passage_id"])
    assert cc.edition_chronology("Homeric Hymns", texts) is None


def test_label_without_edition_date_stays_undated():
    assert "Orphica" not in cc.EDITION_DATES
    assert cc.edition_chronology("Orphica", {}) is None


def test_single_printed_year_is_still_approximate():
    claim = cc.edition_chronology("Semonides", _texts("Semonides"))
    date, _ = date_fields(claim)
    assert date["start"] == date["end"] and date["approximate"]
    assert "single_round_year_kind_unstated" in claim["uncertainty"]


# Release Q: a person's period comes from the floruit, else the middle of the active life.
def _claim(kind, start, end, refs=True, rank="normal"):
    return {"kind": kind, "rank": rank, "references": [{}] if refs else [], "effective_year_interval": [start, end],
            "statement_id": f"{kind}{start}"}


def test_period_from_birth_plus_40_capped_by_death():
    # born 497/6, died 406/5 (Sophocles-like): Classical, not Archaic
    year, rule = cc.period_anchor([_claim("birth", -497, -497), _claim("death", -406, -406)])
    assert (year, rule) == (-457, "birth_plus_40_capped_by_death")
    # a short life: the death date caps the anchor
    year, rule = cc.period_anchor([_claim("birth", -340, -340), _claim("death", -320, -320)])
    assert year == -320


def test_floruit_and_work_period_outrank_birth():
    assert cc.period_anchor([_claim("birth", -600, -501), _claim("floruit", -500, -401)]) == (-450.5, "floruit")
    assert cc.period_anchor([_claim("birth", -300, -300), _claim("work_period_start", -270, -270),
                             _claim("work_period_end", -250, -250)]) == (-260, "work_period_midpoint")


def test_unreferenced_or_deprecated_claims_do_not_place_a_period():
    assert cc.period_anchor([_claim("floruit", -650, -650, refs=False), _claim("birth", -700, -700)]) == (-660, "birth_plus_40")
    assert cc.period_anchor([_claim("birth", -700, -700, rank="deprecated"), _claim("death", -600, -600)]) == (-600, "death")
    assert cc.period_anchor([]) == (None, None)


def test_date_fields_period_uses_anchor_not_birth():
    claim = {"sort_start": -485, "sort_end": -485, "sort_year": -485, "claim_kind": "birth",
             "period_year": -445, "period_rule": "birth_plus_40_capped_by_death", "period_note": "x"}
    date, period = date_fields(claim)
    assert period.startswith("Classical") and date["year"] == -485 and date["period_rule"] == "birth_plus_40_capped_by_death"
    # files without the anchor keep the release P behaviour
    date, period = date_fields({"sort_start": -485, "sort_end": -485, "sort_year": -485})
    assert period.startswith("Archaic") and date["period_rule"] == "selected_claim_midpoint"
