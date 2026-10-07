"""Real local HTTP checks; generation is replaced with a recording fake."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest

SPEC = importlib.util.spec_from_file_location("nature_gallery", Path(__file__).resolve().parents[1] / "tools/serve_nature_gallery.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeProcess:
    returncode = None

    def poll(self):
        return self.returncode


class NatureGalleryHTTPTests(unittest.TestCase):
    collection = "portrait"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "output/imagegen/nature-gallery"
        if self.collection == "landscape":
            self.data /= "landscape"
        (self.data / "images").mkdir(parents=True)
        (self.root / "tools").mkdir()
        (self.root / "tools/regenerate_nature_image.py").write_text("# fake worker", encoding="utf-8")
        (self.root / "local-preview/nature-gallery").mkdir(parents=True)
        (self.root / "local-preview/nature-gallery/index.html").write_text("<h1>Gallery</h1>", encoding="utf-8")
        (self.data / "images/sea_coast-01.png").write_bytes(b"fake-png")
        (self.data / "images/unlisted.png").write_bytes(b"private")
        (self.root / ".env").write_text("SECRET=never-serve-this", encoding="utf-8")
        manifest = {"secret": "not exposed", "themes": [{"id": "sea_coast", "title": "Sea & coast", "description": "Coastal light", "images": [{"id": "sea_coast-01", "path": "images/sea_coast-01.png", "prompt": "Oil painting", "status": "ready", "error": "potential private details"}]}, {"id": "garden_grove", "title": "Garden & grove", "images": []}]}
        (self.data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.calls = []
        self.process = FakeProcess()
        self.process.returncode = None

        def launch(*args, **kwargs):
            self.calls.append((args, kwargs))
            return self.process

        self.server = MODULE.GalleryServer(self.root, port=0, launcher=launch, collection=self.collection)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f"127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, payload=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        final_headers = {"Host": self.host}
        body = raw
        if method == "POST":
            final_headers.update({"Origin": "http://" + self.host, "X-CSRF-Token": self.server.csrf, "Content-Type": "application/json"})
            if raw is None:
                body = json.dumps(payload)
        final_headers.update(headers or {})
        connection.request(method, path, body=body, headers=final_headers)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        response_headers = dict(response.getheaders())
        connection.close()
        return status, data, response_headers

    def test_only_static_allowlist_and_listed_images_are_served(self):
        for path in ("/", "/images/sea_coast-01.png"):
            self.assertEqual(self.request("GET", path)[0], 200)
        for path in ("/.env", "/tools/regenerate_nature_image.py", "/manifest.json", "/api/../.env", "/images/../../.env", "/images/%2e%2e/%2e%2e/.env", "/images/unlisted.png", "/jobs/abc.json"):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_manifest_is_projected_and_internal_error_is_hidden(self):
        status, body, headers = self.request("GET", "/api/manifest")
        self.assertEqual(status, 200)
        self.assertNotIn(b"not exposed", body)
        self.assertNotIn(b"potential private details", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        projected = json.loads(body)
        self.assertEqual(projected["orientation"], self.collection)
        self.assertEqual(projected["size"], "1536x1024" if self.collection == "landscape" else "1024x1536")
        self.assertEqual(projected["title"], "Landscape studies" if self.collection == "landscape" else "Nature studies")

    def test_host_origin_and_csrf_are_required(self):
        payload = {"theme_id": "sea_coast", "image_id": "sea_coast-01", "notes": "hello"}
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Origin": ""}, {"X-CSRF-Token": "wrong"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("POST", "/api/feedback", payload, headers)[0], 403)
        self.assertEqual(self.request("GET", "/api/session", headers={"Host": "evil.example"})[0], 403)
        self.assertFalse((self.data / "state.json").exists())

    def test_credit_failure_is_projected_as_neutral_public_message(self):
        path = self.data / "manifest.json"
        manifest = json.loads(path.read_text())
        image = manifest["themes"][0]["images"][0]
        image.update(status="failed", error="API credits needed. Add credits to the OpenAI account, then try again.", error_code="credit_balance_exhausted")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        projected = json.loads(self.request("GET", "/api/manifest")[1])
        self.assertEqual(projected["themes"][0]["images"][0]["error"], "API credits needed")
        self.assertEqual(projected["themes"][0]["images"][0]["status"], "failed")
        self.assertNotIn("error_code", projected["themes"][0]["images"][0])

    def test_feedback_state_merges_and_history_appends(self):
        common = {"theme_id": "sea_coast", "image_id": "sea_coast-01"}
        self.assertEqual(self.request("POST", "/api/feedback", {**common, "notes": "<script>literal notes</script>"})[0], 200)
        self.assertEqual(self.request("POST", "/api/feedback", {**common, "favourite": True})[0], 200)
        state = json.loads((self.data / "state.json").read_text())
        self.assertEqual(state["sea_coast-01"]["notes"], "<script>literal notes</script>")
        self.assertTrue(state["sea_coast-01"]["favourite"])
        feedback = json.loads(self.request("GET", "/api/feedback")[1])
        self.assertEqual(len(feedback["events"]), 2)
        self.assertEqual(feedback["state"], state)

    def test_invalid_types_ids_and_size_are_rejected(self):
        for payload in ({"theme_id": "../../tools"}, {"theme_id": "sea_coast", "image_id": "unknown"}, {"theme_id": "sea_coast", "notes": ["bad"]}, {"theme_id": "sea_coast", "notes": "a" * 2001}, {"theme_id": "sea_coast", "image_id": "sea_coast-01", "favourite": "yes"}):
            self.assertEqual(self.request("POST", "/api/feedback", payload)[0], 400)
        self.assertEqual(self.request("POST", "/api/feedback", raw="{" )[0], 400)
        self.assertEqual(self.request("POST", "/api/feedback", raw="a" * 17000)[0], 413)
        self.assertEqual(self.request("POST", "/api/feedback", {}, {"Content-Type": "text/plain"})[0], 415)

    def test_favourite_is_exclusive_per_theme_and_preserves_notes_history(self):
        path = self.data / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["themes"][0]["images"].append({"id": "sea_coast-02", "status": "pending"})
        manifest["themes"][1]["images"].append({"id": "garden_grove-01", "status": "pending"})
        path.write_text(json.dumps(manifest), encoding="utf-8")
        choices = [
            {"theme_id": "sea_coast", "image_id": "sea_coast-01", "favourite": True, "notes": "Keep the light"},
            {"theme_id": "garden_grove", "image_id": "garden_grove-01", "favourite": True},
            {"theme_id": "sea_coast", "image_id": "sea_coast-02", "favourite": True},
        ]
        for choice in choices:
            self.assertEqual(self.request("POST", "/api/feedback", choice)[0], 200)
        feedback = json.loads(self.request("GET", "/api/feedback")[1])
        self.assertFalse(feedback["state"]["sea_coast-01"]["favourite"])
        self.assertTrue(feedback["state"]["sea_coast-02"]["favourite"])
        self.assertTrue(feedback["state"]["garden_grove-01"]["favourite"])
        self.assertEqual(feedback["state"]["sea_coast-01"]["notes"], "Keep the light")
        self.assertEqual(len(feedback["events"]), 3)
        self.assertTrue(feedback["events"][0]["favourite"])

    def test_generation_uses_fixed_worker_and_private_validated_job(self):
        payload = {"theme_id": "sea_coast", "image_id": "sea_coast-01", "notes": "soft light; $(not a command)", "command": "malicious"}
        status, body, _ = self.request("POST", "/api/regenerate", payload)
        self.assertEqual(status, 202)
        self.assertEqual(len(self.calls), 1)
        args, kwargs = self.calls[0]
        command = args[0]
        self.assertEqual(Path(command[1]), self.root / "tools/regenerate_nature_image.py")
        self.assertEqual(command[2], "--job")
        self.assertEqual(command[4:], ["--collection", "landscape"] if self.collection == "landscape" else [])
        self.assertFalse(kwargs["shell"])
        job = json.loads(Path(command[3]).read_text())
        self.assertEqual(job["notes"], payload["notes"])
        self.assertNotIn("command", job)
        self.assertEqual(self.request("GET", "/jobs/" + Path(command[3]).name)[0], 404)
        self.assertEqual(json.loads(body)["job_id"], job["job_id"])

    def test_manual_generation_has_global_single_job_limit(self):
        self.assertEqual(self.request("POST", "/api/regenerate", {"theme_id": "sea_coast"})[0], 202)
        self.assertEqual(self.request("POST", "/api/regenerate", {"theme_id": "garden_grove"})[0], 409)
        self.assertEqual(len(self.calls), 1)
        self.process.returncode = 0
        self.assertEqual(self.request("POST", "/api/regenerate", {"theme_id": "garden_grove"})[0], 202)

    def test_job_status_has_no_process_arguments_or_notes(self):
        self.request("POST", "/api/regenerate", {"theme_id": "sea_coast", "notes": "private notes"})
        result = json.loads(self.request("GET", "/api/jobs")[1])
        self.assertEqual(set(result["jobs"][0]), {"job_id", "theme_id", "status"})
        self.assertEqual(result["jobs"][0]["status"], "running")

    def test_cross_process_worker_lock_prevents_launch_after_restart(self):
        (self.data / ".manual-generation.lock").write_text('{"pid":1234}', encoding="utf-8")
        self.assertEqual(self.request("POST", "/api/regenerate", {"theme_id": "sea_coast"})[0], 409)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.data / "jobs").exists())
        jobs = json.loads(self.request("GET", "/api/jobs")[1])["jobs"]
        self.assertEqual(jobs, [{"job_id": "active-worker", "theme_id": None, "status": "running"}])


class LandscapeGalleryHTTPTests(NatureGalleryHTTPTests):
    collection = "landscape"

    def test_landscape_feedback_images_and_locks_are_independent(self):
        portrait = self.root / "output/imagegen/nature-gallery"
        (portrait / "images").mkdir()
        (portrait / "images/portrait-only.png").write_bytes(b"portrait-original")
        originals = {
            "state.json": json.dumps({"sea_coast-01": {"favourite": True, "notes": "Original favourite"}}),
            "feedback.jsonl": '{"notes":"Original feedback"}\n',
            "manifest.json": '{"themes":[]}',
            ".manual-generation.lock": '{"pid":1234}',
        }
        for name, contents in originals.items():
            (portrait / name).write_text(contents, encoding="utf-8")
        self.assertEqual(json.loads(self.request("GET", "/api/state")[1]), {})
        self.assertEqual(json.loads(self.request("GET", "/api/feedback")[1])["events"], [])
        self.assertEqual(json.loads(self.request("GET", "/api/jobs")[1])["jobs"], [])
        self.assertEqual(self.request("GET", "/images/portrait-only.png")[0], 404)
        payload = {"theme_id": "sea_coast", "image_id": "sea_coast-01", "notes": "Landscape feedback", "favourite": False}
        self.assertEqual(self.request("POST", "/api/feedback", payload)[0], 200)
        self.assertEqual(self.request("POST", "/api/regenerate", payload)[0], 202)
        command = self.calls[0][0][0]
        self.assertEqual(Path(command[3]).parent, self.data / "jobs")
        for name, contents in originals.items():
            self.assertEqual((portrait / name).read_text(encoding="utf-8"), contents)
        self.assertEqual((portrait / "images/portrait-only.png").read_bytes(), b"portrait-original")

    def test_manifest_cannot_override_collection_or_traverse_to_portrait(self):
        path = self.data / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest.update(orientation="portrait", title="<script>unsafe title</script>", size="1x1")
        manifest["themes"][0]["images"][0]["path"] = "images/../../images/portrait.png"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        projected = json.loads(self.request("GET", "/api/manifest")[1])
        self.assertEqual(projected["orientation"], "landscape")
        self.assertEqual(projected["title"], "Landscape studies")
        self.assertEqual(projected["size"], "1536x1024")
        self.assertEqual(projected["themes"][0]["images"][0]["path"], "")
        self.assertEqual(self.request("GET", "/images/../../images/portrait.png")[0], 404)


if __name__ == "__main__":
    unittest.main()
