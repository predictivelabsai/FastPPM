"""Master Gantt, Kanban and dependency mapping (spec §2 'Single Tracking View')."""

from __future__ import annotations

from datetime import date

import plotly.graph_objects as go

import ppmstore as store
from web import charts
from web.ui import (PLOTLY, section_title, STATUS_LABELS, status_badge, money, pct)
from fasthtml.common import *

TODAY = "2026-06-22"
_MS_COLOR = {"done": "#1c7c44", "in_progress": "#2b6cb0", "open": "#9AAEB8"}
_RAG_BAR = {"G": "#1c7c44", "A": "#b06b00", "R": "#c0392b"}


def _gantt_fig():
    inis = [i for i in store.list_initiatives()
            if i["type"] != "program" and i.get("start_date") and i.get("end_date")]
    inis = sorted(inis, key=lambda i: i.get("start_date") or "")
    if not inis:
        return None
    fig = go.Figure()
    ytick = []
    for row, i in enumerate(inis):
        name = i["name"][:34]
        ytick.append(name)
        col = _RAG_BAR.get((i.get("rag") or "").upper(), "#123B5D")
        # Baseline bar (thin, grey) then planned bar (RAG-coloured).
        if i.get("baseline_start") and i.get("baseline_end"):
            fig.add_trace(go.Scatter(
                x=[i["baseline_start"], i["baseline_end"]], y=[row + 0.18, row + 0.18],
                mode="lines", line=dict(color="#cfcfd6", width=6),
                hoverinfo="text", text=f"{name} baseline", showlegend=False))
        fig.add_trace(go.Scatter(
            x=[i["start_date"], i["end_date"]], y=[row - 0.05, row - 0.05],
            mode="lines", line=dict(color=col, width=12),
            hoverinfo="text", text=f"{name}: {int(i.get('progress') or 0)}% · {i.get('status')}",
            showlegend=False))
        # Milestone diamonds at planned (or actual) dates.
        for m in store.list_milestones(i["id"]):
            d = m.get("actual_date") or m.get("planned_date")
            if not d:
                continue
            mc = _MS_COLOR.get(m.get("status") or "open", "#9AAEB8")
            fig.add_trace(go.Scatter(
                x=[d], y=[row - 0.05], mode="markers",
                marker=dict(symbol="diamond", size=11, color=mc,
                            line=dict(color="#fff", width=1)),
                hoverinfo="text",
                text=f"{m['title']} — {int(m.get('progress') or 0)}% ({m.get('status')})<br>{d}",
                showlegend=False))
    fig.add_vline(x=TODAY, line=dict(color="#00A6A6", width=2, dash="dot"))
    fig.update_yaxes(tickmode="array", tickvals=list(range(len(inis))),
                     ticktext=ytick, autorange="reversed")
    fig.update_xaxes(type="date", showgrid=True, gridcolor="#f0eef3")
    fig.update_layout(height=max(360, 40 * len(inis) + 80))
    return charts.render(fig, height=max(360, 40 * len(inis) + 80))


KANBAN_COLS = ["not_started", "in_progress", "on_track", "at_risk", "delayed"]


def _kanban():
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    by = {c: [] for c in KANBAN_COLS}
    by["complete"] = []
    for i in inis:
        st = i.get("status")
        (by.get(st) if st in by else by.setdefault(st, [])).append(i)
    cols = []
    for c in KANBAN_COLS:
        cards = [Div(A(i["name"], href=f"/initiative/{i['id']}"),
                     Div(f"{i.get('workstream') or '—'} · {int(i.get('progress') or 0)}% · "
                         f"{money(i.get('value_target'))}",
                         style="color:#7a7a85;font-size:11.5px;margin-top:3px"),
                     cls="kcard") for i in by.get(c, [])]
        cols.append(Div(H4(f"{STATUS_LABELS[c]} ({len(by.get(c, []))})"), *cards, cls="kcol"))
    return Div(*cols, cls="kanban")


def _dependency_list():
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    blocks = []
    for i in inis:
        ms = store.list_milestones(i["id"])
        by_id = {m["id"]: m for m in ms}
        chains = []
        for m in ms:
            for dep in m.get("dependencies") or []:
                pre = by_id.get(dep)
                if pre:
                    chains.append(Div(
                        Span(pre["title"], style="background:#E6F2F5;color:#123B5D;"
                             "border-radius:6px;padding:2px 8px;font-size:12px"),
                        Span(" → ", style="color:#7a7a85"),
                        Span(m["title"], style="background:#E6F2F5;color:#123B5D;"
                             "border-radius:6px;padding:2px 8px;font-size:12px"),
                        style="margin:3px 0"))
        if chains:
            blocks.append(Div(Div(i["name"], style="font-weight:600;margin:8px 0 4px"), *chains))
    return Div(*blocks) if blocks else P("No dependencies mapped.")


def gantt_content():
    return (
        PLOTLY,
        section_title("Master Gantt",
                      "Baseline vs plan · milestone markers (◆) coloured by status · "
                      "today = dotted line"),
        Div(_gantt_fig() or P("No scheduled initiatives."), cls="card"),
        Div(H3("Kanban — initiatives by status"), _kanban(), cls="card"),
        Div(H3("Dependency mapping"), _dependency_list(), cls="card"),
    )
