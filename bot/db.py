from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from .models import ConversationState, MessageRecord, PlanRecord


class BotDB:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    ts_utc INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    msg_type TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    chat_id TEXT PRIMARY KEY,
                    chat_type TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    last_user_ts_utc INTEGER,
                    last_bot_ts_utc INTEGER,
                    daily_count INTEGER NOT NULL DEFAULT 0,
                    daily_date TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    send_at_utc INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    gif_tag TEXT,
                    status TEXT NOT NULL,
                    reason TEXT,
                    confidence REAL NOT NULL,
                    created_at_utc INTEGER NOT NULL,
                    updated_at_utc INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, ts_utc)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_plans_status_time ON plans(status, send_at_utc)"
            )
        # Lightweight migration: ensure newer columns exist.
        self._ensure_column("conversations", "chat_type", "TEXT NOT NULL DEFAULT 'direct'")

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        with self._conn:
            rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            columns = {row[1] for row in rows}
            if column not in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add_message(
        self,
        chat_id: str,
        sender_id: str,
        role: str,
        ts_utc: int,
        content: str,
        msg_type: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO messages (chat_id, sender_id, role, ts_utc, content, msg_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chat_id, sender_id, role, ts_utc, content, msg_type),
            )

    def get_recent_messages(self, chat_id: str, limit: int) -> list[MessageRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content, ts_utc, msg_type, sender_id
                FROM messages
                WHERE chat_id = ?
                ORDER BY ts_utc DESC
                LIMIT ?
                """,
                (chat_id, limit),
            ).fetchall()
        records = [
            MessageRecord(
                role=row[0],
                content=row[1],
                ts_utc=row[2],
                msg_type=row[3],
                sender_id=row[4],
            )
            for row in rows
        ]
        return list(reversed(records))

    def ensure_conversation(self, chat_id: str, chat_type: str) -> ConversationState:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM conversations WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO conversations (chat_id, chat_type, summary, daily_count)
                    VALUES (?, ?, '', 0)
                    """,
                    (chat_id, chat_type),
                )
                return ConversationState(
                    chat_id=chat_id,
                    chat_type=chat_type,
                    summary="",
                    last_user_ts_utc=None,
                    last_bot_ts_utc=None,
                    daily_count=0,
                    daily_date=None,
                )
            if row["chat_type"] != chat_type:
                self._conn.execute(
                    "UPDATE conversations SET chat_type = ? WHERE chat_id = ?",
                    (chat_type, chat_id),
                )
        return self.get_conversation(chat_id)

    def get_conversation(self, chat_id: str) -> ConversationState:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM conversations WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"Conversation not found: {chat_id}")
        return ConversationState(
            chat_id=row["chat_id"],
            chat_type=row["chat_type"],
            summary=row["summary"],
            last_user_ts_utc=row["last_user_ts_utc"],
            last_bot_ts_utc=row["last_bot_ts_utc"],
            daily_count=row["daily_count"],
            daily_date=row["daily_date"],
        )

    def update_conversation_summary(self, chat_id: str, summary: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE conversations SET summary = ? WHERE chat_id = ?",
                (summary, chat_id),
            )

    def update_last_user_ts(self, chat_id: str, ts_utc: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE conversations SET last_user_ts_utc = ? WHERE chat_id = ?",
                (ts_utc, chat_id),
            )

    def update_last_bot_ts(self, chat_id: str, ts_utc: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE conversations SET last_bot_ts_utc = ? WHERE chat_id = ?",
                (ts_utc, chat_id),
            )

    def update_daily_counter(self, chat_id: str, daily_count: int, daily_date: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE conversations SET daily_count = ?, daily_date = ? WHERE chat_id = ?",
                (daily_count, daily_date, chat_id),
            )

    def get_pending_plans(self, chat_id: str) -> list[PlanRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM plans
                WHERE chat_id = ? AND status = 'pending'
                ORDER BY send_at_utc ASC
                """,
                (chat_id,),
            ).fetchall()
        return [self._plan_from_row(row) for row in rows]

    def count_pending_plans(self, chat_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT COUNT(*) FROM plans
                WHERE chat_id = ? AND status = 'pending'
                """,
                (chat_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def add_plan(
        self,
        chat_id: str,
        send_at_utc: int,
        text: str,
        gif_tag: str | None,
        reason: str,
        confidence: float,
        now_utc: int,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO plans (chat_id, send_at_utc, text, gif_tag, status, reason, confidence, created_at_utc, updated_at_utc)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (chat_id, send_at_utc, text, gif_tag, reason, confidence, now_utc, now_utc),
            )

    def cancel_all_plans(self, chat_id: str, now_utc: int) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE plans
                SET status = 'canceled', updated_at_utc = ?
                WHERE chat_id = ? AND status = 'pending'
                """,
                (now_utc, chat_id),
            )
        return cursor.rowcount

    def mark_plan_sent(self, plan_id: int, now_utc: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE plans
                SET status = 'sent', updated_at_utc = ?
                WHERE id = ?
                """,
                (now_utc, plan_id),
            )

    def mark_plan_canceled(self, plan_id: int, now_utc: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE plans
                SET status = 'canceled', updated_at_utc = ?
                WHERE id = ?
                """,
                (now_utc, plan_id),
            )

    def reschedule_plan(self, plan_id: int, send_at_utc: int, now_utc: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE plans
                SET send_at_utc = ?, updated_at_utc = ?
                WHERE id = ?
                """,
                (send_at_utc, now_utc, plan_id),
            )

    def get_due_plans(self, now_utc: int, limit: int = 50) -> list[PlanRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM plans
                WHERE status = 'pending' AND send_at_utc <= ?
                ORDER BY send_at_utc ASC
                LIMIT ?
                """,
                (now_utc, limit),
            ).fetchall()
        return [self._plan_from_row(row) for row in rows]

    def _plan_from_row(self, row: sqlite3.Row) -> PlanRecord:
        return PlanRecord(
            id=row["id"],
            chat_id=row["chat_id"],
            send_at_utc=row["send_at_utc"],
            text=row["text"],
            gif_tag=row["gif_tag"],
            status=row["status"],
            reason=row["reason"],
            confidence=row["confidence"],
        )

    def replace_plans(
        self,
        chat_id: str,
        plans: Iterable[tuple[int, str, str | None, str, float]],
        now_utc: int,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE plans
                SET status = 'canceled', updated_at_utc = ?
                WHERE chat_id = ? AND status = 'pending'
                """,
                (now_utc, chat_id),
            )
            for send_at_utc, text, gif_tag, reason, confidence in plans:
                self._conn.execute(
                    """
                    INSERT INTO plans (chat_id, send_at_utc, text, gif_tag, status, reason, confidence, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (chat_id, send_at_utc, text, gif_tag, reason, confidence, now_utc, now_utc),
                )

    def append_plans(
        self,
        chat_id: str,
        plans: Iterable[tuple[int, str, str | None, str, float]],
        now_utc: int,
    ) -> None:
        with self._lock, self._conn:
            for send_at_utc, text, gif_tag, reason, confidence in plans:
                self._conn.execute(
                    """
                    INSERT INTO plans (chat_id, send_at_utc, text, gif_tag, status, reason, confidence, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (chat_id, send_at_utc, text, gif_tag, reason, confidence, now_utc, now_utc),
                )
