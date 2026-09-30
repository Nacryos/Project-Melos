"""Synthetic ranking fixtures only; these are not historical corpus claims."""

from backend.retrieval import fuse


def passage(identifier, *, kind="text", language="grc", author="Poet",
            edition="Edition A", citation="1", text="Greek fixture", **extra):
    return {"id": identifier, "kind": kind, "language": language,
            "author": author, "edition": edition, "work": "Song",
            "citation": citation, "text": text,
            "source_url": f"https://example.org/{identifier}", **extra}


def test_rank_fusion_uses_positions_not_incomparable_raw_scores():
    records = {
        "a": passage("a", text="alpha"),
        "b": passage("b", citation="2", text="beta"),
    }
    fetch = records.get
    first = fuse("query", [dict(records["a"], score=1e9), records["b"]], [],
                 [{"id": "b", "score": .99}, {"id": "a", "score": .01}], fetch)
    second = fuse("query", [dict(records["a"], score=-1e9), records["b"]], [],
                  [{"id": "b", "score": -99}, {"id": "a", "score": 999}], fetch)
    assert [row["id"] for row in first["results"]] == ["a", "b"]
    assert [row["id"] for row in second["results"]] == ["a", "b"]
    assert first["results"][0]["retrieval_score_kind"] == "reciprocal_rank_fusion"
    assert first["results"][0]["retrieval_ranks"] == {"lexical": 1, "semantic": 2}
    assert first["results"][0]["score"] == second["results"][0]["score"]


def test_explicit_supporting_records_group_into_greek_parent_without_losing_evidence():
    records = {
        "g": passage("g", author="Poet", text="Greek fixture"),
        "t": passage("t", kind="translation", language="eng", text="sea voyage",
                     parent_id="g"),
        "c": passage("c", kind="commentary", language="eng", author="Scholar",
                     text="sea metaphor", parent_id="g"),
    }
    output = fuse("sea", [records["g"]], [],
                  [{"id": "t", "score": .8, "match_reason": "English translation embedding"},
                   {"id": "c", "score": .7, "match_reason": "Commentary embedding"}],
                  records.get, author="POET", language="grc")
    assert output["total"] == 1
    result = output["results"][0]
    assert result["id"] == "g" and result["author"] == "Poet"
    assert result["retrieval_ranks"] == {"lexical": 1, "semantic": 1}
    assert [(e["id"], e["signal"]) for e in result["matched_evidence"]] == [
        ("g", "lexical"), ("t", "semantic"), ("c", "semantic")]
    assert result["matched_evidence"][2]["author"] == "Scholar"
    assert result["matched_evidence"][1]["raw_score"] == .8
    assert result["matched_evidence"][1]["source_url"] == "https://example.org/t"
    assert "linked translation/commentary" in result["match_reason"]
    assert "matched_evidence" not in records["g"]


def test_greek_only_and_filters_do_not_leak_parent_across_selected_language_or_edition():
    records = {
        "g": passage("g", author="Poet", edition="Greek edition"),
        "t": passage("t", kind="translation", language="eng", author="Scholar",
                     edition="English edition", parent_id="g"),
    }
    greek_only = fuse("sea", [], [], [records["t"]], records.get,
                      language="grc", commentary_assisted=False)
    assert greek_only["results"] == []
    assert fuse("sea", [], [], [records["t"]], records.get,
                commentary_assisted=False)["results"] == []
    english = fuse("sea", [], [], [records["t"]], records.get,
                   language="eng", edition="English edition")
    assert [row["id"] for row in english["results"]] == ["t"]
    greek = fuse("sea", [], [], [records["t"]], records.get,
                 author="Poet", language="grc", edition="Greek edition")
    assert [row["id"] for row in greek["results"]] == ["g"]
    wrong_author = fuse("sea", [], [], [records["t"]], records.get,
                        author="Unknown", language="grc")
    assert wrong_author["results"] == []
    alias = fuse("sea", [], [], [records["t"]], records.get,
                 author="Verified alias", author_labels=["Poet"], language="grc")
    assert [row["id"] for row in alias["results"]] == ["g"]


def test_only_explicit_valid_greek_parent_projects_and_reference_filter_holds():
    records = {
        "orphan": passage("orphan", kind="commentary", language="eng",
                          parent_id="missing"),
        "latin": passage("latin", language="lat"),
        "latin_note": passage("latin_note", kind="commentary", language="eng",
                              text="note on Latin fixture", citation="2", parent_id="latin"),
        "reference": passage("reference", kind="reference"),
    }
    result = fuse("sea", [], [], list(records.values()), records.get)
    assert {row["id"] for row in result["results"]} == {"orphan", "latin", "latin_note"}
    assert "reference" not in {row["id"] for row in result["results"]}
    assert "latin_note" in {row["id"] for row in result["results"]}
    assert fuse("sea", [records["reference"]], [], [], records.get,
                include_reference=True)["results"][0]["id"] == "reference"


def test_same_edition_mirror_deduplicates_but_distinct_editions_survive():
    records = {
        "a": passage("a", metadata={"cts_urn": "urn:edition-a"}),
        "mirror": passage("mirror", metadata={"cts_urn": "urn:edition-a"}),
        "other": passage("other", edition="Edition B", metadata={"cts_urn": "urn:edition-b"}),
    }
    output = fuse("Greek", [records["a"], records["mirror"], records["other"]],
                  [], [], records.get)
    assert output["total"] == 2
    assert [row["id"] for row in output["results"]] == ["a", "other"]
    assert output["results"][0]["mirrored_ids"] == ["mirror"]
    assert {e["id"] for e in output["results"][0]["matched_evidence"]} == {"a", "mirror"}
    assert output["results"][1]["retrieval_ranks"] == {"lexical": 2}


def test_pagination_is_stable_after_grouping():
    records = {str(i): passage(str(i), citation=str(i), text=f"fixture {i}")
               for i in range(4)}
    pages = [fuse("fixture", list(records.values()), [], [], records.get,
                  limit=1, offset=i) for i in range(5)]
    assert [page["total"] for page in pages] == [4] * 5
    assert [page["results"][0]["id"] for page in pages[:4]] == list(records)
    assert pages[4]["results"] == []


def test_unreviewed_candidates_and_parents_are_excluded():
    records = {
        "good": passage("good", quality="source_text", citation="1"),
        "ocr": passage("ocr", quality="machine_ocr", citation="2"),
        "mixed": passage("mixed", quality="mixed_content", citation="3"),
        "review": passage("review", quality="needs_review", citation="4"),
        "support": passage("support", kind="translation", language="eng",
                           parent_id="ocr", quality="source_text"),
    }
    result = fuse("fixture", list(records.values()), [], [], records.get,
                  language="grc")
    assert [row["id"] for row in result["results"]] == ["good"]
