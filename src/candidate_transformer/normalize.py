"""Normalization primitives.

Every function here is pure and deterministic: same input gives the same
output, with no network and no clock. Each returns ``None`` when it cannot
confidently normalize a value, rather than guessing.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple

import phonenumbers
import pycountry

# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: Optional[str]) -> Optional[str]:
    """Lowercase + trim. Returns None if it does not look like an email."""
    if not raw:
        return None
    e = raw.strip().lower()
    # strip common wrappers like "mailto:" or surrounding angle brackets
    e = e.replace("mailto:", "").strip("<>").strip()
    return e if _EMAIL_RE.match(e) else None


# --------------------------------------------------------------------------- #
# Phone -> E.164
# --------------------------------------------------------------------------- #
def normalize_phone(raw: Optional[str], default_region: str = "US") -> Optional[str]:
    """Parse a phone number into E.164 (e.g. "+14155550123").

    ``default_region`` is used only when the number has no country code. We
    return None on anything we cannot parse to a *valid* number rather than
    emitting a malformed string.
    """
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        # If the string already carries a "+", region is ignored by the lib.
        parsed = phonenumbers.parse(candidate, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


# --------------------------------------------------------------------------- #
# Dates -> YYYY-MM
# --------------------------------------------------------------------------- #
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_PRESENT_TOKENS = {"present", "current", "now", "ongoing", "till date", "to date"}


def normalize_month(raw: Optional[str]) -> Optional[str]:
    """Normalize a single date token to ``YYYY-MM``.

    Handles: "2020-03", "2020/03", "03/2020", "Mar 2020", "March 2020",
    "2020" (-> "2020-01"), ISO datetimes. "present"/"current" -> None
    (callers interpret a None end date as "ongoing").
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s in _PRESENT_TOKENS:
        return None

    # "Mar 2020" / "March 2020" / "Mar. 2020"
    m = re.match(r"^([a-z]+)\.?\s+(\d{4})$", s)
    if m and m.group(1) in _MONTHS:
        return f"{int(m.group(2)):04d}-{_MONTHS[m.group(1)]:02d}"

    # "2020-03" / "2020/03" / "2020.03"
    m = re.match(r"^(\d{4})[-/.](\d{1,2})$", s)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return f"{int(m.group(1)):04d}-{month:02d}"

    # "03/2020" / "03-2020"
    m = re.match(r"^(\d{1,2})[-/](\d{4})$", s)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return f"{int(m.group(2)):04d}-{month:02d}"

    # bare year "2020"
    m = re.match(r"^(\d{4})$", s)
    if m:
        return f"{int(m.group(1)):04d}-01"

    # ISO datetime fallback "2020-03-15T..."
    try:
        dt = datetime.fromisoformat(s.replace("z", "+00:00"))
        return f"{dt.year:04d}-{dt.month:02d}"
    except ValueError:
        return None


def normalize_year(raw) -> Optional[int]:
    """Extract a 4-digit year as int, or None."""
    if raw is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(raw))
    return int(m.group(0)) if m else None


# --------------------------------------------------------------------------- #
# Country -> ISO-3166 alpha-2
# --------------------------------------------------------------------------- #
# Hand-maintained aliases for forms pycountry does not resolve directly.
_COUNTRY_ALIASES = {
    "usa": "US", "u.s.a.": "US", "u.s.": "US", "us": "US",
    "united states": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "england": "GB", "britain": "GB",
    "great britain": "GB", "united kingdom": "GB",
    "uae": "AE", "south korea": "KR", "korea": "KR", "russia": "RU",
    "bharat": "IN", "india": "IN",
}


def normalize_country(raw: Optional[str]) -> Optional[str]:
    """Map a country name/code to ISO-3166 alpha-2. Returns None if unknown."""
    if not raw:
        return None
    base = raw.strip().lower()
    if not base:
        return None
    # Check the alias table with and without a trailing dot so dotted forms
    # ("u.s.", "u.s.a.") resolve as the table intends; plain "us." also works.
    for alias_key in (base, base.rstrip(".")):
        if alias_key in _COUNTRY_ALIASES:
            return _COUNTRY_ALIASES[alias_key]
    key = base.rstrip(".")
    # exact alpha-2 / alpha-3 already?
    up = key.upper()
    if len(up) == 2 and pycountry.countries.get(alpha_2=up):
        return up
    if len(up) == 3 and pycountry.countries.get(alpha_3=up):
        return pycountry.countries.get(alpha_3=up).alpha_2
    # full name lookup (handles "Canada", "Germany", ...)
    try:
        match = pycountry.countries.lookup(raw.strip())
        return match.alpha_2
    except LookupError:
        return None


# US state abbreviations. Several collide with ISO-3166 alpha-2 country codes
# (CA=California vs Canada, AL=Alabama vs Albania, AR, IN, ...). In a free-text
# "City, XX" location the 2-letter token is far more likely a US state, so we
# treat it as a region, not a country. (Documented limitation: "Mumbai, IN"
# meaning India would be read as a region.)
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


def parse_location(text: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Best-effort split of a free-text location into (city, region, country).

    Accepts "City, Region, Country" or "City, Country". The last comma-part is
    treated as the country and normalized *unless* it is a 2-letter US state
    abbreviation, in which case it is kept as the region. Unrecognized tokens
    are kept as region text rather than discarded.
    """
    if not text:
        return None, None, None
    parts = [p.strip() for p in str(text).split(",") if p.strip()]
    if not parts:
        return None, None, None

    country = None
    if len(parts) >= 2:
        last = parts[-1]
        cc = normalize_country(last)
        if cc and not (len(last) == 2 and last.upper() in _US_STATES):
            country = cc
            parts = parts[:-1]  # consume the country token

    city = parts[0] if len(parts) >= 1 else None
    region = parts[1] if len(parts) >= 2 else None
    return city, region, country


# --------------------------------------------------------------------------- #
# Name
# --------------------------------------------------------------------------- #
def normalize_name(raw: Optional[str]) -> Optional[str]:
    """Trim and collapse whitespace. We preserve casing of multi-cap tokens
    (e.g. "McDonald", "PhD") but title-case obviously lower/upper tokens."""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.strip())
    if not s:
        return None

    def fix(tok: str) -> str:
        if tok.islower() or tok.isupper():
            return tok.capitalize()
        return tok  # already mixed-case, leave it alone

    return " ".join(fix(t) for t in s.split(" "))


def name_match_key(name: Optional[str]) -> Optional[str]:
    """A loose key for identity matching: lowercase, alnum-only, spaces kept."""
    if not name:
        return None
    key = re.sub(r"[^a-z0-9 ]", "", name.lower())
    key = re.sub(r"\s+", " ", key).strip()
    return key or None


# --------------------------------------------------------------------------- #
# Years of experience
# --------------------------------------------------------------------------- #
def normalize_years_experience(raw) -> Optional[float]:
    """Pull a number of years from values like "5", "5 years", "~6 yrs"."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw >= 0 else None
    m = re.search(r"(\d+(?:\.\d+)?)", str(raw))
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# URLs / links
# --------------------------------------------------------------------------- #
def normalize_url(raw: Optional[str]) -> Optional[str]:
    """Trim, add scheme if missing, lowercase the host. Returns None if empty."""
    if not raw:
        return None
    u = raw.strip()
    if not u:
        return None
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u.rstrip("/")


def classify_link(url: Optional[str]) -> Optional[str]:
    """Return 'linkedin' | 'github' | 'portfolio'(other) based on host."""
    if not url:
        return None
    low = url.lower()
    if "linkedin.com" in low:
        return "linkedin"
    if "github.com" in low or "github.io" in low:
        return "github"
    return "other"
