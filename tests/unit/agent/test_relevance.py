from whsearch.agent.service import relevance_scores
from whsearch.domain import Claim


def _claim(cid: str, text: str) -> Claim:
    return Claim(id=cid, text=text)


def test_rare_entity_outweighs_frequent_word() -> None:
    claims = [
        _claim("spam", "ความสามารถพิเศษในการเขียนเรซูเม่สมัครงาน"),
        _claim("gold", "Zhypix is an Android AI assistant"),
    ]
    scores = relevance_scores("Zhypix คืออะไร มีความสามารถอะไรบ้าง?", claims)
    assert scores["gold"] > scores["spam"]


def test_empty_claims() -> None:
    assert relevance_scores("anything?", []) == {}


def test_scores_bounded() -> None:
    claims = [_claim("a", "Python programming language"), _claim("b", "weather sunny")]
    scores = relevance_scores("Python", claims)
    assert all(0.0 <= value <= 1.0 for value in scores.values())
    assert scores["a"] > scores["b"]
