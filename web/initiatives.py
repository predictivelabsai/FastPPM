"""Initiative registry + detail (spec §2 'Initiative / Use Case Detail Pages')."""

from __future__ import annotations

import ppmstore as store
from web.ui import (section_title, money, pct, num, short_date, progress_bar,
                    download_buttons, card_header,
                    status_badge, type_badge, rag_dot, rag_badge,
                    INITIATIVE_TYPES, STATUS_LABELS, VALUE_CAT_LABELS, doc_status_badge)
from fasthtml.common import *


def _filters(current_type, current_status):
    types = [A("All", href="/initiatives", cls="on" if not current_type else "")]
    for k, lbl in INITIATIVE_TYPES.items():
        types.append(A(lbl, href=f"/initiatives?type={k}",
                       cls="on" if current_type == k else ""))
    statuses = [A("Any status", href="/initiatives", cls="on" if not current_status else "")]
    for k, lbl in STATUS_LABELS.items():
        statuses.append(A(lbl, href=f"/initiatives?status={k}",
                          cls="on" if current_status == k else ""))
    return Div(Div(*types, cls="filters"), Div(*statuses, cls="filters"))


def registry_content(type=None, status=None):
    inis = [i for i in store.list_initiatives(type=type or None, status=status or None)
            if i["type"] != "program" or type == "program"]
    rows = []
    for i in inis:
        realized, target = i.get("value_realized") or 0, i.get("value_target") or 0
        rows.append(Tr(
            Td(A(i["name"], href=f"/initiative/{i['id']}", style="font-weight:600"),
               Br(), Span(i.get("workstream") or "", style="font-size:11px;color:#7a7a85")),
            Td(type_badge(i["type"])),
            Td(i.get("owner") or "—"),
            Td(status_badge(i.get("status"))),
            Td(rag_dot(i.get("rag")), " ", str(int(i.get("progress") or 0)) + "%"),
            Td(money(realized) + " / " + money(target)),
            Td(str(i.get("milestone_count", 0))),
        ))
    head = Tr(*[Th(h) for h in ("Initiative", "Type", "Owner", "Status",
                                "Progress", "Value (real/target)", "Milestones")])
    return (
        section_title("Initiatives", f"{len(inis)} initiatives & AI use cases"),
        _filters(type, status),
        Table(Thead(head), Tbody(*rows)),
    )


def initiative_content(iid: int):
    i = store.get_initiative(iid)
    if not i:
        return (section_title("Not found"), P("No such initiative."))
    ms = store.list_milestones(iid)
    risks = store.list_risks(iid)
    activity = store.list_activity(entity_type="initiative", entity_id=iid, limit=10)
    children = store.list_initiatives(parent_id=iid)
    src_doc = store.get_document(i["source_document_id"]) if i.get("source_document_id") else None

    realized, target = i.get("value_realized") or 0, i.get("value_target") or 0
    header = Div(
        Div(type_badge(i["type"]), " ", status_badge(i.get("status")), " ", rag_badge(i.get("rag")),
            style="margin-bottom:6px"),
        H1(i["name"]),
        P(f"Owner: {i.get('owner') or '—'} · Workstream: {i.get('workstream') or '—'}"
          + (f" · Ref: {i['ref']}" if i.get("ref") else "")
          + (f" · Parent: {i['parent_name']}" if i.get("parent_name") else ""),
          style="color:#7a7a85;font-size:13.5px"),
        (P(i["description"], style="margin-top:6px") if i.get("description") else ""),
        (Div("Ingested from ", A(src_doc["file_name"], href=f"/document/{src_doc['id']}"),
             style="font-size:12.5px;color:#7a7a85;margin-top:4px") if src_doc else ""),
    )

    overview = Div(
        Div(H3("Progress"), progress_bar(i.get("progress")),
            Dl(Dt("Start"), Dd(short_date(i.get("start_date"))),
               Dt("End (plan)"), Dd(short_date(i.get("end_date"))),
               Dt("End (baseline)"), Dd(short_date(i.get("baseline_end"))),
               cls="meta", style="margin-top:10px"), cls="card"),
        Div(H3("Value"),
            Dl(Dt("Target"), Dd(money(target)),
               Dt("Realised"), Dd(money(realized)),
               Dt("Realisation"), Dd(pct(round(100 * realized / target, 0) if target else 0)),
               Dt("Category"), Dd(VALUE_CAT_LABELS.get(i.get("value_category"), i.get("value_category") or "—")),
               cls="meta"), cls="card"),
        cls="grid2")

    ms_rows = [Tr(Td(m["title"]),
                  Td(short_date(m.get("baseline_date"))),
                  Td(short_date(m.get("planned_date"))),
                  Td(short_date(m.get("actual_date"))),
                  Td(progress_bar(m.get("progress"))),
                  Td(m.get("status") or "—")) for m in ms]
    base = f"/initiative/{iid}"
    ms_card = Div(card_header(f"Milestones ({len(ms)})",
                              download_buttons(base, "milestones") if ms else None),
                  Table(Thead(Tr(Th("Milestone"), Th("Baseline"), Th("Planned"),
                                 Th("Actual"), Th("Progress"), Th("Status"))),
                        Tbody(*ms_rows)) if ms_rows else P("No milestones."), cls="card")

    rk_rows = [Tr(Td(r["description"]), Td(str(r.get("probability"))), Td(str(r.get("impact"))),
                  Td(str((r.get("probability") or 0) * (r.get("impact") or 0))),
                  Td(r.get("mitigation") or "—")) for r in risks]
    rk_card = Div(card_header(f"Risks ({len(risks)})",
                              download_buttons(base, "risks") if risks else None),
                  Table(Thead(Tr(Th("Risk"), Th("P"), Th("I"), Th("Score"), Th("Mitigation"))),
                        Tbody(*rk_rows)) if rk_rows else P("No risks."), cls="card")

    child_card = ""
    if children:
        ch_rows = [Tr(Td(A(c["name"], href=f"/initiative/{c['id']}")),
                      Td(type_badge(c["type"])), Td(status_badge(c.get("status"))),
                      Td(str(int(c.get("progress") or 0)) + "%"),
                      Td(money(c.get("value_target")))) for c in children]
        child_card = Div(H3(f"Sub-initiatives ({len(children)})"),
                         Table(Thead(Tr(Th("Name"), Th("Type"), Th("Status"),
                                        Th("Progress"), Th("Target"))), Tbody(*ch_rows)), cls="card")

    act_rows = [Tr(Td((a.get("at") or "")[:16].replace("T", " ")),
                   Td(a.get("action")), Td(a.get("detail") or "", style="font-size:12.5px;color:#7a7a85"))
                for a in activity]
    audit_card = Div(H3("Audit trail"),
                     Table(Thead(Tr(Th("When"), Th("Action"), Th("Detail"))), Tbody(*act_rows))
                     if act_rows else P("No activity yet."), cls="card")

    return (header, overview, child_card, ms_card, rk_card, audit_card)
