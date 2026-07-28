"""LangGraph orchestrator — the FastPPM chat analyst.

A ReAct agent that routes transformation-office questions to the specialist
tools and streams the answer as SSE. Assumes an LLM key is configured; without
one it returns the deterministic programme overview (no keyword/regex routing).
"""

from __future__ import annotations

from datetime import date

from agents import sse
from agents.tools import ALL_TOOLS, programme_status
from rag import llm

SYSTEM = (
    f"Today's date is {date.today().isoformat()}. "
    "You are FastPPM, the AI project analyst for a PE portfolio company's "
    "Transformation Office. You know every transformation initiative and internal "
    "AI use case in the Value Creation Plan. Answer questions about status, value "
    "creation, risks, milestones and the ingested source documents using ONLY your "
    "tools — never invent numbers. Be concise and write for an executive / PMO "
    "audience; use markdown tables for lists.\n\n"
    "Tools:\n"
    "- programme_status: overall health, RAG, value realised vs target.\n"
    "- initiative_agent: a named initiative, or all initiatives in a red/amber/green/at-risk status.\n"
    "- risk_agent: top risks by probability × impact.\n"
    "- value_agent: value realised vs target, by category, top contributors.\n"
    "- document_agent: search the ingested status reports / trackers / decks.\n"
    "- update_agent: apply an explicit status update — pass the milestone/initiative "
    "name as `target`, plus `progress` (0-100) and/or `status`.\n"
    "- show_statistics: render a STATISTICS TABLE with a chart offer. Use this "
    "for ANY quantitative / breakdown / comparison / trend question (e.g. value "
    "by category, RAG counts, progress by workstream, top risks, value over "
    "time). Pass the metric and your recommended chart_type (line for a time "
    "series, bar for comparisons, pie for parts-of-whole). The UI shows the table "
    "and lets the user pick a chart, so add only a one-line lead — do NOT restate "
    "the figures or draw an ASCII table.\n\n"
    "Keep [initiative:N] markers the tools return so the UI can link. Prefer £m."
)

_agent = None


def get_agent():
    global _agent
    if _agent is None:
        from langgraph.prebuilt import create_react_agent
        _agent = create_react_agent(llm.get_llm(), ALL_TOOLS, prompt=SYSTEM)
    return _agent


async def astream(question: str, history: list | None = None):
    if not llm.ai_available():
        yield sse.event(sse.TOKEN, {"text": programme_status.invoke({"query": question})
                                    + "\n\n_(Set `XAI_API_KEY` to enable full natural-language Q&A.)_"})
        yield sse.event(sse.DONE, {"tools": 0})
        return
    msgs = list(history or []) + [("user", question)]
    tool_count = 0
    # Request-scoped sink: show_statistics appends rendered datasets here (via the
    # injected RunnableConfig), and we drain it into `dataset` SSE events as each
    # tool finishes — keeping structured data out of the LLM's view.
    sink: list[dict] = []
    config = {"configurable": {"dataset_sink": sink}}
    try:
        async for ev in get_agent().astream_events({"messages": msgs}, version="v2",
                                                    config=config):
            kind = ev["event"]
            if kind == "on_chat_model_stream":
                chunk = ev["data"].get("chunk")
                text = getattr(chunk, "content", "") if chunk else ""
                if text:
                    yield sse.event(sse.TOKEN, {"text": text})
            elif kind == "on_tool_start":
                tool_count += 1
                yield sse.event(sse.TOOL_START, {"name": ev.get("name", "tool")})
            elif kind == "on_tool_end":
                yield sse.event(sse.TOOL_END, {"name": ev.get("name", "tool")})
                while sink:
                    yield sse.event(sse.DATASET, sink.pop(0))
        while sink:  # flush any stragglers
            yield sse.event(sse.DATASET, sink.pop(0))
        yield sse.event(sse.DONE, {"tools": tool_count})
    except Exception as e:  # noqa: BLE001
        yield sse.event(sse.TOKEN, {"text": f"_(analyst error: {e})_"})
        yield sse.event(sse.DONE, {"tools": tool_count})
