"""Structured analytics datasets for the conversational copilot.

The chat tools return prose; these builders return a typed ``Dataset`` (columns +
rows + the natural x / measure mapping) computed from the canonical store — real
numbers, never LLM-invented. A ``Dataset`` is what the UI turns into a table and,
on request, a chart. ``chart_options`` derives which chart types make sense from
the data shape (temporal → line, categorical → bar/pie, single value → KPI).

Numbers are kept raw (£, %, counts); formatting is a presentation concern. Each
builder is keyed in ``BUILDERS`` so the tool / orchestrator layer can dispatch by
metric name.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ppmstore as store

# Column value types — drive both table formatting and chart-axis handling.
CATEGORY, NUMBER, CURRENCY, PCT, DATE = "category", "number", "currency", "pct", "date"


@dataclass
class Column:
    key: str
    label: str
    type: str = NUMBER


@dataclass
class Dataset:
    """A small, self-describing result set ready to table or chart."""
    id: str
    title: str
    columns: list[Column]
    rows: list[dict]
    x: str                       # category / dimension column key
    y: list[str]                 # measure column key(s)
    series: str | None = None    # optional grouping column
    note: str = ""               # one-line prose summary (for the LLM / fallback)
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {"id": self.id, "title": self.title,
             "columns": [vars(c) for c in self.columns], "rows": self.rows,
             "x": self.x, "y": self.y, "series": self.series, "note": self.note,
             "meta": dict(self.meta)}
        d.update(chart_options(self))
        return d


# ── Chart-type selection ────────────────────────────────────────────────────

def _col(ds: Dataset, key: str) -> Column | None:
    return next((c for c in ds.columns if c.key == key), None)


def chart_options(ds: Dataset) -> dict:
    """Which chart types fit this dataset, and the deterministic default.

    Used to populate the offer chips and as the fallback recommendation when the
    LLM does not pick one. Rules: a single value → KPI; a temporal dimension →
    line; otherwise a categorical comparison → bar, with pie offered as a
    parts-of-whole alternative for low-cardinality results.
    """
    n = len(ds.rows)
    xcol = _col(ds, ds.x)
    measures = [m for m in ds.y if _col(ds, m)]
    if n <= 1 and len(measures) <= 1:
        return {"recommended": "kpi", "offered": ["kpi", "bar"]}
    if xcol and xcol.type == DATE:
        return {"recommended": "line", "offered": ["line", "bar"]}
    offered = ["bar"]
    if n <= 12:
        offered.append("pie")  # pie charts the primary (first) measure
    return {"recommended": "bar", "offered": offered}


# ── Money helper (raw → £m/£k for the prose note) ───────────────────────────

def _m(v) -> str:
    v = float(v or 0)
    if abs(v) >= 1e6:
        return f"£{v/1e6:.1f}m"
    if abs(v) >= 1e3:
        return f"£{v/1e3:.0f}k"
    return f"£{v:.0f}"


def _deliverables() -> list[dict]:
    """Initiatives that carry value/progress (excludes the umbrella programme)."""
    return [i for i in store.list_initiatives() if i.get("type") != "program"]


# ── Dataset builders ────────────────────────────────────────────────────────

_RAG_LABEL = {"G": "Green", "A": "Amber", "R": "Red"}
_STATUS_LABEL = {"not_started": "Not started", "in_progress": "In progress",
                 "on_track": "On track", "at_risk": "At risk", "delayed": "Delayed",
                 "complete": "Complete", "on_hold": "On hold"}


def value_by_category() -> Dataset:
    """Value realised vs target, split by value category (EBITDA, cost…)."""
    cats = store.value_summary().get("by_category", [])
    rows = [{"category": (c["category"] or "—").replace("_", " ").title(),
             "realized": round(float(c["realized"] or 0)),
             "target": round(float(c["target"] or 0))}
            for c in cats]
    total = sum(r["realized"] for r in rows)
    return Dataset(
        id="value_by_category", title="Value realised vs target by category",
        columns=[Column("category", "Category", CATEGORY),
                 Column("realized", "Realised", CURRENCY),
                 Column("target", "Target", CURRENCY)],
        rows=rows, x="category", y=["realized", "target"],
        note=f"{_m(total)} realised across {len(rows)} value categories.")


def rag_breakdown() -> Dataset:
    """Active-initiative counts by RAG health (Red / Amber / Green)."""
    rag = store.portfolio_summary().get("rag", {})
    rows = [{"status": _RAG_LABEL.get(k, k), "count": int(v)}
            for k, v in (("G", rag.get("G", 0)), ("A", rag.get("A", 0)),
                         ("R", rag.get("R", 0))) if v]
    total = sum(r["count"] for r in rows)
    return Dataset(
        id="rag_breakdown", title="Initiatives by RAG status",
        columns=[Column("status", "RAG", CATEGORY), Column("count", "Initiatives", NUMBER)],
        rows=rows, x="status", y=["count"],
        meta={"colors": {"Green": "#1c7c44", "Amber": "#b06b00", "Red": "#c0392b"}},
        note=f"{total} active initiatives by RAG health.")


def status_breakdown() -> Dataset:
    """Initiative counts by workflow status (on track, at risk, delayed…)."""
    statuses = store.portfolio_summary().get("statuses", {})
    rows = [{"status": _STATUS_LABEL.get(k, (k or "—").replace("_", " ").title()),
             "count": int(v)} for k, v in statuses.items() if v]
    rows.sort(key=lambda r: -r["count"])
    return Dataset(
        id="status_breakdown", title="Initiatives by status",
        columns=[Column("status", "Status", CATEGORY), Column("count", "Initiatives", NUMBER)],
        rows=rows, x="status", y=["count"],
        note=f"{sum(r['count'] for r in rows)} initiatives across {len(rows)} statuses.")


def progress_by_initiative(limit: int = 12) -> Dataset:
    """Percent-complete for each deliverable initiative (lowest first)."""
    inis = sorted(_deliverables(), key=lambda i: float(i.get("progress") or 0))
    rows = [{"initiative": i["name"], "progress": round(float(i.get("progress") or 0))}
            for i in inis[:limit]]
    return Dataset(
        id="progress_by_initiative", title="Progress by initiative",
        columns=[Column("initiative", "Initiative", CATEGORY),
                 Column("progress", "Progress %", PCT)],
        rows=rows, x="initiative", y=["progress"],
        note=f"Progress for {len(rows)} initiatives (lowest first).")


def progress_by_workstream() -> Dataset:
    """Average percent-complete grouped by workstream."""
    agg: dict[str, list[float]] = {}
    for i in _deliverables():
        ws = i.get("workstream") or "Unassigned"
        agg.setdefault(ws, []).append(float(i.get("progress") or 0))
    rows = [{"workstream": ws, "progress": round(sum(v) / len(v))}
            for ws, v in agg.items() if v]
    rows.sort(key=lambda r: -r["progress"])
    return Dataset(
        id="progress_by_workstream", title="Average progress by workstream",
        columns=[Column("workstream", "Workstream", CATEGORY),
                 Column("progress", "Avg progress %", PCT)],
        rows=rows, x="workstream", y=["progress"],
        note=f"Average progress across {len(rows)} workstreams.")


def top_risks(limit: int = 8) -> Dataset:
    """Highest-exposure risks, scored by probability × impact."""
    risks = store.list_risks()
    rows = []
    for r in risks[:limit]:
        score = int((r.get("probability") or 0) * (r.get("impact") or 0))
        desc = r.get("description") or "—"
        rows.append({"risk": desc[:60] + ("…" if len(desc) > 60 else ""),
                     "initiative": r.get("initiative_name") or "—", "score": score})
    return Dataset(
        id="top_risks", title="Top risks by exposure (probability × impact)",
        columns=[Column("risk", "Risk", CATEGORY),
                 Column("initiative", "Initiative", CATEGORY),
                 Column("score", "Exposure", NUMBER)],
        rows=rows, x="risk", y=["score"],
        note=f"Top {len(rows)} risks by probability × impact.")


def value_over_time() -> Dataset:
    """Value realised vs planned by period (a time series)."""
    periods = store.value_summary().get("by_period", [])
    rows = [{"period": p["period"], "realized": round(float(p["realized"] or 0)),
             "planned": round(float(p["planned"] or 0))} for p in periods]
    return Dataset(
        id="value_over_time", title="Value realised over time",
        columns=[Column("period", "Period", DATE),
                 Column("realized", "Realised", CURRENCY),
                 Column("planned", "Planned", CURRENCY)],
        rows=rows, x="period", y=["realized", "planned"],
        note=f"Value trend across {len(rows)} periods.")


# ── Registry / dispatch ─────────────────────────────────────────────────────

BUILDERS = {
    "value_by_category": value_by_category,
    "rag_breakdown": rag_breakdown,
    "status_breakdown": status_breakdown,
    "progress_by_initiative": progress_by_initiative,
    "progress_by_workstream": progress_by_workstream,
    "top_risks": top_risks,
    "value_over_time": value_over_time,
}


def build(metric: str) -> Dataset:
    """Build a dataset by metric key. Raises KeyError for an unknown metric."""
    return BUILDERS[metric]()
