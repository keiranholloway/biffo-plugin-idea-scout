"""The admin-facing app: the gate, the proxy, and what it forwards.

The Core calls are stubbed — what this layer owns is the admin gate, the path it
proxies to, and that it forwards the *admin's own* token rather than signing as
the plugin's service principal.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

import idea_scout.admin_app as admin_module
from idea_scout.admin_app import app, require_admin


class FakeCore:
    """Records what the app asked Core for, and with which credential."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response: Any = []

    async def request(self, method, path, *, admin, json=None):
        self.calls.append({"method": method, "path": path, "token": admin.token, "json": json})
        return self.response

    def last(self) -> dict[str, Any]:
        assert self.calls, "no Core call was made"
        return self.calls[-1]


@pytest.fixture
def core(monkeypatch) -> FakeCore:
    fake = FakeCore()
    monkeypatch.setattr(admin_module, "_core_request", fake.request)
    return fake


@pytest.fixture
def client(core: FakeCore) -> Iterator[TestClient]:
    app.dependency_overrides[require_admin] = lambda: ForwardedUser(
        sub="admin-1", groups=["admin"], token="admin-token"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── Build types ──────────────────────────────────────────────────────────────


def test_listing_build_types_proxies_to_the_plugin_route(client, core):
    assert client.get("/build-types").status_code == 200
    assert core.last()["path"] == "/api/v1/plugins/idea-scout/build-types"
    assert core.last()["method"] == "GET"


def test_the_admin_list_is_not_filtered_to_active(client, core):
    """Unlike the founder-facing list. An admin has to see a deactivated
    category in order to reactivate it."""
    core.response = [
        {"key": "a", "active": True},
        {"key": "b", "active": False},
    ]
    assert len(client.get("/build-types").json()) == 2


def test_creating_a_build_type_forwards_the_body(client, core):
    client.post("/build-types", json={"key": "new", "label": "New", "active": True})
    assert core.last()["method"] == "POST"
    assert core.last()["json"]["key"] == "new"


def test_updating_a_build_type_targets_its_id(client, core):
    client.put("/build-types/bt1", json={"active": False})
    assert core.last()["path"].endswith("/build-types/bt1")
    assert core.last()["method"] == "PUT"


def test_deleting_a_build_type_is_a_204(client, core):
    assert client.delete("/build-types/bt1").status_code == 204
    assert core.last()["method"] == "DELETE"


# ── Agent config ─────────────────────────────────────────────────────────────


def test_agent_config_proxies_to_cores_admin_route(client, core):
    client.get("/chat-agents")
    assert core.last()["path"] == "/api/v1/admin/plugins/idea-scout/chat-agents"


def test_updating_an_agent_targets_its_key(client, core):
    client.put("/chat-agents/idea-scout-community", json={"model": "m"})
    assert core.last()["path"].endswith("/chat-agents/idea-scout-community")


# ── Credentials ──────────────────────────────────────────────────────────────


def test_it_forwards_the_admins_own_token(client, core):
    """Not a service-principal signature. These Core routes want a real admin
    token; signing as the plugin would be both wrong and a wider credential
    than the operation needs."""
    client.get("/build-types")
    assert core.last()["token"] == "admin-token"


# ── The gate ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/build-types"),
        ("POST", "/build-types"),
        ("GET", "/build-types/bt1"),
        ("PUT", "/build-types/bt1"),
        ("DELETE", "/build-types/bt1"),
        ("GET", "/chat-agents"),
        ("GET", "/chat-agents/k"),
        ("PUT", "/chat-agents/k"),
    ],
)
def test_every_admin_route_is_gated(method, path):
    app.dependency_overrides.clear()
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.request(method, path, json={})

    assert resp.status_code == 401, f"{method} {path} was not gated"


def test_exposes_an_asgi_app_not_a_lambda_handler():
    assert hasattr(admin_module, "app")
    assert not hasattr(admin_module, "handler")


# ── The Core client's timeout ────────────────────────────────────────────────
#
# These exercise the real ``_core_request`` — the fixtures above stub it out, so
# nothing else in this file ever constructs the httpx client that the bug lives
# in. What is pinned is that a timeout is passed *at all*: a bare
# ``httpx.AsyncClient()`` silently inherits httpx's 5s default, which is shorter
# than Core's ~4.9s cold start. See biffo-template#652.


class _RecordingClient:
    """Stands in for ``httpx.AsyncClient``, recording how it was constructed."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _RecordingClient.last_kwargs = kwargs

    last_kwargs: dict[str, Any] = {}

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def recorded_client(monkeypatch) -> type[_RecordingClient]:
    _RecordingClient.last_kwargs = {}
    monkeypatch.setattr(admin_module.httpx, "AsyncClient", _RecordingClient)
    monkeypatch.setattr(admin_module, "_CORE_API_URL", "https://core.example")
    return _RecordingClient


async def test_the_core_client_is_given_an_explicit_timeout(recorded_client):
    """Not httpx's default. The default is 5s, Core cold-starts in ~4.9s, so
    leaving it unset makes the first request after a cold start a coin toss."""
    admin = ForwardedUser(sub="admin-1", groups=["admin"], token="admin-token")

    await admin_module._core_request("GET", "/api/v1/whatever", admin=admin)

    assert "timeout" in recorded_client.last_kwargs, (
        "httpx.AsyncClient was constructed with no timeout — it will inherit "
        "httpx's 5s default, which is shorter than Core's cold start"
    )


async def test_the_timeout_clears_cores_cold_start(recorded_client):
    """A number, and comfortably above the ~4.9s cold start rather than merely
    above httpx's default."""
    admin = ForwardedUser(sub="admin-1", groups=["admin"], token="admin-token")

    await admin_module._core_request("GET", "/api/v1/whatever", admin=admin)

    timeout = recorded_client.last_kwargs["timeout"]
    assert isinstance(timeout, (int, float))
    assert timeout >= 15.0, f"{timeout}s leaves no headroom over a ~4.9s cold start"


def test_the_timeout_matches_the_sdk_client_default():
    """So a call out of the admin app and a call out of ``BiffoAPIClient`` wait
    the same amount — one plugin, one budget."""
    assert admin_module._CORE_TIMEOUT_SECONDS == 30.0
