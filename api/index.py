"""Vercel serverless entry point for the web UI.

Vercel's ``@vercel/python`` runtime serves the module-level ``app`` (a WSGI
callable). This thin shim exists only so the ``src``-layout package is importable
inside the serverless bundle; all real logic lives in
``candidate_transformer.web``.

Locally you do NOT need this file — just run::

    python -m candidate_transformer.web        # http://127.0.0.1:5000
"""
import os
import sys

# src-layout: make the package importable from the serverless bundle root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from candidate_transformer.web import create_app  # noqa: E402

# Vercel looks for a WSGI/ASGI app named ``app`` in files under api/.
app = create_app()
