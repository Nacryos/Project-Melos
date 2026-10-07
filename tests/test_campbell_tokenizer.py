"""Synthetic editorial mechanics, not authored Greek corpus evidence."""
import unicodedata

from backend.passage_analysis import PassageAnalysisService, tokenize_span, utf16_offset


def test_isolated_combining_marks_are_editorial_and_lossless():
    text = "😀 …́ …̓ ά β"
    tokens = tokenize_span(text, 0, len(text))
    assert "".join(token["text"] for token in tokens) == text
    assert [token["text"] for token in tokens if token["kind"] == "word"] == ["ά", "β"]
    for token in tokens:
        assert text[token["start"]:token["end"]] == token["text"]
        assert token["start_utf16"] == utf16_offset(text, token["start"])
        assert token["end_utf16"] == utf16_offset(text, token["end"])
        if unicodedata.category(token["text"][0]).startswith("M"):
            assert token["kind"] == "editorial"


def test_underdotted_and_bracket_interrupted_words_are_looked_up_as_the_editors_reading():
    text = "α̣β γ[δ]ε ζ …́"
    passage = {"id": "synthetic:editorial", "language": "grc", "kind": "text", "text": text}
    calls = []
    def lookup(form, passage_id):
        calls.append(form)
        return {"candidates": []}
    service = PassageAnalysisService(lambda _: passage, lookup)
    result = service.analyze({"passage_id": passage["id"], "start": 0, "end": len(text),
                              "offset_unit": "codepoint", "selected_text": text})
    # The printed text is lossless; lookups use the editor's reading.
    assert calls == ["αβ", "γδε", "ζ"]
    words = [token for token in result["tokens"] if token["kind"] == "word"]
    assert [token["text"] for token in words] == ["α̣β", "γ[δ]ε", "ζ"]
    assert [token["form"] for token in words] == ["αβ", "γδε", "ζ"]
    assert words[0]["uncertain_letters"] and not words[0].get("editorial_fragment")
    assert any("Underdots" in warning for warning in words[0]["warnings"])
    assert words[1]["editorial_reconstruction"] and words[1]["supplied_letters"] == ["δ"]
    assert not words[1].get("supplied_whole_word")
    assert any("supplied by the editor" in warning for warning in words[1]["warnings"])
    assert "".join(token["text"] for token in result["tokens"]) == text


def test_supplied_letters_follow_the_bracket_direction():
    # A closing bracket inside a word closes a lacuna from the previous line:
    # the letters before it were supplied. An opening bracket supplies what follows.
    cases = {"να̣]σον": ("νασον", ["να"]), "λίποντε[ς": ("λίποντες", ["ς"]),
             "θύ[μ]ῳ": ("θύμῳ", ["μ"]), "ὀν]τρ[έχο]ντες": ("ὀντρέχοντες", ["ὀν", "έχο"])}
    for printed, (form, supplied) in cases.items():
        token = next(t for t in tokenize_span(printed, 0, len(printed)) if t["kind"] == "word")
        assert token["text"] == printed and token["form"] == form, printed
        assert token["supplied_letters"] == supplied, printed
        assert not token.get("editorial_fragment"), printed


def test_normal_accents_and_whole_supplied_words_keep_existing_behavior():
    text = "ά β̓ [γ] δ"
    words = [token for token in tokenize_span(text, 0, len(text)) if token["kind"] == "word"]
    assert len(words) == 4
    assert all(not token.get("editorial_fragment") for token in words)
    assert words[2]["text"] == "γ" and words[2]["supplied_whole_word"] and words[2]["supplied_letters"] == ["γ"]
    assert not words[0].get("editorial_reconstruction")


def test_non_bracket_interruptions_remain_fragments():
    text = "α…β γ†δ"
    words = [token for token in tokenize_span(text, 0, len(text)) if token["kind"] == "word"]
    assert len(words) == 4
    assert all(token["editorial_fragment"] for token in words)


def test_selection_starting_at_combining_mark_does_not_create_fake_word():
    text = "ά β"
    tokens = tokenize_span(text, 1, len(text))
    assert tokens[0]["text"] == "́"
    assert tokens[0]["kind"] == "editorial"
    assert [token["text"] for token in tokens if token["kind"] == "word"] == ["β"]
