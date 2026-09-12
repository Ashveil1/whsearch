from whsearch.domain import Passage, SearchResult
from whsearch.retrieval import deduplicate_results, rank_passages


def test_deduplicate_results_normalizes_fragments_and_host_case() -> None:
    results = [
        SearchResult(title="A", url="https://EXAMPLE.com/path#one"),
        SearchResult(title="B", url="https://example.com/path#two"),
    ]
    assert len(deduplicate_results(results)) == 1


def test_rank_passages_prefers_matching_passage() -> None:
    passages = [
        Passage("The weather is sunny.", 0),
        Passage("Python is a programming language.", 1),
    ]
    ranked = rank_passages("Python programming", passages)
    assert ranked[0].index == 1
    assert ranked[0].score is not None
