"""Storage interface for FastPPM — Transformation Office / Value Creation Plan.

FastPPM is the single source of truth for one PE portfolio company's
transformation initiatives and internal AI use cases. Messy documents (PDF, XLSX,
PPTX, DOCX) are ingested, normalised to a canonical schema, reviewed, and merged
into a unified repository that powers Gantt, value tracking, dashboards and a
chat-first analytics layer.

Persistence is pluggable behind one backend-neutral interface, selected at
runtime by ``DATA_STORAGE`` (Phase 1: ``sqlite``, also Postgres via ``DB_URL``).
No caller touches a database directly. Return shapes are plain ``dict`` /
``list[dict]``; timestamps are ISO-8601 UTC strings.

Canonical model:

    initiative ─┬─ milestone*   (planned/actual/baseline dates, dependencies[])
                ├─ risk*        (probability × impact)
                ├─ value_entry* (periodic planned vs realised value)
                └─ document*    (ingested source, linked on merge)
    document   →  structured_json (extracted candidate entities, pre-merge)
    activity_log (audit trail: every merge / status change / NL update)
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone


def utcnow() -> str:
    """ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage(abc.ABC):
    """Backend-neutral persistence + read API for FastPPM."""

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @abc.abstractmethod
    def init_db(self) -> None:
        """Create schema/indexes and seed the admin user. Idempotent."""

    # ── Initiatives (transformation programs / workstreams / AI use cases) ──

    @abc.abstractmethod
    def upsert_initiative(self, ini: dict) -> int:
        """Insert/update an initiative by natural key ``ref`` (falls back to name).
        Fields: ref, name, description, type (program|workstream|ai_use_case|
        value_initiative), workstream, owner, status, rag, progress,
        start_date, end_date, baseline_start, baseline_end, value_target,
        value_realized, value_category, parent_ref, source_document_id.
        ``parent_ref`` is resolved to parent_id. Returns the initiative id."""

    @abc.abstractmethod
    def get_initiative(self, initiative_id: int) -> dict | None:
        ...

    @abc.abstractmethod
    def get_initiative_by_ref(self, ref: str) -> dict | None:
        ...

    @abc.abstractmethod
    def list_initiatives(self, type: str | None = None, status: str | None = None,
                         workstream: str | None = None, parent_id: int | None = None,
                         limit: int = 1000) -> list[dict]:
        """Initiatives with milestone counts joined, ordered by name."""

    @abc.abstractmethod
    def set_initiative_fields(self, initiative_id: int, fields: dict) -> None:
        """Patch arbitrary scalar fields (status, rag, progress, dates, value)."""

    @abc.abstractmethod
    def count_initiatives(self) -> int:
        ...

    # ── Milestones (with dependencies) ──────────────────────────────────────

    @abc.abstractmethod
    def upsert_milestone(self, m: dict) -> int:
        """Insert/update by (initiative_id, title). Fields: initiative_id, title,
        planned_date, actual_date, baseline_date, progress, status, owner,
        dependencies (list of milestone ids). Returns id."""

    @abc.abstractmethod
    def get_milestone(self, milestone_id: int) -> dict | None:
        ...

    @abc.abstractmethod
    def list_milestones(self, initiative_id: int | None = None) -> list[dict]:
        """Milestones (optionally for one initiative), enriched with the
        initiative name, ordered by planned_date."""

    @abc.abstractmethod
    def set_milestone_fields(self, milestone_id: int, fields: dict) -> None:
        ...

    # ── Risks ───────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def upsert_risk(self, r: dict) -> int:
        """Insert/update by (initiative_id, description). Fields: initiative_id,
        description, probability (1-5), impact (1-5), status, mitigation, owner.
        Returns id."""

    @abc.abstractmethod
    def list_risks(self, initiative_id: int | None = None) -> list[dict]:
        """Risks (optionally for one initiative), enriched with initiative name,
        ordered by probability×impact desc."""

    # ── Value tracking (periodic planned vs realised) ───────────────────────

    @abc.abstractmethod
    def add_value_entry(self, v: dict) -> int:
        """Insert/update by (initiative_id, period, category). Fields:
        initiative_id (nullable = programme-level), period, category
        (ebitda|cost_savings|revenue|synergy|other), planned, realized.
        Returns id."""

    @abc.abstractmethod
    def list_value_entries(self, initiative_id: int | None = None,
                           category: str | None = None) -> list[dict]:
        """Value entries (optionally filtered), ordered by period."""

    @abc.abstractmethod
    def value_summary(self) -> dict:
        """Programme value rollup: target, realized, by category, by period."""

    # ── Documents (ingestion) ───────────────────────────────────────────────

    @abc.abstractmethod
    def add_document(self, doc: dict) -> int:
        """Register an uploaded document. Fields: file_name, file_type, file_path,
        byte_size, status ('uploaded'), uploaded_by. Returns id."""

    @abc.abstractmethod
    def update_document(self, document_id: int, fields: dict) -> None:
        """Patch document fields: status, raw_text, structured_json (dumped),
        summary, n_initiatives, n_milestones, n_risks, n_value_drivers,
        n_inconsistencies, error."""

    @abc.abstractmethod
    def get_document(self, document_id: int) -> dict | None:
        """One document; structured_json is returned parsed into a dict/list."""

    @abc.abstractmethod
    def list_documents(self, status: str | None = None) -> list[dict]:
        """Documents newest-first (without raw_text/structured_json blobs)."""

    @abc.abstractmethod
    def search_documents(self, query: str, limit: int = 8) -> list[dict]:
        """Full-text-ish search over merged documents' raw_text for chat RAG.
        Returns {id, file_name, snippet, score}."""

    # ── Activity log (audit trail) ──────────────────────────────────────────

    @abc.abstractmethod
    def log_activity(self, entry: dict) -> int:
        """Append an audit entry. Fields: entity_type, entity_id, action, detail,
        actor. Returns id."""

    @abc.abstractmethod
    def list_activity(self, entity_type: str | None = None,
                      entity_id: int | None = None, limit: int = 50) -> list[dict]:
        """Audit entries newest-first, optionally scoped to one entity."""

    # ── Dashboard rollup ────────────────────────────────────────────────────

    @abc.abstractmethod
    def portfolio_summary(self) -> dict:
        """Programme health headline: initiative counts by status/type, RAG
        counts, on_track_pct, avg_progress, on_time_pct, value_target,
        value_realized, realization_pct, open_risks, document counts."""

    # ── Prompt manager (versioned system prompts) ──────────────────────────
    # A named prompt (e.g. 'extraction') has an append-only version history; one
    # version is active. The document extractor reads the active 'extraction'
    # prompt at run time, so it can be tuned in-app without a code change.

    @abc.abstractmethod
    def ensure_prompt(self, key: str, name: str, description: str,
                      default_content: str) -> int:
        """Create the prompt (and version 1 = ``default_content``, active) if it
        does not exist. Idempotent — never overwrites existing versions. Returns id."""

    @abc.abstractmethod
    def list_prompts(self) -> list[dict]:
        """All prompts with active version + version count."""

    @abc.abstractmethod
    def get_prompt(self, key: str) -> dict | None:
        """One prompt incl. ``active_version`` and ``active_content``."""

    @abc.abstractmethod
    def get_active_prompt_content(self, key: str) -> str | None:
        """The content of the active version (or None if the prompt is unknown)."""

    @abc.abstractmethod
    def list_prompt_versions(self, key: str) -> list[dict]:
        """Versions newest-first: ``{id, version, content, notes, created_by,
        created_at, is_active}``."""

    @abc.abstractmethod
    def add_prompt_version(self, key: str, content: str, notes: str = "",
                           created_by: str = "") -> dict:
        """Append a new version (version = max+1) and make it active.
        Returns ``{id, version}``."""

    @abc.abstractmethod
    def set_active_prompt_version(self, key: str, version_id: int) -> None:
        """Activate an existing version of the prompt."""

    # ── Reports (template → AI-assembled, block-edited, exportable) ─────────
    # A report is an ordered list of blocks (heading/paragraph/bullet/divider),
    # each holding HTML (WYSIWYG). report_templates hold the uploaded skeleton
    # outline the AI follows when generating.

    @abc.abstractmethod
    def add_report_template(self, tpl: dict) -> int:
        """Store an uploaded report template. Fields: name, file_type, outline
        (text), uploaded_by. Returns id."""

    @abc.abstractmethod
    def list_report_templates(self) -> list[dict]:
        ...

    @abc.abstractmethod
    def get_report_template(self, template_id: int) -> dict | None:
        ...

    @abc.abstractmethod
    def create_report(self, title: str, blocks: list[dict],
                      template_name: str = "", created_by: str = "") -> int:
        """Create a report with its ordered blocks (each {type, content}).
        Returns the report id."""

    @abc.abstractmethod
    def get_report(self, report_id: int) -> dict | None:
        ...

    @abc.abstractmethod
    def list_reports(self, limit: int = 100) -> list[dict]:
        """Reports newest-first with a block count."""

    @abc.abstractmethod
    def set_report_title(self, report_id: int, title: str) -> None:
        ...

    @abc.abstractmethod
    def delete_report(self, report_id: int) -> None:
        ...

    @abc.abstractmethod
    def list_report_blocks(self, report_id: int) -> list[dict]:
        """Blocks for a report in order: ``{id, position, type, content}``."""

    @abc.abstractmethod
    def get_report_block(self, block_id: int) -> dict | None:
        ...

    @abc.abstractmethod
    def add_report_block(self, report_id: int, type: str = "paragraph",
                         content: str = "", after_id: int | None = None) -> int:
        """Insert a block (after ``after_id`` or at the end). Returns id."""

    @abc.abstractmethod
    def update_report_block(self, block_id: int, content: str,
                            type: str | None = None) -> None:
        ...

    @abc.abstractmethod
    def move_report_block(self, block_id: int, direction: int) -> None:
        """Swap a block with its neighbour (direction -1 up / +1 down)."""

    @abc.abstractmethod
    def delete_report_block(self, block_id: int) -> None:
        ...

    # ── Users / auth ────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_user_by_email(self, email: str) -> dict | None:
        """Return ``{id, email, password_hash, name, role}`` or None."""

    # ── Chat history (copilot sessions) ────────────────────────────────────

    @abc.abstractmethod
    def create_chat_session(self, user_email: str, title: str = "") -> int:
        ...

    @abc.abstractmethod
    def add_chat_message(self, session_id: int, role: str, content: str) -> None:
        ...

    @abc.abstractmethod
    def list_chat_sessions(self, user_email: str, limit: int = 30) -> list[dict]:
        ...

    @abc.abstractmethod
    def get_chat_messages(self, session_id: int) -> list[dict]:
        ...
