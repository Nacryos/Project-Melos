"""Build the separate Wiktionary SQLite reference index after independent audit.

Run: python -m scripts.build_wiktionary_index
"""

from __future__ import annotations

import json

from backend.wiktionary import build_index


if __name__ == "__main__":
    print(json.dumps(build_index(), ensure_ascii=False))
