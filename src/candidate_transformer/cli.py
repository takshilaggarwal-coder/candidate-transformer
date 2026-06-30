"""Command-line interface.

Examples
--------
Default schema, auto-detected source types, pretty JSON to stdout:

    python -m candidate_transformer \
        --source samples/inputs/recruiters.csv \
        --source samples/inputs/ats.json \
        --source samples/inputs/resume_jane_doe.pdf \
        --source samples/inputs/notes.txt

Custom config, explicit type override, write to a file:

    python -m candidate_transformer \
        --source recruiter_csv=samples/inputs/recruiters.csv \
        --config configs/custom_example.json \
        --out out.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List

from .config import OutputConfig
from .pipeline import SourceSpec, run
from .sources import ADAPTERS


def _parse_source(token: str) -> SourceSpec:
    """Accept 'type=path' (explicit) or 'path' (auto-detect)."""
    if "=" in token:
        maybe_type, _, rest = token.partition("=")
        if maybe_type in ADAPTERS:
            return SourceSpec(path=rest, type=maybe_type)
    return SourceSpec(path=token, type=None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="candidate_transformer",
        description="Merge multi-source candidate data into one canonical profile.",
    )
    p.add_argument("--source", "-s", action="append", default=[], metavar="[TYPE=]PATH",
                   help="Input source. Repeatable. Prefix with 'type=' to override "
                        f"auto-detection. Types: {sorted(ADAPTERS)}")
    p.add_argument("--config", "-c", metavar="PATH",
                   help="Custom output-config JSON. Omit for the default schema.")
    p.add_argument("--out", "-o", metavar="PATH",
                   help="Write JSON here. Default: stdout.")
    p.add_argument("--no-validate", action="store_true",
                   help="Skip output validation (not recommended).")
    p.add_argument("--quiet", "-q", action="store_true", help="Suppress warning logs.")
    p.add_argument("--canonical", action="store_true",
                   help="Also include the internal canonical records under '_canonical'.")
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="[%(levelname)s] %(message)s", stream=sys.stderr,
    )

    if not args.source:
        print("error: at least one --source is required", file=sys.stderr)
        return 2

    sources = [_parse_source(s) for s in args.source]
    config = OutputConfig.load(args.config) if args.config else None

    result = run(sources, config=config, validate=not args.no_validate)

    for w in result.warnings:
        logging.getLogger("candidate_transformer").warning(w)

    payload: object = result.outputs
    if args.canonical:
        payload = {
            "candidates": result.outputs,
            "_canonical": [p.to_dict() for p in result.profiles],
            "warnings": result.warnings,
        }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {len(result.outputs)} candidate(s) -> {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
