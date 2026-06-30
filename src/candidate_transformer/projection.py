"""Projection layer: canonical record -> caller-requested shape.

This is the ONLY place that knows about the runtime config. It reads values out
of the canonical profile by path, optionally re-normalizes them, renames them to
the requested output key, and applies the missing-value policy. It never invents
data and never mutates the canonical record.

Supported ``from`` path grammar (dot-separated tokens, each optionally suffixed):
    name            -> dict key
    name[0]         -> list index
    name[]          -> wildcard: map the rest of the path over every list item
e.g. ``emails[0]``, ``skills[].name``, ``location.country``, ``experience[0].company``.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional

from .canonical import CanonicalProfile
from .config import FieldSpec, OutputConfig
from .normalize import (normalize_country, normalize_month, normalize_phone)
from .skills import canonicalize_skill

_TOKEN_RE = re.compile(r"^([A-Za-z_][\w]*)?(\[(\d*)\])?$")


class ProjectionError(Exception):
    """Raised when on_missing='error' and a value is absent."""


# --------------------------------------------------------------------------- #
# Path resolution
# --------------------------------------------------------------------------- #
def resolve_path(obj: Any, path: str) -> Any:
    """Resolve a canonical path against a plain dict/list structure."""
    return _resolve(obj, [t for t in path.split(".") if t != ""])


def _resolve(obj: Any, tokens: List[str]) -> Any:
    if obj is None:
        return None
    if not tokens:
        return obj
    m = _TOKEN_RE.match(tokens[0])
    if not m:
        return None
    name, bracket, idx = m.group(1), m.group(2), m.group(3)
    rest = tokens[1:]

    val = obj.get(name) if (name and isinstance(obj, dict)) else (obj if not name else None)
    if bracket is None:
        return _resolve(val, rest)
    if not isinstance(val, list):
        return None
    if idx == "":  # wildcard: map remainder over the list, dropping Nones
        mapped = [_resolve(el, rest) for el in val]
        return [x for x in mapped if x is not None]
    i = int(idx)
    return _resolve(val[i], rest) if 0 <= i < len(val) else None


# --------------------------------------------------------------------------- #
# Normalization hook (per-field "normalize" in the config)
# --------------------------------------------------------------------------- #
def _apply_normalize(value: Any, kind: Optional[str], region: str) -> Any:
    if kind is None or value is None:
        return value
    if isinstance(value, list):
        return [_apply_normalize(v, kind, region) for v in value]
    k = kind.lower()
    if k == "e164":
        return normalize_phone(str(value), region)
    if k == "canonical":
        return canonicalize_skill(str(value))
    if k in ("iso3166", "iso-3166"):
        return normalize_country(str(value))
    if k in ("yyyy-mm", "yyyymm", "month"):
        return normalize_month(str(value))
    if k == "lowercase":
        return str(value).lower()
    if k == "uppercase":
        return str(value).upper()
    return value  # unknown normalize kind: leave value untouched (don't guess)


# --------------------------------------------------------------------------- #
# Output assembly
# --------------------------------------------------------------------------- #
def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _set_nested(out: dict, dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    node = out
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value


def _head(path: str) -> str:
    """First token of a path/provenance label, e.g. 'skills:Python' -> 'skills'."""
    return re.split(r"[.\[:]", path, maxsplit=1)[0]


def _strip_confidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_confidence(v) for k, v in value.items()
                if k not in ("confidence", "overall_confidence")}
    if isinstance(value, list):
        return [_strip_confidence(v) for v in value]
    return value


def project(profile: CanonicalProfile, config: OutputConfig) -> dict:
    """Apply ``config`` to ``profile`` and return the projected dict."""
    src = profile.to_dict()
    out: dict = {}
    projected_heads = set()

    for spec in config.fields:  # type: FieldSpec
        value = resolve_path(src, spec.from_path)
        value = _apply_normalize(value, spec.normalize, config.default_region)

        if _is_missing(value):
            policy = spec.on_missing or config.on_missing
            if policy == "error":
                raise ProjectionError(
                    f"required value missing for output field '{spec.path}' "
                    f"(from '{spec.from_path}')")
            if policy == "omit":
                continue
            value = None  # policy == "null"

        _set_nested(out, spec.path, value)
        projected_heads.add(_head(spec.from_path))

    # confidence toggle
    if config.include_confidence:
        out.setdefault("overall_confidence", profile.overall_confidence)
    else:
        out = _strip_confidence(out)

    # provenance toggle (filtered to the fields actually projected)
    if config.include_provenance:
        prov = [
            {"field": p.field, "source": p.source, "method": p.method}
            for p in profile.provenance
            if (not config.fields) or _head(p.field) in projected_heads
        ]
        out["provenance"] = prov

    return out
