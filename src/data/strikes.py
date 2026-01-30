"""Fetch and parse the strikes merkle tree from IPFS via CSStrikes contract."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from web3 import Web3

from ..core.config import get_settings
from .cache import cached

logger = logging.getLogger(__name__)


# Strike thresholds by operator type (curve_id)
# Default (Permissionless): 3 strikes till key exit
# ICS (Identified Community Staker): 4 strikes till key exit
STRIKE_THRESHOLDS = {
    0: 3,  # Permissionless (Legacy)
    1: 4,  # ICS/Legacy EA
    2: 3,  # Permissionless (current)
}
DEFAULT_STRIKE_THRESHOLD = 3


def get_strike_threshold(curve_id: int) -> int:
    """Get the strike threshold for ejection based on operator curve_id."""
    if curve_id not in STRIKE_THRESHOLDS:
        logger.warning(f"Unknown curve_id {curve_id}, defaulting to strike threshold {DEFAULT_STRIKE_THRESHOLD}")
    return STRIKE_THRESHOLDS.get(curve_id, DEFAULT_STRIKE_THRESHOLD)


@dataclass
class ValidatorStrikes:
    """Strike information for a single validator."""

    pubkey: str
    strikes: list[int]  # Array of 6 values (0 or 1) representing strikes per frame
    strike_count: int  # Total strikes in the 6-frame window
    strike_threshold: int  # Number of strikes required for ejection (3 or 4)
    at_ejection_risk: bool  # True if strike_count >= strike_threshold


class StrikesProvider:
    """Fetches strikes data from CSStrikes contract via IPFS."""

    # Rate limiting: minimum seconds between gateway requests
    MIN_REQUEST_INTERVAL = 1.0

    # CSStrikes contract ABI (only treeCid function needed)
    CSSTRIKES_ABI = [
        {
            "inputs": [],
            "name": "treeCid",
            "outputs": [{"internalType": "string", "name": "", "type": "string"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]

    def __init__(self, rpc_url: str | None = None, cache_dir: Path | None = None):
        self.settings = get_settings()
        # Use configurable gateways from settings (comma-separated)
        self.gateways = [g.strip() for g in self.settings.ipfs_gateways.split(",") if g.strip()]
        self.w3 = Web3(Web3.HTTPProvider(rpc_url or self.settings.eth_rpc_url))
        self.cache_dir = cache_dir or Path.home() / ".cache" / "csm-dashboard" / "strikes"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_time = 0.0
        self._rate_limit_lock = asyncio.Lock()

        # Initialize CSStrikes contract
        self.csstrikes = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.settings.csstrikes_address),
            abi=self.CSSTRIKES_ABI,
        )

    def _get_cache_path(self, cid: str) -> Path:
        """Get the cache file path for a CID."""
        return self.cache_dir / f"{cid}.json"

    def _load_from_cache(self, cid: str) -> dict | None:
        """Load tree data from local cache if available."""
        cache_path = self._get_cache_path(cid)
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                cache_path.unlink(missing_ok=True)
        return None

    def _save_to_cache(self, cid: str, data: dict) -> None:
        """Save tree data to local cache."""
        cache_path = self._get_cache_path(cid)
        try:
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    async def _rate_limit(self) -> None:
        """Ensure minimum interval between IPFS gateway requests."""
        async with self._rate_limit_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.MIN_REQUEST_INTERVAL:
                await asyncio.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_time = time.time()

    @cached(ttl=300)  # Cache CID for 5 minutes
    async def get_tree_cid(self) -> str:
        """Get the current strikes tree CID from the contract."""
        return await asyncio.to_thread(
            self.csstrikes.functions.treeCid().call
        )

    async def _fetch_tree_from_ipfs(self, cid: str) -> dict | None:
        """Fetch tree data from IPFS gateways."""
        # Check cache first
        cached_data = self._load_from_cache(cid)
        if cached_data is not None:
            return cached_data

        # Rate limit gateway requests
        await self._rate_limit()

        # Try each gateway
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for gateway in self.gateways:
                try:
                    url = f"{gateway}{cid}"
                    response = await client.get(url)
                    if response.status_code == 200:
                        try:
                            data = response.json()
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse strikes tree JSON from {gateway}: {e}")
                            continue
                        # Cache the successful result
                        self._save_to_cache(cid, data)
                        return data
                except Exception as e:
                    logger.debug(f"IPFS gateway {gateway} failed for strikes CID {cid}: {e}")
                    continue

        logger.warning(f"All IPFS gateways failed for strikes CID {cid}")
        return None

    @cached(ttl=300)  # Cache parsed tree for 5 minutes
    async def fetch_strikes_tree(self) -> dict | None:
        """
        Fetch and return the full strikes tree.

        Returns dict with:
        - format: "standard-v1"
        - leafEncoding: ["uint256", "bytes", "uint256[]"]
        - tree: list of merkle tree nodes
        - values: list of {treeIndex, value: [operatorId, pubkey, strikesArray]}
        """
        cid = await self.get_tree_cid()
        if not cid:
            return None
        return await self._fetch_tree_from_ipfs(cid)

    async def get_operator_strikes(
        self, operator_id: int, curve_id: int | None = None
    ) -> list[ValidatorStrikes]:
        """
        Get strikes for all validators belonging to an operator.

        Args:
            operator_id: The CSM operator ID
            curve_id: The operator's bond curve ID (determines strike threshold)
                     If None, defaults to 3 strikes (permissionless threshold)

        Returns:
            List of ValidatorStrikes for validators with any strikes.
            Validators with 0 strikes are not included in the tree.
        """
        tree_data = await self.fetch_strikes_tree()
        if not tree_data:
            return []

        values = tree_data.get("values", [])
        operator_strikes = []

        # Determine strike threshold based on operator type
        strike_threshold = get_strike_threshold(curve_id) if curve_id is not None else DEFAULT_STRIKE_THRESHOLD

        for entry in values:
            value = entry.get("value", [])
            if len(value) < 3:
                continue

            entry_operator_id = value[0]
            pubkey = value[1]
            strikes_array = value[2]

            # Validate types - operator_id must be an int
            if not isinstance(entry_operator_id, int):
                try:
                    entry_operator_id = int(entry_operator_id)
                except (ValueError, TypeError):
                    continue

            if entry_operator_id != operator_id:
                continue

            # Ensure pubkey is a string
            if not isinstance(pubkey, str):
                pubkey = str(pubkey) if pubkey else ""

            # Count total strikes (sum of the 6-frame array), filtering non-numeric values
            if isinstance(strikes_array, list):
                strike_count = sum(s for s in strikes_array if isinstance(s, (int, float)))
            else:
                strike_count = 0

            operator_strikes.append(
                ValidatorStrikes(
                    pubkey=pubkey,
                    strikes=strikes_array if isinstance(strikes_array, list) else [],
                    strike_count=strike_count,
                    strike_threshold=strike_threshold,
                    at_ejection_risk=strike_count >= strike_threshold,
                )
            )

        return operator_strikes

    async def get_operator_strike_summary(
        self, operator_id: int, curve_id: int | None = None
    ) -> dict[str, int]:
        """
        Get a summary of strikes for an operator.

        Args:
            operator_id: The CSM operator ID
            curve_id: The operator's bond curve ID (determines strike threshold)

        Returns:
            Dict with:
            - total_validators_with_strikes: Count of validators with any strikes
            - validators_at_risk: Count of validators at ejection risk (>= threshold)
            - validators_near_ejection: Count one strike away from ejection
            - total_strikes: Sum of all strikes across all validators
            - max_strikes: Highest strike count on any single validator
            - strike_threshold: The ejection threshold for this operator type
        """
        strikes = await self.get_operator_strikes(operator_id, curve_id)
        strike_threshold = get_strike_threshold(curve_id) if curve_id is not None else DEFAULT_STRIKE_THRESHOLD

        return {
            "total_validators_with_strikes": len(strikes),
            "validators_at_risk": sum(1 for s in strikes if s.at_ejection_risk),
            "validators_near_ejection": sum(1 for s in strikes if s.strike_count == strike_threshold - 1),
            "total_strikes": sum(s.strike_count for s in strikes),
            "max_strikes": max((s.strike_count for s in strikes), default=0),
            "strike_threshold": strike_threshold,
        }

    def clear_cache(self) -> None:
        """Clear all cached strikes data."""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink(missing_ok=True)
