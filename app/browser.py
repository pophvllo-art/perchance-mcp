"""The browser session that does the actual work.

Why a browser at all? Because perchance's /api/verifyUser answers

    {"status":"failed_verification","reason":"token_required"}

unless you pass a Turnstile token, and that token can only be produced by
executing the Turnstile widget. A plain HTTP client (even one impersonating
Chrome's TLS fingerprint) can get the *ad access code* just fine, but it
cannot mint a Turnstile token.

So: one Chromium, inside this same container, sharing this same egress IP.
That also sidesteps the whole "cf_clearance is IP-bound" problem, because the
browser that solves the challenge is the browser that makes the API calls.

The flow mirrors the official embed page:
  1. load the embed page -> it solves Cloudflare + Turnstile in-page
  2. read the resulting userKey out of localStorage
  3. drive the embed iframe with our prompt
  4. it posts the finished image back to us as a data URL
"""

import asyncio
import base64
import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from . import config

try:
    from patchright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


# ── JS that runs inside the page ────────────────────────────────────────────
JS_EMBED_WRAPPER = """
(params) => {
    window.__genResult = null;
    window.addEventListener('message', function(e) {
        if(e.source === document.getElementById('genFrame').contentWindow && e.data && e.data.type === 'finished') {
            window.__genResult = { dataUrl: e.data.dataUrl, seedUsed: e.data.seedUsed };
        }
    });

    let hashData = {
        prompt: params.prompt,
        seed: params.seed,
        resolution: params.resolution,
        guidanceScale: params.guidance,
        negativePrompt: params.negative || '',
        saveChannel: params.channel || '',
        saveTitle: params.prompt || '',
        saveDescription: params.negative || '',
        requestId: Math.random().toString(),
        iframeId: 'genFrame',
        hideGalleryButtons: true,
    };
    let embedUrl = 'https://image-generation.perchance.org/embed#' + encodeURIComponent(JSON.stringify(hashData));

    let f = document.createElement('iframe');
    f.id = 'genFrame';
    f.src = embedUrl;
    f.style.cssText = 'position:fixed;top:0;left:0;width:640px;height:640px;border:0;';
    document.body.appendChild(f);
    return 'fired';
}
"""

JS_CHECK_STATUS = """() => {
    let out = {};
    out.userKey = localStorage['userKey-0'] || '';
    out.adAccessCode = localStorage.adAccessCode || '';
    // newer builds namespace the key: generation-v2:<browserId>:userKey-0
    try {
        for (let i = 0; i < localStorage.length; i++) {
            let k = localStorage.key(i);
            if (k && /userKey-0$/.test(k) && !out.userKey) {
                out.userKey = localStorage.getItem(k) || '';
                out.userKeyStorageKey = k;
            }
        }
    } catch(e) {}
    out.url = location.href.substring(0, 80);
    let wc = document.getElementById('waitingContentEl');
    if (wc) out.waitingContent = wc.innerText.substring(0, 200);
    return out;
}"""

JS_SAVE_TO_GALLERY = """async (cfg) => {
    let img = document.getElementById('resultImgEl') || document.querySelector('img[src^="data:image"]');
    if (!img) return { status: 'error_no_img' };
    let src = img.getAttribute('src') || '';
    let base64Data = src.split(',')[1] || '';
    if (!base64Data) return { status: 'error_no_base64' };
    let fileExt = cfg.ext || (src.indexOf('data:image/png') === 0 ? 'png' : 'jpeg');
    let meta = {};
    try { meta = JSON.parse(decodeURIComponent(window.location.hash.slice(1))); } catch(e) {}
    let url = '/api/saveImageToGallery?channel=' + encodeURIComponent(meta.saveChannel || cfg.channel || '')
        + '&subChannel=' + encodeURIComponent(cfg.galleryName)
        + '&fileExtension=' + encodeURIComponent(fileExt)
        + '&title=' + encodeURIComponent(meta.saveTitle || cfg.title || '')
        + '&description=' + encodeURIComponent(meta.saveDescription || cfg.description || '')
        + '&__cacheBust=' + Math.random();
    return await fetch(url, { method: 'POST', body: base64Data })
        .then(r => r.json())
        .catch(e => ({ status: 'network_error: ' + e }));
}"""


class BrowserError(RuntimeError):
    pass


class BrowserSession:
    """Owns the Chromium instance and the single page we drive."""

    def __init__(self) -> None:
        self.page = None
        self.context = None
        self.playwright = None
        self.xvfb = None
        self.ready = False
        self._ready_event = asyncio.Event()
        self._boot_error: Optional[str] = None
        self._lock = asyncio.Lock()
        self._user_key: str = ""
        self._ad_code: str = ""

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def start_background(self) -> None:
        """Boot the browser without blocking the HTTP server."""
        asyncio.create_task(self._boot())

    async def _boot(self) -> None:
        try:
            await self.start()
            self._ready_event.set()
        except Exception as exc:  # noqa: BLE001
            self._boot_error = str(exc)
            self._ready_event.set()
            print(f"browser failed to start: {exc}", flush=True)

    async def wait_ready(self, timeout: int = 180) -> None:
        """Block until the browser is up (or the boot failed)."""
        if self.ready:
            return
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise BrowserError(
                f"the browser did not finish booting within {timeout}s"
            ) from exc
        if not self.ready:
            raise BrowserError(self._boot_error or "the browser failed to start")

    async def start(self) -> None:
        if async_playwright is None:
            raise BrowserError(
                "patchright is not installed. Run: pip install patchright && patchright install chromium"
            )
        os.makedirs(config.BROWSER_DIR, exist_ok=True)

        if not os.environ.get("DISPLAY") and config.USE_XVFB:
            try:
                subprocess.run(["rm", "-f", "/tmp/.X99-lock"], check=False)
                self.xvfb = subprocess.Popen(
                    ["Xvfb", config.DISPLAY, "-screen", "0", "1280x720x24"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                os.environ["DISPLAY"] = config.DISPLAY
                await asyncio.sleep(1)
                print("Xvfb started", flush=True)
            except Exception as exc:
                print(f"Xvfb unavailable ({exc}) - using the existing DISPLAY", flush=True)

        self.playwright = await async_playwright().start()
        args = [
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--use-gl=swiftshader", "--enable-webgl",
            "--window-size=1280,720",
            "--single-process",
            "--disable-extensions", "--disable-plugins",
            "--disable-background-networking", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding",
            "--js-flags=--max-old-space-size=256",
        ]
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=config.BROWSER_DIR,
            headless=False,
            args=args,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self._load_embed(warmup=True)
        self.ready = True
        self._ready_event.set()
        print("browser ready", flush=True)

    async def stop(self) -> None:
        for name, obj in (("context", self.context), ("playwright", self.playwright)):
            try:
                if obj is None:
                    continue
                if name == "context":
                    await obj.close()
                else:
                    await obj.stop()
            except Exception:
                pass
        if self.xvfb is not None:
            try:
                self.xvfb.terminate()
            except Exception:
                pass
        self.ready = False

    async def _load_embed(self, warmup: bool = False) -> None:
        url = (
            "https://image-generation.perchance.org/embed#%7B%22prompt%22%3A%22warmup%22%7D"
        )
        print(f"loading embed page ({'warmup' if warmup else 'reload'})...", flush=True)
        try:
            await self.page.goto(url, timeout=60000, wait_until="domcontentloaded")
        except Exception as exc:
            print(f"  goto error: {exc}", flush=True)
        for _ in range(40):
            await asyncio.sleep(1)
            try:
                title = (await self.page.title()).lower()
                if "just a moment" not in title:
                    print("  Cloudflare passed", flush=True)
                    return
            except Exception:
                pass
        print("  WARNING: Cloudflare did not clear in time", flush=True)

    # ── identity ─────────────────────────────────────────────────────────────
    async def refresh_identity(self) -> Tuple[str, str]:
        """Return (userKey, adAccessCode) from the page."""
        for _ in range(30):
            try:
                status = await self.page.evaluate(JS_CHECK_STATUS)
            except Exception:
                await asyncio.sleep(2)
                continue
            key = (status or {}).get("userKey") or ""
            ad = (status or {}).get("adAccessCode") or ""
            if key:
                self._user_key = key
            if ad:
                self._ad_code = ad
            if key and ad:
                return key, ad
            await asyncio.sleep(2)
        raise BrowserError(
            "could not obtain a userKey from the browser. The page said: "
            f"{str(status)[:300]}"
        )

    @property
    def user_key(self) -> str:
        return self._user_key

    # ── generation ───────────────────────────────────────────────────────────
    async def generate(
        self,
        prompt: str,
        resolution: str = "768x768",
        seed: int = -1,
        guidance: int = 7,
        negative: str = "",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        timeout = timeout or config.GEN_TIMEOUT
        async with self._lock:
            return await self._generate_locked(prompt, resolution, seed, guidance, negative, timeout)

    async def _generate_locked(
        self, prompt, resolution, seed, guidance, negative, timeout
    ) -> Dict[str, Any]:
        try:
            await self.page.set_content(
                "<!doctype html><html><head><meta charset='utf-8'><title>gen</title></head>"
                "<body style='margin:0'></body></html>"
            )
        except Exception as exc:
            raise BrowserError(f"could not prepare the page: {exc}") from exc

        try:
            await self.page.evaluate(
                JS_EMBED_WRAPPER,
                {
                    "prompt": prompt,
                    "resolution": resolution,
                    "seed": seed,
                    "guidance": guidance,
                    "negative": negative or "",
                    "channel": config.SAVE_CHANNEL,
                },
            )
        except Exception as exc:
            raise BrowserError(f"could not start the embed frame: {exc}") from exc

        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(1)
            try:
                result = await self.page.evaluate("() => window.__genResult")
            except Exception:
                continue
            if not result:
                continue
            data_url = result.get("dataUrl") or ""
            if not data_url.startswith("data:"):
                raise BrowserError("the embed frame returned an empty result")
            head, _, b64 = data_url.partition(",")
            try:
                raw = base64.b64decode(b64)
            except Exception as exc:
                raise BrowserError(f"the embed frame returned undecodable data: {exc}") from exc
            mime = head[5:].split(";")[0] or "image/png"
            return {
                "bytes": raw,
                "mime": mime,
                "seed": result.get("seedUsed", seed),
                "data_url": data_url,
            }

        raise BrowserError(f"generation timed out after {timeout}s")

    # ── gallery ──────────────────────────────────────────────────────────────
    async def save_to_gallery(
        self, ext: str, prompt: str, negative: str = "", gallery: str = ""
    ) -> Tuple[bool, Dict[str, Any]]:
        gallery = gallery or config.GALLERY_NAME
        if not gallery:
            return False, {"status": "no_gallery_configured"}
        frame = None
        try:
            for f in self.page.frames:
                if "image-generation.perchance.org" in (f.url or ""):
                    frame = f
                    break
        except Exception:
            pass
        if frame is None:
            return False, {"status": "no_embed_frame"}

        try:
            await frame.evaluate(
                "(n) => { try { localStorage.subChannelName = n; } catch(e) {} }", gallery
            )
        except Exception:
            pass
        cfg = {
            "channel": config.SAVE_CHANNEL,
            "galleryName": gallery,
            "ext": ext,
            "title": (prompt or "")[:400],
            "description": (negative or "")[:1000],
        }
        try:
            res = await frame.evaluate(JS_SAVE_TO_GALLERY, cfg)
        except Exception as exc:
            return False, {"status": "error", "error": str(exc)}
        return (res or {}).get("status") == "success", (res or {})

    # ── diagnostics ──────────────────────────────────────────────────────────
    async def diagnose(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {"browser": "ready" if self.ready else "not ready"}
        if not self.ready:
            if self._boot_error:
                info["error"] = self._boot_error
            return info
        try:
            status = await self.page.evaluate(JS_CHECK_STATUS)
            info["user_key"] = "ok" if (status or {}).get("userKey") else "missing"
            info["ad_access_code"] = "ok" if (status or {}).get("adAccessCode") else "missing"
            info["page"] = str((status or {}).get("waitingContent") or "")[:120]
        except Exception as exc:
            info["error"] = str(exc)[:200]
        return info


_session: Optional[BrowserSession] = None


def get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session
