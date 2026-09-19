"""Configuration management using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Web Server Settings
    # Bare-metal defaults. The Docker image sets HOST=0.0.0.0 and PORT=3000 via
    # ENV, which override these inside the container while `csm serve` on the
    # host keeps behaving as the README documents.
    host: str = "127.0.0.1"
    port: int = 8080

    # RPC Configuration
    eth_rpc_url: str = "https://eth.llamarpc.com"

    # Beacon Chain API (optional)
    beacon_api_url: str = "https://beaconcha.in/api/v1"
    beacon_api_key: str | None = None  # Optional beaconcha.in API key for higher rate limits

    # Etherscan API (optional, for historical event queries)
    etherscan_api_key: str | None = None

    # Data Sources
    rewards_proofs_url: str = (
        "https://raw.githubusercontent.com/lidofinance/csm-rewards/mainnet/proofs.json"
    )

    # Cache Settings
    cache_ttl_seconds: int = 300  # 5 minutes

    # Cache / Database Settings
    # Every on-disk cache derives from cache_dir, so a single CACHE_DIR env var
    # relocates all of them. This matters in containers: the saved-operator DB,
    # the discovered-CID cache and the IPFS log cache must land on the mounted
    # volume together, or distribution history re-runs full discovery on every
    # restart.
    cache_dir: Path = Path.home() / ".cache" / "csm-dashboard"
    # Derived from cache_dir unless DATABASE_PATH is set explicitly.
    database_path: Path = Path.home() / ".cache" / "csm-dashboard" / "operators.db"
    # IPFS Gateway Configuration (comma-separated list, tried in order)
    # dweb.link and ipfs.io are both Protocol Labs and rate-limit (HTTP 429)
    # together, and w3s.link has been refusing connections — when all three
    # fail, recent distribution frames silently go missing, so a gateway on
    # different infrastructure is kept as a fallback.
    ipfs_gateways: str = (
        "https://dweb.link/ipfs/,"
        "https://ipfs.io/ipfs/,"
        "https://w3s.link/ipfs/,"
        "https://gateway.pinata.cloud/ipfs/"
    )

    # Contract Addresses (Mainnet)
    csmodule_address: str = "0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F"
    csaccounting_address: str = "0x4d72BFF1BeaC69925F8Bd12526a39BAAb069e5Da"
    csfeedistributor_address: str = "0xD99CC66fEC647E68294C6477B40fC7E0F6F618D0"
    csstrikes_address: str = "0xaa328816027F2D32B9F56d190BC9Fa4A5C07637f"
    steth_address: str = "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
    withdrawal_queue_address: str = "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1"

    @model_validator(mode="after")
    def _derive_database_path(self) -> "Settings":
        """Point database_path at cache_dir unless it was set explicitly.

        ``model_fields_set`` holds only the fields the caller (or the env /
        .env layer) actually supplied, so an explicit DATABASE_PATH is never
        clobbered while a bare CACHE_DIR still moves the database with
        everything else.
        """
        if "database_path" not in self.model_fields_set:
            self.database_path = self.cache_dir / "operators.db"
        return self

    @property
    def discovered_cids_path(self) -> Path:
        """Persistent cache of distribution CIDs discovered at runtime."""
        return self.cache_dir / "discovered_cids.json"

    @property
    def ipfs_cache_dir(self) -> Path:
        """Directory holding fetched IPFS distribution logs."""
        return self.cache_dir / "ipfs"

    @property
    def strikes_cache_dir(self) -> Path:
        """Directory holding fetched strikes data."""
        return self.cache_dir / "strikes"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def resolve_bind(
    host: str | None,
    port: int | None,
    settings: Settings | None = None,
) -> tuple[str, int]:
    """Resolve the address to bind to, applying CLI > env/.env > default.

    An explicit CLI flag wins; ``None`` means "not supplied" and defers to the
    settings layer, which pydantic-settings has already resolved from the
    environment, then ``.env``, then the field default. Mirrors the
    ``rpc_url or self.settings.eth_rpc_url`` idiom in OnChainDataProvider,
    except that ``is not None`` is used so ``--port 0`` (ephemeral port) is
    honoured rather than treated as absent.
    """
    settings = settings if settings is not None else get_settings()
    return (
        host if host is not None else settings.host,
        port if port is not None else settings.port,
    )
