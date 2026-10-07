import json
from types import SimpleNamespace

import pytest

from backend.syntax_provider import MAX_CHARS, SyntaxProvider, SyntaxProviderError, _mark_nonlexical


@pytest.fixture
def provider(tmp_path):
    (tmp_path / "melos-provenance.json").write_text(json.dumps({
        "provider": "test", "model": "test-model", "model_version": "fixture",
        "revision": "test-revision", "source_url": "https://example.invalid/test-only",
        "artifact_sha256": "test-hash", "license": "test", "annotation_scheme": "test",
        "files": [{"path": "not-loaded-in-unit-tests", "sha256": "test"}],
    }))
    return SyntaxProvider(tmp_path)


class FakeDoc(list):
    def __init__(self, text, spans):
        super().__init__()
        self.text = text
        for i, (start, end) in enumerate(spans):
            self.append(SimpleNamespace(i=i, idx=start, text=text[start:end], lemma_=text[start:end],
                                        pos_="NOUN", tag_="test", morph=SimpleNamespace(to_dict=lambda: {"Case": "Nom"}),
                                        dep_="ROOT" if i == 0 else "dep", is_sent_start=i == 0))
        for item in self:
            item.head = self[0]


class FakeNlp:
    def __init__(self, spans):
        self.spans = spans

    def make_doc(self, text):
        return FakeDoc(text, self.spans)

    def __call__(self, doc):
        return doc


def test_missing_model_status_and_analysis(tmp_path):
    adapter = SyntaxProvider(tmp_path)
    assert adapter.status()["state"] == "unavailable"
    with pytest.raises(SyntaxProviderError, match="Install"):
        adapter.analyze("λόγος")


def test_status_does_not_load(provider, monkeypatch):
    monkeypatch.setattr("backend.syntax_provider.importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr(provider, "_load", lambda receipt: pytest.fail("status loaded model"))
    assert provider.status()["state"] == "available"
    assert provider.status()["verified_in_process"] is False


def test_exact_offsets_repeats_brackets_combining_marks(provider, monkeypatch):
    text = "🙂 α\u0301 [λόγος] … λόγος!"
    # The parser sees the view without the editor's brackets; spans are view
    # offsets and come back mapped onto the unchanged source text.
    spans = [(0, 1), (2, 4), (5, 10), (11, 12), (13, 18), (18, 19)]
    monkeypatch.setattr(provider, "_load", lambda receipt: FakeNlp(spans))
    monkeypatch.setattr("backend.syntax_provider.importlib.metadata.version", lambda name: "test-version")
    result = provider.analyze(text)
    assert result["evidence_type"] == "contextual_prediction"
    assert result["offset_unit"] == "unicode_codepoint"
    assert result["tokens"][0]["head"] is None
    assert [t["start"] for t in result["tokens"] if t["text"] == "λόγος"] == [6, 15]
    assert all(text[t["start"]:t["end"]] == t["text"] for t in result["tokens"])
    assert result["tokens"][1]["features"] == {"Case": "Nom"}
    assert result["parser_input_preprocessing"]["characters_dropped"] == 2


def test_bracket_interrupted_word_maps_to_one_source_span(provider, monkeypatch):
    text = "να\u0323]σον Δ[ίος]"
    # View "νασον Δίος": one token per printed word, brackets inside the span.
    spans = [(0, 5), (5, 6), (6, 10)]
    monkeypatch.setattr(provider, "_load", lambda receipt: FakeNlp(spans))
    monkeypatch.setattr("backend.syntax_provider.importlib.metadata.version", lambda name: "test-version")
    result = provider.analyze(text)
    words = [t for t in result["tokens"] if t["token_kind"] == "lexical"]
    assert [t["text"] for t in words] == ["να\u0323]σον", "Δ[ίος"]
    assert [t["model_text"] for t in words] == ["νασον", "Δίος"]
    assert all(text[t["start"]:t["end"]] == t["text"] for t in result["tokens"])


@pytest.mark.parametrize("text,code", [("", "invalid_text"), (" \n", "invalid_text"), (None, "invalid_text"), ("α" * (MAX_CHARS+1), "span_too_large")])
def test_input_limits_before_loading(provider, text, code):
    with pytest.raises(SyntaxProviderError) as exc:
        provider.analyze(text)
    assert exc.value.code == code


def test_single_concurrent_inference(provider, monkeypatch):
    monkeypatch.setattr("backend.syntax_provider.LOCK_WAIT_SECONDS", 0.1)
    provider._lock.acquire()
    try:
        with pytest.raises(SyntaxProviderError) as exc:
            provider.analyze("λόγος")
        assert exc.value.code == "provider_busy"
    finally:
        provider._lock.release()


def test_load_error_is_visible_and_not_retried(provider, monkeypatch):
    def fail(receipt):
        raise RuntimeError("bad runtime")
    monkeypatch.setattr(provider, "_load", fail)
    with pytest.raises(SyntaxProviderError) as exc:
        provider.analyze("λόγος")
    assert exc.value.code == "provider_failed"
    assert provider.status()["state"] == "error"
    monkeypatch.setattr(provider, "_load", lambda receipt: pytest.fail("retried failed initialization"))
    with pytest.raises(SyntaxProviderError):
        provider.analyze("λόγος")


def test_rejects_model_mutation(provider, monkeypatch):
    class ChangesText(FakeNlp):
        def __call__(self, doc):
            doc.text = "restored source"
            return doc
    monkeypatch.setattr(provider, "_load", lambda receipt: ChangesText([(0, 5)]))
    with pytest.raises(SyntaxProviderError) as exc:
        provider.analyze("λόγος")
    assert exc.value.code == "offset_mismatch"


def test_integrity_failure_before_import(provider):
    with pytest.raises(SyntaxProviderError) as exc:
        provider.analyze("λόγος")
    assert exc.value.code == "model_integrity"


def test_token_limit_before_prediction(provider, monkeypatch):
    class TooMany(FakeNlp):
        def __call__(self, doc):
            pytest.fail("inference should not run")
    monkeypatch.setattr(provider, "_load", lambda receipt: TooMany([(0, 1)] * 257))
    with pytest.raises(SyntaxProviderError) as exc:
        provider.analyze("α")
    assert exc.value.code == "span_too_large"


def test_editorial_and_whitespace_predictions_are_explicitly_inapplicable():
    tokens = [dict(id=i, text=text, lemma="model-guess", upos="NOUN", xpos="test", features={"Case": "Nom"},
                   head=head, deprel="root" if head is None else "nmod")
              for i, (text, head) in enumerate([("\n", None), ("λόγος", 0), ("[", 1), ("…", 1), (".", 1)])]
    _mark_nonlexical(tokens)
    for token in (tokens[0], tokens[2], tokens[3]):
        assert token["prediction_status"] == "not_applicable"
        assert token["lemma"] is None and token["features"] == {}
        assert token["raw_prediction"]["lemma"] == "model-guess"
    assert tokens[1]["head"] is None
    assert tokens[1]["deprel"] is None
    assert tokens[1]["attachment_status"] == "unresolved_nonlexical_head"
    assert tokens[4]["token_kind"] == "punctuation"
    assert tokens[4]["head"] == 1


def test_whitespace_analysis_view_preserves_original_spans(provider, monkeypatch):
    text = "α\r\n\t[β]"
    spans = [(0, 1), (1, 4), (4, 5)]
    seen = []
    class RecordsInput(FakeNlp):
        def make_doc(self, value):
            seen.append(value)
            return super().make_doc(value)
    monkeypatch.setattr(provider, "_load", lambda receipt: RecordsInput(spans))
    monkeypatch.setattr("backend.syntax_provider.importlib.metadata.version", lambda name: "test-version")
    result = provider.analyze(text)
    assert seen == ["α   β"]
    assert result["tokens"][1]["text"] == "\r\n\t"
    assert result["tokens"][1]["model_text"] == "   "
    assert result["tokens"][1]["prediction_status"] == "not_applicable"
    assert all(text[t["start"]:t["end"]] == t["text"] for t in result["tokens"])
    assert result["source_text_unchanged"] is True
    assert result["model_input_identical"] is False
    assert result["parser_input_preprocessing"]["characters_replaced"] == 3
    assert result["parser_input_preprocessing"]["position_preserving"] is False
    assert result["parser_input_preprocessing"]["characters_dropped"] == 2
    original = provider.analyze(text, normalize_whitespace=False)
    # Without whitespace normalisation only the editor's brackets are dropped.
    assert seen[-1] == text.replace("[", "").replace("]", "")
    assert original["parser_input_preprocessing"]["name"] == "editorial_brackets_dropped_v2"
