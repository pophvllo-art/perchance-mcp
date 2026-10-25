"""Offline smoke tests. No network, no solver, no API key needed."""

import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("PERCHANCE_API_KEY", "test-key")
os.environ.setdefault("PERCHANCE_IMAGE_DIR", "/tmp/perchance-test-images")

from app.auth import APIKeyMiddleware  # noqa: E402
from app.images import build_blocks, sniff_mime  # noqa: E402
from app.mcp_app import _resolve_size  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_resolve_size():
    assert _resolve_size("S") == "768x768"
    assert _resolve_size("square") == "768x768"
    assert _resolve_size("Ssm") == "512x512"
    assert _resolve_size("portrait") == "512x768"
    assert _resolve_size("L") == "768x512"
    assert _resolve_size("nonsense") == "768x768"
    print("resolve_size OK")


def test_sniff_mime():
    assert sniff_mime(PNG) == "image/png"
    assert sniff_mime(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    print("sniff_mime OK")


def test_build_blocks():
    blocks = build_blocks([{"bytes": PNG, "mime": "image/png", "index": 0, "seed": 7}])
    assert len(blocks) == 2, blocks
    assert blocks[0].type == "text"
    assert blocks[1].type == "image"
    assert blocks[1].mimeType == "image/png"
    assert base64.b64decode(blocks[1].data) == PNG
    print("build_blocks OK")


def test_auth_middleware():
    sent = []

    async def app(scope, receive, send):
        sent.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = APIKeyMiddleware(app, "secret", allow_query=True)

    async def call(headers, query=b""):
        sent.clear()
        out = {}

        async def send(msg):
            out.update(msg)

        await mw(
            {"type": "http", "path": "/v1/images/generations",
             "headers": headers, "query_string": query},
            None, send,
        )
        return out

    good = [(b"authorization", b"Bearer secret")]
    bad = [(b"authorization", b"Bearer wrong")]

    assert asyncio.run(call(good))["status"] == 200
    assert asyncio.run(call(bad))["status"] == 401
    assert asyncio.run(call([], b"api_key=secret"))["status"] == 200
    assert asyncio.run(call([], b"api_key=nope"))["status"] == 401
    print("auth_middleware OK")


if __name__ == "__main__":
    test_resolve_size()
    test_sniff_mime()
    test_build_blocks()
    test_auth_middleware()
    print("\nALL SMOKE TESTS PASSED")
