"""Skill canonicalization.

Maps noisy free-text skill mentions ("js", "React.js", "node") onto a small
controlled vocabulary of canonical names ("JavaScript", "React", "Node.js").

The table is a deterministic alias map, not a fuzzy matcher. An unknown skill
is passed through with light title-casing rather than being mapped to the
nearest known skill.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# Canonical name -> list of lowercase aliases (the canonical name is always an
# implicit alias of itself).
_CANONICAL_SKILLS: Dict[str, list] = {
    "Python": ["python", "py", "python3"],
    "JavaScript": ["javascript", "js", "ecmascript", "java script"],
    "TypeScript": ["typescript", "ts"],
    "Java": ["java"],
    "C++": ["c++", "cpp", "cplusplus"],
    "C#": ["c#", "csharp", "c sharp"],
    "Go": ["go", "golang"],
    "Rust": ["rust"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "SQL": ["sql"],
    "React": ["react", "react.js", "reactjs"],
    "Angular": ["angular", "angular.js", "angularjs"],
    "Vue.js": ["vue", "vue.js", "vuejs"],
    "Node.js": ["node", "node.js", "nodejs"],
    "Django": ["django"],
    "Flask": ["flask"],
    "Spring": ["spring", "spring boot", "springboot"],
    "TensorFlow": ["tensorflow", "tensor flow", "tf"],
    "PyTorch": ["pytorch", "torch"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy", "np"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Azure": ["azure", "microsoft azure"],
    "PostgreSQL": ["postgresql", "postgres", "psql"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Kafka": ["kafka", "apache kafka"],
    "Git": ["git"],
    "Linux": ["linux"],
    "GraphQL": ["graphql", "graph ql"],
    "REST": ["rest", "rest api", "restful"],
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning", "dl"],
    "NLP": ["nlp", "natural language processing"],
    "Data Analysis": ["data analysis", "data analytics"],
}

# Build reverse lookup: alias -> canonical. Built once at import time.
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for _canon, _aliases in _CANONICAL_SKILLS.items():
    _ALIAS_TO_CANONICAL[_canon.lower()] = _canon
    for _a in _aliases:
        _ALIAS_TO_CANONICAL[_a] = _canon


def _clean(raw: str) -> str:
    """Lowercase, trim, collapse internal whitespace and stray punctuation."""
    s = raw.strip().lower()
    s = re.sub(r"\s+", " ", s)
    # strip surrounding punctuation but keep meaningful symbols like + and #
    s = s.strip(" .,;:|/")
    return s


def canonicalize_skill(raw: str) -> Optional[str]:
    """Return the canonical skill name for a raw mention, or a title-cased
    pass-through for unknown skills. Returns None for empty/garbage input.
    """
    if not raw or not raw.strip():
        return None
    key = _clean(raw)
    if not key:
        return None
    if key in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[key]
    # Unknown skill: don't guess a mapping. Preserve it with conservative
    # casing so it still de-duplicates against itself across sources.
    if key.isupper() or len(key) <= 3:
        return key.upper()
    return " ".join(w.capitalize() for w in key.split(" "))


def is_known_skill(raw: str) -> bool:
    """True if the raw mention maps to a known canonical skill."""
    if not raw:
        return False
    return _clean(raw) in _ALIAS_TO_CANONICAL
