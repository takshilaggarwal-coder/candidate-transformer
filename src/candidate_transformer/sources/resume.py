"""Resume adapter (unstructured source, PDF or DOCX prose).

Resume parsing is heuristic, so this adapter is conservative and
section-driven:

  1. pull plain text out of the PDF/DOCX,
  2. read the header block (name, headline, contact line),
  3. slice the body into SUMMARY / EXPERIENCE / EDUCATION / SKILLS sections by
     recognizing section headings,
  4. parse each section with high-precision patterns (date ranges, comma splits).

Anything that isn't confidently parsed is left empty rather than guessed. The
sample resumes follow a conventional layout; unusual layouts degrade to partial
extraction.
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from .base import RawCandidate, RawEducation, RawExperience, SourceAdapter

# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def _extract_pdf(path: str) -> str:
    import pdfplumber
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _extract_docx(path: str) -> str:
    import docx
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in (".docx", ".doc"):
        return _extract_docx(path)
    # plain-text fallback so the adapter never hard-fails on extension
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-]{6,}\d)(?!\w)")
_URL_RE = re.compile(r"((?:https?://)?(?:www\.)?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/[^\s|]+)")

_DATE_TOKEN = r"(?:[A-Za-z]{3,9}\.?\s+\d{4}|\d{1,2}[/\-]\d{4}|\d{4})"
_DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*(?:[–\-—]|to)\s*(?P<end>present|current|now|{_DATE_TOKEN})",
    re.I,
)

_SECTIONS = {
    "summary": ["summary", "objective", "profile", "about"],
    "experience": ["experience", "work experience", "employment", "professional experience",
                   "work history"],
    "education": ["education", "academics", "academic background"],
    "skills": ["skills", "technical skills", "core skills", "technologies"],
}
# flat lookup of heading text -> section key
_HEADING_LOOKUP = {kw: sec for sec, kws in _SECTIONS.items() for kw in kws}

_INSTITUTION_KEYWORDS = ["university", "college", "institute", "school",
                         "iit", "nit", "iim", "polytechnic", "academy"]
# Leading degree token at the start of an education line, e.g. "B.S.", "B.Tech",
# "M.S.", "Bachelor", "PhD". Group 1 captures the degree itself.
_DEGREE_RE = re.compile(
    r"^(b\.?\s?tech|b\.?\s?eng\.?|b\.?\s?e\.?|b\.?\s?sc?\.?|bachelor(?:'s)?|"
    r"m\.?\s?tech|m\.?\s?eng\.?|m\.?\s?sc?\.?|master(?:'s)?|m\.?b\.?a\.?|ph\.?\s?d\.?|diploma)",
    re.I,
)


def _is_heading(line: str) -> Optional[str]:
    s = line.strip().strip(":").lower()
    if not s or len(s) > 30:
        return None
    return _HEADING_LOOKUP.get(s)


def _looks_like_name(line: str) -> bool:
    s = line.strip()
    if not s or "@" in s or any(ch.isdigit() for ch in s):
        return False
    toks = s.split()
    if not (1 <= len(toks) <= 4):
        return False
    # mostly alphabetic tokens, at least one capitalized
    return all(re.match(r"^[A-Za-z.\-']+$", t) for t in toks) and any(t[0].isupper() for t in toks)


# --------------------------------------------------------------------------- #
# Section parsing
# --------------------------------------------------------------------------- #
def _split_sections(lines: List[str]) -> Tuple[List[str], dict]:
    """Return (header_lines, {section_key: [lines]})."""
    header: List[str] = []
    sections: dict = {}
    current: Optional[str] = None
    for line in lines:
        sec = _is_heading(line)
        if sec:
            current = sec
            sections.setdefault(current, [])
            continue
        if current is None:
            header.append(line)
        else:
            sections[current].append(line)
    return header, sections


def _parse_experience(lines: List[str]) -> List[RawExperience]:
    items: List[RawExperience] = []
    current: Optional[RawExperience] = None
    summary_buf: List[str] = []

    def flush():
        nonlocal current, summary_buf
        if current is not None:
            if summary_buf:
                current.summary = " ".join(summary_buf).strip()
            items.append(current)
        current, summary_buf = None, []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        dm = _DATE_RANGE_RE.search(line)
        is_bullet = bool(re.match(r"^[\-•*·]\s+", line))
        if dm and not is_bullet:
            # new entry header; text before the date range holds title/company
            flush()
            current = RawExperience(start=dm.group("start"), end=dm.group("end"))
            head = line[: dm.start()].strip(" ,|—-–").strip()
            title, company = _split_title_company(head)
            current.title, current.company = title, company
        elif current is not None:
            summary_buf.append(re.sub(r"^[\-•*·]\s+", "", line))
        # lines before the first dated entry are ignored (often a blurb)
    flush()
    return items


def _split_title_company(head: str) -> Tuple[Optional[str], Optional[str]]:
    if not head:
        return None, None
    # "Title at Company"
    m = re.split(r"\s+at\s+", head, maxsplit=1, flags=re.I)
    if len(m) == 2:
        return m[0].strip() or None, m[1].strip() or None
    # "Title — Company" / "Title - Company" / "Title | Company"
    for sep in ["—", "–", " - ", "|"]:
        if sep in head:
            a, b = head.split(sep, 1)
            return a.strip() or None, b.strip() or None
    # "Title, Company"
    if "," in head:
        a, b = head.split(",", 1)
        return a.strip() or None, b.strip() or None
    return head.strip() or None, None


def _parse_education(lines: List[str]) -> List[RawEducation]:
    """Parse lines like 'B.S. in Computer Science, UC Berkeley, 2018'.

    Strategy per comma-separated part: a leading degree token yields degree (+
    any trailing 'in <field>'); a part containing an institution keyword yields
    institution; the remaining unclassified part is taken as the institution.
    """
    items: List[RawEducation] = []
    for raw in lines:
        line = raw.strip().lstrip("-•*· ").strip()
        if not line:
            continue
        year = None
        ym = re.search(r"(19|20)\d{2}", line)
        if ym:
            year = ym.group(0)

        parts = [p.strip() for p in line.split(",") if p.strip()]
        degree = field = institution = None
        leftovers = []
        for p in parts:
            if re.fullmatch(r"(19|20)\d{2}", p):
                continue  # the year, already captured
            dm = _DEGREE_RE.match(p)
            if dm and degree is None:
                degree = dm.group(1).strip()
                rest = p[dm.end():].strip(" .,-")
                rest = re.sub(r"^(in|of)\s+", "", rest, flags=re.I).strip()
                if rest:
                    field = rest
                continue
            if any(k in p.lower() for k in _INSTITUTION_KEYWORDS) and institution is None:
                institution = p
                continue
            leftovers.append(p)

        if institution is None and leftovers:
            institution = leftovers.pop(0)
        if field is None and leftovers:
            field = leftovers[0]

        if degree or institution or field or year:
            items.append(RawEducation(institution=institution, degree=degree,
                                       field=field, end_year=year))
    return items


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #
class ResumeAdapter(SourceAdapter):
    name = "resume"

    def extract(self, path: str) -> List[RawCandidate]:
        text = extract_text(path)
        if not text or not text.strip():
            return []
        lines = [ln.rstrip() for ln in text.splitlines()]
        cand = RawCandidate(source=self.name)

        # contact info can appear anywhere; scan whole doc
        emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))
        cand.emails = emails
        phones = []
        for m in _PHONE_RE.findall(text):
            digits = re.sub(r"\D", "", m)
            if 7 <= len(digits) <= 15:
                phones.append(m.strip())
        cand.phones = list(dict.fromkeys(phones))
        for url in _URL_RE.findall(text):
            low = url.lower()
            if "linkedin" in low and not cand.linkedin:
                cand.linkedin = url
            elif "github" in low and not cand.github:
                cand.github = url

        header, sections = _split_sections(lines)

        # name = first header line that looks like a name; headline = next
        # meaningful header line that isn't the contact line
        non_empty = [h for h in header if h.strip()]
        for i, h in enumerate(non_empty):
            if _looks_like_name(h):
                cand.full_name = h.strip()
                for nxt in non_empty[i + 1:]:
                    if "@" not in nxt and not _PHONE_RE.search(nxt) and "|" not in nxt \
                            and not _URL_RE.search(nxt):
                        cand.headline = nxt.strip()
                        break
                break

        if "skills" in sections:
            blob = " , ".join(sections["skills"])
            cand.skills = [s.strip(" -•*·") for s in re.split(r"[,\n|/]", blob) if s.strip(" -•*·")]
        if "experience" in sections:
            cand.experience = _parse_experience(sections["experience"])
        if "education" in sections:
            cand.education = _parse_education(sections["education"])

        return [cand] if (cand.full_name or cand.emails) else []
