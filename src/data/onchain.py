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
from .cache import SimpleCache, cached
from .discovered_cids import load_discovered_cids, merge_cid_sources, record_new_cids
from .etherscan import EtherscanProvider
from .known_cids import KNOWN_DISTRIBUTION_LOGS

# Manual cache for distribution log history (adaptive TTL)
_distribution_cache = SimpleCache()


class OnChainDataProvider:
    """Fetches data from Ethereum contracts."""

    def __init__(self, rpc_url: str | None = None):
        self.settings = get_settings()
        self._data_warnings: list[str] = []
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

    def get_and_clear_warnings(self) -> list[str]:
        """Return accumulated data warnings and clear the list."""
        warnings = self._data_warnings.copy()
        self._data_warnings.clear()
        return warnings

    async def get_current_log_cid(self) -> str:
        """Get the current distribution log CID from the contract."""
        return await asyncio.to_thread(
            self.csfeedistributor.functions.logCid().call
        )

    async def get_distribution_log_history(
        self, start_block: int | None = None
    ) -> list[dict]:
        """
        Query DistributionLogUpdated events to get historical logCids.

        Merges all available sources (known CIDs, runtime cache, Etherscan,
        RPC scanning, and contract state) and always includes the current
        distribution. Persists discoveries to a runtime cache on disk.

        Args:
            start_block: Starting block number (default: CSM deployment ~20873000)

        Returns:
            List of {block, logCid} dicts, sorted by block number (oldest first)
        """
        # Check manual cache first
        cache_key = "distribution_log_history"
        from .cache import _MISSING

        cached_result = _distribution_cache.get(cache_key)
        if cached_result is not _MISSING:
            cids, cached_warnings = cached_result
            # Re-emit cached warnings so every caller sees them
            self._data_warnings.extend(cached_warnings)
            return cids

        # CSM was deployed around block 20873000 (Dec 2024)
        if start_block is None:
            start_block = 20873000

        # 1. Start with all known sources merged
        base_cids = merge_cid_sources(KNOWN_DISTRIBUTION_LOGS, load_discovered_cids())
        result_complete = False
        # Track warnings local to this discovery call (not IPFS/other concerns)
        local_warnings: list[str] = []

        # 2. Try Etherscan API (comprehensive, most reliable)
        etherscan = EtherscanProvider()
        if etherscan.is_available():
            events = await etherscan.get_distribution_log_events(
                self.settings.csfeedistributor_address,
                start_block,
            )
            if events:
                logger.info(f"Fetched {len(events)} distributions via Etherscan API")
                base_cids = merge_cid_sources(base_cids, events)
                result_complete = True
            else:
                local_warnings.append(
                    "Etherscan API returned no results. "
                    "Check your API key or try again later."
                )
        else:
            logger.info(
                "No Etherscan API key configured — using RPC + known CIDs fallback"
            )

        # 3. RPC scan for events after the last known block
        if not result_complete:
            last_known_block = (
                base_cids[-1]["block"] if base_cids else start_block
            )
            rpc_events = await self._query_events_chunked(last_known_block + 1)
            if rpc_events:
                base_cids = merge_cid_sources(base_cids, rpc_events)

        # 4. Always get current logCid from contract and merge it in
        current_cid = None
        current_block = None
        try:
            current_cid = await self.get_current_log_cid()
            current_block = await asyncio.to_thread(
                lambda: self.w3.eth.block_number
            )
            if current_cid:
                existing_cids = {e["logCid"] for e in base_cids}
                if current_cid not in existing_cids:
                    base_cids.append(
                        {"block": current_block, "logCid": current_cid}
                    )
                    base_cids.sort(key=lambda x: x["block"])
                    logger.info(
                        f"Added current distribution CID from contract "
                        f"(not found via other methods)"
                    )
        except Exception as e:
            logger.warning(f"Failed to get current log CID from contract: {e}")

        # 5. Persist any newly discovered CIDs to runtime cache
        record_new_cids(base_cids)

        # 6. Completeness check
        if not result_complete and current_cid:
            latest_cid = base_cids[-1]["logCid"] if base_cids else None
            # We have the current CID (added in step 4), but may be missing
            # intermediate ones between known_cids and the current CID
            known_count = len(base_cids)
            blocks_spanned = current_block - start_block if current_block else 0
            expected_approx = max(1, blocks_spanned // 200000)
            if known_count < expected_approx * 0.8:
                local_warnings.append(
                    f"Distribution history may be incomplete: found {known_count} "
                    f"distributions, expected ~{expected_approx}. "
                    f"Configure etherscan_api_key in .env for complete data."
                )

        # 7. Cache with adaptive TTL (store only discovery warnings for re-emission)
        cache_ttl = 3600 if result_complete else 300
        _distribution_cache.set(cache_key, (base_cids, local_warnings), cache_ttl)
        self._data_warnings.extend(local_warnings)

        logger.info(
            f"Distribution history: {len(base_cids)} total distributions "
            f"(complete={result_complete})"
        )
        return base_cids

    async def _query_events_chunked(
        self, start_block: int, chunk_size: int = 50000
    ) -> list[dict]:
        """Query events in chunks to work around RPC limitations.

        Uses larger chunks (50k blocks) since DistributionLogUpdated events
        are rare (~1 per 200k blocks). Includes exponential backoff and
        adaptive chunk sizing on failure.
        """
        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []
        consecutive_failures = 0
        max_consecutive_failures = 10
        current_chunk_size = chunk_size

        from_block = start_block
        while from_block < current_block:
            to_block = min(from_block + current_chunk_size - 1, current_block)
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
                consecutive_failures = 0
                current_chunk_size = chunk_size  # Reset to full size on success
                from_block = to_block + 1
            except Exception as e:
                # Try halving chunk size before counting as a real failure
                if current_chunk_size > 10000:
                    current_chunk_size = current_chunk_size // 2
                    logger.debug(
                        f"RPC query failed for {from_block}-{to_block}, "
                        f"reducing chunk size to {current_chunk_size}: {e}"
                    )
                    continue  # Retry same from_block with smaller chunk

                # Chunk is at minimum size — this is a real failure
                consecutive_failures += 1
                logger.debug(
                    f"RPC event query failed for blocks {from_block}-{to_block}: {e}"
                )
                if consecutive_failures >= max_consecutive_failures:
                    remaining = current_block - from_block
                    self._data_warnings.append(
                        f"RPC event scanning stopped early: {remaining:,} blocks "
                        f"unscanned after {max_consecutive_failures} consecutive "
                        f"failures. Some distributions may be missing."
                    )
                    logger.warning(
                        f"Giving up on RPC event queries after "
                        f"{max_consecutive_failures} consecutive failures "
                        f"({remaining:,} blocks remaining)"
                    )
                    break

                # Exponential backoff, then advance past this chunk
                backoff = min(2**consecutive_failures, 10)
                logger.debug(f"Backing off {backoff}s before next RPC attempt")
                await asyncio.sleep(backoff)
                from_block = to_block + 1
                current_chunk_size = chunk_size  # Reset chunk size for next range

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

    @cached(ttl=3600)  # Cache for 1 hour since historical events don't change
    async def get_historical_apr_data(self) -> list[dict]:
        """Fetch historical stETH APR data from TokenRebased events via RPC.

        Returns list of {block, apr, blockTime} sorted by block ascending.
        Returns empty list if RPC log queries fail.
        """
        try:
            events = await self._fetch_token_rebased_events()
        except Exception as e:
            logger.warning(f"Failed to fetch TokenRebased events: {e}")
            return []

        results = []
        for event in events:
            args = event["args"]
            pre_total_shares = args["preTotalShares"]
            pre_total_ether = args["preTotalEther"]
            post_total_shares = args["postTotalShares"]
            post_total_ether = args["postTotalEther"]
            time_elapsed = args["timeElapsed"]

            if pre_total_shares == 0 or post_total_shares == 0 or time_elapsed == 0:
                continue

            # APR = ((postEther/postShares) / (preEther/preShares) - 1) * (365 * 86400 / timeElapsed) * 100
            pre_rate = pre_total_ether / pre_total_shares
            post_rate = post_total_ether / post_total_shares
            apr = (post_rate / pre_rate - 1) * (365 * 86400 / time_elapsed) * 100

            results.append({
                "block": str(event["blockNumber"]),
                "apr": str(apr),
                "blockTime": str(args["reportTimestamp"]),
            })

        return results

    async def _fetch_token_rebased_events(
        self, start_block: int = 20_000_000, chunk_size: int = 50_000
    ) -> list:
        """Fetch TokenRebased events from stETH contract in chunks."""
        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []
        consecutive_failures = 0
        max_consecutive_failures = 3

        for from_block in range(start_block, current_block, chunk_size):
            to_block = min(from_block + chunk_size - 1, current_block)
            try:
                events = await asyncio.to_thread(
                    partial(
                        self.steth.events.TokenRebased.get_logs,
                        from_block=from_block,
                        to_block=to_block,
                    )
                )
                all_events.extend(events)
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                logger.debug(
                    f"TokenRebased event query failed for blocks {from_block}-{to_block}: {e}"
                )
                if consecutive_failures >= max_consecutive_failures:
                    logger.debug(
                        f"Giving up on TokenRebased event queries after "
                        f"{max_consecutive_failures} consecutive failures"
                    )
                    break

        return sorted(all_events, key=lambda e: e["blockNumber"])

    # Mapping from event name to (flow_direction, event_type_key)
    _BOND_EVENT_MAP = {
        "BondDepositedETH": (1, "deposit_eth"),
        "BondDepositedStETH": (1, "deposit_steth"),
        "BondDepositedWstETH": (1, "deposit_wsteth"),
        "BondClaimedStETH": (-1, "claim_steth"),
        "BondClaimedUnstETH": (-1, "claim_unsteth"),
        "BondClaimedWstETH": (-1, "claim_wsteth"),
        "BondBurned": (-1, "burned"),
        "BondCharged": (-1, "charged"),
    }

    @cached(ttl=3600)
    async def get_bond_event_history(
        self, operator_id: int, start_block: int | None = None
    ) -> list[dict]:
        """Fetch all bond deposit/claim/burn events for an operator.

        Returns list of dicts sorted by block number, each containing:
        event_type, block_number, timestamp, amount_wei, amount_eth, tx_hash, flow_direction
        """
        from datetime import datetime as dt_cls
        from datetime import timezone as tz

        if start_block is None:
            start_block = 20873000  # CSM deployment block

        current_block = await asyncio.to_thread(lambda: self.w3.eth.block_number)
        all_events = []
        chunk_size = 10000

        for event_name, (flow_dir, event_type_key) in self._BOND_EVENT_MAP.items():
            event_obj = getattr(self.csaccounting.events, event_name, None)
            if event_obj is None:
                continue

            consecutive_failures = 0
            for from_blk in range(start_block, current_block, chunk_size):
                to_blk = min(from_blk + chunk_size - 1, current_block)
                try:
                    logs = await asyncio.to_thread(
                        partial(
                            event_obj.get_logs,
                            from_block=from_blk,
                            to_block=to_blk,
                            argument_filters={"nodeOperatorId": operator_id},
                        )
                    )
                    for log in logs:
                        # BondBurned/BondCharged use "burnedAmount"/"chargedAmount" as actual amount
                        if event_name == "BondBurned":
                            amount_wei = log["args"]["burnedAmount"]
                        elif event_name == "BondCharged":
                            amount_wei = log["args"]["chargedAmount"]
                        else:
                            amount_wei = log["args"]["amount"]

                        all_events.append({
                            "event_name": event_name,
                            "event_type": event_type_key,
                            "block_number": log["blockNumber"],
                            "amount_wei": amount_wei,
                            # wstETH amounts are approximate as ETH (wstETH deposits are rare in CSM)
                            "amount_eth": amount_wei / 10**18,
                            "tx_hash": log["transactionHash"].hex(),
                            "flow_direction": flow_dir,
                        })
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    logger.debug(
                        f"Bond event query failed for {event_name} blocks {from_blk}-{to_blk}: {e}"
                    )
                    if consecutive_failures >= 3:
                        break

        # Sort by block number and enrich with timestamps
        all_events.sort(key=lambda x: x["block_number"])

        # Batch-fetch timestamps for unique blocks
        unique_blocks = list({e["block_number"] for e in all_events})
        block_timestamps = {}
        for blk_num in unique_blocks:
            try:
                block_data = await asyncio.to_thread(
                    partial(self.w3.eth.get_block, blk_num)
                )
                block_timestamps[blk_num] = dt_cls.fromtimestamp(
                    block_data["timestamp"], tz=tz.utc
                ).isoformat()
            except Exception:
                block_timestamps[blk_num] = ""

        for event in all_events:
            event["timestamp"] = block_timestamps.get(event["block_number"], "")

        return all_events

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

                # stETH Transfer 'value' is the rebasing token amount in wei (1:1 with ETH).
                # Stored as 'shares' to satisfy the WithdrawalEvent schema, but NOTE: this is
                # NOT stETH shares — it is the stETH balance amount (token units, 18 decimals).
                # For unstETH events, 'shares' really are stETH shares (different unit).
                steth_amount = event["value"]
                eth_value = Decimal(steth_amount) / Decimal(10**18)

                enriched.append(
                    {
                        "block_number": event["block"],
                        "timestamp": timestamp,
                        "shares": steth_amount,  # stETH token amount in wei (not stETH shares)
                        "eth_value": float(eth_value),
                        "tx_hash": event["tx_hash"],
                    }
                )
            except Exception:
                # Skip events we can't enrich
                continue

        return enriched
