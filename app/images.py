"""Helpers for turning raw image bytes into MCP content blocks.

The important bit: an MCP tool must return an ImageContent block for the
model to actually SEE the picture. Returning a markdown ![](url) string inside
a TextContent block renders for the human but gives the model zero pixels.
"""

import base64
from typing import Any, Dict, List

import mcp.types as types

from . import storage

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)


def sniff_mime(raw: bytes) -> str:
    for sig, mime in _MAGIC:
        if raw.startswith(sig):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def to_png(raw: bytes) -> bytes | None:
    """WebP -> PNG so every client can render it. Needs Pillow."""
    try:
        from io import BytesIO

        from PIL import Image as PILImage

        buf = BytesIO()
        PILImage.open(BytesIO(raw)).convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


def build_blocks(results: List[Dict[str, Any]], base_url: str = "") -> List[types.ContentBlock]:
    """One text block + one image block per generated image."""
    blocks: List[types.ContentBlock] = []
    for item in results:
        raw = item["bytes"]
        mime = item.get("mime") or sniff_mime(raw)
        if mime == "image/webp":
            png = to_png(raw)
            if png:
                raw, mime = png, "image/png"

        name = storage.save(raw, "png" if mime == "image/png" else "jpg")
        url = f"{base_url}/images/{name}" if base_url else f"/images/{name}"

        lines = [
            f"Image {item.get('index', 0) + 1}/{len(results)}",
            f"- url: {url}",
            f"- size: {item.get('resolution', 'unknown')}",
            f"- seed: {item.get('seed', 'unknown')}",
        ]
        blocks.append(types.TextContent(type="text", text="\n".join(lines)))
        blocks.append(
            types.ImageContent(
                type="image",
                data=base64.b64encode(raw).decode(),
                mimeType=mime,
            )
        )
    return blocks
