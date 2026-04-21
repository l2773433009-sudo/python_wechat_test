from __future__ import annotations


def generate_qrcode_png(content: str) -> bytes:
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError("qrcode support requires installing the 'qrcode[pil]' dependency") from exc
    image = qrcode.make(content)
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
