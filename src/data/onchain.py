"""On-chain data fetching via Web3."""

import asyncio
import logging
from decimal import Decimal
from functools import partial

from web3 import Web3

logger = logging.getLogger(__name__)

from ..core.config import get_settings
from ..core.contracts import (
    CSACCOUNTING_ABI,
    CSFEEDISTRIBUTOR_ABI,
    CSMODULE_ABI,
    STETH_ABI,
    WITHDRAWAL_QUEUE_ABI,
)
from ..core.types import BondSummary, NodeOperator
from .cache import cached
from .etherscan import EtherscanProvider
from .known_cids import KNOWN_DISTRIBUTION_LOGS


class OnChainDataProvider:
    """Fetches data from Ethereum contracts."""

    def __init__(self, rpc_url: str | None = None):
        self.settings = get_settings()
        self.w3 = Web3(
            Web3.HTTPProvider(
                rpc_url or self.settings.eth_rpc_url,
                request_kwargs={"timeout": 30},
            )
        )

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
        self.withdrawal_queue = self.w3.eth.contract(
            address=Web3.to_checksum_address(self.settings.withdrawal_queue_address),
            abi=WITHDRAWAL_QUEUE_ABI,
        )

    @cached(ttl=60)
    async def get_node_operators_count(self) -> int:
        """Get total number of node operators."""
        return await asyncio.to_thread(
            self.csmodule.functions.getNodeOperatorsCount().call
        )

    @cached(ttl=300)
    async def get_node_operator(self, operator_id: int) -> NodeOperator:
        """Get node operator data by ID."""
        data = await asyncio.to_thread(
            self.csmodule.functions.getNodeOperator(operator_id).call
        )
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
                    def run_batch():
                        with self.w3.batch_requests() as batch:
                            for op_id in range(start, end):
                                batch.add(self.csmodule.functions.getNodeOperator(op_id))
                            return batch.execute()

                    results = await asyncio.to_thread(run_batch)

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
                    data = await asyncio.to_thread(
                        self.csmodule.functions.getNodeOperator(op_id).call
                    )
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

    @cached(ttl=300)
    async def get_bond_curve_id(self, operator_id: int) -> int:
        """Get the bond curve ID for an operator.

        Returns:
            0 = Permissionless (2.4 ETH first validator, 1.3 ETH subsequent)
            1 = ICS/Legacy EA (1.5 ETH first validator, 1.3 ETH subsequent)
        """
        try:
            return await asyncio.to_thread(
                self.csaccounting.functions.getBondCurveId(operator_id).call
            )
        except Exception:
            # Fall back to 0 (Permissionless) if call fails
            return 0

    @staticmethod
    def calculate_required_bond(validator_count: int, curve_id: int = 0) -> Decimal:
        """Calculate required bond for a given validator count and curve type.

        Args:
            validator_count: Number of validators
            curve_id: Bond curve ID from CSAccounting contract

        Returns:
            Required bond in ETH

        Note:
            Curve IDs on mainnet CSM:
            - Curve 0: Original permissionless (2 ETH first, 1.3 ETH subsequent) - deprecated
            - Curve 1: Original ICS/EA (1.5 ETH first, 1.3 ETH subsequent) - deprecated
            - Curve 2: Current permissionless default (1.5 ETH first, 1.3 ETH subsequent)
            The contract returns curve points directly, but for estimation we use
            standard formulas.
        """
        if validator_count <= 0:
            return Decimal(0)

        # Curve 2 is the current mainnet default (1.5 ETH first, 1.3 ETH subsequent)
        # Curve 0/1 were the original curves, now deprecated
        if curve_id == 0:  # Original Permissionless (deprecated)
            logger.debug(f"Using deprecated curve 0 bond calculation")
            first_bond = Decimal("2.0")
        elif curve_id not in (1, 2):
            logger.warning(f"Unknown curve_id {curve_id}, using default bond calculation")
            first_bond = Decimal("1.5")
        else:  # Curve 1, 2 - current default curves
            first_bond = Decimal("1.5")

        subsequent_bond = Decimal("1.3")

        if validator_count == 1:
            return first_bond
        else:
            return first_bond + (subsequent_bond * (validator_count - 1))

    @staticmethod
    def get_operator_type_name(curve_id: int) -> str:
        """Get human-readable operator type from curve ID.

        Args:
            curve_id: Bond curve ID from CSAccounting contract

        Returns:
            Operator type name

        Note:
            Curve IDs on mainnet CSM:
            - Curve 0: Original permissionless (deprecated)
            - Curve 1: Original ICS/EA (deprecated)
            - Curve 2: Current permissionless default
        """
        if curve_id == 0:
            return "Permissionless (Legacy)"
        elif curve_id == 1:
            return "ICS/Legacy EA"
        elif curve_id == 2:
            return "Permissionless"
        else:
            return f"Custom (Curve {curve_id})"

    @cached(ttl=60)
    async def get_bond_summary(self, operator_id: int) -> BondSummary:
        """Get bond summary for an operator."""
        current, required = await asyncio.to_thread(
            self.csaccounting.functions.getBondSummary(operator_id).call
        )

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
        return await asyncio.to_thread(
            self.csfeedistributor.functions.distributedShares(operator_id).call
        )

    @cached(ttl=60)
    async def shares_to_eth(self, shares: int) -> Decimal:
        """Convert stETH shares to ETH value."""
        if shares == 0:
            return Decimal(0)
        eth_wei = await asyncio.to_thread(
            self.steth.functions.getPooledEthByShares(shares).call
        )
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
            keys_bytes = await asyncio.to_thread(
                self.csmodule.functions.getSigningKeys(
                    operator_id, batch_start, batch_count
                ).call
            )
            # Each key is 48 bytes
            for i in range(0, len(keys_bytes), 48):
                key = "0x" + keys_bytes[i : i + 48].hex()
                keys.append(key)

        return keys

    async def get_current_log_cid(self) -> str:
        """Get the current distribution log CID from the contract."""
        return await asyncio.to_thread(
            self.csfeedistributor.functions.logCid().call
        )

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
            current_cid = await self.get_current_log_cid()
            if current_cid:
                current_block = await asyncio.to_thread(
                    lambda: self.w3.eth.block_number
                )
                return [{"block": current_block, "logCid": current_cid}]
        except Exception as e:
            logger.debug(f"Failed to get current log CID as fallback: {e}")

        return []

    async def _query_events_chunked(
        self, start_block: int, chunk_size: int = 10000
    ) -> list[dict]:
        """Query events in smaller chunks to work around RPC limitations."""
        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []

        for from_block in range(start_block, current_block, chunk_size):
            to_block = min(from_block + chunk_size - 1, current_block)
            try:
                events = await asyncio.to_thread(
                    partial(
                        self.csfeedistributor.events.DistributionLogUpdated.get_logs,
                        from_block=from_block,
                        to_block=to_block,
                    )
                )
                for e in events:
                    all_events.append(
                        {"block": e["blockNumber"], "logCid": e["args"]["logCid"]}
                    )
            except Exception:
                # If chunked queries fail, give up on this method
                return []

        return sorted(all_events, key=lambda x: x["block"])

    @cached(ttl=3600)  # Cache for 1 hour
    async def get_withdrawal_history(
        self, reward_address: str, start_block: int | None = None
    ) -> list[dict]:
        """
        Get complete withdrawal history for an operator's reward address.

        Combines multiple withdrawal types:
        1. stETH Transfer events from CSAccounting (claimRewardsStETH)
        2. unstETH withdrawal requests/claims (claimRewardsUnstETH)

        Args:
            reward_address: The operator's reward address
            start_block: Starting block number (default: CSM deployment ~20873000)

        Returns:
            List of withdrawal events with block, tx_hash, shares, timestamp, and type
        """
        if start_block is None:
            start_block = 20873000  # CSM deployment block

        reward_address = Web3.to_checksum_address(reward_address)

        # Fetch both stETH and unstETH withdrawals
        steth_events = await self._get_steth_withdrawals(reward_address, start_block)
        unsteth_events = await self._get_unsteth_withdrawals(reward_address, start_block)

        # Combine and sort by block number
        all_events = steth_events + unsteth_events
        all_events.sort(key=lambda x: x["block_number"])

        return all_events

    async def _get_steth_withdrawals(
        self, reward_address: str, start_block: int
    ) -> list[dict]:
        """Get stETH direct transfer withdrawals (claimRewardsStETH)."""
        csaccounting_address = self.settings.csaccounting_address

        # 1. Try Etherscan API first (most reliable)
        etherscan = EtherscanProvider()
        if etherscan.is_available():
            events = await etherscan.get_transfer_events(
                token_address=self.settings.steth_address,
                from_address=csaccounting_address,
                to_address=reward_address,
                from_block=start_block,
            )
            if events:
                enriched = await self._enrich_withdrawal_events(events)
                # Mark as stETH type
                for e in enriched:
                    e["withdrawal_type"] = "stETH"
                return enriched

        # 2. Try chunked RPC queries
        events = await self._query_transfer_events_chunked(
            csaccounting_address, reward_address, start_block
        )
        if events:
            enriched = await self._enrich_withdrawal_events(events)
            for e in enriched:
                e["withdrawal_type"] = "stETH"
            return enriched

        return []

    async def _get_unsteth_withdrawals(
        self, reward_address: str, start_block: int
    ) -> list[dict]:
        """Get unstETH withdrawal requests (claimRewardsUnstETH).

        Queries WithdrawalRequested events where CSAccounting is the requestor
        and the reward_address is the owner of the withdrawal NFT.
        """
        csaccounting_address = self.settings.csaccounting_address

        # Try Etherscan API first
        etherscan = EtherscanProvider()
        if etherscan.is_available():
            events = await etherscan.get_withdrawal_requested_events(
                contract_address=self.settings.withdrawal_queue_address,
                requestor=csaccounting_address,
                owner=reward_address,
                from_block=start_block,
            )
            if events:
                return await self._enrich_unsteth_events(events, reward_address)

        # Fallback to chunked RPC queries
        events = await self._query_withdrawal_requested_chunked(
            csaccounting_address, reward_address, start_block
        )
        if events:
            return await self._enrich_unsteth_events(events, reward_address)

        return []

    async def _query_withdrawal_requested_chunked(
        self,
        requestor: str,
        owner: str,
        start_block: int,
        chunk_size: int = 10000,
    ) -> list[dict]:
        """Query WithdrawalRequested events in chunks via RPC."""
        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []

        requestor = Web3.to_checksum_address(requestor)
        owner = Web3.to_checksum_address(owner)

        for from_blk in range(start_block, current_block, chunk_size):
            to_blk = min(from_blk + chunk_size - 1, current_block)
            try:
                events = await asyncio.to_thread(
                    partial(
                        self.withdrawal_queue.events.WithdrawalRequested.get_logs,
                        from_block=from_blk,
                        to_block=to_blk,
                        argument_filters={
                            "requestor": requestor,
                            "owner": owner,
                        },
                    )
                )
                for e in events:
                    all_events.append(
                        {
                            "request_id": e["args"]["requestId"],
                            "block": e["blockNumber"],
                            "tx_hash": e["transactionHash"].hex(),
                            "amount_steth": e["args"]["amountOfStETH"],
                            "amount_shares": e["args"]["amountOfShares"],
                        }
                    )
            except Exception:
                # If chunked queries fail, give up on this method
                return []

        return sorted(all_events, key=lambda x: x["block"])

    async def _enrich_unsteth_events(
        self, events: list[dict], reward_address: str
    ) -> list[dict]:
        """Add timestamps, status, and claim info to unstETH events."""
        from datetime import datetime, timezone

        if not events:
            return []

        # Get status for all request IDs
        request_ids = [e["request_id"] for e in events]
        try:
            statuses = await asyncio.to_thread(
                self.withdrawal_queue.functions.getWithdrawalStatus(request_ids).call
            )
        except Exception:
            # If status query fails, set all as unknown
            statuses = [None] * len(events)

        # Get claim events for this address
        claim_events = await self._get_withdrawal_claimed_events(reward_address)
        claims_by_request = {c["request_id"]: c for c in claim_events}

        enriched = []
        for i, event in enumerate(events):
            try:
                # Get block timestamp
                block = await asyncio.to_thread(
                    partial(self.w3.eth.get_block, event["block"])
                )
                timestamp = datetime.fromtimestamp(
                    block["timestamp"], tz=timezone.utc
                ).isoformat()

                # Determine status from contract query
                status = statuses[i] if i < len(statuses) and statuses[i] else None
                if status:
                    if status[5]:  # isClaimed
                        withdrawal_status = "claimed"
                    elif status[4]:  # isFinalized
                        withdrawal_status = "finalized"
                    else:
                        withdrawal_status = "pending"
                else:
                    withdrawal_status = "unknown"

                # Convert shares to ETH for display
                shares = event.get("amount_shares", event.get("value", 0))
                eth_value = await self.shares_to_eth(shares)

                enriched_event = {
                    "block_number": event["block"],
                    "timestamp": timestamp,
                    "shares": shares,
                    "eth_value": float(eth_value),
                    "tx_hash": event["tx_hash"],
                    "withdrawal_type": "unstETH",
                    "request_id": event["request_id"],
                    "status": withdrawal_status,
                }

                # Add claim info if claimed
                claim = claims_by_request.get(event["request_id"])
                if claim:
                    enriched_event["claimed_eth"] = claim["amount_eth"]
                    enriched_event["claim_tx_hash"] = claim["tx_hash"]
                    # Get claim timestamp
                    try:
                        claim_block = await asyncio.to_thread(
                            partial(self.w3.eth.get_block, claim["block"])
                        )
                        enriched_event["claim_timestamp"] = datetime.fromtimestamp(
                            claim_block["timestamp"], tz=timezone.utc
                        ).isoformat()
                    except Exception as e:
                        logger.debug(f"Failed to get claim timestamp for block {claim.get('block')}: {e}")

                enriched.append(enriched_event)
            except Exception as e:
                logger.debug(f"Failed to enrich withdrawal event: {e}")
                continue

        return enriched

    async def _get_withdrawal_claimed_events(
        self, receiver: str, start_block: int = 20873000
    ) -> list[dict]:
        """Get WithdrawalClaimed events for a receiver address."""
        receiver = Web3.to_checksum_address(receiver)

        # Try Etherscan first
        etherscan = EtherscanProvider()
        if etherscan.is_available():
            events = await etherscan.get_withdrawal_claimed_events(
                contract_address=self.settings.withdrawal_queue_address,
                receiver=receiver,
                from_block=start_block,
            )
            if events:
                return events

        # RPC fallback - query in chunks
        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []

        for from_blk in range(start_block, current_block, 10000):
            to_blk = min(from_blk + 9999, current_block)
            try:
                logs = await asyncio.to_thread(
                    partial(
                        self.withdrawal_queue.events.WithdrawalClaimed.get_logs,
                        from_block=from_blk,
                        to_block=to_blk,
                        argument_filters={"receiver": receiver},
                    )
                )
                for e in logs:
                    all_events.append(
                        {
                            "request_id": e["args"]["requestId"],
                            "tx_hash": e["transactionHash"].hex(),
                            "amount_eth": e["args"]["amountOfETH"] / 10**18,
                            "block": e["blockNumber"],
                        }
                    )
            except Exception:
                continue

        return all_events

    async def _query_transfer_events_chunked(
        self,
        from_address: str,
        to_address: str,
        start_block: int,
        chunk_size: int = 10000,
    ) -> list[dict]:
        """Query Transfer events in smaller chunks."""
        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []

        from_address = Web3.to_checksum_address(from_address)
        to_address = Web3.to_checksum_address(to_address)

        for from_blk in range(start_block, current_block, chunk_size):
            to_blk = min(from_blk + chunk_size - 1, current_block)
            try:
                events = await asyncio.to_thread(
                    partial(
                        self.steth.events.Transfer.get_logs,
                        from_block=from_blk,
                        to_block=to_blk,
                        argument_filters={
                            "from": from_address,
                            "to": to_address,
                        },
                    )
                )
                for e in events:
                    all_events.append(
                        {
                            "block": e["blockNumber"],
                            "tx_hash": e["transactionHash"].hex(),
                            "value": e["args"]["value"],
                        }
                    )
            except Exception:
                # If chunked queries fail, give up on this method
                return []

        return sorted(all_events, key=lambda x: x["block"])

    async def _enrich_withdrawal_events(self, events: list[dict]) -> list[dict]:
        """Add timestamps and ETH values to withdrawal events."""
        from datetime import datetime, timezone

        enriched = []
        for event in events:
            try:
                # Get block timestamp
                block = await asyncio.to_thread(
                    partial(self.w3.eth.get_block, event["block"])
                )
                timestamp = datetime.fromtimestamp(
                    block["timestamp"], tz=timezone.utc
                ).isoformat()

                # Convert shares to ETH (using current rate as approximation)
                eth_value = await self.shares_to_eth(event["value"])

                enriched.append(
                    {
                        "block_number": event["block"],
                        "timestamp": timestamp,
                        "shares": event["value"],
                        "eth_value": float(eth_value),
                        "tx_hash": event["tx_hash"],
                    }
                )
            except Exception:
                # Skip events we can't enrich
                continue

        return enriched
