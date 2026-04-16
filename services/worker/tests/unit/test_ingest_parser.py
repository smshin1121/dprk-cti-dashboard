"""Tests for worker.ingest.parser — feedparser.parse(bytes) only."""

from __future__ import annotations

from pathlib import Path

from worker.ingest.parser import parse_feed


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures/rss"


# ---------------------------------------------------------------------------
# Happy RSS 2.0
# ---------------------------------------------------------------------------


def test_parse_rss_returns_entries() -> None:
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert len(outcome.entries) == 3
    assert outcome.parse_error is None


def test_parse_rss_extracts_title() -> None:
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert outcome.entries[0].title is not None
    assert "Lazarus" in outcome.entries[0].title


def test_parse_rss_extracts_link() -> None:
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert outcome.entries[0].link == "https://example.com/reports/lazarus-crypto-2026"


def test_parse_rss_extracts_published() -> None:
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert outcome.entries[0].published_raw is not None
    assert "2026" in outcome.entries[0].published_raw


def test_parse_rss_empty_title_is_none() -> None:
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert outcome.entries[2].title is None


def test_parse_rss_detected_kind() -> None:
    content = (FIXTURES / "sample_rss.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert outcome.detected_kind == "rss"


# ---------------------------------------------------------------------------
# Happy Atom 1.0
# ---------------------------------------------------------------------------


def test_parse_atom_returns_entries() -> None:
    content = (FIXTURES / "sample_atom.xml").read_bytes()
    outcome = parse_feed(content, "atom")

    assert len(outcome.entries) == 1
    assert outcome.parse_error is None


def test_parse_atom_extracts_link() -> None:
    content = (FIXTURES / "sample_atom.xml").read_bytes()
    outcome = parse_feed(content, "atom")

    assert outcome.entries[0].link == "https://atom-example.com/posts/scarcruft-analysis"


def test_parse_atom_detected_kind() -> None:
    content = (FIXTURES / "sample_atom.xml").read_bytes()
    outcome = parse_feed(content, "atom")

    assert outcome.detected_kind == "atom"


# ---------------------------------------------------------------------------
# Broken payload — hard error
# ---------------------------------------------------------------------------


def test_parse_broken_sets_parse_error() -> None:
    content = (FIXTURES / "broken.xml").read_bytes()
    outcome = parse_feed(content, "rss")

    assert outcome.parse_error is not None
    assert outcome.parse_error.exception_type != ""


# ---------------------------------------------------------------------------
# Benign warning — should NOT be classified as parse_error
# ---------------------------------------------------------------------------


def test_parse_benign_encoding_override_not_error() -> None:
    content = b"<?xml version='1.0' encoding='iso-8859-1'?><rss version='2.0'><channel><title>T</title><item><title>OK</title></item></channel></rss>"
    outcome = parse_feed(content, "rss")

    assert outcome.parse_error is None
    assert len(outcome.entries) == 1


# ---------------------------------------------------------------------------
# feedparser.parse(bytes) contract — no URL call
# ---------------------------------------------------------------------------


def test_parse_accepts_bytes_not_url() -> None:
    content = b"<rss version='2.0'><channel><title>T</title></channel></rss>"
    outcome = parse_feed(content, "rss")

    assert outcome.entries == ()
    assert outcome.parse_error is None
