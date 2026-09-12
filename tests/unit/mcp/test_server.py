def test_mcp_server_imports() -> None:
    from whsearch.mcp.server import mcp

    assert mcp.name == "WHSearch"
