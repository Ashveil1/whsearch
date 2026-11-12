import asyncio

import pytest

from whsearch.agent import ResearchAgent
from whsearch.agent.relevance import has_answer_overlap
from whsearch.domain import Document, Passage, ResearchBudget, SearchQuery, SearchResult
from whsearch.search import SearchService


@pytest.mark.parametrize(
    ("question", "text", "expected"),
    [
        ("What is the orbital period of Saturn?", "The garden is sunny all year long.", False),
        ("What is the Copper telescope project?", "The project needs a coordinator.", False),
        (
            "What is the Copper telescope project?",
            "The Copper telescope project studies stars.",
            True,
        ),
        ("What is Python programming?", "Python is a programming language.", True),
        ("What is Python programming?", "Python is a large snake.", False),
        ("รถไฟฟ้าสายสีเขียวเปิดเมื่อไหร่", "บทความเกี่ยวกับอาหารไทยและผักผลไม้", False),
        ("ประวัติรถไฟไทยเป็นอย่างไร", "รถไฟไทยมีประวัติเริ่มต้นมานานแล้ว", True),
        ("รถไฟคืออะไร", "รถไฟเป็นยานพาหนะสำหรับขนส่งผู้โดยสาร", True),
        ("คืออะไร", "รายงานนี้อธิบายว่าอะไรบ้างที่สำคัญ", False),
        ("การศึกษา 2566", "รายงานด้านเศรษฐกิจประจำปี 2566", False),
        ("การศึกษา 2566", "รายงานการศึกษาในปี 2566 มีเนื้อหาที่น่าสนใจ", True),
        ("Auralis คืออะไร", "ความสามารถที่จำเป็นในการสมัครงาน", False),
        ("Auralis คืออะไร", "Auralis is an imaginary note-taking application.", True),
    ],
)
def test_absolute_question_overlap(question: str, text: str, expected: bool) -> None:
    assert has_answer_overlap(question, text) is expected


def test_weak_relative_winner_does_not_become_an_answer() -> None:
    class Provider:
        async def search(self, query: SearchQuery) -> list[SearchResult]:
            return [SearchResult("Report", "https://example.org/report")]

    class Reader:
        async def read(self, url: str) -> Document:
            text = "The project requires a candidate with strong communication skills."
            return Document(url, "Report", text, (Passage(text, 0),))

    async def run() -> None:
        agent = ResearchAgent(SearchService(Provider()), Reader())
        report = await agent.research(
            "What is the Copper telescope project?",
            ResearchBudget(max_queries=1, max_pages=1, max_rounds=1),
        )
        assert len(report.claims) == 1  # Still available for inspection.
        assert report.answer == ""
        assert report.answer_citations == ()

    asyncio.run(run())


def test_answer_citations_identify_exact_claim_origin() -> None:
    documents = {
        "https://one.example/a": "Mars rover studies geology on the red planet in great detail.",
        "https://two.example/b": "Mars rover studies geology on the blue planet in great detail.",
    }

    class Provider:
        async def search(self, query: SearchQuery) -> list[SearchResult]:
            return [SearchResult("Mars", url) for url in documents]

    class Reader:
        async def read(self, url: str) -> Document:
            text = documents[url]
            return Document(url, "Mars", text, (Passage(text, 0),))

    async def run() -> None:
        report = await ResearchAgent(SearchService(Provider()), Reader()).research(
            "Mars rover geology", ResearchBudget(max_queries=1, max_pages=2, max_rounds=1)
        )
        assert len(report.claims) == 2
        assert any(len(claim.sources) > 1 for claim in report.claims)
        for line in report.answer.splitlines()[1:]:
            claim = next(c for c in report.claims if c.text in line)
            for index, url in enumerate(report.answer_citations, 1):
                if f"[{index}]" in line:
                    assert claim.text in documents[url]

    asyncio.run(run())
