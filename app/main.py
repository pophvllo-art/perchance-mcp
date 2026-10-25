"""Entry point. One ASGI app serves BOTH:
  * MCP  -> /mcp          (streamable HTTP)
  * REST -> /v1/...       (OpenAI-compatible images API)

Both are protected by the same API key.
"""

import contextlib
import os
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from . import config, storage
from .auth import APIKeyMiddleware
from .browser import get_session
from .http_app import images, models, status
from .mcp_app import mcp


async def health(request):
    session = get_session()
    ready = session.ready
    return JSONResponse({
        "service": "perchance-mcp",
        "status": "ok" if ready else "warming up",
        "browser": "ready" if ready else "starting",
        "auth": "enabled" if config.API_KEY else "DISABLED",
    })


async def serve_image(request):
    name = os.path.basename(request.path_params["filename"])
    path = storage.path_for(name)
    if not os.path.isfile(path):
        return JSONResponse({"error": {"message": "not found"}}, status_code=404)
    with open(path, "rb") as fh:
        raw = fh.read()
    return Response(
        raw,
        media_type="image/png" if name.endswith(".png") else "image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@contextlib.asynccontextmanager
async def lifespan(app):
    """Two things must be started before we serve traffic:
      1. the MCP session manager's task group (mounting the MCP app inside
         ours does NOT run its lifespan, so we start it ourselves)
      2. the browser, which takes a while to boot. We boot it in the
         background so the HTTP server is up immediately and /health can
         report "warming up" while it finishes.
    """
    async with mcp.session_manager.run():
        session = get_session()
        await session.start_background()
        try:
            yield
        finally:
            await session.stop()


def build_app() -> Starlette:
    storage.cleanup()
    mcp_app = mcp.streamable_http_app()
    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/status", status),
            Route("/v1/models", models),
            Route("/v1/images/generations", images, methods=["POST"]),
            Route("/images/{filename}", serve_image),
            Mount("/", app=mcp_app),
        ],
        lifespan=lifespan,
    )
    if config.API_KEY:
        app = APIKeyMiddleware(  # type: ignore[assignment]
            app, config.API_KEY, allow_query=config.ALLOW_QUERY_KEY
        )
    return app


def main() -> None:
    if not config.API_KEY:
        print("WARNING: PERCHANCE_API_KEY is not set - the server is OPEN.", flush=True)
    else:
        print(f"API key auth is ON (key length {len(config.API_KEY)}).", flush=True)
    print(f"Listening on {config.HOST}:{config.PORT}", flush=True)
    print("  MCP  ->  /mcp", flush=True)
    print("  REST ->  /v1/images/generations", flush=True)
    uvicorn.run(
        build_app(),
        host=config.HOST,
        port=config.PORT,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
