"""Tests for the structured analytics datasets that drive the chart UI.

Each builder must return a self-describing Dataset (typed columns + rows + the
x/measure mapping) computed from the canonical store, and ``chart_options`` must
recommend a sensible chart type from the data shape.
"""

from __future__ import annotations

import pytest

from agents import analytics as an


@pytest.fixture
def seeded(store):
    """A small but representative programme: a few initiatives, risks, value."""
    store.upsert_initiative({"ref": "VCP", "name": "Value Creation Plan", "type": "program"})
    common = {"type": "workstream", "parent_ref": "VCP"}
    store.upsert_initiative({**common, "ref": "WS-1", "name": "Pricing", "workstream": "Commercial",
                             "status": "on_track", "rag": "G", "progress": 70,
                             "value_target": 4_000_000, "value_realized": 2_000_000,
                             "value_category": "ebitda"})
    store.upsert_initiative({**common, "ref": "WS-2", "name": "ERP", "workstream": "Technology",
                             "status": "at_risk", "rag": "A", "progress": 40,
                             "value_target": 3_000_000, "value_realized": 600_000,
                             "value_category": "cost_savings"})
    store.upsert_initiative({**common, "ref": "WS-3", "name": "CRM", "workstream": "Technology",
                             "status": "delayed", "rag": "R", "progress": 20,
                             "value_target": 1_000_000, "value_realized": 100_000,
                             "value_category": "ebitda"})
    rid = store.get_initiative_by_ref("WS-2")["id"]
    store.upsert_risk({"initiative_id": rid, "description": "Vendor lock-in on the ERP platform",
                       "probability": 4, "impact": 5})
    store.upsert_risk({"initiative_id": rid, "description": "Data migration slippage",
                       "probability": 3, "impact": 3})
    store.add_value_entry({"initiative_id": rid, "period": "2026-Q1", "category": "ebitda",
                           "planned": 200_000, "realized": 150_000})
    store.add_value_entry({"initiative_id": rid, "period": "2026-Q2", "category": "ebitda",
                           "planned": 400_000, "realized": 300_000})
    return store


def test_dataset_serialization_roundtrip(seeded):
    ds = an.value_by_category()
    d = ds.as_dict()
    # Self-describing: title, typed columns, rows, mapping, and chart options.
    assert d["title"] and d["x"] == "category" and d["y"] == ["realized", "target"]
    assert {c["key"] for c in d["columns"]} == {"category", "realized", "target"}
    assert "recommended" in d and "offered" in d
    # Every row carries exactly the declared column keys.
    keys = {c["key"] for c in d["columns"]}
    assert all(set(r) == keys for r in d["rows"])


def test_value_by_category_numbers(seeded):
    ds = an.value_by_category()
    ebitda = next(r for r in ds.rows if r["category"] == "Ebitda")
    assert ebitda["realized"] == 2_100_000  # Pricing 2.0m + CRM 0.1m
    assert ebitda["target"] == 5_000_000    # Pricing 4.0m + CRM 1.0m


def test_rag_breakdown_counts_and_colors(seeded):
    ds = an.rag_breakdown()
    counts = {r["status"]: r["count"] for r in ds.rows}
    assert counts == {"Green": 1, "Amber": 1, "Red": 1}
    assert ds.meta["colors"]["Red"] == "#c0392b"


def test_status_breakdown(seeded):
    ds = an.status_breakdown()
    counts = {r["status"]: r["count"] for r in ds.rows}
    assert counts.get("On track") == 1 and counts.get("At risk") == 1
    # Sorted by count descending.
    assert ds.rows == sorted(ds.rows, key=lambda r: -r["count"])


def test_progress_by_initiative_lowest_first(seeded):
    ds = an.progress_by_initiative()
    assert [r["initiative"] for r in ds.rows] == ["CRM", "ERP", "Pricing"]
    assert ds.rows[0]["progress"] == 20


def test_progress_by_workstream_averages(seeded):
    ds = an.progress_by_workstream()
    by_ws = {r["workstream"]: r["progress"] for r in ds.rows}
    assert by_ws["Commercial"] == 70
    assert by_ws["Technology"] == 30  # mean(40, 20)


def test_top_risks_scored_and_ranked(seeded):
    ds = an.top_risks()
    assert ds.rows[0]["score"] == 20  # 4 × 5, ranked first
    assert ds.rows[0]["initiative"] == "ERP"
    assert [r["score"] for r in ds.rows] == sorted((r["score"] for r in ds.rows), reverse=True)


def test_value_over_time_is_temporal_series(seeded):
    ds = an.value_over_time()
    assert [r["period"] for r in ds.rows] == ["2026-Q1", "2026-Q2"]
    assert ds.rows[1]["realized"] == 300_000


# ── chart_options heuristics ────────────────────────────────────────────────

def test_chart_options_temporal_recommends_line(seeded):
    assert an.chart_options(an.value_over_time())["recommended"] == "line"


def test_chart_options_categorical_recommends_bar_offers_pie(seeded):
    opt = an.chart_options(an.rag_breakdown())
    assert opt["recommended"] == "bar"
    assert "pie" in opt["offered"]


def test_chart_options_single_value_recommends_kpi():
    ds = an.Dataset(id="x", title="t", columns=[an.Column("k", "K", an.CATEGORY),
                    an.Column("v", "V", an.NUMBER)],
                    rows=[{"k": "Total", "v": 42}], x="k", y=["v"])
    assert an.chart_options(ds)["recommended"] == "kpi"


def test_chart_options_high_cardinality_drops_pie():
    rows = [{"k": f"i{n}", "v": n} for n in range(20)]
    ds = an.Dataset(id="x", title="t", columns=[an.Column("k", "K", an.CATEGORY),
                    an.Column("v", "V", an.NUMBER)], rows=rows, x="k", y=["v"])
    assert an.chart_options(ds)["offered"] == ["bar"]


def test_build_dispatch_and_unknown(seeded):
    assert an.build("top_risks").id == "top_risks"
    with pytest.raises(KeyError):
        an.build("does_not_exist")
