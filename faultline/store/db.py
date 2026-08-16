"""SQLite store: cache, trace, and the append-only claim record."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faultline.config import PROJECT_ROOT, SETTINGS

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def cache_key(provider: str, model_id: str, messages: list[dict[str, str]],
              schema: dict[str, Any]) -> str:
    """Stable hash over everything that could change the answer.

    sort_keys matters: a non-deterministic dict ordering would produce a
    different key for an identical request and silently defeat the cache.
    """
    payload = json.dumps(
        {"provider": provider, "model": model_id, "messages": messages, "schema": schema},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class Store:
    def __init__(self, db_path: Path | None = None):
        self.path = Path(db_path or SETTINGS.db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns that CREATE TABLE IF NOT EXISTS will not add to an
        existing database. Cheap, idempotent, and keeps older run history
        readable instead of forcing the db to be deleted."""
        for table, column, decl in (("claims", "source_title", "TEXT"),):
            have = {r["name"] for r in
                    self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # --- runs ----------------------------------------------------------------

    def start_run(self, mode: str, question: str | None = None,
                  paper_ref: str | None = None, config: dict | None = None) -> str:
        run_id = new_id("run")
        self.conn.execute(
            "INSERT INTO runs (id, mode, question, paper_ref, started_at, config_json) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, mode, question, paper_ref, _now(), json.dumps(config or {})))
        self.conn.commit()
        return run_id

    def finish_run(self, run_id: str, ledger: dict | None = None,
                   field: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, ledger_json=?, field=COALESCE(?, field) WHERE id=?",
            (_now(), json.dumps(ledger or {}), field, run_id))
        self.conn.commit()

    # --- llm cache -----------------------------------------------------------

    def cache_get(self, key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT response_json, raw_text, tokens_in, tokens_out FROM llm_cache WHERE key=?",
            (key,)).fetchone()
        if row is None:
            return None
        return {
            "data": json.loads(row["response_json"]),
            "raw_text": row["raw_text"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
        }

    def cache_put(self, key: str, provider: str, model_id: str, lineage: str,
                  data: dict, raw_text: str, tokens_in: int, tokens_out: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO llm_cache "
            "(key, provider, model_id, lineage, response_json, raw_text, "
            " tokens_in, tokens_out, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (key, provider, model_id, lineage, json.dumps(data), raw_text,
             tokens_in, tokens_out, _now()))
        self.conn.commit()

    # --- trace ---------------------------------------------------------------

    def event(self, run_id: str, kind: str, **kw: Any) -> None:
        """Append to the trace. Every model call, cache hit, failover and
        refusal lands here — this is what the user audits, not a log file."""
        self.conn.execute(
            "INSERT INTO events (run_id, ts, stage, role, provider, model_id, lineage, "
            "kind, subject_id, tokens_in, tokens_out, latency_ms, attempts, detail) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, _now(), kw.get("stage"), kw.get("role"), kw.get("provider"),
             kw.get("model_id"), kw.get("lineage"), kind, kw.get("subject_id"),
             kw.get("tokens_in", 0), kw.get("tokens_out", 0), kw.get("latency_ms", 0),
             kw.get("attempts", 1), kw.get("detail")))
        self.conn.commit()

    def trace(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()

    # --- generic upsert helpers ---------------------------------------------

    def insert(self, table: str, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" * len(row))
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})",
            tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()))
        self.conn.commit()

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        cols = ", ".join(rows[0])
        marks = ", ".join("?" * len(rows[0]))
        self.conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})",
            [tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in r.values())
             for r in rows])
        self.conn.commit()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def close(self) -> None:
        self.conn.close()
