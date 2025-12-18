"""On-chain data fetching via Web3."""

import asyncio
from decimal import Decimal

from web3 import Web3

from ..core.config import get_settings
from ..core.contracts import (
    CSACCOUNTING_ABI,
    CSFEEDISTRIBUTOR_ABI,
    CSMODULE_ABI,
    STETH_ABI,
)
from ..core.types import BondSummary, NodeOperator
from .cache import cached
from .etherscan import EtherscanProvider
from .known_cids import KNOWN_DISTRIBUTION_LOGS


class OnChainDataProvider:
    """Fetches data from Ethereum contracts."""

    def __init__(self, rpc_url: str | None = None):
        self.settings = get_settings()
        self.w3 = Web3(Web3.HTTPProvider(rpc_url or self.settings.eth_rpc_url))

        # Initialize contracts
        self.csmodule = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.settings.csmodule_address),
            abi=CSMODULE_ABI,
        )
        self.csaccounting = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.settings.csaccounting_address),
            abi=CSACCOUNTING_ABI,
        )
        self.csfeedistributor = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.settings.csfeedistributor_address),
            abi=CSFEEDISTRIBUTOR_ABI,
        )
        self.steth = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.settings.steth_address),
            abi=STETH_ABI,
        )

    @cached(ttl=60)
    async def get_node_operators_count(self) -> int:
        """Get total number of node operators."""
        return self.csmodule.functions.getNodeOperatorsCount().call()

    @cached(ttl=300)
    async def get_node_operator(self, operator_id: int) -> NodeOperator:
        """Get node operator data by ID."""
        data = self.csmodule.functions.getNodeOperator(operator_id).call()
        return NodeOperator(
            node_operator_id=operator_id,
            total_added_keys=data[0],
            total_withdrawn_keys=data[1],
            total_deposited_keys=data[2],
            total_vetted_keys=data[3],
            stuck_validators_count=data[4],
            depositable_validators_count=data[5],
            target_limit=data[6],
            target_limit_mode=data[7],
            total_exited_keys=data[8],
            enqueued_count=data[9],
            manager_address=data[10],
            proposed_manager_address=data[11],
            reward_address=data[12],
            proposed_reward_address=data[13],
            extended_manager_permissions=data[14],
        )

    async def find_operator_by_address(self, address: str) -> int | None:
        """
        Find operator ID by manager or reward address.

        Tries batch requests first (faster if RPC supports JSON-RPC batching).
        Falls back to sequential calls with rate limiting if batch fails.
        """
        address = Web3.to_checksum_address(address)
        total = await self.get_node_operators_count()

        # Try batch requests first (not all RPCs support this)
        batch_size = 50
        batch_supported = True

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)

            if batch_supported:
                try:
                    with self.w3.batch_requests() as batch:
                        for op_id in range(start, end):
                            batch.add(self.csmodule.functions.getNodeOperator(op_id))
                        results = batch.execute()

                    for i, data in enumerate(results):
                        op_id = start + i
                        manager = data[10]
                        reward = data[12]
                        if manager.lower() == address.lower() or reward.lower() == address.lower():
                            return op_id
                    continue  # Batch succeeded, move to next batch
                except Exception:
                    # Batch not supported by this RPC, fall back to sequential
                    batch_supported = False

            # Sequential fallback with rate limiting
            for op_id in range(start, end):
                try:
                    data = self.csmodule.functions.getNodeOperator(op_id).call()
                    manager = data[10]
                    reward = data[12]
                    if manager.lower() == address.lower() or reward.lower() == address.lower():
                        return op_id
                    # Small delay to avoid rate limiting on public RPCs
                    await asyncio.sleep(0.05)
                except Exception:
                    await asyncio.sleep(0.1)  # Longer delay on error
                    continue

        return None

    @cached(ttl=60)
    async def get_bond_summary(self, operator_id: int) -> BondSummary:
        """Get bond summary for an operator."""
        current, required = self.csaccounting.functions.getBondSummary(
            operator_id
        ).call()

        current_eth = Decimal(current) / Decimal(10**18)
        required_eth = Decimal(required) / Decimal(10**18)
        excess_eth = max(Decimal(0), current_eth - required_eth)

        return BondSummary(
            current_bond_wei=current,
            required_bond_wei=required,
            current_bond_eth=current_eth,
            required_bond_eth=required_eth,
            excess_bond_eth=excess_eth,
        )

    @cached(ttl=60)
    async def get_distributed_shares(self, operator_id: int) -> int:
        """Get already distributed (claimed) shares for operator."""
        return self.csfeedistributor.functions.distributedShares(operator_id).call()

    @cached(ttl=60)
    async def shares_to_eth(self, shares: int) -> Decimal:
        """Convert stETH shares to ETH value."""
        if shares == 0:
            return Decimal(0)
        eth_wei = self.steth.functions.getPooledEthByShares(shares).call()
        return Decimal(eth_wei) / Decimal(10**18)

    async def get_signing_keys(
        self, operator_id: int, start: int = 0, count: int = 100
    ) -> list[str]:
        """Get validator pubkeys for an operator.

        Fetches in batches of 100 to avoid RPC limits on large operators.
        """
        keys = []
        batch_size = 100

        for batch_start in range(start, start + count, batch_size):
            batch_count = min(batch_size, start + count - batch_start)
            keys_bytes = self.csmodule.functions.getSigningKeys(
                operator_id, batch_start, batch_count
            ).call()
            # Each key is 48 bytes
            for i in range(0, len(keys_bytes), 48):
                key = "0x" + keys_bytes[i : i + 48].hex()
                keys.append(key)

        return keys

    def get_current_log_cid(self) -> str:
        """Get the current distribution log CID from the contract."""
        return self.csfeedistributor.functions.logCid().call()

    @cached(ttl=3600)  # Cache for 1 hour since historical events don't change
    async def get_distribution_log_history(
        self, start_block: int | None = None
    ) -> list[dict]:
        """
        Query DistributionLogUpdated events to get historical logCids.

        Tries multiple methods in order:
        1. Etherscan API (if API key configured) - most reliable
        2. Chunked RPC queries (10k block chunks) - works on some RPCs
        3. Hardcoded known CIDs - fallback for users without API keys
        4. Current logCid from contract - ultimate fallback

        Args:
            start_block: Starting block number (default: CSM deployment ~20873000)

        Returns:
            List of {block, logCid} dicts, sorted by block number (oldest first)
        """
        # CSM was deployed around block 20873000 (Dec 2024)
        if start_block is None:
            start_block = 20873000

        # 1. Try Etherscan API first (most reliable)
        etherscan = EtherscanProvider()
        if etherscan.is_available():
            events = await etherscan.get_distribution_log_events(
                self.settings.csfeedistributor_address,
                start_block,
            )
            if events:
                return events

        # 2. Try chunked RPC queries
        events = await self._query_events_chunked(start_block)
        if events:
            return events

        # 3. Use known historical CIDs as fallback
        if KNOWN_DISTRIBUTION_LOGS:
            return KNOWN_DISTRIBUTION_LOGS

        # 4. Ultimate fallback: current logCid only
        try:
            current_cid = self.get_current_log_cid()
            if current_cid:
                current_block = self.w3.eth.block_number
                return [{"block": current_block, "logCid": current_cid}]
        except Exception:
            pass

        return []

    async def _query_events_chunked(
        self, start_block: int, chunk_size: int = 10000
    ) -> list[dict]:
        """Query events in smaller chunks to work around RPC limitations."""
        current_block = self.w3.eth.block_number
        all_events = []

        for from_block in range(start_block, current_block, chunk_size):
            to_block = min(from_block + chunk_size - 1, current_block)
            try:
                events = self.csfeedistributor.events.DistributionLogUpdated.get_logs(
                    from_block=from_block,
                    to_block=to_block,
                )
                for e in events:
                    all_events.append(
                        {"block": e["blockNumber"], "logCid": e["args"]["logCid"]}
                    )
            except Exception:
                # If chunked queries fail, give up on this method
                return []

        return sorted(all_events, key=lambda x: x["block"])
