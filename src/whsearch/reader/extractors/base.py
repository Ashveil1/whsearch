from __future__ import annotations

from typing import Protocol

from whsearch.domain import Document


class Extractor(Protocol):
    def extract(self, url: str, html: str) -> Document: ...
