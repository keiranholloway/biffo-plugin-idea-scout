"""Tests for ``CoreTransport.request``'s error mapping — the seam that turns
Core's HTTP failures into this adapter's own error contract.

Both arms are load-bearing and neither was covered before this file: a 404
becomes :class:`CoreNotFoundError` (a distinct, expected condition adapter.py
treats as "not there yet" rather than a failure), and anything else becomes
:class:`CoreHttpError` carrying Core's *actual* response body. That second part
is deliberate, not incidental — a sibling plugin once shipped a mapping that
substituted a guess ("Core may be unavailable") for the real body, and the
guess was read as the diagnosis while Core was up and had answered with a 500
from its own unique-constraint violation (biffo-template#924). These tests
assert on the body content itself, not just the exception type, so that
regression cannot creep back in unnoticed.

``CoreTransport.request`` calls the inherited ``_send`` (real HTTP + SigV4,
from ``biffo_plugin_sdk``'s ``SignedCoreClient``) and only maps what it raises.
Stubbing ``_send`` to raise ``BiffoAPIError`` directly — the way ``FakeTransport``
in ``fakes.py`` stubs the whole ``Transport`` seam for adapter tests — exercises
exactly this mapping without needing real credentials or network.
"""

from __future__ import annotations

from typing import Any

import pytest
from biffo_plugin_sdk import BiffoAPIError

from idea_scout.adapter import CoreHttpError, CoreNotFoundError
from idea_scout.transport import CoreTransport


def _transport() -> CoreTransport:
    return CoreTransport(founder_token="founder-token-abc")


def _stub_send(exc: BiffoAPIError):
    """A replacement for the inherited ``_send`` that always raises ``exc``,
    ignoring whatever it was called with."""

    async def _send(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return _send


# ── 404 -> CoreNotFoundError ─────────────────────────────────────────────────


async def test_a_404_maps_to_core_not_found_error():
    transport = _transport()
    exc = BiffoAPIError(404, "Not Found", body=None)
    transport._send = _stub_send(exc)

    with pytest.raises(CoreNotFoundError) as excinfo:
        await transport.request("GET", "/api/v1/internal/user-profile/mine")

    assert excinfo.value.__cause__ is exc


async def test_a_404s_message_names_the_method_and_path():
    transport = _transport()
    transport._send = _stub_send(BiffoAPIError(404, "Not Found", body=None))

    with pytest.raises(CoreNotFoundError) as excinfo:
        await transport.request("GET", "/api/v1/internal/user-profile/mine")

    message = str(excinfo.value)
    assert "GET" in message
    assert "/api/v1/internal/user-profile/mine" in message
    assert "404" in message


# ── Anything else -> CoreHttpError, carrying Core's real body ───────────────


async def test_a_non_404_maps_to_core_http_error():
    transport = _transport()
    exc = BiffoAPIError(500, "Internal Server Error", body={"error": "boom"})
    transport._send = _stub_send(exc)

    with pytest.raises(CoreHttpError) as excinfo:
        await transport.request("POST", "/api/v1/internal/agent-runs")

    assert not isinstance(excinfo.value, CoreNotFoundError)
    assert excinfo.value.__cause__ is exc


async def test_the_http_error_reports_cores_actual_body_not_a_guess():
    """The property biffo-template#924 was written about: the message must
    carry what Core actually said, not a placeholder like "Core may be
    unavailable" that reads as a diagnosis while being nothing of the sort."""
    transport = _transport()
    body = {"error": "unique constraint violated on idea_scout_runs.chain_id"}
    transport._send = _stub_send(BiffoAPIError(500, "Internal Server Error", body=body))

    with pytest.raises(CoreHttpError) as excinfo:
        await transport.request("POST", "/api/v1/internal/owner-data/idea_scout_runs")

    message = str(excinfo.value)
    assert "POST" in message
    assert "/api/v1/internal/owner-data/idea_scout_runs" in message
    assert "500" in message
    assert "unique constraint violated on idea_scout_runs.chain_id" in message
    assert "may be unavailable" not in message


async def test_a_none_body_falls_back_to_detail():
    """Core doesn't always return a JSON body (e.g. a bare 5xx from a proxy in
    front of it) — ``exc.body`` is then ``None`` and the mapping falls back to
    ``exc.detail`` rather than reporting the literal string ``"None"``."""
    transport = _transport()
    transport._send = _stub_send(
        BiffoAPIError(502, "Bad Gateway: upstream connection reset", body=None)
    )

    with pytest.raises(CoreHttpError) as excinfo:
        await transport.request("GET", "/api/v1/internal/plugins/idea-scout/business-models")

    message = str(excinfo.value)
    assert "Bad Gateway: upstream connection reset" in message
    assert "None" not in message


async def test_a_long_body_is_truncated_to_500_characters():
    """Core's body is untrusted, unbounded response content — a large one
    (e.g. an HTML error page from a misconfigured proxy) must not make its way
    unbounded into an exception message that gets logged."""
    transport = _transport()
    long_body = {"error": "x" * 800}
    transport._send = _stub_send(BiffoAPIError(500, "Internal Server Error", body=long_body))

    with pytest.raises(CoreHttpError) as excinfo:
        await transport.request("GET", "/api/v1/internal/plugins/me/config/researcher")

    message = str(excinfo.value)
    detail_part = message.split(": ", 1)[1]
    assert len(detail_part) == 500
    assert detail_part == str(long_body)[:500]
