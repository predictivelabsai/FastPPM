"""Portfolio dashboard + value views (spec §2 'Portfolio Dashboard', value waterfall)."""

from __future__ import annotations

import plotly.graph_objects as go

import ppmstore as store
from web import charts
from web.ui import (PLOTLY, metric, section_title, money, pct, num, rag_dot,
                    RAG_COLOR, VALUE_CAT_LABELS, status_badge)
from fasthtml.common import *


def _rag_donut(rag):
    order = ["G", "A", "R"]
    labels = {"G": "Green", "A": "Amber", "R": "Red"}
    vals = [rag.get(k, 0) for k in order]
    if sum(vals) == 0:
        return None
    fig = go.Figure(go.Pie(labels=[labels[k] for k in order], values=vals, hole=0.62,
                           marker=dict(colors=[RAG_COLOR[k] for k in order]),
                           textinfo="value", sort=False))
    return charts.render(fig, 280)


def _value_waterfall():
    """Cumulative value: realised by initiative building toward target gap."""
    inis = sorted([i for i in store.list_initiatives() if i["type"] != "program"
                   and (i.get("value_realized") or 0) > 0],
                  key=lambda i: i["value_realized"], reverse=True)[:8]
    if not inis:
        return None
    s = store.value_summary()
    gap = max(0, (s["target"] - s["realized"]))
    labels = [i["name"][:22] for i in inis] + ["Remaining to target", "Target"]
    vals = [i["value_realized"] / 1e6 for i in inis] + [gap / 1e6, s["target"] / 1e6]
    measure = ["relative"] * len(inis) + ["relative", "total"]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measure, x=labels, y=vals,
        text=[f"{v:.1f}" for v in vals], textposition="outside",
        connector=dict(line=dict(color="#cfcfd6")),
        increasing=dict(marker=dict(color="#1c7c44")),
        decreasing=dict(marker=dict(color="#b06b00")),
        totals=dict(marker=dict(color="#123B5D"))))
    fig.update_layout(yaxis_title="Value (£m)", xaxis_tickangle=-30)
    return charts.render(fig, 380)


def _category_bar(by_cat):
    if not by_cat:
        return None
    labels = [VALUE_CAT_LABELS.get(c["category"], c["category"]) for c in by_cat]
    fig = go.Figure()
    fig.add_bar(name="Realised", x=labels, y=[c["realized"] / 1e6 for c in by_cat],
                marker_color="#00A6A6")
    fig.add_bar(name="Target", x=labels, y=[c["target"] / 1e6 for c in by_cat],
                marker_color="#D8E5EA")
    fig.update_layout(barmode="overlay", yaxis_title="£m")
    return charts.render(fig, 280)


def _value_trend():
    entries = store.list_value_entries()
    if not entries:
        return None
    by_period = {}
    for e in entries:
        d = by_period.setdefault(e["period"], {"planned": 0, "realized": 0})
        d["planned"] += e.get("planned") or 0
        d["realized"] += e.get("realized") or 0
    periods = sorted(by_period)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=periods, y=[by_period[p]["planned"] / 1e6 for p in periods],
                             name="Planned", line=dict(color="#7a7a85", dash="dash")))
    fig.add_trace(go.Scatter(x=periods, y=[by_period[p]["realized"] / 1e6 for p in periods],
                             name="Realised", line=dict(color="#1c7c44", width=3)))
    fig.update_layout(yaxis_title="£m (cumulative plan vs actual)")
    return charts.render(fig, 280)


def dashboard_content():
    s = store.portfolio_summary()
    metrics = Div(
        metric("Initiatives", str(s["total_initiatives"]),
               f"{s['types'].get('ai_use_case',0)} AI use cases"),
        metric("On track", pct(s["on_track_pct"]),
               f"{s['rag'].get('G',0)}G · {s['rag'].get('A',0)}A · {s['rag'].get('R',0)}R",
               accent="#1c7c44"),
        metric("Avg progress", pct(s["avg_progress"]), "across initiatives"),
        metric("On-time delivery", pct(s["on_time_pct"]), "milestones"),
        metric("Value realised", money(s["value_realized"]),
               f"{s['realization_pct']}% of {money(s['value_target'])}", accent="#00A6A6"),
        metric("Open risks", str(s["open_risks"]), f"{s['high_risks']} high", accent="#c0392b"),
        cls="metrics")

    activity = store.list_activity(limit=8)
    act_rows = [Tr(Td((a.get("at") or "")[:16].replace("T", " ")),
                   Td(a.get("action")), Td(a.get("detail") or "",
                   style="font-size:12.5px;color:#7a7a85")) for a in activity]

    return (
        PLOTLY,
        section_title("Programme dashboard",
                      "Value Creation Plan 2026 · transformation & AI use-case health"),
        metrics,
        Div(H3("Value waterfall — realised by initiative toward target"),
            _value_waterfall() or P("No value data."), cls="card"),
        Div(
            Div(H3("Programme health (RAG)"), _rag_donut(s["rag"]) or P("No data."), cls="card"),
            Div(H3("Value by category"), _category_bar(store.value_summary()["by_category"]) or P("No data."), cls="card"),
            cls="grid2"),
        Div(
            Div(H3("Planned vs realised (cumulative)"), _value_trend() or P("No data."), cls="card"),
            Div(H3("Recent activity"),
                Table(Thead(Tr(Th("When"), Th("Action"), Th("Detail"))), Tbody(*act_rows))
                if act_rows else P("No activity yet."), cls="card"),
            cls="grid2"),
    )


def value_content():
    s = store.value_summary()
    inis = sorted([i for i in store.list_initiatives() if i["type"] != "program"],
                  key=lambda i: (i.get("value_realized") or 0), reverse=True)
    rows = [Tr(
        Td(A(i["name"], href=f"/initiative/{i['id']}")),
        Td(VALUE_CAT_LABELS.get(i.get("value_category"), i.get("value_category") or "—")),
        Td(money(i.get("value_target"))),
        Td(money(i.get("value_realized"))),
        Td(pct(round(100 * (i.get("value_realized") or 0) / i["value_target"], 0)
               if i.get("value_target") else 0)),
    ) for i in inis if i.get("value_target")]
    return (
        PLOTLY,
        section_title("Value creation tracking",
                      f"£{s['realized']/1e6:.1f}m realised of £{s['target']/1e6:.1f}m target "
                      f"({s['realization_pct']}%)"),
        Div(H3("Value waterfall"), _value_waterfall() or P("No data."), cls="card"),
        Div(
            Div(H3("By category"), _category_bar(s["by_category"]) or P("No data."), cls="card"),
            Div(H3("Planned vs realised"), _value_trend() or P("No data."), cls="card"),
            cls="grid2"),
        Div(H3("Value by initiative"),
            Table(Thead(Tr(Th("Initiative"), Th("Category"), Th("Target"),
                           Th("Realised"), Th("%"))), Tbody(*rows)), cls="card"),
    )
