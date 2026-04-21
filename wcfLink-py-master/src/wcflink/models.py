from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


@dataclass(slots=True)
class VersionInfo:
    version: str
    commit: str | None = None
    build_time: str | None = None
    modified: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionInfo":
        return cls(
            version=_as_str(data.get("version")),
            commit=_as_str(data.get("commit")) or None,
            build_time=_as_str(data.get("build_time")) or None,
            modified=_as_bool(data.get("modified"), False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "commit": self.commit,
            "build_time": self.build_time,
            "modified": self.modified,
        }


@dataclass(slots=True)
class LoginSession:
    session_id: str
    base_url: str
    qr_code: str = ""
    qr_code_url: str = ""
    status: str = ""
    account_id: str = ""
    ilink_user_id: str = ""
    bot_token: str = ""
    error: str = ""
    started_at: str = ""
    updated_at: str = ""
    completed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoginSession":
        return cls(
            session_id=_as_str(data.get("session_id")),
            base_url=_as_str(data.get("base_url")),
            qr_code=_as_str(data.get("qr_code")),
            qr_code_url=_as_str(data.get("qr_code_url")),
            status=_as_str(data.get("status")),
            account_id=_as_str(data.get("account_id")),
            ilink_user_id=_as_str(data.get("ilink_user_id")),
            bot_token=_as_str(data.get("bot_token")),
            error=_as_str(data.get("error")),
            started_at=_as_str(data.get("started_at")),
            updated_at=_as_str(data.get("updated_at")),
            completed_at=_as_str(data.get("completed_at")),
        )

    def to_dict(self, include_private: bool = False) -> dict[str, Any]:
        data = {
            "session_id": self.session_id,
            "base_url": self.base_url,
            "qr_code_url": self.qr_code_url,
            "status": self.status,
            "account_id": self.account_id,
            "ilink_user_id": self.ilink_user_id,
            "error": self.error,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }
        if include_private:
            data["qr_code"] = self.qr_code
            data["bot_token"] = self.bot_token
        return data


@dataclass(slots=True)
class Account:
    account_id: str
    base_url: str
    token: str = ""
    ilink_user_id: str = ""
    enabled: bool = False
    login_status: str = ""
    last_error: str = ""
    get_updates_buf: str = ""
    last_poll_at: str = ""
    last_inbound_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Account":
        return cls(
            account_id=_as_str(data.get("account_id")),
            base_url=_as_str(data.get("base_url")),
            token=_as_str(data.get("token")),
            ilink_user_id=_as_str(data.get("ilink_user_id")),
            enabled=_as_bool(data.get("enabled"), False),
            login_status=_as_str(data.get("login_status")),
            last_error=_as_str(data.get("last_error")),
            get_updates_buf=_as_str(data.get("get_updates_buf")),
            last_poll_at=_as_str(data.get("last_poll_at")),
            last_inbound_at=_as_str(data.get("last_inbound_at")),
            created_at=_as_str(data.get("created_at")),
            updated_at=_as_str(data.get("updated_at")),
        )

    def to_dict(self, include_private: bool = False) -> dict[str, Any]:
        data = {
            "account_id": self.account_id,
            "base_url": self.base_url,
            "ilink_user_id": self.ilink_user_id,
            "enabled": self.enabled,
            "login_status": self.login_status,
            "last_error": self.last_error,
            "last_poll_at": self.last_poll_at,
            "last_inbound_at": self.last_inbound_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_private:
            data["token"] = self.token
            data["get_updates_buf"] = self.get_updates_buf
        return data


@dataclass(slots=True)
class PeerContext:
    account_id: str
    peer_user_id: str
    context_token: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerContext":
        return cls(
            account_id=_as_str(data.get("account_id")),
            peer_user_id=_as_str(data.get("peer_user_id")),
            context_token=_as_str(data.get("context_token")),
            updated_at=_as_str(data.get("updated_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "peer_user_id": self.peer_user_id,
            "context_token": self.context_token,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Event:
    id: int
    account_id: str
    direction: str
    event_type: str
    from_user_id: str = ""
    to_user_id: str = ""
    message_id: int = 0
    context_token: str = ""
    body_text: str = ""
    media_path: str = ""
    media_file_name: str = ""
    media_mime_type: str = ""
    raw_json: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            id=_as_int(data.get("id")),
            account_id=_as_str(data.get("account_id")),
            direction=_as_str(data.get("direction")),
            event_type=_as_str(data.get("event_type")),
            from_user_id=_as_str(data.get("from_user_id")),
            to_user_id=_as_str(data.get("to_user_id")),
            message_id=_as_int(data.get("message_id")),
            context_token=_as_str(data.get("context_token")),
            body_text=_as_str(data.get("body_text")),
            media_path=_as_str(data.get("media_path")),
            media_file_name=_as_str(data.get("media_file_name")),
            media_mime_type=_as_str(data.get("media_mime_type")),
            raw_json=_as_str(data.get("raw_json")),
            created_at=_as_str(data.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "direction": self.direction,
            "event_type": self.event_type,
            "from_user_id": self.from_user_id,
            "to_user_id": self.to_user_id,
            "message_id": self.message_id,
            "context_token": self.context_token,
            "body_text": self.body_text,
            "media_path": self.media_path,
            "media_file_name": self.media_file_name,
            "media_mime_type": self.media_mime_type,
            "raw_json": self.raw_json,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class LogEntry:
    id: int
    level: str
    message: str
    source: str
    meta_json: str = ""
    created_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LogEntry":
        return cls(
            id=_as_int(data.get("id")),
            level=_as_str(data.get("level")),
            message=_as_str(data.get("message")),
            source=_as_str(data.get("source")),
            meta_json=_as_str(data.get("meta_json")),
            created_at=_as_str(data.get("created_at")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "message": self.message,
            "source": self.source,
            "meta_json": self.meta_json,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class Settings:
    listen_addr: str
    webhook_url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        return cls(
            listen_addr=_as_str(data.get("listen_addr")),
            webhook_url=_as_str(data.get("webhook_url")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "listen_addr": self.listen_addr,
            "webhook_url": self.webhook_url,
        }
