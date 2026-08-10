"""Relational engine ownership for FastPPM."""

from database_pool import dispose_database_pools, get_engine


def test_engine_is_singleton_per_url(tmp_path):
    dispose_database_pools()
    url = f"sqlite:///{tmp_path / 'ppm.db'}"
    assert get_engine(url) is get_engine(url)
    dispose_database_pools()
