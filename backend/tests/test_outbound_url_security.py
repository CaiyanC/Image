import socket
from unittest.mock import patch

import pytest

from app.services import generation_service
from app.services.outbound_url_service import validate_outbound_url


def _answer(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 443))]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "https://127.0.0.1/admin",
    "https://169.254.169.254/latest/meta-data",
    "https://[::1]/admin",
    "file:///etc/passwd",
    "https://user:password@api.example.com/v1",
])
def test_outbound_url_rejects_unsafe_literal_targets(url):
    with pytest.raises(ValueError):
        validate_outbound_url(url, resolve_dns=False)


def test_outbound_url_rejects_a_hostname_resolving_to_private_space():
    with patch("app.services.outbound_url_service.socket.getaddrinfo", return_value=_answer("10.1.2.3")):
        with pytest.raises(ValueError, match="public"):
            validate_outbound_url("https://models.example.com/v1")


def test_outbound_url_accepts_https_hostname_when_every_address_is_public():
    with patch("app.services.outbound_url_service.socket.getaddrinfo", return_value=_answer("93.184.216.34")):
        assert validate_outbound_url("https://models.example.com/v1") == "https://models.example.com/v1"


def test_outbound_url_rejects_mixed_public_and_private_dns_answers():
    answers = _answer("93.184.216.34") + _answer("10.1.2.3")
    with patch("app.services.outbound_url_service.socket.getaddrinfo", return_value=answers):
        with pytest.raises(ValueError, match="public"):
            validate_outbound_url("https://models.example.com/v1")


def test_private_model_endpoint_requires_both_explicit_private_and_http_opt_ins():
    with patch("app.services.outbound_url_service.socket.getaddrinfo", return_value=_answer("10.1.2.3")):
        assert validate_outbound_url(
            "http://models.internal/v1",
            allow_private=True,
            allow_insecure_http=True,
        ) == "http://models.internal/v1"


def test_generated_image_download_rejects_private_targets_before_request():
    import asyncio

    with pytest.raises(ValueError, match="public"):
        asyncio.run(generation_service._download_generated_image("https://127.0.0.1/private.png"))
