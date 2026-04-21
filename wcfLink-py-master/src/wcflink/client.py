from __future__ import annotations

import json
from typing import Any
from urllib import error, parse, request

from .exceptions import WcfLinkAPIError
from .models import Account, Event, LoginSession, Settings, VersionInfo


class WcfLinkClient:
    def __init__(self, base_url: str = "http://127.0.0.1:17890", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def version(self) -> VersionInfo:
        return VersionInfo.from_dict(self._request_json("GET", "/api/version"))

    def health_live(self) -> dict[str, Any]:
        return self._request_json("GET", "/health/live")

    def health_ready(self) -> dict[str, Any]:
        return self._request_json("GET", "/health/ready")

    def start_login(self, base_url: str = "") -> LoginSession:
        payload = {"base_url": base_url} if base_url else {}
        return LoginSession.from_dict(self._request_json("POST", "/api/accounts/login/start", payload))

    def get_login_status(self, session_id: str) -> LoginSession:
        query = parse.urlencode({"session_id": session_id})
        return LoginSession.from_dict(self._request_json("GET", f"/api/accounts/login/status?{query}"))

    def get_login_qr(self, session_id: str) -> bytes:
        query = parse.urlencode({"session_id": session_id})
        return self._request_bytes("GET", f"/api/accounts/login/qr?{query}")

    def list_accounts(self) -> list[Account]:
        data = self._request_json("GET", "/api/accounts")
        return [Account.from_dict(item) for item in data.get("items", [])]

    def list_events(self, after_id: int = 0, limit: int = 100) -> list[Event]:
        query = parse.urlencode({"after_id": after_id, "limit": limit})
        data = self._request_json("GET", f"/api/events?{query}")
        return [Event.from_dict(item) for item in data.get("items", [])]

    def list_logs(self, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        query = parse.urlencode({"after_id": after_id, "limit": limit})
        data = self._request_json("GET", f"/api/logs?{query}")
        return list(data.get("items", []))

    def get_settings(self) -> Settings:
        return Settings.from_dict(self._request_json("GET", "/api/settings"))

    def update_settings(self, listen_addr: str, webhook_url: str = "") -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/api/settings",
            {"listen_addr": listen_addr, "webhook_url": webhook_url},
        )

    def send_text(
        self,
        account_id: str,
        to_user_id: str,
        text: str,
        context_token: str = "",
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/api/messages/send-text",
            {
                "account_id": account_id,
                "to_user_id": to_user_id,
                "text": text,
                "context_token": context_token,
            },
        )

    def send_media(
        self,
        account_id: str,
        to_user_id: str,
        file_path: str,
        media_type: str = "",
        text: str = "",
        context_token: str = "",
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/api/messages/send-media",
            {
                "account_id": account_id,
                "to_user_id": to_user_id,
                "file_path": file_path,
                "type": media_type,
                "text": text,
                "context_token": context_token,
            },
        )

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self._request_bytes(method, path, payload)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _request_bytes(self, method: str, path: str, payload: dict[str, Any] | None = None) -> bytes:
        data: bytes | None = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            url=self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except error.HTTPError as exc:
            body = exc.read()
            message = self._extract_error_message(body) or f"HTTP {exc.code}"
            raise WcfLinkAPIError(exc.code, message, self._parse_error_body(body)) from exc
        except error.URLError as exc:
            raise WcfLinkAPIError(0, str(exc.reason)) from exc

    @staticmethod
    def _parse_error_body(body: bytes) -> Any:
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return body.decode("utf-8", errors="replace")

    @classmethod
    def _extract_error_message(cls, body: bytes) -> str:
        parsed = cls._parse_error_body(body)
        if isinstance(parsed, dict):
            value = parsed.get("error")
            if value:
                return str(value)
        if isinstance(parsed, str):
            return parsed
        return ""
