"""Tests for the optional recruiter keyword boost (``scoring.py``).

The boost is a *display-time* concern layered on top of the engine: it must
never change ``overall_confidence`` itself, and with no keywords it must be a
no-op. These tests pin that contract plus the matching and blending behaviour.
"""
import pytest

from candidate_transformer.canonical import (CanonicalProfile, EducationItem,
                                             ExperienceItem, Location, Skill)
from candidate_transformer.scoring import (KEYWORD_WEIGHT, blend_score,
                                           keyword_match, parse_keywords)


def _profile(**kw) -> CanonicalProfile:
    base = dict(candidate_id="c1", full_name="Test Person")
    base.update(kw)
    return CanonicalProfile(**base)


# --------------------------------------------------------------------------- #
# parse_keywords
# --------------------------------------------------------------------------- #
def test_parse_splits_on_commas_newlines_semicolons():
    assert parse_keywords("go, python\nreact; sql") == ["go", "python", "react", "sql"]


def test_parse_dedupes_case_insensitively_and_preserves_order():
    assert parse_keywords("Go, go, GO, Rust") == ["Go", "Rust"]


def test_parse_collapses_whitespace_and_trims():
    assert parse_keywords("  machine   learning ,  ml ") == ["machine learning", "ml"]


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", None, ",,, ;"])
def test_parse_empty_inputs_yield_no_keywords(raw):
    assert parse_keywords(raw) == []


# --------------------------------------------------------------------------- #
# keyword_match — skill alias path
# --------------------------------------------------------------------------- #
def test_alias_keyword_matches_canonical_skill():
    p = _profile(skills=[Skill("Kubernetes", 0.9, ["ats_json"]),
                         Skill("Go", 0.8, ["resume"])])
    frac, matched = keyword_match(p, ["k8s", "golang"])
    assert frac == 1.0
    assert matched == ["k8s", "golang"]


def test_skill_keyword_absent_does_not_match():
    p = _profile(skills=[Skill("Go", 0.8, ["resume"])])
    frac, matched = keyword_match(p, ["java"])
    assert frac == 0.0 and matched == []


# --------------------------------------------------------------------------- #
# keyword_match — free-text path
# --------------------------------------------------------------------------- #
def test_text_match_against_headline_experience_education():
    p = _profile(
        headline="Backend engineer, fintech",
        experience=[ExperienceItem(company="Stripe", title="Engineer",
                                   summary="Owned the payments service")],
        education=[EducationItem(institution="MIT", degree="B.Sc", field="CS")],
        location=Location(city="Berlin", region=None, country="DE"),
    )
    frac, matched = keyword_match(p, ["fintech", "stripe", "payments", "MIT", "berlin"])
    assert frac == 1.0
    assert set(matched) == {"fintech", "stripe", "payments", "MIT", "berlin"}


def test_short_token_does_not_false_positive_inside_word():
    # "go" must not match "google" when the candidate has no Go skill.
    p = _profile(headline="Loves google cloud", skills=[Skill("AWS", 0.9, ["x"])])
    frac, matched = keyword_match(p, ["go"])
    assert frac == 0.0 and matched == []


def test_symbol_keyword_matches_in_text():
    p = _profile(experience=[ExperienceItem(summary="Wrote a lot of C++ here")])
    frac, matched = keyword_match(p, ["c++"])
    assert matched == ["c++"]


def test_partial_match_fraction():
    p = _profile(skills=[Skill("Python", 0.9, ["x"])])
    frac, matched = keyword_match(p, ["python", "rust", "java", "go"])
    assert frac == pytest.approx(0.25)
    assert matched == ["python"]


def test_no_keywords_is_empty_match():
    p = _profile(skills=[Skill("Python", 0.9, ["x"])])
    assert keyword_match(p, []) == (0.0, [])


# --------------------------------------------------------------------------- #
# blend_score
# --------------------------------------------------------------------------- #
def test_blend_is_weighted_average_of_relevance_and_confidence():
    # 0.6 * 1.0 + 0.4 * 0.5 = 0.8
    assert blend_score(0.5, 1.0) == pytest.approx(KEYWORD_WEIGHT * 1.0 + 0.4 * 0.5)


def test_full_match_lifts_a_weak_profile_above_a_strong_non_match():
    weak_but_relevant = blend_score(0.40, 1.0)
    strong_but_irrelevant = blend_score(0.92, 0.0)
    assert weak_but_relevant > strong_but_irrelevant


def test_blend_monotonic_in_match_fraction():
    assert blend_score(0.7, 0.0) < blend_score(0.7, 0.5) < blend_score(0.7, 1.0)


def test_blend_passes_through_none_base():
    # config that hides confidence => nothing to blend
    assert blend_score(None, 1.0) is None


def test_blend_never_exceeds_one():
    assert blend_score(1.0, 1.0) <= 1.0


# --------------------------------------------------------------------------- #
# Engine contract: keyword scoring must not touch overall_confidence
# --------------------------------------------------------------------------- #
def test_keyword_match_does_not_mutate_profile_confidence():
    p = _profile(skills=[Skill("Go", 0.8, ["resume"])], overall_confidence=0.77)
    keyword_match(p, ["go", "python"])
    assert p.overall_confidence == 0.77


# --------------------------------------------------------------------------- #
# Web integration: keywords re-rank; empty keywords are a no-op
# --------------------------------------------------------------------------- #
def test_web_keyword_boost_reranks_and_annotates():
    pytest.importorskip("flask")
    from candidate_transformer.web import create_app

    client = create_app().test_client()

    # No keywords: the relevance UI must be absent. (The class names live in the
    # always-present CSS, so assert on the rendered *elements*, not substrings.)
    plain = client.post("/run", data={}).get_data(as_text=True)
    assert 'class="kwrow"' not in plain
    assert "Ranked by" not in plain

    # With a keyword every real candidate's record contains, the relevance
    # chips and the "Ranked by" banner appear.
    boosted = client.post("/run", data={"keywords": "kubernetes, go"}).get_data(as_text=True)
    assert "Ranked by" in boosted
    assert 'class="kw hit"' in boosted


def test_default_view_is_sorted_by_confidence_descending():
    pytest.importorskip("flask")
    import re

    from candidate_transformer.web import create_app

    html = create_app().test_client().post("/run", data={}).get_data(as_text=True)
    badges = [int(x) for x in re.findall(r'class="conf"[^>]*>.*?(\d+)%', html, re.S)]
    assert badges, "expected at least one confidence badge"
    assert badges == sorted(badges, reverse=True), f"cards not descending by confidence: {badges}"
