"""Minimal HTTP front for a local Morpheus build, reusing morphsvc's own engine code.

GET /api/v1/analysis/word?word=<w>&engine=morpheusgrc&lang=grc[&noAposRetry=1]
  -> the same JSON envelope morphsvc (and morph.alpheios.net) returns: the request flow of
     morphsvc.analysisword.AnalysisWord.call_engine without Flask or a response cache.
GET /health -> {"morpheus_commit", "morphsvc_commit", "stemlib"}

Only `morpheusgrc`/`grc` is served. The one local change: the Morpheus subprocess gets a
timeout (subclass), so a stuck process cannot hold a worker.
"""
import json
import os
import subprocess
import threading
import itertools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from morphsvc.lib.engines.MorpheusLocalEngine import MorpheusLocalEngine

CONFIG = {
    "PARSERS_MORPHEUS_URI": "org.perseus:tools:morpheus.v1",
    "PARSERS_MORPHEUS_RIGHTS": "Morphology provided by Morpheus from the Perseus Digital Library at Tufts University.",
    "PARSERS_MORPHEUS_PATH": os.environ["MORPHEUS_BIN"],
    "PARSERS_MORPHEUS_STEMLIBDIR": os.environ["MORPHEUS_STEMLIB"],
    "SERVICES_LEXICAL_ENTITY_SVC_GRC": None,
    "SERVICES_LEXICAL_ENTITY_SVC_LAT": None,
    "SERVICES_LEXICAL_ENTITY_BASE_URI": None,
}
SLOTS = threading.BoundedSemaphore(int(os.environ.get("MORPHEUS_WORKERS", "4")))


class Engine(MorpheusLocalEngine):
    def _execute_query(self, args, word):
        return subprocess.check_output(itertools.chain([self.morpheus_path], args, [word]), timeout=10)


ENGINE = Engine("morpheusgrc", CONFIG)


def analyse(word, options):
    engine_args = {name: options.get(name) for name in ENGINE.options()}
    word_uri = "urn:word:" + word
    analysis = ENGINE.lookup(word=word, word_uri=word_uri, language="grc", request_args=engine_args)
    oa = ENGINE.as_annotation("urn:TuftsMorphologyService:" + word + ":morpheusgrc", word_uri, analysis)
    return ENGINE.output_json(oa)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, kind="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/health":
            return self._send(200, json.dumps({"morpheus_commit": os.environ.get("MORPHEUS_COMMIT"),
                                               "morphsvc_commit": os.environ.get("MORPHSVC_COMMIT"),
                                               "stemlib": CONFIG["PARSERS_MORPHEUS_STEMLIBDIR"]}))
        if url.path != "/api/v1/analysis/word":
            return self._send(404, '{"error":"not found"}')
        query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        word = query.get("word", "")
        if query.get("engine") != "morpheusgrc" or query.get("lang") != "grc" or not 0 < len(word) <= 80:
            return self._send(400, '{"error":"expected engine=morpheusgrc, lang=grc and one word"}')
        with SLOTS:
            try:
                body = analyse(word, query)
            except Exception as exc:  # report, never crash the server
                return self._send(500, json.dumps({"error": type(exc).__name__}))
        self._send(201, body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
