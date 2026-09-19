"""Tests for the config module."""

import os
from pathlib import Path

from unittest.mock import patch

from src.core.config import Settings, get_settings, resolve_bind


class TestSettings:
    """Tests for the Settings class."""

    def test_default_values(self):
        """Test that settings have expected structure and types.

        Note: Actual values may differ if a .env file is present.
        """
        settings = Settings()

        # Test that settings exist and have correct types
        assert isinstance(settings.eth_rpc_url, str)
        assert settings.eth_rpc_url.startswith("https://")
        assert isinstance(settings.beacon_api_url, str)
        assert settings.beacon_api_key is None or isinstance(settings.beacon_api_key, str)
        assert settings.etherscan_api_key is None or isinstance(settings.etherscan_api_key, str)
        assert isinstance(settings.cache_ttl_seconds, int)
        assert settings.cache_ttl_seconds > 0

    def test_contract_addresses(self):
        """Test that contract addresses are set correctly."""
        settings = Settings()

        assert settings.csmodule_address == "0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F"
        assert settings.csaccounting_address == "0x4d72BFF1BeaC69925F8Bd12526a39BAAb069e5Da"
        assert settings.csfeedistributor_address == "0xD99CC66fEC647E68294C6477B40fC7E0F6F618D0"
        assert settings.csstrikes_address == "0xaa328816027F2D32B9F56d190BC9Fa4A5C07637f"
        assert settings.steth_address == "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
        assert settings.withdrawal_queue_address == "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1"

    def test_environment_variable_override(self):
        """Test that environment variables override defaults."""
        custom_rpc = "https://custom.rpc.example.com"
        custom_ttl = "600"

        with patch.dict(
            os.environ,
            {
                "ETH_RPC_URL": custom_rpc,
                "CACHE_TTL_SECONDS": custom_ttl,
            },
        ):
            settings = Settings()

        assert settings.eth_rpc_url == custom_rpc
        assert settings.cache_ttl_seconds == 600

    def test_optional_api_keys(self):
        """Test that optional API keys can be set."""
        with patch.dict(
            os.environ,
            {
                "BEACON_API_KEY": "beacon_key_123",
                "ETHERSCAN_API_KEY": "etherscan_key_456",
            },
        ):
            settings = Settings()

        assert settings.beacon_api_key == "beacon_key_123"
        assert settings.etherscan_api_key == "etherscan_key_456"


class TestGetSettings:
    """Tests for the get_settings function."""

    def test_get_settings_returns_settings_instance(self):
        """Test that get_settings returns a Settings instance."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_is_cached(self):
        """Test that get_settings returns the same cached instance."""
        # Clear the cache first
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        # Should be the same instance (cached)
        assert settings1 is settings2


class TestServerBindSettings:
    """Tests for the host/port settings and CLI-over-env precedence."""

    def test_bind_defaults(self):
        """Bare-metal defaults are unchanged: 127.0.0.1:8080."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOST", None)
            os.environ.pop("PORT", None)
            settings = Settings()

        assert settings.host == "127.0.0.1"
        assert settings.port == 8080

    def test_port_and_host_env_override(self):
        """PORT/HOST environment variables override the field defaults."""
        with patch.dict(os.environ, {"HOST": "0.0.0.0", "PORT": "9001"}):
            settings = Settings()

        assert settings.host == "0.0.0.0"
        assert settings.port == 9001

    def test_resolve_bind_falls_back_to_settings(self):
        """With no CLI flags, the settings values win."""
        settings = Settings(host="0.0.0.0", port=3000)

        assert resolve_bind(None, None, settings) == ("0.0.0.0", 3000)

    def test_resolve_bind_cli_beats_env(self):
        """An explicit CLI flag beats the env-backed settings value."""
        settings = Settings(host="0.0.0.0", port=9001)

        assert resolve_bind("127.0.0.1", 7000, settings) == ("127.0.0.1", 7000)

    def test_resolve_bind_flags_are_independent(self):
        """Supplying only one flag leaves the other on the settings value."""
        settings = Settings(host="0.0.0.0", port=9001)

        assert resolve_bind(None, 7000, settings) == ("0.0.0.0", 7000)
        assert resolve_bind("::1", None, settings) == ("::1", 9001)

    def test_resolve_bind_accepts_port_zero(self):
        """Port 0 (ephemeral) is a real value, not a missing one."""
        settings = Settings(port=9001)

        assert resolve_bind(None, 0, settings)[1] == 0

    def test_resolve_bind_uses_get_settings_when_omitted(self):
        """Omitting the settings argument reads the cached global settings."""
        get_settings.cache_clear()
        with patch.dict(os.environ, {"PORT": "9123"}):
            get_settings.cache_clear()
            assert resolve_bind(None, None)[1] == 9123
        get_settings.cache_clear()


class TestCacheDirSettings:
    """All on-disk caches derive from a single configurable root."""

    def test_cache_dir_default(self):
        """Default root is the historical ~/.cache/csm-dashboard location."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CACHE_DIR", None)
            os.environ.pop("DATABASE_PATH", None)
            settings = Settings()

        assert settings.cache_dir == Path.home() / ".cache" / "csm-dashboard"

    def test_all_paths_derive_from_cache_dir(self):
        """One CACHE_DIR relocates the db, the CID cache and the IPFS cache."""
        settings = Settings(cache_dir=Path("/mnt/appdata/csm"))

        assert settings.database_path == Path("/mnt/appdata/csm/operators.db")
        assert settings.discovered_cids_path == Path("/mnt/appdata/csm/discovered_cids.json")
        assert settings.ipfs_cache_dir == Path("/mnt/appdata/csm/ipfs")

    def test_cache_dir_env_override(self):
        """CACHE_DIR is settable from the environment."""
        with patch.dict(os.environ, {"CACHE_DIR": "/mnt/appdata/csm"}):
            os.environ.pop("DATABASE_PATH", None)
            settings = Settings()

        assert settings.cache_dir == Path("/mnt/appdata/csm")
        assert settings.database_path == Path("/mnt/appdata/csm/operators.db")

    def test_explicit_database_path_wins_over_cache_dir(self):
        """An explicit DATABASE_PATH is not clobbered by the derivation."""
        settings = Settings(
            cache_dir=Path("/mnt/appdata/csm"),
            database_path=Path("/elsewhere/custom.db"),
        )

        assert settings.database_path == Path("/elsewhere/custom.db")
        # The other caches still follow cache_dir.
        assert settings.ipfs_cache_dir == Path("/mnt/appdata/csm/ipfs")

    def test_explicit_database_path_env_wins(self):
        """Same precedence when both arrive as environment variables."""
        with patch.dict(
            os.environ,
            {"CACHE_DIR": "/mnt/appdata/csm", "DATABASE_PATH": "/elsewhere/custom.db"},
        ):
            settings = Settings()

        assert settings.database_path == Path("/elsewhere/custom.db")
