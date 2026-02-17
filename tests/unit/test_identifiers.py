"""Tests for operator identifier parsing helpers."""

import pytest
from fastapi import HTTPException

from src.web.identifiers import MAX_OPERATOR_ID, parse_operator_identifier


class TestParseOperatorIdentifier:
    """Tests for parse_operator_identifier."""

    def test_parses_numeric_operator_id(self):
        kind, value = parse_operator_identifier("42")
        assert kind == "id"
        assert value == 42

    def test_rejects_operator_id_above_limit(self):
        with pytest.raises(HTTPException) as exc:
            parse_operator_identifier(str(MAX_OPERATOR_ID + 1))
        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid operator ID"

    def test_parses_and_normalizes_eth_address(self):
        kind, value = parse_operator_identifier("0x00000000219ab540356cbb839cbe05303d7705fa")
        assert kind == "address"
        assert value == "0x00000000219ab540356cBB839Cbe05303d7705Fa"

    def test_rejects_malformed_eth_address(self):
        with pytest.raises(HTTPException) as exc:
            parse_operator_identifier("0x123")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid Ethereum address"

    def test_rejects_invalid_identifier_format(self):
        with pytest.raises(HTTPException) as exc:
            parse_operator_identifier("not-an-id-or-address")
        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid identifier format"
