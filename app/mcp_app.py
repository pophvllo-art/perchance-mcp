"""The MCP surface. One tool: generate_image.

It returns a list of MCP content blocks (text + image) so the picture is both
visible to the human AND readable by the model.
"""

import asyncio
import os

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import config
from .browser import BrowserError, get_session
from .images import build_blocks

PUBLIC_URL = (os.environ.get("PUBLIC_URL") or "").rstrip("/")


def _build_transport_security() -> TransportSecuritySettings:
    """The MCP SDK rejects any Host header that is not localhost, which makes
    every request fail with "Invalid Host header" the moment you put the
    server behind a public domain and a reverse proxy.

    Two ways out, and we use both:

    1. PUBLIC_URL tells the SDK your real hostname, so it can allow it.
       The SDK does an EXACT string match on the Host header, so we register
       the bare host *and* a "host:*" wildcard for when a proxy appends a
       port.

    2. If an API key is configured we turn the check off entirely. It is
       redundant there: the API key middleware wraps the whole app and has
       already rejected every unauthenticated request before the SDK's Host
       check ever runs. The check exists to stop a malicious web page from
       driving a browser at a *localhost* MCP server; against a public,
       key-authenticated endpoint it is pure friction.

    Set PERCHANCE_DISABLE_DNS_REBINDING_PROTECTION=1 to force option 2.
    """
    flag = (os.environ.get("PERCHANCE_DISABLE_DNS_REBINDING_PROTECTION") or "").lower()
    forced_off = flag in ("1", "true", "yes", "on")
    forced_on = flag in ("0", "false", "no", "off")

    if forced_off or (config.API_KEY and not forced_on):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

    def _register(raw: str) -> None:
        host = raw.split("//")[-1].split("/")[0].strip()
        if not host:
            return
        bare = host.split(":")[0]
        for item in (host, bare):
            if item and item not in hosts:
                hosts.append(item)
        for item in (f"{bare}:*",):
            if item not in hosts:
                hosts.append(item)
        for item in (f"https://{bare}", f"http://{bare}"):
            if item not in origins:
                origins.append(item)

    if PUBLIC_URL:
        _register(PUBLIC_URL)

    extra = (os.environ.get("PERCHANCE_ALLOWED_HOSTS") or "").strip()
    for item in extra.split(","):
        if item.strip():
            _register(item)

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


mcp = FastMCP(
    "Perchance_Image_Generator",
    transport_security=_build_transport_security(),
)


def _resolve_size(value: str) -> str:
    if not value:
        return config.DEFAULT_RESOLUTION
    v = str(value).strip().lower()
    named = {
        "s": "768x768", "square": "768x768", "768x768": "768x768",
        "ssm": "512x512", "512x512": "512x512",
        "p": "512x768", "portrait": "512x768", "512x768": "512x768",
        "l": "768x512", "landscape": "768x512", "768x512": "768x512",
    }
    return named.get(v, config.DEFAULT_RESOLUTION)


@mcp.tool()
async def generate_image(
    prompt: str,
    size: str = "768x768",
    seed: int = -1,
    guidance: int = 0,
    n: int = 1,
) -> list:
    """
    Create images.

    Args:
        prompt: What the image should show. Describe positively what should be in it.
        size: "768x768" (S/square), "512x512" (Ssm), "512x768" (P/portrait),
              "768x512" (L/landscape). Default "768x768".
        seed: -1 = random (default). A fixed integer reproduces a similar result.
        guidance: 0 = default (7). 1-30. 5-8 balanced, 9-13 literal, 14+ can look over-baked.
        n: How many images to make, 1-4. Default 1.
    """
    try:
        count = max(1, min(int(n), config.MAX_IMAGES))
    except Exception:
        count = 1
    try:
        seed_value = int(seed)
    except Exception:
        seed_value = -1
    try:
        guide_value = int(guidance)
    except Exception:
        guide_value = 0
    if guide_value <= 0:
        guide_value = config.DEFAULT_GUIDANCE

    resolution = _resolve_size(size)
    session = get_session()
    try:
        await session.wait_ready(config.READY_TIMEOUT)
    except BrowserError as exc:
        return [types.TextContent(type="text", text=f"Error: browser not ready: {exc}")]

    results = []
    for index in range(count):
        try:
            item = await session.generate(
                prompt=prompt,
                resolution=resolution,
                seed=seed_value,
                guidance=guide_value,
            )
        except BrowserError as exc:
            return [types.TextContent(type="text", text=f"Error: {exc}")]
        except Exception as exc:  # noqa: BLE001
            return [types.TextContent(type="text", text=f"Unexpected error: {exc}")]

        item["index"] = index
        item["resolution"] = resolution
        results.append(item)

    return build_blocks(results, base_url=PUBLIC_URL)


@mcp.tool()
async def health() -> str:
    """Report whether the generator can currently reach perchance."""
    session = get_session()
    info = await session.diagnose()
    lines = ["Perchance status:"]
    for key, value in info.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)
