"""Selection and failover across one or more Ethereum RPC endpoints.

``ETH_RPC_URL`` accepts a comma-separated, ordered list so a self-hosted node
whose address moves (a DAppNode on DHCP, for example) can fall back to another
endpoint instead of taking the dashboard down with it. This mirrors the
existing ``ipfs_gateways`` setting, which is already a comma-separated list.

The chosen endpoint is memoized process-wide for ``RPC_SELECTION_TTL`` seconds
so the probe cost is not paid per request, and is invalidated as soon as a call
fails at the transport level, so the next request fails over rather than
pinning a dead node for the rest of the TTL.
"""

import logging
import threading
import time
from collections.abc import Callable

from web3 import Web3

from ..core.rpc_errors import RPCUnavailableError, safe_rpc_host

logger = logging.getLogger(__name__)

# How long a successful endpoint choice is trusted before being re-probed.
RPC_SELECTION_TTL = 300.0

# Per-candidate probe timeout. Deliberately short: this runs inline when a
# failover is needed, and a slow candidate should be skipped, not waited on.
RPC_PROBE_TIMEOUT = 5.0

_selection: tuple[str, float] | None = None
_selection_lock = threading.Lock()


def parse_rpc_candidates(raw: str) -> list[str]:
    """Split a comma-separated ``ETH_RPC_URL`` into an ordered candidate list."""
    return [url.strip() for url in raw.split(",") if url.strip()]


def invalidate_rpc_selection() -> None:
    """Forget the memoized endpoint so the next selection re-probes.

    Called when a transport-level failure proves the current endpoint is no
    longer usable.
    """
    global _selection
    with _selection_lock:
        _selection = None


def _default_probe(url: str) -> int:
    """Return the chain ID, raising if the endpoint does not answer."""
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": RPC_PROBE_TIMEOUT}))
    return w3.eth.chain_id


def select_rpc_url(
    candidates: list[str],
    *,
    probe: Callable[[str], int] = _default_probe,
) -> str:
    """Return the first candidate that answers, memoized for a short while.

    A single candidate is returned without probing — the overwhelmingly common
    configuration must not pay a round-trip it has no use for, since there is
    nothing to fail over to. Raises :class:`RPCUnavailableError` naming every
    host tried only when all of them fail.
    """
    global _selection

    if not candidates:
        raise RPCUnavailableError("no RPC endpoint configured (ETH_RPC_URL is empty)")

    if len(candidates) == 1:
        return candidates[0]

    now = time.monotonic()
    with _selection_lock:
        if _selection is not None:
            url, chosen_at = _selection
            # Ignore a memo for a URL that is no longer configured.
            if now - chosen_at < RPC_SELECTION_TTL and url in candidates:
                return url

    tried: list[str] = []
    for url in candidates:
        safe = safe_rpc_host(url)
        tried.append(safe)
        try:
            chain_id = probe(url)
        except Exception as e:
            # Log the type only — the message may embed the full URL, which can
            # carry an API key in its path or query.
            logger.warning(f"RPC endpoint {safe} did not respond: {type(e).__name__}")
            continue

        with _selection_lock:
            _selection = (url, time.monotonic())
        logger.info(f"RPC endpoint selected: {safe} (chain_id={chain_id})")
        if chain_id != 1:
            logger.warning(f"RPC chain_id is {chain_id}, expected 1 (mainnet)")
        return url

    raise RPCUnavailableError(", ".join(tried))
