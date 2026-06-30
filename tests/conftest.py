"""Pytest setup: put ``src`` on sys.path and expose sample-input paths.

We keep the package under ``src/`` (src-layout) so tests import it the same way
an installed package would. No editable install needed to run the suite.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

SAMPLES = os.path.join(ROOT, "samples", "inputs")


@pytest.fixture(scope="session")
def samples_dir():
    return SAMPLES


@pytest.fixture(scope="session")
def all_sources():
    """The five sample inputs, as (path, explicit_type) pairs.

    ``garbage.json`` is intentionally malformed; the type is forced so we
    exercise the JSON adapter's failure path (not just type detection).
    """
    return [
        (os.path.join(SAMPLES, "recruiters.csv"), None),
        (os.path.join(SAMPLES, "ats.json"), None),
        (os.path.join(SAMPLES, "resume_jane_doe.pdf"), None),
        (os.path.join(SAMPLES, "resume_raj_patel.docx"), None),
        (os.path.join(SAMPLES, "notes.txt"), None),
        (os.path.join(SAMPLES, "garbage.json"), "ats_json"),
    ]
