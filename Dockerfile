# ─────────────────────────────────────────────────────────────────────────────
# One container: the API + a Chromium that solves Cloudflare/Turnstile.
# Same container == same egress IP, which Cloudflare requires.
# Peak RAM ~600-800 MB. Fits Cloady's 1 GB free tier.
#
# Base is pinned to an exact Debian bookworm tag, and every apt package below
# was verified against the bookworm package index (note: `libasound2`, NOT
# `libasound2t64` -- the t64 name only exists in trixie and Ubuntu 24.04).
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12.9-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    PERCHANCE_BROWSER_DIR=/data/browser \
    PERCHANCE_IMAGE_DIR=/data/images \
    PERCHANCE_USE_XVFB=1 \
    PERCHANCE_DISPLAY=:99

WORKDIR /srv

# Chromium's runtime libraries + Xvfb for a virtual display.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl xvfb fonts-liberation \
      libasound2 \
      libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
      libcairo2 libcups2 libdbus-1-3 libdrm2 libgbm1 libglib2.0-0 \
      libgtk-3-0 libnspr4 libnss3 \
      libpango-1.0-0 libpangocairo-1.0-0 \
      libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxext6 \
      libxfixes3 libxkbcommon0 libxrandr2 libxss1 libxcursor1 libxi6 libxtst6 \
      libdumbnet1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# patchright ships its own patched Chromium build.
RUN patchright install chromium

COPY app ./app
COPY start.sh ./start.sh
RUN chmod +x ./start.sh && mkdir -p /data/browser /data/images

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["./start.sh"]
