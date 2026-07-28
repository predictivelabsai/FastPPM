"""The show_statistics tool: hands a structured dataset to the request-scoped
sink (out-of-band, via RunnableConfig) while returning only a short summary to
the LLM, and honours the LLM's chart_type pick.
"""

from __future__ import annotations

import pytest

from agents import tools


@pytest.fixture
def seeded(store):
    store.upsert_initiative({"ref": "VCP", "name": "Value Creation Plan", "type": "program"})
    common = {"type": "workstream", "parent_ref": "VCP"}
    store.upsert_initiative({**common, "ref": "WS-1", "name": "Pricing", "status": "on_track",
                             "rag": "G", "progress": 70, "value_target": 4_000_000,
                             "value_realized": 2_000_000, "value_category": "ebitda"})
    store.upsert_initiative({**common, "ref": "WS-2", "name": "ERP", "status": "at_risk",
                             "rag": "A", "progress": 40, "value_target": 3_000_000,
                             "value_realized": 600_000, "value_category": "cost_savings"})
    store.upsert_initiative({**common, "ref": "WS-3", "name": "CRM", "status": "delayed",
                             "rag": "R", "progress": 20, "value_target": 1_000_000,
                             "value_realized": 100_000, "value_category": "ebitda"})
    return store


def _call(metric, chart_type="", sink=None):
    config = {"configurable": {"dataset_sink": sink}} if sink is not None else {}
    return tools.show_statistics.invoke(
        {"metric": metric, "chart_type": chart_type}, config=config)


def test_returns_summary_not_figures_and_stashes_dataset(seeded):
    sink: list[dict] = []
    out = _call("value_by_category", "bar", sink)
    # The LLM sees a short one-line summary, not a restated table of figures.
    assert isinstance(out, str) and len(out) < 200 and "\n" not in out
    # The dataset is handed to the UI out-of-band.
    assert len(sink) == 1
    ds = sink[0]
    assert ds["id"] == "value_by_category" and ds["rows"]
    assert {"columns", "x", "y", "recommended", "offered"} <= ds.keys()


def test_llm_chart_pick_overrides_default(seeded):
    sink: list[dict] = []
    _call("value_by_category", "pie", sink)
    assert sink[0]["recommended"] == "pie"
    assert "pie" in sink[0]["offered"]


def test_invalid_chart_type_falls_back_to_deterministic(seeded):
    sink: list[dict] = []
    _call("rag_breakdown", "spaghetti", sink)
    assert sink[0]["recommended"] == "bar"  # deterministic default stands


def test_unknown_metric_is_reported_not_stashed(seeded):
    sink: list[dict] = []
    out = _call("nonsense_metric", "bar", sink)
    assert "unknown metric" in out.lower()
    assert sink == []


def test_works_without_a_sink(seeded):
    # No sink in config (e.g. a non-streaming caller) must not error.
    out = _call("rag_breakdown", "bar", sink=None)
    assert isinstance(out, str) and out


def test_registered_in_all_tools():
    assert tools.show_statistics in tools.ALL_TOOLS
