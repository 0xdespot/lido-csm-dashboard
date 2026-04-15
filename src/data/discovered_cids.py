"""Persistent runtime cache for discovered distribution CIDs.

Supplements the static known_cids.py with CIDs discovered at runtime
via Etherscan API, RPC event queries, or contract calls. Persisted to
disk so future runs start from the most recent known block.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".cache" / "csm-dashboard" / "discovered_cids.json"


def load_discovered_cids() -> list[dict]:
    """Load previously discovered CIDs from disk."""
    if not CACHE_PATH.exists():
        return []
    try:
        data = json.loads(CACHE_PATH.read_text())
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load discovered CIDs cache: {e}")
    return []


def save_discovered_cids(cids: list[dict]) -> None:
    """Save discovered CIDs to disk."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cids, indent=2))
    except OSError as e:
        logger.warning(f"Failed to save discovered CIDs cache: {e}")


def merge_cid_sources(*sources: list[dict]) -> list[dict]:
    """Merge multiple CID lists, deduplicating by logCid and sorting by block."""
    seen: dict[str, dict] = {}
    for source in sources:
        for entry in source:
            cid = entry.get("logCid")
            block = entry.get("block")
            if not cid or block is None:
                continue
            # Keep the entry with the lowest block number (most accurate)
            if cid not in seen or block < seen[cid]["block"]:
                seen[cid] = entry
    return sorted(seen.values(), key=lambda x: x["block"])


def record_new_cids(new_cids: list[dict]) -> None:
    """Merge new CIDs with existing cache and persist."""
    existing = load_discovered_cids()
    merged = merge_cid_sources(existing, new_cids)
    if merged != existing:
        save_discovered_cids(merged)
        logger.info(
            f"Discovered CID cache updated: {len(existing)} -> {len(merged)} entries"
        )
