"""Source adapter framework.

Every source (CSV, ATS JSON, resume, recruiter notes, and any future one such
as GitHub or LinkedIn) implements the same contract: read its raw input and
emit zero or more :class:`RawCandidate` records. A ``RawCandidate`` is an
un-normalized bag of strings tagged with the source it came from. Normalization
happens later in a single place, so the rules stay consistent regardless of
which source a value came from.

A broken source must not crash the run. Adapters may raise; :func:`safe_extract`
is the boundary that catches the error, logs it, and treats the source as
having contributed nothing.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("candidate_transformer.sources")


@dataclass
class RawExperience:
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class RawEducation:
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[str] = None


@dataclass
class RawCandidate:
    """Un-normalized, per-source view of one person."""
    source: str
    full_name: Optional[str] = None
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    # location may arrive as free text or pre-split fields
    location_text: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country_text: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other_links: List[str] = field(default_factory=list)
    headline: Optional[str] = None
    years_experience: Optional[Any] = None
    skills: List[str] = field(default_factory=list)
    experience: List[RawExperience] = field(default_factory=list)
    education: List[RawEducation] = field(default_factory=list)


class SourceAdapter(ABC):
    """Base class. ``name`` is the provenance label and the trust-table key."""

    name: str = "base"

    @abstractmethod
    def extract(self, path: str) -> List[RawCandidate]:
        """Parse ``path`` and return raw candidates. May raise; the caller
        wraps this in :func:`safe_extract`."""
        raise NotImplementedError


def safe_extract(adapter: SourceAdapter, path: str) -> List[RawCandidate]:
    """Run an adapter, swallowing and logging any failure.

    A missing or garbage source yields an empty list instead of aborting the
    pipeline.
    """
    try:
        records = adapter.extract(path)
    except FileNotFoundError:
        logger.warning("source '%s': file not found: %s", adapter.name, path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("source '%s' failed on %s: %s", adapter.name, path, exc)
        return []
    # tag/repair the source label defensively
    for r in records:
        if not r.source:
            r.source = adapter.name
    logger.info("source '%s': extracted %d candidate record(s)", adapter.name, len(records))
    return records
