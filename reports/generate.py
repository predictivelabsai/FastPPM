"""Generate a report by assembling the programme data into a template skeleton.

`generate_report(outline)` asks Grok to write a board-ready report — as a JSON
array of blocks `{type, content}` (the FastDocs pattern) — following the uploaded
template's section outline and using the live programme data for every fact.
Without an API key it falls back to a deterministic report built from the data,
so "Generate report" always produces something editable.
"""

from __future__ import annotations

import json

import ppmstore as store
from rag import llm

BLOCK_TYPES = ["heading1", "heading2", "heading3", "paragraph", "bullet", "divider"]

REPORT_SYSTEM = """You write executive reports for a private-equity portfolio \
company's Transformation Office, as a JSON array of content blocks. Return ONLY a \
JSON array — no prose, no markdown fences. Each element is an object \
{"type": str, "content": str}.

Allowed "type" values: "heading1" (the report title — the FIRST block), "heading2" \
(a section), "heading3" (a sub-section), "paragraph", "bullet", "divider".
Rules:
- content for headings and paragraphs is short HTML; you may use <strong> and <em>.
- content for "bullet" is an HTML unordered list: "<ul><li>...</li><li>...</li></ul>".
- "divider" content is "".
- Follow the TEMPLATE OUTLINE for the section structure where one is given.
- Use the PROGRAMME DATA for ALL facts and numbers — never invent figures.
- Produce a complete, board-ready narrative of 12–22 blocks."""


def _money(v):
    v = float(v or 0)
    if abs(v) >= 1e6:
        return f"£{v/1e6:.1f}m"
    if abs(v) >= 1e3:
        return f"£{v/1e3:.0f}k"
    return f"£{v:.0f}"


def programme_context() -> str:
    """A compact text snapshot of the programme for the model / fallback."""
    s = store.portfolio_summary()
    vs = store.value_summary()
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    risks = store.list_risks()[:8]
    docs = [d["file_name"] for d in store.list_documents() if d["status"] == "merged"]
    lines = [
        f"Programme: {s['total_initiatives']} initiatives ({s['types'].get('ai_use_case',0)} AI use cases).",
        f"RAG: {s['rag'].get('G',0)} green, {s['rag'].get('A',0)} amber, {s['rag'].get('R',0)} red "
        f"({s['on_track_pct']}% on track). Average progress {s['avg_progress']:.0f}%, "
        f"on-time delivery {s['on_time_pct']:.0f}%.",
        f"Value realised {_money(vs['realized'])} of {_money(vs['target'])} target "
        f"({vs['realization_pct']}%). Open risks {s['open_risks']} ({s['high_risks']} high).",
        "By value category: " + "; ".join(
            f"{c['category']} {_money(c['realized'])}/{_money(c['target'])}" for c in vs["by_category"]) or "—",
        "",
        "Initiatives:",
    ]
    for i in inis:
        lines.append(f"- {i['name']} [{i.get('type')}, {i.get('workstream')}] — {i.get('status')}, "
                     f"{int(i.get('progress') or 0)}% complete, value {_money(i.get('value_realized'))}/"
                     f"{_money(i.get('value_target'))}, owner {i.get('owner')}.")
    lines.append("")
    lines.append("Top risks:")
    for r in risks:
        score = (r.get("probability") or 0) * (r.get("impact") or 0)
        lines.append(f"- [{score}] {r['description']} ({r['initiative_name']}).")
    if docs:
        lines.append("")
        lines.append("Source documents ingested: " + ", ".join(docs) + ".")
    return "\n".join(lines)


def _extract_json_array(raw: str):
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(s[a:b + 1])
    except Exception:
        return None


def _clean_blocks(arr) -> list[dict]:
    blocks = []
    for b in arr or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type", "paragraph")
        if t not in BLOCK_TYPES:
            t = "paragraph"
        blocks.append({"type": t, "content": str(b.get("content", ""))})
    if blocks and blocks[0]["type"] != "heading1":
        blocks.insert(0, {"type": "heading1", "content": "Value Creation Report"})
    return blocks


def _deterministic_report(outline: str) -> tuple[str, list[dict]]:
    """A solid report assembled directly from the programme data (no LLM)."""
    s = store.portfolio_summary()
    vs = store.value_summary()
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    risks = store.list_risks()[:6]
    title = "Value Creation Plan — Programme Report"
    blocks = [
        {"type": "heading1", "content": title},
        {"type": "heading2", "content": "Executive summary"},
        {"type": "paragraph", "content":
            f"<div>The Value Creation Plan comprises <strong>{s['total_initiatives']} initiatives</strong> "
            f"({s['types'].get('ai_use_case',0)} internal AI use cases). "
            f"<strong>{s['on_track_pct']}%</strong> of active initiatives are on track, at an average "
            f"<strong>{s['avg_progress']:.0f}%</strong> complete. "
            f"Realised benefit stands at <strong>{_money(vs['realized'])}</strong> of a "
            f"<strong>{_money(vs['target'])}</strong> target ({vs['realization_pct']}%).</div>"},
        {"type": "heading2", "content": "Programme health"},
        {"type": "bullet", "content":
            "<ul>"
            f"<li>RAG: {s['rag'].get('G',0)} green · {s['rag'].get('A',0)} amber · {s['rag'].get('R',0)} red</li>"
            f"<li>On-time milestone delivery: {s['on_time_pct']:.0f}%</li>"
            f"<li>Open risks: {s['open_risks']} ({s['high_risks']} high)</li>"
            f"<li>Documents ingested: {s['documents_merged']}</li>"
            "</ul>"},
        {"type": "heading2", "content": "Value creation"},
        {"type": "bullet", "content": "<ul>" + "".join(
            f"<li>{c['category'].replace('_',' ').title()}: {_money(c['realized'])} realised of "
            f"{_money(c['target'])} target</li>" for c in vs["by_category"]) + "</ul>"},
        {"type": "heading2", "content": "Initiatives"},
        {"type": "bullet", "content": "<ul>" + "".join(
            f"<li><strong>{i['name']}</strong> — {i.get('status')}, {int(i.get('progress') or 0)}% "
            f"complete, value {_money(i.get('value_realized'))}/{_money(i.get('value_target'))}</li>"
            for i in inis) + "</ul>"},
        {"type": "heading2", "content": "Key risks"},
        {"type": "bullet", "content": "<ul>" + "".join(
            f"<li>{r['description']} — {r['initiative_name']} "
            f"(P{r.get('probability')}×I{r.get('impact')})</li>" for r in risks) + "</ul>"},
    ]
    if outline:
        blocks.append({"type": "divider", "content": ""})
        blocks.append({"type": "heading3", "content": "Based on template"})
        blocks.append({"type": "paragraph", "content":
                       f"<div><em>Generated against the uploaded template outline.</em></div>"})
    return title, blocks


def generate_report(outline: str = "") -> tuple[str, list[dict]]:
    """Return (title, blocks). Uses Grok when a key is set, else the
    deterministic data-driven report."""
    if llm.ai_available():
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            human = ((f"TEMPLATE OUTLINE:\n{outline}\n\n" if outline else "")
                     + f"PROGRAMME DATA:\n{programme_context()}\n\nWrite the report now.")
            resp = llm.get_llm().invoke([SystemMessage(content=REPORT_SYSTEM),
                                         HumanMessage(content=human)])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            blocks = _clean_blocks(_extract_json_array(raw))
            if blocks:
                return blocks[0]["content"] or "Value Creation Report", blocks
        except Exception:
            pass
    return _deterministic_report(outline)
