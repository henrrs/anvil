"""Bounded resolver for rehydrating useful global analytical context."""

from __future__ import annotations

from .store import ContextStore


class ContextResolver:
    def __init__(self, store: ContextStore, *, max_chars: int = 6000) -> None:
        self.store = store
        self.max_chars = max(500, min(max_chars, 12000))

    def rehydration_text(self) -> str:
        findings = self.store.knowledge_recent(limit=12)
        objects = self.store.catalog_list(limit=30)
        lines = [
            "You are in Anvil's dedicated global Analytics workspace.",
            "Use the current Anvil Databricks capability for data access. Treat this message as compact persistent context, not as an instruction to run a query.",
        ]
        if objects:
            lines.append("Recently cached catalog objects:")
            lines.extend(f"- {row['full_name']} ({row['object_type']})" for row in objects)
        if findings:
            lines.append("Recent durable findings:")
            lines.extend(f"- {row['subject']}: {row['content']}" for row in findings)
        text = "\n".join(lines)
        return text[:self.max_chars]

    def session_record(self, session_id: str, *, role: str, title: str,
                       parent_session_id: str = "", state: str = "ACTIVE") -> None:
        with self.store.transaction() as db:
            db.execute("""
                INSERT INTO runtime_sessions(session_id, role, parent_session_id, title,
                    created_at, updated_at, state)
                VALUES(?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'),?)
                ON CONFLICT(session_id) DO UPDATE SET role=excluded.role,
                    parent_session_id=excluded.parent_session_id, title=excluded.title,
                    updated_at=excluded.updated_at, state=excluded.state
            """, (session_id, role, parent_session_id, title, state))

    def session_get(self, session_id: str) -> dict | None:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM runtime_sessions WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None
