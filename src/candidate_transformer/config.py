"""Runtime output configuration (the "configurable output" twist).

A config reshapes the output without touching the engine. It can:
  * select a subset of fields,
  * rename / remap a field from a canonical path (the ``from`` key),
  * set per-field normalization (e.g. E164 for phones, canonical for skills),
  * toggle provenance and confidence,
  * choose what to do when a value is missing: null | omit | error.

These dataclasses are the parsed, validated form of the JSON the caller passes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Literal, Optional

OnMissing = Literal["null", "omit", "error"]
_VALID_TYPES = {"string", "number", "integer", "boolean",
                "string[]", "number[]", "object", "object[]", "any"}
_VALID_ON_MISSING = {"null", "omit", "error"}


@dataclass
class FieldSpec:
    path: str                              # output key (dotted paths allowed)
    source: Optional[str] = None           # canonical "from" path; default = path
    type: str = "any"
    required: bool = False
    normalize: Optional[str] = None        # E164 | canonical | lowercase | iso3166 | yyyy-mm
    on_missing: Optional[OnMissing] = None  # per-field override of global

    @property
    def from_path(self) -> str:
        return self.source or self.path


@dataclass
class OutputConfig:
    fields: List[FieldSpec] = field(default_factory=list)
    include_confidence: bool = True
    include_provenance: bool = True
    on_missing: OnMissing = "null"
    default_region: str = "US"             # used by phone normalization

    @staticmethod
    def from_dict(d: dict) -> "OutputConfig":
        if not isinstance(d, dict):
            raise ValueError("config must be a JSON object")
        on_missing = d.get("on_missing", "null")
        if on_missing not in _VALID_ON_MISSING:
            raise ValueError(f"on_missing must be one of {_VALID_ON_MISSING}, got {on_missing!r}")
        specs: List[FieldSpec] = []
        for raw in d.get("fields", []):
            if "path" not in raw:
                raise ValueError(f"field spec missing required 'path': {raw}")
            ftype = raw.get("type", "any")
            if ftype not in _VALID_TYPES:
                raise ValueError(f"field '{raw['path']}': unknown type {ftype!r}")
            fom = raw.get("on_missing")
            if fom is not None and fom not in _VALID_ON_MISSING:
                raise ValueError(f"field '{raw['path']}': bad on_missing {fom!r}")
            specs.append(FieldSpec(
                path=raw["path"],
                source=raw.get("from"),
                type=ftype,
                required=bool(raw.get("required", False)),
                normalize=raw.get("normalize"),
                on_missing=fom,
            ))
        return OutputConfig(
            fields=specs,
            include_confidence=bool(d.get("include_confidence", True)),
            include_provenance=bool(d.get("include_provenance", True)),
            on_missing=on_missing,
            default_region=d.get("default_region", "US"),
        )

    @staticmethod
    def load(path: str) -> "OutputConfig":
        with open(path, "r", encoding="utf-8") as fh:
            return OutputConfig.from_dict(json.load(fh))
