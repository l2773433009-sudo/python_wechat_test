from __future__ import annotations

import json
import logging
from dataclasses import is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib import parse

from .models import Account, Event, LogEntry, LoginSession, Settings, VersionInfo
from .qr import generate_qrcode_png
from .service import Service
from .version import current


class APIServer:
    def __init__(self, service: Service, logger: logging.Logger, listen_addr: str) -> None:
        host, port_text = listen_addr.rsplit(":", 1)
        self._server = ThreadingHTTPServer((host, int(port_text)), _make_handler(service, logger))
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _make_handler(service: Service, logger: logging.Logger):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path, _, query_string = self.path.partition("?")
            query = parse.parse_qs(query_string)
            try:
                if path == "/health/live" or path == "/health/ready":
                    self._write_json(200, {"ok": True, "timestamp": datetime.utcnow().isoformat() + "Z", "version": current()})
                    return
                if path == "/api/version":
                    self._write_json(200, current())
                    return
                if path == "/api/accounts/login/status":
                    session_id = query_value(query, "session_id")
                    self._write_json(200, service.get_login_status(session_id))
                    return
                if path == "/api/accounts/login/qr":
                    session_id = query_value(query, "session_id")
                    session = service.get_login_session(session_id)
                    if not session.qr_code_url:
                        raise ValueError("qr code url is empty")
                    payload = generate_qrcode_png(session.qr_code_url)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path == "/api/accounts":
                    self._write_json(200, {"items": service.list_accounts()})
                    return
                if path == "/api/events":
                    self._write_json(
                        200,
                        {"items": service.list_events(int(query.get("after_id", ["0"])[0]), int(query.get("limit", ["100"])[0]))},
                    )
                    return
                if path == "/api/logs":
                    self._write_json(
                        200,
                        {"items": service.list_logs(int(query.get("after_id", ["0"])[0]), int(query.get("limit", ["100"])[0]))},
                    )
                    return
                if path == "/api/settings":
                    self._write_json(200, service.get_settings())
                    return
                self._write_json(404, {"error": "not found"})
            except LookupError as exc:
                self._write_json(404, {"error": str(exc)})
            except ValueError as exc:
                self._write_json(400, {"error": str(exc)})
            except Exception as exc:
                logger.exception("request failed")
                self._write_json(500, {"error": str(exc)})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            try:
                payload = self._read_json()
                if path == "/api/accounts/login/start":
                    self._write_json(200, service.start_login(str(payload.get("base_url") or "")))
                    return
                if path == "/api/accounts/logout":
                    account_id = str(payload.get("account_id") or "")
                    if not account_id:
                        self._write_json(400, {"error": "account_id is required"})
                        return
                    service.logout_account(account_id)
                    self._write_json(200, {"ok": True})
                    return
                if path == "/api/settings":
                    settings = Settings.from_dict(payload)
                    if not settings.listen_addr.strip():
                        raise ValueError("listen_addr is required")
                    out = service.update_settings(settings)
                    self._write_json(200, {"settings": out, "restart_needed": True})
                    return
                if path == "/api/messages/send-text":
                    service.send_text(
                        str(payload.get("account_id") or ""),
                        str(payload.get("to_user_id") or ""),
                        str(payload.get("text") or ""),
                        str(payload.get("context_token") or ""),
                    )
                    self._write_json(200, {"ok": True})
                    return
                if path == "/api/messages/send-media":
                    service.send_media(
                        str(payload.get("account_id") or ""),
                        str(payload.get("to_user_id") or ""),
                        str(payload.get("type") or ""),
                        str(payload.get("file_path") or ""),
                        str(payload.get("text") or ""),
                        str(payload.get("context_token") or ""),
                    )
                    self._write_json(200, {"ok": True})
                    return
                self._write_json(404, {"error": "not found"})
            except LookupError as exc:
                self._write_json(404, {"error": str(exc)})
            except ValueError as exc:
                self._write_json(400, {"error": str(exc)})
            except Exception as exc:
                logger.exception("request failed")
                self._write_json(500, {"error": str(exc)})

        def log_message(self, format: str, *args: object) -> None:
            logger.debug("%s - %s", self.address_string(), format % args)

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length == 0:
                return {}
            raw = self.rfile.read(content_length)
            return json.loads(raw.decode("utf-8"))

        def _write_json(self, status: int, payload: Any) -> None:
            raw = json.dumps(serialize(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def serialize(value: Any) -> Any:
    if isinstance(value, (LoginSession, Account, Event, LogEntry, Settings, VersionInfo)):
        if isinstance(value, (LoginSession, Account)):
            return value.to_dict()
        return value.to_dict()
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if is_dataclass(value):
        return serialize(value.__dict__)
    return value


def query_value(query: dict[str, list[str]], key: str) -> str:
    value = query.get(key, [""])[0].strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value
