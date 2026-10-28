"""SSRF-safe URL validation and fetching for public website ingestion.

Rules enforced
  * only http/https; no credentials in the URL; only ports 80/443 (configurable)
  * every hostname is resolved and *every* resolved address must be globally routable
    (loopback, private, link-local, multicast, reserved, unspecified, CGNAT, and
    IPv4-mapped IPv6 forms of those are rejected)
  * redirects are followed manually (max N) and each hop is re-validated
  * the connection is made to the validated IP (Host/SNI preserved) so DNS cannot be
    re-resolved to a different address between validation and connection (anti-rebinding)
  * response size and total duration are capped
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

ALLOWED_PORTS = {80, 443}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class UnsafeUrlError(ValueError):
    """The URL (or a redirect target) is not allowed."""


class FetchError(RuntimeError):
    """The fetch failed for a non-security reason (timeout, too large, HTTP error)."""


def ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv6Address) and addr.sixtofour:
        addr = addr.sixtofour
    if addr in _CGNAT:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified or not addr.is_global)


Resolver = Callable[[str, int], list[str]]


def default_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise FetchError(f"DNS lookup failed for {host}") from e
    return sorted({i[4][0] for i in infos})


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    scheme: str
    host: str
    port: int
    ip: str
    path_qs: str


def validate_url(url: str, resolver: Resolver = default_resolver,
                 allowed_ports: set[int] = ALLOWED_PORTS) -> ValidatedTarget:
    if not url or len(url) > 2048:
        raise UnsafeUrlError("URL is empty or too long")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeUrlError("URLs containing credentials are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as e:
        raise UnsafeUrlError("Invalid port") from e
    if port not in allowed_ports:
        raise UnsafeUrlError(f"Port {port} is not allowed")
    if host.lower() in ("localhost",) or host.lower().endswith((".localhost", ".local", ".internal")):
        raise UnsafeUrlError("Local hostnames are not allowed")

    try:  # literal IP (including decimal/hex forms are rejected by ip_address -> handled by resolver)
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        addrs = resolver(host, port)
    if not addrs:
        raise FetchError(f"No addresses found for {host}")
    for a in addrs:
        if not ip_is_public(a):
            raise UnsafeUrlError("The destination resolves to a non-public network address")
    path_qs = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return ValidatedTarget(url.strip(), parts.scheme, host, port, addrs[0], path_qs)


@dataclass
class FetchResult:
    final_url: str
    status: int
    content_type: str
    body: bytes
    redirects: list[str]
    truncated: bool


# A transport performs ONE request to a validated target and returns
# (status, headers(lower-cased dict), body_bytes, truncated). It must not follow redirects.
Transport = Callable[[ValidatedTarget, int, float], tuple[int, dict, bytes, bool]]


def socket_transport(target: ValidatedTarget, max_bytes: int, timeout: float):
    """Real transport: connects to the pre-validated IP, preserving Host/SNI."""
    import http.client
    import ssl

    deadline = time.monotonic() + timeout
    sock = socket.create_connection((target.ip, target.port), timeout=timeout)
    try:
        if target.scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=target.host)
        req = (f"GET {target.path_qs} HTTP/1.1\r\nHost: {target.host}\r\n"
               f"User-Agent: ProoflineBot/1.0\r\nAccept: text/html,application/xhtml+xml,text/plain\r\n"
               f"Accept-Encoding: identity\r\nConnection: close\r\n\r\n").encode()
        sock.sendall(req)
        buf = b""
        while b"\r\n\r\n" not in buf:
            if time.monotonic() > deadline:
                raise FetchError("Timed out reading response headers")
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
            if len(buf) > 65536:
                raise FetchError("Response headers too large")
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            status = int(lines[0].split()[1])
        except (IndexError, ValueError) as e:
            raise FetchError("Malformed HTTP response") from e
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        body = rest
        truncated = False
        while len(body) <= max_bytes:
            if time.monotonic() > deadline:
                raise FetchError("Timed out reading response body")
            chunk = sock.recv(65536)
            if not chunk:
                break
            body += chunk
        if len(body) > max_bytes:
            body, truncated = body[:max_bytes], True
        if headers.get("transfer-encoding", "").lower() == "chunked":
            body = _dechunk(body)
        return status, headers, body, truncated
    finally:
        sock.close()


def _dechunk(data: bytes) -> bytes:
    out, i = b"", 0
    while i < len(data):
        j = data.find(b"\r\n", i)
        if j < 0:
            break
        try:
            size = int(data[i:j].split(b";")[0], 16)
        except ValueError:
            break
        if size == 0:
            break
        out += data[j + 2:j + 2 + size]
        i = j + 2 + size + 2
    return out


def safe_fetch(url: str, *, resolver: Resolver = default_resolver,
               transport: Transport = socket_transport, max_bytes: int = 2_000_000,
               timeout: float = 10.0, max_redirects: int = 3) -> FetchResult:
    redirects: list[str] = []
    current = url
    started = time.monotonic()
    for _ in range(max_redirects + 1):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise FetchError("Total fetch time exceeded")
        target = validate_url(current, resolver)
        status, headers, body, truncated = transport(target, max_bytes, remaining)
        if status in (301, 302, 303, 307, 308):
            loc = headers.get("location")
            if not loc:
                raise FetchError("Redirect without Location header")
            current = urljoin(current, loc)
            redirects.append(current)
            continue
        if status >= 400:
            raise FetchError(f"The server responded with HTTP {status}")
        return FetchResult(current, status, headers.get("content-type", ""), body, redirects, truncated)
    raise FetchError("Too many redirects")
