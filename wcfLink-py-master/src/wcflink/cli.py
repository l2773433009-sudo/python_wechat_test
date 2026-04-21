from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .client import WcfLinkClient
from .config import load
from .engine import Engine, current_version
from .exceptions import WcfLinkAPIError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wcflink", description="Python implementation of wcfLink")
    parser.add_argument("--base-url", default="http://127.0.0.1:17890", help="wcfLink service base URL")

    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve")
    serve.add_argument("--listen-addr", default=None)
    serve.add_argument("--state-dir", default=None)
    serve.add_argument("--media-dir", default=None)
    serve.add_argument("--db-path", default=None)
    serve.add_argument("--upstream-base-url", default=None)
    serve.add_argument("--cdn-base-url", default=None)
    serve.add_argument("--channel-version", default=None)
    serve.add_argument("--poll-timeout", type=float, default=None)
    serve.add_argument("--webhook-url", default=None)
    serve.add_argument("--log-level", default=None)

    sub.add_parser("version")
    sub.add_parser("api-version")
    sub.add_parser("accounts")

    events = sub.add_parser("events")
    events.add_argument("--after-id", type=int, default=0)
    events.add_argument("--limit", type=int, default=100)

    logs = sub.add_parser("logs")
    logs.add_argument("--after-id", type=int, default=0)
    logs.add_argument("--limit", type=int, default=100)

    login = sub.add_parser("login")
    login_sub = login.add_subparsers(dest="login_command", required=True)

    login_start = login_sub.add_parser("start")
    login_start.add_argument("--upstream-base-url", default="", help="Override iLink upstream base URL")

    login_status = login_sub.add_parser("status")
    login_status.add_argument("session_id")

    login_qr = login_sub.add_parser("qr")
    login_qr.add_argument("session_id")
    login_qr.add_argument("-o", "--output", required=True, help="PNG output path")

    send_text = sub.add_parser("send-text")
    send_text.add_argument("--account-id", required=True)
    send_text.add_argument("--to-user-id", required=True)
    send_text.add_argument("--text", required=True)
    send_text.add_argument("--context-token", default="")

    send_media = sub.add_parser("send-media")
    send_media.add_argument("--account-id", required=True)
    send_media.add_argument("--to-user-id", required=True)
    send_media.add_argument("--file-path", required=True)
    send_media.add_argument("--type", default="")
    send_media.add_argument("--text", default="")
    send_media.add_argument("--context-token", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "serve":
        return run_server(args)

    try:
        match args.command:
            case "version":
                print_json(current_version().to_dict())
            case "api-version":
                client = WcfLinkClient(args.base_url)
                print_json(client.version().to_dict())
            case "accounts":
                client = WcfLinkClient(args.base_url)
                print_json([item.to_dict() for item in client.list_accounts()])
            case "events":
                client = WcfLinkClient(args.base_url)
                print_json([item.to_dict() for item in client.list_events(args.after_id, args.limit)])
            case "logs":
                client = WcfLinkClient(args.base_url)
                print_json(client.list_logs(args.after_id, args.limit))
            case "login":
                client = WcfLinkClient(args.base_url)
                return handle_login(args, client)
            case "send-text":
                client = WcfLinkClient(args.base_url)
                print_json(
                    client.send_text(
                        account_id=args.account_id,
                        to_user_id=args.to_user_id,
                        text=args.text,
                        context_token=args.context_token,
                    )
                )
            case "send-media":
                client = WcfLinkClient(args.base_url)
                print_json(
                    client.send_media(
                        account_id=args.account_id,
                        to_user_id=args.to_user_id,
                        file_path=args.file_path,
                        media_type=args.type,
                        text=args.text,
                        context_token=args.context_token,
                    )
                )
            case _:
                parser.error("unsupported command")
    except WcfLinkAPIError as exc:
        sys.stderr.write(f"wcfLink API error: {exc}\n")
        return 1

    return 0


def handle_login(args: argparse.Namespace, client: WcfLinkClient) -> int:
    match args.login_command:
        case "start":
            print_json(client.start_login(base_url=args.upstream_base_url).to_dict())
        case "status":
            print_json(client.get_login_status(args.session_id).to_dict())
        case "qr":
            output = Path(args.output)
            output.write_bytes(client.get_login_qr(args.session_id))
            print(str(output))
        case _:
            raise ValueError("unsupported login command")
    return 0


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run_server(args: argparse.Namespace) -> int:
    cfg = load().with_overrides(
        listen_addr=args.listen_addr,
        state_dir=args.state_dir,
        media_dir=args.media_dir,
        db_path=args.db_path,
        default_base_url=args.upstream_base_url,
        cdn_base_url=args.cdn_base_url,
        channel_version=args.channel_version,
        poll_timeout=args.poll_timeout,
        webhook_url=args.webhook_url,
        log_level=args.log_level,
    )
    if args.state_dir is not None:
        if args.media_dir is None:
            cfg = cfg.with_overrides(media_dir=str(Path(args.state_dir) / "media"))
        if args.db_path is None:
            cfg = cfg.with_overrides(db_path=str(Path(args.state_dir) / "wcflink.db"))
        cfg = cfg.with_overrides(settings_path=str(Path(args.state_dir) / "settings.json"))

    logging.basicConfig(
        level=getattr(logging, str(cfg.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("wcflink")
    logger.info("starting wcflink on %s", cfg.listen_addr)
    logger.info("version %s", current_version().version)
    engine = Engine(cfg=cfg, logger=logger)
    engine.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
