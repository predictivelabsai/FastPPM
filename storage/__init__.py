"""Pluggable storage for FastPPM.

The active backend is chosen by the ``DATA_STORAGE`` environment variable. Phase
1 ships a single relational backend (``sqlite``, also Postgres via ``DB_URL``);
the factory leaves room for additional backends without touching callers.

Callers use ``get_store()`` (or the ``ppmstore`` compat shim) and never import a
concrete backend, so swapping is a one-line env change.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from .base import Storage, utcnow

load_dotenv()

_store: Storage | None = None


def get_store() -> Storage:
    """Return the process-wide storage backend singleton."""
    global _store
    if _store is None:
        _store = _build_store()
    return _store


def _build_store() -> Storage:
    backend = os.environ.get("DATA_STORAGE", "sqlite").strip().lower()
    if backend == "sqlite":
        from .sqlite_store import SqliteStore
        return SqliteStore()
    raise ValueError(
        f"Unknown DATA_STORAGE={backend!r}; expected 'sqlite' "
        "(also reaches Postgres via DB_URL)."
    )


def reset_store() -> None:
    """Drop the cached singleton (tests use this to rebuild against a fresh db)."""
    global _store
    _store = None


__all__ = ["Storage", "get_store", "reset_store", "utcnow"]
