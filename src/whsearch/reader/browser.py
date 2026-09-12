from __future__ import annotations

import asyncio
import importlib
from typing import Any

from whsearch.observability import get_logger

_logger = get_logger("reader.browser")

_BLOCKED_TYPES = frozenset({"image", "font", "media"})


def _import_playwright() -> Any | None:
    """Import playwright lazily; None when the `js` extra is not installed."""
    try:
        module = importlib.import_module("playwright.async_api")
    except ImportError:
        return None
    return module.async_playwright


def is_browser_available() -> bool:
    return _import_playwright() is not None


class BrowserRenderer:
    """Optional L3 fallback: headless Chromium for JS-shell pages.

    Reuses one browser with a small page semaphore so low-memory
    machines never run many renderers at once. Every failure degrades
    to None — callers must always have a non-browser fallback.
    """

    _LAUNCH_ARGS = ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu")

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        max_pages: int = 2,
        executable_path: str | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self._timeout_ms = int(timeout_seconds * 1000)
        self._semaphore = asyncio.Semaphore(max_pages)
        self._lock = asyncio.Lock()
        self._executable_path = executable_path
        self._playwright: Any | None = None
        self._browser: Any | None = None

    async def render_text(self, url: str, *, user_agent: str) -> str | None:
        factory = _import_playwright()
        if factory is None:
            return None
        async with self._semaphore:
            try:
                browser = await self._ensure_browser(factory)
                page = await browser.new_page(user_agent=user_agent)
                try:
                    await page.route("**/*", _block_handler)
                    await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                    await page.wait_for_timeout(1200)
                    text = await page.inner_text("body", timeout=self._timeout_ms)
                finally:
                    await page.close()
            except Exception as exc:
                _logger.debug("browser render failed for %r: %s", url, exc)
                return None
        cleaned = " ".join((text or "").split())
        return cleaned or None

    async def _ensure_browser(self, factory: Any) -> Any:
        if self._browser is not None:
            return self._browser
        async with self._lock:
            if self._browser is not None:
                return self._browser
            playwright = await factory().__aenter__()
            self._playwright = playwright
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": list(self._LAUNCH_ARGS),
            }
            if self._executable_path:
                launch_kwargs["executable_path"] = self._executable_path
            self._browser = await playwright.chromium.launch(**launch_kwargs)
            return self._browser

    async def aclose(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                _logger.debug("browser close failed: %s", exc)
            self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.__aexit__(None, None, None)
            except Exception as exc:  # pragma: no cover - best-effort cleanup
                _logger.debug("playwright stop failed: %s", exc)
            self._playwright = None


async def _block_handler(route: Any) -> None:
    if route.request.resource_type in _BLOCKED_TYPES:
        await route.abort()
    else:
        await route.continue_()
