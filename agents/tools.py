"""Specialist copilot tools over the FastPPM repository.

LangChain ``@tool`` functions the orchestrator routes to. Reads return compact
plain-English text with [initiative:N] markers; ``update_agent`` performs natural-
language status updates ("mark milestone X 80% complete") against the canonical
data and writes an audit entry.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

import ppmstore as store
from agents import analytics


def _m(v):
    v = float(v or 0)
    if abs(v) >= 1e6:
        return f"£{v/1e6:.1f}m"
    if abs(v) >= 1e3:
        return f"£{v/1e3:.0f}k"
    return f"£{v:.0f}"


_CHART_TYPES = ("bar", "pie", "line", "donut", "kpi")


@tool
def show_statistics(metric: str, chart_type: str = "", config: RunnableConfig = None) -> str:
    """Show a STATISTICS TABLE (with a chart offer) for a quantitative question.

    Use this for ANY 'how many', 'show me the numbers', breakdown, comparison or
    trend question — the UI renders the table and offers chart chips so the user
    can see it as a bar / pie / line chart. ``metric`` is one of:
      - value_by_category: value realised vs target by category (EBITDA, cost…)
      - rag_breakdown: initiative counts by RAG health (red / amber / green)
      - status_breakdown: initiative counts by workflow status
      - progress_by_initiative: % complete per initiative
      - progress_by_workstream: average % complete per workstream
      - top_risks: highest risks by probability × impact
      - value_over_time: value realised vs planned by period (a time series)
    Set ``chart_type`` to your recommended view: ``line`` for a time series,
    ``bar`` for comparisons, ``pie`` for parts-of-whole. Returns a one-line
    summary; the table renders beneath it, so do NOT restate the figures."""
    metric = (metric or "").strip().lower()
    if metric not in analytics.BUILDERS:
        return (f"Unknown metric '{metric}'. Choose one of: "
                f"{', '.join(analytics.BUILDERS)}.")
    ds = analytics.build(metric)
    if not ds.rows:
        return f"No data available for {metric} yet."
    payload = ds.as_dict()
    ct = (chart_type or "").strip().lower()
    if ct in _CHART_TYPES:
        payload["recommended"] = ct                       # the LLM's pick wins
        if ct not in payload["offered"]:
            payload["offered"] = [ct, *payload["offered"]]
    # Hand the dataset out-of-band to the orchestrator via the request-scoped
    # sink (injected through RunnableConfig — never seen by the LLM).
    sink = (config or {}).get("configurable", {}).get("dataset_sink")
    if sink is not None:
        sink.append(payload)
    return f"{ds.note} (Table and chart options shown to the user.)"


@tool
def programme_status(query: str = "") -> str:
    """Overall transformation programme health: initiative counts, RAG, on-track
    %, average progress, on-time delivery, value realised vs target, open risks.
    Use for 'overall status', 'how is the programme doing' questions."""
    s = store.portfolio_summary()
    return (
        f"Value Creation Plan: {s['total_initiatives']} initiatives "
        f"({s['types'].get('ai_use_case',0)} AI use cases). "
        f"RAG among active: {s['rag'].get('G',0)} green, {s['rag'].get('A',0)} amber, "
        f"{s['rag'].get('R',0)} red ({s['on_track_pct']}% on track). "
        f"Average progress {s['avg_progress']:.0f}%, on-time delivery {s['on_time_pct']:.0f}%. "
        f"Value realised {_m(s['value_realized'])} of {_m(s['value_target'])} target "
        f"({s['realization_pct']}%). {s['open_risks']} open risks "
        f"({s['high_risks']} high). {s['documents_merged']} documents ingested."
    )


@tool
def initiative_agent(name_or_status: str = "") -> str:
    """Details for a named initiative, or all initiatives in a RAG/status. Pass an
    initiative name fragment, or 'red'/'amber'/'green'/'at risk'/'delayed'.
    Use for 'status of X', 'which initiatives are red' questions."""
    q = (name_or_status or "").strip().lower()
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    rag_map = {"red": "R", "amber": "A", "green": "G"}
    status_words = {"at risk": "at_risk", "delayed": "delayed", "on track": "on_track",
                    "complete": "complete", "in progress": "in_progress"}
    sel = None
    if q in rag_map:
        sel = [i for i in inis if (i.get("rag") or "").upper() == rag_map[q]]
    elif q in status_words:
        sel = [i for i in inis if i.get("status") == status_words[q]]
    if sel is not None:
        if not sel:
            return f"No initiatives matching '{name_or_status}'."
        lines = [f"{len(sel)} initiative(s) — {name_or_status}:"]
        for i in sel:
            lines.append(f"  - {i['name']} ({int(i.get('progress') or 0)}%, "
                         f"{i.get('status')}) — value {_m(i.get('value_realized'))}/"
                         f"{_m(i.get('value_target'))} [initiative:{i['id']}]")
        return "\n".join(lines)
    hits = [i for i in inis if q in (i["name"] or "").lower()]
    if not hits:
        return f"No initiative matching '{name_or_status}'."
    out = []
    for i in hits[:4]:
        ms = store.list_milestones(i["id"])
        nxt = next((m for m in ms if (m.get("progress") or 0) < 100), None)
        out.append(
            f"**{i['name']}** ({i.get('status')}, {i.get('workstream')}) [initiative:{i['id']}]\n"
            f"  Owner {i.get('owner')}. Progress {int(i.get('progress') or 0)}%. "
            f"Value {_m(i.get('value_realized'))} of {_m(i.get('value_target'))} "
            f"({i.get('value_category')}). {len(ms)} milestones, {i.get('risk_count',0)} risks.\n"
            f"  Next milestone: {nxt['title'] + ' due ' + (nxt.get('planned_date') or '') if nxt else 'all complete'}.")
    return "\n".join(out)


@tool
def risk_agent(query: str = "") -> str:
    """Top risks across the programme (or for a named initiative), ranked by
    probability × impact. Use for 'top risks', 'red risks' questions."""
    risks = store.list_risks()
    if not risks:
        return "No risks recorded."
    lines = ["Top risks (probability × impact):"]
    for r in risks[:8]:
        score = (r.get("probability") or 0) * (r.get("impact") or 0)
        lines.append(f"  - [{score}] {r['description']} — {r['initiative_name']} "
                     f"(P{r.get('probability')}×I{r.get('impact')}). "
                     f"Mitigation: {r.get('mitigation') or '—'}")
    return "\n".join(lines)


@tool
def value_agent(query: str = "") -> str:
    """Value creation: realised vs target overall and by category, and the top
    value-contributing initiatives. Use for 'value realised', 'value drivers',
    'EBITDA impact' questions."""
    vs = store.value_summary()
    lines = [f"Value realised {_m(vs['realized'])} of {_m(vs['target'])} target "
             f"({vs['realization_pct']}%)."]
    if vs["by_category"]:
        lines.append("By category:")
        for c in vs["by_category"]:
            lines.append(f"  - {c['category']}: {_m(c['realized'])} of {_m(c['target'])}")
    drivers = sorted([i for i in store.list_initiatives() if i["type"] != "program"
                      and i.get("value_realized")],
                     key=lambda i: i["value_realized"], reverse=True)[:6]
    lines.append("Top value contributors:")
    for i in drivers:
        lines.append(f"  - {i['name']}: {_m(i['value_realized'])} realised of "
                     f"{_m(i['value_target'])} [initiative:{i['id']}]")
    return "\n".join(lines)


@tool
def document_agent(query: str = "") -> str:
    """Search the ingested source documents (status reports, trackers, decks) and
    answer with citations. Use for 'what did the X report say', document look-ups."""
    hits = store.search_documents(query, limit=5)
    if not hits:
        return "No matching content in the ingested documents."
    lines = ["From the ingested documents:"]
    for h in hits:
        lines.append(f"  - [{h['file_name']}] …{h['snippet']}…")
    return "\n".join(lines)


_STATUS_ONLY = ("at_risk", "delayed", "on_track", "on_hold")
_RAG_FOR_STATUS = {"at_risk": "A", "delayed": "R", "on_track": "G",
                   "complete": "G", "in_progress": "G", "on_hold": "A"}


@tool
def update_agent(target: str = "", progress: int = -1, status: str = "") -> str:
    """Apply a status update to a milestone or initiative. ``target`` is the
    milestone or initiative NAME. Set ``progress`` to 0-100 to update completion
    (targets a milestone), and/or ``status`` to one of not_started/in_progress/
    on_track/at_risk/delayed/complete/on_hold (targets an initiative). Use ONLY
    for explicit update requests."""
    pct = progress if isinstance(progress, int) and 0 <= progress <= 100 else None
    status = (status or "").strip().lower().replace(" ", "_") or None
    detail = f"target='{target}' progress={pct} status={status}"

    # A progress/completion update targets a milestone (workflow statuses like
    # 'at risk' are initiative-level). Match "<milestone> <initiative>" so the
    # initiative name disambiguates titles shared across initiatives.
    if pct is not None and status not in _STATUS_ONLY:
        best_m = _best_match(target, [(f"{m['title']} {m['initiative_name']}", m)
                                      for m in store.list_milestones()])
        if best_m:
            new_status = "done" if pct >= 100 else "in_progress"
            store.set_milestone_fields(best_m["id"], {"progress": pct, "status": new_status})
            store.log_activity({"entity_type": "milestone", "entity_id": best_m["id"],
                                "action": "nl_update", "detail": detail, "actor": "copilot"})
            return (f"Updated milestone '{best_m['title']}' "
                    f"(initiative: {best_m['initiative_name']}) → {pct}%, status {new_status}.")

    # Otherwise update an initiative's status and/or progress.
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    best_i = _best_match(target, [(i["name"], i) for i in inis])
    if best_i and (status or pct is not None):
        fields = {}
        if status:
            fields["status"] = status
            fields["rag"] = _RAG_FOR_STATUS.get(status)
        if pct is not None:
            fields["progress"] = pct
        store.set_initiative_fields(best_i["id"], fields)
        store.log_activity({"entity_type": "initiative", "entity_id": best_i["id"],
                            "action": "nl_update", "detail": detail, "actor": "copilot"})
        bits = [f"status {status}"] if status else []
        if pct is not None:
            bits.append(f"{pct}%")
        return f"Updated initiative '{best_i['name']}' → {', '.join(bits)}."
    return (f"Could not match '{target}' to a milestone or initiative. Name it more "
            "specifically.")


def _words(s: str) -> set[str]:
    """Lowercased word set with punctuation stripped — no regex."""
    keep = []
    for ch in (s or "").lower():
        keep.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return set(w for w in "".join(keep).split() if len(w) > 2)


def _best_match(query: str, candidates: list[tuple[str, dict]]) -> dict | None:
    qwords = _words(query)
    if not qwords:
        return None
    best, best_score = None, 0
    for label, obj in candidates:
        score = len(qwords & _words(label))
        if score > best_score:
            best, best_score = obj, score
    return best if best_score >= 1 else None


ALL_TOOLS = [programme_status, initiative_agent, risk_agent, value_agent,
             document_agent, update_agent, show_statistics]
