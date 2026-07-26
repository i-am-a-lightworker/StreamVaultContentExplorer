"""Shared test helpers for the StreamVault regression suite."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import runpy


@lru_cache(maxsize=1)
def load_app() -> dict:
    """Load the application functions once for the whole test run."""
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    return runpy.run_path(str(app_path))
