"""OpenAI-compatible REST surface.

POST /v1/images/generations
    {"prompt": "...", "size": "768x768", "n": 1, "seed": -1, "guidance": 0}
    -> {"created": 1234, "data": [{"url": "https://.../images/<sha>.png", ...}]}

Also accepts response_format="b64_json" for clients that want the bytes
inline instead of a URL.
"""

import base64
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config, storage
from .browser import BrowserError, get_session


def _resolve_size(value: Any) -> str:
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


async def models(request: Request) -> JSONResponse:
    return JSONResponse({
        "object": "list",
        "data": [{"id": "perchance", "object": "model", "owned_by": "local"}],
    })


async def images(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": {"message": "invalid JSON", "type": "invalid_request_error"}},
            status_code=400,
        )

    prompt = body.get("prompt")
    if not prompt or not str(prompt).strip():
        return JSONResponse(
            {"error": {"message": "'prompt' is required", "type": "invalid_request_error"}},
            status_code=400,
        )

    try:
        n = int(body.get("n", body.get("count", 1)))
    except Exception:
        n = 1
    n = max(1, min(n, config.MAX_IMAGES))

    try:
        seed = int(body.get("seed", -1))
    except Exception:
        seed = -1

    try:
        guidance = int(body.get("guidance", body.get("guidance_scale", 0)) or 0)
    except Exception:
        guidance = 0
    if guidance <= 0:
        guidance = config.DEFAULT_GUIDANCE

    size = _resolve_size(body.get("size", body.get("shape")))
    fmt = body.get("response_format", "url")
    if fmt not in ("url", "b64_json"):
        fmt = "url"

    session = get_session()
    try:
        await session.wait_ready(config.READY_TIMEOUT)
    except BrowserError as exc:
        return JSONResponse(
            {"error": {"message": str(exc), "type": "server_error"}}, status_code=503
        )

    base = str(request.base_url).rstrip("/")
    data = []
    for index in range(n):
        try:
            item = await session.generate(
                prompt=str(prompt),
                resolution=size,
                seed=seed,
                guidance=guidance,
                negative=str(body.get("negative", "") or ""),
            )
        except BrowserError as exc:
            return JSONResponse(
                {"error": {"message": str(exc), "type": "server_error"}}, status_code=502
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": {"message": str(exc), "type": "server_error"}}, status_code=500
            )

        raw = item["bytes"]
        if fmt == "b64_json":
            data.append({
                "b64_json": base64.b64encode(raw).decode(),
                "revised_prompt": str(prompt),
                "seed": item.get("seed"),
                "resolution": size,
            })
            continue

        name = storage.save(raw, "png" if item["mime"] == "image/png" else "jpg")
        data.append({
            "url": f"{base}/images/{name}",
            "revised_prompt": str(prompt),
            "seed": item.get("seed"),
            "resolution": size,
            "guidance": guidance,
        })

    return JSONResponse({"created": int(time.time()), "data": data})


async def status(request: Request) -> JSONResponse:
    info = await get_session().diagnose()
    return JSONResponse({"service": "perchance-mcp", "ok": True, "details": info})
