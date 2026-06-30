"""ATS JSON blob adapter (STRUCTURED source).

The ATS uses its *own* field names that do not match our canonical schema
(e.g. ``applicant_name``, ``contact.mobileNumber``, ``employmentHistory``).
The whole job of this adapter is the remap from their vocabulary to ours.

We accept three container shapes so the adapter is robust to real exports:
  * a bare list of applicant objects
  * ``{"candidates": [...]}`` / ``{"applicants": [...]}`` / ``{"results": [...]}``
  * a single applicant object
Unknown keys are ignored; missing keys degrade to empty, never crash.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import RawCandidate, RawEducation, RawExperience, SourceAdapter


def _get(d: Dict[str, Any], *keys, default=None):
    """First present, non-empty value among several possible ATS key spellings."""
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return default


def _as_list(d: Dict[str, Any], *keys) -> list:
    val = _get(d, *keys, default=[])
    if isinstance(val, list):
        return val
    if isinstance(val, (str, dict)):
        return [val]
    return []


class ATSJsonAdapter(SourceAdapter):
    name = "ats_json"

    def extract(self, path: str) -> List[RawCandidate]:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        applicants = self._unwrap(data)
        return [self._map_one(a) for a in applicants if isinstance(a, dict)]

    @staticmethod
    def _unwrap(data: Any) -> List[Any]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("candidates", "applicants", "results", "data", "records"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]  # single applicant object
        return []

    def _map_one(self, a: Dict[str, Any]) -> RawCandidate:
        cand = RawCandidate(source=self.name)

        # --- identity / contact (their names -> ours) ---
        cand.full_name = _get(a, "applicant_name", "fullName", "name", "candidateName")

        contact = _get(a, "contact", "contactInfo", default={}) or {}
        emails = [
            _get(contact, "primaryEmail", "email"),
            _get(contact, "altEmail", "secondaryEmail"),
            _get(a, "email"),
        ]
        cand.emails = [e for e in emails if e]
        phones = [_get(contact, "mobileNumber", "phone", "mobile"), _get(a, "phone")]
        cand.phones = [p for p in phones if p]

        # --- location ---
        addr = _get(a, "addr", "address", "location", default={}) or {}
        if isinstance(addr, dict):
            cand.city = _get(addr, "town", "city")
            cand.region = _get(addr, "state", "region", "province")
            cand.country_text = _get(addr, "nation", "country", "countryCode")
        elif isinstance(addr, str):
            cand.location_text = addr

        # --- links ---
        social = _get(a, "social", "links", "socialProfiles", default={}) or {}
        cand.linkedin = _get(social, "linkedinUrl", "linkedin")
        gh = _get(social, "githubUrl", "github", "githubHandle")
        if gh:
            cand.github = gh if str(gh).startswith("http") else f"https://github.com/{gh}"
        cand.portfolio = _get(social, "website", "portfolio", "blog")

        # --- headline / years ---
        cand.headline = _get(a, "headline", "summary", "professionalSummary")
        cand.years_experience = _get(a, "totalExperienceYears", "yearsOfExperience", "experienceYears")

        # --- skills ---
        skills = _as_list(a, "skillSet", "skills", "keySkills")
        cand.skills = [str(s) for s in skills if s]

        # --- employment history -> experience ---
        for job in _as_list(a, "employmentHistory", "experience", "workHistory"):
            if not isinstance(job, dict):
                continue
            cand.experience.append(RawExperience(
                company=_get(job, "employer", "company", "organisation", "organization"),
                title=_get(job, "designation", "role", "title", "jobTitle"),
                start=_get(job, "from", "startDate", "since", "start"),
                end=_get(job, "to", "endDate", "until", "end"),
                summary=_get(job, "description", "summary", "responsibilities"),
            ))

        # --- academics -> education ---
        for edu in _as_list(a, "academics", "education", "educationHistory"):
            if not isinstance(edu, dict):
                continue
            cand.education.append(RawEducation(
                institution=_get(edu, "school", "institution", "university", "college"),
                degree=_get(edu, "qualification", "degree"),
                field=_get(edu, "specialization", "field", "major", "fieldOfStudy"),
                end_year=_get(edu, "yearOfPassing", "endYear", "graduationYear", "year"),
            ))

        return cand
