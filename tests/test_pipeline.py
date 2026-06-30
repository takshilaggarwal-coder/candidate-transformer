"""End-to-end pipeline tests over the real sample inputs.

These exercise the whole chain (detect -> extract -> normalize -> merge ->
project -> validate) and lock in the cross-source behaviours that matter:
the location collision fix, conflict resolution, robustness to a garbage file,
determinism, and the required-field drop policy.
"""
import json
import os

import pytest

from candidate_transformer.config import OutputConfig
from candidate_transformer.pipeline import SourceSpec, run

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIGS = os.path.join(ROOT, "configs")
GOLD = os.path.join(HERE, "gold")


@pytest.fixture(scope="module")
def specs(all_sources):
    return [SourceSpec(path=p, type=t) for p, t in all_sources]


def _by_name(outputs, name):
    return next(o for o in outputs if o.get("full_name") == name)


# --------------------------------------------------------------------------- #
# Default run over all sources
# --------------------------------------------------------------------------- #
def test_default_run_produces_all_candidates(specs):
    result = run(specs)                      # validate=True by default
    names = {o["full_name"] for o in result.outputs}
    assert {"Jane A. Doe", "Raj Patel", "Maria Garcia", "Garbled Row"} <= names


def test_jane_country_is_us_not_canada(specs):
    # regression: "San Francisco, CA" must not resolve CA -> Canada
    jane = _by_name(run(specs).outputs, "Jane A. Doe")
    assert jane["location"]["region"] == "CA"
    assert jane["location"]["country"] == "US"


def test_raj_stale_current_company_resolved(specs):
    # CSV carried Infosys as the current job; resume's real end date wins
    raj = _by_name(run(specs).outputs, "Raj Patel")
    infosys = next(e for e in raj["experience"] if e["company"] == "Infosys")
    assert infosys["end"] == "2022-06"


def test_jane_phone_corroborated_and_e164(specs):
    jane = _by_name(run(specs).outputs, "Jane A. Doe")
    assert jane["phones"] == ["+14155550186"]   # 4 spellings -> one E.164 value


def test_garbage_source_warns_but_does_not_crash(specs):
    result = run(specs)
    assert any("garbage" in w for w in result.warnings)
    # despite the malformed file, real candidates still came through
    assert len(result.outputs) >= 4


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_pipeline_is_deterministic(specs):
    a = run(specs).outputs
    b = run(specs).outputs
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --------------------------------------------------------------------------- #
# Custom config: required-field policy drops contact-less candidates
# --------------------------------------------------------------------------- #
def test_custom_config_drops_candidates_without_required_email(specs):
    cfg = OutputConfig.load(os.path.join(CONFIGS, "custom_example.json"))
    result = run(specs, config=cfg)
    names = {o.get("full_name") for o in result.outputs}
    assert names == {"Jane A. Doe", "Raj Patel"}      # Maria & Garbled dropped
    assert any("Maria" in w or "ba5a6c421b" in w or "failed" in w
               for w in result.warnings)


def test_recruiter_card_shape(specs):
    cfg = OutputConfig.load(os.path.join(CONFIGS, "recruiter_card.json"))
    result = run(specs, config=cfg)
    # the card renames full_name -> "name", so look it up by that key
    jane = next(o for o in result.outputs if o.get("name") == "Jane A. Doe")
    # card omits confidence + provenance entirely
    assert "overall_confidence" not in jane
    assert "provenance" not in jane
    assert jane["email"] == "jane.doe@example.com"
    assert jane["github"] == "https://github.com/janedoe"


# --------------------------------------------------------------------------- #
# Gold-profile snapshot (locks in verified-correct merged output for Jane)
# --------------------------------------------------------------------------- #
def test_jane_matches_gold_profile(specs):
    jane = _by_name(run(specs).outputs, "Jane A. Doe")
    with open(os.path.join(GOLD, "jane_default.json"), encoding="utf-8") as fh:
        gold = json.load(fh)
    assert jane == gold
