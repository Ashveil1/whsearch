import asyncio
from collections.abc import Callable

import httpx
import pytest

from whsearch.exceptions import ReaderError
from whsearch.reader import ReaderService, RobotsPolicy
from whsearch.reader.browser import BrowserRenderer, _block_handler, is_browser_available


class FakeRoute:
    def __init__(self, resource_type: str) -> None:
        self.request = type("Request", (), {"resource_type": resource_type})()
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


class FakePage:
    def __init__(self, text: str = "", fail_goto: bool = False) -> None:
        self._text = text
        self._fail_goto = fail_goto
        self.closed = False

    async def route(self, pattern: str, handler: object) -> None:
        return None

    async def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:
        if self._fail_goto:
            raise RuntimeError("navigation failed")

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def inner_text(self, selector: str, timeout: int = 0) -> str:
        return self._text

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.closed = False

    async def new_page(self, user_agent: str = "") -> FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class FakeCM:
    def __init__(self, browser: FakeBrowser) -> None:
        self._browser = browser

    async def __aenter__(self) -> object:
        outer = self

        class PW:
            async def __getattr__(self, name: str) -> object:
                raise AttributeError(name)

        pw = PW()

        class Chromium:
            async def launch(self, headless: bool = True) -> FakeBrowser:
                return outer._browser

        pw.chromium = Chromium()  # type: ignore[attr-defined]
        return pw

    async def __aexit__(self, *args: object) -> None:
        return None


def _factory_for(browser: FakeBrowser) -> Callable[[], FakeCM]:
    def _factory() -> FakeCM:
        return FakeCM(browser)

    return _factory


def test_no_playwright_means_no_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("whsearch.reader.browser._import_playwright", lambda: None)
    assert is_browser_available() is False
    renderer = BrowserRenderer()
    assert asyncio.run(renderer.render_text("https://example.com/", user_agent="UA")) is None


def test_render_returns_cleaned_text(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = FakeBrowser(FakePage("  Hello   rendered  world  "))
    monkeypatch.setattr(
        "whsearch.reader.browser._import_playwright", lambda: _factory_for(browser)
    )
    renderer = BrowserRenderer()
    assert (
        asyncio.run(renderer.render_text("https://example.com/", user_agent="UA"))
        == "Hello rendered world"
    )


def test_render_failure_degrades_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = FakeBrowser(FakePage(fail_goto=True))
    monkeypatch.setattr(
        "whsearch.reader.browser._import_playwright", lambda: _factory_for(browser)
    )
    renderer = BrowserRenderer()
    assert asyncio.run(renderer.render_text("https://example.com/", user_agent="UA")) is None


def test_block_handler_aborts_media() -> None:
    async def _main() -> None:
        image = FakeRoute("image")
        await _block_handler(image)
        assert image.aborted is True
        text = FakeRoute("document")
        await _block_handler(text)
        assert text.continued is True

    asyncio.run(_main())


def test_renderer_validates_args() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        BrowserRenderer(timeout_seconds=0)
    with pytest.raises(ValueError, match="max_pages"):
        BrowserRenderer(max_pages=0)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


SHELL_HTML = "<html><head><title>Shell app</title></head><body><div id='root'></div></body></html>"


def _shell_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    return httpx.Response(200, headers={"content-type": "text/html"}, text=SHELL_HTML)


class StubBrowser:
    def __init__(self, text: str | None) -> None:
        self._text = text
        self.calls = 0
        self.closed = False

    async def render_text(self, url: str, user_agent: str = "") -> str | None:
        self.calls += 1
        return self._text

    async def aclose(self) -> None:
        self.closed = True


def test_reader_uses_browser_for_thin_pages() -> None:
    async def _main() -> None:
        async with _client(_shell_handler) as client:
            stub = StubBrowser(
                "Rendered body text that is comfortably long enough to keep. " * 5
            )
            service = ReaderService(client, RobotsPolicy(client, "t"), browser=stub)  # type: ignore[arg-type]
            document = await service.read("https://example.com/app")
            assert "Rendered body text" in document.content
            assert stub.calls == 1
            await service.aclose()
            assert stub.closed is True

    asyncio.run(_main())


LONG_HTML = """<html><head><title>Long article</title></head><body><article>
<p>This is a sufficiently long paragraph used to exercise the offline reader path.</p>
<p>A second paragraph keeps the extracted document comfortably above the minimum.</p>
<p>A third paragraph ensures the static text wins over any browser rendering.</p>
</article></body></html>"""


def test_reader_skips_browser_for_rich_pages() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=LONG_HTML)

    async def _main() -> None:
        async with _client(_handler) as client:
            stub = StubBrowser("Short.")
            service = ReaderService(client, RobotsPolicy(client, "t"), browser=stub)  # type: ignore[arg-type]
            document = await service.read("https://example.com/article")
            assert "sufficiently long paragraph" in document.content
            assert stub.calls == 0

    asyncio.run(_main())


def test_reader_empty_shell_without_browser_still_reader_error() -> None:
    async def _main() -> None:
        async with _client(_shell_handler) as client:
            service = ReaderService(client, RobotsPolicy(client, "t"))
            with pytest.raises(ReaderError, match="too short"):
                await service.read("https://example.com/app")
            await service.aclose()

    asyncio.run(_main())
