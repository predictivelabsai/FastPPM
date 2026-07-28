"""Document ingestion engine — upload, review extracted entities, merge (flagship).

Page rendering only; the upload/process/merge route handlers live in app.py.
"""

from __future__ import annotations

import ppmstore as store
from web.ui import (section_title, money, short_date, doc_status_badge, status_badge,
                    type_badge, INITIATIVE_TYPES, VALUE_CAT_LABELS,
                    download_buttons, card_header)
from fasthtml.common import *

ACCEPT = ".pdf,.xlsx,.xls,.pptx,.docx"


def documents_content(flash=None):
    docs = store.list_documents()
    dropzone = Form(
        Div("📂  Drag & drop status reports, trackers or decks here",
            Div("PDF · XLSX · PPTX · DOCX — bulk upload supported",
                style="font-size:12px;color:#7a7a85;margin-top:4px"),
            Input(type="file", name="files", multiple=True, accept=ACCEPT, required=True),
            cls="dropzone"),
        Button("Upload & extract", cls="btn", style="margin-top:12px"),
        method="post", action="/documents/upload", enctype="multipart/form-data")

    rows = []
    for d in docs:
        actions = []
        if d["status"] in ("extracted", "uploaded", "error"):
            actions.append(A("Review", href=f"/document/{d['id']}", cls="btn sm"))
        if d["status"] == "merged":
            actions.append(A("View", href=f"/document/{d['id']}", cls="btn sm ghost"))
        counts = (f"{d.get('n_milestones',0)}M · {d.get('n_risks',0)}R · "
                  f"{d.get('n_value_drivers',0)}V"
                  + (f" · ⚠{d['n_inconsistencies']}" if d.get("n_inconsistencies") else ""))
        rows.append(Tr(
            Td(d["file_name"], Br(),
               Span((d.get("uploaded_at") or "")[:10], style="font-size:11px;color:#7a7a85")),
            Td(d.get("file_type", "").upper()),
            Td(doc_status_badge(d["status"])),
            Td(counts if d["status"] in ("extracted", "merged") else "—"),
            Td(d.get("summary") or "—", style="font-size:12.5px;color:#7a7a85"),
            Td(*actions),
        ))
    table = Table(Thead(Tr(Th("Document"), Th("Type"), Th("Status"),
                           Th("Extracted"), Th("Summary"), Th(""))),
                  Tbody(*rows)) if rows else P("No documents yet — upload some above.")

    banner = ""
    if flash:
        banner = Div(flash, cls="banner ok")

    return (
        section_title("Document ingestion",
                      "Upload messy sources → auto-extract milestones, risks & value "
                      "drivers → review → merge into the master repository"),
        banner,
        Div(dropzone, cls="card"),
        Div(H3(f"Documents ({len(docs)})"), table, cls="card"),
    )


def _entity_table(headers, rows):
    return Table(Thead(Tr(*[Th(h) for h in headers])), Tbody(*rows))


def _source_preview(d):
    """The 'before' — the original document. PDFs render inline; other formats
    show the raw text/tables we read out of them (deliberately messy)."""
    if d.get("file_type") == "pdf":
        return Iframe(src=f"/document/{d['id']}/file",
                      style="width:100%;height:440px;border:1px solid var(--line);"
                      "border-radius:8px;background:#fff")
    raw = (d.get("raw_text") or "").strip()
    if not raw:
        return P("No preview available for this file.", style="color:#7a7a85")
    return Pre(raw[:6000], style="white-space:pre-wrap;max-height:440px;overflow:auto;"
               "background:#f5f6f4;border:1px solid var(--line);border-radius:8px;"
               "padding:12px;font-size:11.5px;line-height:1.45")


def review_content(doc_id: int):
    d = store.get_document(doc_id)
    if not d:
        return (section_title("Not found"), P("No such document."))
    data = d.get("structured_json") or {}
    ini = data.get("initiative") or {}
    method = data.get("_method", "")
    merged = d["status"] == "merged"

    head = Div(
        Div(doc_status_badge(d["status"]), " ",
            Span(d.get("file_type", "").upper(), style="color:#7a7a85;font-size:12px"),
            (Span(f" · extracted via {method}", style="color:#7a7a85;font-size:12px") if method else ""),
            style="margin-bottom:6px"),
        H1(d["file_name"]),
        P(d.get("summary") or "", style="color:#7a7a85"),
    )

    if d["status"] == "error":
        return (head, Div(f"Extraction error: {d.get('error')}", cls="banner warn"))

    ms = data.get("milestones", [])
    rks0 = data.get("risks", [])
    vds0 = data.get("value_drivers", [])
    incons0 = data.get("inconsistencies", [])

    def _count(n, label, warn=False):
        col = "#c0392b" if warn else "#123B5D"
        return Span(f"{n} {label}", style=f"display:inline-block;background:{col}14;color:{col};"
                    "border-radius:20px;padding:3px 11px;font-size:12px;font-weight:600;margin:3px 6px 3px 0")

    # ── Before → after: the source document vs. what FastPPM extracted ──────
    source_card = Div(
        Div("📄 Source document", style="font-weight:700;color:var(--navy);font-size:15px"),
        Div("what you uploaded — messy, free-form", style="color:#7a7a85;font-size:12px;margin-bottom:10px"),
        _source_preview(d), cls="card")
    extracted_card = Div(
        Div("✨ Extracted by FastPPM", style="font-weight:700;color:var(--navy);font-size:15px"),
        Div("structured, normalised, ready to merge", style="color:#7a7a85;font-size:12px;margin-bottom:10px"),
        Div(_count(len(ms), "milestones"), _count(len(rks0), "risks"),
            _count(len(vds0), "value drivers"),
            (_count(len(incons0), "inconsistencies", warn=True) if incons0 else ""),
            style="margin-bottom:12px"),
        Dl(Dt("Initiative"), Dd(ini.get("name") or "—"),
           Dt("Type"), Dd(INITIATIVE_TYPES.get(ini.get("type"), ini.get("type") or "—")),
           Dt("Owner"), Dd(ini.get("owner") or "—"),
           Dt("Status"), Dd(ini.get("status") or "—"),
           Dt("Value target"), Dd(money(ini.get("value_target")) if ini.get("value_target") else "—"),
           Dt("Value realised"), Dd(money(ini.get("value_realized")) if ini.get("value_realized") else "—"),
           cls="meta"), cls="card")
    before_after = Div(source_card, extracted_card, cls="grid2")
    base = f"/document/{doc_id}"
    ms_card = Div(card_header(f"Milestones ({len(ms)})",
                              download_buttons(base, "milestones") if ms else None),
                  _entity_table(["Title", "Owner", "Planned", "Actual", "Progress", "Status"],
                                [Tr(Td(m.get("title")), Td(m.get("owner") or "—"),
                                    Td(short_date(m.get("planned_date"))),
                                    Td(short_date(m.get("actual_date"))),
                                    Td(f"{int(m['progress'])}%" if m.get("progress") is not None else "—"),
                                    Td(m.get("status") or "—")) for m in ms])
                  if ms else P("None extracted."), cls="card")

    rks = data.get("risks", [])
    rk_card = Div(card_header(f"Risks ({len(rks)})",
                              download_buttons(base, "risks") if rks else None),
                  _entity_table(["Risk", "P", "I", "Mitigation"],
                                [Tr(Td(r.get("description")), Td(str(r.get("probability"))),
                                    Td(str(r.get("impact"))), Td(r.get("mitigation") or "—"))
                                 for r in rks]) if rks else P("None extracted."), cls="card")

    vds = data.get("value_drivers", [])
    vd_card = Div(card_header(f"Value drivers ({len(vds)})",
                              download_buttons(base, "value_drivers") if vds else None),
                  _entity_table(["Driver", "Category", "Target", "Realised", "Period"],
                                [Tr(Td(v.get("name")),
                                    Td(VALUE_CAT_LABELS.get(v.get("category"), v.get("category") or "—")),
                                    Td(money(v.get("target")) if v.get("target") else "—"),
                                    Td(money(v.get("realized")) if v.get("realized") else "—"),
                                    Td(v.get("period") or "—")) for v in vds])
                  if vds else P("None extracted."), cls="card")

    incons = data.get("inconsistencies", [])
    inc_card = (Div(H3(f"⚠ Inconsistencies flagged ({len(incons)})"),
                    Ul(*[Li(x) for x in incons]), cls="card")
                if incons else "")

    if merged:
        action = Div(f"✓ Merged into the master repository "
                     f"{(d.get('merged_at') or '')[:10]}.", cls="banner ok")
        if d.get("structured_json"):
            ini_obj = next((i for i in store.list_initiatives()
                            if i["name"].lower() == (ini.get("name") or "").lower()), None)
            if ini_obj:
                action = Div(action, A("Open the merged initiative →",
                                       href=f"/initiative/{ini_obj['id']}", cls="btn"))
    else:
        action = Form(
            Button("Merge into master repository", cls="btn"),
            method="post", action=f"/document/{doc_id}/merge",
            style="margin:4px 0 16px")

    return (head, action, before_after,
            H3("Extracted entities in full", style="margin:18px 0 10px;color:#48484f"),
            Div(ms_card, rk_card, cls="grid2"), vd_card, inc_card)
