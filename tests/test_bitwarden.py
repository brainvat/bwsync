"""Tests for bwsync.bitwarden — unit tests that don't need a running bw serve."""

import hashlib

from bwsync.bitwarden import BitwardenClient
from bwsync.schema import NormalizedEntry


def test_password_matches_true():
    client = BitwardenClient(session_token="fake")
    entry = NormalizedEntry(url="https://example.com", username="alice", password="secret123")
    bw_item = {"login": {"password": "secret123"}}
    assert client.password_matches(bw_item, entry) is True


def test_password_matches_false():
    client = BitwardenClient(session_token="fake")
    entry = NormalizedEntry(url="https://example.com", username="alice", password="secret123")
    bw_item = {"login": {"password": "different_password"}}
    assert client.password_matches(bw_item, entry) is False


def test_password_matches_both_empty():
    client = BitwardenClient(session_token="fake")
    entry = NormalizedEntry(url="https://example.com", username="alice", password="")
    bw_item = {"login": {"password": ""}}
    assert client.password_matches(bw_item, entry) is True


def test_base_url_construction():
    client = BitwardenClient(host="http://localhost", port=9999, session_token="tok")
    assert client.base_url == "http://localhost:9999"


def test_headers_include_session():
    client = BitwardenClient(session_token="my-token")
    headers = client._headers()
    assert headers["Authorization"] == "Bearer my-token"
