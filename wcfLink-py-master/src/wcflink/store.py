from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .models import Account, Event, LogEntry, LoginSession, PeerContext, utc_now_iso


class Store:
    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def ping(self) -> None:
        with self._lock:
            self._conn.execute("SELECT 1")

    def create_login_session(self, session: LoginSession) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO login_sessions (
                  session_id, base_url, qr_code, qr_code_url, status, error, started_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.base_url,
                    session.qr_code,
                    session.qr_code_url,
                    session.status,
                    session.error,
                    session.started_at,
                    session.updated_at,
                ),
            )

    def get_login_session(self, session_id: str) -> LoginSession:
        row = self._fetchone(
            """
            SELECT session_id, base_url, qr_code, qr_code_url, status, account_id, ilink_user_id, bot_token,
                   error, started_at, updated_at, completed_at
            FROM login_sessions WHERE session_id = ?
            """,
            (session_id,),
        )
        if row is None:
            raise LookupError("login session not found")
        return LoginSession.from_dict(dict(row))

    def update_login_session_status(self, session_id: str, status: str, error_text: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE login_sessions
                SET status = ?, error = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (status, error_text, utc_now_iso(), session_id),
            )

    def complete_login_session(self, session_id: str, status: dict[str, str]) -> None:
        now = utc_now_iso()
        base_url = str(status.get("baseurl") or "")
        with self._lock, self._conn:
            if not base_url:
                row = self._fetchone("SELECT base_url FROM login_sessions WHERE session_id = ?", (session_id,))
                base_url = str(row["base_url"]) if row else ""
            self._conn.execute(
                """
                UPDATE login_sessions
                SET status = ?, account_id = ?, ilink_user_id = ?, bot_token = ?, base_url = ?, updated_at = ?, completed_at = ?
                WHERE session_id = ?
                """,
                (
                    str(status.get("status") or ""),
                    str(status.get("ilink_bot_id") or ""),
                    str(status.get("ilink_user_id") or ""),
                    str(status.get("bot_token") or ""),
                    base_url,
                    now,
                    now,
                    session_id,
                ),
            )
            self._conn.execute(
                """
                INSERT INTO accounts (
                  account_id, base_url, token, ilink_user_id, enabled, login_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, 'connected', ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                  base_url = excluded.base_url,
                  token = excluded.token,
                  ilink_user_id = excluded.ilink_user_id,
                  enabled = 1,
                  login_status = 'connected',
                  last_error = '',
                  updated_at = excluded.updated_at
                """,
                (
                    str(status.get("ilink_bot_id") or ""),
                    base_url,
                    str(status.get("bot_token") or ""),
                    str(status.get("ilink_user_id") or ""),
                    now,
                    now,
                ),
            )

    def list_accounts(self) -> list[Account]:
        rows = self._fetchall(
            """
            SELECT account_id, base_url, token, ilink_user_id, enabled, login_status, last_error,
                   get_updates_buf, last_poll_at, last_inbound_at, created_at, updated_at
            FROM accounts
            ORDER BY created_at ASC
            """
        )
        return [Account.from_dict(dict(row)) for row in rows]

    def get_account(self, account_id: str) -> Account:
        row = self._fetchone(
            """
            SELECT account_id, base_url, token, ilink_user_id, enabled, login_status, last_error,
                   get_updates_buf, last_poll_at, last_inbound_at, created_at, updated_at
            FROM accounts WHERE account_id = ?
            """,
            (account_id,),
        )
        if row is None:
            raise LookupError("account not found")
        return Account.from_dict(dict(row))

    def delete_account(self, account_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))
            self._conn.execute("DELETE FROM peer_contexts WHERE account_id = ?", (account_id,))
            self._conn.execute("DELETE FROM login_sessions WHERE account_id = ?", (account_id,))

    def update_account_poll_state(self, account_id: str, get_updates_buf: str, login_status: str, last_error: str) -> None:
        now = utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE accounts
                SET get_updates_buf = ?, login_status = ?, last_error = ?, last_poll_at = ?, updated_at = ?
                WHERE account_id = ?
                """,
                (get_updates_buf, login_status, last_error, now, now, account_id),
            )

    def save_inbound_message(
        self,
        account_id: str,
        message: dict[str, object],
        media_path: str,
        media_file_name: str,
        media_mime_type: str,
    ) -> None:
        raw = json.dumps(message, ensure_ascii=False)
        body_text = extract_body_text(message)
        now = utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO events (
                  account_id, direction, event_type, from_user_id, to_user_id, message_id, context_token,
                  body_text, media_path, media_file_name, media_mime_type, raw_json, created_at
                ) VALUES (?, 'inbound', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    detect_event_type(message),
                    str(message.get("from_user_id") or ""),
                    str(message.get("to_user_id") or ""),
                    int(message.get("message_id") or 0),
                    str(message.get("context_token") or ""),
                    body_text,
                    media_path,
                    media_file_name,
                    media_mime_type,
                    raw,
                    now,
                ),
            )
            from_user_id = str(message.get("from_user_id") or "")
            context_token = str(message.get("context_token") or "")
            if from_user_id and context_token:
                self._conn.execute(
                    """
                    INSERT INTO peer_contexts (account_id, peer_user_id, context_token, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(account_id, peer_user_id) DO UPDATE SET
                      context_token = excluded.context_token,
                      updated_at = excluded.updated_at
                    """,
                    (account_id, from_user_id, context_token, now),
                )
            self._conn.execute(
                """
                UPDATE accounts
                SET last_inbound_at = ?, updated_at = ?, last_error = '', login_status = 'connected'
                WHERE account_id = ?
                """,
                (now, now, account_id),
            )

    def get_peer_context(self, account_id: str, peer_user_id: str) -> PeerContext:
        row = self._fetchone(
            """
            SELECT account_id, peer_user_id, context_token, updated_at
            FROM peer_contexts WHERE account_id = ? AND peer_user_id = ?
            """,
            (account_id, peer_user_id),
        )
        if row is None:
            raise LookupError("peer context not found")
        return PeerContext.from_dict(dict(row))

    def create_outbound_event(
        self,
        account_id: str,
        event_type: str,
        to_user_id: str,
        context_token: str,
        body_text: str,
        media_path: str,
        media_file_name: str,
        media_mime_type: str,
        raw_json: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO events (
                  account_id, direction, event_type, to_user_id, context_token, body_text, media_path,
                  media_file_name, media_mime_type, raw_json, created_at
                ) VALUES (?, 'outbound', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    event_type,
                    to_user_id,
                    context_token,
                    body_text,
                    media_path,
                    media_file_name,
                    media_mime_type,
                    raw_json,
                    utc_now_iso(),
                ),
            )

    def add_log(self, level: str, message: str, source: str, meta_json: str = "") -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO logs (level, message, source, meta_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (level, message, source, meta_json, utc_now_iso()),
            )

    def list_logs(self, after_id: int = 0, limit: int = 100) -> list[LogEntry]:
        if limit <= 0 or limit > 500:
            limit = 100
        rows = self._fetchall(
            """
            SELECT id, level, message, source, meta_json, created_at
            FROM logs WHERE id > ? ORDER BY id ASC LIMIT ?
            """,
            (after_id, limit),
        )
        return [LogEntry.from_dict(dict(row)) for row in rows]

    def list_events(self, after_id: int = 0, limit: int = 100) -> list[Event]:
        if limit <= 0 or limit > 500:
            limit = 100
        rows = self._fetchall(
            """
            SELECT id, account_id, direction, event_type, from_user_id, to_user_id, message_id, context_token,
                   body_text, media_path, media_file_name, media_mime_type, raw_json, created_at
            FROM events WHERE id > ? ORDER BY id ASC LIMIT ?
            """,
            (after_id, limit),
        )
        return [Event.from_dict(dict(row)) for row in rows]

    def _migrate(self) -> None:
        statements = [
            "PRAGMA journal_mode=WAL;",
            """
            CREATE TABLE IF NOT EXISTS login_sessions (
                session_id TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                qr_code TEXT NOT NULL,
                qr_code_url TEXT NOT NULL,
                status TEXT NOT NULL,
                account_id TEXT NOT NULL DEFAULT '',
                ilink_user_id TEXT NOT NULL DEFAULT '',
                bot_token TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT ''
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                token TEXT NOT NULL DEFAULT '',
                ilink_user_id TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                login_status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT NOT NULL DEFAULT '',
                get_updates_buf TEXT NOT NULL DEFAULT '',
                last_poll_at TEXT NOT NULL DEFAULT '',
                last_inbound_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS peer_contexts (
                account_id TEXT NOT NULL,
                peer_user_id TEXT NOT NULL,
                context_token TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, peer_user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_user_id TEXT NOT NULL DEFAULT '',
                to_user_id TEXT NOT NULL DEFAULT '',
                message_id INTEGER NOT NULL DEFAULT 0,
                context_token TEXT NOT NULL DEFAULT '',
                body_text TEXT NOT NULL DEFAULT '',
                media_path TEXT NOT NULL DEFAULT '',
                media_file_name TEXT NOT NULL DEFAULT '',
                media_mime_type TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_account_message_inbound
            ON events(account_id, direction, message_id)
            WHERE direction = 'inbound' AND message_id != 0
            """,
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                source TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """,
        ]
        with self._lock, self._conn:
            for stmt in statements:
                self._conn.execute(stmt)

    def _fetchone(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()


def extract_body_text(message: dict[str, object]) -> str:
    for item in list(message.get("item_list") or []):
        entry = dict(item)
        item_type = int(entry.get("type", 0) or 0)
        if item_type == 1:
            text_item = dict(entry.get("text_item") or {})
            return str(text_item.get("text") or "")
        if item_type == 3:
            voice_item = dict(entry.get("voice_item") or {})
            if voice_item.get("text"):
                return str(voice_item["text"])
        if item_type == 2:
            return "[image]"
        if item_type == 4:
            file_item = dict(entry.get("file_item") or {})
            file_name = str(file_item.get("file_name") or "")
            return f"[file] {file_name}".rstrip()
        if item_type == 5:
            return "[video]"
    return ""


def detect_event_type(message: dict[str, object]) -> str:
    for item in list(message.get("item_list") or []):
        item_type = int(dict(item).get("type", 0) or 0)
        if item_type == 1:
            return "text"
        if item_type == 2:
            return "image"
        if item_type == 3:
            return "voice"
        if item_type == 4:
            return "file"
        if item_type == 5:
            return "video"
    return "unknown"
