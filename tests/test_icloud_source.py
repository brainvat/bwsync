"""Tests for bwsync.sources.icloud — parsing tests that don't need Keychain access."""

from bwsync.sources.icloud import (
    _KeychainItem,
    _build_url,
    _parse_keychain_dump,
    _protocol_to_scheme,
)

SAMPLE_DUMP = '''keychain: "/Users/testuser/Library/Keychains/login.keychain-db"
version: 512
class: "inet"
attributes:
    "acct"<blob>="alice@example.com"
    "atyp"<blob>="form"
    "path"<blob>="/"
    "port"<uint32>="0"
    "ptcl"<uint32>="htps"
    "srvr"<blob>="github.com"
class: "inet"
attributes:
    "acct"<blob>="bob"
    "atyp"<blob>="http"
    "path"<blob>="/login"
    "port"<uint32>="8080"
    "ptcl"<uint32>="http"
    "srvr"<blob>="intranet.corp.com"
class: "genp"
attributes:
    "acct"<blob>="wifi-password"
    "svce"<blob>="AirPort"
'''


def test_parse_keychain_dump_finds_inet_items():
    items = _parse_keychain_dump(SAMPLE_DUMP)
    assert len(items) == 2  # Should skip the genp class


def test_parse_keychain_dump_first_item():
    items = _parse_keychain_dump(SAMPLE_DUMP)
    assert items[0].server == "github.com"
    assert items[0].account == "alice@example.com"
    assert items[0].protocol == "htps"


def test_parse_keychain_dump_second_item():
    items = _parse_keychain_dump(SAMPLE_DUMP)
    assert items[1].server == "intranet.corp.com"
    assert items[1].account == "bob"
    assert items[1].port == "8080"


def test_protocol_to_scheme():
    assert _protocol_to_scheme("htps") == "https"
    assert _protocol_to_scheme("http") == "http"
    assert _protocol_to_scheme("unknown") == "https"  # default


def test_build_url_basic():
    item = _KeychainItem(server="github.com", protocol="htps")
    assert _build_url(item) == "https://github.com"


def test_build_url_with_port():
    item = _KeychainItem(server="intranet.corp.com", protocol="http", port="8080")
    assert _build_url(item) == "http://intranet.corp.com:8080"


def test_build_url_with_path():
    item = _KeychainItem(server="example.com", protocol="htps", path="/api/v1")
    assert _build_url(item) == "https://example.com/api/v1"


def test_build_url_ignores_root_path():
    item = _KeychainItem(server="example.com", protocol="htps", path="/")
    assert _build_url(item) == "https://example.com"


def test_build_url_ignores_zero_port():
    item = _KeychainItem(server="example.com", protocol="htps", port="0")
    assert _build_url(item) == "https://example.com"
