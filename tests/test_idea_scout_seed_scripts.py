"""The seed data. Two of these three scripts are hard prerequisites — the plugin
deploys clean and is unusable without them — so their contents are asserted
rather than trusted.
"""

from __future__ import annotations

from _scripts import load_script

from idea_scout.definitions import (
    DEFAULT_INSTRUCTIONS,
    RESEARCH_AGENT_NAMES,
    SYNTHESIS_AGENT_NAME,
)

payloads = load_script("seed_agent_config").payloads
BUILD_TYPES = load_script("seed_build_types").BUILD_TYPES

# ── Build types ──────────────────────────────────────────────────────────────


def test_the_starting_categories_have_unique_keys():
    """The key is what a run stores and what the founder's request is validated
    against; a duplicate would make one of them unreachable."""
    keys = [t["key"] for t in BUILD_TYPES]
    assert len(set(keys)) == len(keys)


def test_every_category_has_a_description():
    """Not decoration — the description goes into the research brief, so a blank
    one silently makes the agents' scoping worse."""
    for build_type in BUILD_TYPES:
        assert build_type["description"].strip(), build_type["key"]


def test_every_category_is_ordered():
    orders = [t["sort_order"] for t in BUILD_TYPES]
    assert len(set(orders)) == len(orders)
    assert orders == sorted(orders)


def test_keys_are_url_and_storage_safe():
    for build_type in BUILD_TYPES:
        key = build_type["key"]
        assert key == key.lower()
        assert " " not in key
        assert len(key) <= 64


# ── Agent config ─────────────────────────────────────────────────────────────


def test_a_row_is_seeded_for_every_agent_role():
    keys = {row["agent_key"] for row in payloads()}
    assert keys == {*RESEARCH_AGENT_NAMES, SYNTHESIS_AGENT_NAME}


def test_the_seeded_prompt_is_exactly_the_built_in_default():
    """Turning configuration on must change nothing observable. A seed that
    quietly differs from the fallback shifts behaviour the moment it lands, and
    the diff is invisible to whoever runs the script."""
    for row in payloads():
        assert row["system_prompt"] == DEFAULT_INSTRUCTIONS[row["agent_key"]]


def test_every_seeded_row_is_active():
    assert all(row["active"] for row in payloads())


# ── Model catalog ────────────────────────────────────────────────────────────


def test_the_default_research_model_is_seeded_usable_and_default():
    """Without this row `start_run` 422s on the default research model."""
    from idea_scout.definitions import DEFAULT_RESEARCH_MODEL

    models = load_script("seed_model_catalog").MODELS
    rows = [m for m in models if m["model_id"] == DEFAULT_RESEARCH_MODEL]
    assert len(rows) == 1
    assert rows[0]["active"] and rows[0]["web_capable"] and rows[0]["is_default"]
    assert len({m["model_id"] for m in models}) == len(models)


def _http_error(code: int = 500):
    import io
    import urllib.error

    return urllib.error.HTTPError("http://x", code, "boom", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def test_a_failed_catalog_listing_exits_nonzero(monkeypatch, capsys):
    script = load_script("seed_model_catalog")
    monkeypatch.setenv("CORE_API_URL", "http://api")
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "tok")
    monkeypatch.setattr("sys.argv", ["seed_model_catalog.py"])

    def boom(*_a, **_k):
        raise _http_error(403)

    monkeypatch.setattr(script, "_request", boom)
    assert script.main() == 1
    assert "Could not list model catalog: 403" in capsys.readouterr().err


def test_a_failed_catalog_create_exits_nonzero(monkeypatch, capsys):
    script = load_script("seed_model_catalog")
    monkeypatch.setenv("CORE_API_URL", "http://api")
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "tok")
    monkeypatch.setattr("sys.argv", ["seed_model_catalog.py"])

    def fake(method, *_a, **_k):
        if method == "GET":
            return []
        raise _http_error(500)

    monkeypatch.setattr(script, "_request", fake)
    assert script.main() == 1
    assert "Failed on" in capsys.readouterr().err
