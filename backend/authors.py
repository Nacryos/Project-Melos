"""Exact, audited author-identity lookups for corpus labels.

This module only resolves source-linked aliases in the accepted P2 profile.
Literary dialect claims in that profile are context for a reader, not labels
for individual tokens, forms, passages, or poem composition dates.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES = ROOT / "data/metadata/p2-author-profiles.json"
DEFAULT_CLAIMS = ROOT / "data/claims/p2_authors.jsonl"
DEFAULT_ACCEPTANCE = ROOT / "data/reports/p2-claim-acceptance.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accepted(profile_path: Path, claim_path: Path, acceptance_path: Path) -> bool:
    if not all(path.exists() for path in (profile_path, claim_path, acceptance_path)):
        return False
    try:
        files = json.loads(acceptance_path.read_text(encoding="utf-8"))["files"]
        claim = files[claim_path.name]
        profile = files[profile_path.name]
        return (claim.get("verdict") == "PASS" and claim.get("sha256") == _digest(claim_path)
                and profile.get("verdict") == "PASS" and profile.get("sha256") == _digest(profile_path))
    except (KeyError, TypeError, ValueError, OSError):
        return False


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


@lru_cache(maxsize=16)
def _load_checked(profile_path: str, claim_path: str, acceptance_path: str,
                  signatures: tuple[tuple[int, int] | None, ...]) -> tuple[dict, ...]:
    profile = Path(profile_path)
    claim = Path(claim_path)
    acceptance = Path(acceptance_path)
    if not _accepted(profile, claim, acceptance):
        return ()
    payload = json.loads(profile.read_text(encoding="utf-8"))
    return tuple(payload["profiles"])


def load_profiles(*, path: Path | None = None, claim_path: Path | None = None,
                  acceptance_path: Path | None = None) -> list[dict]:
    """Return profiles only when both current files match independent audit hashes.

    Path overrides permit isolated tests or alternate accepted corpora without
    consulting the global Melos dataset.
    """
    path = Path(path) if path is not None else DEFAULT_PROFILES
    claim_path = Path(claim_path) if claim_path is not None else DEFAULT_CLAIMS
    acceptance_path = Path(acceptance_path) if acceptance_path is not None else DEFAULT_ACCEPTANCE
    paths = (path, claim_path, acceptance_path)
    signatures = tuple(_signature(item) for item in paths)
    return deepcopy(list(_load_checked(*(str(item.resolve()) for item in paths), signatures)))


def _key(label: str) -> str:
    return unicodedata.normalize("NFC", label).casefold()


def lookup_author(author: str, *, path: Path | None = None,
                  claim_path: Path | None = None,
                  acceptance_path: Path | None = None) -> dict | None:
    """Resolve an exact source-attested label; abstain on collisions or mixtures."""
    if not isinstance(author, str) or not author.strip() or "/" in author:
        return None
    key = _key(author)
    owners = [profile for profile in load_profiles(path=path, claim_path=claim_path,
                                                   acceptance_path=acceptance_path)
              if any(_key(alias["label"]) == key for alias in profile["aliases"])]
    return owners[0] if len(owners) == 1 else None


def equivalent_labels(author: str, *, path: Path | None = None,
                      claim_path: Path | None = None,
                      acceptance_path: Path | None = None) -> list[str]:
    """Return the profile's exact source-backed aliases, preserving source spelling."""
    profile = lookup_author(author, path=path, claim_path=claim_path,
                            acceptance_path=acceptance_path)
    if profile is None:
        return []
    return list(dict.fromkeys(alias["label"] for alias in profile["aliases"]))
