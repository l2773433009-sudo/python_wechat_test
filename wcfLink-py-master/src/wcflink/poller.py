from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .models import Account
from .store import Store
from .ilink_client import ILinkClient


class PollerManager:
    def __init__(
        self,
        store: Store,
        ilink_client: ILinkClient,
        logger: logging.Logger,
        on_message: Callable[[Account, dict[str, object]], None] | None = None,
    ) -> None:
        self.store = store
        self.ilink_client = ilink_client
        self.logger = logger
        self.on_message = on_message
        self._lock = threading.Lock()
        self._running: dict[str, threading.Event] = {}

    def start_enabled_accounts(self) -> None:
        for account in self.store.list_accounts():
            if account.enabled and account.token:
                self.start_account(account)

    def start_account(self, account: Account) -> None:
        with self._lock:
            if account.account_id in self._running:
                return
            stop_event = threading.Event()
            self._running[account.account_id] = stop_event
        thread = threading.Thread(target=self._run, args=(account, stop_event), daemon=True)
        thread.start()

    def stop_all(self) -> None:
        with self._lock:
            running = list(self._running.values())
            self._running.clear()
        for stop_event in running:
            stop_event.set()

    def stop_account(self, account_id: str) -> None:
        with self._lock:
            stop_event = self._running.pop(account_id, None)
        if stop_event is not None:
            stop_event.set()

    def lookup_context_token(self, account_id: str, peer_user_id: str) -> str:
        try:
            return self.store.get_peer_context(account_id, peer_user_id).context_token
        except LookupError:
            return ""

    def _run(self, account: Account, stop_event: threading.Event) -> None:
        log = self.logger.getChild(f"poller.{account.account_id}")
        current = account
        backoff = 2.0
        log.info("poller started")
        try:
            while not stop_event.is_set():
                try:
                    payload = self.ilink_client.get_updates(current.base_url, current.token, current.get_updates_buf)
                except Exception as exc:
                    self.store.update_account_poll_state(current.account_id, current.get_updates_buf, "error", str(exc))
                    log.error("getupdates failed: %s", exc)
                    if stop_event.wait(backoff):
                        return
                    backoff = min(backoff * 2, 30.0)
                    continue

                backoff = 2.0
                current.get_updates_buf = str(payload.get("get_updates_buf") or current.get_updates_buf)
                ret = int(payload.get("ret", 0) or 0)
                err_code = int(payload.get("errcode", 0) or 0)
                status = "connected"
                err_text = ""
                if ret != 0 or err_code != 0:
                    status = "warning"
                    err_text = str(payload.get("errmsg") or "getupdates returned non-zero status")
                self.store.update_account_poll_state(current.account_id, current.get_updates_buf, status, err_text)

                for message in list(payload.get("msgs") or []):
                    msg = dict(message)
                    if int(msg.get("message_type", 0) or 0) != 1:
                        continue
                    try:
                        if self.on_message is None:
                            self.store.save_inbound_message(current.account_id, msg, "", "", "")
                        else:
                            self.on_message(current, msg)
                    except Exception as exc:
                        log.error("save inbound event failed: %s", exc)

                try:
                    current = self.store.get_account(current.account_id)
                except LookupError:
                    return

                delay = 0.0 if int(payload.get("longpolling_timeout_ms", 0) or 0) > 0 else 1.0
                if delay > 0 and stop_event.wait(delay):
                    return
        finally:
            with self._lock:
                self._running.pop(account.account_id, None)
            log.info("poller stopped")
