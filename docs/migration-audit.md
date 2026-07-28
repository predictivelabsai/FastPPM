# FastPPM migration audit

Audit date: 2026-07-28

Target: `/home/julian/dev/predictivelabsai/FastPPM`

## Result

All application modules, tests, deployment files, data-model definitions,
sample inputs, report templates, ingestion formats, exports, authentication,
chat/analytics tools, and documentation generators were migrated. Runtime
databases, caches, credentials, and obsolete generated guides were deliberately
excluded and replaced with a freshly seeded `fastppm.db` and freshly generated
FastPPM guides.

Renamed internal surfaces:

- `cxostore.py` → `ppmstore.py`
- legacy database names → `fastppm.db`
- legacy public-mode variable → `FASTPPM_PUBLIC`
- `docs/user_guide.md` → `docs/fastppm_user_guide.md`
- generated guide basename → `fastppm_user_guide_YYYY-MM-DD`

## Functional parity

| Area | Migrated | Verification |
|---|---:|---|
| Canonical storage model and SQLite/Postgres facade | Yes | Storage contract tests |
| Initiative, milestone, dependency, risk, value, document, activity, user, chat and prompt entities | Yes | Seed plus storage tests |
| PDF/XLSX/PPTX/DOCX extraction and normalisation | Yes | Source modules and sample files present |
| Document review/merge workflow | Yes | `/documents` browser and HTTP checks |
| Chat analyst, SSE and deterministic fallback | Yes | Orchestrator/stream tests and `/` browser check |
| Conversational tables and charts | Yes | Analytics/chart tests |
| Dashboard, Gantt, Kanban, dependencies and value pages | Yes | Browser and HTTP checks |
| Initiative registry/detail and CSV/XLSX exports | Yes | Browser detail check and migrated export routes |
| Report builder/editor and PDF/DOCX/PPTX exports | Yes | Migrated modules/templates and Documents UI |
| Prompt Manager and versioning | Yes | Browser check |
| Email/password and optional Google OAuth | Yes | Migrated auth module and environment template |
| Docker/Coolify deployment configuration | Yes | Migrated Dockerfile, Compose and workflow |
| Guide generation and optional Drive upload | Yes | Generated Markdown/HTML/PDF/PPTX bundle |

## Automated verification

- `pytest -q`: **33 passed**
- Fresh seed: **12 initiatives**, **5 AI use cases**, average progress **49%**,
  value realised **£8.0m / £21.7m**, and **4** source documents
- HTTP 200: `/`, `/dashboard`, `/initiatives`, `/gantt`, `/documents`, `/value`,
  `/prompts`, `/help/guide`, `/help/architecture`, `/health`
- Playwright/Chrome checks: Chat, Dashboard, Initiatives, Gantt, Documents,
  Value, Prompt Manager, User Guide and initiative detail
- Case-insensitive legacy-brand scan over text sources and extracted guide
  content: no legacy brand references

## Documentation artifacts

- `docs/media/fastppm-tour.gif`
- `docs/fastppm_user_guide.md`
- `docs/fastppm_user_guide_2026-07-28.pdf`
- `docs/fastppm_user_guide_2026-07-28.pptx`
- `docs/fastppm_user_guide_2026-07-28.html`
- Captures used by the guides: `docs/screenshots/`
