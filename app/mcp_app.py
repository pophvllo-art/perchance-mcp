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
    """The MCP SDK blocks any Host header that is not localhost, which would
    break every request once this is deployed behind a public domain. Add the
    real host, and allow turning the check off entirely via env var."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

    if PUBLIC_URL:
        host = PUBLIC_URL.split("//")[-1].split("/")[0]
        if host and host not in hosts:
            hosts.append(host)
            origins.append(f"https://{host}")
            origins.append(f"http://{host}")

    extra = (os.environ.get("PERCHANCE_ALLOWED_HOSTS") or "").strip()
    for item in extra.split(","):
        item = item.strip()
        if item:
            hosts.append(item)
            origins.append(f"https://{item}")

    disabled = (os.environ.get("PERCHANCE_DISABLE_DNS_REBINDING_PROTECTION") or "").lower()
    if disabled in ("1", "true", "yes", "on"):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

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
