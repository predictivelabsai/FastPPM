"""Test fixtures for FastPPM.

Each test runs against a throwaway SQLite database so nothing touches the dev db.
The store is the single source of truth, exercised through the public facade.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh SqliteStore backed by a temp-file db, schema initialised."""
    monkeypatch.setenv("DATA_STORAGE", "sqlite")
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path/'test.db'}")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pass")

    import storage
    storage.reset_store()
    s = storage.get_store()
    s.init_db()
    yield s
    storage.reset_store()
