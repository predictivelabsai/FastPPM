# FastPPM — Technical Architecture

FastPPM is a conversational-first project-management and use-case-tracking tool
for a single PE portfolio company's **Transformation Office**. It ingests messy,
siloed documents (PDF / XLSX / PPTX / DOCX), normalises them to a canonical
schema, and delivers a unified master repository with a Gantt, value tracking,
dashboards and a chat-first analyst.

It shares its architecture with the sister app **TaxHub**: a FastHTML 3-pane UI,
a pluggable storage facade, xAI Grok via LangChain, and Plotly dashboards.

---

## 1. Layers

```
┌──────────────────────────────────────────────────────────────┐
│  web/ (FastHTML)   3-pane shell · chat · dashboard · gantt ·  │
│                    initiatives · documents · value · help     │
├──────────────────────────────────────────────────────────────┤
│  agents/ (LangGraph)        ingest/ (extraction + normalise)  │
│  chat analyst + tools       PDF/XLSX/PPTX/DOCX → canonical     │
├──────────────────────────────────────────────────────────────┤
│  ppmstore  (facade)   →   storage/  (Storage interface)       │
│                            └─ SQLite / Postgres backend       │
└──────────────────────────────────────────────────────────────┘
```

Every caller goes through the `Storage` interface (`ppmstore`), selected at
runtime by `DATA_STORAGE`. No code touches a database directly, so the backend is
swappable (Phase 1 ships SQLite, also Postgres via `DB_URL`).

| Module | Responsibility |
|---|---|
| `storage/base.py` | Backend-neutral `Storage` interface (dicts in/out, ISO-8601 UTC) |
| `storage/sqlite_store.py` | SQLite / Postgres backend (SQLAlchemy core) |
| `ppmstore.py` | Facade — `import ppmstore as store` forwards to the active backend |
| `ingest/extract.py` | Per-format text + table extraction |
| `ingest/normalize.py` | Extracted content → canonical candidate entities (Grok, via the managed prompt) |
| `ingest/service.py` | `process_document()` + `merge_document()` orchestration |
| `agents/orchestrator.py` | LangGraph ReAct chat analyst (+ SSE streaming) |
| `agents/tools.py` | Specialist tools: programme / initiative / risk / value / document / update |
| `rag/llm.py` | Grok client (xAI, OpenAI-compatible) |
| `web/app.py` | FastHTML app, routes, auth, upload/merge handlers |
| `web/ui.py` | Design system + 3-pane shell |
| `web/{dashboard,initiatives,gantt,documents,help}.py` | Page modules |
| `web/reports.py` + `reports/{generate,export}.py` | Report builder: AI-assembled blocks, WYSIWYG (Trix) editor, export to PDF/DOCX/PPTX |
| `web/exports.py` | CSV / XLSX export of extracted + canonical tables |

---

## 2. Web routes (`web/app.py`, port 5012)

| Route | Purpose |
|---|---|
| `/` | Chat analyst (home) — SSE streaming |
| `/dashboard` | Programme health, value waterfall, RAG, recent activity |
| `/value` | Value realised vs target, by category & period |
| `/initiatives` · `/initiative/{id}` | Registry + detail (milestones, risks, value, audit) |
| `/gantt` | Master Gantt (baseline vs actual) + Kanban + dependencies |
| `/documents` · `/document/{id}` | Ingestion: upload, review extracted entities, merge |
| `/report/{id}` + `/reports/generate` | Report builder: AI-assembled, WYSIWYG block editor, export (pdf/docx/pptx) |
| `/help/guide` · `/help/architecture` | User guide + this document |
| `/login` · `/auth/google` · `/auth/callback` · `/logout` | Auth |
| `/health` | Health check (`{"status":"ok"}`) |

---

## 3. Canonical data model

```
initiative ─┬─ milestone*    (planned / actual / baseline dates, dependencies[])
            ├─ risk*         (probability × impact, mitigation)
            ├─ value_entry*  (periodic planned vs realised, by category)
            └─ document*     (the ingested source, linked on merge)
document   →  structured_json   (extracted candidate entities, pre-merge)
activity_log (audit trail: every merge / status change / NL update)
```

- **`initiatives`** — the unified registry: a top-level `program` (Value Creation
  Plan) with child `workstream` / `ai_use_case` / `value_initiative` rows. Fields:
  ref, name, type, workstream, owner, status, rag, progress, start/end +
  baseline dates, value_target, value_realized, value_category, parent_id,
  source_document_id.
- **`milestones`** — title, planned/actual/baseline dates, progress, status,
  owner, `dependencies` (JSON list of milestone ids) → drives the Gantt + the
  dependency graph.
- **`risks`** — description, probability (1-5), impact (1-5), mitigation, status.
- **`value_entries`** — periodic planned vs realised value by category
  (ebitda / cost_savings / revenue / synergy).
- **`documents`** — ingestion lifecycle (`uploaded → parsing → extracted →
  merged`), raw_text, `structured_json` (the reviewable candidate entities),
  and extracted counts.
- **`activity_log`** — the audit trail surfaced on each initiative.

The `program` node is an umbrella; value/progress rollups sum its children only,
so it is never double-counted.

---

## 4. Document ingestion (the flagship)

```
upload ─▶ extract ─▶ normalize ─▶ review ─▶ merge
 file      text +     canonical    human    write to
 (4 fmt)   tables     candidates   check    initiatives/…
```

1. **Extract** (`ingest/extract.py`) — dispatch on extension:
   `pdfplumber` (PDF), `openpyxl` (XLSX), `python-pptx` (PPTX), `python-docx`
   (DOCX) → `{text, tables}`. Defensive: a malformed file yields whatever could
   be read, never an exception that aborts a bulk upload.
2. **Normalize** (`ingest/normalize.py`) — **LLM-only**: Grok maps varying column
   names / date formats / structures to canonical candidate entities (initiative,
   milestones, risks, value drivers) and flags **inconsistencies** (e.g. 100% but
   not complete, late delivery, missing owner, duplicate). The system instruction
   is the **active version of the `extraction` prompt** from the Prompt Manager
   (`storage` `prompts` + `prompt_versions`), edited in-app via a WYSIWYG editor,
   so extraction can be tuned without a code change. No regex/heuristics.
3. **Review** (`/document/{id}`) — the "extracted N milestones · M risks · K
   inconsistencies" screen with every candidate entity.
4. **Merge** (`ingest/service.merge_document`) — write the candidates to the
   canonical tables as an initiative (creating or matching by name), link the
   source document, roll up progress/value, and append an audit entry.

---

## 5. AI — the chat analyst

`agents/orchestrator.py` builds a LangGraph **ReAct agent** (`create_react_agent`)
over Grok and streams the answer as Server-Sent Events. It routes to specialist
`@tool`s in `agents/tools.py`:

| Tool | Answers |
|---|---|
| `programme_status` | Overall health, RAG, value realised vs target |
| `initiative_agent` | A named initiative, or all in a red/amber/green status |
| `risk_agent` | Top risks by probability × impact |
| `value_agent` | Value realised vs target, by category, top contributors |
| `document_agent` | Search the ingested source documents |
| `update_agent` | Natural-language status updates (writes + audit log) |

**Natural-language updates** — "mark Design / baseline as 80% complete", "set ERP
modernisation to at risk" — are matched to the right milestone/initiative and
applied, with an `activity_log` entry. Progress/completion targets a milestone;
workflow status (at risk / delayed / on track) targets an initiative.

**Key required** — with no `XAI_API_KEY` the chat analyst returns a deterministic
programme summary and document extraction is unavailable; both need the key. The
extraction prompt is managed in the Prompt Manager (WYSIWYG, versioned).

---

## 6. Environment variables

```
DATA_STORAGE=sqlite                 # 'sqlite' (also Postgres via DB_URL)
DB_URL=sqlite:///fastppm.db
UPLOAD_DIR=data/uploads             # uploaded documents (on the persistent volume)
XAI_API_KEY=                        # xAI Grok; REQUIRED for extraction + full chat
XAI_BASE_URL=https://api.x.ai/v1
GROK_MODEL=grok-4-1-fast-reasoning
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=…                    # authoritative — reset on each init/redeploy
APP_SECRET=…
FASTPPM_PUBLIC=0                     # 1 disables the login gate (public demo)
GOOGLE_CLIENT_ID= / GOOGLE_CLIENT_SECRET= / GOOGLE_REDIRECT_URI=   # OAuth (optional)
GOOGLE_ALLOWED_DOMAINS= / GOOGLE_ALLOWED_EMAILS=                   # sign-in allowlist
```

---

## 7. Auth

- **Email / password** — bcrypt against the `users` table; the admin row is
  seeded from `ADMIN_EMAIL` / `ADMIN_PASSWORD` (authoritative — reset on every
  init, so rotating is an env change + redeploy).
- **Google OAuth** (`web/auth.py`) — "Continue with Google" using the GCP OAuth
  code flow (httpx, no extra library). Access is allowlisted by domain + explicit
  email. Reuses the shared GCP OAuth client.
- **Roles** — transformation_lead / executive (read + approvals), pmo (full
  CRUD), functional_owner (status updates); seeded admin has `admin`.

---

## 8. Deployment

Docker / **Coolify**, port **5012**, persistent volume at `/app/data` (SQLite db
+ uploaded documents). Deployed at **fastppm.predictivelabs.ai**.

- **Build** — `Dockerfile` (python:3.12-slim) → `uvicorn web.app:app`.
- **CI/CD** — push to `main` → GitHub Action → Coolify deploy webhook (and the
  Coolify GitHub App also auto-deploys). The **post-deploy command**
  `python -m scripts.seed` re-seeds the demo programme + sample documents
  (idempotent + deterministic via `zlib.crc32` seeding).
- **Storage in prod** — SQLite on the volume; set
  `DB_URL=postgresql+psycopg2://…` for Postgres, no code change.

```bash
docker compose up -d web          # serve
python -m scripts.seed            # load demo programme + sample docs
```

---

## 9. Testing

`tests/test_storage.py` is the storage contract test — one suite asserting the
behaviour the app and ingestion engine rely on: initiative rollups, milestones +
dependencies, risks, value tracking, the document lifecycle, the activity log and
the programme summary. Run `pytest -q`.

---

## 10. Roadmap

- **PPTX / PDF export** of the executive value-creation deck and sponsor pack.
- **Editable Gantt** — drag-to-reschedule (currently read-only Plotly).
- **Embeddings / vector RAG** over the document corpus (currently full-text).
- **Scenario modelling** — "what if Project X slips 2 months?".
- **Integrations** — Outlook/Teams, ERP financial actuals, Jira/Asana import.
- **Multi-company portfolio** — roll several portfolio companies into one view.
