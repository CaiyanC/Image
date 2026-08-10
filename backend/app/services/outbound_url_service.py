"""Validation for administrator-configured outbound model endpoints."""

import ipaddress
import socket
from urllib.parse import urlsplit


_ALWAYS_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata.amazonaws.com",
}


def validate_outbound_url(
    url: str,
    *,
    resolve_dns: bool = True,
    allow_private: bool = False,
    allow_insecure_http: bool = False,
) -> str:
    """Return a normalized URL only when it is safe for an outbound API call.

    Configuration writes validate the URL structure and literal IP immediately.
    Runtime calls additionally resolve every A/AAAA answer and reject the entire
    target if any answer is not globally routable. Private network endpoints
    require an explicit deployment opt-in; loopback, link-local and metadata
    destinations remain blocked even with that opt-in.
    """

    value = str(url or "").strip()
    if not value:
        raise ValueError("Model endpoint URL is required")
    if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Model endpoint URL contains invalid characters")
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"https", "http"}:
        raise ValueError("Model endpoint must use HTTP or HTTPS")
    if scheme == "http" and not allow_insecure_http:
        raise ValueError("Model endpoint must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Model endpoint must not contain URL credentials")
    if parsed.fragment:
        raise ValueError("Model endpoint must not contain a URL fragment")
    hostname = (parsed.hostname or "").strip().rstrip(".").lower()
    if not hostname:
        raise ValueError("Model endpoint hostname is required")
    if hostname in _ALWAYS_BLOCKED_HOSTS or hostname.endswith(".localhost"):
        raise ValueError("Model endpoint hostname is blocked")
    if "%" in hostname:
        raise ValueError("Model endpoint hostname is invalid")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Model endpoint port is invalid") from exc

    literal = _parse_ip(hostname)
    if literal is not None:
        _validate_address(literal, allow_private=allow_private)
        return value
    if not resolve_dns:
        return value

    try:
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Model endpoint hostname could not be resolved") from exc
    addresses = {
        answer[4][0]
        for answer in answers
        if len(answer) >= 5 and answer[4]
    }
    if not addresses:
        raise ValueError("Model endpoint hostname returned no addresses")
    for address in addresses:
        parsed_address = _parse_ip(address)
        if parsed_address is None:
            raise ValueError("Model endpoint resolved to an invalid address")
        _validate_address(parsed_address, allow_private=allow_private)
    return value


def _parse_ip(value: str):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _validate_address(address, *, allow_private: bool) -> None:
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise ValueError("Model endpoint must resolve to a public address")
    if address.is_global:
        return
    if allow_private and address.is_private:
        return
    raise ValueError("Model endpoint must resolve to a public address")
