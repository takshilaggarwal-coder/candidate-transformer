"""Normalize + identity-resolve + merge raw source records into canonical profiles.

Three stages live here:

1. ``normalize_candidate`` turns one raw, per-source record into a normalized
   per-source view, recording *how* each value was obtained (provenance method).
2. ``_group_by_identity`` clusters per-source views that refer to the same
   person, using a union-find over strong keys (email, phone) and a weak key
   (name + company/country).
3. ``merge_group`` resolves each canonical field across the cluster:
   - winner = value with the highest combined confidence,
   - confidence = noisy-OR over the trust weights of the sources that agree,
   - provenance records the winning source(s) and method.

The confidence formula is noisy-OR, ``1 - Π(1 - wᵢ)``. Independent sources
agreeing on a value raise confidence without exceeding 1.0, while a lone
low-trust source stays low.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .canonical import (CanonicalProfile, EducationItem, ExperienceItem, Links,
                        Location, ProvenanceEntry, Skill)
from .normalize import (classify_link, name_match_key, normalize_country,
                        normalize_email, normalize_month, normalize_name,
                        normalize_phone, normalize_url, normalize_year,
                        normalize_years_experience)
from .skills import canonicalize_skill
from .sources.base import RawCandidate

# --------------------------------------------------------------------------- #
# Trust model (the tunable numbers in the system)
# --------------------------------------------------------------------------- #
SOURCE_TRUST: Dict[str, float] = {
    "recruiter_csv": 0.90,
    "ats_json": 0.85,
    "resume": 0.80,
    "recruiter_notes": 0.50,
}
# deterministic tie-break order (lower wins ties)
SOURCE_PRIORITY: Dict[str, int] = {
    "recruiter_csv": 0, "ats_json": 1, "resume": 2, "recruiter_notes": 3,
}
# per-(field,source) trust multiplier; default 1.0. Encodes "who is authoritative
# for what": resumes win on experience/skills, structured sources win on contact.
FIELD_TRUST: Dict[str, Dict[str, float]] = {
    "full_name":        {"recruiter_csv": 1.0, "ats_json": 1.0, "resume": 0.95, "recruiter_notes": 0.8},
    "emails":           {"recruiter_csv": 1.0, "ats_json": 1.0, "resume": 0.95, "recruiter_notes": 0.7},
    "phones":           {"recruiter_csv": 1.0, "ats_json": 1.0, "resume": 0.95, "recruiter_notes": 0.7},
    "location":         {"recruiter_csv": 0.95, "ats_json": 0.95, "resume": 0.9, "recruiter_notes": 0.5},
    "links":            {"recruiter_csv": 0.5, "ats_json": 1.0, "resume": 1.0, "recruiter_notes": 0.4},
    "headline":         {"recruiter_csv": 0.7, "ats_json": 0.95, "resume": 0.9, "recruiter_notes": 0.5},
    "years_experience": {"recruiter_csv": 0.4, "ats_json": 0.95, "resume": 0.9, "recruiter_notes": 0.6},
    "skills":           {"recruiter_csv": 0.5, "ats_json": 0.90, "resume": 1.0, "recruiter_notes": 0.7},
    "experience":       {"recruiter_csv": 0.6, "ats_json": 0.90, "resume": 1.0, "recruiter_notes": 0.3},
    "education":        {"recruiter_csv": 0.2, "ats_json": 0.90, "resume": 1.0, "recruiter_notes": 0.3},
}
DEFAULT_TRUST = 0.5


def field_weight(source: str, fieldname: str) -> float:
    base = SOURCE_TRUST.get(source, DEFAULT_TRUST)
    mult = FIELD_TRUST.get(fieldname, {}).get(source, 1.0)
    return round(base * mult, 6)


def method_for(source: str, normalization: Optional[str] = None) -> str:
    base = {"recruiter_csv": "direct", "ats_json": "remapped"}.get(source, "extracted")
    return f"{base}+{normalization}" if normalization else base


def noisy_or(weights: List[float]) -> float:
    prod = 1.0
    for w in weights:
        prod *= (1.0 - max(0.0, min(1.0, w)))
    return round(1.0 - prod, 4)


# --------------------------------------------------------------------------- #
# Stage 1: per-source normalization
# --------------------------------------------------------------------------- #
@dataclass
class NormalizedCandidate:
    source: str
    full_name: Optional[str] = None
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other_links: List[str] = field(default_factory=list)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: List[str] = field(default_factory=list)
    experience: List[ExperienceItem] = field(default_factory=list)
    education: List[EducationItem] = field(default_factory=list)


def normalize_candidate(raw: RawCandidate, default_region: str = "US") -> NormalizedCandidate:
    nc = NormalizedCandidate(source=raw.source)
    nc.full_name = normalize_name(raw.full_name)

    nc.emails = _dedupe([normalize_email(e) for e in raw.emails])

    # phone region: prefer the candidate's own country if we can read it
    region = normalize_country(raw.country_text) or default_region
    nc.phones = _dedupe([normalize_phone(p, region) for p in raw.phones])

    if raw.city or raw.region or raw.country_text:
        nc.city = (raw.city or "").strip() or None
        nc.region = (raw.region or "").strip() or None
        nc.country = normalize_country(raw.country_text)
    elif raw.location_text:
        from .normalize import parse_location
        nc.city, nc.region, nc.country = parse_location(raw.location_text)

    nc.linkedin = normalize_url(raw.linkedin) if raw.linkedin else None
    nc.github = normalize_url(raw.github) if raw.github else None
    nc.portfolio = normalize_url(raw.portfolio) if raw.portfolio else None
    for link in raw.other_links:
        u = normalize_url(link)
        if u:
            kind = classify_link(u)
            if kind == "linkedin" and not nc.linkedin:
                nc.linkedin = u
            elif kind == "github" and not nc.github:
                nc.github = u
            else:
                nc.other_links.append(u)

    nc.headline = (raw.headline or "").strip() or None
    nc.years_experience = normalize_years_experience(raw.years_experience)

    seen = set()
    for s in raw.skills:
        canon = canonicalize_skill(s)
        if canon and canon.lower() not in seen:
            seen.add(canon.lower())
            nc.skills.append(canon)

    for e in raw.experience:
        company = (e.company or "").strip() or None
        title = (e.title or "").strip() or None
        if not (company or title):
            continue
        nc.experience.append(ExperienceItem(
            company=company, title=title,
            start=normalize_month(e.start), end=normalize_month(e.end),
            summary=(e.summary or "").strip() or None,
        ))

    for ed in raw.education:
        inst = (ed.institution or "").strip() or None
        deg = (ed.degree or "").strip() or None
        fld = (ed.field or "").strip() or None
        if not (inst or deg or fld):
            continue
        nc.education.append(EducationItem(
            institution=inst, degree=deg, field=fld,
            end_year=normalize_year(ed.end_year),
        ))
    return nc


def _dedupe(values: List[Optional[str]]) -> List[str]:
    out, seen = [], set()
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


# --------------------------------------------------------------------------- #
# Stage 2: identity resolution (union-find)
# --------------------------------------------------------------------------- #
class _DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)  # deterministic root


def _weak_key(nc: NormalizedCandidate) -> Optional[str]:
    nk = name_match_key(nc.full_name)
    if not nk:
        return None
    disc = None
    if nc.experience and nc.experience[0].company:
        disc = nc.experience[0].company.lower()
    elif nc.country:
        disc = nc.country.lower()
    return f"{nk}|{disc}" if disc else None


def _group_by_identity(cands: List[NormalizedCandidate]) -> List[List[NormalizedCandidate]]:
    dsu = _DSU(len(cands))
    by_key: Dict[str, List[int]] = {}

    def add(key: str, i: int):
        by_key.setdefault(key, []).append(i)

    for i, nc in enumerate(cands):
        for e in nc.emails:
            add(f"email:{e}", i)
        for p in nc.phones:
            add(f"phone:{p}", i)
        wk = _weak_key(nc)
        if wk:
            add(f"weak:{wk}", i)
        nk = name_match_key(nc.full_name)
        if nk:
            add(f"name:{nk}", i)  # links name-only sources (e.g. notes); homonym risk documented

    for members in by_key.values():
        for j in range(1, len(members)):
            dsu.union(members[0], members[j])

    groups: Dict[int, List[NormalizedCandidate]] = {}
    for i, nc in enumerate(cands):
        groups.setdefault(dsu.find(i), []).append(nc)
    # deterministic ordering of groups and of members within a group
    ordered = []
    for root in sorted(groups):
        members = sorted(groups[root], key=lambda c: (SOURCE_PRIORITY.get(c.source, 99), c.source))
        ordered.append(members)
    return ordered


# --------------------------------------------------------------------------- #
# Stage 3: field resolution
# --------------------------------------------------------------------------- #
@dataclass
class _Resolved:
    value: object
    confidence: float
    source: str
    method: str


def _resolve_scalar(claims: List[Tuple[object, str, float, str]]) -> Optional[_Resolved]:
    """claims = [(value, source, weight, normalization_tag)]. Returns winner."""
    groups: Dict[object, List[Tuple[str, float, str]]] = {}
    for value, source, weight, norm in claims:
        if value in (None, "", []):
            continue
        groups.setdefault(value, []).append((source, weight, norm))
    if not groups:
        return None
    scored = []
    for value, contribs in groups.items():
        conf = noisy_or([w for _, w, _ in contribs])
        best = min(contribs, key=lambda c: (-c[1], SOURCE_PRIORITY.get(c[0], 99)))
        scored.append((value, conf, best[0], best[2], best[1]))
    # winner: highest confidence; ties -> source priority; then stable str(value)
    scored.sort(key=lambda s: (-s[1], SOURCE_PRIORITY.get(s[2], 99), str(s[0])))
    v, conf, src, norm, _ = scored[0]
    return _Resolved(v, conf, src, method_for(src, norm))


def _resolve_multi(field_values: List[Tuple[str, str, float, str]]) -> List[Tuple[str, float, List[str], str]]:
    """field_values = [(value, source, weight, norm)]. Returns one row per
    distinct value: (value, confidence, contributing_sources, method)."""
    groups: Dict[str, List[Tuple[str, float, str]]] = {}
    for value, source, weight, norm in field_values:
        if not value:
            continue
        groups.setdefault(value, []).append((source, weight, norm))
    rows = []
    for value, contribs in groups.items():
        conf = noisy_or([w for _, w, _ in contribs])
        srcs = sorted({s for s, _, _ in contribs}, key=lambda s: SOURCE_PRIORITY.get(s, 99))
        best_norm = min(contribs, key=lambda c: (-c[1], SOURCE_PRIORITY.get(c[0], 99)))[2]
        rows.append((value, conf, srcs, best_norm))
    # deterministic: confidence desc, then value
    rows.sort(key=lambda r: (-r[1], str(r[0])))
    return rows


def _candidate_id(emails: List[str], name: Optional[str], phones: List[str]) -> str:
    if emails:
        key = sorted(emails)[0]
    elif name:
        key = name_match_key(name) or name.lower()
    elif phones:
        key = sorted(phones)[0]
    else:
        key = "unknown"
    return "cand_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def merge_group(group: List[NormalizedCandidate]) -> CanonicalProfile:
    prov: List[ProvenanceEntry] = []
    confidences: List[float] = []

    def scalar(trust_field: str, prov_path: str, getter, norm_tag: Optional[str] = None):
        """Resolve one scalar field. ``trust_field`` keys the trust table;
        ``prov_path`` is the canonical path written into provenance (they differ
        for sub-objects, e.g. trust_field='location', prov_path='location.city')."""
        claims = []
        for nc in group:
            val = getter(nc)
            if val not in (None, "", []):
                claims.append((val, nc.source, field_weight(nc.source, trust_field), norm_tag))
        res = _resolve_scalar(claims)
        if res is not None:
            prov.append(ProvenanceEntry(prov_path, res.source, res.method))
            confidences.append(res.confidence)
        return res

    # ---- scalars ----
    name_res = scalar("full_name", "full_name", lambda c: c.full_name)
    headline_res = scalar("headline", "headline", lambda c: c.headline)
    years_res = scalar("years_experience", "years_experience", lambda c: c.years_experience)

    # ---- multi: emails / phones ----
    def multi(trust_field: str, prov_path: str, getter, norm_tag):
        vals = []
        for nc in group:
            for v in getter(nc):
                vals.append((v, nc.source, field_weight(nc.source, trust_field), norm_tag))
        rows = _resolve_multi(vals)
        for value, conf, srcs, norm in rows:
            for s in srcs:
                prov.append(ProvenanceEntry(prov_path, s, method_for(s, norm)))
            confidences.append(conf)
        return rows

    email_rows = multi("emails", "emails", lambda c: c.emails, "lowercased")
    phone_rows = multi("phones", "phones", lambda c: c.phones, "E164")

    # ---- location subfields (trust keyed by 'location', provenance per subfield) ----
    city_res = scalar("location", "location.city", lambda c: c.city)
    region_res = scalar("location", "location.region", lambda c: c.region)
    country_res = scalar("location", "location.country", lambda c: c.country, "ISO3166")
    location = Location(
        city=city_res.value if city_res else None,
        region=region_res.value if region_res else None,
        country=country_res.value if country_res else None,
    )

    # ---- links ----
    li = scalar("links", "links.linkedin", lambda c: c.linkedin)
    gh = scalar("links", "links.github", lambda c: c.github)
    pf = scalar("links", "links.portfolio", lambda c: c.portfolio)
    other_rows = multi("links", "links.other", lambda c: c.other_links, None)
    links = Links(
        linkedin=li.value if li else None,
        github=gh.value if gh else None,
        portfolio=pf.value if pf else None,
        other=[r[0] for r in other_rows],
    )

    # ---- skills (array of objects with per-skill confidence + sources) ----
    skill_rows = _resolve_multi([
        (s, nc.source, field_weight(nc.source, "skills"), "canonical")
        for nc in group for s in nc.skills
    ])
    skills = [Skill(name=v, confidence=conf, sources=srcs) for v, conf, srcs, _ in skill_rows]
    for v, conf, srcs, _ in skill_rows:
        confidences.append(conf)
        for s in srcs:
            prov.append(ProvenanceEntry(f"skills:{v}", s, method_for(s, "canonical")))

    # ---- experience / education (dedupe + fill) ----
    experience = _merge_experience(group, prov, confidences)
    education = _merge_education(group, prov, confidences)

    all_emails = [r[0] for r in email_rows]

    # Overall confidence blends two things:
    #   1. corroboration: the mean of the per-field confidences (how well the
    #      fields present are backed by trusted/agreeing sources), and
    #   2. coverage: what fraction of the core identity signals are present.
    # Without (2), a lone field from a high-trust source (e.g. just a name off a
    # recruiter CSV) would score as high as a fully populated, corroborated
    # profile. Coverage keeps a sparse record low even when its single field is
    # trustworthy. A complete profile has coverage 1.0, so this does not
    # penalise a well-populated record.
    core_signals = [
        bool(name_res and name_res.value),
        bool(all_emails),
        bool([r[0] for r in phone_rows]),
        bool(location.city or location.region or location.country),
        bool(skills),
        bool(experience),
    ]
    coverage = sum(core_signals) / len(core_signals)
    mean_field_conf = sum(confidences) / len(confidences) if confidences else 0.0
    overall = round(mean_field_conf * coverage, 4)

    profile = CanonicalProfile(
        candidate_id=_candidate_id(all_emails, name_res.value if name_res else None,
                                   [r[0] for r in phone_rows]),
        full_name=name_res.value if name_res else None,
        emails=all_emails,
        phones=[r[0] for r in phone_rows],
        location=location,
        links=links,
        headline=headline_res.value if headline_res else None,
        years_experience=years_res.value if years_res else None,
        skills=skills,
        experience=experience,
        education=education,
        provenance=prov,
        overall_confidence=overall,
    )
    return profile


def _pick_subfield(contribs: List[Tuple[object, float, int]]):
    """contribs = [(value, weight, priority)]; return the value from the
    highest-weight contributor that actually has one (None-safe, deterministic)."""
    present = [c for c in contribs if c[0] not in (None, "")]
    if not present:
        return None
    present.sort(key=lambda c: (-c[1], c[2], str(c[0])))
    return present[0][0]


def _merge_list_items(group, fieldname, key_fn, subfields, build_fn, sort_key):
    """Generic dedupe-and-fill for experience/education.

    Items from different sources that share ``key_fn`` are one real-world entry.
    Each output subfield is resolved independently by trust weight, so a stale
    "current company / present end-date" from a low-trust source loses to the
    resume. Item confidence = noisy-OR over all contributing sources' weights.
    """
    buckets: Dict[tuple, List[Tuple[object, str, float]]] = {}
    for nc in group:
        w = field_weight(nc.source, fieldname)
        prio = SOURCE_PRIORITY.get(nc.source, 99)
        for item in getattr(nc, fieldname):
            buckets.setdefault(key_fn(item), []).append((item, nc.source, w, prio))

    resolved = []
    for key, contribs in buckets.items():
        merged_vals = {}
        for sf in subfields:
            merged_vals[sf] = _pick_subfield([(getattr(it, sf), w, prio)
                                              for it, _s, w, prio in contribs])
        weights = [w for _it, _s, w, _p in contribs]
        winner_src = min(contribs, key=lambda c: (-c[2], c[3]))[1]
        resolved.append((build_fn(merged_vals), winner_src, noisy_or(weights)))

    resolved.sort(key=lambda r: sort_key(r[0]), reverse=True)
    return resolved


def _merge_experience(group, prov, confidences) -> List[ExperienceItem]:
    resolved = _merge_list_items(
        group, "experience",
        key_fn=lambda it: ((it.company or "").lower(), (it.title or "").lower()),
        subfields=("company", "title", "start", "end", "summary"),
        build_fn=lambda v: ExperienceItem(**v),
        sort_key=lambda it: (it.start or "0000-00"),
    )
    items = []
    for idx, (item, src, conf) in enumerate(resolved):
        items.append(item)
        prov.append(ProvenanceEntry(f"experience[{idx}]", src, method_for(src)))
        confidences.append(conf)
    return items


def _merge_education(group, prov, confidences) -> List[EducationItem]:
    resolved = _merge_list_items(
        group, "education",
        key_fn=lambda it: ((it.institution or "").lower(), (it.degree or "").lower()),
        subfields=("institution", "degree", "field", "end_year"),
        build_fn=lambda v: EducationItem(**v),
        sort_key=lambda it: (it.end_year or 0),
    )
    items = []
    for idx, (item, src, conf) in enumerate(resolved):
        items.append(item)
        prov.append(ProvenanceEntry(f"education[{idx}]", src, method_for(src)))
        confidences.append(conf)
    return items


def build_profiles(raws: List[RawCandidate], default_region: str = "US") -> List[CanonicalProfile]:
    """Full merge entry point: normalize -> group -> merge each group."""
    normalized = [normalize_candidate(r, default_region) for r in raws]
    groups = _group_by_identity(normalized)
    profiles = [merge_group(g) for g in groups]
    # deterministic profile ordering by candidate_id
    profiles.sort(key=lambda p: p.candidate_id)
    return profiles
