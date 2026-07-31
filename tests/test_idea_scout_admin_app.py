"""Tests for the admin app's routes.

The paths here were ``/api/v1/admin/plugins/idea-scout/builtin-agents`` and every
one of them passed, because ``TestClient(app)`` calls the app object directly —
where a route declared at an absolute path is reachable. Mounted under
``/api/v1/plugins/idea-scout/admin`` by the plugin host, that same declaration
served the endpoint at
``/api/v1/plugins/idea-scout/admin/api/v1/admin/plugins/idea-scout/builtin-agents``,
which nothing calls and nothing could (#69). Relative paths are the only ones a
mounted app can honour, so these assert relative paths.
"""

from biffo_plugin_sdk import ForwardedUser
from fastapi.testclient import TestClient

from idea_scout.admin_app import app
from idea_scout.definitions import (
    COMMUNITY_AGENT_NAME,
    COMPETITIVE_AGENT_NAME,
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NARRATIVE_AGENT_NAME,
    SYNTHESIS_AGENT_NAME,
)


def test_builtin_agents_endpoint_exists():
    """The endpoint should respond with built-in agent data."""
    client = TestClient(app)
    response = client.get("/builtin-agents")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert len(data["agents"]) == 4


def test_builtin_agents_research_models_have_online_suffix():
    """Research agents must have the :online suffix to access web search.

    Without :online, research agents silently fail after burning paid calls.
    This test ensures the endpoint returns models with web capability.
    """
    client = TestClient(app)
    response = client.get("/builtin-agents")
    data = response.json()

    research_agents = [
        a
        for a in data["agents"]
        if a["agent_key"] in [COMMUNITY_AGENT_NAME, NARRATIVE_AGENT_NAME, COMPETITIVE_AGENT_NAME]
    ]

    for agent in research_agents:
        assert agent["model"].endswith(":online"), (
            f"Research agent {agent['agent_key']} must have :online suffix. Got: {agent['model']}"
        )


def test_builtin_agents_models_match_constants():
    """Built-in agent models must match the constants in definitions.py.

    Ensures the endpoint, app.py, and seed_agent_config.py all use the same
    defaults so they cannot drift apart.
    """
    client = TestClient(app)
    response = client.get("/builtin-agents")
    data = response.json()

    agents_by_key = {a["agent_key"]: a for a in data["agents"]}

    # Research agents
    for research_key in [COMMUNITY_AGENT_NAME, NARRATIVE_AGENT_NAME, COMPETITIVE_AGENT_NAME]:
        assert agents_by_key[research_key]["model"] == DEFAULT_RESEARCH_MODEL, (
            f"Research agent {research_key} should use DEFAULT_RESEARCH_MODEL. "
            f"Expected: {DEFAULT_RESEARCH_MODEL}, Got: {agents_by_key[research_key]['model']}"
        )

    # Synthesis agent
    assert agents_by_key[SYNTHESIS_AGENT_NAME]["model"] == DEFAULT_SYNTHESIS_MODEL, (
        f"Synthesis agent should use DEFAULT_SYNTHESIS_MODEL. "
        f"Expected: {DEFAULT_SYNTHESIS_MODEL}, Got: {agents_by_key[SYNTHESIS_AGENT_NAME]['model']}"
    )


def test_builtin_agents_have_real_prompts():
    """Built-in agents should return real prompt text, not placeholders."""
    client = TestClient(app)
    response = client.get("/builtin-agents")
    data = response.json()

    for agent in data["agents"]:
        # Real prompts are several sentences; placeholders are not
        assert len(agent["system_prompt"]) > 50, (
            f"Agent {agent['agent_key']} prompt is too short. "
            f"Likely a placeholder: {agent['system_prompt'][:50]}"
        )
        # No placeholder strings
        assert "Built-in prompt — stored row not found" not in agent["system_prompt"]
        assert "(Built-in default)" not in agent["system_prompt"]


class TestTheStaticMountDoesNotShadowTheApi:
    """The SPA mount is registered LAST, and that ordering is load-bearing.

    Starlette matches routes in registration order and ``Mount("/")`` matches
    every path, with no fall-through to a later route. This module used to mount
    the built UI *above* its API routes, so even a correctly-pathed
    ``/builtin-agents`` would have returned ``index.html``.

    Every unit test in this file would still have passed, because in a source
    checkout ``web-admin/dist`` does not exist and the mount is skipped entirely.
    So this test builds the dist directory the deployment has.
    """

    def test_the_api_still_answers_when_the_spa_is_mounted(self, tmp_path, monkeypatch):
        import importlib

        dist = tmp_path / "idea-scout" / "web-admin" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><title>SPA</title>")
        monkeypatch.setenv("BIFFO_PLUGINS_ROOT", str(tmp_path))

        import idea_scout.admin_app as admin_app

        reloaded = importlib.reload(admin_app)
        try:
            client = TestClient(reloaded.app)

            # The mount is genuinely active — guard the guard, or the assertion
            # below passes for the boring reason that nothing was mounted at all.
            # `/`, not an arbitrary path: StaticFiles(html=True) serves
            # index.html for a DIRECTORY and 404s an unknown key, so it is not an
            # SPA history fallback and asking it for one proves nothing.
            spa = client.get("/")
            assert spa.status_code == 200
            assert "<!doctype html>" in spa.text.lower()

            # ...and the API is still reachable underneath it.
            api = client.get("/builtin-agents")
            assert api.status_code == 200, (
                "the static mount is shadowing the API — it must be registered "
                "after every route (#69)"
            )
            assert "agents" in api.json()
        finally:
            monkeypatch.delenv("BIFFO_PLUGINS_ROOT", raising=False)
            importlib.reload(admin_app)


class TestChatAgentProxyForwardsAsTheCallingAdmin:
    """The proxy adds a hop and no privilege.

    Core's ``require_admin`` authorises the real human on every forwarded call,
    so the admin's own bearer token goes upstream — not this plugin's service
    principal. Forwarding as the plugin would turn "an admin can edit prompts"
    into "anyone who reaches this route can", which is the whole reason the
    cross-plugin read was refused in the first place (biffo-template#909).
    """

    def test_the_admins_own_token_is_forwarded_upstream(self, monkeypatch):
        import httpx as real_httpx

        import idea_scout.admin_app as admin_app

        seen: dict = {}

        class _Resp:
            status_code = 200
            content = b"[]"

            @staticmethod
            def json():
                return []

        class _Client:
            def __init__(self, *_args, **kwargs):
                seen["timeout"] = kwargs.get("timeout")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def request(self, method, url, json=None, headers=None):
                seen["method"] = method
                seen["url"] = url
                seen["headers"] = headers
                return _Resp()

        monkeypatch.setattr(admin_app.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(admin_app, "_CORE_API_URL", "https://core.example.invalid")

        admin = ForwardedUser(sub="admin-sub", groups=["admin"], token="the-admins-own-token")

        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            admin_app.list_chat_agents(admin=admin)
        )

        assert seen["headers"]["Authorization"] == "Bearer the-admins-own-token"
        assert seen["url"] == (
            "https://core.example.invalid/api/v1/admin/plugins/idea-scout/chat-agents"
        )
        # An explicit timeout, not httpx's unchosen 5s default against a Core
        # that cold-starts in ~4.3s (biffo-template#652/#724).
        assert seen["timeout"] == admin_app._CORE_TIMEOUT_SECONDS
        assert real_httpx is not None

    def test_cores_refusal_is_carried_through_with_its_reason(self, monkeypatch):
        """A bare status is what made #69 unreadable — the panel could only say
        "no agents stored" because nothing told it why."""
        import asyncio

        from fastapi import HTTPException

        import idea_scout.admin_app as admin_app

        class _Resp:
            status_code = 403
            content = b'{"detail":"Administrator access required"}'
            text = '{"detail":"Administrator access required"}'

        class _Client:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def request(self, *_a, **_k):
                return _Resp()

        monkeypatch.setattr(admin_app.httpx, "AsyncClient", _Client)
        monkeypatch.setattr(admin_app, "_CORE_API_URL", "https://core.example.invalid")

        admin = ForwardedUser(sub="admin-sub", groups=["admin"], token="t")

        try:
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                admin_app.list_chat_agents(admin=admin)
            )
        except HTTPException as exc:
            assert exc.status_code == 403
            assert "Administrator access required" in str(exc.detail)
        else:  # pragma: no cover - the point of the test
            raise AssertionError("Core's 403 must reach the panel, not be swallowed")


def test_the_history_route_is_proxied_too():
    """#69 proxied CRUD and stopped, so history 404'd from the panel's own base.

    Asserts the route EXISTS on the app at a relative path — the same defect
    class as the absolute-path `builtin-agents` declaration, and the reason
    biffo-template#909's "an admin can see a prompt's history" criterion was
    unreachable while Core was faithfully recording every edit.
    """
    paths = {p for p in (getattr(r, "path", None) for r in app.routes) if p is not None}
    assert "/chat-agents/{agent_key}/history" in paths, (
        f"history is not proxied; the panel's base would 404. Routes: {sorted(paths)}"
    )


def test_a_failed_startup_seed_logs_cores_actual_response(monkeypatch):
    """The admin app's startup seed reports Core's response, same as app.py's.

    Two apps run the same handler shape, so the misleading "(Core may be
    unavailable)" wording lived in both (biffo-template#924). Both are asserted,
    because a fix to one is not a fix to the other.
    """
    import asyncio
    import logging

    from idea_scout import admin_app as admin_module
    from idea_scout.adapter import CoreHttpError

    detail = "POST /api/v1/internal/plugins/me/config/seed -> 500: uq_plugin_chat_agent_key"

    class _Exploding:
        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def seed_own_config(self, *, config: object) -> object:
            raise CoreHttpError(detail)

    monkeypatch.setattr(admin_module, "CoreTransport", lambda **kwargs: object())
    monkeypatch.setattr(admin_module, "CoreHttpGateway", _Exploding)

    # Capture from the module's OWN logger rather than through `caplog`, which
    # depends on propagation reaching the root handler. That holds here and does
    # not hold once this file is vendored into `biffo-platform`, whose suite also
    # imports Core: AWS Lambda Powertools' `Logger()` reconfigures logging and
    # disables propagation, so the assertion would fail for a reason that has
    # nothing to do with what it tests — green here, red downstream, identical
    # code. (biffo-plugin-ideation learned this the hard way; see its
    # tests/test_startup_seeding.py.)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    admin_module._LOGGER.addHandler(handler)
    previous_level = admin_module._LOGGER.level
    admin_module._LOGGER.setLevel(logging.ERROR)
    try:
        asyncio.run(admin_module._seed_agent_config())
    finally:
        admin_module._LOGGER.removeHandler(handler)
        admin_module._LOGGER.setLevel(previous_level)

    logged = "\n".join(record.getMessage() for record in records)
    assert detail in logged, logged
    assert "may be unavailable" not in logged, logged
