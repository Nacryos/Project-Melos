"""Local, narrowly scoped feedback gallery. Run: python tools/serve_nature_gallery.py.

The optional regeneration worker receives only a validated --job JSON path.
This server never imports a paid-generation client or exposes its environment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import subprocess
import sys
import threading
from urllib.parse import unquote, urlsplit
import uuid

THEMES = ("sea_coast", "garden_grove", "meadow_pasture", "mountain_woodland", "river_spring")
STATUSES = {"pending", "generating", "ready", "failed"}
ASSETS = {"/": "index.html", "/index.html": "index.html", "/gallery.css": "gallery.css", "/gallery.js": "gallery.js"}
MAX_BODY = 16_384
MAX_NOTES = 2_000


def now():
    return datetime.now(timezone.utc).isoformat()


class GalleryServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, repo: Path, port=8793, launcher=None, collection="portrait"):
        if collection not in {"portrait", "landscape"}:
            raise ValueError("Unknown gallery collection")
        self.repo = repo.resolve()
        self.collection = collection
        self.data = self.repo / "output/imagegen/nature-gallery"
        if collection == "landscape":
            self.data /= "landscape"
        self.static = self.repo / "local-preview/nature-gallery"
        self.worker = self.repo / "tools/regenerate_nature_image.py"
        self.data.mkdir(parents=True, exist_ok=True)
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.launcher = launcher or subprocess.Popen
        self.jobs = {}
        super().__init__(("127.0.0.1", port), GalleryHandler)

    def read_json(self, name, fallback):
        try:
            return json.loads((self.data / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fallback

    def manifest(self):
        raw = self.read_json("manifest.json", {})
        result = []
        for theme in raw.get("themes", []) if isinstance(raw, dict) else []:
            if not isinstance(theme, dict) or theme.get("id") not in THEMES:
                continue
            images = []
            for item in theme.get("images", []):
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                path = item.get("path", "")
                valid_path = self.image_path(path)
                error = ""
                if item.get("error"):
                    error = "API credits needed" if item.get("error_code") == "credit_balance_exhausted" or "credit_balance_exhausted" in str(item["error"]) or str(item["error"]).startswith("API credits needed") else "Generation did not finish. Please try again."
                images.append({"id": item["id"][:160], "path": path if valid_path else "", "prompt": str(item.get("prompt", ""))[:12000], "status": item.get("status") if item.get("status") in STATUSES else "pending", "error": error})
            result.append({"id": theme["id"], "title": str(theme.get("title", theme["id"]))[:200], "description": str(theme.get("description", ""))[:2000], "images": images})
        # Collection identity comes from the fixed server selection, never arbitrary
        # manifest values, and all browser labels are rendered as text.
        return {"themes": result, "orientation": self.collection,
                "size": "1536x1024" if self.collection == "landscape" else "1024x1536",
                "title": "Landscape studies" if self.collection == "landscape" else "Nature studies"}

    def image_path(self, relative):
        if not isinstance(relative, str) or not relative.startswith("images/") or "\\" in relative:
            return None
        candidate = (self.data / relative).resolve()
        image_root = (self.data / "images").resolve()
        if not image_root.is_relative_to(self.data.resolve()) or not candidate.is_relative_to(image_root) or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            return None
        return candidate

    def state(self):
        state = self.read_json("state.json", {})
        return state if isinstance(state, dict) else {}

    def record(self, event):
        with (self.data / "feedback.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")


class GalleryHandler(BaseHTTPRequestHandler):
    server: GalleryServer

    def log_message(self, format, *args):
        # URLs can contain arbitrary text; keep local logs intentionally quiet.
        pass

    def send_bytes(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(content)

    def json(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def trusted(self, write=False):
        port = self.server.server_port
        host = self.headers.get("Host", "")
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.json(403, {"error": "Unrecognized local host."})
            return False
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or (origin and origin != "http://" + host):
            self.json(403, {"error": "Same-origin access required."})
            return False
        if write and (origin != "http://" + host or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), self.server.csrf)):
            self.json(403, {"error": "Reload the gallery before saving."})
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        route = unquote(urlsplit(self.path).path)
        if route == "/api/session":
            return self.json(200, {"csrf_token": self.server.csrf})
        if route == "/api/manifest":
            return self.json(200, self.server.manifest())
        if route == "/api/state":
            return self.json(200, self.server.state())
        if route == "/api/feedback":
            events = []
            try:
                for line in (self.server.data / "feedback.jsonl").read_text(encoding="utf-8").splitlines():
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
            except OSError:
                pass
            return self.json(200, {"state": self.server.state(), "events": events})
        if route == "/api/jobs":
            with self.server.lock:
                jobs = [{"job_id": key, "theme_id": value["theme_id"], "status": "running" if value["process"].poll() is None else "finished" if value["process"].returncode == 0 else "failed"} for key, value in self.server.jobs.items()]
                if (self.server.data / ".manual-generation.lock").exists() and not any(job["status"] == "running" for job in jobs):
                    jobs.append({"job_id": "active-worker", "theme_id": None, "status": "running"})
            return self.json(200, {"jobs": jobs})
        if route in ASSETS:
            path = self.server.static / ASSETS[route]
        elif route.startswith("/images/"):
            relative = route[1:]
            allowed = {im["path"] for theme in self.server.manifest()["themes"] for im in theme["images"]}
            path = self.server.image_path(relative) if relative in allowed else None
        else:
            path = None
        if not path or not path.is_file():
            return self.json(404, {"error": "Not found."})
        self.send_bytes(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_POST(self):
        if not self.trusted(write=True):
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.json(415, {"error": "JSON required."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                return self.json(413, {"error": "Request too large or empty."})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.json(400, {"error": "Invalid JSON request."})
        route = urlsplit(self.path).path
        if route not in {"/api/feedback", "/api/regenerate"}:
            return self.json(404, {"error": "Not found."})
        theme_id, image_id = payload.get("theme_id"), payload.get("image_id")
        manifest = self.server.manifest()
        theme = next((item for item in manifest["themes"] if item["id"] == theme_id), None)
        if not theme or (image_id is not None and (not isinstance(image_id, str) or image_id not in {item["id"] for item in theme["images"]})):
            return self.json(400, {"error": "Unknown theme or painting."})
        notes = payload.get("notes", "")
        if not isinstance(notes, str) or len(notes) > MAX_NOTES:
            return self.json(400, {"error": "Notes must be at most 2,000 characters."})
        if "favourite" in payload and (not image_id or not isinstance(payload["favourite"], bool)):
            return self.json(400, {"error": "Favourite must be true or false for a painting."})
        with self.server.lock:
            event = {"type": "feedback" if route == "/api/feedback" else "regenerate", "theme_id": theme_id, "image_id": image_id, "created_at": now()}
            for key in ("notes", "favourite"):
                if key in payload:
                    event[key] = payload[key]
            if route == "/api/feedback":
                state = self.server.state()
                if payload.get("favourite") is True:
                    for candidate in theme["images"]:
                        previous = state.get(candidate["id"])
                        if candidate["id"] != image_id and isinstance(previous, dict):
                            previous["favourite"] = False
                key = image_id or theme_id
                entry = state.get(key, {})
                entry.update(event)
                state[key] = entry
                temporary = self.server.data / "state.json.tmp"
                temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.server.data / "state.json")
                self.server.record(event)
                return self.json(200, {"saved": True, "state": state})
            if not self.server.worker.is_file():
                return self.json(503, {"error": "Generation worker is not ready yet. Feedback can still be saved."})
            if (self.server.data / ".manual-generation.lock").exists() or any(job["process"].poll() is None for job in self.server.jobs.values()):
                return self.json(409, {"error": "A painting is already being created. Please wait for it to finish before creating another."})
            job_id = uuid.uuid4().hex
            job = {"job_id": job_id, "theme_id": theme_id, "image_id": image_id, "notes": notes, "created_at": now()}
            job_folder = self.server.data / "jobs"
            job_folder.mkdir(exist_ok=True)
            job_path = job_folder / (job_id + ".json")
            job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                command = [sys.executable, str(self.server.worker), "--job", str(job_path)]
                if self.server.collection == "landscape":
                    command.extend(["--collection", "landscape"])
                process = self.server.launcher(command, cwd=str(self.server.repo), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                return self.json(503, {"error": "The generation worker could not start. Please try again."})
            self.server.jobs[job_id] = {"theme_id": theme_id, "process": process}
            self.server.record({**event, "job_id": job_id})
            return self.json(202, {"job_id": job_id, "status": "queued"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--collection", choices=("portrait", "landscape"), default="portrait")
    args = parser.parse_args()
    server = GalleryServer(Path(__file__).resolve().parents[1], args.port, collection=args.collection)
    print(f"Nature gallery: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
