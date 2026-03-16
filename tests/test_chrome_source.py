"""Tests for bwsync.sources.chrome — unit tests that don't need actual Chrome."""

from bwsync.sources.chrome import _chrome_date_to_iso, _derive_name_from_url


def test_chrome_date_to_iso_valid():
    # 2024-01-15 in Chrome epoch (microseconds since 1601-01-01)
    # Unix timestamp for 2024-01-15 = 1705276800
    # Chrome timestamp = (1705276800 + 11644473600) * 1_000_000
    chrome_ts = (1705276800 + 11644473600) * 1_000_000
    assert _chrome_date_to_iso(chrome_ts) == "2024-01-15"


def test_chrome_date_to_iso_zero():
    assert _chrome_date_to_iso(0) == ""


def test_chrome_date_to_iso_none():
    assert _chrome_date_to_iso(None) == ""


def test_derive_name_from_url_basic():
    assert _derive_name_from_url("https://github.com/login") == "github.com"


def test_derive_name_from_url_www():
    assert _derive_name_from_url("https://www.example.com/path") == "example.com"


def test_derive_name_from_url_empty():
    assert _derive_name_from_url("") == ""


def test_derive_name_from_url_no_scheme():
    # urlparse without scheme puts everything in path
    result = _derive_name_from_url("example.com")
    assert result == ""  # no hostname parsed without scheme
