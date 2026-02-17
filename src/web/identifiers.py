"""Identifier parsing and validation helpers for web routes."""

from fastapi import HTTPException
from web3 import Web3

MAX_OPERATOR_ID = 1_000_000


def parse_operator_identifier(identifier: str) -> tuple[str, int | str]:
    """Parse an operator identifier and return ("id"|"address", normalized_value)."""
    if identifier.isdigit():
        operator_id = int(identifier)
        if operator_id > MAX_OPERATOR_ID:
            raise HTTPException(status_code=400, detail="Invalid operator ID")
        return ("id", operator_id)

    if identifier.startswith("0x"):
        if not Web3.is_address(identifier):
            raise HTTPException(status_code=400, detail="Invalid Ethereum address")
        return ("address", Web3.to_checksum_address(identifier))

    raise HTTPException(status_code=400, detail="Invalid identifier format")
