# perchance-mcp

[![CI](https://github.com/pophvllo-art/perchance-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/pophvllo-art/perchance-mcp/actions/workflows/ci.yml)

A self-hosted image generator that speaks **both** MCP and the OpenAI images API.

| Endpoint | Use it for |
|---|---|
| `POST /mcp` | MCP clients (Claude Desktop, Claude Code, Zed, this chat app, ...) |
| `POST /v1/images/generations` | Anything that speaks the OpenAI images API (OpenWebUI, LM Studio, ComfyUI, your own scripts) |
| `GET /health` | Uptime checks. No auth. |
| `GET /status` | Deep diagnostics: browser state, user key, ad code. |

One container. One API key. Both surfaces are protected by it.

---

## 1. Why this needs a browser (read this before you try to "optimise" it)

Perchance has no public API. This speaks the same protocol the official embed
page uses, reverse engineered from `image-generation.perchance.org/embed`:

| Step | Endpoint | Notes |
|---|---|---|
| 1 | `GET perchance.org/api/getAccessCodeForAdPoweredStuff` | Returns 64 hex chars as plain text. **Works with a plain HTTP client** (verified). |
| 2 | `GET image-generation.perchance.org/api/verifyUser?browserId=..&token=..` | Needs a **Turnstile token**. |
| 3 | `POST .../api/createTicket` | body `{"kind","generatorName"}` |
| 4 | `POST .../api/generate` | body `{"prompt","seed","resolution","guidanceScale",..}` |
| 5 | image bytes | data URL in the response, or an `imageId` to fetch |

### The finding that decides the architecture

Calling step 2 without a token gives you:

```json
{"status": "failed_verification", "reason": "token_required"}
```

A Turnstile token can only be minted by **executing the Turnstile widget in a
real browser**. No amount of TLS-fingerprint impersonation (`curl_cffi`,
`tls-client`, ...) gets you there. Verified directly.

The obvious next idea is "put a Cloudflare solver next to the API". That does
not work either, and this is worth knowing:

> **Cloudflare's `cf_clearance` cookie is bound to the IP that solved it.**
> Verified by taking a clearance cookie produced on IP A and replaying it from
> IP B: **HTTP 403**.

So a solver on another host, another container or another Cloud account hands
you a cookie that is worthless to you.

**Therefore: one browser, in this container, on this IP.** It solves the
challenge and then makes the API calls itself. No solver, no key handoff, no
IP problem. That is the whole design.

### Memory

Chromium with `--single-process` and swiftshader peaks around **600-800 MB**.
Cloady's free tier gives **1 GB**, so it fits, but it is the tightest part of
the project. If it gets OOM-killed, drop `n` to 1 and lower the resolution.

---

## 2. Repository layout

```
perchance-mcp/
├── app/
│   ├── config.py       all settings, every one read from an env var
│   ├── auth.py         the API key middleware
│   ├── browser.py      Chromium session: cloudflare/Turnstile + generation
│   ├── storage.py      writes images to disk
│   ├── images.py       raw bytes -> MCP image content blocks
│   ├── mcp_app.py      the MCP tool
│   ├── http_app.py     the OpenAI-compatible REST endpoints
│   └── main.py         assembles both into one ASGI app
├── Dockerfile          Chromium + Xvfb + the API, one container
├── docker-compose.yml  local development
├── start.sh            entrypoint
├── .env.example        every setting, documented
└── tests/
```

---

## 3. Run it locally first (10 minutes)

Prove it works before touching GitHub.

```bash
git clone https://github.com/YOUR-USERNAME/perchance-mcp.git
cd perchance-mcp

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
# paste that into PERCHANCE_API_KEY= inside .env

docker compose up --build
```

The first boot takes a minute: Chromium downloads, Xvfb starts, and the
browser solves Cloudflare.

Check it:

```bash
curl http://localhost:8080/health
# {"service":"perchance-mcp","status":"ok","browser":"ready","auth":"enabled"}

curl http://localhost:8080/status
# browser state, whether the user key was found, etc.

curl -X POST http://localhost:8080/v1/images/generations \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a red circle on green","size":"768x768","n":1}'
```

---

## 4. Push it to GitHub (the part you asked about)

Three commands. Everything else is clicking.

### 4a. Create the repo

1. Go to <https://github.com/new>
2. **Repository name**: `perchance-mcp`
3. **Private** — tick it.
4. Do **not** tick "Add a README", "Add .gitignore", or "Choose a license".
5. **Create repository**.

### 4b. Send the code up

In a terminal, in the folder that has the files:

```bash
cd perchance-mcp

git init
git add .
git commit -m "Initial commit: Perchance MCP + OpenAI-compatible API"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/perchance-mcp.git
git push -u origin main
```

Git asks for a username and a **Personal Access Token**, not your password.
To make one:

1. GitHub -> avatar -> **Settings**
2. **Developer settings** -> **Personal access tokens** -> **Tokens (classic)**
3. **Generate new token** -> name `perchance`, 30 days, tick the **`repo`** box
4. Generate, copy the `ghp_...` string. You only see it once.

If `git push` says `Support for password authentication was removed`, that
means it wanted a token. Paste the `ghp_...` when it asks for a password.

### 4c. Check

Refresh the GitHub page. Your files should be there.

---

## 5. Deploy to Cloady

Cloady's free workspace allows **0.5 vCPU, 1 GB RAM, 5 GB SSD** and
**200 GB of traffic**, no card needed.

### 5a. Create the app

1. Sign in at <https://cloady.com>
2. **New app** -> **Connect GitHub** (read access to your repos)
3. Pick `perchance-mcp`, branch `main`
4. Region: **EU1** (Germany), **SIN1**, **USE1** or **USW1**

### 5b. Build

You have two options.

**Option A - build from the repo (simplest).** Cloady finds the `Dockerfile`
automatically. Nothing to change.

**Option B - deploy a prebuilt image.** A GitHub Actions workflow
(`.github/workflows/ci.yml`) builds the image on every push and publishes it to
GitHub Container Registry as:

```
ghcr.io/pophvllo-art/perchance-mcp:latest
```

It is also tagged with the commit SHA (`...:0f0ea2a`), so you can pin an
exact build. The image is about **545 MB compressed** (Chromium is most of
it) and exposes port `8080`.

GHCR packages are **private by default**, so flip it to public once:

- GitHub -> your profile -> **Packages** -> `perchance-mcp` -> **Package
  settings** -> **Change visibility** -> **Public**

or from the API, with a token that has the `write:packages` scope:

```bash
curl -X PATCH \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d '{"visibility":"public"}' \
  https://api.github.com/users/pophvllo-art/packages/container/perchance-mcp
```

Then in Cloady pick **Deploy a Docker image** and use that reference.

Either way the result is the same container. Option A is one less moving
part; Option B is faster to redeploy because the build already happened.

### 5c. Resources

| Setting | Value |
|---|---|
| Port | `8080` |
| CPU | `0.5` |
| RAM | `1 GB` |
| Disk | `5 GB` |

### 5d. Environment variables

In the service's **Environment** tab:

```
PERCHANCE_API_KEY = <your 32+ char key>
PUBLIC_URL = https://<the-url-cloady-gives-you>
```

`PUBLIC_URL` matters: the MCP SDK blocks any `Host` header that is not
`localhost`, so without it every MCP request fails with

```
Error while sending message: Streamable HTTP error: Invalid Host header
```

Setting `PUBLIC_URL` to your exact hostname fixes it. If a proxy appends a
port to the `Host` header, the code registers a wildcard for that too.

If you ever cannot know the URL in advance, set
`PERCHANCE_DISABLE_DNS_REBINDING_PROTECTION=1` instead. The server also turns
this check off automatically whenever an API key is configured, because the
API key middleware has already rejected every unauthenticated request by then
- the Host check exists to protect *localhost* MCP servers from a malicious
web page, and against a public key-authenticated endpoint it is pure
friction.

> **Do not put the key in GitHub.** Put it in Cloady's environment tab. If you
> ever commit it by accident it is in your git history forever — change the
> key.

### 5e. Deploy and watch

Hit **Deploy**, open the **Logs** tab. You want:

```
API key auth is ON (key length 43).
Listening on 0.0.0.0:8080
Xvfb started
loading embed page (warmup)...
Cloudflare passed
browser ready
```

Cloady gives you a free TLS certificate, so the URL is `https://...`.

---

### 5f. Which option do I pick?

| | Option A (build from repo) | Option B (prebuilt image) |
|---|---|---|
| Setup | none | flip the package public |
| First deploy | builds on Cloady (5-10 min) | pulls a 545 MB image (2-3 min) |
| Every redeploy | rebuilds | seconds, just a new tag |
| Needs GHCR public | no | yes |

Start with **Option A**. It is one less thing to get wrong, and you can move
to Option B later without changing a line of code.

## 6. Verify it is alive

```bash
# 1. health (no auth)
curl https://YOUR_URL/health

# 2. deep diagnostics
curl https://YOUR_URL/status -H "Authorization: Bearer YOUR_KEY"

# 3. a real image
curl -X POST https://YOUR_URL/v1/images/generations \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a lighthouse in a storm","size":"768x768"}'
```

`/status` tells you exactly where it is broken:

| `/status` says | Meaning | Fix |
|---|---|---|
| `browser: ready`, `user_key: ok` | fully working | - |
| `browser: starting` | still booting | wait, check the logs |
| `user_key: missing` | Cloudflare/Turnstile did not clear | check the logs for "Cloudflare passed" |
| `error: ...` with 403 | the container's IP is flagged | change region, or add a volume so the profile persists |
| `browser: not ready` + OOM in the logs | out of RAM | lower `n`, use `512x512`, or go one tier up |

---

## 7. Connect it to an MCP client

### In a URL (works everywhere)

```
https://YOUR_URL/mcp?api_key=YOUR_KEY
```

### With headers (better, the key stays out of logs)

```json
{
  "mcpServers": {
    "perchance": {
      "url": "https://YOUR_URL/mcp",
      "headers": { "Authorization": "Bearer YOUR_KEY" }
    }
  }
}
```

### Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "perchance": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://YOUR_URL/mcp?api_key=YOUR_KEY"]
    }
  }
}
```

The tool is called `generate_image`.

---

## 8. Using it as a plain image API

Same shape as OpenAI's images endpoint, so most clients work unchanged:

```bash
curl -X POST https://YOUR_URL/v1/images/generations \
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "model": "perchance",
        "prompt": "a watercolour fox in a birch forest",
        "size": "768x768",
        "n": 2,
        "seed": -1,
        "guidance": 7
      }'
```

```json
{
  "created": 1792930000,
  "data": [
    {
      "url": "https://YOUR_URL/images/abc123....png",
      "revised_prompt": "a watercolour fox in a birch forest",
      "seed": 42,
      "resolution": "768x768",
      "guidance": 7
    }
  ]
}
```

Add `"response_format": "b64_json"` to get the bytes inline instead of a URL.

**OpenWebUI**: Admin -> Settings -> Connections -> OpenAI -> base URL
`https://YOUR_URL/v1`, paste the key, then pick the `perchance` model.

---

## 9. Gotchas worth knowing

- **The MCP image block is the single most important detail.** The tool
  returns a real MCP `image` content block, so the model can actually *see*
  the picture. Do not "simplify" it to a markdown link, or the image stays
  visible to the human while becoming invisible to the model.
- **Seed is "close", not "exact".** The same seed gives a very similar image
  but not a byte-identical one. The engine is not bit-deterministic.
- **WebP.** The endpoint can return WebP. `Pillow` is in `requirements.txt`,
  so it is converted to PNG automatically.
- **Persistent profile.** `/data/browser` holds the Chromium profile, so the
  Cloudflare clearance survives restarts. On the free tier there is no
  persistent volume, so each boot re-solves. If a region starts 403-ing,
  changing region is the quickest fix.
- **Gallery.** Set `PERCHANCE_GALLERY_NAME` to save to your perchance gallery
  and get permanent CDN links. Blank = skip.
- **One at a time.** Perchance queues one generation per user key; the
  browser session serialises requests with a lock.
- **The first request after a cold start is the slow one.** The embed page
  has to solve Turnstile before it will generate anything, and that can take
  30-90 seconds. The server does that warm-up during boot, so it is already
  paid for by the time you call the tool - but if the container has just
  restarted, give it a minute before your first call or your MCP client may
  hit its own timeout first.
- **The embed runs in a persistent iframe.** We keep one iframe alive and
  navigate it between prompts, so the Chromium profile keeps its clearance
  and the userKey stays valid. Recreating the iframe every time would force
  a fresh Turnstile solve on every single image.

## 10. Licence

MIT. See `LICENSE`.
