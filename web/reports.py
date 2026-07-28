"""Report builder — AI-assembled, WYSIWYG block editor, with a live preview pane.

A report is an ordered list of typed blocks (heading/paragraph/bullet/divider),
each holding HTML, edited block-by-block in a Trix WYSIWYG editor (HTMX swaps into
``#report-main``; the preview pane updates out-of-band). Lifted in spirit from the
sister FastDocs block model.
"""

from __future__ import annotations

import ppmstore as store
from web.ui import (section_title, TRIX_CSS, TRIX_JS, TRIX_STYLE, money)
from fasthtml.common import *

BLOCK_TYPES = ["heading1", "heading2", "heading3", "paragraph", "bullet", "divider"]
BLOCK_LABELS = {"heading1": "Title (H1)", "heading2": "Heading (H2)",
                "heading3": "Sub-heading (H3)", "paragraph": "Paragraph",
                "bullet": "Bullet list", "divider": "Divider"}

HX = {"hx_target": "#report-main", "hx_swap": "innerHTML"}

REPORT_CSS = Style("""
.rb{position:relative;border:1px solid transparent;border-radius:8px;padding:4px 8px;margin:2px 0}
.rb:hover{background:#fafbfc;border-color:var(--line)}
.rb-tools{position:absolute;top:4px;right:6px;display:none;gap:2px;background:#fff;
  border:1px solid var(--line);border-radius:7px;padding:2px}
.rb:hover .rb-tools{display:flex}
.rb-btn{cursor:pointer;padding:2px 7px;border-radius:5px;font-size:13px;color:var(--navy);user-select:none}
.rb-btn:hover{background:#E6F2F5;text-decoration:none}
.rb-body h1{font-size:24px;color:#48484f;margin:6px 0}
.rb-body h2{font-size:19px;color:var(--navy);margin:14px 0 6px}
.rb-body h3{font-size:15px;color:var(--navy);margin:10px 0 4px}
.rb-body p,.rb-body .rb-p{font-size:14px;line-height:1.6;color:#48484f;margin:6px 0}
.rb-body ul{margin:6px 0 6px 4px}.rb-body li{margin:3px 0;font-size:14px;line-height:1.55}
.rb-hr{border:none;border-top:1px solid var(--line);margin:14px 0}
.rb-editing{background:#F1FAFA;border-color:var(--accent)}
.rb-typesel{padding:6px 9px;border:1px solid var(--line);border-radius:7px;font-size:13px;margin-bottom:8px}
.rb-editbtns{display:flex;gap:8px;margin-top:10px}
.report-doc{background:#fff;padding:8px 4px}
.report-preview{font-size:13px}
.report-preview h1{font-size:19px}.report-preview h2{font-size:15px;color:var(--navy)}
.report-preview h3{font-size:13px;color:var(--navy)}
.report-preview ul{margin-left:6px}
""")


# ── Block rendering ─────────────────────────────────────────────────────────

def render_block(b):
    t, c = b["type"], b.get("content", "")
    if t == "divider":
        return Hr(cls="rb-hr")
    if t == "heading1":
        return H1(NotStr(c or "Untitled"))
    if t == "heading2":
        return H2(NotStr(c))
    if t == "heading3":
        return H3(NotStr(c))
    if t == "bullet":
        if "<ul" in (c or "") or "<ol" in (c or ""):
            return NotStr(c)
        return Ul(*[Li(x) for x in (c or "").split("\n") if x.strip()])
    return Div(NotStr(c or "—"), cls="rb-p")


def _block_view(rid, b):
    bid = b["id"]
    tools = Div(
        A("✎", title="Edit", hx_get=f"/report/{rid}/main?editing={bid}", cls="rb-btn", **HX),
        A("↑", hx_post=f"/report/{rid}/block/{bid}/move?dir=-1", cls="rb-btn", **HX),
        A("↓", hx_post=f"/report/{rid}/block/{bid}/move?dir=1", cls="rb-btn", **HX),
        A("＋", title="Add below", hx_post=f"/report/{rid}/block/add?after={bid}", cls="rb-btn", **HX),
        A("✕", title="Delete", hx_post=f"/report/{rid}/block/{bid}/delete", cls="rb-btn", **HX),
        cls="rb-tools")
    return Div(Div(render_block(b), cls="rb-body"), tools, cls="rb")


def _block_edit(rid, b):
    bid = b["id"]
    opts = [Option(BLOCK_LABELS[t], value=t, selected=(t == b["type"])) for t in BLOCK_TYPES]
    return Div(Form(
        Select(*opts, name="type", cls="rb-typesel"),
        Input(type="hidden", id=f"rbc{bid}", name="content", value=b.get("content", "")),
        NotStr(f'<trix-editor input="rbc{bid}"></trix-editor>'),
        Div(Button("Save", cls="btn sm", type="submit"),
            Button("Cancel", type="button", cls="btn sm ghost",
                   hx_get=f"/report/{rid}/main", **HX),
            cls="rb-editbtns"),
        hx_post=f"/report/{rid}/block/{bid}", **HX),
        cls="rb rb-editing")


def report_blocks(rid, editing=None):
    """Inner content of #report-main (swappable)."""
    blocks = store.list_report_blocks(rid)
    nodes = [_block_edit(rid, b) if (editing and b["id"] == editing) else _block_view(rid, b)
             for b in blocks]
    add = A("＋ Add block", hx_post=f"/report/{rid}/block/add", cls="btn sm ghost",
            style="margin-top:12px;display:inline-block", **HX)
    return Div(*nodes, add) if nodes else Div(
        P("This report has no blocks yet.", style="color:#7a7a85"), add)


def preview_inner(rid):
    return Div(*[render_block(b) for b in store.list_report_blocks(rid)], cls="report-doc")


def preview_oob(rid):
    return Div(preview_inner(rid), id="report-preview", hx_swap_oob="true")


def preview_pane(rid):
    return Div(Div("📄 Live preview", cls="rhead"),
               Div(preview_inner(rid), id="report-preview", cls="rbody report-preview"),
               cls="pane right")


def editor_center(rid):
    r = store.get_report(rid)
    if not r:
        return Div(section_title("Not found"), P("No such report."), cls="pane center centerdoc")
    fmts = Div(
        A("⬇ PDF", href=f"/report/{rid}/export?fmt=pdf", cls="btn sm"),
        A("⬇ DOCX", href=f"/report/{rid}/export?fmt=docx", cls="btn sm ghost"),
        A("⬇ PPTX", href=f"/report/{rid}/export?fmt=pptx", cls="btn sm ghost"),
        style="display:flex;gap:6px")
    header = Div(
        Div(A("← Documents", href="/documents", style="font-size:12.5px"),
            style="margin-bottom:6px"),
        Div(Form(Input(name="title", value=r["title"],
                       style="font-size:21px;font-weight:700;border:none;width:100%;"
                       "color:#48484f;background:transparent",
                       hx_post=f"/report/{rid}/title", hx_trigger="change", hx_swap="none"),
                 style="flex:1"),
            fmts,
            style="display:flex;align-items:center;gap:14px"),
        P((f"From template: {r['template_name']} · " if r.get("template_name") else "")
          + "Hover a block to edit, reorder, add or delete. Edits show live in the preview →",
          style="color:#7a7a85;font-size:13px;margin-top:4px"),
        style="margin-bottom:12px")
    return Div(Div(header, Div(report_blocks(rid), id="report-main"), cls="wrap"),
               TRIX_CSS, TRIX_JS, TRIX_STYLE, REPORT_CSS,
               cls="pane center centerdoc")


# ── Documents-tab report builder panel ──────────────────────────────────────

def builder_panel():
    reports = store.list_reports()
    tpls = store.list_report_templates()
    upload = Form(
        Div("①  Upload a report template",
            style="font-weight:600;color:var(--navy);margin-bottom:4px"),
        Div("PDF / DOCX / MD / TXT — its sections guide the generated report.",
            style="font-size:12px;color:#7a7a85;margin-bottom:8px"),
        Input(type="file", name="template", accept=".pdf,.docx,.md,.txt"),
        Button("⬆ Upload report template", cls="btn sm ghost", style="margin-top:10px"),
        method="post", action="/reports/template/upload", enctype="multipart/form-data")
    gen = Form(
        Div("②  Generate report", style="font-weight:600;color:var(--navy);margin-bottom:4px"),
        Div("Merges the programme data into the chosen template.",
            style="font-size:12px;color:#7a7a85;margin-bottom:8px"),
        Select(Option("No template — use programme data", value=""),
               *[Option(t["name"], value=str(t["id"])) for t in tpls], name="template_id"),
        Button("✨ Generate report", cls="btn", style="margin-top:10px"),
        method="post", action="/reports/generate")
    rrows = [Tr(Td(A(r["title"], href=f"/report/{r['id']}", style="font-weight:600")),
                Td(r.get("template_name") or "—"),
                Td(str(r.get("block_count") or 0)),
                Td((r.get("updated_at") or "")[:10]),
                Td(A("Open", href=f"/report/{r['id']}", cls="btn sm"), " ",
                   A("PDF", href=f"/report/{r['id']}/export?fmt=pdf", cls="btn sm ghost")))
             for r in reports]
    table = (Table(Thead(Tr(Th("Report"), Th("Template"), Th("Blocks"), Th("Updated"), Th(""))),
                   Tbody(*rrows)) if reports else
             P("No reports yet — upload a template and generate one.", style="color:#7a7a85"))
    return Div(
        H3("Report builder"),
        P("Upload a final report template, then generate a board-ready report that "
          "merges the programme content into it — edit it in the WYSIWYG editor and "
          "export to PDF, DOCX or PPTX.", style="color:#7a7a85;font-size:13.5px;margin-top:-4px"),
        Div(upload, gen, cls="grid2", style="margin:12px 0"),
        Div(H4(f"Reports ({len(reports)})", style="margin:14px 0 8px;color:#48484f;font-size:14px"),
            table),
        cls="card")
