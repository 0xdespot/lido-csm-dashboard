"""Contract ABIs and helpers."""

import json
from importlib import resources
from typing import Any


def load_abi(name: str) -> list[dict[str, Any]]:
    """Load ABI from JSON file in abis directory."""
    abi_file = resources.files("src.abis").joinpath(f"{name}.json")
    return json.loads(abi_file.read_text())


# Load ABIs at module level for easy import
CSMODULE_ABI = load_abi("CSModule")
CSACCOUNTING_ABI = load_abi("CSAccounting")
CSFEEDISTRIBUTOR_ABI = load_abi("CSFeeDistributor")
STETH_ABI = load_abi("stETH")
