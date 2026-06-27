"""Errors and helpers for detecting an unreachable Ethereum RPC node.

Kept in ``core`` (no web/data dependencies) so both the web layer and the
data layer can import these without creating an import cycle.
"""

import socket
from urllib.parse import urlparse

import requests.exceptions
import urllib3.exceptions


class RPCUnavailableError(Exception):
    """Raised when the configured Ethereum RPC node cannot be reached.

    Distinct from contract reverts / value errors — this means the transport
    failed (connection refused, DNS failure, timeout), i.e. the node is down
    or misconfigured, not that the requested data is absent.

    Carries a sanitized ``host`` (scheme://host:port, never the full URL) so
    it can be shown to users without leaking an API key embedded in the path.
    """

    def __init__(self, host: str):
        self.host = host
        super().__init__(f"RPC node unreachable at {host}")


def safe_rpc_host(url: str) -> str:
    """Return ``scheme://host[:port]`` for an RPC URL, dropping path/query.

    Any API key embedded in the URL path or query string is stripped, so the
    result is safe to log and to show to users.
    """
    parsed = urlparse(url)
    safe = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        safe += f":{parsed.port}"
    return safe


# Transport-level failures that mean "the node is unreachable". Deliberately
# excludes bare OSError and web3 ContractLogicError/Web3RPCError — a contract
# revert still means "operator not found", not "node down".
_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    urllib3.exceptions.HTTPError,  # base of MaxRetryError / NewConnectionError
    socket.gaierror,  # DNS resolution failure
    ConnectionError,  # builtin, covers ConnectionRefusedError
)


def is_connection_error(exc: BaseException) -> bool:
    """True if ``exc`` (or anything in its cause/context chain) is a transport
    failure indicating the RPC node is unreachable.

    web3 7.x lets the underlying ``requests`` connection error propagate, but
    it may be wrapped, so we walk ``__cause__`` / ``__context__`` to a bounded
    depth.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < 20:
        if id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, _CONNECTION_ERRORS):
            return True
        current = current.__cause__ or current.__context__
        depth += 1
    return False
