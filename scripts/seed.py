"""Load the demo transformation programme into the active backend.

Reads config/programme.yaml, then:
  - upserts the programme + its workstreams / AI use cases (canonical initiatives),
  - generates milestones (baseline vs planned vs actual dates + dependency chain),
    risks and quarterly value tracking for each, deterministically,
  - generates the messy sample source documents (scripts.gen_samples) and
    registers all four; two are processed + merged so the document corpus has
    content for chat RAG and appears in the master view, two are left in the
    ingestion queue to demo the flagship upload → review → merge flow live.

Idempotent + process-independent (stable crc32 seeding). Run: python -m scripts.seed
"""

from __future__ import annotations

import random
import zlib
from datetime import date, timedelta
from pathlib import Path

import yaml

import ppmstore as store

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

TODAY = date(2026, 6, 22)
QUARTERS = [("2026-Q1", date(2026, 3, 31)), ("2026-Q2", date(2026, 6, 30)),
            ("2026-Q3", date(2026, 9, 30)), ("2026-Q4", date(2026, 12, 31))]

MILESTONE_STAGES = ["Mobilise & charter", "Design / baseline", "Build / pilot",
                    "First value / rollout", "Scale & embed", "Benefits realisation"]

RISK_LIBRARY = [
    ("Key-person / resourcing dependency", 3, 3),
    ("Vendor or delivery slippage", 4, 4),
    ("Scope creep vs. baseline", 3, 3),
    ("Benefit realisation slower than plan", 3, 4),
    ("Data quality / model accuracy below target", 3, 4),
    ("Business-unit adoption resistance", 2, 3),
]


def _seed_int(s: str) -> int:
    return zlib.crc32(s.encode())


def _iso(d: date) -> str:
    return d.isoformat()


def _as_date(v) -> date:
    """YAML may give us a date object or an ISO string."""
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _iso_or_none(v):
    return _iso(_as_date(v)) if v else None


def _gen_milestones(ini: dict):
    ref = ini["ref"]
    if ini["type"] == "program":
        return  # programme rolls up its children; no own milestones
    rng = random.Random(_seed_int(ref))
    start = _as_date(ini["start"])
    end = _as_date(ini["end"])
    base_end = _as_date(ini.get("baseline_end") or ini["end"])
    rag = ini.get("rag", "G")
    progress = ini.get("progress", 0)
    n = 5
    span = (end - start).days
    base_span = (base_end - start).days
    slip = {"G": 0, "A": 12, "R": 28}.get(rag, 0)
    prev_title = None
    iid = ini["_id"]
    for i in range(n):
        frac = (i + 1) / n
        baseline_d = start + timedelta(days=int(base_span * frac))
        planned_d = baseline_d + timedelta(days=int(slip * frac) + rng.randint(-3, 5))
        # A milestone is "done" if its share of the timeline is below progress.
        done = (frac * 100) <= progress + 2
        actual_d = None
        status = "open"
        m_prog = 0
        if done:
            actual_d = planned_d + timedelta(days=rng.randint(-2, slip // 2 + 4))
            status = "done"
            m_prog = 100
        elif (frac * 100) <= progress + 22:
            status = "in_progress"
            m_prog = rng.randint(30, 80)
        title = MILESTONE_STAGES[i] if i < len(MILESTONE_STAGES) else f"Phase {i+1}"
        deps = []
        if prev_title is not None:
            prev = next((m for m in store.list_milestones(iid) if m["title"] == prev_title), None)
            if prev:
                deps = [prev["id"]]
        mid = store.upsert_milestone({
            "initiative_id": iid, "title": title, "owner": ini.get("owner"),
            "baseline_date": _iso(baseline_d), "planned_date": _iso(planned_d),
            "actual_date": _iso(actual_d) if actual_d else None,
            "progress": m_prog, "status": status, "dependencies": deps,
        })
        prev_title = title


def _gen_risks(ini: dict):
    if ini["type"] == "program":
        return
    rng = random.Random(_seed_int(ini["ref"] + "r"))
    n = {"G": 1, "A": 2, "R": 3}.get(ini.get("rag", "G"), 1)
    picks = rng.sample(RISK_LIBRARY, n)
    bump = {"G": 0, "A": 0, "R": 1}.get(ini.get("rag", "G"), 0)
    for desc, p, im in picks:
        store.upsert_risk({"initiative_id": ini["_id"], "description": desc,
                           "probability": min(5, p + bump), "impact": min(5, im),
                           "mitigation": "Owned mitigation; reviewed at programme board.",
                           "owner": ini.get("owner"), "status": "open"})


def _gen_value(ini: dict):
    if ini["type"] == "program":
        return
    target = ini.get("value_target", 0) or 0
    realized = ini.get("value_realized", 0) or 0
    cat = ini.get("value_category", "ebitda")
    # Plan ramps linearly to target over the year; realised is loaded into the
    # quarters that have passed, summing to value_realized.
    realized_split = [0.45, 0.55, 0.0, 0.0]  # Q1, Q2 actuals; Q3/Q4 not yet
    for (period, q_end), rfrac in zip(QUARTERS, realized_split):
        frac = min(1.0, max(0.1, ((q_end - date(2026, 1, 1)).days) / 364))
        store.add_value_entry({
            "initiative_id": ini["_id"], "period": period, "category": cat,
            "planned": round(target * frac, 0),
            "realized": round(realized * rfrac, 0) if q_end <= TODAY else 0,
        })


def _load_documents():
    """Generate the sample docs and register them for the ingestion demo.

    Extraction is LLM-only, so we only process/pre-merge when an API key is
    configured; otherwise the docs sit in the 'uploaded' queue for the reviewer
    to extract once a key is set."""
    from scripts import gen_samples
    from ingest import service, extract as ex
    from rag import llm
    paths = gen_samples.generate()
    pre_merge = {"SupplyChain_AI_Forecasting_Tracker.xlsx",
                 "Finance_Automation_Board_Update.pptx"}
    ai = llm.ai_available()
    for p in paths:
        # Skip if already registered (idempotent re-seed).
        if any(d["file_name"] == p.name for d in store.list_documents()):
            continue
        did = store.add_document({
            "file_name": p.name, "file_type": ex.file_type(p.name),
            "file_path": str(p), "byte_size": p.stat().st_size,
            "status": "uploaded", "uploaded_by": "seed"})
        if ai:
            # Extract → candidate entities; pre-merge two into the master view +
            # document corpus, leave two in the 'extracted' queue for a live merge.
            service.process_document(did)
            if p.name in pre_merge:
                service.merge_document(did, actor="seed")


def main():
    cfg = yaml.safe_load((CONFIG / "programme.yaml").read_text())
    store.init_db()

    # Register the editable extraction prompt (idempotent) for the Prompt Manager.
    from ingest.normalize import DEFAULT_EXTRACTION_PROMPT, PROMPT_KEY
    store.ensure_prompt(PROMPT_KEY, "Document extraction",
                        "System prompt guiding what the LLM extracts from uploaded documents.",
                        DEFAULT_EXTRACTION_PROMPT)

    inis = cfg["initiatives"]
    # First pass: create all initiatives (so parents exist for parent_ref).
    for ini in inis:
        ini["_id"] = store.upsert_initiative({
            "ref": ini["ref"], "name": ini["name"], "type": ini["type"],
            "workstream": ini.get("workstream"), "owner": ini.get("owner"),
            "status": ini.get("status"), "rag": ini.get("rag"),
            "progress": ini.get("progress"),
            "start_date": _iso_or_none(ini.get("start")),
            "end_date": _iso_or_none(ini.get("end")),
            "baseline_end": _iso_or_none(ini.get("baseline_end")),
            "baseline_start": _iso_or_none(ini.get("start")),
            "value_target": ini.get("value_target"),
            "value_realized": ini.get("value_realized"),
            "value_category": ini.get("value_category"),
            "parent_ref": ini.get("parent"),
        })
    # Second pass: dependent records.
    for ini in inis:
        _gen_milestones(ini)
        _gen_risks(ini)
        _gen_value(ini)

    _load_documents()

    s = store.portfolio_summary()
    print(f"Seeded {s['total_initiatives']} initiatives "
          f"({s['types'].get('ai_use_case',0)} AI use cases) · "
          f"avg progress {s['avg_progress']:.0f}% · value realised "
          f"£{s['value_realized']/1e6:.1f}m of £{s['value_target']/1e6:.1f}m "
          f"({s['realization_pct']}%) · {s['documents_merged']}/{s['documents_total']} docs merged")


if __name__ == "__main__":
    main()
