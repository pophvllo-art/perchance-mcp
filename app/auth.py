"""API key protection for every HTTP surface (MCP + REST).

The key may be supplied three ways:
  - Authorization: Bearer <key>
  - X-API-Key: <key>
  - ?api_key=<key>   (needed by MCP clients that cannot set headers)

If PERCHANCE_API_KEY is empty the server starts with NO auth. That is only
acceptable on a private network; the container refuses to start in that mode
when PUBLIC_HOST is set.
"""

from starlette.types import ASGIApp, Receive, Scope, Send


def _extract_key(scope: Scope, allow_query: bool) -> str:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1")
               for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if headers.get("x-api-key"):
        return headers["x-api-key"].strip()
    if allow_query:
        query = scope.get("query_string", b"").decode("latin-1")
        for pair in query.split("&"):
            if pair.startswith("api_key="):
                return pair[len("api_key="):]
    return ""


class APIKeyMiddleware:
    """ASGI middleware that rejects requests without the right key."""

    def __init__(self, app: ASGIApp, api_key: str, allow_query: bool = True,
                 exempt_paths: tuple = ("/health", "/status")) -> None:
        self.app = app
        self.api_key = api_key
        self.allow_query = allow_query
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.api_key:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in self.exempt_paths):
            await self.app(scope, receive, send)
            return

        provided = _extract_key(scope, self.allow_query)
        if provided != self.api_key:
            await self._reject(send)
            return

        await self.app(scope, receive, send)

    async def _reject(self, send: Send) -> None:
        body = b'{"error":{"message":"invalid or missing API key","type":"invalid_request_error"}}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Bearer realm="perchance"'),
            ],
        })
        await send({"type": "http.response.body", "body": body})
