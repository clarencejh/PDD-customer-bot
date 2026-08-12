"""Fetch remote images without DNS rebinding or proxy surprises."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from urllib3.connectionpool import HTTPSConnectionPool


def _public_address(hostname: str, port: int) -> str:
    """Resolve once and return a public address that the request will pin to."""
    addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("logo host has no address")
    # A local proxy in fake-ip mode (Clash/mihomo TUN) answers every query with
    # the RFC 2544 benchmark range and routes by hostname itself.  That range is
    # unroutable otherwise, so allowing it here cannot reach real LAN targets.
    if all(
        ipaddress.ip_address(item[4][0]) in ipaddress.ip_network("198.18.0.0/15")
        for item in addresses
    ):
        return addresses[0][4][0]
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_multicast
            or not ip.is_global
        ):
            raise ValueError("logo URL resolves to a non-public address")
    return addresses[0][4][0]


def fetch_image(url: str, max_bytes: int = 5 * 1024 * 1024, timeout: float = 10.0) -> bytes:
    """Fetch an HTTPS image while connecting to the verified IP address.

    The TLS SNI/certificate hostname and HTTP Host header remain the original
    hostname, while the connection pool is pinned to the address resolved
    above.  Redirects are disabled so a response cannot escape the check.
    """
    parsed = urlsplit(str(url))
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("logo URL must use https")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("logo URL has unsupported authority")

    hostname = parsed.hostname.rstrip(".")
    port = 443
    address = _public_address(hostname, port)
    pool = HTTPSConnectionPool(
        address,
        port=port,
        timeout=timeout,
        maxsize=1,
        block=True,
        retries=False,
        assert_hostname=hostname,
        server_hostname=hostname,
        cert_reqs="CERT_REQUIRED",
    )
    response = None
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        response = pool.urlopen(
            "GET",
            path,
            headers={
                "Host": hostname,
                "Accept": "image/*",
                "User-Agent": "Customer-Agent/1.0",
            },
            preload_content=False,
            redirect=False,
        )
        if response.status < 200 or response.status >= 300:
            raise ValueError("logo request returned an invalid status")
        if not response.headers.get("Content-Type", "").lower().startswith("image/"):
            raise ValueError("logo response is not an image")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("logo response is too large")

        chunks = []
        total = 0
        for chunk in response.stream(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("logo response is too large")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if response is not None:
            response.release_conn()
        pool.close()
