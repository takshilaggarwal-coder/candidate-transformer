"""Source adapter registry + lightweight type detection.

Adding a new source (e.g. GitHub or LinkedIn) is a two-line change: implement a
``SourceAdapter`` and register it here. The merge/normalize/projection stages
never need to know which sources exist.
"""
from __future__ import annotations

import os
from typing import Dict, Optional, Type

from .base import RawCandidate, SourceAdapter, safe_extract
from .ats_json import ATSJsonAdapter
from .recruiter_csv import RecruiterCSVAdapter
from .recruiter_notes import RecruiterNotesAdapter
from .resume import ResumeAdapter

# explicit source-type name -> adapter class
ADAPTERS: Dict[str, Type[SourceAdapter]] = {
    "recruiter_csv": RecruiterCSVAdapter,
    "ats_json": ATSJsonAdapter,
    "resume": ResumeAdapter,
    "recruiter_notes": RecruiterNotesAdapter,
}


def get_adapter(source_type: str) -> SourceAdapter:
    if source_type not in ADAPTERS:
        raise KeyError(f"unknown source type '{source_type}'. "
                       f"known: {sorted(ADAPTERS)}")
    return ADAPTERS[source_type]()


def detect_source_type(path: str) -> Optional[str]:
    """Guess the source type from filename/extension when not given explicitly.

    Detection is best-effort and overridable on the CLI (``--source type=path``).
    """
    base = os.path.basename(path).lower()
    ext = os.path.splitext(base)[1]
    if ext == ".csv":
        return "recruiter_csv"
    if ext == ".json":
        return "ats_json"
    if ext in (".pdf", ".docx", ".doc"):
        return "resume"
    if ext == ".txt":
        # disambiguate notes vs a plain-text resume by filename hint
        if "resume" in base or "cv" in base:
            return "resume"
        return "recruiter_notes"
    return None


__all__ = [
    "ADAPTERS", "get_adapter", "detect_source_type",
    "safe_extract", "RawCandidate", "SourceAdapter",
    "RecruiterCSVAdapter", "ATSJsonAdapter", "ResumeAdapter", "RecruiterNotesAdapter",
]
