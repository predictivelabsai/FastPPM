"""Normalise extracted document content to canonical candidate entities.

The flagship step: messy tables/text from a status report, tracker or deck →

    {
      "initiative":   {name, type, owner, status, progress, value_target,
                       value_realized, value_category},
      "milestones":   [{title, owner, planned_date, actual_date, progress, status}],
      "risks":        [{description, probability, impact, mitigation, status}],
      "value_drivers":[{name, category, target, realized, period}],
      "inconsistencies": ["..."],
      "summary": "..."
    }

This is **LLM-only** (Grok). The system instruction is the active *extraction*
prompt from the Prompt Manager (versioned, editable in-app), falling back to
``DEFAULT_EXTRACTION_PROMPT``. No regex / heuristics — the model is responsible
for normalising varying column names, date formats and structures, and for
flagging inconsistencies. We assume an API key is configured.
"""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage

from rag import llm

PROMPT_KEY = "extraction"

# The editable, business-user prompt (Prompt Manager, WYSIWYG). PLAIN ENGLISH ONLY
# — no JSON, no schema. Stored as HTML; the LLM reads it fine. A business user can
# safely tweak these bullets without being able to break the output format, which
# is enforced separately by OUTPUT_FORMAT below (code-side, not editable).
DEFAULT_EXTRACTION_PROMPT = """<div>
<p>You are reviewing a transformation document (a status report, tracker or deck). \
Pull out the initiative it describes, along with its milestones, risks and value \
drivers.</p>
<p><strong>What to capture</strong></p>
<ul>
<li>The <strong>initiative</strong>: its name, who owns it, its overall status and \
how much benefit it is targeting vs. has delivered so far.</li>
<li>Each <strong>milestone</strong>: its name, owner, planned and actual dates, \
percent complete, and status.</li>
<li>Each <strong>risk</strong>: a short description, how likely it is and how big \
the impact would be (each rated 1 to 5), and any mitigation.</li>
<li>Each <strong>value driver</strong> (the benefits): its name, the type of value \
(EBITDA, cost savings, revenue or synergy), the target and what has been realised.</li>
</ul>
<p><strong>How to interpret</strong></p>
<ul>
<li>Treat anything about AI, machine learning, automation or forecasting as an \
“AI use case”.</li>
<li>Only include things that are actually in the document — don't invent anything.</li>
<li>Flag anything that looks off: a milestone shown as 100% but not marked complete, \
a missing owner, a date that has slipped, duplicates, or a benefit far above its \
target.</li>
</ul>
</div>"""

# The output contract — fixed in code so the structure the app parses can never be
# broken from the UI. Appended to the editable guidance at run time.
OUTPUT_FORMAT = """Return your answer as STRICT JSON only — no prose, no markdown \
fences — matching exactly this shape:

{
  "initiative": {"name": str, "type": "workstream"|"ai_use_case"|"program"|"value_initiative",
    "owner": str|null, "status": "not_started"|"in_progress"|"on_track"|"at_risk"|"delayed"|"complete",
    "value_target": number|null, "value_realized": number|null,
    "value_category": "ebitda"|"cost_savings"|"revenue"|"synergy"|null},
  "milestones": [{"title": str, "owner": str|null, "planned_date": "YYYY-MM-DD"|null,
    "actual_date": "YYYY-MM-DD"|null, "progress": number|null,
    "status": "open"|"in_progress"|"done"|null}],
  "risks": [{"description": str, "probability": 1-5, "impact": 1-5, "mitigation": str|null}],
  "value_drivers": [{"name": str, "category": "ebitda"|"cost_savings"|"revenue"|"synergy",
    "target": number|null, "realized": number|null, "period": str|null}],
  "inconsistencies": [str]
}

Money must be plain numbers (e.g. £3.2m -> 3200000). Dates as "YYYY-MM-DD" (or
"YYYY-MM" if only a month/quarter is given). Omit anything not in the document."""


def _active_prompt() -> str:
    """The active 'extraction' system prompt (Prompt Manager), or the default."""
    try:
        import ppmstore as store
        content = store.get_active_prompt_content(PROMPT_KEY)
        if content:
            return content
    except Exception:
        pass
    return DEFAULT_EXTRACTION_PROMPT


def _document_text(extracted: dict) -> str:
    """Flatten extracted text + tables into a single block for the model."""
    parts = [extracted.get("text") or ""]
    for i, tbl in enumerate(extracted.get("tables", []) or [], 1):
        rows = "\n".join("\t".join(str(c) for c in row) for row in tbl)
        parts.append(f"[TABLE {i}]\n{rows}")
    return "\n\n".join(p for p in parts if p.strip())[:16000]


def _strip_to_json(raw: str) -> str:
    """Return the JSON object substring, tolerating ``` fences — no regex."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
    start, end = s.find("{"), s.rfind("}")
    return s[start: end + 1] if start != -1 and end != -1 else s


def _summary(ini: dict, data: dict) -> str:
    name = (ini or {}).get("name") or "Document"
    return (f"{name}: {len(data.get('milestones', []))} milestones, "
            f"{len(data.get('risks', []))} risks, "
            f"{len(data.get('value_drivers', []))} value drivers.")


def normalize(extracted: dict, file_name: str, use_ai: bool = True) -> dict:
    """Produce canonical candidate entities from one document via the LLM.

    Returns the canonical shape; on an empty document or model error, returns an
    empty candidate set with the reason in ``inconsistencies``.
    """
    empty = {"initiative": {}, "milestones": [], "risks": [], "value_drivers": [],
             "inconsistencies": [], "summary": "", "_method": "llm"}
    text = _document_text(extracted)
    if not text.strip():
        empty["inconsistencies"] = ["No readable text could be extracted from the file."]
        return empty

    # System message = the editable business guidance + the fixed output contract.
    system = _active_prompt() + "\n\n" + OUTPUT_FORMAT
    human = f"DOCUMENT FILENAME: {file_name}\n\nDOCUMENT CONTENT:\n{text}"
    try:
        resp = llm.get_llm().invoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        data = json.loads(_strip_to_json(raw))
    except Exception as e:  # noqa: BLE001
        empty["inconsistencies"] = [f"Extraction failed: {e}"]
        return empty

    data.setdefault("initiative", {})
    for k in ("milestones", "risks", "value_drivers", "inconsistencies"):
        data.setdefault(k, [])
    data["summary"] = _summary(data["initiative"], data)
    data["_method"] = "llm"
    return data
