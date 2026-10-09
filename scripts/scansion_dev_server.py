"""Local preview of the scanner pages (worktree only; never deployed).

    python scripts/scansion_dev_server.py            # http://127.0.0.1:8790/scan.html and /rules.html

Serves backend/scansion/api.py (POST /api/scan, GET /api/scan/rules, rule validation and saving)
and the two prototype pages from the worktree root. Saving the rules file is enabled here only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MELOS_SCANSION_DEV", "1")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402

from backend.scansion.api import router  # noqa: E402

app = FastAPI(title="Melos scanner (local preview)")
app.include_router(router)


@app.get("/")
def index():
    return RedirectResponse("/scan.html")


@app.get("/{page}.html")
def page(page: str):
    if page not in ("scan", "rules"):
        return RedirectResponse("/scan.html")
    return FileResponse(ROOT / f"{page}.html", media_type="text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8790"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
