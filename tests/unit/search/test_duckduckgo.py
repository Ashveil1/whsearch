from whsearch.search.providers.duckduckgo import _extract_target_url


def test_extract_duckduckgo_redirect_url() -> None:
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs&rut=abc"
    assert _extract_target_url(href) == "https://example.com/docs"


def test_extract_direct_url() -> None:
    assert _extract_target_url("https://example.com/docs") == "https://example.com/docs"


def test_reject_invalid_url() -> None:
    assert _extract_target_url("javascript:alert(1)") is None


def test_snippets_do_not_come_from_other_results() -> None:
    from bs4 import BeautifulSoup

    from whsearch.search.providers.duckduckgo import _extract_snippet

    soup = BeautifulSoup(
        '<body><a class="result-link" href="https://one.example">First result</a>'
        '<a class="result-link" href="https://two.example">Second unrelated result</a></body>',
        "html.parser",
    )
    links = soup.select("a.result-link")
    assert _extract_snippet(links[0], "First result") == ""
    assert _extract_snippet(links[1], "Second unrelated result") == ""


def test_classic_lite_snippet_in_following_row() -> None:
    from bs4 import BeautifulSoup

    from whsearch.search.providers.duckduckgo import _extract_snippet

    soup = BeautifulSoup(
        '<table><tr><td><a class="result-link" href="https://one.example">Title</a></td></tr>'
        '<tr><td class="result-snippet">The correct snippet</td></tr></table>',
        "html.parser",
    )
    assert _extract_snippet(soup.select_one("a.result-link"), "Title") == "The correct snippet"
