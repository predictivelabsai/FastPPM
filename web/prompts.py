"""Prompt Manager — view/edit/version the system prompts that guide the agents.

The document-extraction prompt is edited in a **WYSIWYG editor (Trix)** — no
markdown knowledge needed. Content is stored as HTML and fed to the LLM as-is;
the JSON schema lives in a code block so it is preserved verbatim. Saving creates
a new active version; any prior version can be re-activated. History is
append-only.
"""

from __future__ import annotations

import html as _html

import ppmstore as store
from web.ui import section_title
from fasthtml.common import *

# Trix WYSIWYG (single include; outputs clean HTML, preserves code blocks).
TRIX_CSS = Link(rel="stylesheet", href="https://unpkg.com/trix@2.1.15/dist/trix.css")
TRIX_JS = Script(src="https://unpkg.com/trix@2.1.15/dist/trix.umd.min.js")
TRIX_STYLE = Style("""
trix-toolbar .trix-button-group--file-tools{display:none}
trix-editor{min-height:360px;max-height:520px;overflow-y:auto;background:#fff;
  border:1px solid var(--line);border-radius:8px;padding:14px;font-size:13.5px;line-height:1.5}
trix-editor:empty:not(:focus)::before{color:#9a93a6}
trix-editor pre{background:#f5f6f4;border:1px solid var(--line);border-radius:6px;
  padding:10px 12px;font-size:12px;white-space:pre-wrap}
.mddoc-html{font-size:13px;line-height:1.55}
.mddoc-html pre{background:#f5f6f4;border:1px solid var(--line);border-radius:6px;
  padding:10px;font-size:12px;white-space:pre-wrap;overflow-x:auto}
""")


def _as_html(content: str) -> str:
    """Render stored content for the editor / preview. Plain-text (legacy
    versions) is wrapped in a code block so newlines + braces survive."""
    content = content or ""
    return content if "<" in content else "<pre>" + _html.escape(content) + "</pre>"


def prompts_content():
    rows = []
    for p in store.list_prompts():
        rows.append(Tr(
            Td(A(p["name"], href=f"/prompt/{p['key']}", style="font-weight:600"), Br(),
               Span(p.get("description") or "", style="font-size:11.5px;color:#7a7a85")),
            Td(Code(p["key"])),
            Td(f"v{p.get('active_version') or '—'}"),
            Td(str(p.get("version_count") or 0)),
            Td(A("Edit / versions", href=f"/prompt/{p['key']}", cls="btn sm")),
        ))
    return (
        section_title("Prompt Manager",
                      "Versioned system prompts that guide what the agents extract. "
                      "Edit in the WYSIWYG editor to create a new active version; "
                      "re-activate any prior one."),
        Table(Thead(Tr(Th("Prompt"), Th("Key"), Th("Active"), Th("Versions"), Th(""))),
              Tbody(*rows)) if rows else P("No prompts registered."),
    )


def prompt_detail_content(key: str, saved: bool = False):
    p = store.get_prompt(key)
    if not p:
        return (section_title("Not found"), P("No such prompt."))
    versions = store.list_prompt_versions(key)
    banner = Div("✓ Saved as a new active version.", cls="banner ok") if saved else ""

    editor = Form(
        Input(type="hidden", id="prompt-content", name="content",
              value=_as_html(p.get("active_content"))),
        NotStr('<trix-editor input="prompt-content" '
               'placeholder="Write the extraction instructions…"></trix-editor>'),
        Label("Change note (optional)"),
        Input(name="notes", placeholder="e.g. tightened date handling"),
        Button("Save as new active version", cls="btn", style="margin-top:12px"),
        method="post", action=f"/prompt/{key}/version", cls="std")

    vrows = []
    for v in versions:
        is_active = v.get("is_active")
        actions = (Span("● Active", style="color:#1c7c44;font-weight:600;font-size:12px")
                   if is_active else
                   Form(Button("Activate", cls="btn sm ghost"), method="post",
                        action=f"/prompt/{key}/activate/{v['id']}", style="display:inline"))
        vrows.append(Div(
            Div(Span(f"v{v['version']}", style="font-weight:700;color:#123B5D"), " ",
                Span((v.get("created_at") or "")[:16].replace("T", " "),
                     style="color:#7a7a85;font-size:12px"), " ",
                Span(f"· {v.get('created_by') or '—'}", style="color:#7a7a85;font-size:12px"),
                (Span(f" · {v['notes']}", style="color:#7a7a85;font-size:12px") if v.get("notes") else ""),
                " ", actions, style="margin-bottom:4px"),
            Details(Summary("view content", style="cursor:pointer;font-size:12px;color:#6b7686"),
                    Div(NotStr(_as_html(v.get("content"))), cls="mddoc-html",
                        style="background:#fbfcfd;border:1px solid var(--line);"
                        "border-radius:6px;padding:10px;margin-top:6px")),
            style="padding:10px 0;border-bottom:1px solid var(--line)"))

    return (
        TRIX_CSS, TRIX_JS, TRIX_STYLE,
        Div(A("← All prompts", href="/prompts", style="font-size:12.5px"), style="margin-bottom:6px"),
        section_title(p["name"], p.get("description")),
        banner,
        Div(H3("Edit"),
            P("Write plain-English guidance and bullet rules — no markdown, no JSON, "
              "no code needed. Format with the toolbar. The output structure is handled "
              "automatically; you just describe what to extract.",
              style="color:#7a7a85;font-size:12.5px;margin:-6px 0 10px"),
            editor, cls="card"),
        Div(H3(f"Version history ({len(versions)})"), *vrows, cls="card"),
    )
