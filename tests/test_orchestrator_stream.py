"""The orchestrator drains the request-scoped dataset sink into `dataset` SSE
events as tools finish — so a stats question streams a structured table payload
to the UI, ordered after the tool that produced it.

Driven with a fake agent (no LLM key needed) that mimics show_statistics
populating the sink it receives via RunnableConfig.
"""

from __future__ import annotations

import json

import pytest

from agents import orchestrator


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    """Stands in for the LangGraph ReAct agent: simulates a tool call that fills
    the injected sink, then streams a short text answer."""

    async def astream_events(self, inputs, version, config):
        sink = config["configurable"]["dataset_sink"]
        yield {"event": "on_tool_start", "name": "show_statistics", "data": {}}
        sink.append({"id": "rag_breakdown", "title": "Initiatives by RAG status",
                     "columns": [{"key": "status", "label": "RAG", "type": "category"},
                                 {"key": "count", "label": "Initiatives", "type": "number"}],
                     "rows": [{"status": "Green", "count": 6}, {"status": "Red", "count": 1}],
                     "x": "status", "y": ["count"], "recommended": "bar",
                     "offered": ["bar", "pie"]})
        yield {"event": "on_tool_end", "name": "show_statistics", "data": {}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("Here's the breakdown.")}}


def _parse(raw: str):
    name = next(l[len("event: "):] for l in raw.splitlines() if l.startswith("event: "))
    data = next(l[len("data: "):] for l in raw.splitlines() if l.startswith("data: "))
    return name, json.loads(data)


@pytest.mark.asyncio
async def test_dataset_event_streams_after_tool(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ai_available", lambda: True)
    monkeypatch.setattr(orchestrator, "get_agent", lambda: _FakeAgent())

    events = [_parse(ev) async for ev in orchestrator.astream("how many are red?")]
    names = [n for n, _ in events]

    assert "dataset" in names
    # The dataset arrives right after its tool finishes, before the final token.
    assert names.index("tool_end") < names.index("dataset") < names.index("token")

    payload = next(d for n, d in events if n == "dataset")
    assert payload["id"] == "rag_breakdown"
    assert payload["recommended"] == "bar" and "pie" in payload["offered"]
    assert [r["status"] for r in payload["rows"]] == ["Green", "Red"]

    assert names[-1] == "done"  # stream always terminates with done
