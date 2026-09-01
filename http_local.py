"""One place that decides when an HTTP client must ignore the environment.

Windows keeps its proxy in the registry, and `httpx` with `trust_env=True`
picks it up through `urllib.request.getproxies()`. A `socks=` entry there
becomes `socks4://…`, which httpx cannot use at all:

    ValueError: Unknown scheme for proxy URL URL('socks4://127.0.0.1:10808')

The registry's own ProxyOverride lists `localhost;127.*`, so Windows itself
would never send these requests to the proxy — but httpx does not read
ProxyOverride. The result is that turning a VPN on breaks calls to services
running on the same machine.

This is not hypothetical. Every rerank call failed for a whole measurement run
this way, and the only visible sign was `rerank_status: failed` in the trace:
search quality on the golden set fell from 9/10 to 5/10 on the normative half
while the contour reported itself healthy. The embedder and the rules extractor
each grew their own copy of this guard; the reranker had none, so it is the one
that broke.
"""
from __future__ import annotations

from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_local(url: str) -> bool:
    return (urlparse(str(url or "")).hostname or "").lower() in LOCAL_HOSTS


def httpx_client_kwargs(url: str) -> dict:
    """`httpx.Client` keyword arguments for talking to `url`.

    A service on this machine is reached directly; anything else keeps the
    environment's proxy configuration, which is what it is there for.
    """
    return {"trust_env": False} if is_local(url) else {}
