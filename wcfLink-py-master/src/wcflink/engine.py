from __future__ import annotations

import logging
import time

from .config import Config, load
from .ilink_client import ILinkClient
from .models import Account, Event, LogEntry, LoginSession, Settings, VersionInfo
from .poller import PollerManager
from .server import APIServer
from .service import RuntimeState, Service
from .store import Store
from .version import current


class Engine:
    def __init__(self, cfg: Config | None = None, logger: logging.Logger | None = None) -> None:
        self.cfg = cfg or load()
        self.logger = logger or logging.getLogger("wcflink")
        self.store = Store(self.cfg.db_path)
        self.ilink_client = ILinkClient(self.cfg.channel_version, self.cfg.poll_timeout + 10.0)
        self.runtime = RuntimeState(self.cfg)
        self.pollers = PollerManager(self.store, self.ilink_client, self.logger)
        self.service = Service(self.cfg, self.logger, self.store, self.ilink_client, self.runtime, self.pollers)
        self.pollers.on_message = self.service.handle_inbound_message
        self.server = APIServer(self.service, self.logger, self.cfg.listen_addr)
        self._started = False

    def start_background(self) -> None:
        if self._started:
            return
        self.store.ping()
        self.pollers.start_enabled_accounts()
        self.server.start()
        self._started = True

    def run(self) -> None:
        self.start_background()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("shutdown requested")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.pollers.stop_all()
        self.server.shutdown()
        self.store.close()

    def start_login(self, base_url: str = "") -> LoginSession:
        return self.service.start_login(base_url)

    def get_login_status(self, session_id: str) -> LoginSession:
        return self.service.get_login_status(session_id)

    def get_login_session(self, session_id: str) -> LoginSession:
        return self.service.get_login_session(session_id)

    def list_accounts(self) -> list[Account]:
        return self.service.list_accounts()

    def list_events(self, after_id: int = 0, limit: int = 100) -> list[Event]:
        return self.service.list_events(after_id, limit)

    def list_logs(self, after_id: int = 0, limit: int = 100) -> list[LogEntry]:
        return self.service.list_logs(after_id, limit)

    def get_settings(self) -> Settings:
        return self.service.get_settings()

    def update_settings(self, settings: Settings) -> Settings:
        return self.service.update_settings(settings)

    def send_text(self, account_id: str, to_user_id: str, text: str, context_token: str = "") -> None:
        self.service.send_text(account_id, to_user_id, text, context_token)

    def send_media(
        self,
        account_id: str,
        to_user_id: str,
        media_type: str,
        file_path: str,
        text: str = "",
        context_token: str = "",
    ) -> None:
        self.service.send_media(account_id, to_user_id, media_type, file_path, text, context_token)

    def logout_account(self, account_id: str) -> None:
        self.service.logout_account(account_id)


def load_config() -> Config:
    return load()


def current_version() -> VersionInfo:
    return current()
