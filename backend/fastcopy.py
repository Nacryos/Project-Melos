"""Release U: a deep copy for the JSON-like trees of the analysis pipeline (dicts, lists, tuples, sets of
strings and numbers). copy.deepcopy keeps a memo of every object and dispatches by type for each node, which
made it the largest single cost of passage and draft analysis (about 1.1 million calls for one stanza).
This copies dict, list, tuple and set containers recursively and shares every other value; the analysis
data hold no other mutable objects. Shared references inside one tree become separate copies (as the JSON
response would show them anyway)."""
from __future__ import annotations

from typing import Any


def deepcopy(value: Any, _memo: Any = None) -> Any:
    kind = type(value)
    if kind is dict:
        return {k: deepcopy(v) for k, v in value.items()}
    if kind is list:
        return [deepcopy(v) for v in value]
    if kind is tuple:
        return tuple(deepcopy(v) for v in value)
    if kind is set:
        return {deepcopy(v) for v in value}
    if isinstance(value, dict):  # an OrderedDict or defaultdict keeps its type
        import copy
        return copy.deepcopy(value)
    return value


__all__ = ["deepcopy"]
