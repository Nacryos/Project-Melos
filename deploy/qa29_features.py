"""Read API probes for QA29; no Jev reranking or morphology fetches.

The analysis POST computes local CPU predictions and may populate operational
caches; it never changes source records. Run against the canary before promotion.
"""
import argparse
import hashlib
import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PASSAGE_ID = "p2_cgl_anthology:355"
PHRASE = "κηλήμασι παντοδαποῖς"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def english(language):
    return isinstance(language, str) and bool(re.fullmatch(
        r"(?:en|eng)(?:-[a-z0-9]{2,8})*", language.strip().lower()))


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Probe:
    def __init__(self, origin):
        self.origin = origin.rstrip("/")

    def request(self, path, *, payload=None, **params):
        url = self.origin + path + ("?" + urlencode(params) if params else "")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data,
                          headers={"Content-Type": "application/json"} if data else {})
        with urlopen(request, timeout=240) as response:
            return json.load(response)

    def word_senses(self):
        result = self.request("/api/word", form="ἀνήρ")
        entry = next((row for row in result.get("lexicon_entries", [])
                      if row.get("id") == "lsj:1:n8665"), None)
        require(entry is not None, "The exact LSJ aner entry is missing")
        require(entry.get("dictionary_senses_status") == "source_structured",
                "LSJ raw XML definitions are unavailable or failed provenance checks")
        senses = entry.get("dictionary_senses", [])
        texts = [row["text"] for row in senses]
        require(texts and texts[0] == "man", "Aner must start with the source definition 'man'")
        require({"husband", "male animal", "free men"} <= set(texts),
                "Representative source meanings of aner are missing")
        require(not ({"woman", "god", "beast", "free"} & set(texts)),
                "Opposed meanings or clipped phrases leaked into aner definitions")
        require(not any(re.search(r"nar-|ner-|Sanskrit|Skt\.", text, re.I) for text in texts),
                "Sanskrit etymology leaked into English definitions")
        for sense in senses:
            require(sense.get("lexicon_entry_id") == entry["id"]
                    and sense.get("evidence_type") == "dictionary_sense"
                    and re.fullmatch(r"[0-9a-f]{64}", sense.get("raw_sha256", ""))
                    and sense.get("raw_sha256") == senses[0].get("raw_sha256")
                    and sense.get("source_url") == entry.get("source_url")
                    and sense.get("source_locator", {}).get("node_path"),
                    "Aner definition lost its exact entry/source identity")
        return {"source_senses": len(senses)}

    def sequence(self):
        reverse = " ".join(reversed(PHRASE.split()))
        cases = [("ordered", PHRASE), ("proximity", reverse), ("all_terms", reverse)]
        for relation, query in cases:
            result = self.request("/api/search", q=query, mode="forms", match="exact",
                                  forms_relation=relation, slop=0, author="Ibycus", limit=100)
            contract = result.get("search_contract", {})
            require(result.get("mode") == "forms" and contract.get("relation") == relation
                    and contract.get("complete") is True and contract.get("query_term_count") == 2
                    and contract.get("expansion_policy") == "literal_only",
                    f"{relation}: strict multiword contract is missing")
            require(PASSAGE_ID in {row["id"] for row in result["results"]},
                    f"{relation}: known original passage is absent")
            for row in result["results"]:
                proof = row.get("sequence_match", {})
                terms = proof.get("terms", [])
                require(proof.get("relation") == relation and proof.get("text_sha256") == digest(row["text"]),
                        f"{relation}: witness does not belong to its returned source text")
                require(len(terms) == 2 and {term["query_index"] for term in terms} == {0, 1}
                        and len({term["token_index"] for term in terms}) == 2,
                        f"{relation}: query words need distinct source-token witnesses")
                for term in terms:
                    spans = term.get("source_spans", [])
                    require(bool(spans), "Sequence term lacks source spans")
                    for span in spans:
                        require(row["text"][span["start"]:span["end"]] == span["text"],
                                "Sequence offset changed the source wording")
                if relation == "ordered":
                    require(terms[0]["token_index"] < terms[1]["token_index"], "Ordered witness is reversed")
                require(proof.get("extra_words") == (None if relation == "all_terms" else 0),
                        "Sequence gap contract changed")
        reversed_order = self.request("/api/search", q=reverse, mode="forms", match="exact",
                                      forms_relation="ordered", slop=0, author="Ibycus", limit=100)
        require(reversed_order.get("total") == 0, "Reversed ordered phrase incorrectly matched")
        expanded = self.request("/api/search", q=PHRASE, mode="forms", match="fuzzy",
                                forms_relation="ordered", slop=0, author="Ibycus", limit=100)
        require(expanded.get("search_contract", {}).get("expansion_policy")
                == "accepted_source_links_no_generated_paradigms", "Source form expansion is missing")
        require(PASSAGE_ID in {row["id"] for row in expanded.get("results", [])},
                "Source-expanded phrase lost the original literal occurrence")
        return {"relations": 3, "reversed_order_rejected": True, "source_expansion": True}

    def analysis(self):
        passage = self.request("/api/passage", id=PASSAGE_ID)
        text = passage["text"]
        require(text[63:83] == PHRASE, "Known exact source selection changed")
        result = self.request("/api/analyze-passage", payload={
            "version": 1, "passage_id": PASSAGE_ID, "start": 63, "end": 83,
            "offset_unit": "codepoint", "selected_text": text[63:83],
            "rerank": False, "fetch_machine": False,
        })
        require(result.get("status") == "ok" and result["selection"]["text"] == PHRASE
                and (result["selection"]["start"], result["selection"]["end"]) == (63, 83),
                "Analysis did not preserve the exact selection")
        require(result["passage"]["text_sha256"] == digest(text), "Analysis source hash changed")
        require(result.get("ranking", {}).get("status") == "not_requested"
                and result.get("sense_ranking", {}).get("status") == "not_requested"
                and result.get("limits", {}).get("machine_fetches") == 0,
                "Probe unexpectedly requested an external inference operation")
        tokens = result["tokens"]
        require("".join(token["text"] for token in tokens) == PHRASE, "Selection tokens are not lossless")
        for token in tokens:
            require(text[token["start"]:token["end"]] == token["text"], "Analysis token offsets are wrong")
        # Only a known representative needs a definition; absent senses remain absent.
        charm = next(token for token in tokens if token["text"] == "κηλήμασι")
        senses = [sense for entry in charm.get("lexicon_entries", [])
                  for sense in entry.get("dictionary_senses", [])]
        require(any(s.get("lexicon_entry_id") == "lsj:11:n57100" and s.get("text") == "charm, spell"
                    for s in senses), "Representative source sense 'charm, spell' is missing")
        syntax = result.get("syntax", {})
        require(syntax.get("state") == "ready" and syntax.get("evidence_type") == "contextual_prediction",
                "Actual local syntax inference did not reach ready")
        require(syntax.get("tokens") and syntax.get("provenance", {}).get("revision"),
                "Parser output or pinned-model provenance is missing")
        selected = []
        for token in syntax["tokens"]:
            begin, end = token["absolute_start"], token["absolute_end"]
            require(text[begin:end] == token["text"], "Syntax changed original source characters")
            require(begin == syntax["context_start"] + token["start"]
                    and end == syntax["context_start"] + token["end"], "Syntax relative/absolute offsets disagree")
            require(token["selected"] == (begin < 83 and end > 63), "Syntax selection overlap is incorrect")
            if token["selected"]:
                selected.append(token)
        require(len(selected) == 2, "Parser did not retain both selected Greek words")
        interlinear = result.get("interlinear", {})
        require(interlinear.get("text") == PHRASE and bool(interlinear.get("readings")),
                "Interlinear projection is missing")
        for reading in interlinear["readings"]:
            require("".join(token["text"] for token in reading["tokens"]) == PHRASE,
                    "Interlinear projection changed the selected wording")
        meaning = result.get("meaning", {})
        require(meaning.get("language") == "eng" and meaning.get("interpretations") == [],
                "A partial Greek phrase was presented as an aligned translation")
        for row in result.get("context", {}).get("published_translations", []) + meaning.get("context_translations", []):
            require(english(row.get("language")), "Non-English text leaked into English translation output")
        require(not result["context"]["published_translations"],
                "This control has only Modern Greek translations; no English context should be fabricated")
        return {"syntax_tokens": len(syntax["tokens"]), "selected_tokens": len(selected),
                "paid_calls_requested": 0}

    def translations(self):
        source = self.request("/api/passage", id=PASSAGE_ID + ":tr1")
        require(source.get("language") == "ell" and source.get("parent_id") == PASSAGE_ID,
                "Modern Greek source translation is missing")
        query = " ".join(source["text"].split()[:6])
        default = self.request("/api/search", q=query, mode="words", match="exact", author="Ibycus", limit=100)
        require(all(row.get("kind") != "translation" or english(row.get("language"))
                    for row in default.get("results", [])), "Default search displayed a non-English translation")
        explicit = self.request("/api/search", q=query, mode="words", match="exact", language="ell",
                                author="Ibycus", limit=100)
        require(source["id"] in {row["id"] for row in explicit.get("results", [])},
                "Explicit Modern Greek source-language search lost its translation")
        for row in default.get("results", []) + explicit.get("results", []):
            require(all(english(preview.get("language")) for preview in row.get("translation_previews", [])),
                    "A non-English translation was labelled as an English preview")
        return {"default_english_only": True, "explicit_modern_greek_preserved": True}

    def semantic(self):
        status = self.request("/api/status")
        embeddings = status.get("embeddings", {})
        require(embeddings.get("ready") is True and embeddings.get("model") == "BAAI/bge-m3",
                "The BGE-M3 index is not ready")
        result = self.request("/api/search", q="Sappho Cretan grove cold water and roses",
                              mode="themes", limit=5)
        require(result.get("mode") == "themes" and bool(result.get("results"))
                and result.get("method") == "Local multilingual dense rank grouped by explicit parent IDs; rank is not confidence or influence evidence.",
                "Actual local BGE embedding query failed or used a fallback")
        require(all(row.get("retrieval_score_kind") == "reciprocal_rank"
                    and row.get("language") == "grc" and row.get("kind") == "text"
                    for row in result["results"]), "Semantic result projection changed")
        return {"model": embeddings["model"], "results": len(result["results"])}


def verify(origin):
    probe = Probe(origin)
    for name in ("word_senses", "sequence", "analysis", "translations", "semantic"):
        started = time.perf_counter()
        try:
            detail = getattr(probe, name)()
        except Exception as exc:
            print(json.dumps({"test": name, "status": "FAIL", "error": str(exc)}), flush=True)
            raise
        print(json.dumps({"test": name, "status": "PASS", "seconds": round(time.perf_counter() - started, 2),
                          **detail}), flush=True)
    print("QA29 feature probes passed; no paid inference requested.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8792")
    args = parser.parse_args()
    verify(args.origin)
