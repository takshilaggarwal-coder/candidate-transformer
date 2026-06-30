"""Optional recruiter keyword boost.

This module sits outside the merge engine. ``overall_confidence`` stays a pure
data-trust signal (used by the CLI, the gold snapshot, and the confidence
tests); keyword relevance is a separate question answered only at display time.

When the recruiter supplies no keywords, nothing here runs and the score and
ordering are whatever the engine produced. When they do, each candidate gets a
relevance fraction (how many keywords appear in their record), that fraction is
blended into the displayed score, and candidates are re-ranked keyword-first.

Matching runs against the full canonical record (skills plus free text), not
the projected output, so it behaves the same under any output config.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .canonical import CanonicalProfile
from .skills import canonicalize_skill, is_known_skill

# Weight given to keyword relevance when blending it with the engine's
# confidence into the single displayed score. At 0.6 relevance leads, but a
# well-corroborated profile still edges out a flakier one at the same match.
KEYWORD_WEIGHT = 0.6

_SEPARATORS = re.compile(r"[,\n;]+")
_WS = re.compile(r"\s+")


def parse_keywords(raw: Optional[str]) -> List[str]:
    """Split a free-text keyword box into clean, de-duplicated terms.

    Accepts commas, newlines, or semicolons as separators. De-dupe is
    case-insensitive and order-preserving. Empty / whitespace-only input
    returns ``[]`` (which callers treat as "feature off").
    """
    if not raw:
        return []
    out: List[str] = []
    seen = set()
    for part in _SEPARATORS.split(raw):
        term = _WS.sub(" ", part).strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _profile_text(profile: CanonicalProfile) -> str:
    """Everything a keyword may match against: skills + the free-text fields."""
    bits: List[str] = [s.name for s in profile.skills]
    if profile.headline:
        bits.append(profile.headline)
    for e in profile.experience:
        bits += [e.title or "", e.company or "", e.summary or ""]
    for ed in profile.education:
        bits += [ed.degree or "", ed.field or "", ed.institution or ""]
    loc = profile.location
    if loc:
        bits += [loc.city or "", loc.region or "", loc.country or ""]
    return " \n ".join(b for b in bits if b).lower()


def _keyword_hits(keyword: str, text_lc: str, skill_names_lc: set) -> bool:
    """True if ``keyword`` is present, either as a known skill the candidate has
    or as a bounded match anywhere in their text."""
    kw = _WS.sub(" ", keyword).strip().lower()
    if not kw:
        return False
    # Skill path: canonicalize so "k8s" matches a "Kubernetes" skill and "js" a
    # "JavaScript" skill, using the same alias table the merge uses.
    if is_known_skill(keyword):
        canon = canonicalize_skill(keyword)
        if canon and canon.lower() in skill_names_lc:
            return True
    # Text path: match the term bounded by non-alphanumerics, so "go" does not
    # fire on "google" yet symbol-bearing terms like "c++" still match.
    pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
    return re.search(pattern, text_lc) is not None


def keyword_match(profile: CanonicalProfile,
                  keywords: List[str]) -> Tuple[float, List[str]]:
    """Return ``(fraction_matched, matched_keywords)`` for one profile.

    ``fraction_matched`` is in ``[0, 1]``: the share of the recruiter's
    distinct keywords that appear in the candidate's record.
    """
    if not keywords:
        return 0.0, []
    text_lc = _profile_text(profile)
    skill_names_lc = {s.name.lower() for s in profile.skills}
    matched = [kw for kw in keywords if _keyword_hits(kw, text_lc, skill_names_lc)]
    return (len(matched) / len(keywords)), matched


def blend_score(base: Optional[float], match_fraction: float) -> Optional[float]:
    """Blend the engine's confidence with keyword relevance into one number.

    ``base`` is ``overall_confidence`` (may be ``None`` if the output config
    hides it). With ``match_fraction == 0`` the candidate's relevance drags the
    score down, so keyword matches rise and non-matches sink. Returns ``None``
    unchanged when ``base`` is ``None`` (no score to show).
    """
    if base is None:
        return None
    blended = KEYWORD_WEIGHT * match_fraction + (1.0 - KEYWORD_WEIGHT) * base
    return round(blended, 4)
