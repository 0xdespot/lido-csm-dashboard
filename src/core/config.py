"""Configuration management using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # RPC Configuration
    eth_rpc_url: str = "https://eth.llamarpc.com"

    # Beacon Chain API (optional)
    beacon_api_url: str = "https://beaconcha.in/api/v1"
    beacon_api_key: str | None = None  # Optional beaconcha.in API key for higher rate limits

    # Etherscan API (optional, for historical event queries)
    etherscan_api_key: str | None = None

    # The Graph API (optional, for historical stETH APR data)
    thegraph_api_key: str | None = None

    # Data Sources
    rewards_proofs_url: str = (
        "https://raw.githubusercontent.com/lidofinance/csm-rewards/mainnet/proofs.json"
    )

    # Cache Settings
    cache_ttl_seconds: int = 300  # 5 minutes

    # Contract Addresses (Mainnet)
    csmodule_address: str = "0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F"
    csaccounting_address: str = "0x4d72BFF1BeaC69925F8Bd12526a39BAAb069e5Da"
    csfeedistributor_address: str = "0xD99CC66fEC647E68294C6477B40fC7E0F6F618D0"
    csstrikes_address: str = "0xaa328816027F2D32B9F56d190BC9Fa4A5C07637f"
    steth_address: str = "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
