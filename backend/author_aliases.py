"""Owner-curated author label merging.

Collectors keep the exact author label their source gives them: ``Alcaeus``,
``Alcaeus of Mytilene``, ``alcaeus-lyric`` and ``Αλκαίος`` all denote one poet
but were counted and filtered as four. This module maps such labels onto one
canonical display name so the author chooser, author filter, coverage report
and mirror grouping treat them as one author. Every record keeps its original
label; merging is presentation and retrieval policy, never a change to source
data.

Labels that join several poets with ``" / "`` (for example ``Sappho / Alcaeus``)
are never merged into one author. They match a filter for any of their parts.

The table lives beside this module as ``backend/author_aliases.json`` so it ships
with the API package (the deployment mounts its own ``data/``). Adding a label
there is the only step needed to merge a new spelling; the corpus must then be rebuilt so
the ``author_canonical`` column and ``passage_authors`` table pick it up.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TABLE = ROOT / "backend/author_aliases.json"
MIXED_SEPARATOR = " / "
_SPACES = re.compile(r"[\s_\-]+")


def fold(label: str) -> str:
    """Lossy comparison key: case, diacritics, sigma forms and separators folded."""
    text = unicodedata.normalize("NFD", str(label or "")).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("ς", "σ").replace("ϲ", "σ")
    return _SPACES.sub(" ", text).strip()


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


@lru_cache(maxsize=4)
def _load(path: str, signature: tuple[int, int] | None) -> tuple[dict[str, dict], dict[str, dict]]:
    table = Path(path)
    if signature is None:
        return {}, {}
    payload = json.loads(table.read_text(encoding="utf-8"))
    by_fold: dict[str, dict] = {}
    by_canonical: dict[str, dict] = {}
    for entry in payload.get("authors", []):
        canonical = str(entry["canonical"]).strip()
        record = {"canonical": canonical, "greek": entry.get("greek"),
                  "labels": list(dict.fromkeys([canonical, *entry.get("labels", [])])),
                  "sources": list(entry.get("sources", []))}
        by_canonical[fold(canonical)] = record
        for label in record["labels"]:
            key = fold(label)
            if key and key in by_fold and by_fold[key]["canonical"] != canonical:
                raise ValueError(f"Alias {label!r} is claimed by both {by_fold[key]['canonical']} and {canonical}")
            if key:
                by_fold[key] = record
    return by_fold, by_canonical


def table(path: Path | None = None) -> tuple[dict[str, dict], dict[str, dict]]:
    path = Path(path) if path is not None else DEFAULT_TABLE
    return _load(str(path.resolve()), _signature(path))


def is_mixed(label: str) -> bool:
    return MIXED_SEPARATOR in str(label or "")


def profile(label: str, path: Path | None = None) -> dict | None:
    """The alias record for a single-author label, or None when unmerged."""
    if not label or is_mixed(label):
        return None
    return table(path)[0].get(fold(label))


def canonical(label: str, path: Path | None = None) -> str:
    """Canonical display name; a mixed or unknown label is returned unchanged."""
    text = str(label or "").strip()
    record = profile(text, path)
    return record["canonical"] if record else text


def canonical_key(label: str, path: Path | None = None) -> str:
    """Folded key of the canonical name; identical for every merged spelling."""
    return fold(canonical(label, path))


def component_keys(label: str, path: Path | None = None) -> list[str]:
    """Keys a record with this label should answer to in an author filter.

    A single-author label yields its canonical key. A mixed label yields its own
    key plus the canonical key of each named part, so the record appears when
    any of its poets is selected while staying visibly a joint attribution.
    """
    text = str(label or "").strip()
    if not text:
        return []
    keys = [fold(text)]
    if is_mixed(text):
        for part in text.split(MIXED_SEPARATOR):
            key = canonical_key(part, path)
            if key and key not in keys:
                keys.append(key)
    else:
        key = canonical_key(text, path)
        if key not in keys:
            keys.insert(0, key)
    return keys


def merged_labels(label: str, path: Path | None = None) -> list[str]:
    """All spellings merged with this label, canonical first."""
    record = profile(label, path)
    if record is None:
        return [str(label or "").strip()] if str(label or "").strip() else []
    return list(record["labels"])


def canonical_names(path: Path | None = None) -> list[str]:
    return [record["canonical"] for record in table(path)[1].values()]
