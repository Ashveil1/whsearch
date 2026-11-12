import ssl

import pytest

from whsearch.config import Settings
from whsearch.infrastructure.http.client import HttpClientFactory


def test_explicit_ca_file_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHSEARCH_CA_FILE", "/tmp/custom-ca.pem")
    assert Settings.from_environment().ca_file == "/tmp/custom-ca.pem"


def test_explicit_ca_file_never_disables_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    contexts: list[ssl.SSLContext] = []

    def create_context(*, cafile: str) -> ssl.SSLContext:
        assert cafile == "/tmp/custom-ca.pem"
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        contexts.append(ctx)
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", create_context)
    client = HttpClientFactory(ca_file="/tmp/custom-ca.pem").create()
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname
    import asyncio

    asyncio.run(client.aclose())
