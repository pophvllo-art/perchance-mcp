"""Integration-ish tests: the MCP tool really returns image blocks, and a
public Host header is accepted (the MCP SDK blocks unknown hosts by default,
which would break every request once deployed behind a domain)."""

import asyncio
import base64
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("PERCHANCE_API_KEY", "test-key")
os.environ.setdefault("PERCHANCE_IMAGE_DIR", "/tmp/perchance-test-images")

from app import config as app_config  # noqa: E402
from app import mcp_app  # noqa: E402


def _reload():
    """app.config caches env vars at import time, so reload it too."""
    importlib.reload(app_config)
    importlib.reload(mcp_app)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeSession:
    ready = True

    async def wait_ready(self, timeout=180):
        return None

    async def generate(self, **kwargs):
        return {
            "bytes": PNG,
            "mime": "image/png",
            "seed": 1234,
            "index": 0,
            "resolution": kwargs.get("resolution", "768x768"),
        }


def test_tool_returns_image_block():
    original = mcp_app.get_session
    mcp_app.get_session = lambda: FakeSession()
    try:
        blocks = asyncio.run(mcp_app.generate_image("a red circle", size="S", n=1))
    finally:
        mcp_app.get_session = original

    kinds = [b.type for b in blocks]
    assert kinds == ["text", "image"], kinds
    image = blocks[1]
    assert image.mimeType == "image/png"
    assert base64.b64decode(image.data) == PNG
    assert "url" in blocks[0].text
    print("tool returns a real image block OK")


def test_multiple_images():
    original = mcp_app.get_session
    mcp_app.get_session = lambda: FakeSession()
    try:
        blocks = asyncio.run(mcp_app.generate_image("x", n=3))
    finally:
        mcp_app.get_session = original
    assert [b.type for b in blocks] == ["text", "image"] * 3
    print("n=3 produces three image blocks OK")


def test_public_host_allowed():
    """With NO API key the protection stays on and must allow the real host."""
    saved_key = os.environ.pop("PERCHANCE_API_KEY", None)
    os.environ["PUBLIC_URL"] = "https://perchance-example.cloady.io"
    try:
        _reload()
        ts = mcp_app.mcp.settings.transport_security
        assert ts.enable_dns_rebinding_protection is True
        assert "perchance-example.cloady.io" in ts.allowed_hosts, ts.allowed_hosts
        assert "perchance-example.cloady.io:*" in ts.allowed_hosts, ts.allowed_hosts
        assert "https://perchance-example.cloady.io" in ts.allowed_origins, ts.allowed_origins
        print("public host is allowed while protection is on OK")
    finally:
        del os.environ["PUBLIC_URL"]
        if saved_key is not None:
            os.environ["PERCHANCE_API_KEY"] = saved_key
        importlib.reload(mcp_app)


def test_host_check_off_when_api_key_set():
    """With an API key the check is redundant (auth already ran) and is off."""
    os.environ["PERCHANCE_API_KEY"] = "test-key"
    os.environ.pop("PUBLIC_URL", None)
    try:
        _reload()
        ts = mcp_app.mcp.settings.transport_security
        assert ts.enable_dns_rebinding_protection is False
        print("host check is auto-disabled when an API key is set OK")
    finally:
        _reload()


def test_error_is_graceful():
    class Broken:
        ready = True

        async def wait_ready(self, timeout=180):
            return None

        async def generate(self, **kwargs):
            raise RuntimeError("upstream is on fire")

    original = mcp_app.get_session
    mcp_app.get_session = lambda: Broken()
    try:
        blocks = asyncio.run(mcp_app.generate_image("x"))
    finally:
        mcp_app.get_session = original
    assert len(blocks) == 1 and blocks[0].type == "text"
    assert "upstream is on fire" in blocks[0].text
    print("errors degrade to a text block OK")


if __name__ == "__main__":
    test_tool_returns_image_block()
    test_multiple_images()
    test_public_host_allowed()
    test_host_check_off_when_api_key_set()
    test_error_is_graceful()
    print("\nALL INTEGRATION TESTS PASSED")
