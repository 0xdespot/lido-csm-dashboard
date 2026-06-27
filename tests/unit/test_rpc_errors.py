"""Tests for RPC error detection and the unreachable-node exception."""

import socket

import pytest
import requests.exceptions
import urllib3.exceptions
from web3.exceptions import ContractLogicError

from src.core.rpc_errors import (
    RPCUnavailableError,
    is_connection_error,
    safe_rpc_host,
)


class TestSafeRpcHost:
    """safe_rpc_host should expose host:port but never the URL path/query."""

    def test_keeps_scheme_host_port(self):
        assert safe_rpc_host("http://10.10.20.10:8545") == "http://10.10.20.10:8545"

    def test_drops_path_and_query(self):
        # An API key in the path/query must not survive.
        assert (
            safe_rpc_host("https://eth.example.com/v3/SECRETKEY?token=abc")
            == "https://eth.example.com"
        )

    def test_no_port(self):
        assert safe_rpc_host("https://eth.llamarpc.com") == "https://eth.llamarpc.com"


class TestIsConnectionError:
    """is_connection_error flags transport failures, not contract/value errors."""

    def test_requests_connection_error(self):
        assert is_connection_error(requests.exceptions.ConnectionError("refused"))

    def test_requests_timeout(self):
        assert is_connection_error(requests.exceptions.ConnectTimeout("slow"))

    def test_urllib3_maxretry(self):
        assert is_connection_error(
            urllib3.exceptions.MaxRetryError(pool=None, url="http://x", reason=None)
        )

    def test_socket_gaierror(self):
        assert is_connection_error(socket.gaierror("name resolution failed"))

    def test_builtin_connection_refused(self):
        assert is_connection_error(ConnectionRefusedError("refused"))

    def test_detects_wrapped_cause(self):
        # web3 can re-raise; the transport failure may be the __cause__.
        try:
            try:
                raise requests.exceptions.ConnectionError("refused")
            except requests.exceptions.ConnectionError as inner:
                raise ValueError("contract call failed") from inner
        except ValueError as outer:
            assert is_connection_error(outer)

    def test_detects_implicit_context(self):
        # Even without `from`, the original error lives in __context__.
        try:
            try:
                raise ConnectionRefusedError("refused")
            except ConnectionRefusedError:
                raise ValueError("downstream")
        except ValueError as outer:
            assert is_connection_error(outer)

    def test_contract_logic_error_is_not_connection(self):
        # A revert means "operator not found", not "node down".
        assert not is_connection_error(ContractLogicError("execution reverted"))

    def test_plain_value_error_is_not_connection(self):
        assert not is_connection_error(ValueError("bad data"))

    def test_does_not_loop_on_self_referential_chain(self):
        # Defensive: a cyclic cause chain must terminate.
        err = ValueError("a")
        err.__cause__ = err
        assert is_connection_error(err) is False


class TestRPCUnavailableError:
    def test_carries_host_and_message(self):
        err = RPCUnavailableError("http://10.10.20.10:8545")
        assert err.host == "http://10.10.20.10:8545"
        assert "10.10.20.10:8545" in str(err)
