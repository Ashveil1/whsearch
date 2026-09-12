from whsearch.research import plan_queries
from whsearch.research.planner import _keywords, _thai_keywords


def test_thai_keywords_keep_entity_and_content_word() -> None:
    assert _thai_keywords("zhypix คืออะไร มีความสามารถอะไรบ้าง") == "zhypix ความสามารถ"


def test_thai_keywords_do_not_shred_combining_marks() -> None:
    # \w splits Thai sara; whitespace chunks must stay intact instead.
    assert _keywords("Zhypix คืออะไร มีความสามารถอะไรบ้าง?") == "zhypix ความสามารถ"


def test_thai_keywords_other_question() -> None:
    assert _keywords("ผลบอลโลก 2026 ใครได้แชมป์?") == "ผลบอลโลก 2026 แชมป์"


def test_thai_keywords_fallback_never_empty() -> None:
    assert _thai_keywords("คืออะไร") != ""


def test_thai_content_words_survive() -> None:
    assert _thai_keywords("ประเทศไทย") == "ประเทศไทย"


def test_plan_includes_thai_keyword_query() -> None:
    texts = [q.text for q in plan_queries("Zhypix คืออะไร มีความสามารถอะไรบ้าง?", max_queries=4)]
    assert "zhypix ความสามารถ" in texts


def test_english_keywords_unchanged() -> None:
    assert _keywords("What is Elengenix and how does it work?") == "elengenix work"
