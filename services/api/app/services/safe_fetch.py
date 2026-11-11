"""Fetching an address we were handed (from a public DNS record, or a public registry) without becoming a way into the server's own network.

https only, no credentials in the address, and every host (the first and any redirect target) must resolve only to public addresses. A size limit and a short timeout apply. Redirects are followed by hand,
a few at most, so each hop is checked; with max_redirects=0 any redirect is refused. A name that changes its answer between the check and the request is the small remaining gap: the answer is only ever parsed
as a certificate or as registration data, and never shown or followed further.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx


class FetchRefused(Exception):
    """The address is not one we may fetch (not https, not public, redirected too far, too large, or it did not answer)."""


async def _check(url: str) -> None:
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise FetchRefused("The address is not a plain https address.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise FetchRefused("The address does not resolve.") from None
    if not infos or any(not ipaddress.ip_address(i[4][0]).is_global for i in infos):
        raise FetchRefused("The address is not on the public internet.")


async def fetch(url: str, max_bytes: int = 200_000, max_redirects: int = 0, accept: str = "*/*") -> bytes:
    current = url
    for hop in range(max_redirects + 1):
        await _check(current)
        try:
            async with (
                httpx.AsyncClient(follow_redirects=False, timeout=8.0) as client,
                client.stream("GET", current, headers={"Accept": accept}) as res,
            ):
                if res.status_code in (301, 302, 303, 307, 308) and res.headers.get("location"):
                    if hop == max_redirects:
                        raise FetchRefused(
                            "The address redirects, which is not followed here."
                            if max_redirects == 0
                            else "The address redirects too many times."
                        )
                    current = urljoin(current, res.headers["location"])
                    continue
                if res.status_code != 200:
                    raise FetchRefused(f"The address answered {res.status_code}.")
                body = b""
                async for chunk in res.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise FetchRefused("The file is larger than expected.")
                return body
        except httpx.HTTPError:
            raise FetchRefused("The address did not answer.") from None
    raise FetchRefused("The address redirects too many times.")
