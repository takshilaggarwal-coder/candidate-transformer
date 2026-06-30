"""Pipeline orchestration.

    detect -> extract -> normalize -> merge -> confidence -> project -> validate

Each stage lives in its own module; this file wires them together and is the
programmatic entry point used by both the CLI and the web UI.

Extraction failures are isolated per source (see ``safe_extract``), and
per-candidate projection/validation failures are captured as warnings so one
bad record does not fail the whole batch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .canonical import CanonicalProfile
from .config import OutputConfig
from .merge import build_profiles
from .projection import project
from .sources import detect_source_type, get_adapter, safe_extract
from .sources.base import RawCandidate
from .validation import (validate_against_config, validate_default,
                         validate_or_raise)


@dataclass
class SourceSpec:
    path: str
    type: Optional[str] = None  # None => auto-detect from extension/name


@dataclass
class PipelineResult:
    outputs: List[dict]                 # projected (or default) dicts, validated
    profiles: List[CanonicalProfile]    # internal canonical records (for debugging)
    warnings: List[str]
    # The canonical record behind each emitted output, 1:1 with ``outputs``
    # (``profiles`` may be longer when a record fails projection/validation).
    # Lets callers reach the full record for an output regardless of config.
    output_profiles: List[CanonicalProfile] = field(default_factory=list)


def _extract_all(sources: List[SourceSpec]) -> Tuple[List[RawCandidate], List[str]]:
    raws: List[RawCandidate] = []
    warnings: List[str] = []
    for spec in sources:
        stype = spec.type or detect_source_type(spec.path)
        if not stype:
            warnings.append(f"could not detect source type for '{spec.path}' (skipped)")
            continue
        try:
            adapter = get_adapter(stype)
        except KeyError as exc:
            warnings.append(str(exc))
            continue
        records = safe_extract(adapter, spec.path)
        if not records:
            warnings.append(f"source '{stype}' ({spec.path}) contributed no records")
        raws.extend(records)
    return raws, warnings


def run(sources: List[SourceSpec],
        config: Optional[OutputConfig] = None,
        validate: bool = True) -> PipelineResult:
    """Run the full pipeline over ``sources``.

    If ``config`` is None the output is the full default canonical schema;
    otherwise the canonical profile is projected through the config. Output is
    validated unless ``validate=False``.
    """
    default_region = config.default_region if config else "US"

    raws, warnings = _extract_all(sources)
    profiles = build_profiles(raws, default_region=default_region)

    outputs: List[dict] = []
    output_profiles: List[CanonicalProfile] = []
    for profile in profiles:
        try:
            if config is None:
                out = profile.to_dict()
                if validate:
                    validate_or_raise(validate_default(out))
            else:
                out = project(profile, config)
                if validate:
                    validate_or_raise(validate_against_config(out, config))
            outputs.append(out)
            output_profiles.append(profile)  # keep 1:1 with outputs
        except Exception as exc:  # noqa: BLE001
            # Record the problem and keep going. The caller (CLI/web) decides
            # how to surface warnings, so we don't log here as well and emit
            # the same failure twice.
            warnings.append(f"candidate '{profile.candidate_id}' failed "
                            f"projection/validation: {exc}")

    return PipelineResult(outputs=outputs, profiles=profiles, warnings=warnings,
                          output_profiles=output_profiles)
