"""FastPPM — conversational-first transformation PM tool (3-pane FastHTML app).

Left: nav + initiative tree. Centre: the chat analyst (home) or content pages.
Right: copilot rail. Document ingestion is the flagship: upload → extract →
review → merge into the master repository.

Run:  python -m uvicorn web.app:app --host 0.0.0.0 --port 5012
"""

from __future__ import annotations

import os
from pathlib import Path

import bcrypt
from fasthtml.common import *
from starlette.responses import StreamingResponse

import ppmstore as store
from web.ui import (CSS, MARKED, FAVICON, PLOTLY, VH_STREAM_JS, COPILOT_JS, Page,
                    left_pane, SUGGESTIONS, BRAND, money, pct)
from web import dashboard, initiatives, gantt, documents, prompts, help as helppages
from web import account_auth, auth, exports, reports as reportsui
from web.landing import landing_page
from reports import generate as repgen, export as repexport
from agents import orchestrator
from ingest import extract as ex
from ingest import service
from ingest.normalize import DEFAULT_EXTRACTION_PROMPT, PROMPT_KEY

store.init_db()
# Register the editable extraction system prompt (idempotent) so the Prompt
# Manager is populated and the extractor reads the active version at run time.
store.ensure_prompt(PROMPT_KEY, "Document extraction",
                    "System prompt guiding what the LLM extracts from uploaded "
                    "documents into canonical milestones, risks and value drivers.",
                    DEFAULT_EXTRACTION_PROMPT)
# One-time migration: any earlier extraction prompt that embedded the JSON schema
# → the plain-English guidance default (the schema now lives in code, not the UI).
# Idempotent — only fires while the active version still contains the schema.
_active = store.get_active_prompt_content(PROMPT_KEY)
if _active and '"value_drivers"' in _active:
    store.add_prompt_version(PROMPT_KEY, DEFAULT_EXTRACTION_PROMPT,
                             notes="Simplified to plain-English guidance (schema moved to code)",
                             created_by="system")
LOGIN_REQUIRED = os.environ.get("FASTPPM_PUBLIC", "0") != "1"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def current_user(sess):
    return sess.get("uid") if sess else None


def user_email(sess):
    return sess.get("email", "") if sess else ""


def require(sess):
    if LOGIN_REQUIRED and not current_user(sess):
        return RedirectResponse("/login", status_code=303)
    return None


app, rt = fast_app(hdrs=(FAVICON, MARKED), secret_key=os.environ.get("APP_SECRET", "fastppm-2026"),
                   pico=False)


def establish_local_account(sess, account):
    user = store.get_user_by_email(account["email"])
    sess["uid"] = user["id"] if user else f"local:{account['email']}"
    sess["email"] = account["email"]
    sess["role"] = (user.get("role") if user else None) or "pmo"


account_auth.register_fasthtml_routes(
    rt, app_name="FastPPM", success_path="/", on_login=establish_local_account
)


@rt("/health")
def health():
    return JSONResponse({"status": "ok"})


# ── Auth ────────────────────────────────────────────────────────────────────

@rt("/login", methods=["GET"])
def login_form(sess, error: str = ""):
    google = ""
    if auth.enabled():
        google = Div(
            A(Img(src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg",
                  style="width:18px;height:18px;vertical-align:middle;margin-right:8px"),
              "Continue with Google", href="/auth/google", cls="btn ghost",
              style="width:100%;text-align:center;display:block"),
            Div("or", style="text-align:center;color:#9a93a6;font-size:12px;margin:14px 0"))
    return Title(f"Sign in · {BRAND}"), CSS, Form(
        H2(BRAND), P("Value Creation Plan · Transformation Office",
                     style="color:#7a7a85;margin-top:-6px"),
        (P(error, style="color:#c0392b") if error else ""),
        google,
        Input(name="email", placeholder="Email", type="email"),
        Input(name="password", placeholder="Password", type="password"),
        Button("Sign in", cls="btn", style="width:100%"),
        method="post", action="/login", cls="form")


@rt("/login", methods=["POST"])
def login_submit(sess, email: str = "", password: str = ""):
    user = store.get_user_by_email(email)
    if user and user.get("password_hash") and bcrypt.checkpw(
            password.encode(), user["password_hash"].encode()):
        sess["uid"] = user["id"]
        sess["email"] = user.get("email") or email
        sess["role"] = user.get("role") or "pmo"
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/login?error=Invalid+credentials", status_code=303)


@rt("/logout")
def logout(sess):
    sess.clear()
    return RedirectResponse("/login", status_code=303)


@rt("/auth/google")
def auth_google(sess, request):
    if not auth.enabled():
        return RedirectResponse("/login?error=Google+sign-in+not+configured", status_code=303)
    state = auth.new_state()
    sess["oauth_state"] = state
    return RedirectResponse(auth.authorize_url(request, state), status_code=303)


@rt("/auth/callback")
def auth_callback(sess, request, code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return RedirectResponse("/login?error=Google+sign-in+cancelled", status_code=303)
    if not state or state != sess.get("oauth_state"):
        return RedirectResponse("/login?error=Invalid+sign-in+state", status_code=303)
    sess.pop("oauth_state", None)
    info = auth.exchange_code(request, code)
    if not info:
        return RedirectResponse("/login?error=Google+sign-in+failed", status_code=303)
    if not auth.is_allowed(info["email"]):
        return RedirectResponse("/login?error=This+Google+account+is+not+authorised",
                                status_code=303)
    account_auth.accounts.link_google(info["email"], info["name"])
    # Reuse a local user row if one exists (keeps its role), else log in as the
    # Google identity with a default PMO role.
    user = store.get_user_by_email(info["email"])
    sess["uid"] = user["id"] if user else f"google:{info['email']}"
    sess["email"] = info["email"]
    sess["role"] = (user.get("role") if user else None) or "pmo"
    return RedirectResponse("/", status_code=303)


# ── Chat home ───────────────────────────────────────────────────────────────

# The home centre reuses the shared chat engine (ui.VH_STREAM_JS): the unified
# SSE streamer + the generative-analytics table/chart renderer.
CHAT_JS = Script("""
function suggest(t){document.getElementById('inp').value=t;sendMessage();}
function sendMessage(e){if(e)e.preventDefault();vhStream('msgs','inp');return false;}
""")


def _home_center(sess, sid=0):
    msgs = store.get_chat_messages(sid) if sid else []
    bubbles = [Div(NotStr(m["content"]), cls=f"bubble {m['role']}") for m in msgs]
    if not bubbles:
        bubbles = [Div(f"I'm {BRAND} — your transformation programme analyst. Ask me about "
                       "status, value, risks or any initiative, or tell me to update one "
                       "(e.g. “mark Design / baseline as 80% complete”).", cls="bubble assistant")]
    cards = [Div(s, cls="scard", onclick="suggest(this.textContent)") for s in SUGGESTIONS]
    return Div(
        Div(f"Ask {BRAND}", cls="chead"),
        Div(*bubbles, id="msgs", cls="msgs"),
        Div(*cards, cls="cards"),
        Form(Textarea(placeholder="Ask about the programme, or give an update…", id="inp",
                      onkeydown="if(event.key==='Enter'&&!event.shiftKey){return sendMessage(event);}"),
             Button("Ask", type="submit"),
             onsubmit="return sendMessage(event)", cls="composer"),
        cls="pane center")


def _home_right():
    s = store.portfolio_summary()
    items = [("Initiatives", str(s["total_initiatives"])),
             ("On track", pct(s["on_track_pct"])),
             ("Avg progress", pct(s["avg_progress"])),
             ("Value realised", money(s["value_realized"])),
             ("Realisation", pct(s["realization_pct"])),
             ("Open risks", str(s["open_risks"])),
             ("Documents", f"{s['documents_merged']}/{s['documents_total']}")]
    rows = [Div(Span(k, style="color:#7a7a85"), Span(v, style="font-weight:600;float:right"),
                style="padding:8px 0;border-bottom:1px solid var(--line);font-size:13.5px")
            for k, v in items]
    return Div(Div("Programme snapshot", cls="rhead"),
               Div(*rows, A("Open dashboard →", href="/dashboard",
                            style="display:block;margin-top:12px;font-weight:600"),
                   cls="rbody"), cls="pane right")


@rt("/")
def home(sess, sid: int = 0):
    if LOGIN_REQUIRED and not current_user(sess):
        return landing_page()
    if (r := require(sess)):
        return r
    return (Title(BRAND), CSS,
            Div(left_pane(sess), _home_center(sess, sid), _home_right(), cls="app"),
            MARKED, PLOTLY, VH_STREAM_JS, CHAT_JS)


@rt("/chat", methods=["POST"])
async def chat(sess, msg: str = "", sid: int = 0):
    if LOGIN_REQUIRED and not current_user(sess):
        return JSONResponse({"error": "auth"}, status_code=401)
    email = user_email(sess)
    if not sid:
        sid = store.create_chat_session(email, title=msg[:48])
    store.add_chat_message(sid, "user", msg)

    async def stream():
        import json as _j
        yield orchestrator.sse.event("session", {"sid": sid})
        acc, datasets = [], []
        async for ev in orchestrator.astream(msg):
            if ev.startswith("event: token"):
                try:
                    acc.append(_j.loads(ev.split("data: ", 1)[1])["text"])
                except Exception:
                    pass
            elif ev.startswith("event: dataset"):
                try:
                    datasets.append(_j.loads(ev.split("data: ", 1)[1]))
                except Exception:
                    pass
            yield ev
        # Persist the answer plus any datasets (as a non-executing JSON block) so
        # reopening the chat re-renders the tables and chart offers (vhHydrate).
        content = "".join(acc) or "(no response)"
        if datasets:
            content += ('\n\n<script type="application/vh-dataset">'
                        + _j.dumps(datasets) + "</script>")
        store.add_chat_message(sid, "assistant", content)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Content pages ───────────────────────────────────────────────────────────

@rt("/dashboard")
def dashboard_page(sess):
    if (r := require(sess)):
        return r
    return Page(sess, *dashboard.dashboard_content(), title=f"Dashboard · {BRAND}",
                active="/dashboard")


@rt("/value")
def value_page(sess):
    if (r := require(sess)):
        return r
    return Page(sess, *dashboard.value_content(), title=f"Value · {BRAND}", active="/value")


@rt("/initiatives")
def initiatives_page(sess, type: str = "", status: str = ""):
    if (r := require(sess)):
        return r
    return Page(sess, *initiatives.registry_content(type, status),
                title=f"Initiatives · {BRAND}", active="/initiatives")


@rt("/initiative/{iid}")
def initiative_page(sess, iid: int):
    if (r := require(sess)):
        return r
    return Page(sess, *initiatives.initiative_content(iid), title=f"Initiative · {BRAND}")


@rt("/gantt")
def gantt_page(sess):
    if (r := require(sess)):
        return r
    return Page(sess, *gantt.gantt_content(), title=f"Gantt · {BRAND}", active="/gantt")


# ── Documents / ingestion ───────────────────────────────────────────────────

@rt("/documents")
def documents_page(sess, flash: str = ""):
    if (r := require(sess)):
        return r
    # Documents tab: centre = ingestion + report builder; right pane = a live
    # document preview (the latest report) instead of the copilot rail.
    center = Div(Div(*documents.documents_content(flash or None),
                     reportsui.builder_panel(), cls="wrap"), cls="pane center centerdoc")
    reps = store.list_reports(limit=1)
    if reps:
        right = reportsui.preview_pane(reps[0]["id"])
    else:
        right = Div(Div("📄 Document preview", cls="rhead"),
                    Div(P("Generate a report and it previews here.", style="color:#7a7a85"),
                        cls="rbody"), cls="pane right")
    return (Title(f"Documents · {BRAND}"), CSS, reportsui.REPORT_CSS,
            Div(left_pane(sess, "/documents"), center, right, cls="app"), MARKED)


@rt("/reports/template/upload", methods=["POST"])
async def report_template_upload(sess, request):
    if (r := require(sess)):
        return r
    form = await request.form()
    f = form.get("template")
    from urllib.parse import quote
    if not f or not getattr(f, "filename", None):
        return RedirectResponse("/documents", status_code=303)
    fname = _safe_name(f.filename)
    ext = os.path.splitext(fname)[1].lower()
    data = await f.read()
    path = UPLOAD_DIR / f"tpl_{store.count_initiatives()}_{fname}"
    path.write_bytes(data)
    if ext in (".md", ".txt"):
        outline = data.decode("utf-8", "ignore")[:8000]
    else:
        outline = (ex.extract(str(path)).get("text") or "")[:8000]
    store.add_report_template({"name": fname, "file_type": ex.file_type(fname),
                               "outline": outline, "uploaded_by": user_email(sess)})
    return RedirectResponse(f"/documents?flash={quote('Template uploaded: ' + fname)}",
                            status_code=303)


@rt("/reports/generate", methods=["POST"])
def report_generate(sess, template_id: str = ""):
    if (r := require(sess)):
        return r
    tpl = store.get_report_template(int(template_id)) if template_id else None
    outline = tpl["outline"] if tpl else ""
    title, blocks = repgen.generate_report(outline)
    rid = store.create_report(title, blocks, template_name=(tpl["name"] if tpl else ""),
                              created_by=user_email(sess))
    return RedirectResponse(f"/report/{rid}", status_code=303)


@rt("/report/{rid}")
def report_page(sess, rid: int):
    if (r := require(sess)):
        return r
    if not store.get_report(rid):
        return Page(sess, H1("Report not found"))
    return (Title(f"Report · {BRAND}"), CSS,
            Div(left_pane(sess, "/documents"), reportsui.editor_center(rid),
                reportsui.preview_pane(rid), cls="app"), MARKED)


@rt("/report/{rid}/main")
def report_main(sess, rid: int, editing: int = 0):
    if (r := require(sess)):
        return r
    return reportsui.report_blocks(rid, editing or None)


@rt("/report/{rid}/title", methods=["POST"])
def report_title(sess, rid: int, title: str = ""):
    if (r := require(sess)):
        return r
    if title.strip():
        store.set_report_title(rid, title.strip())
    return Response("")


@rt("/report/{rid}/block/add", methods=["POST"])
def report_block_add(sess, rid: int, after: int = 0, type: str = "paragraph"):
    if (r := require(sess)):
        return r
    bid = store.add_report_block(rid, type=type, content="", after_id=after or None)
    return reportsui.report_blocks(rid, editing=bid), reportsui.preview_oob(rid)


@rt("/report/{rid}/block/{bid}", methods=["POST"])
def report_block_save(sess, rid: int, bid: int, content: str = "", type: str = "paragraph"):
    if (r := require(sess)):
        return r
    store.update_report_block(bid, content, type=type)
    return reportsui.report_blocks(rid), reportsui.preview_oob(rid)


@rt("/report/{rid}/block/{bid}/move", methods=["POST"])
def report_block_move(sess, rid: int, bid: int, dir: int = 1):
    if (r := require(sess)):
        return r
    store.move_report_block(bid, dir)
    return reportsui.report_blocks(rid), reportsui.preview_oob(rid)


@rt("/report/{rid}/block/{bid}/delete", methods=["POST"])
def report_block_delete(sess, rid: int, bid: int):
    if (r := require(sess)):
        return r
    store.delete_report_block(bid)
    return reportsui.report_blocks(rid), reportsui.preview_oob(rid)


@rt("/report/{rid}/export")
def report_export(sess, rid: int, fmt: str = "pdf"):
    if (r := require(sess)):
        return r
    rep = store.get_report(rid)
    if not rep:
        return Response("Not found", status_code=404)
    fmt = fmt if fmt in ("pdf", "docx", "pptx") else "pdf"
    data, media = repexport.export(fmt, rep["title"], store.list_report_blocks(rid))
    out = f"{_slug(rep['title'])}.{fmt}"
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{out}"'})


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "file")
    cleaned = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in base)
    return (cleaned or "file")[:120]


@rt("/documents/upload", methods=["POST"])
async def upload(sess, request):
    if (r := require(sess)):
        return r
    form = await request.form()
    files = form.getlist("files")
    counts = {"docs": 0, "milestones": 0, "risks": 0, "value_drivers": 0, "inconsistencies": 0}
    for f in files:
        fname = getattr(f, "filename", None)
        if not fname:
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ex.SUPPORTED:
            continue
        data = await f.read()
        path = UPLOAD_DIR / f"{store.count_initiatives()}_{_safe_name(fname)}"
        path.write_bytes(data)
        did = store.add_document({
            "file_name": _safe_name(fname), "file_type": ex.file_type(fname),
            "file_path": str(path), "byte_size": len(data),
            "status": "uploaded", "uploaded_by": user_email(sess)})
        extracted = service.process_document(did)
        counts["docs"] += 1
        counts["milestones"] += len(extracted.get("milestones", []))
        counts["risks"] += len(extracted.get("risks", []))
        counts["value_drivers"] += len(extracted.get("value_drivers", []))
        counts["inconsistencies"] += len(extracted.get("inconsistencies", []))
    from urllib.parse import quote
    flash = (f"Processed {counts['docs']} document(s): extracted "
             f"{counts['milestones']} milestones, {counts['risks']} risks, "
             f"{counts['value_drivers']} value drivers"
             + (f", {counts['inconsistencies']} inconsistencies flagged" if counts['inconsistencies'] else "")
             + ". Review each below, then merge.")
    return RedirectResponse(f"/documents?flash={quote(flash)}", status_code=303)


@rt("/document/{did}")
def document_page(sess, did: int):
    if (r := require(sess)):
        return r
    return Page(sess, *documents.review_content(did), title=f"Review · {BRAND}", active="/documents")


_DOC_MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@rt("/document/{did}/file")
def document_file(sess, did: int):
    if (r := require(sess)):
        return r
    d = store.get_document(did)
    if not d or not d.get("file_path"):
        return Response("Not found", status_code=404)
    p = Path(d["file_path"])
    if not p.exists():
        return Response("File not found", status_code=404)
    media = _DOC_MEDIA.get(d.get("file_type"), "application/octet-stream")
    return Response(p.read_bytes(), media_type=media,
                    headers={"Content-Disposition": f'inline; filename="{d["file_name"]}"'})


def _slug(s: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in (s or "x"))[:50]


@rt("/document/{did}/export")
def document_export(sess, did: int, kind: str = "milestones", fmt: str = "csv"):
    if (r := require(sess)):
        return r
    res = exports.document_table(store, did, kind)
    if not res:
        return Response("Not found", status_code=404)
    fname, title, cols, rows = res
    out = f"{_slug(Path(fname).stem)}-{kind}.{'xlsx' if fmt == 'xlsx' else 'csv'}"
    return (exports.xlsx_response(title, cols, rows, out) if fmt == "xlsx"
            else exports.csv_response(cols, rows, out))


@rt("/initiative/{iid}/export")
def initiative_export(sess, iid: int, kind: str = "milestones", fmt: str = "csv"):
    if (r := require(sess)):
        return r
    i = store.get_initiative(iid)
    if not i:
        return Response("Not found", status_code=404)
    title, cols, rows = exports.initiative_table(store, iid, kind)
    out = f"{_slug(i.get('ref') or i['name'])}-{kind}.{'xlsx' if fmt == 'xlsx' else 'csv'}"
    return (exports.xlsx_response(title, cols, rows, out) if fmt == "xlsx"
            else exports.csv_response(cols, rows, out))


@rt("/document/{did}/merge", methods=["POST"])
def merge_document(sess, did: int):
    if (r := require(sess)):
        return r
    res = service.merge_document(did, actor=user_email(sess) or "user")
    if res.get("initiative_id"):
        return RedirectResponse(f"/initiative/{res['initiative_id']}", status_code=303)
    return RedirectResponse("/documents", status_code=303)


# ── Prompt Manager ──────────────────────────────────────────────────────────

@rt("/prompts")
def prompts_page(sess):
    if (r := require(sess)):
        return r
    return Page(sess, *prompts.prompts_content(), title=f"Prompts · {BRAND}", active="/prompts")


@rt("/prompt/{key}")
def prompt_page(sess, key: str, saved: int = 0):
    if (r := require(sess)):
        return r
    return Page(sess, *prompts.prompt_detail_content(key, saved=bool(saved)),
                title=f"Prompt · {BRAND}", active="/prompts")


@rt("/prompt/{key}/version", methods=["POST"])
def prompt_new_version(sess, key: str, content: str = "", notes: str = ""):
    if (r := require(sess)):
        return r
    if content.strip():
        store.add_prompt_version(key, content, notes=notes, created_by=user_email(sess) or "user")
    return RedirectResponse(f"/prompt/{key}?saved=1", status_code=303)


@rt("/prompt/{key}/activate/{vid}", methods=["POST"])
def prompt_activate(sess, key: str, vid: int):
    if (r := require(sess)):
        return r
    store.set_active_prompt_version(key, vid)
    return RedirectResponse(f"/prompt/{key}", status_code=303)


# ── Help ────────────────────────────────────────────────────────────────────

@rt("/help/guide")
def help_guide(sess):
    if (r := require(sess)):
        return r
    return Page(sess, *helppages.user_guide_content(), title=f"User Guide · {BRAND}",
                active="/help/guide")


@rt("/help/architecture")
def help_architecture(sess):
    if (r := require(sess)):
        return r
    return Page(sess, *helppages.architecture_content(),
                title=f"Architecture · {BRAND}", active="/help/architecture")


_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _serve_latest(ext: str, media_type: str):
    """Serve the newest date-stamped user guide of this type (filenames are
    fastppm_user_guide_YYYY-MM-DD.ext, so name-sort = date-sort)."""
    matches = sorted(_DOCS_DIR.glob(f"fastppm_user_guide_*.{ext}"))
    if not matches:
        legacy = _DOCS_DIR / f"fastppm_user_guide.{ext}"
        matches = [legacy] if legacy.exists() else []
    if not matches:
        return None
    p = matches[-1]
    return Response(p.read_bytes(), media_type=media_type,
                    headers={"Content-Disposition": f'inline; filename="{p.name}"'})


@rt("/help/user-guide-pdf")
def user_guide_pdf(sess):
    if (r := require(sess)):
        return r
    return _serve_latest("pdf", "application/pdf") or \
        Page(sess, H1("Not generated"), P("Run python -m scripts.generate_user_guide."))


@rt("/help/user-guide-pptx")
def user_guide_pptx(sess):
    if (r := require(sess)):
        return r
    return _serve_latest(
        "pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation") or \
        Page(sess, H1("Not generated"), P("Run python -m scripts.generate_user_guide."))
