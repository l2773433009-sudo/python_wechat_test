from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import secrets
from pathlib import Path
from typing import Any
from urllib import error, parse, request


class ILinkClient:
    def __init__(self, channel_version: str, timeout: float = 45.0) -> None:
        self.channel_version = channel_version
        self.timeout = timeout

    def fetch_qrcode(self, base_url: str) -> dict[str, Any]:
        endpoint = f"{base_url.rstrip('/')}/ilink/bot/get_bot_qrcode?bot_type=3"
        req = request.Request(endpoint, method="GET")
        return self._do_json(req, token="", payload=None)

    def fetch_qrcode_status(self, base_url: str, qr_code: str) -> dict[str, Any]:
        endpoint = f"{base_url.rstrip('/')}/ilink/bot/get_qrcode_status?qrcode={parse.quote(qr_code)}"
        req = request.Request(endpoint, method="GET", headers={"iLink-App-ClientVersion": "1"})
        return self._do_json(req, token="", payload=None)

    def get_updates(self, base_url: str, token: str, get_updates_buf: str) -> dict[str, Any]:
        return self._post_json(
            f"{base_url.rstrip('/')}/ilink/bot/getupdates",
            token,
            {
                "get_updates_buf": get_updates_buf,
                "base_info": {"channel_version": self.channel_version},
            },
        )

    def send_text_message(self, base_url: str, token: str, to_user_id: str, text: str, context_token: str) -> None:
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": f"wcfLink-{secrets.randbits(63)}",
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": text}}],
                "context_token": context_token,
            },
            "base_info": {"channel_version": self.channel_version},
        }
        out = self._post_json(f"{base_url.rstrip('/')}/ilink/bot/sendmessage", token, payload)
        self._raise_if_send_failed(out)

    def get_upload_url(self, base_url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload["base_info"] = {"channel_version": self.channel_version}
        return self._post_json(f"{base_url.rstrip('/')}/ilink/bot/getuploadurl", token, payload)

    def upload_local_media(
        self,
        cdn_base_url: str,
        base_url: str,
        token: str,
        to_user_id: str,
        file_path: str,
        media_type: int,
    ) -> dict[str, Any]:
        plaintext = Path(file_path).read_bytes()
        raw_md5 = hashlib.md5(plaintext).hexdigest()
        aes_key = secrets.token_bytes(16)
        file_key = secrets.token_hex(16)
        ciphertext = encrypt_aes_ecb(plaintext, aes_key)
        upload_resp = self.get_upload_url(
            base_url,
            token,
            {
                "filekey": file_key,
                "media_type": media_type,
                "to_user_id": to_user_id,
                "rawsize": len(plaintext),
                "rawfilemd5": raw_md5,
                "filesize": len(ciphertext),
                "no_need_thumb": True,
                "aeskey": aes_key.hex(),
            },
        )
        upload_param = str(upload_resp.get("upload_param", ""))
        if not upload_param:
            raise RuntimeError("getuploadurl returned empty upload_param")
        download_param = self._upload_ciphertext_to_cdn(cdn_base_url, upload_param, file_key, ciphertext)
        return {
            "download_encrypted_query_param": download_param,
            "aes_key_hex": aes_key.hex(),
            "plain_size": len(plaintext),
            "cipher_size": len(ciphertext),
        }

    def send_image_message(
        self, base_url: str, token: str, to_user_id: str, context_token: str, text: str, uploaded: dict[str, Any]
    ) -> None:
        self._send_media_items(
            base_url,
            token,
            to_user_id,
            context_token,
            text,
            {
                "type": 2,
                "image_item": {
                    "media": {
                        "encrypt_query_param": uploaded["download_encrypted_query_param"],
                        "aes_key": base64.b64encode(uploaded["aes_key_hex"].encode("utf-8")).decode("ascii"),
                        "encrypt_type": 1,
                    },
                    "mid_size": uploaded["cipher_size"],
                },
            },
        )

    def send_video_message(
        self, base_url: str, token: str, to_user_id: str, context_token: str, text: str, uploaded: dict[str, Any]
    ) -> None:
        self._send_media_items(
            base_url,
            token,
            to_user_id,
            context_token,
            text,
            {
                "type": 5,
                "video_item": {
                    "media": {
                        "encrypt_query_param": uploaded["download_encrypted_query_param"],
                        "aes_key": base64.b64encode(uploaded["aes_key_hex"].encode("utf-8")).decode("ascii"),
                        "encrypt_type": 1,
                    },
                    "video_size": uploaded["cipher_size"],
                },
            },
        )

    def send_file_message(
        self,
        base_url: str,
        token: str,
        to_user_id: str,
        context_token: str,
        text: str,
        file_name: str,
        uploaded: dict[str, Any],
    ) -> None:
        self._send_media_items(
            base_url,
            token,
            to_user_id,
            context_token,
            text,
            {
                "type": 4,
                "file_item": {
                    "media": {
                        "encrypt_query_param": uploaded["download_encrypted_query_param"],
                        "aes_key": base64.b64encode(uploaded["aes_key_hex"].encode("utf-8")).decode("ascii"),
                        "encrypt_type": 1,
                    },
                    "file_name": file_name,
                    "len": str(uploaded["plain_size"]),
                },
            },
        )

    def send_voice_message(
        self,
        base_url: str,
        token: str,
        to_user_id: str,
        context_token: str,
        text: str,
        encode_type: int,
        uploaded: dict[str, Any],
    ) -> None:
        self._send_media_items(
            base_url,
            token,
            to_user_id,
            context_token,
            text,
            {
                "type": 3,
                "voice_item": {
                    "media": {
                        "encrypt_query_param": uploaded["download_encrypted_query_param"],
                        "aes_key": base64.b64encode(uploaded["aes_key_hex"].encode("utf-8")).decode("ascii"),
                        "encrypt_type": 1,
                    },
                    "encode_type": encode_type,
                    "text": "",
                },
            },
        )

    def download_message_media(self, cdn_base_url: str, item: dict[str, Any]) -> tuple[bytes, str, str]:
        item_type = int(item.get("type", 0))
        if item_type == 2:
            image_item = item.get("image_item") or {}
            media = image_item.get("media") or {}
            aes_key = media.get("aes_key", "")
            if image_item.get("aeskey"):
                aes_key = base64.b64encode(str(image_item["aeskey"]).encode("utf-8")).decode("ascii")
            buf = self._download_cdn_media(cdn_base_url, str(media.get("encrypt_query_param", "")), aes_key)
            mime = detect_mime(buf, ".jpg")
            return buf, "image" + extension_from_mime(mime, ".jpg"), mime
        if item_type == 3:
            voice_item = item.get("voice_item") or {}
            media = voice_item.get("media") or {}
            buf = self._download_cdn_media(cdn_base_url, str(media.get("encrypt_query_param", "")), str(media.get("aes_key", "")))
            return buf, "voice.silk", "audio/silk"
        if item_type == 4:
            file_item = item.get("file_item") or {}
            media = file_item.get("media") or {}
            file_name = str(file_item.get("file_name") or "file.bin")
            buf = self._download_cdn_media(cdn_base_url, str(media.get("encrypt_query_param", "")), str(media.get("aes_key", "")))
            return buf, file_name, detect_mime(buf, Path(file_name).suffix)
        if item_type == 5:
            video_item = item.get("video_item") or {}
            media = video_item.get("media") or {}
            buf = self._download_cdn_media(cdn_base_url, str(media.get("encrypt_query_param", "")), str(media.get("aes_key", "")))
            return buf, "video.mp4", "video/mp4"
        raise RuntimeError(f"unsupported media item type {item_type}")

    def _send_media_items(
        self,
        base_url: str,
        token: str,
        to_user_id: str,
        context_token: str,
        text: str,
        media_item: dict[str, Any],
    ) -> None:
        items: list[dict[str, Any]] = []
        if text.strip():
            items.append({"type": 1, "text_item": {"text": text}})
        items.append(media_item)
        for item in items:
            payload = {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": f"wcfLink-{secrets.randbits(63)}",
                    "message_type": 2,
                    "message_state": 2,
                    "item_list": [item],
                    "context_token": context_token,
                },
                "base_info": {"channel_version": self.channel_version},
            }
            out = self._post_json(f"{base_url.rstrip('/')}/ilink/bot/sendmessage", token, payload)
            self._raise_if_send_failed(out)

    def _post_json(self, endpoint: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        req = request.Request(endpoint, data=payload, method="POST")
        return self._do_json(req, token=token, payload=payload)

    def _do_json(self, req: request.Request, token: str, payload: bytes | None) -> dict[str, Any]:
        req.add_header("Content-Type", "application/json")
        req.add_header("AuthorizationType", "ilink_bot_token")
        req.add_header("X-WECHAT-UIN", random_wechat_uin())
        if payload is not None:
            req.add_header("Content-Length", str(len(payload)))
        if token.strip():
            req.add_header("Authorization", f"Bearer {token.strip()}")
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except error.HTTPError as exc:
            raw = exc.read()
            raise RuntimeError(f"ilink http {exc.code}: {raw.decode('utf-8', errors='replace')}") from exc
        except error.URLError as exc:
            raise RuntimeError(str(exc.reason)) from exc
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _upload_ciphertext_to_cdn(self, cdn_base_url: str, upload_param: str, file_key: str, ciphertext: bytes) -> str:
        endpoint = (
            f"{cdn_base_url.rstrip('/')}/upload?encrypted_query_param={parse.quote(upload_param)}&filekey={parse.quote(file_key)}"
        )
        req = request.Request(endpoint, data=ciphertext, method="POST", headers={"Content-Type": "application/octet-stream"})
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
                download_param = resp.headers.get("x-encrypted-param", "")
        except error.HTTPError as exc:
            raise RuntimeError(f"cdn upload http {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        if not download_param.strip():
            raise RuntimeError("cdn upload response missing x-encrypted-param")
        return download_param

    def _download_cdn_media(self, cdn_base_url: str, encrypted_query_param: str, aes_key_base64: str) -> bytes:
        endpoint = f"{cdn_base_url.rstrip('/')}/download?encrypted_query_param={parse.quote(encrypted_query_param)}"
        req = request.Request(endpoint, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except error.HTTPError as exc:
            raise RuntimeError(f"cdn download http {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
        if not aes_key_base64.strip():
            return raw
        return decrypt_aes_ecb(raw, parse_aes_key(aes_key_base64))

    @staticmethod
    def _raise_if_send_failed(payload: dict[str, Any]) -> None:
        ret = int(payload.get("ret", 0) or 0)
        err_code = int(payload.get("errcode", 0) or 0)
        if ret == 0 and err_code == 0:
            return
        err_msg = str(payload.get("errmsg") or "sendmessage returned non-zero status")
        raise RuntimeError(f"{err_msg} (ret={ret} errcode={err_code})")


def random_wechat_uin() -> str:
    return base64.b64encode(os.urandom(8)).decode("ascii")


def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
    cipher = _new_aes_cipher(key)
    block_size = 16
    padding = block_size - len(plaintext) % block_size
    padded = plaintext + bytes([padding]) * padding
    return b"".join(cipher.encrypt(padded[i : i + block_size]) for i in range(0, len(padded), block_size))


def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
    if len(ciphertext) % 16 != 0:
        raise RuntimeError(f"ciphertext size {len(ciphertext)} is not a multiple of block size")
    cipher = _new_aes_cipher(key)
    raw = b"".join(cipher.decrypt(ciphertext[i : i + 16]) for i in range(0, len(ciphertext), 16))
    padding = raw[-1]
    if padding <= 0 or padding > 16 or raw[-padding:] != bytes([padding]) * padding:
        raise RuntimeError("invalid PKCS7 padding")
    return raw[:-padding]


def parse_aes_key(aes_key_base64: str) -> bytes:
    decoded = base64.b64decode(aes_key_base64)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and all(chr(b) in "0123456789abcdefABCDEF" for b in decoded):
        return bytes.fromhex(decoded.decode("ascii"))
    raise RuntimeError(f"unexpected aes_key length {len(decoded)}")


def _new_aes_cipher(key: bytes) -> Any:
    try:
        from Crypto.Cipher import AES
    except ImportError as exc:
        raise RuntimeError("media encryption requires installing the 'pycryptodome' dependency") from exc
    return AES.new(key, AES.MODE_ECB)


def detect_mime(buf: bytes, fallback_ext: str) -> str:
    guessed, _ = mimetypes.guess_type(f"dummy{fallback_ext}")
    if guessed:
        return guessed
    return "application/octet-stream"


def extension_from_mime(mime: str, fallback: str) -> str:
    return mimetypes.guess_extension(mime) or fallback
