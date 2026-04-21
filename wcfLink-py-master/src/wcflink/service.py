from __future__ import annotations

import json
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
import time
from typing import Any
from urllib import request

from .config import Config, save_file_settings
from .ilink_client import ILinkClient
from .models import Account, LoginSession, Settings, utc_now_iso
from .poller import PollerManager
from .store import Store, detect_event_type, extract_body_text


class RuntimeState:
    def __init__(self, cfg: Config) -> None:
        self._settings = Settings(listen_addr=cfg.listen_addr, webhook_url=cfg.webhook_url)

    def settings(self) -> Settings:
        return Settings.from_dict(self._settings.to_dict())

    def update_settings(self, settings: Settings) -> None:
        self._settings = Settings.from_dict(settings.to_dict())


class Service:
    def __init__(
        self,
        cfg: Config,
        logger: logging.Logger,
        store: Store,
        ilink_client: ILinkClient,
        runtime: RuntimeState,
        pollers: PollerManager | None = None,
    ) -> None:
        self.cfg = cfg
        self.logger = logger
        self.store = store
        self.ilink_client = ilink_client
        self.runtime = runtime
        self.pollers = pollers

    def start_login(self, base_url: str = "") -> LoginSession:
        if not base_url:
            base_url = self.cfg.default_base_url
        qr = self.ilink_client.fetch_qrcode(base_url)
        now = utc_now_iso()
        session = LoginSession(
            session_id=f"login_{time.time_ns()}",
            base_url=base_url,
            qr_code=str(qr.get("qrcode") or ""),
            qr_code_url=str(qr.get("qrcode_img_content") or ""),
            status="wait",
            started_at=now,
            updated_at=now,
        )
        self.store.create_login_session(session)
        return session

    def get_login_status(self, session_id: str) -> LoginSession:
        session = self.store.get_login_session(session_id)
        if session.status == "confirmed":
            return session
        status = self.ilink_client.fetch_qrcode_status(session.base_url, session.qr_code)
        if not str(status.get("status") or ""):
            return session
        if str(status.get("status")) == "confirmed":
            self.store.complete_login_session(session_id, status)
            if self.pollers is not None:
                try:
                    self.pollers.start_account(self.store.get_account(str(status.get("ilink_bot_id") or "")))
                except LookupError:
                    pass
            return self.store.get_login_session(session_id)
        self.store.update_login_session_status(session_id, str(status.get("status") or session.status), "")
        return self.store.get_login_session(session_id)

    def get_login_session(self, session_id: str) -> LoginSession:
        return self.store.get_login_session(session_id)

    def list_accounts(self) -> list[Account]:
        return self.store.list_accounts()

    def list_events(self, after_id: int = 0, limit: int = 100):
        return self.store.list_events(after_id, limit)

    def list_logs(self, after_id: int = 0, limit: int = 100):
        return self.store.list_logs(after_id, limit)

    def get_settings(self) -> Settings:
        return self.runtime.settings()

    def update_settings(self, settings: Settings) -> Settings:
        save_file_settings(self.cfg.settings_path, settings.listen_addr, settings.webhook_url)
        self.runtime.update_settings(settings)
        self.store.add_log("INFO", "settings updated", "settings", "")
        return self.runtime.settings()

    def logout_account(self, account_id: str) -> None:
        if self.pollers is not None:
            self.pollers.stop_account(account_id)
        self.store.delete_account(account_id)
        self.store.add_log("INFO", "account disconnected locally", "account", json.dumps({"account_id": account_id}))

    def send_text(self, account_id: str, to_user_id: str, text: str, context_token: str = "") -> None:
        account = self.store.get_account(account_id)
        context_token = self._resolve_context_token(account_id, to_user_id, context_token)
        if not context_token.strip():
            raise RuntimeError("context token not found for this user; current text sending only supports replying to users who have already sent a message")
        self.ilink_client.send_text_message(account.base_url, account.token, to_user_id, text, context_token)
        raw = json.dumps(
            {"to_user_id": to_user_id, "text": text, "context_token": context_token},
            ensure_ascii=False,
        )
        self.store.create_outbound_event(account_id, "text", to_user_id, context_token, text, "", "", "", raw)
        self.store.add_log("INFO", "outbound text sent", "message", raw)

    def send_media(
        self,
        account_id: str,
        to_user_id: str,
        media_type: str,
        file_path: str,
        text: str = "",
        context_token: str = "",
    ) -> None:
        account = self.store.get_account(account_id)
        context_token = self._resolve_context_token(account_id, to_user_id, context_token)
        if not context_token.strip():
            raise RuntimeError("context token not found for this user; media sending only supports replying to users who have already sent a message")

        normalized_type, upload_type = normalize_media_send_type(media_type, file_path)
        uploaded = self.ilink_client.upload_local_media(
            self.cfg.cdn_base_url,
            account.base_url,
            account.token,
            to_user_id,
            file_path,
            upload_type,
        )
        file_name = Path(file_path).name
        if normalized_type == "image":
            self.ilink_client.send_image_message(account.base_url, account.token, to_user_id, context_token, text, uploaded)
        elif normalized_type == "video":
            self.ilink_client.send_video_message(account.base_url, account.token, to_user_id, context_token, text, uploaded)
        elif normalized_type == "file":
            self.ilink_client.send_file_message(
                account.base_url, account.token, to_user_id, context_token, text, file_name, uploaded
            )
        elif normalized_type == "voice":
            self.ilink_client.send_voice_message(
                account.base_url,
                account.token,
                to_user_id,
                context_token,
                text,
                detect_voice_encode_type(file_path),
                uploaded,
            )
        else:
            raise RuntimeError(f"unsupported media type {normalized_type!r}")

        mime_type = detect_outbound_mime(normalized_type, file_path)
        raw = json.dumps(
            {
                "to_user_id": to_user_id,
                "file_path": file_path,
                "media_type": normalized_type,
                "text": text,
                "context_token": context_token,
            },
            ensure_ascii=False,
        )
        self.store.create_outbound_event(
            account_id, normalized_type, to_user_id, context_token, text, file_path, file_name, mime_type, raw
        )
        self.store.add_log("INFO", "outbound media sent", "message", raw)

    def handle_inbound_message(self, account: Account, message: dict[str, Any]) -> None:
        media_path = ""
        media_file_name = ""
        media_mime_type = ""
        media_item = first_inbound_media_item(message)
        if media_item is not None:
            try:
                media_bytes, suggested_file_name, mime_type = self.ilink_client.download_message_media(
                    self.cfg.cdn_base_url, media_item
                )
                media_path, media_file_name, media_mime_type = self._save_inbound_media(
                    account.account_id,
                    int(message.get("message_id", 0) or 0),
                    str(message.get("from_user_id") or ""),
                    suggested_file_name,
                    mime_type,
                    media_bytes,
                )
            except Exception as exc:
                self.logger.warning("download inbound media failed: %s", exc)
                self.store.add_log(
                    "ERROR",
                    "download inbound media failed",
                    "media",
                    json.dumps(
                        {
                            "account_id": account.account_id,
                            "message_id": int(message.get("message_id", 0) or 0),
                            "err": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                )

        self.store.save_inbound_message(account.account_id, message, media_path, media_file_name, media_mime_type)

        payload = json.dumps(
            {
                "account_id": account.account_id,
                "base_url": account.base_url,
                "event_type": detect_event_type(message),
                "body_text": extract_body_text(message),
                "from_user_id": str(message.get("from_user_id") or ""),
                "to_user_id": str(message.get("to_user_id") or ""),
                "message_id": int(message.get("message_id", 0) or 0),
                "context_token": str(message.get("context_token") or ""),
                "media_path": media_path,
                "media_file_name": media_file_name,
                "media_mime_type": media_mime_type,
                "raw_message": message,
                "received_at": utc_now_iso(),
            },
            ensure_ascii=False,
        ).encode("utf-8")

        settings = self.runtime.settings()
        if not settings.webhook_url:
            self.store.add_log("INFO", "inbound message received", "inbound", payload.decode("utf-8"))
            return
        self._deliver_webhook(settings.webhook_url, payload)

    def _resolve_context_token(self, account_id: str, to_user_id: str, context_token: str) -> str:
        if context_token.strip():
            return context_token
        try:
            return self.store.get_peer_context(account_id, to_user_id).context_token
        except LookupError:
            return ""

    def _save_inbound_media(
        self,
        account_id: str,
        message_id: int,
        from_user_id: str,
        file_name: str,
        mime_type: str,
        data: bytes,
    ) -> tuple[str, str, str]:
        media_root = Path(self.cfg.media_dir)
        now = datetime.utcnow()
        target_dir = media_root / sanitize_path_segment(account_id) / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        target_dir.mkdir(parents=True, exist_ok=True)

        safe_name = sanitize_file_name(file_name) or "media"
        suffix = Path(safe_name).suffix or extension_for_mime(mime_type) or ".bin"
        base = Path(safe_name).stem
        prefix = str(message_id or __import__("time").time_ns())
        if from_user_id:
            prefix = f"{prefix}_{sanitize_path_segment(from_user_id)}"
        final_name = f"{prefix}_{base}{suffix}"
        full_path = target_dir / final_name
        full_path.write_bytes(data)
        return str(full_path), final_name, mime_type

    def _deliver_webhook(self, webhook_url: str, payload: bytes) -> None:
        req = request.Request(webhook_url, data=payload, method="POST", headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=10) as resp:
                if resp.status < 200 or resp.status >= 300:
                    raise RuntimeError(f"webhook delivery failed with status {resp.status}")
        except Exception as exc:
            self.store.add_log("ERROR", "webhook delivery failed", "webhook", str(exc))
            return
        self.store.add_log("INFO", "webhook delivered", "webhook", "")


def normalize_media_send_type(media_type: str, file_path: str) -> tuple[str, int]:
    value = media_type.strip().lower()
    if not value:
        suffix = Path(file_path).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            value = "image"
        elif suffix in {".mp4", ".mov", ".m4v"}:
            value = "video"
        elif suffix in {".silk", ".amr", ".mp3", ".ogg", ".wav", ".m4a"}:
            value = "voice"
        else:
            value = "file"
    mapping = {"image": 1, "video": 2, "file": 3, "voice": 4}
    if value not in mapping:
        raise RuntimeError(f"unsupported media type {media_type!r}")
    return value, mapping[value]


def first_inbound_media_item(message: dict[str, Any]) -> dict[str, Any] | None:
    for item in list(message.get("item_list") or []):
        entry = dict(item)
        if int(entry.get("type", 0) or 0) in {2, 3, 4, 5}:
            return entry
    return None


def detect_outbound_mime(media_type: str, file_path: str) -> str:
    if media_type == "image":
        suffix = Path(file_path).suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix == ".gif":
            return "image/gif"
        return "image/jpeg"
    if media_type == "video":
        return "video/mp4"
    if media_type == "voice":
        suffix = Path(file_path).suffix.lower()
        return {
            ".amr": "audio/amr",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
        }.get(suffix, "audio/silk")
    return "application/octet-stream"


def sanitize_path_segment(value: str) -> str:
    out = str(value).strip()
    for char in '/\\:*?"<>|@':
        out = out.replace(char, "_")
    return out or "unknown"


def sanitize_file_name(value: str) -> str:
    name = Path(str(value).strip()).name
    if name in {"", ".", "/"}:
        return ""
    return sanitize_path_segment(name)


def extension_for_mime(mime_type: str) -> str:
    return mimetypes.guess_extension(mime_type) or ""


def detect_voice_encode_type(file_path: str) -> int:
    return {
        ".amr": 5,
        ".mp3": 7,
        ".ogg": 8,
    }.get(Path(file_path).suffix.lower(), 6)
