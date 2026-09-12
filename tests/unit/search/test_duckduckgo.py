from whsearch.search.providers.duckduckgo import _extract_target_url


def test_extract_duckduckgo_redirect_url() -> None:
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs&rut=abc"
    assert _extract_target_url(href) == "https://example.com/docs"


def test_extract_direct_url() -> None:
    assert _extract_target_url("https://example.com/docs") == "https://example.com/docs"


def test_reject_invalid_url() -> None:
    assert _extract_target_url("javascript:alert(1)") is None
