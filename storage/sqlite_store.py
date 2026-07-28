"""SQLite (SQLAlchemy) storage backend for FastPPM.

Zero-infra relational backend: local dev and the first production deploy need no
external service. Point ``DB_URL`` at Postgres when volume demands it. List-valued
fields (milestone dependencies) and the documents' extracted entities are stored
as JSON text and returned parsed.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text

from .base import Storage, utcnow


class SqliteStore(Storage):
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or os.environ.get("DB_URL", "sqlite:///fastppm.db")
        connect_args = {"check_same_thread": False} if self.db_url.startswith("sqlite") else {}
        self.engine = create_engine(self.db_url, future=True, connect_args=connect_args)

    @contextmanager
    def conn(self):
        with self.engine.begin() as c:
            if self.db_url.startswith("sqlite"):
                c.execute(text("PRAGMA foreign_keys=ON"))
                c.execute(text("PRAGMA journal_mode=WAL"))
            yield c

    # ── Schema ─────────────────────────────────────────────────────────────

    DDL = [
        """CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            name          TEXT,
            role          TEXT DEFAULT 'pmo',
            created_at    TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS initiatives (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            ref                TEXT UNIQUE,
            name               TEXT NOT NULL,
            description        TEXT,
            type               TEXT DEFAULT 'workstream',
            workstream         TEXT,
            owner              TEXT,
            status             TEXT DEFAULT 'not_started',
            rag                TEXT,
            progress           REAL DEFAULT 0,
            start_date         TEXT,
            end_date           TEXT,
            baseline_start     TEXT,
            baseline_end       TEXT,
            value_target       REAL DEFAULT 0,
            value_realized     REAL DEFAULT 0,
            value_category     TEXT,
            parent_id          INTEGER REFERENCES initiatives(id),
            source_document_id INTEGER REFERENCES documents(id),
            created_at         TEXT,
            updated_at         TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS milestones (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            initiative_id INTEGER NOT NULL REFERENCES initiatives(id),
            title         TEXT NOT NULL,
            planned_date  TEXT,
            actual_date   TEXT,
            baseline_date TEXT,
            progress      REAL DEFAULT 0,
            status        TEXT DEFAULT 'open',
            owner         TEXT,
            dependencies  TEXT,
            UNIQUE(initiative_id, title)
        )""",
        """CREATE TABLE IF NOT EXISTS risks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            initiative_id INTEGER NOT NULL REFERENCES initiatives(id),
            description   TEXT NOT NULL,
            probability   INTEGER DEFAULT 3,
            impact        INTEGER DEFAULT 3,
            status        TEXT DEFAULT 'open',
            mitigation    TEXT,
            owner         TEXT,
            UNIQUE(initiative_id, description)
        )""",
        """CREATE TABLE IF NOT EXISTS value_entries (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            initiative_id INTEGER REFERENCES initiatives(id),
            period        TEXT NOT NULL,
            category      TEXT DEFAULT 'ebitda',
            planned       REAL DEFAULT 0,
            realized      REAL DEFAULT 0,
            UNIQUE(initiative_id, period, category)
        )""",
        """CREATE TABLE IF NOT EXISTS documents (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name        TEXT NOT NULL,
            file_type        TEXT,
            file_path        TEXT,
            byte_size        INTEGER,
            status           TEXT DEFAULT 'uploaded',
            raw_text         TEXT,
            structured_json  TEXT,
            summary          TEXT,
            n_initiatives    INTEGER DEFAULT 0,
            n_milestones     INTEGER DEFAULT 0,
            n_risks          INTEGER DEFAULT 0,
            n_value_drivers  INTEGER DEFAULT 0,
            n_inconsistencies INTEGER DEFAULT 0,
            error            TEXT,
            uploaded_by      TEXT,
            uploaded_at      TEXT,
            merged_at        TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT,
            entity_id   INTEGER,
            action      TEXT,
            detail      TEXT,
            actor       TEXT,
            at          TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS prompts (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            key               TEXT UNIQUE NOT NULL,
            name              TEXT,
            description       TEXT,
            active_version_id INTEGER,
            created_at        TEXT,
            updated_at        TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS prompt_versions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_id  INTEGER NOT NULL REFERENCES prompts(id),
            version    INTEGER NOT NULL,
            content    TEXT NOT NULL,
            notes      TEXT,
            created_by TEXT,
            created_at TEXT,
            UNIQUE(prompt_id, version)
        )""",
        """CREATE TABLE IF NOT EXISTS report_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            file_type   TEXT,
            outline     TEXT,
            uploaded_by TEXT,
            created_at  TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS reports (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT NOT NULL,
            template_name TEXT,
            created_by    TEXT,
            created_at    TEXT,
            updated_at    TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS report_blocks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL REFERENCES reports(id),
            position  INTEGER NOT NULL DEFAULT 0,
            type      TEXT NOT NULL DEFAULT 'paragraph',
            content   TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS chat_sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            title      TEXT,
            created_at TEXT,
            updated_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES chat_sessions(id),
            role       TEXT NOT NULL,
            content    TEXT,
            created_at TEXT
        )""",
    ]

    def init_db(self) -> None:
        with self.conn() as c:
            for ddl in self.DDL:
                c.execute(text(ddl))
        self._seed_admin()

    def _seed_admin(self) -> None:
        # ADMIN_EMAIL / ADMIN_PASSWORD are authoritative: the admin row is created
        # if missing, and its password is (re)set to match the env on every init —
        # so rotating the password is just an env change + redeploy.
        import bcrypt
        email = os.environ.get("ADMIN_EMAIL", "admin@example.com")
        pw = os.environ.get("ADMIN_PASSWORD", "change-me")
        pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        with self.conn() as c:
            row = c.execute(text("SELECT id FROM users WHERE email = :e"),
                            {"e": email}).fetchone()
            if row:
                c.execute(text("UPDATE users SET password_hash = :p, role = 'admin' "
                               "WHERE email = :e"), {"p": pw_hash, "e": email})
            else:
                c.execute(text(
                    "INSERT INTO users (email, password_hash, name, role, created_at) "
                    "VALUES (:e, :p, :n, 'admin', :t)"),
                    {"e": email, "p": pw_hash, "n": "FastPPM Admin", "t": utcnow()})

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _row(r) -> dict | None:
        return dict(r._mapping) if r is not None else None

    @staticmethod
    def _rows(rs) -> list[dict]:
        return [dict(r._mapping) for r in rs]

    def _ini_id(self, c, ref: str | None) -> int | None:
        if not ref:
            return None
        r = c.execute(text("SELECT id FROM initiatives WHERE ref = :r"), {"r": ref}).fetchone()
        return r[0] if r else None

    @staticmethod
    def _set_clause(fields: dict) -> tuple[str, dict]:
        cols = list(fields.keys())
        clause = ", ".join(f"{c}=:{c}" for c in cols)
        return clause, dict(fields)

    # ── Initiatives ─────────────────────────────────────────────────────────

    _INI_COLS = ["name", "description", "type", "workstream", "owner", "status",
                 "rag", "progress", "start_date", "end_date", "baseline_start",
                 "baseline_end", "value_target", "value_realized", "value_category",
                 "source_document_id"]

    def upsert_initiative(self, ini: dict) -> int:
        with self.conn() as c:
            parent_id = self._ini_id(c, ini.get("parent_ref"))
            ref = ini.get("ref") or ini["name"]
            r = c.execute(text("SELECT id FROM initiatives WHERE ref = :r OR "
                               "(ref IS NULL AND name = :n)"),
                          {"r": ini.get("ref"), "n": ini["name"]}).fetchone()
            params = {col: ini.get(col) for col in self._INI_COLS}
            params["parent_id"] = parent_id
            params["ref"] = ini.get("ref")
            if params.get("progress") is None:
                params["progress"] = 0
            if r:
                params["i"] = r[0]
                params["t"] = utcnow()
                sets = ", ".join(f"{col}=:{col}" for col in self._INI_COLS)
                c.execute(text(f"UPDATE initiatives SET {sets}, parent_id=:parent_id, "
                               "updated_at=:t WHERE id=:i"), params)
                return r[0]
            params["t"] = utcnow()
            cols = ", ".join(self._INI_COLS)
            vals = ", ".join(f":{col}" for col in self._INI_COLS)
            res = c.execute(text(
                f"INSERT INTO initiatives (ref, {cols}, parent_id, created_at, updated_at) "
                f"VALUES (:ref, {vals}, :parent_id, :t, :t)"), params)
            return res.lastrowid

    _INI_SELECT = """
        SELECT i.*, p.name AS parent_name,
            (SELECT COUNT(*) FROM milestones m WHERE m.initiative_id = i.id) AS milestone_count,
            (SELECT COUNT(*) FROM risks r WHERE r.initiative_id = i.id) AS risk_count
        FROM initiatives i
        LEFT JOIN initiatives p ON p.id = i.parent_id
    """

    def get_initiative(self, initiative_id: int) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text(self._INI_SELECT + " WHERE i.id = :i"),
                                       {"i": initiative_id}).fetchone())

    def get_initiative_by_ref(self, ref: str) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text(self._INI_SELECT + " WHERE i.ref = :r"),
                                       {"r": ref}).fetchone())

    def list_initiatives(self, type: str | None = None, status: str | None = None,
                         workstream: str | None = None, parent_id: int | None = None,
                         limit: int = 1000) -> list[dict]:
        q = self._INI_SELECT
        where, p = [], {"lim": limit}
        if type:
            where.append("i.type = :type"); p["type"] = type
        if status:
            where.append("i.status = :status"); p["status"] = status
        if workstream:
            where.append("i.workstream = :ws"); p["ws"] = workstream
        if parent_id is not None:
            where.append("i.parent_id = :pid"); p["pid"] = parent_id
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY i.name LIMIT :lim"
        with self.conn() as c:
            return self._rows(c.execute(text(q), p))

    def set_initiative_fields(self, initiative_id: int, fields: dict) -> None:
        if not fields:
            return
        fields = {**fields, "updated_at": utcnow()}
        clause, params = self._set_clause(fields)
        params["i"] = initiative_id
        with self.conn() as c:
            c.execute(text(f"UPDATE initiatives SET {clause} WHERE id=:i"), params)

    def count_initiatives(self) -> int:
        with self.conn() as c:
            return c.execute(text("SELECT COUNT(*) FROM initiatives")).scalar() or 0

    # ── Milestones ──────────────────────────────────────────────────────────

    @staticmethod
    def _deps_out(v):
        if not v:
            return []
        try:
            return json.loads(v)
        except Exception:
            return []

    def upsert_milestone(self, m: dict) -> int:
        with self.conn() as c:
            r = c.execute(text("SELECT id FROM milestones WHERE initiative_id=:i AND title=:t"),
                          {"i": m["initiative_id"], "t": m["title"]}).fetchone()
            params = {"i": m["initiative_id"], "t": m["title"],
                      "pd": m.get("planned_date"), "ad": m.get("actual_date"),
                      "bd": m.get("baseline_date"), "pr": m.get("progress", 0),
                      "s": m.get("status", "open"), "o": m.get("owner"),
                      "d": json.dumps(m.get("dependencies") or [])}
            if r:
                c.execute(text("UPDATE milestones SET planned_date=:pd, actual_date=:ad, "
                               "baseline_date=:bd, progress=:pr, status=:s, owner=:o, "
                               "dependencies=:d WHERE id=:id"), {**params, "id": r[0]})
                return r[0]
            res = c.execute(text(
                "INSERT INTO milestones (initiative_id, title, planned_date, actual_date, "
                "baseline_date, progress, status, owner, dependencies) "
                "VALUES (:i, :t, :pd, :ad, :bd, :pr, :s, :o, :d)"), params)
            return res.lastrowid

    def get_milestone(self, milestone_id: int) -> dict | None:
        with self.conn() as c:
            d = self._row(c.execute(text("SELECT * FROM milestones WHERE id=:i"),
                                    {"i": milestone_id}).fetchone())
        if d:
            d["dependencies"] = self._deps_out(d.get("dependencies"))
        return d

    def list_milestones(self, initiative_id: int | None = None) -> list[dict]:
        q = ("SELECT m.*, i.name AS initiative_name, i.ref AS initiative_ref "
             "FROM milestones m JOIN initiatives i ON i.id = m.initiative_id")
        p = {}
        if initiative_id is not None:
            q += " WHERE m.initiative_id = :i"; p["i"] = initiative_id
        q += " ORDER BY m.planned_date"
        with self.conn() as c:
            rows = self._rows(c.execute(text(q), p))
        for d in rows:
            d["dependencies"] = self._deps_out(d.get("dependencies"))
        return rows

    def set_milestone_fields(self, milestone_id: int, fields: dict) -> None:
        if not fields:
            return
        if "dependencies" in fields:
            fields = {**fields, "dependencies": json.dumps(fields["dependencies"] or [])}
        clause, params = self._set_clause(fields)
        params["i"] = milestone_id
        with self.conn() as c:
            c.execute(text(f"UPDATE milestones SET {clause} WHERE id=:i"), params)

    # ── Risks ───────────────────────────────────────────────────────────────

    def upsert_risk(self, r_: dict) -> int:
        with self.conn() as c:
            r = c.execute(text("SELECT id FROM risks WHERE initiative_id=:i AND description=:d"),
                          {"i": r_["initiative_id"], "d": r_["description"]}).fetchone()
            params = {"i": r_["initiative_id"], "d": r_["description"],
                      "pr": r_.get("probability", 3), "im": r_.get("impact", 3),
                      "s": r_.get("status", "open"), "mi": r_.get("mitigation"),
                      "o": r_.get("owner")}
            if r:
                c.execute(text("UPDATE risks SET probability=:pr, impact=:im, status=:s, "
                               "mitigation=:mi, owner=:o WHERE id=:id"), {**params, "id": r[0]})
                return r[0]
            res = c.execute(text(
                "INSERT INTO risks (initiative_id, description, probability, impact, status, "
                "mitigation, owner) VALUES (:i, :d, :pr, :im, :s, :mi, :o)"), params)
            return res.lastrowid

    def list_risks(self, initiative_id: int | None = None) -> list[dict]:
        q = ("SELECT r.*, i.name AS initiative_name FROM risks r "
             "JOIN initiatives i ON i.id = r.initiative_id")
        p = {}
        if initiative_id is not None:
            q += " WHERE r.initiative_id = :i"; p["i"] = initiative_id
        q += " ORDER BY (r.probability * r.impact) DESC"
        with self.conn() as c:
            return self._rows(c.execute(text(q), p))

    # ── Value tracking ──────────────────────────────────────────────────────

    def add_value_entry(self, v: dict) -> int:
        with self.conn() as c:
            pid = v.get("initiative_id")
            r = c.execute(text(
                "SELECT id FROM value_entries WHERE (initiative_id IS :i OR initiative_id=:i) "
                "AND period=:p AND category=:cat"),
                {"i": pid, "p": v["period"], "cat": v.get("category", "ebitda")}).fetchone()
            params = {"i": pid, "p": v["period"], "cat": v.get("category", "ebitda"),
                      "pl": v.get("planned", 0), "re": v.get("realized", 0)}
            if r:
                c.execute(text("UPDATE value_entries SET planned=:pl, realized=:re WHERE id=:id"),
                          {**params, "id": r[0]})
                return r[0]
            res = c.execute(text(
                "INSERT INTO value_entries (initiative_id, period, category, planned, realized) "
                "VALUES (:i, :p, :cat, :pl, :re)"), params)
            return res.lastrowid

    def list_value_entries(self, initiative_id: int | None = None,
                           category: str | None = None) -> list[dict]:
        q = "SELECT * FROM value_entries"
        where, p = [], {}
        if initiative_id is not None:
            where.append("initiative_id = :i"); p["i"] = initiative_id
        if category:
            where.append("category = :c"); p["c"] = category
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY period"
        with self.conn() as c:
            return self._rows(c.execute(text(q), p))

    def value_summary(self) -> dict:
        with self.conn() as c:
            tot = self._row(c.execute(text(
                "SELECT COALESCE(SUM(value_target),0) AS target, "
                "COALESCE(SUM(value_realized),0) AS realized FROM initiatives "
                "WHERE type != 'program'")).fetchone())
            by_cat = self._rows(c.execute(text(
                "SELECT value_category AS category, COALESCE(SUM(value_target),0) AS target, "
                "COALESCE(SUM(value_realized),0) AS realized FROM initiatives "
                "WHERE value_category IS NOT NULL AND type != 'program' GROUP BY value_category")))
            by_period = self._rows(c.execute(text(
                "SELECT period, COALESCE(SUM(planned),0) AS planned, "
                "COALESCE(SUM(realized),0) AS realized FROM value_entries "
                "GROUP BY period ORDER BY period")))
        target = tot["target"] or 0
        realized = tot["realized"] or 0
        return {"target": target, "realized": realized,
                "realization_pct": round(100 * realized / target, 1) if target else 0,
                "by_category": by_cat, "by_period": by_period}

    # ── Documents ───────────────────────────────────────────────────────────

    def add_document(self, doc: dict) -> int:
        with self.conn() as c:
            res = c.execute(text(
                "INSERT INTO documents (file_name, file_type, file_path, byte_size, status, "
                "uploaded_by, uploaded_at) VALUES (:fn, :ft, :fp, :bs, :st, :ub, :t)"),
                {"fn": doc["file_name"], "ft": doc.get("file_type"),
                 "fp": doc.get("file_path"), "bs": doc.get("byte_size"),
                 "st": doc.get("status", "uploaded"), "ub": doc.get("uploaded_by"),
                 "t": utcnow()})
            return res.lastrowid

    def update_document(self, document_id: int, fields: dict) -> None:
        if not fields:
            return
        if "structured_json" in fields and not isinstance(fields["structured_json"], str):
            fields = {**fields, "structured_json": json.dumps(fields["structured_json"])}
        clause, params = self._set_clause(fields)
        params["i"] = document_id
        with self.conn() as c:
            c.execute(text(f"UPDATE documents SET {clause} WHERE id=:i"), params)

    def get_document(self, document_id: int) -> dict | None:
        with self.conn() as c:
            d = self._row(c.execute(text("SELECT * FROM documents WHERE id=:i"),
                                    {"i": document_id}).fetchone())
        if d and d.get("structured_json"):
            try:
                d["structured_json"] = json.loads(d["structured_json"])
            except Exception:
                d["structured_json"] = None
        return d

    def list_documents(self, status: str | None = None) -> list[dict]:
        q = ("SELECT id, file_name, file_type, file_path, byte_size, status, summary, "
             "n_initiatives, n_milestones, n_risks, n_value_drivers, n_inconsistencies, "
             "error, uploaded_by, uploaded_at, merged_at FROM documents")
        p = {}
        if status:
            q += " WHERE status = :s"; p["s"] = status
        q += " ORDER BY id DESC"
        with self.conn() as c:
            return self._rows(c.execute(text(q), p))

    def search_documents(self, query: str, limit: int = 8) -> list[dict]:
        # Substring scan over merged documents (lightweight, backend-portable).
        terms = [t for t in (query or "").lower().split() if len(t) > 2][:6]
        with self.conn() as c:
            docs = self._rows(c.execute(text(
                "SELECT id, file_name, raw_text FROM documents WHERE status='merged' "
                "AND raw_text IS NOT NULL")))
        scored = []
        for d in docs:
            txt = (d.get("raw_text") or "").lower()
            score = sum(txt.count(t) for t in terms)
            if score:
                i = min((txt.find(t) for t in terms if t in txt), default=0)
                snippet = (d["raw_text"][max(0, i - 60): i + 200]).strip()
                scored.append({"id": d["id"], "file_name": d["file_name"],
                               "snippet": snippet, "score": score})
        scored.sort(key=lambda x: -x["score"])
        return scored[:limit]

    # ── Activity log ────────────────────────────────────────────────────────

    def log_activity(self, entry: dict) -> int:
        with self.conn() as c:
            res = c.execute(text(
                "INSERT INTO activity_log (entity_type, entity_id, action, detail, actor, at) "
                "VALUES (:et, :ei, :a, :d, :ac, :t)"),
                {"et": entry.get("entity_type"), "ei": entry.get("entity_id"),
                 "a": entry.get("action"), "d": entry.get("detail"),
                 "ac": entry.get("actor"), "t": utcnow()})
            return res.lastrowid

    def list_activity(self, entity_type: str | None = None,
                      entity_id: int | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT * FROM activity_log"
        where, p = [], {"lim": limit}
        if entity_type:
            where.append("entity_type = :et"); p["et"] = entity_type
        if entity_id is not None:
            where.append("entity_id = :ei"); p["ei"] = entity_id
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id DESC LIMIT :lim"
        with self.conn() as c:
            return self._rows(c.execute(text(q), p))

    # ── Dashboard rollup ────────────────────────────────────────────────────

    def portfolio_summary(self) -> dict:
        with self.conn() as c:
            status_rows = self._rows(c.execute(text(
                "SELECT status, COUNT(*) AS n FROM initiatives GROUP BY status")))
            type_rows = self._rows(c.execute(text(
                "SELECT type, COUNT(*) AS n FROM initiatives GROUP BY type")))
            rag_rows = self._rows(c.execute(text(
                "SELECT rag, COUNT(*) AS n FROM initiatives WHERE status NOT IN "
                "('complete','not_started') GROUP BY rag")))
            # Roll up the deliverable initiatives only — the 'program' node is an
            # umbrella whose value/progress is the sum of its children.
            agg = self._row(c.execute(text(
                "SELECT COALESCE(AVG(progress),0) AS avg_progress, "
                "COALESCE(SUM(value_target),0) AS target, "
                "COALESCE(SUM(value_realized),0) AS realized, COUNT(*) AS total "
                "FROM initiatives WHERE type != 'program'")).fetchone())
            open_risks = c.execute(text(
                "SELECT COUNT(*) FROM risks WHERE status='open'")).scalar() or 0
            high_risks = c.execute(text(
                "SELECT COUNT(*) FROM risks WHERE status='open' AND probability*impact >= 12"
                )).scalar() or 0
            # On-time: milestones with actual <= planned (completed) or planned not past
            ms = self._rows(c.execute(text(
                "SELECT planned_date, actual_date, status, progress FROM milestones")))
            doc_total = c.execute(text("SELECT COUNT(*) FROM documents")).scalar() or 0
            doc_merged = c.execute(text(
                "SELECT COUNT(*) FROM documents WHERE status='merged'")).scalar() or 0
        statuses = {r["status"]: r["n"] for r in status_rows}
        types = {r["type"]: r["n"] for r in type_rows}
        rag = {r["rag"]: r["n"] for r in rag_rows if r["rag"]}
        active = sum(rag.values())
        on_track = rag.get("G", 0)
        # On-time %: completed milestones delivered on/before planned date.
        done = [m for m in ms if (m.get("status") == "done" or (m.get("progress") or 0) >= 100)]
        on_time = sum(1 for m in done if m.get("actual_date") and m.get("planned_date")
                      and m["actual_date"] <= m["planned_date"])
        target = agg["target"] or 0
        realized = agg["realized"] or 0
        return {
            "statuses": statuses, "types": types, "rag": rag,
            "total_initiatives": agg["total"], "active_initiatives": active,
            "on_track_pct": round(100 * on_track / active, 1) if active else 0,
            "avg_progress": round(agg["avg_progress"] or 0, 0),
            "on_time_pct": round(100 * on_time / len(done), 0) if done else 0,
            "value_target": target, "value_realized": realized,
            "realization_pct": round(100 * realized / target, 1) if target else 0,
            "open_risks": open_risks, "high_risks": high_risks,
            "documents_total": doc_total, "documents_merged": doc_merged,
        }

    # ── Prompt manager ──────────────────────────────────────────────────────

    def ensure_prompt(self, key: str, name: str, description: str,
                      default_content: str) -> int:
        with self.conn() as c:
            row = c.execute(text("SELECT id FROM prompts WHERE key = :k"),
                            {"k": key}).fetchone()
            if row:
                return row[0]
            res = c.execute(text(
                "INSERT INTO prompts (key, name, description, created_at, updated_at) "
                "VALUES (:k, :n, :d, :t, :t)"),
                {"k": key, "n": name, "d": description, "t": utcnow()})
            pid = res.lastrowid
            vres = c.execute(text(
                "INSERT INTO prompt_versions (prompt_id, version, content, notes, "
                "created_by, created_at) VALUES (:p, 1, :c, 'Initial version', 'system', :t)"),
                {"p": pid, "c": default_content, "t": utcnow()})
            c.execute(text("UPDATE prompts SET active_version_id = :v WHERE id = :p"),
                      {"v": vres.lastrowid, "p": pid})
            return pid

    def list_prompts(self) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text("""
                SELECT p.*, av.version AS active_version,
                    (SELECT COUNT(*) FROM prompt_versions v WHERE v.prompt_id = p.id) AS version_count
                FROM prompts p
                LEFT JOIN prompt_versions av ON av.id = p.active_version_id
                ORDER BY p.name""")))

    def get_prompt(self, key: str) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text("""
                SELECT p.*, av.version AS active_version, av.content AS active_content
                FROM prompts p
                LEFT JOIN prompt_versions av ON av.id = p.active_version_id
                WHERE p.key = :k"""), {"k": key}).fetchone())

    def get_active_prompt_content(self, key: str) -> str | None:
        with self.conn() as c:
            r = c.execute(text("""
                SELECT av.content FROM prompts p
                JOIN prompt_versions av ON av.id = p.active_version_id
                WHERE p.key = :k"""), {"k": key}).fetchone()
        return r[0] if r else None

    def list_prompt_versions(self, key: str) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text("""
                SELECT v.*, (v.id = p.active_version_id) AS is_active
                FROM prompt_versions v JOIN prompts p ON p.id = v.prompt_id
                WHERE p.key = :k ORDER BY v.version DESC"""), {"k": key}))

    def add_prompt_version(self, key: str, content: str, notes: str = "",
                           created_by: str = "") -> dict:
        with self.conn() as c:
            p = c.execute(text("SELECT id FROM prompts WHERE key = :k"), {"k": key}).fetchone()
            if not p:
                raise ValueError(f"Unknown prompt key={key!r}")
            pid = p[0]
            nextv = (c.execute(text("SELECT COALESCE(MAX(version),0)+1 FROM prompt_versions "
                                    "WHERE prompt_id = :p"), {"p": pid}).scalar())
            res = c.execute(text(
                "INSERT INTO prompt_versions (prompt_id, version, content, notes, created_by, "
                "created_at) VALUES (:p, :v, :c, :n, :u, :t)"),
                {"p": pid, "v": nextv, "c": content, "n": notes, "u": created_by, "t": utcnow()})
            c.execute(text("UPDATE prompts SET active_version_id = :v, updated_at = :t WHERE id = :p"),
                      {"v": res.lastrowid, "t": utcnow(), "p": pid})
            return {"id": res.lastrowid, "version": nextv}

    def set_active_prompt_version(self, key: str, version_id: int) -> None:
        with self.conn() as c:
            c.execute(text("""
                UPDATE prompts SET active_version_id = :v, updated_at = :t
                WHERE key = :k AND :v IN (
                    SELECT id FROM prompt_versions WHERE prompt_id = prompts.id)"""),
                {"v": version_id, "t": utcnow(), "k": key})

    # ── Reports ─────────────────────────────────────────────────────────────

    def add_report_template(self, tpl: dict) -> int:
        with self.conn() as c:
            res = c.execute(text(
                "INSERT INTO report_templates (name, file_type, outline, uploaded_by, created_at) "
                "VALUES (:n, :ft, :o, :u, :t)"),
                {"n": tpl["name"], "ft": tpl.get("file_type"), "o": tpl.get("outline"),
                 "u": tpl.get("uploaded_by"), "t": utcnow()})
            return res.lastrowid

    def list_report_templates(self) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text(
                "SELECT id, name, file_type, uploaded_by, created_at FROM report_templates "
                "ORDER BY id DESC")))

    def get_report_template(self, template_id: int) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text("SELECT * FROM report_templates WHERE id=:i"),
                                       {"i": template_id}).fetchone())

    def create_report(self, title: str, blocks: list[dict], template_name: str = "",
                      created_by: str = "") -> int:
        with self.conn() as c:
            res = c.execute(text(
                "INSERT INTO reports (title, template_name, created_by, created_at, updated_at) "
                "VALUES (:t, :tn, :cb, :n, :n)"),
                {"t": title, "tn": template_name, "cb": created_by, "n": utcnow()})
            rid = res.lastrowid
            for pos, b in enumerate(blocks):
                c.execute(text(
                    "INSERT INTO report_blocks (report_id, position, type, content) "
                    "VALUES (:r, :p, :ty, :c)"),
                    {"r": rid, "p": pos, "ty": b.get("type", "paragraph"),
                     "c": b.get("content", "")})
            return rid

    def get_report(self, report_id: int) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text("SELECT * FROM reports WHERE id=:i"),
                                       {"i": report_id}).fetchone())

    def list_reports(self, limit: int = 100) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text(
                "SELECT r.*, (SELECT COUNT(*) FROM report_blocks b WHERE b.report_id=r.id) "
                "AS block_count FROM reports r ORDER BY r.id DESC LIMIT :l"), {"l": limit}))

    def set_report_title(self, report_id: int, title: str) -> None:
        with self.conn() as c:
            c.execute(text("UPDATE reports SET title=:t, updated_at=:u WHERE id=:i"),
                      {"t": title, "u": utcnow(), "i": report_id})

    def delete_report(self, report_id: int) -> None:
        with self.conn() as c:
            c.execute(text("DELETE FROM report_blocks WHERE report_id=:i"), {"i": report_id})
            c.execute(text("DELETE FROM reports WHERE id=:i"), {"i": report_id})

    def list_report_blocks(self, report_id: int) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text(
                "SELECT id, position, type, content FROM report_blocks WHERE report_id=:r "
                "ORDER BY position, id"), {"r": report_id}))

    def get_report_block(self, block_id: int) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text("SELECT * FROM report_blocks WHERE id=:i"),
                                       {"i": block_id}).fetchone())

    def _touch_report(self, c, report_id: int):
        c.execute(text("UPDATE reports SET updated_at=:u WHERE id=:i"),
                  {"u": utcnow(), "i": report_id})

    def add_report_block(self, report_id: int, type: str = "paragraph",
                         content: str = "", after_id: int | None = None) -> int:
        with self.conn() as c:
            if after_id:
                pos = c.execute(text("SELECT position FROM report_blocks WHERE id=:i"),
                                {"i": after_id}).scalar()
                pos = (pos if pos is not None else 0) + 1
                c.execute(text("UPDATE report_blocks SET position=position+1 "
                               "WHERE report_id=:r AND position>=:p"), {"r": report_id, "p": pos})
            else:
                mx = c.execute(text("SELECT COALESCE(MAX(position),-1) FROM report_blocks "
                                    "WHERE report_id=:r"), {"r": report_id}).scalar()
                pos = (mx if mx is not None else -1) + 1
            res = c.execute(text(
                "INSERT INTO report_blocks (report_id, position, type, content) "
                "VALUES (:r, :p, :ty, :c)"),
                {"r": report_id, "p": pos, "ty": type, "c": content})
            self._touch_report(c, report_id)
            return res.lastrowid

    def update_report_block(self, block_id: int, content: str, type: str | None = None) -> None:
        with self.conn() as c:
            if type is not None:
                c.execute(text("UPDATE report_blocks SET content=:c, type=:ty WHERE id=:i"),
                          {"c": content, "ty": type, "i": block_id})
            else:
                c.execute(text("UPDATE report_blocks SET content=:c WHERE id=:i"),
                          {"c": content, "i": block_id})
            rid = c.execute(text("SELECT report_id FROM report_blocks WHERE id=:i"),
                            {"i": block_id}).scalar()
            if rid:
                self._touch_report(c, rid)

    def move_report_block(self, block_id: int, direction: int) -> None:
        with self.conn() as c:
            b = c.execute(text("SELECT report_id, position FROM report_blocks WHERE id=:i"),
                          {"i": block_id}).fetchone()
            if not b:
                return
            rid, pos = b[0], b[1]
            npos = pos + (1 if direction > 0 else -1)
            other = c.execute(text("SELECT id, position FROM report_blocks WHERE report_id=:r "
                                   "AND position=:p"), {"r": rid, "p": npos}).fetchone()
            if not other:
                return
            c.execute(text("UPDATE report_blocks SET position=:p WHERE id=:i"),
                      {"p": npos, "i": block_id})
            c.execute(text("UPDATE report_blocks SET position=:p WHERE id=:i"),
                      {"p": pos, "i": other[0]})
            self._touch_report(c, rid)

    def delete_report_block(self, block_id: int) -> None:
        with self.conn() as c:
            rid = c.execute(text("SELECT report_id FROM report_blocks WHERE id=:i"),
                            {"i": block_id}).scalar()
            c.execute(text("DELETE FROM report_blocks WHERE id=:i"), {"i": block_id})
            if rid:
                self._touch_report(c, rid)

    # ── Users / auth ────────────────────────────────────────────────────────

    def get_user_by_email(self, email: str) -> dict | None:
        with self.conn() as c:
            return self._row(c.execute(text(
                "SELECT id, email, password_hash, name, role FROM users WHERE email = :e"),
                {"e": email}).fetchone())

    # ── Chat history ────────────────────────────────────────────────────────

    def create_chat_session(self, user_email: str, title: str = "") -> int:
        with self.conn() as c:
            res = c.execute(text(
                "INSERT INTO chat_sessions (user_email, title, created_at, updated_at) "
                "VALUES (:e, :t, :n, :n)"), {"e": user_email, "t": title, "n": utcnow()})
            return res.lastrowid

    def add_chat_message(self, session_id: int, role: str, content: str) -> None:
        with self.conn() as c:
            c.execute(text("INSERT INTO chat_messages (session_id, role, content, created_at) "
                           "VALUES (:s, :r, :c, :t)"),
                      {"s": session_id, "r": role, "c": content, "t": utcnow()})
            c.execute(text("UPDATE chat_sessions SET updated_at=:t WHERE id=:s"),
                      {"t": utcnow(), "s": session_id})

    def list_chat_sessions(self, user_email: str, limit: int = 30) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text(
                "SELECT id, title, updated_at FROM chat_sessions WHERE user_email=:e "
                "ORDER BY updated_at DESC LIMIT :l"), {"e": user_email, "l": limit}))

    def get_chat_messages(self, session_id: int) -> list[dict]:
        with self.conn() as c:
            return self._rows(c.execute(text(
                "SELECT role, content, created_at FROM chat_messages WHERE session_id=:s "
                "ORDER BY id"), {"s": session_id}))
