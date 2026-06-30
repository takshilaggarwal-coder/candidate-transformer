"""Unit tests for the pure, deterministic normalizers.

These are the foundation: every normalizer returns a clean value or ``None``,
never a malformed guess. Expectations here are hand-computed, not snapshotted.
"""
import pytest

from candidate_transformer.normalize import (classify_link, name_match_key,
                                             normalize_country, normalize_email,
                                             normalize_month, normalize_name,
                                             normalize_phone, normalize_url,
                                             normalize_year,
                                             normalize_years_experience,
                                             parse_location)
from candidate_transformer.skills import canonicalize_skill, is_known_skill


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("  JANE.DOE@Example.com ", "jane.doe@example.com"),
    ("mailto:x@y.com", "x@y.com"),
    ("<a@b.com>", "a@b.com"),
    ("not-an-email", None),
    ("@nope.com", None),
    ("", None),
    (None, None),
])
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


# --------------------------------------------------------------------------- #
# Phone -> E.164
# --------------------------------------------------------------------------- #
def test_phone_us_formatting():
    assert normalize_phone("(415) 555-0186", "US") == "+14155550186"


def test_phone_keeps_explicit_country_code():
    assert normalize_phone("+91 98765 43210", "US") == "+919876543210"


def test_phone_uses_region_when_no_country_code():
    # bare Indian 10-digit number is only valid when parsed as IN
    assert normalize_phone("9876543210", "IN") == "+919876543210"


@pytest.mark.parametrize("raw", ["", "   ", "not a phone", "12", None])
def test_phone_rejects_garbage(raw):
    assert normalize_phone(raw, "US") is None


# --------------------------------------------------------------------------- #
# Dates -> YYYY-MM
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("Mar 2020", "2020-03"),
    ("March 2020", "2020-03"),
    ("Mar. 2020", "2020-03"),
    ("2020-03", "2020-03"),
    ("2020/03", "2020-03"),
    ("03/2020", "2020-03"),
    ("2020", "2020-01"),
    ("2020-03-15T10:30:00", "2020-03"),
    ("present", None),
    ("Current", None),
    ("garbage", None),
    ("2020-13", None),   # invalid month rejected, not silently wrapped
    (None, None),
])
def test_normalize_month(raw, expected):
    assert normalize_month(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Class of 2018", 2018),
    (2018, 2018),
    ("graduated 1999", 1999),
    ("nope", None),
    (None, None),
])
def test_normalize_year(raw, expected):
    assert normalize_year(raw) == expected


# --------------------------------------------------------------------------- #
# Country -> ISO-3166 alpha-2
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("USA", "US"),
    ("United States", "US"),
    ("U.S.", "US"),
    ("India", "IN"),
    ("Canada", "CA"),
    ("UK", "GB"),
    ("Germany", "DE"),
    ("DE", "DE"),
    ("DEU", "DE"),
    ("Atlantis", None),
    ("", None),
    (None, None),
])
def test_normalize_country(raw, expected):
    assert normalize_country(raw) == expected


# --------------------------------------------------------------------------- #
# Location parsing — including the US-state / country collision edge case
# --------------------------------------------------------------------------- #
def test_location_state_abbrev_is_not_a_country():
    # "CA" here is California, NOT Canada. The 2-letter state must stay region.
    assert parse_location("San Francisco, CA") == ("San Francisco", "CA", None)


def test_location_full_triple():
    assert parse_location("San Francisco, CA, USA") == ("San Francisco", "CA", "US")


def test_location_international_triple():
    assert parse_location("Bengaluru, Karnataka, India") == ("Bengaluru", "Karnataka", "IN")


def test_location_city_country_pair():
    assert parse_location("London, UK") == ("London", None, "GB")


def test_location_empty():
    assert parse_location("") == (None, None, None)
    assert parse_location(None) == (None, None, None)


# --------------------------------------------------------------------------- #
# Name
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("  jane   doe ", "Jane Doe"),
    ("JANE DOE", "Jane Doe"),
    ("McDonald", "McDonald"),     # mixed-case preserved
    ("jane mcdonald", "Jane Mcdonald"),
    ("", None),
    (None, None),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_name_match_key_is_loose():
    assert name_match_key("Jane A. Doe") == "jane a doe"
    assert name_match_key("  JANE   DOE  ") == "jane doe"
    assert name_match_key(None) is None


# --------------------------------------------------------------------------- #
# Years of experience
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("7 years", 7.0),
    ("~6 yrs", 6.0),
    (5, 5.0),
    (4.5, 4.5),
    (-3, None),
    ("none", None),
    (None, None),
])
def test_normalize_years_experience(raw, expected):
    assert normalize_years_experience(raw) == expected


# --------------------------------------------------------------------------- #
# URLs / links
# --------------------------------------------------------------------------- #
def test_normalize_url_adds_scheme_and_strips_trailing_slash():
    assert normalize_url("github.com/x") == "https://github.com/x"
    assert normalize_url("https://x.com/") == "https://x.com"
    assert normalize_url("  ") is None
    assert normalize_url(None) is None


@pytest.mark.parametrize("url,kind", [
    ("https://www.linkedin.com/in/janedoe", "linkedin"),
    ("https://github.com/janedoe", "github"),
    ("https://janedoe.github.io", "github"),
    ("https://janedoe.dev", "other"),
    (None, None),
])
def test_classify_link(url, kind):
    assert classify_link(url) == kind


# --------------------------------------------------------------------------- #
# Skills canonicalization (deterministic alias table)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("js", "JavaScript"),
    ("JS", "JavaScript"),
    ("k8s", "Kubernetes"),
    ("postgres", "PostgreSQL"),
    ("  python ", "Python"),
])
def test_canonicalize_known_skill(raw, expected):
    assert canonicalize_skill(raw) == expected


def test_canonicalize_unknown_skill_passes_through_conservatively():
    # an unknown token is title-cased, never force-mapped to something wrong
    out = canonicalize_skill("Rust")
    assert out == "Rust"
    assert is_known_skill("k8s") is True
    assert is_known_skill("definitely-not-a-skill") is False
