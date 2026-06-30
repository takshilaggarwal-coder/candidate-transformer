"""Recruiter notes adapter (unstructured source, free-text .txt).

Free text is the lowest-trust source. This adapter extracts only what
high-precision patterns can pull out (emails, phones, an explicit name label, a
"N years" phrase) plus skill mentions matched against the controlled
vocabulary. It does not parse employment history out of prose; that is the
resume adapter's job, and guessing it from notes would be low-precision.

A notes file may describe several candidates separated by blank-line blocks or
a "Candidate:"/"Re:" header; the adapter splits on those and emits one record
per block.
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..skills import is_known_skill, _CANONICAL_SKILLS  # reuse the vocabulary
from .base import RawCandidate, SourceAdapter

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone: optional +, then 7+ digits possibly grouped by spaces/dashes/parens.
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-]{6,}\d)(?!\w)")
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs|yr)\b", re.I)
_NAME_LABEL_RE = re.compile(r"^(?:candidate|name|re|subject)\s*[:\-]\s*(.+)$", re.I | re.M)

# Pre-build a list of (alias, canonical-mention) for whole-word scanning.
_SKILL_TOKENS = sorted(
    {alias for aliases in _CANONICAL_SKILLS.values() for alias in aliases},
    key=len, reverse=True,  # match longer aliases first ("node.js" before "node")
)


def _split_blocks(text: str) -> List[str]:
    """Split notes into per-candidate blocks. Prefer explicit headers; fall
    back to blank-line-separated paragraphs; else one block."""
    if _NAME_LABEL_RE.search(text):
        # split right before each label line
        parts = re.split(r"(?=^(?:candidate|name|re)\s*[:\-])", text, flags=re.I | re.M)
        return [p for p in parts if p.strip()]
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    return blocks or ([text] if text.strip() else [])


def _find_name(block: str) -> Optional[str]:
    m = _NAME_LABEL_RE.search(block)
    if m:
        # take the labelled value up to the first email/phone/newline
        raw = m.group(1).strip()
        raw = re.split(r"[<(,|]|\s—\s|\s-\s", raw)[0].strip()
        raw = _EMAIL_RE.sub("", raw).strip(" .,-")
        if raw:
            return raw
    return None


def _find_skills(block: str) -> List[str]:
    low = block.lower()
    found: List[str] = []
    for alias in _SKILL_TOKENS:
        # word-ish boundary that tolerates '.', '+', '#' inside the alias
        pat = r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
        if re.search(pat, low):
            found.append(alias)
    return found


class RecruiterNotesAdapter(SourceAdapter):
    name = "recruiter_notes"

    def extract(self, path: str) -> List[RawCandidate]:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        if not text.strip():
            return []

        out: List[RawCandidate] = []
        for block in _split_blocks(text):
            cand = RawCandidate(source=self.name)
            cand.full_name = _find_name(block)
            cand.emails = list(dict.fromkeys(_EMAIL_RE.findall(block)))
            # filter phone candidates that are obviously years or short ids
            phones = []
            for m in _PHONE_RE.findall(block):
                digits = re.sub(r"\D", "", m)
                if 7 <= len(digits) <= 15:
                    phones.append(m.strip())
            cand.phones = list(dict.fromkeys(phones))
            ym = _YEARS_RE.search(block)
            if ym:
                cand.years_experience = ym.group(1)
            cand.skills = _find_skills(block)

            # keep only blocks that identify someone or add signal
            if cand.full_name or cand.emails or cand.phones or cand.skills:
                out.append(cand)
        return out
