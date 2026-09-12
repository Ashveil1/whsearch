from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from whsearch.domain import Document, Passage


class HtmlExtractor:
    """Extracts readable HTML into a stable Document/Passage model."""

    _remove = ("script", "style", "noscript", "template", "svg", "nav", "footer", "form")

    def extract(
        self, url: str, html: str, *, published_at: datetime | None = None
    ) -> Document:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(self._remove):
            tag.decompose()
        title = _text(soup.title) or url
        root = soup.find("main") or soup.find("article") or soup.body or soup
        headings: list[str] = []
        blocks: list[str] = []
        for node in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote"]):
            text = _clean(node.get_text(" ", strip=True))
            if not text:
                continue
            if node.name and node.name.startswith("h"):
                headings.append(text)
                continue
            blocks.append(text)
        if not blocks:
            fallback = _clean(root.get_text(" ", strip=True))
            blocks = [fallback] if fallback else []
        if sum(len(b) for b in blocks) < 200:
            # Degraded/JS-heavy pages: meta descriptions often survive when the
            # body is just a mount point. Keyless and dependency-free.
            meta = _meta_description(soup)
            if meta and all(meta not in b for b in blocks):
                blocks.append(meta)
        passages = tuple(
            Passage(text=text, index=index, section=headings[-1] if headings else None)
            for index, text in enumerate(blocks)
        )
        content = "\n\n".join(p.text for p in passages)
        canonical = _canonical_url(soup, url)
        return Document(
            url=url,
            title=title,
            content=content,
            passages=passages,
            canonical_url=canonical,
            published_at=published_at,
        )


def _text(node: object) -> str:
    return node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _canonical_url(soup: BeautifulSoup, url: str) -> str | None:
    node = soup.find("link", rel=lambda value: value and "canonical" in value)
    href = node.get("href") if node else None
    return urljoin(url, href) if isinstance(href, str) and href else None


def _meta_description(soup: BeautifulSoup) -> str:
    for attr, value in (
        ("property", "og:description"),
        ("name", "description"),
        ("name", "twitter:description"),
    ):
        node = soup.find("meta", attrs={attr: value})
        content = node.get("content", "") if node else ""
        if isinstance(content, str):
            cleaned = _clean(content)
            if len(cleaned) >= 40:
                return cleaned
    return ""
