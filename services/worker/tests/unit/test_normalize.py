"""Tests for worker.bootstrap.normalize — URL canonicalization + title hash."""

from __future__ import annotations

import hashlib

import pytest

from worker.bootstrap.normalize import canonicalize_url, sha256_title


# ---------------------------------------------------------------------------
# canonicalize_url — happy path
# ---------------------------------------------------------------------------


def test_canonicalize_passes_simple_url_through() -> None:
    assert (
        canonicalize_url("https://example.com/a/b")
        == "https://example.com/a/b"
    )


def test_canonicalize_lowercases_scheme_and_host() -> None:
    assert (
        canonicalize_url("HTTPS://Example.COM/A/B")
        == "https://example.com/A/B"  # path casing preserved
    )


def test_canonicalize_strips_surrounding_whitespace() -> None:
    assert (
        canonicalize_url("  https://example.com/a  ")
        == "https://example.com/a"
    )


def test_canonicalize_drops_trailing_slash() -> None:
    assert (
        canonicalize_url("https://example.com/a/")
        == "https://example.com/a"
    )


def test_canonicalize_preserves_root_slash() -> None:
    assert (
        canonicalize_url("https://example.com/")
        == "https://example.com/"
    )


def test_canonicalize_collapses_double_slashes() -> None:
    assert (
        canonicalize_url("https://example.com/a//b///c")
        == "https://example.com/a/b/c"
    )


# ---------------------------------------------------------------------------
# canonicalize_url — port handling
# ---------------------------------------------------------------------------


def test_canonicalize_drops_default_http_port() -> None:
    assert (
        canonicalize_url("http://example.com:80/a")
        == "http://example.com/a"
    )


def test_canonicalize_drops_default_https_port() -> None:
    assert (
        canonicalize_url("https://example.com:443/a")
        == "https://example.com/a"
    )


def test_canonicalize_keeps_nondefault_port() -> None:
    assert (
        canonicalize_url("https://example.com:8443/a")
        == "https://example.com:8443/a"
    )


# ---------------------------------------------------------------------------
# canonicalize_url — tracking-param stripping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tracking_param",
    [
        "utm_source=newsletter",
        "utm_medium=email",
        "utm_campaign=march",
        "utm_term=dprk",
        "utm_content=header",
        "utm_id=abc",
        "gclid=xyz",
        "fbclid=abc123",
        "mc_eid=deadbeef",
        "mc_cid=cafef00d",
        "igshid=xyz",
        "msclkid=xyz",
        "yclid=xyz",
        "dclid=xyz",
        "gbraid=xyz",
        "wbraid=xyz",
    ],
)
def test_canonicalize_strips_tracking_param(tracking_param: str) -> None:
    assert (
        canonicalize_url(f"https://example.com/a?{tracking_param}")
        == "https://example.com/a"
    )


def test_canonicalize_strips_multiple_tracking_params() -> None:
    raw = "https://example.com/a?utm_source=x&utm_campaign=y&fbclid=z"
    assert canonicalize_url(raw) == "https://example.com/a"


def test_canonicalize_preserves_real_query_params() -> None:
    raw = "https://example.com/search?q=lazarus&lang=en"
    assert canonicalize_url(raw) == "https://example.com/search?lang=en&q=lazarus"
    #                                                        ^^^ sorted


def test_canonicalize_mixed_tracking_and_real_params() -> None:
    raw = "https://example.com/search?q=lazarus&utm_source=nl&lang=en"
    assert canonicalize_url(raw) == "https://example.com/search?lang=en&q=lazarus"


def test_canonicalize_sorts_query_params_for_determinism() -> None:
    a = canonicalize_url("https://example.com/x?a=1&b=2&c=3")
    b = canonicalize_url("https://example.com/x?c=3&b=2&a=1")
    assert a == b


def test_canonicalize_tracking_param_matching_is_case_insensitive() -> None:
    assert (
        canonicalize_url("https://example.com/a?UTM_SOURCE=x")
        == "https://example.com/a"
    )


# ---------------------------------------------------------------------------
# canonicalize_url — fragment handling
# ---------------------------------------------------------------------------


def test_canonicalize_drops_fragment() -> None:
    assert (
        canonicalize_url("https://example.com/a#section-2")
        == "https://example.com/a"
    )


def test_canonicalize_drops_fragment_with_query() -> None:
    assert (
        canonicalize_url("https://example.com/a?x=1#section-2")
        == "https://example.com/a?x=1"
    )


# ---------------------------------------------------------------------------
# canonicalize_url — rejection cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ftp://example.com/x",
        "mailto:a@b.c",
        "just-a-string",
        "https:///noschemehost",
    ],
)
def test_canonicalize_rejects_invalid_inputs(bad: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_url(bad)


def test_canonicalize_rejects_none() -> None:
    with pytest.raises(ValueError):
        canonicalize_url(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# canonicalize_url — idempotency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a",
        "https://example.com/a/b/c",
        "http://example.com:8080/x?y=1",
        "https://example.com/search?a=1&b=2&utm_source=x",
        "HTTPS://Example.COM/A/B/?utm_source=nl#frag",
    ],
)
def test_canonicalize_is_idempotent(url: str) -> None:
    once = canonicalize_url(url)
    twice = canonicalize_url(once)
    assert once == twice


# ---------------------------------------------------------------------------
# sha256_title
# ---------------------------------------------------------------------------


def test_sha256_title_returns_64_char_hex() -> None:
    digest = sha256_title("hello")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_sha256_title_is_deterministic() -> None:
    assert sha256_title("Hello world") == sha256_title("Hello world")


def test_sha256_title_is_case_insensitive() -> None:
    assert sha256_title("Lazarus") == sha256_title("lazarus")
    assert sha256_title("Lazarus") == sha256_title("LAZARUS")


def test_sha256_title_strips_whitespace() -> None:
    assert sha256_title("Lazarus") == sha256_title("  Lazarus  ")


def test_sha256_title_collapses_internal_whitespace() -> None:
    assert sha256_title("a  b   c") == sha256_title("a b c")
    assert sha256_title("a\tb\nc") == sha256_title("a b c")


def test_sha256_title_distinguishes_different_titles() -> None:
    assert sha256_title("Lazarus") != sha256_title("Kimsuky")


def test_sha256_title_rejects_empty_and_whitespace() -> None:
    with pytest.raises(ValueError):
        sha256_title("")
    with pytest.raises(ValueError):
        sha256_title("   ")


def test_sha256_title_rejects_none() -> None:
    with pytest.raises(ValueError):
        sha256_title(None)  # type: ignore[arg-type]


def test_sha256_title_matches_hashlib_reference() -> None:
    """Double-check the exact bytes hashed to prevent accidental drift
    if someone tweaks the normalization path."""
    reference = hashlib.sha256("hello world".encode("utf-8")).hexdigest()
    assert sha256_title("  Hello   World  ") == reference
