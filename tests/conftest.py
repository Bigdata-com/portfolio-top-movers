"""
Pytest configuration: isolate the SQLite DB and default env before importing the app.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="portfolio-top-movers-test-"))
os.environ["DB_STRING"] = f"sqlite:///{_tmp / 'jobs.sqlite'}"


@pytest.fixture(autouse=True)
def clear_jobs() -> None:
    """Reset job storage between tests."""
    from services.job_storage import job_storage

    job_storage.clear_all()
    yield
