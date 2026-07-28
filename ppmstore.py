"""FastPPM storage — facade.

Storage is pluggable (see the ``storage`` package, selected by ``DATA_STORAGE``).
This module is the import surface every caller uses: ``import ppmstore as store``,
then ``store.<method>(...)`` is forwarded to the active backend instance — so the
web app, seed loader and agents are decoupled from the concrete backend.
"""

from __future__ import annotations

from storage import get_store, reset_store, utcnow  # noqa: F401  (re-exported)


def __getattr__(name: str):
    """Forward any attribute access to the configured storage backend.

    e.g. ``store.upsert_project(...)`` → ``get_store().upsert_project(...)``.
    """
    return getattr(get_store(), name)


if __name__ == "__main__":
    store = get_store()
    store.init_db()
    print("Initialized FastPPM storage:", type(store).__name__)
    print(store.portfolio_summary())
