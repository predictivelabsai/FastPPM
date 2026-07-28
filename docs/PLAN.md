# FastPPM — Value Creation Cockpit · Build Plan

A PE-grade **Project Management, Value Creation Monitoring, and KPI/Status
Reporting Cockpit** for a private-equity portfolio company. Built by cloning the
proven architecture, design system, and backend patterns of the sister repo
**`taxhub`** (`dev/FastPPM/taxhub`).

> Source spec: `data/project-management-dashboard.pdf` (the functional outline).
> This plan is the implementation blueprint for **Phase 1**, with later phases
> sketched.

---

## 1. Locked decisions

| Decision | Choice | Notes |
|---|---|---|
| **Storage** | SQLite (local) → Postgres (prod), single relational backend | Port taxhub's `Storage` interface + facade; drop the Neo4j backend. Financial/time-series data is relational, not graph-shaped. |
| **AI copilot** | xAI Grok via OpenAI-compatible LangChain client | Copy taxhub's `rag/llm.py` + agent/SSE pattern verbatim; re-prompt for PE value-creation Q&A. |
| **MVP scope** | Phase 1 — Intake + Project Registry + Executive Cockpit | The spec's own Phase 1; an end-to-end spine that demos value fast. |
| **Seed data** | Synthetic PE demo dataset | `config/seed_portfolio.yaml` → realistic fake portfolio co (~20 projects, KPIs, business cases, levers, RAG). |
| **Web framework** | FastHTML + Plotly (identical to taxhub) | Same 3-pane shell, same `--navy/--accent` design tokens. |
| **Python** | 3.12 | Matches taxhub Dockerfile. |
| **Deploy** | Docker / Coolify, uvicorn, `/health` check | Mirror taxhub; pick a distinct port (proposed **5012**). |

---

## 2. What we clone from taxhub (pattern-for-pattern)

| taxhub pattern | fastppm equivalent |
|---|---|
| `storage/base.py` — abstract `Storage` interface, dicts in/out, ISO-8601 UTC | Same interface shape, PE domain methods |
| `storage/__init__.py` — runtime factory (`DATA_STORAGE`) + singleton | Same, sqlite-only |
| `taxstore.py` — `__getattr__` facade (`import ppmstore as store`) | `ppmstore.py` |
| `storage/sqlite_store.py` — SQLAlchemy core, `lastrowid` ids, `_seed_admin()` bcrypt | Same engine, PE schema |
| `web/app.py` — `fast_app(...)`, decorator routes, 3-pane `Page()` shell, `CSS`/`JS` | Same shell + design tokens, PE pages |
| `web/{coverage,obligations,monitor}.py` — page/logic modules | `web/{cockpit,intake,registry,scoring}.py` |
| bcrypt login + session (`sess["uid"]`, `require()`, `LOGIN_REQUIRED`) | Identical, plus **roles** (sponsor/PMO/lead/finance) |
| Plotly `.to_html(include_plotlyjs="cdn")` charts | Value bridge, bubble chart, heatmaps, scorecards |
| `agents/` (LangGraph react agent) + `agents/sse.py` + `rag/llm.py` | Re-prompted copilot, same SSE streaming |
| config-driven YAML catalogue + `scripts/` loader | `config/seed_portfolio.yaml` + `scripts/seed.py` |
| `tests/test_storage.py` contract test | Same, single backend |
| Dockerfile / docker-compose / `/health` | Same, port 5012 |

---

## 3. Repo layout (target)

```
fastppm/
  storage/
    base.py            # Storage interface (PE domain)
    sqlite_store.py    # SQLite/Postgres backend (SQLAlchemy core)
    __init__.py        # runtime factory + singleton
  ppmstore.py          # facade  → import ppmstore as store
  web/
    app.py             # FastHTML app, routes, 3-pane shell, CSS/JS
    cockpit.py         # executive dashboard + drill-down charts (Plotly)
    intake.py          # intake form + triage/scoring engine
    registry.py        # project registry + portfolio views
    scoring.py         # weighted prioritisation framework
  agents/
    orchestrator.py    # LangGraph react agent ("Ask the cockpit")
    tools.py           # specialist tools (portfolio, value, finance, project)
    sse.py             # SSE event helpers (copied)
  rag/
    llm.py             # Grok client (copied from taxhub)
  config/
    seed_portfolio.yaml  # synthetic demo dataset
    kpis.yaml            # enterprise KPI definitions (leading/lagging)
  scripts/
    seed.py            # load YAML → DB
  tests/
    conftest.py
    test_storage.py    # contract test
  data/                # SQLite db + uploads (volume); spec PDF lives here
  static/
  requirements.txt
  .env.example
  Dockerfile
  docker-compose.yaml
  README.md
```

---

## 4. Data model (Phase 1)

Relational schema, all ids minted via `lastrowid`. Money in integer minor units
or `NUMERIC`; timestamps ISO-8601 UTC.

- **`users`** — id, email, password_hash (bcrypt), name, **role** (`sponsor` |
  `pmo` | `lead` | `finance` | `functional`). Seeded admin.
- **`business_units`** — id, name, strategic_pillar.
- **`value_levers`** — id, key, label (revenue_growth, margin_expansion,
  operational_efficiency, customer_retention, new_product_market). From `kpis.yaml`.
- **`projects`** (central registry) — id, name, description, sponsor,
  business_unit_id, request_type (capex/opex/digital/m&a), stage
  (`new`→`evaluated`→`approved`→`active`→`on_hold`→`rejected`→`complete`),
  primary_lever_id, lead_user_id, timeline_start/end, created_at.
- **`intake_scores`** — project_id, strategic_fit (1-5), urgency, feasibility,
  estimated_impact, weighted_total (computed), scored_by, scored_at.
- **`business_cases`** — project_id, investment_onetime, investment_recurring,
  revenue_uplift, cost_savings, ebitda_impact, payback_months, npv, irr, roi_pct,
  scenario (base/best/worst), baseline_captured_at, approved_by, approved_at.
- **`project_status`** (periodic snapshot) — project_id, period (YYYY-MM),
  rag_schedule/budget/scope/risk (R/A/G), pct_complete, budget_planned,
  budget_actual, narrative, updated_by, updated_at.
- **`milestones`** — project_id, title, due_date, owner, pct_complete, status.
- **`risks`** — project_id, title, probability (1-5), impact (1-5), mitigation,
  owner, status.
- **`kpis`** — id, key, label, type (`leading`|`lagging`), unit, target,
  lever_id. From `kpis.yaml`.
- **`kpi_values`** — kpi_id, project_id (nullable = portfolio-level), period,
  planned, actual, variance (computed).
- **`value_bridge`** — period, component (entry_ebitda, organic, margin, m&a,
  multiple, current), amount — powers the waterfall.
- **`chat_sessions`** / **`chat_messages`** — copilot history (copied shape).

Approval gate: on `business_cases.approved_at`, baseline metrics are frozen and
the project moves `evaluated → approved`; a project id + budget code is minted.

---

## 5. Web layer — pages (Phase 1)

Same 3-pane shell as taxhub: **left nav** (brand, navigate links, recent chats,
project tree) · **center content** · **right copilot/feed**. Reuse the
`--navy:#123B5D / --accent:#00A6A6` FastPPM design tokens.

| Route | Page | Content |
|---|---|---|
| `/login` | Auth | bcrypt login, role from user row |
| `/` | Home / copilot | "Ask the cockpit" chat (SSE), suggestion chips |
| `/cockpit` | **Executive Cockpit** | Portfolio health (RAG counts, on-track %), total invested vs value created, **value bridge waterfall**, top value drivers, portfolio IRR/payback summary |
| `/portfolio` | Portfolio views | **Bubble chart** (investment × ROI × risk), **heatmap** by BU/pillar, capacity snapshot |
| `/registry` | Project registry | Sortable table (status, ROI, %complete, lever), filters |
| `/project/{id}` | Project detail | RAG status, milestones, budget vs actual, risks, business case, KPI contribution |
| `/intake` | Intake portal | Standardised submission form → triage/scoring → Kanban backlog |
| `/intake/board` | Demand pipeline | Kanban (New→Evaluated→Approved→On Hold/Rejected) |
| `/scorecard` | KPI scorecard | Leading vs lagging indicators, plan-vs-actual variance |
| `/health` | Health check | `{"status":"ok"}` |

**Charts (Plotly, `to_html(include_plotlyjs="cdn")`)**: value-bridge waterfall,
portfolio bubble, BU/pillar heatmap, RAG donut, KPI trend lines, variance bars.

**Scoring engine** (`web/scoring.py`): weighted prioritisation —
`40% value/ROI + 30% strategic alignment + 20% risk + 10% resource fit` — mirrors
taxhub's `obligations.py` determine-engine pattern (pure function over rows).

---

## 6. AI copilot — "Ask the cockpit"

Copy taxhub's `rag/llm.py` (Grok, OpenAI-compatible), `agents/sse.py`, and the
`create_react_agent` orchestrator. Re-prompt the system message for PE value
creation; replace specialist tools with:

- `portfolio_agent` — health, RAG rollups, on-track counts, top drivers.
- `value_agent` — value-bridge attribution, realized vs projected benefits.
- `finance_agent` — ROI/NPV/IRR/payback, budget variance, plan vs actual.
- `project_agent` — status, milestones, risks for a named project.

Degrades gracefully when `XAI_API_KEY` is unset (direct query fallback, like
taxhub). SSE streaming + the existing JS handler reused unchanged.

---

## 7. Seed data

`config/seed_portfolio.yaml` → one synthetic portfolio company ("Project
Atlas"), ~20 projects spanning all five value levers and four request types, each
with intake scores, a business case (base/best/worst), 6–12 months of status
snapshots, milestones, risks, and KPI actuals; plus a populated value bridge from
entry to current EBITDA. `config/kpis.yaml` defines the top ~10 enterprise KPIs
(leading: adoption, velocity, pipeline; lagging: EBITDA, margin, NPS, cash
conversion). `scripts/seed.py` loads both into the DB (idempotent upserts).

---

## 8. Phase 1 build order (milestones)

1. **Scaffold** — `requirements.txt`, `.env.example`, `Dockerfile`,
   `docker-compose.yaml` (port 5012), `.gitignore` already present.
2. **Storage** — `storage/base.py` (PE interface), `sqlite_store.py`,
   `__init__.py` factory, `ppmstore.py` facade, `_seed_admin()`.
3. **Tests** — `tests/test_storage.py` contract test (single backend) green.
4. **Seed** — `config/{seed_portfolio,kpis}.yaml` + `scripts/seed.py`; DB populated.
5. **Web shell** — `web/app.py`: `fast_app`, CSS/JS tokens, 3-pane `Page()`,
   login/session/roles, left nav, `/health`.
6. **Registry + project detail** — table, filters, `/project/{id}`.
7. **Cockpit** — `web/cockpit.py`: value bridge, RAG health, drivers, IRR summary.
8. **Portfolio views** — bubble chart + heatmap.
9. **Intake + scoring** — form, `web/scoring.py`, Kanban board, approval gate.
10. **Scorecard** — leading/lagging KPI views + variance.
11. **Copilot** — `rag/llm.py`, `agents/*`, "Ask the cockpit" wired to SSE.
12. **README + docs** — usage, env, deploy; commit.

---

## 9. Later phases (sketch)

- **Phase 2** — ROI modeling deep-dive (sensitivity, scenarios), full status
  tracking (change requests, weekly update reminders/alerts), document repository.
- **Phase 3** — Product roadmapping (Now/Next/Later, Gantt, dependencies),
  advanced analytics, automated Sponsor Pack PDF/deck export, Slack/email
  alerting, ERP/CRM/Jira integration points, resource & capacity management.

---

## 10. Open items / assumptions

- **Single portfolio company** in Phase 1 (multi-company/multi-fund deferred).
- **Roles** enforced at route level (read-only for sponsor/board; CRUD for PMO).
- **Sponsor Pack export** (PDF/deck) deferred to Phase 3.
- **Port 5012** assumed to avoid clashing with taxhub's 5011 — confirm.
