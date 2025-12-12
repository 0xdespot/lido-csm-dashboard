"""On-chain data fetching via Web3."""

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


class OnChainDataProvider:
    """Fetches data from Ethereum contracts."""

    def __init__(self, rpc_url: str | None = None):
        settings = get_settings()
        self.w3 = Web3(Web3.HTTPProvider(rpc_url or settings.eth_rpc_url))

        # Initialize contracts
        self.csmodule = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.csmodule_address),
            abi=CSMODULE_ABI,
        )
        self.csaccounting = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.csaccounting_address),
            abi=CSACCOUNTING_ABI,
        )
        self.csfeedistributor = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.csfeedistributor_address),
            abi=CSFEEDISTRIBUTOR_ABI,
        )
        self.steth = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.steth_address),
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
        import time

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
                    time.sleep(0.05)
                except Exception:
                    time.sleep(0.1)  # Longer delay on error
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
