"""Run a small deterministic offline retrieval/research regression benchmark.

This fixture is synthetic: its metrics are diagnostics, not real-world accuracy
or evidence that claims are true. It makes no network requests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

from whsearch.agent import ResearchAgent
from whsearch.domain import (
    Document,
    Passage,
    ResearchBudget,
    ResearchReport,
    SearchQuery,
    SearchResult,
)
from whsearch.search import SearchService

_DATA = Path(__file__).parent / "data" / "quality.json"
_MARKER = re.compile(r"\[(\d+)\]")


class RetrievalCase(TypedDict):
    id: str
    language: str
    query: str
    passages: list[str]
    relevant: list[int]


class FixtureDocument(TypedDict):
    url: str
    title: str
    passages: list[str]


class ResearchCase(TypedDict):
    id: str
    language: str
    question: str
    answerable: bool
    documents: list[FixtureDocument]
    gold_claims: list[str]
    relevant_urls: list[str]


class Dataset(TypedDict):
    version: int
    description: str
    retrieval: list[RetrievalCase]
    research: list[ResearchCase]


class RetrievalResult(TypedDict):
    id: str
    language: str
    ranked_indices: list[int]
    reciprocal_rank: float
    hit_at_1: float
    recall_at_3: float


class ResearchResult(TypedDict):
    id: str
    language: str
    answerable: bool
    answer: str
    top_answer_correct: bool | None
    abstained: bool
    answer_lines: int
    relevant_answer_lines: int
    citation_markers: int
    relevant_citation_markers: int
    citation_structure_valid: bool


def load_dataset(path: Path = _DATA) -> Dataset:
    data = cast(Dataset, json.loads(path.read_text(encoding="utf-8")))
    if data["version"] != 1 or not data["retrieval"] or not data["research"]:
        raise ValueError("unsupported or empty benchmark dataset")
    ids: set[str] = set()
    for case in data["retrieval"]:
        if case["id"] in ids or not case["query"] or not case["relevant"]:
            raise ValueError("invalid retrieval case")
        ids.add(case["id"])
        if not case["passages"] or any(
            index < 0 or index >= len(case["passages"]) for index in case["relevant"]
        ):
            raise ValueError(f"invalid relevance labels for {case['id']}")
    for research_case in data["research"]:
        urls = [doc["url"] for doc in research_case["documents"]]
        if (
            research_case["id"] in ids
            or not research_case["question"]
            or not urls
            or len(urls) != len(set(urls))
            or not set(research_case["relevant_urls"]).issubset(urls)
            or research_case["answerable"] != bool(research_case["gold_claims"])
        ):
            raise ValueError("invalid research case")
        if any(
            not doc["passages"] or any(not text.strip() for text in doc["passages"])
            for doc in research_case["documents"]
        ):
            raise ValueError(f"invalid documents for {research_case['id']}")
        ids.add(research_case["id"])
    return data


def evaluate_retrieval(case: RetrievalCase) -> RetrievalResult:
    from whsearch.retrieval import rank_passages

    passages = [Passage(text, index) for index, text in enumerate(case["passages"])]
    ranked = [p.index for p in rank_passages(case["query"], passages, limit=len(passages))]
    relevant = set(case["relevant"])
    first = next((rank for rank, index in enumerate(ranked, 1) if index in relevant), None)
    return {
        "id": case["id"],
        "language": case["language"],
        "ranked_indices": ranked,
        "reciprocal_rank": 1 / first if first is not None else 0.0,
        "hit_at_1": float(bool(ranked) and ranked[0] in relevant),
        "recall_at_3": len(relevant.intersection(ranked[:3])) / len(relevant),
    }


class FixtureProvider:
    def __init__(self, documents: list[FixtureDocument]) -> None:
        self._documents = documents

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        # Fixed order isolates the reader/research pipeline from web discovery.
        return [SearchResult(title=doc["title"], url=doc["url"]) for doc in self._documents]


class FixtureReader:
    def __init__(self, documents: list[FixtureDocument]) -> None:
        self._documents = {doc["url"]: doc for doc in documents}

    async def read(self, url: str) -> Document:
        doc = self._documents[url]
        passages = tuple(Passage(text, i) for i, text in enumerate(doc["passages"]))
        return Document(
            url=url, title=doc["title"], content="\n\n".join(doc["passages"]), passages=passages
        )


def _normalized_extract(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().replace("|", " ").split())


def score_research(case: ResearchCase, report: ResearchReport) -> ResearchResult:
    lines = report.answer.splitlines()[1:] if report.answer else []
    evidence_pairs = {(item.claim_id, item.url) for item in report.evidence}
    document_texts = {
        (doc["url"], index): text
        for doc in case["documents"]
        for index, text in enumerate(doc["passages"])
    }
    structure_valid = True
    relevant_lines = citation_markers = relevant_markers = 0
    gold = set(case["gold_claims"])
    relevant_urls = set(case["relevant_urls"])
    first_correct = False
    for number, line in enumerate(lines, 1):
        candidates = [
            claim for claim in report.claims if line.startswith(f"{number}. {claim.text} ")
        ]
        if len(candidates) != 1:
            structure_valid = False
            continue
        claim = candidates[0]
        is_relevant = claim.text in gold
        relevant_lines += int(is_relevant)
        if number == 1:
            first_correct = is_relevant
        # Only parse citation markers following the claim, not brackets inside its text.
        suffix = line[len(f"{number}. {claim.text} ") :]
        indices = [int(match) for match in _MARKER.findall(suffix)]
        urls: list[str] = []
        for index in indices:
            citation_markers += 1
            if not 1 <= index <= len(report.answer_citations):
                structure_valid = False
                continue
            url = report.answer_citations[index - 1]
            urls.append(url)
            relevant_markers += int(is_relevant and url in relevant_urls)
            if (claim.id, url) not in evidence_pairs:
                structure_valid = False
        if not indices or not set(urls).issubset(claim.sources):
            structure_valid = False
        for url in urls:
            matching = [
                item for item in report.evidence if item.claim_id == claim.id and item.url == url
            ]
            if not any(
                _normalized_extract(claim.text) in _normalized_extract(item.passage_text)
                for item in matching
            ):
                structure_valid = False
            for item in matching:
                original = document_texts.get((item.url, item.passage_index))
                if original is None or not original.startswith(item.passage_text):
                    structure_valid = False
    return {
        "id": case["id"],
        "language": case["language"],
        "answerable": case["answerable"],
        "answer": report.answer,
        "top_answer_correct": first_correct if case["answerable"] else None,
        "abstained": not bool(lines),
        "answer_lines": len(lines),
        "relevant_answer_lines": relevant_lines,
        "citation_markers": citation_markers,
        "relevant_citation_markers": relevant_markers,
        "citation_structure_valid": structure_valid,
    }


async def evaluate_research(case: ResearchCase) -> ResearchResult:
    documents = case["documents"]
    agent = ResearchAgent(SearchService(FixtureProvider(documents)), FixtureReader(documents))
    report = await agent.research(
        case["question"], ResearchBudget(max_queries=1, max_pages=len(documents), max_rounds=1)
    )
    return score_research(case, report)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


async def run(data: Dataset) -> dict[str, object]:
    retrieval = [evaluate_retrieval(case) for case in data["retrieval"]]
    research = [await evaluate_research(case) for case in data["research"]]
    answerable = [result for result in research if result["answerable"]]
    unanswerable = [result for result in research if not result["answerable"]]
    total_lines = sum(result["answer_lines"] for result in research)
    total_markers = sum(result["citation_markers"] for result in research)
    return {
        "dataset_version": data["version"],
        "warning": "Synthetic, small, offline fixture; not a real-world quality estimate.",
        "summary": {
            "retrieval_cases": len(retrieval),
            "hit_at_1": _mean([r["hit_at_1"] for r in retrieval]),
            "mrr": _mean([r["reciprocal_rank"] for r in retrieval]),
            "recall_at_3": _mean([r["recall_at_3"] for r in retrieval]),
            "answerable_cases": len(answerable),
            "answerable_top1_hit": _mean(
                [float(bool(r["top_answer_correct"])) for r in answerable]
            ),
            "unanswerable_cases": len(unanswerable),
            "unanswerable_abstention": _mean([float(r["abstained"]) for r in unanswerable]),
            "answer_line_precision": round(
                sum(r["relevant_answer_lines"] for r in research) / total_lines, 4
            )
            if total_lines
            else None,
            "citation_topical_precision": round(
                sum(r["relevant_citation_markers"] for r in research) / total_markers, 4
            )
            if total_markers
            else None,
            "citation_structure_valid_cases": sum(r["citation_structure_valid"] for r in research),
            "research_cases": len(research),
        },
        "retrieval": retrieval,
        "research": research,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=_DATA)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run(load_dataset(args.dataset)))
    if args.summary_only:
        result = {key: result[key] for key in ("dataset_version", "warning", "summary")}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
