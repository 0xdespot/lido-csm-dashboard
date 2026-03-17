"""Etherscan API client for event queries."""

import json
import logging
from decimal import Decimal

import httpx
from web3 import Web3

from ..core.config import get_settings

logger = logging.getLogger(__name__)


class EtherscanProvider:
    """Query contract events via Etherscan API."""

    BASE_URL = "https://api.etherscan.io/v2/api"

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.etherscan_api_key

    def is_available(self) -> bool:
        """Check if Etherscan API key is configured."""
        return bool(self.api_key)

    async def get_distribution_log_events(
        self,
        contract_address: str,
        from_block: int,
        to_block: str | int = "latest",
    ) -> list[dict]:
        """Query DistributionLogUpdated events from Etherscan."""
        if not self.api_key:
            return []

        # Event topic: keccak256("DistributionLogUpdated(string)")
        topic0 = Web3.keccak(text="DistributionLogUpdated(string)").hex()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "chainid": 1,
                    "module": "logs",
                    "action": "getLogs",
                    "address": contract_address,
                    "topic0": topic0,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "apikey": self.api_key,
                },
            )

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Etherscan response: {e}")
                return []

            if data.get("status") != "1":
                msg = data.get("message", "")
                result = data.get("result", "")
                logger.warning(f"Etherscan API error (distribution logs): {msg} - {result}")
                return []

            results = []
            for log in data.get("result", []):
                # Decode the logCid from the data field
                # The data is ABI-encoded string: offset (32 bytes) + length (32 bytes) + data
                raw_data = log["data"]
                # Skip the offset (0x40 = 64 chars after 0x) and length prefix
                # String data starts at byte 64 (128 hex chars after 0x)
                if len(raw_data) > 130:  # 0x + 128 chars minimum
                    # Extract length from bytes 32-64
                    length_hex = raw_data[66:130]
                    length = int(length_hex, 16)
                    # Extract string data starting at byte 64
                    string_data = raw_data[130 : 130 + length * 2]
                    try:
                        log_cid = bytes.fromhex(string_data).decode("utf-8")
                        results.append(
                            {
                                "block": int(log["blockNumber"], 16),
                                "logCid": log_cid,
                            }
                        )
                    except (ValueError, UnicodeDecodeError):
                        continue

            return sorted(results, key=lambda x: x["block"])

    async def get_transfer_events(
        self,
        token_address: str,
        from_address: str,
        to_address: str,
        from_block: int,
        to_block: str | int = "latest",
    ) -> list[dict]:
        """Query Transfer events from Etherscan for a specific from/to pair."""
        if not self.api_key:
            return []

        # Event topic: keccak256("Transfer(address,address,uint256)")
        topic0 = Web3.keccak(text="Transfer(address,address,uint256)").hex()
        # topic1 is indexed 'from' address (padded to 32 bytes)
        topic1 = "0x" + from_address.lower().replace("0x", "").zfill(64)
        # topic2 is indexed 'to' address (padded to 32 bytes)
        topic2 = "0x" + to_address.lower().replace("0x", "").zfill(64)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "chainid": 1,
                    "module": "logs",
                    "action": "getLogs",
                    "address": token_address,
                    "topic0": topic0,
                    "topic1": topic1,
                    "topic2": topic2,
                    "topic0_1_opr": "and",
                    "topic1_2_opr": "and",
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "apikey": self.api_key,
                },
            )

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Etherscan transfer events response: {e}")
                return []

            if data.get("status") != "1":
                msg = data.get("message", "")
                result = data.get("result", "")
                logger.warning(f"Etherscan API error (transfer events): {msg} - {result}")
                return []

            results = []
            for log in data.get("result", []):
                # The data field contains the non-indexed value (amount)
                raw_data = log["data"]
                try:
                    value = int(raw_data, 16)
                    results.append(
                        {
                            "block": int(log["blockNumber"], 16),
                            "tx_hash": log["transactionHash"],
                            "value": value,
                        }
                    )
                except (ValueError, TypeError):
                    continue

            return sorted(results, key=lambda x: x["block"])

    async def get_withdrawal_requested_events(
        self,
        contract_address: str,
        requestor: str,
        owner: str,
        from_block: int,
        to_block: str | int = "latest",
    ) -> list[dict]:
        """Query WithdrawalRequested events from Etherscan.

        Args:
            contract_address: WithdrawalQueue contract address
            requestor: Address that requested the withdrawal (CSAccounting)
            owner: Address that owns the unstETH NFT (reward_address)
            from_block: Starting block
            to_block: Ending block

        Returns:
            List of withdrawal request events
        """
        if not self.api_key:
            return []

        # Event: WithdrawalRequested(uint256 indexed requestId, address indexed requestor,
        #                            address indexed owner, uint256 amountOfStETH, uint256 amountOfShares)
        topic0 = Web3.keccak(
            text="WithdrawalRequested(uint256,address,address,uint256,uint256)"
        ).hex()
        # topic1 is indexed requestId - not filtering on this
        # topic2 is indexed 'requestor' address (padded to 32 bytes)
        topic2 = "0x" + requestor.lower().replace("0x", "").zfill(64)
        # topic3 is indexed 'owner' address (padded to 32 bytes)
        topic3 = "0x" + owner.lower().replace("0x", "").zfill(64)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "chainid": 1,
                    "module": "logs",
                    "action": "getLogs",
                    "address": contract_address,
                    "topic0": topic0,
                    "topic2": topic2,
                    "topic3": topic3,
                    "topic0_2_opr": "and",
                    "topic2_3_opr": "and",
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "apikey": self.api_key,
                },
            )

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Etherscan withdrawal requested events: {e}")
                return []

            if data.get("status") != "1":
                msg = data.get("message", "")
                result = data.get("result", "")
                logger.warning(f"Etherscan API error (withdrawal requested): {msg} - {result}")
                return []

            results = []
            for log in data.get("result", []):
                try:
                    # requestId is topic1 (indexed)
                    request_id = int(log["topics"][1], 16)
                    # amountOfStETH and amountOfShares are in data field
                    raw_data = log["data"]
                    # Each uint256 is 64 hex chars (32 bytes)
                    amount_steth = int(raw_data[2:66], 16)
                    amount_shares = int(raw_data[66:130], 16)

                    results.append(
                        {
                            "request_id": request_id,
                            "block": int(log["blockNumber"], 16),
                            "tx_hash": log["transactionHash"],
                            "amount_steth": amount_steth,
                            "amount_shares": amount_shares,
                        }
                    )
                except (ValueError, TypeError, IndexError):
                    continue

            return sorted(results, key=lambda x: x["block"])

    async def get_withdrawal_claimed_events(
        self,
        contract_address: str,
        receiver: str,
        from_block: int,
        to_block: str | int = "latest",
    ) -> list[dict]:
        """Query WithdrawalClaimed events from Etherscan.

        Args:
            contract_address: WithdrawalQueue contract address
            receiver: Address that received the ETH (reward_address)
            from_block: Starting block
            to_block: Ending block

        Returns:
            List of withdrawal claim events
        """
        if not self.api_key:
            return []

        # Event: WithdrawalClaimed(uint256 indexed requestId, address indexed owner,
        #                          address indexed receiver, uint256 amountOfETH)
        topic0 = Web3.keccak(
            text="WithdrawalClaimed(uint256,address,address,uint256)"
        ).hex()
        # topic3 is indexed 'receiver' address (padded to 32 bytes)
        topic3 = "0x" + receiver.lower().replace("0x", "").zfill(64)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "chainid": 1,
                    "module": "logs",
                    "action": "getLogs",
                    "address": contract_address,
                    "topic0": topic0,
                    "topic3": topic3,
                    "topic0_3_opr": "and",
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "apikey": self.api_key,
                },
            )

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse Etherscan withdrawal claimed events: {e}")
                return []

            if data.get("status") != "1":
                msg = data.get("message", "")
                result = data.get("result", "")
                logger.warning(f"Etherscan API error (withdrawal claimed): {msg} - {result}")
                return []

            results = []
            for log in data.get("result", []):
                try:
                    # requestId is topic1 (indexed)
                    request_id = int(log["topics"][1], 16)
                    # amountOfETH is in data field - use Decimal for precision
                    amount_eth = Decimal(int(log["data"], 16)) / Decimal(10**18)

                    results.append(
                        {
                            "request_id": request_id,
                            "tx_hash": log["transactionHash"],
                            "amount_eth": float(amount_eth),  # Convert to float for JSON serialization
                            "block": int(log["blockNumber"], 16),
                        }
                    )
                except (ValueError, TypeError, IndexError):
                    continue

            return sorted(results, key=lambda x: x["block"])
