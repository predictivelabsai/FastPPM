"""Ingestion orchestration: process an uploaded document, then merge it.

    process_document(id)  : extract → normalize → store candidate entities,
                            set status='extracted' with counts. (No canonical
                            writes yet — the user reviews first.)
    merge_document(id)    : write the (possibly edited) candidate entities into
                            the canonical initiatives/milestones/risks/value
                            tables, link the source doc, set status='merged'.

Both are idempotent and defensive so a bad file degrades to an error status
rather than aborting a bulk upload.
"""

from __future__ import annotations

import ppmstore as store
from ingest import extract as ex
from ingest import normalize as nm


def process_document(document_id: int, use_ai: bool = True) -> dict:
    """Extract + normalize one uploaded document; persist candidate entities."""
    doc = store.get_document(document_id)
    if not doc:
        return {}
    store.update_document(document_id, {"status": "parsing"})
    try:
        extracted = ex.extract(doc["file_path"])
        data = nm.normalize(extracted, doc["file_name"], use_ai=use_ai)
    except Exception as e:  # noqa: BLE001
        store.update_document(document_id, {"status": "error", "error": str(e)})
        return {}
    store.update_document(document_id, {
        "status": "extracted",
        "raw_text": (extracted.get("text") or "")[:200000],
        "structured_json": data,
        "summary": data.get("summary"),
        "n_initiatives": 1 if data.get("initiative", {}).get("name") else 0,
        "n_milestones": len(data.get("milestones", [])),
        "n_risks": len(data.get("risks", [])),
        "n_value_drivers": len(data.get("value_drivers", [])),
        "n_inconsistencies": len(data.get("inconsistencies", [])),
    })
    return data


def _next_ref() -> str:
    return f"INI-{store.count_initiatives() + 1:03d}"


def merge_document(document_id: int, actor: str = "ingestion",
                   data: dict | None = None) -> dict:
    """Write candidate entities to the canonical tables. Returns counts."""
    doc = store.get_document(document_id)
    if not doc:
        return {}
    data = data or doc.get("structured_json") or {}
    ini = data.get("initiative") or {}
    name = ini.get("name") or doc["file_name"]

    # Find an existing initiative by name, else create one with a fresh ref.
    existing = next((i for i in store.list_initiatives() if i["name"].lower() == name.lower()), None)
    ref = existing["ref"] if existing and existing.get("ref") else _next_ref()
    iid = store.upsert_initiative({
        "ref": ref, "name": name, "type": ini.get("type") or "workstream",
        "owner": ini.get("owner"), "status": ini.get("status") or "in_progress",
        "rag": _rag_from_status(ini.get("status")),
        "value_target": ini.get("value_target"), "value_realized": ini.get("value_realized"),
        "value_category": ini.get("value_category"), "source_document_id": document_id,
    })

    n_m = n_r = n_v = 0
    progresses = []
    for m in data.get("milestones", []):
        if not m.get("title"):
            continue
        store.upsert_milestone({"initiative_id": iid, **{k: m.get(k) for k in
                                ("title", "planned_date", "actual_date", "baseline_date",
                                 "progress", "status", "owner")}})
        if m.get("progress") is not None:
            progresses.append(m["progress"])
        n_m += 1
    for r in data.get("risks", []):
        if not r.get("description"):
            continue
        store.upsert_risk({"initiative_id": iid, **{k: r.get(k) for k in
                           ("description", "probability", "impact", "mitigation", "status")}})
        n_r += 1
    target = realized = 0.0
    for v in data.get("value_drivers", []):
        period = v.get("period") or "2026"
        store.add_value_entry({"initiative_id": iid, "period": str(period)[:7],
                               "category": v.get("category") or "ebitda",
                               "planned": v.get("target") or 0, "realized": v.get("realized") or 0})
        target += v.get("target") or 0
        realized += v.get("realized") or 0
        n_v += 1

    # Roll progress / value up onto the initiative when the doc didn't state them.
    patch = {}
    if progresses and not ini.get("progress"):
        patch["progress"] = round(sum(progresses) / len(progresses), 0)
    if target and not ini.get("value_target"):
        patch["value_target"] = target
    if realized and not ini.get("value_realized"):
        patch["value_realized"] = realized
    if patch:
        store.set_initiative_fields(iid, patch)

    store.update_document(document_id, {"status": "merged", "merged_at": store.utcnow()})
    store.log_activity({"entity_type": "initiative", "entity_id": iid, "action": "merge",
                        "detail": f"Merged {n_m} milestones, {n_r} risks, {n_v} value drivers "
                                  f"from {doc['file_name']}", "actor": actor})
    return {"initiative_id": iid, "milestones": n_m, "risks": n_r, "value_drivers": n_v}


def _rag_from_status(status: str | None) -> str:
    return {"complete": "G", "on_track": "G", "in_progress": "G",
            "at_risk": "A", "delayed": "R", "not_started": "A"}.get(status or "", "A")
