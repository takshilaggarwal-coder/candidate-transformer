"""Recruiter CSV export adapter (STRUCTURED source).

Expected-ish columns: name, email, phone, current_company, title.
We tolerate header aliases, extra columns, blank cells, and rows that are
entirely empty. Each non-empty row becomes one RawCandidate; the recruiter's
"current_company/title" becomes a single (current) experience entry with an
open end date.
"""
from __future__ import annotations

import csv
from typing import Dict, List, Optional

from .base import RawCandidate, RawExperience, SourceAdapter

# Map many possible header spellings onto our internal keys.
_HEADER_ALIASES = {
    "name": "name", "full name": "name", "candidate": "name", "candidate name": "name",
    "email": "email", "e-mail": "email", "email address": "email",
    "phone": "phone", "phone number": "phone", "mobile": "phone", "contact": "phone",
    "current_company": "company", "current company": "company", "company": "company",
    "employer": "company", "organization": "company",
    "title": "title", "job title": "title", "role": "title", "position": "title",
    "location": "location", "city": "location",
}


def _norm_header(h: str) -> Optional[str]:
    if h is None:
        return None
    return _HEADER_ALIASES.get(h.strip().lower())


class RecruiterCSVAdapter(SourceAdapter):
    name = "recruiter_csv"

    def extract(self, path: str) -> List[RawCandidate]:
        out: List[RawCandidate] = []
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return []  # empty file
            colmap: Dict[int, str] = {}
            for i, h in enumerate(header):
                key = _norm_header(h)
                if key:
                    colmap[i] = key

            for row in reader:
                if not any(cell.strip() for cell in row if cell):
                    continue  # skip fully blank rows
                rec: Dict[str, str] = {}
                for i, cell in enumerate(row):
                    key = colmap.get(i)
                    if key and cell and cell.strip():
                        # if a logical column appears twice keep the first value
                        rec.setdefault(key, cell.strip())

                cand = RawCandidate(source=self.name)
                cand.full_name = rec.get("name")
                if rec.get("email"):
                    cand.emails = [rec["email"]]
                if rec.get("phone"):
                    cand.phones = [rec["phone"]]
                cand.location_text = rec.get("location")
                company, title = rec.get("company"), rec.get("title")
                if company or title:
                    cand.experience = [RawExperience(company=company, title=title, end="present")]
                    # a recruiter's "title" doubles as a reasonable headline hint
                    cand.headline = title
                # Only keep the row if it carries at least one identifying signal.
                if cand.full_name or cand.emails or cand.phones:
                    out.append(cand)
        return out
