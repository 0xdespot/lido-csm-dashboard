"""Etherscan API client for event queries."""

import httpx
from web3 import Web3

from ..core.config import get_settings


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
        topic0 = "0x" + Web3.keccak(text="DistributionLogUpdated(string)").hex()

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

            data = response.json()
            if data.get("status") != "1":
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
        topic0 = "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex()
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

            data = response.json()
            if data.get("status") != "1":
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
