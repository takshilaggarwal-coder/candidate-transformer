"""Output validation.

Two entry points:
  * ``validate_default`` checks a full canonical dict against the fixed default
    schema (shape/types of every field).
  * ``validate_against_config`` checks a projected dict against the *requested*
    schema declared in the runtime config (declared types + required).

Validation is hand-written rather than pulling in jsonschema; the rule set is
small enough that the checks stay readable. Errors are collected and returned
as a list so the caller can report all problems at once; ``validate_or_raise``
turns them into an exception.
"""
from __future__ import annotations

from typing import Any, List

from .config import OutputConfig


class ValidationError(Exception):
    pass


# field -> (python type check). "opt" means None is allowed.
def _is_str(v): return isinstance(v, str)
def _is_num(v): return isinstance(v, (int, float)) and not isinstance(v, bool)
def _is_int(v): return isinstance(v, int) and not isinstance(v, bool)
def _is_bool(v): return isinstance(v, bool)


_TYPE_CHECKERS = {
    "string": _is_str,
    "number": _is_num,
    "integer": _is_int,
    "boolean": _is_bool,
    "object": lambda v: isinstance(v, dict),
    "any": lambda v: True,
    "string[]": lambda v: isinstance(v, list) and all(_is_str(x) for x in v),
    "number[]": lambda v: isinstance(v, list) and all(_is_num(x) for x in v),
    "object[]": lambda v: isinstance(v, list) and all(isinstance(x, dict) for x in v),
}


def _get_nested(obj: dict, dotted: str):
    node = obj
    present = True
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            present = False
            node = None
            break
    return present, node


# --------------------------------------------------------------------------- #
# Default schema
# --------------------------------------------------------------------------- #
_DEFAULT_SCHEMA = {
    "candidate_id": "string",
    "full_name": "string?",
    "emails": "string[]",
    "phones": "string[]",
    "location": "object",
    "links": "object",
    "headline": "string?",
    "years_experience": "number?",
    "skills": "object[]",
    "experience": "object[]",
    "education": "object[]",
    "provenance": "object[]",
    "overall_confidence": "number",
}


def validate_default(profile: dict) -> List[str]:
    errors: List[str] = []
    for fieldname, typ in _DEFAULT_SCHEMA.items():
        optional = typ.endswith("?")
        base = typ.rstrip("?")
        if fieldname not in profile:
            errors.append(f"default schema: missing field '{fieldname}'")
            continue
        value = profile[fieldname]
        if value is None:
            if not optional:
                errors.append(f"default schema: field '{fieldname}' must not be null")
            continue
        if not _TYPE_CHECKERS[base](value):
            errors.append(f"default schema: field '{fieldname}' expected {base}, "
                          f"got {type(value).__name__}")
    # spot-check E.164 phone shape
    for ph in profile.get("phones", []) or []:
        if not (isinstance(ph, str) and ph.startswith("+")):
            errors.append(f"default schema: phone '{ph}' is not E.164 (+...)")
    return errors


# --------------------------------------------------------------------------- #
# Config-driven schema
# --------------------------------------------------------------------------- #
def validate_against_config(out: dict, config: OutputConfig) -> List[str]:
    errors: List[str] = []
    for spec in config.fields:
        present, value = _get_nested(out, spec.path)
        if not present or value is None:
            if spec.required:
                errors.append(f"required field '{spec.path}' is missing or null")
            continue  # optional + absent/null is fine
        checker = _TYPE_CHECKERS.get(spec.type, lambda v: True)
        if not checker(value):
            errors.append(f"field '{spec.path}' expected {spec.type}, "
                          f"got {type(value).__name__}")
    return errors


def validate_or_raise(errors: List[str]) -> None:
    if errors:
        raise ValidationError("output failed validation:\n  - " + "\n  - ".join(errors))
