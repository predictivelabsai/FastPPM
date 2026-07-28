"""Contract test for the FastPPM Storage backend.

Covers the canonical model the app and ingestion engine rely on: initiatives
(with parent rollup), milestones (+dependencies), risks, value tracking, the
document lifecycle, the activity log and the programme rollup.
"""

from __future__ import annotations


def test_admin_seeded(store):
    u = store.get_user_by_email("admin@example.com")
    assert u and u["role"] == "admin" and u["password_hash"]


def test_initiative_upsert_and_parent(store):
    prog = store.upsert_initiative({"ref": "VCP", "name": "Value Creation Plan",
                                    "type": "program"})
    payload = {"ref": "WS-1", "name": "Pricing", "type": "workstream",
               "owner": "CFO", "status": "on_track", "rag": "G",
               "progress": 60, "value_target": 2_000_000,
               "value_realized": 800_000, "value_category": "ebitda",
               "parent_ref": "VCP"}
    iid = store.upsert_initiative(payload)
    assert store.upsert_initiative(payload) == iid  # idempotent by ref
    i = store.get_initiative(iid)
    assert i["parent_name"] == "Value Creation Plan"
    assert store.get_initiative_by_ref("WS-1")["id"] == iid
    assert len(store.list_initiatives(parent_id=prog)) == 1


def test_milestones_with_dependencies(store):
    iid = store.upsert_initiative({"ref": "WS-2", "name": "ERP"})
    m1 = store.upsert_milestone({"initiative_id": iid, "title": "Design",
                                 "planned_date": "2026-03-01", "progress": 100, "status": "done"})
    build = {"initiative_id": iid, "title": "Build", "planned_date": "2026-06-01",
             "dependencies": [m1]}
    m2 = store.upsert_milestone(build)
    assert store.upsert_milestone(build) == m2  # idempotent by (initiative, title)
    got = store.get_milestone(m2)
    assert got["dependencies"] == [m1]
    ms = store.list_milestones(iid)
    assert [m["title"] for m in ms] == ["Design", "Build"]  # ordered by planned_date
    assert ms[0]["initiative_name"] == "ERP"


def test_set_milestone_fields(store):
    iid = store.upsert_initiative({"ref": "WS-3", "name": "CRM"})
    mid = store.upsert_milestone({"initiative_id": iid, "title": "Pilot", "progress": 30})
    store.set_milestone_fields(mid, {"progress": 90, "status": "in_progress"})
    assert store.get_milestone(mid)["progress"] == 90


def test_risks_ordered(store):
    iid = store.upsert_initiative({"ref": "WS-4", "name": "Ops"})
    store.upsert_risk({"initiative_id": iid, "description": "Minor", "probability": 2, "impact": 2})
    store.upsert_risk({"initiative_id": iid, "description": "Major", "probability": 5, "impact": 4})
    risks = store.list_risks(iid)
    assert risks[0]["description"] == "Major"  # highest probability×impact first
    assert risks[0]["initiative_name"] == "Ops"


def test_value_tracking(store):
    iid = store.upsert_initiative({"ref": "WS-5", "name": "Working capital",
                                   "type": "workstream", "value_target": 1_000_000,
                                   "value_realized": 400_000, "value_category": "cost_savings"})
    store.add_value_entry({"initiative_id": iid, "period": "2026-Q1",
                           "category": "cost_savings", "planned": 250_000, "realized": 200_000})
    store.add_value_entry({"initiative_id": iid, "period": "2026-Q1",
                           "category": "cost_savings", "planned": 250_000, "realized": 220_000})
    assert len(store.list_value_entries(iid)) == 1  # upsert by (init, period, category)
    s = store.value_summary()
    assert s["target"] == 1_000_000 and s["realized"] == 400_000
    assert s["realization_pct"] == 40.0


def test_program_excluded_from_value(store):
    store.upsert_initiative({"ref": "VCP", "name": "Programme", "type": "program",
                             "value_target": 5_000_000, "value_realized": 1_000_000})
    store.upsert_initiative({"ref": "WS-6", "name": "Leaf", "type": "workstream",
                             "value_target": 2_000_000, "value_realized": 800_000})
    s = store.value_summary()
    assert s["target"] == 2_000_000  # programme node excluded from the rollup


def test_document_lifecycle(store):
    did = store.add_document({"file_name": "status.pdf", "file_type": "pdf",
                              "file_path": "/tmp/status.pdf", "status": "uploaded"})
    store.update_document(did, {
        "status": "extracted", "raw_text": "pricing optimisation milestone build",
        "structured_json": {"milestones": [{"title": "Build"}]},
        "n_milestones": 1})
    d = store.get_document(did)
    assert d["status"] == "extracted"
    assert d["structured_json"]["milestones"][0]["title"] == "Build"  # parsed back
    assert store.list_documents(status="extracted")[0]["id"] == did
    # search only returns merged docs
    assert store.search_documents("pricing") == []
    store.update_document(did, {"status": "merged"})
    assert store.search_documents("pricing")[0]["id"] == did


def test_activity_log(store):
    iid = store.upsert_initiative({"ref": "WS-7", "name": "Data"})
    store.log_activity({"entity_type": "initiative", "entity_id": iid,
                        "action": "merge", "detail": "from x.pdf", "actor": "pmo"})
    acts = store.list_activity(entity_type="initiative", entity_id=iid)
    assert acts[0]["action"] == "merge"


def test_portfolio_summary(store):
    store.upsert_initiative({"ref": "VCP", "name": "Programme", "type": "program"})
    iid = store.upsert_initiative({"ref": "WS-8", "name": "AI forecasting",
                                   "type": "ai_use_case", "status": "on_track", "rag": "G",
                                   "progress": 60, "value_target": 1_000_000,
                                   "value_realized": 300_000})
    store.upsert_milestone({"initiative_id": iid, "title": "Pilot",
                            "planned_date": "2026-03-01", "actual_date": "2026-02-25",
                            "progress": 100, "status": "done"})
    store.upsert_risk({"initiative_id": iid, "description": "Data quality",
                       "probability": 4, "impact": 4})
    s = store.portfolio_summary()
    assert s["total_initiatives"] == 1  # program excluded
    assert s["types"]["ai_use_case"] == 1
    assert s["on_track_pct"] == 100.0
    assert s["value_realized"] == 300_000
    assert s["on_time_pct"] == 100.0  # delivered before planned
    assert s["open_risks"] == 1 and s["high_risks"] == 1


def test_prompt_manager(store):
    # ensure_prompt is idempotent and creates an active version 1.
    store.ensure_prompt("extraction", "Document extraction", "desc", "PROMPT v1")
    store.ensure_prompt("extraction", "Document extraction", "desc", "ignored")  # no overwrite
    p = store.get_prompt("extraction")
    assert p["active_version"] == 1
    assert p["active_content"] == "PROMPT v1"
    assert store.get_active_prompt_content("extraction") == "PROMPT v1"
    assert len(store.list_prompt_versions("extraction")) == 1

    # Adding a version makes it active.
    v2 = store.add_prompt_version("extraction", "PROMPT v2", notes="tweak", created_by="pmo")
    assert v2["version"] == 2
    assert store.get_active_prompt_content("extraction") == "PROMPT v2"
    versions = store.list_prompt_versions("extraction")
    assert [v["version"] for v in versions] == [2, 1]  # newest first
    assert versions[0]["is_active"] and not versions[1]["is_active"]

    # Re-activate the old version.
    v1_id = next(v["id"] for v in versions if v["version"] == 1)
    store.set_active_prompt_version("extraction", v1_id)
    assert store.get_active_prompt_content("extraction") == "PROMPT v1"

    listed = next(x for x in store.list_prompts() if x["key"] == "extraction")
    assert listed["version_count"] == 2


def test_reports(store):
    tid = store.add_report_template({"name": "Board.docx", "file_type": "docx",
                                     "outline": "- Summary\n- Value\n- Risks", "uploaded_by": "pmo"})
    assert store.get_report_template(tid)["name"] == "Board.docx"
    assert len(store.list_report_templates()) == 1

    rid = store.create_report("Q2 Report", [
        {"type": "heading1", "content": "Q2 Report"},
        {"type": "paragraph", "content": "<div>On track.</div>"},
        {"type": "bullet", "content": "<ul><li>a</li></ul>"},
    ], template_name="Board.docx", created_by="pmo")
    assert store.get_report(rid)["title"] == "Q2 Report"
    assert store.list_reports()[0]["block_count"] == 3

    blocks = store.list_report_blocks(rid)
    assert [b["type"] for b in blocks] == ["heading1", "paragraph", "bullet"]

    # edit, add (after), reorder, delete
    store.update_report_block(blocks[1]["id"], "<div>Edited.</div>", type="paragraph")
    assert store.get_report_block(blocks[1]["id"])["content"] == "<div>Edited.</div>"
    nb = store.add_report_block(rid, "heading2", "New section", after_id=blocks[0]["id"])
    order = [b["type"] for b in store.list_report_blocks(rid)]
    assert order == ["heading1", "heading2", "paragraph", "bullet"]
    store.move_report_block(nb, 1)  # heading2 down past paragraph
    order2 = [b["type"] for b in store.list_report_blocks(rid)]
    assert order2 == ["heading1", "paragraph", "heading2", "bullet"]
    store.delete_report_block(nb)
    assert len(store.list_report_blocks(rid)) == 3

    store.set_report_title(rid, "Q2 Final")
    assert store.get_report(rid)["title"] == "Q2 Final"
    store.delete_report(rid)
    assert store.get_report(rid) is None
    assert store.list_report_blocks(rid) == []


def test_chat_sessions(store):
    sid = store.create_chat_session("admin@example.com", title="Status")
    store.add_chat_message(sid, "user", "How is the programme?")
    store.add_chat_message(sid, "assistant", "On track.")
    assert [m["role"] for m in store.get_chat_messages(sid)] == ["user", "assistant"]
    assert store.list_chat_sessions("admin@example.com")[0]["title"] == "Status"
