from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path


DEFAULT_LISTEN_ADDR = "127.0.0.1:17890"
DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_CHANNEL_VERSION = "2.0.1"
DEFAULT_POLL_TIMEOUT = 35.0


@dataclass(slots=True)
class Config:
    listen_addr: str
    state_dir: str
    media_dir: str
    db_path: str
    settings_path: str
    default_base_url: str
    cdn_base_url: str
    channel_version: str
    poll_timeout: float
    log_level: str
    open_browser: bool
    webhook_url: str

    def with_overrides(self, **overrides: object) -> "Config":
        normalized = {key: value for key, value in overrides.items() if value is not None}
        return replace(self, **normalized)


def default_state_dir() -> str:
    return str(Path.cwd() / "data")


def load_file_settings(path: str) -> dict[str, str]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_file_settings(path: str, listen_addr: str, webhook_url: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"listen_addr": listen_addr, "webhook_url": webhook_url}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load() -> Config:
    state_dir = os.getenv("WCFLINK_STATE_DIR", default_state_dir())
    media_dir = os.getenv("WCFLINK_MEDIA_DIR", str(Path(state_dir) / "media"))
    db_path = os.getenv("WCFLINK_DB_PATH", str(Path(state_dir) / "wcflink.db"))
    settings_path = str(Path(state_dir) / "settings.json")
    file_settings = load_file_settings(settings_path)

    return Config(
        listen_addr=os.getenv("WCFLINK_LISTEN_ADDR", file_settings.get("listen_addr", DEFAULT_LISTEN_ADDR)),
        state_dir=state_dir,
        media_dir=media_dir,
        db_path=db_path,
        settings_path=settings_path,
        default_base_url=os.getenv("WCFLINK_BASE_URL", DEFAULT_BASE_URL),
        cdn_base_url=os.getenv("WCFLINK_CDN_BASE_URL", DEFAULT_CDN_BASE_URL),
        channel_version=os.getenv("WCFLINK_CHANNEL_VERSION", DEFAULT_CHANNEL_VERSION),
        poll_timeout=float(os.getenv("WCFLINK_POLL_TIMEOUT", str(DEFAULT_POLL_TIMEOUT))),
        log_level=os.getenv("WCFLINK_LOG_LEVEL", "INFO"),
        open_browser=_env_bool("WCFLINK_OPEN_BROWSER", False),
        webhook_url=os.getenv("WCFLINK_WEBHOOK_URL", file_settings.get("webhook_url", "")),
    )


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
