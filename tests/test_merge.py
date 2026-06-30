"""Tests for the merge engine: trust math, confidence, conflict resolution,
identity resolution, and the normalize-doesn't-crash robustness contract.

We construct ``RawCandidate`` objects directly so each behaviour is isolated
from the file-parsing adapters.
"""
import pytest

from candidate_transformer.merge import (build_profiles, field_weight,
                                         method_for, noisy_or,
                                         normalize_candidate)
from candidate_transformer.sources.base import RawCandidate, RawExperience


# --------------------------------------------------------------------------- #
# Trust math (the only tunable numbers; pin them down)
# --------------------------------------------------------------------------- #
def test_field_weight_is_source_trust_times_field_multiplier():
    assert field_weight("recruiter_csv", "emails") == 0.9      # 0.90 * 1.0
    assert field_weight("ats_json", "skills") == 0.765         # 0.85 * 0.90
    assert field_weight("resume", "skills") == 0.8             # 0.80 * 1.0
    assert field_weight("recruiter_csv", "education") == 0.18  # 0.90 * 0.2


def test_field_weight_unknown_source_falls_back():
    # unknown source -> DEFAULT_TRUST 0.5, unknown field multiplier -> 1.0
    assert field_weight("mystery_source", "emails") == 0.5


@pytest.mark.parametrize("weights,expected", [
    ([0.9], 0.9),
    ([0.5, 0.5], 0.75),          # 1 - 0.5*0.5
    ([0.8, 0.765], 0.953),       # corroboration: resume + ats on a skill
    ([], 0.0),                   # no evidence -> zero
    ([1.5], 1.0),                # clamps above 1.0
    ([-0.2], 0.0),               # clamps below 0.0
])
def test_noisy_or(weights, expected):
    assert noisy_or(weights) == expected


def test_method_for_labels_by_source():
    assert method_for("recruiter_csv") == "direct"
    assert method_for("ats_json") == "remapped"
    assert method_for("resume") == "extracted"
    assert method_for("recruiter_notes") == "extracted"
    assert method_for("ats_json", "E164") == "remapped+E164"


# --------------------------------------------------------------------------- #
# Confidence: corroboration raises it, never above 1.0
# --------------------------------------------------------------------------- #
def test_corroboration_raises_skill_confidence():
    two = build_profiles([
        RawCandidate(source="resume", emails=["a@b.com"], skills=["Python"]),
        RawCandidate(source="ats_json", emails=["a@b.com"], skills=["python"]),
    ])
    assert len(two) == 1
    py = next(s for s in two[0].skills if s.name == "Python")
    assert py.confidence == 0.953                      # noisy_or(0.8, 0.765)
    assert py.sources == ["ats_json", "resume"]        # ordered by source priority

    one = build_profiles([
        RawCandidate(source="resume", emails=["a@b.com"], skills=["Python"]),
    ])
    py_solo = one[0].skills[0]
    assert py_solo.confidence == 0.8
    # corroborated confidence strictly exceeds the single-source confidence
    assert py.confidence > py_solo.confidence


# --------------------------------------------------------------------------- #
# Conflict resolution: highest-trust source wins, deterministically
# --------------------------------------------------------------------------- #
def test_headline_conflict_resolved_by_trust():
    profiles = build_profiles([
        RawCandidate(source="recruiter_csv", emails=["a@b.com"],
                     full_name="Sam Lee", headline="Software Engineer"),
        RawCandidate(source="ats_json", emails=["a@b.com"],
                     full_name="Sam Lee", headline="Senior Software Engineer"),
    ])
    assert len(profiles) == 1
    # ats headline weight 0.85*0.95=0.8075 beats csv 0.90*0.7=0.63
    assert profiles[0].headline == "Senior Software Engineer"
    head_prov = [p for p in profiles[0].provenance if p.field == "headline"]
    assert head_prov and head_prov[0].source == "ats_json"


def test_stale_end_date_loses_to_higher_trust_source():
    # Same job from two sources with conflicting end dates. The resume
    # (higher experience-trust) must win the per-subfield resolution.
    profiles = build_profiles([
        RawCandidate(source="recruiter_csv", emails=["a@b.com"], full_name="Sam Lee",
                     experience=[RawExperience(company="Acme", title="Engineer",
                                               start="2018-06", end="2020-01")]),
        RawCandidate(source="resume", emails=["a@b.com"], full_name="Sam Lee",
                     experience=[RawExperience(company="Acme", title="Engineer",
                                               start="2018-06", end="2021-02")]),
    ])
    assert len(profiles) == 1
    exp = profiles[0].experience
    assert len(exp) == 1                  # deduped into one real-world entry
    assert exp[0].end == "2021-02"        # resume wins the conflicting subfield


# --------------------------------------------------------------------------- #
# Identity resolution (union-find)
# --------------------------------------------------------------------------- #
def test_shared_email_merges_into_one_profile():
    profiles = build_profiles([
        RawCandidate(source="recruiter_csv", emails=["a@b.com"], full_name="A B"),
        RawCandidate(source="resume", emails=["a@b.com"], full_name="A. B."),
    ])
    assert len(profiles) == 1


def test_distinct_people_stay_separate():
    profiles = build_profiles([
        RawCandidate(source="recruiter_csv", emails=["a@b.com"], full_name="A B"),
        RawCandidate(source="recruiter_csv", emails=["c@d.com"], full_name="C D"),
    ])
    assert len(profiles) == 2


def test_candidate_id_is_stable_for_same_email():
    p1 = build_profiles([RawCandidate(source="resume", emails=["a@b.com"])])
    p2 = build_profiles([RawCandidate(source="ats_json", emails=["a@b.com"])])
    assert p1[0].candidate_id == p2[0].candidate_id


# --------------------------------------------------------------------------- #
# Robustness: garbage in a record must not crash, must not invent values
# --------------------------------------------------------------------------- #
def test_normalize_drops_invalid_contact_values():
    nc = normalize_candidate(RawCandidate(
        source="recruiter_csv",
        full_name="  ",
        emails=["not-an-email", "garbage"],
        phones=["12", "nope"],
    ))
    assert nc.emails == []      # honestly-empty, not a bad guess
    assert nc.phones == []
    assert nc.full_name is None


def test_invalid_record_yields_low_but_valid_profile():
    # a record with only a name should still merge cleanly (no exceptions)
    profiles = build_profiles([
        RawCandidate(source="recruiter_notes", full_name="Lone Name"),
    ])
    assert len(profiles) == 1
    assert profiles[0].full_name == "Lone Name"
    assert profiles[0].emails == []
