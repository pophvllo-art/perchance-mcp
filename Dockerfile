# ─────────────────────────────────────────────────────────────────────────────
# One container: the API + a Chromium that solves Cloudflare/Turnstile.
# Same container == same egress IP, which Cloudflare requires.
# Peak RAM ~600-800 MB. Fits Cloady's 1 GB free tier.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    PERCHANCE_BROWSER_DIR=/data/browser \
    PERCHANCE_IMAGE_DIR=/data/images \
    PERCHANCE_USE_XVFB=1 \
    PERCHANCE_DISPLAY=:99

WORKDIR /srv

# Chromium + the shared libraries it needs + Xvfb for a virtual display.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl \
      xvfb \
      chromium \
      fonts-liberation \
      libasound2t64 \
      libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 \
      libcups2 libdbus-1-3 libdrm2 libgbm1 \
      libgtk-3-0 libnspr4 libnss3 \
      libpango-1.0-0 libpangocairo-1.0-0 \
      libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 \
      libxfixes3 libxkbcommon0 libxrandr2 \
      libdumbnet1 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# patchright ships its own patched chromium build
RUN patchright install chromium \
 && patchright install-deps chromium || true

COPY app ./app
COPY start.sh ./start.sh
RUN chmod +x ./start.sh && mkdir -p /data/browser /data/images

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["./start.sh"]
