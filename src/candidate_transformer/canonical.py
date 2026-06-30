"""Canonical (internal) data model.

The merge stage always produces a complete ``CanonicalProfile``. Output
shaping is kept separate: ``projection.py`` is the only place that reshapes
this record for a caller. That split lets the same engine serve the default
schema and any runtime custom config without code changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Location:
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None  # ISO-3166 alpha-2, e.g. "US"


@dataclass
class Links:
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: List[str] = field(default_factory=list)


@dataclass
class Skill:
    name: str               # canonical skill name, e.g. "JavaScript"
    confidence: float       # 0..1
    sources: List[str] = field(default_factory=list)


@dataclass
class ExperienceItem:
    company: Optional[str] = None
    title: Optional[str] = None
    start: Optional[str] = None   # YYYY-MM
    end: Optional[str] = None     # YYYY-MM or None ("present")
    summary: Optional[str] = None


@dataclass
class EducationItem:
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


@dataclass
class ProvenanceEntry:
    field: str       # canonical field path, e.g. "emails" or "experience[0].company"
    source: str      # which source supplied the winning value
    method: str      # how it was obtained, e.g. "direct", "regex", "E164", "remapped"


@dataclass
class CanonicalProfile:
    candidate_id: str
    full_name: Optional[str] = None
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    location: Location = field(default_factory=Location)
    links: Links = field(default_factory=Links)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[Skill] = field(default_factory=list)
    experience: List[ExperienceItem] = field(default_factory=list)
    education: List[EducationItem] = field(default_factory=list)
    provenance: List[ProvenanceEntry] = field(default_factory=list)
    overall_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Plain-dict view of the full canonical record (default schema)."""
        return asdict(self)
