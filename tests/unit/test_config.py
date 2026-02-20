"""Tests for the config module."""

import os
import pytest
from unittest.mock import patch

from src.core.config import Settings, get_settings


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
