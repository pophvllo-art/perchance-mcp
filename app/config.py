"""Central configuration. Everything is read from environment variables so the
same image works locally and on Cloady without code changes."""

import os


def _env_str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


# ── auth ────────────────────────────────────────────────────────────────────
# Leave EMPTY to disable auth (dev only). On a public host this MUST be set.
API_KEY = _env_str("PERCHANCE_API_KEY")
# Allow the key to travel as a query param, needed by MCP clients that can't
# set custom headers on a streamable-HTTP connection.
ALLOW_QUERY_KEY = _env_bool("PERCHANCE_ALLOW_QUERY_KEY", True)

# ── network ─────────────────────────────────────────────────────────────────
HOST = _env_str("HOST", "0.0.0.0")
PORT = _env_int("PORT", 8080)

# ── browser ─────────────────────────────────────────────────────────────────
# The Chromium profile persists here so the Cloudflare / Turnstile clearance
# survives restarts. Mount it as a volume on a paid plan, or accept a fresh
# solve on every boot.
BROWSER_DIR = _env_str("PERCHANCE_BROWSER_DIR", "/data/browser")
DISPLAY = _env_str("PERCHANCE_DISPLAY", ":99")
USE_XVFB = _env_bool("PERCHANCE_USE_XVFB", True)
# How long a tool call waits for the browser to finish booting.
READY_TIMEOUT = _env_int("PERCHANCE_READY_TIMEOUT", 180)

# ── perchance upstream ──────────────────────────────────────────────────────
PERCHANCE_ORIGIN = _env_str("PERCHANCE_ORIGIN", "https://perchance.org")
PERCHANCE_GEN_ORIGIN = _env_str(
    "PERCHANCE_GEN_ORIGIN", "https://image-generation.perchance.org"
)
# The generator page used for the ad-access-code handshake.
PERCHANCE_GEN_URL = _env_str(
    "PERCHANCE_GEN_URL", "https://perchance.org/stable-diffusion-ai"
)
GENERATOR_NAME = _env_str("PERCHANCE_GENERATOR_NAME", "stable-diffusion-ai")
# "kind" sent to /api/createTicket
TICKET_KIND = _env_str("PERCHANCE_TICKET_KIND", "image")
# The version token the site puts on /api/generate
GENERATE_VERSION = _env_str("PERCHANCE_GENERATE_VERSION", "9b43eec2")

# Persistent identity for this deployment (32 hex chars).
BROWSER_ID = _env_str("PERCHANCE_BROWSER_ID")
# Optional: a userKey obtained ahead of time (64 hex).
PERCHANCE_USER_KEY = _env_str("PERCHANCE_USER_KEY")

# ── generation defaults ─────────────────────────────────────────────────────
DEFAULT_RESOLUTION = _env_str("PERCHANCE_DEFAULT_RESOLUTION", "768x768")
DEFAULT_GUIDANCE = _env_int("PERCHANCE_DEFAULT_GUIDANCE", 7)
MAX_IMAGES = _env_int("PERCHANCE_MAX_IMAGES", 4)
GEN_TIMEOUT = _env_int("PERCHANCE_GEN_TIMEOUT", 180)

# Save generated images to the perchance gallery under this name.
GALLERY_NAME = _env_str("PERCHANCE_GALLERY_NAME", "")
SAVE_CHANNEL = _env_str("PERCHANCE_SAVE_CHANNEL", "")

# Where to write generated images so the MCP tool can inline them.
IMAGE_DIR = _env_str("PERCHANCE_IMAGE_DIR", "/data/images")
IMAGE_TTL = _env_int("PERCHANCE_IMAGE_TTL", 3600)

# Verbose logging.
DEBUG = _env_bool("PERCHANCE_DEBUG", False)
