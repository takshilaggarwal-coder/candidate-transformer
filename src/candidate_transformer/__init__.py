"""Multi-source candidate data transformer.

Public API:
    from candidate_transformer import run, SourceSpec, OutputConfig
"""
from .canonical import CanonicalProfile
from .config import OutputConfig
from .pipeline import PipelineResult, SourceSpec, run

__all__ = ["run", "SourceSpec", "OutputConfig", "PipelineResult", "CanonicalProfile"]
__version__ = "1.0.0"
