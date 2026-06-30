"""Tests for the projection layer + runtime config.

The projection layer is the only place that reshapes the canonical record. It
must: resolve the path grammar, rename/subset fields, re-normalize on request,
honour the missing-value policy, and toggle confidence/provenance — all without
mutating or inventing data.
"""
import pytest

from candidate_transformer.canonical import (CanonicalProfile, EducationItem,
                                             ExperienceItem, Links, Location,
                                             ProvenanceEntry, Skill)
from candidate_transformer.config import OutputConfig
from candidate_transformer.projection import (ProjectionError, project,
                                              resolve_path)


def make_profile(**overrides) -> CanonicalProfile:
    p = CanonicalProfile(
        candidate_id="cand_test",
        full_name="Jane Doe",
        emails=["jane@x.com", "j@y.com"],
        phones=["+14155550186"],
        location=Location(city="San Francisco", region="CA", country="US"),
        links=Links(github="https://github.com/jane"),
        headline="Engineer",
        years_experience=7.0,
        skills=[Skill("Python", 0.95, ["resume"]), Skill("Go", 0.8, ["resume"])],
        experience=[ExperienceItem(company="Stripe", title="SWE", start="2021-03")],
        education=[EducationItem(institution="UCB", degree="B.S.", field="CS", end_year=2018)],
        provenance=[
            ProvenanceEntry("full_name", "resume", "extracted"),
            ProvenanceEntry("emails", "resume", "extracted+lowercased"),
            ProvenanceEntry("skills:Python", "resume", "extracted+canonical"),
        ],
        overall_confidence=0.9,
    )
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


# --------------------------------------------------------------------------- #
# Path grammar
# --------------------------------------------------------------------------- #
def test_resolve_path_grammar():
    d = make_profile().to_dict()
    assert resolve_path(d, "full_name") == "Jane Doe"
    assert resolve_path(d, "emails[0]") == "jane@x.com"
    assert resolve_path(d, "location.country") == "US"
    assert resolve_path(d, "experience[0].company") == "Stripe"
    assert resolve_path(d, "skills[].name") == ["Python", "Go"]   # wildcard map


def test_resolve_path_missing_returns_none():
    d = make_profile().to_dict()
    assert resolve_path(d, "emails[9]") is None       # index out of range
    assert resolve_path(d, "nope.nothere") is None    # unknown key
    assert resolve_path(d, "links.portfolio") is None  # present but null


# --------------------------------------------------------------------------- #
# Subset + rename
# --------------------------------------------------------------------------- #
def test_subset_and_rename():
    cfg = OutputConfig.from_dict({
        "fields": [
            {"path": "name", "from": "full_name", "type": "string"},
            {"path": "primary_email", "from": "emails[0]", "type": "string"},
            {"path": "skills", "from": "skills[].name", "type": "string[]"},
        ],
        "include_confidence": False,
        "include_provenance": False,
    })
    out = project(make_profile(), cfg)
    assert out == {
        "name": "Jane Doe",
        "primary_email": "jane@x.com",
        "skills": ["Python", "Go"],
    }


def test_nested_output_path():
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "contact.country", "from": "location.country", "type": "string"}],
        "include_confidence": False,
        "include_provenance": False,
    })
    out = project(make_profile(), cfg)
    assert out == {"contact": {"country": "US"}}


# --------------------------------------------------------------------------- #
# Per-field normalization on projection
# --------------------------------------------------------------------------- #
def test_normalize_iso3166_on_projection():
    # canonical happens to hold a raw country here; projection re-normalizes it
    profile = make_profile(location=Location(country="USA"))
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "country", "from": "location.country",
                    "type": "string", "normalize": "iso3166"}],
        "include_confidence": False, "include_provenance": False,
    })
    assert project(profile, cfg) == {"country": "US"}


def test_normalize_e164_over_wildcard_list():
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "phones", "from": "phones",
                    "type": "string[]", "normalize": "e164"}],
        "include_confidence": False, "include_provenance": False,
        "default_region": "US",
    })
    assert project(make_profile(), cfg) == {"phones": ["+14155550186"]}


# --------------------------------------------------------------------------- #
# Missing-value policy
# --------------------------------------------------------------------------- #
def _portfolio_cfg(policy):
    return OutputConfig.from_dict({
        "fields": [{"path": "portfolio", "from": "links.portfolio", "type": "string"}],
        "on_missing": policy,
        "include_confidence": False, "include_provenance": False,
    })


def test_on_missing_null():
    assert project(make_profile(), _portfolio_cfg("null")) == {"portfolio": None}


def test_on_missing_omit():
    assert project(make_profile(), _portfolio_cfg("omit")) == {}


def test_on_missing_error_raises():
    with pytest.raises(ProjectionError):
        project(make_profile(), _portfolio_cfg("error"))


def test_per_field_on_missing_overrides_global():
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "portfolio", "from": "links.portfolio",
                    "type": "string", "on_missing": "omit"}],
        "on_missing": "error",   # global would raise; per-field omit wins
        "include_confidence": False, "include_provenance": False,
    })
    assert project(make_profile(), cfg) == {}


# --------------------------------------------------------------------------- #
# Toggles: confidence + provenance
# --------------------------------------------------------------------------- #
def test_include_confidence_adds_overall_and_keeps_nested():
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "skills", "from": "skills", "type": "object[]"}],
        "include_confidence": True, "include_provenance": False,
    })
    out = project(make_profile(), cfg)
    assert out["overall_confidence"] == 0.9
    assert out["skills"][0]["confidence"] == 0.95


def test_exclude_confidence_strips_nested_and_overall():
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "skills", "from": "skills", "type": "object[]"}],
        "include_confidence": False, "include_provenance": False,
    })
    out = project(make_profile(), cfg)
    assert "overall_confidence" not in out
    assert "confidence" not in out["skills"][0]
    assert out["skills"][0]["name"] == "Python"


def test_provenance_filtered_to_projected_fields():
    cfg = OutputConfig.from_dict({
        "fields": [{"path": "full_name", "from": "full_name", "type": "string"}],
        "include_confidence": False, "include_provenance": True,
    })
    out = project(make_profile(), cfg)
    # only provenance whose head is among projected fields ('full_name')
    fields = {p["field"] for p in out["provenance"]}
    assert fields == {"full_name"}


# --------------------------------------------------------------------------- #
# Config validation
# --------------------------------------------------------------------------- #
def test_config_rejects_unknown_type():
    with pytest.raises(ValueError):
        OutputConfig.from_dict({"fields": [{"path": "x", "type": "frobnicate"}]})


def test_config_rejects_bad_on_missing():
    with pytest.raises(ValueError):
        OutputConfig.from_dict({"fields": [], "on_missing": "explode"})


def test_config_requires_path():
    with pytest.raises(ValueError):
        OutputConfig.from_dict({"fields": [{"from": "full_name"}]})
