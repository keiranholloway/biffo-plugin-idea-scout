"""The manifest is this plugin's contract with Core — assert it, don't assume it.

Two kinds of check live here:

1. **Structural** — it loads through the SDK's real ``PluginManifest`` model
   (the same one Core's discovery and ``biffo plugin install`` validate against),
   and its tables/routes/permissions agree with each other. CI runs
   ``load_manifest`` too; these go further, because the SDK model ignores fields
   it does not know about (``core_capabilities``, ``owner_scoped_service``,
   ingress blocks) and so cannot catch a typo in any of them.
2. **Intentional** — the declarations that encode a decision someone could
   quietly undo: which Core capabilities this plugin depends on, and which
   tables are owner-scoped rather than tenant-scoped.
"""

from __future__ import annotations

import json

from biffo_plugin_sdk.plugin import load_manifest

from idea_scout.manifest import MANIFEST_PATH

# The repo root: the manifest sits at the top level, so its parent is the root.
_ROOT = MANIFEST_PATH.parent

# Every Core capability this plugin binds, and the gateway call that needs it.
# Adding a capability here without using it — or using a seam without declaring
# it — is exactly the drift this test exists to catch.
#
#   agent-run-request     -> requesting the research and synthesis runs
#   agent-run-read        -> polling those runs for their terminal state
#   run-output-tool       -> the findings/candidates structured-output tools
#   owner-scoped-tables   -> /internal/owner-data/idea_scout_{runs,candidates,cadence}
#   chat-agent-registry   -> the admin-editable prompt/model per agent role
#   user-profile-read     -> /internal/user-profile/mine (biffo-platform #74)
EXPECTED_CAPABILITIES = {
    "agent-run-request",
    "agent-run-read",
    "run-output-tool",
    "owner-scoped-tables",
    "chat-agent-registry",
    "user-profile-read",
}

OWNER_SCOPED_TABLES = {"idea_scout_runs", "idea_scout_candidates", "idea_scout_cadence"}
ADMIN_MANAGED_TABLES = {
    "idea_scout_build_types",
    "idea_scout_business_models",
    "idea_scout_model_catalog",
}


def _raw() -> dict:
    """The manifest as written on disk — the SDK model drops unknown fields, so
    anything Core reads but the SDK does not must be asserted against this."""
    return json.loads(MANIFEST_PATH.read_text())


# ── Structural ───────────────────────────────────────────────────────────────


def test_loads_through_the_sdk_model():
    manifest = load_manifest(MANIFEST_PATH)
    assert manifest.name == "idea-scout"
    assert manifest.version == "0.1.0"


def test_declares_exactly_the_expected_tables():
    manifest = load_manifest(MANIFEST_PATH)
    assert {t.name for t in manifest.tables} == OWNER_SCOPED_TABLES | ADMIN_MANAGED_TABLES


def test_business_models_mirrors_build_types():
    """The two admin-managed pickers must stay structurally identical — same
    columns, same permission posture, same unique key. A divergence here means
    one of them has drifted into a different contract by accident."""
    raw = _raw()
    tables = {t["name"]: t for t in raw["tables"]}
    build, models = tables["idea_scout_build_types"], tables["idea_scout_business_models"]

    assert [c["name"] for c in models["columns"]] == [c["name"] for c in build["columns"]]
    assert [c["type"] for c in models["columns"]] == [c["type"] for c in build["columns"]]
    assert models["permissions"] == build["permissions"]
    assert models["indexes"][0]["columns"] == ["tenant_id", "key"]
    assert models["indexes"][0]["unique"] is True


def test_runs_carry_an_optional_business_model():
    """Optional by design: a founder may have no preference, and NULL is a real
    answer rather than missing data."""
    runs = {t["name"]: t for t in _raw()["tables"]}["idea_scout_runs"]
    column = next(c for c in runs["columns"] if c["name"] == "business_model")
    assert column["type"] == "String(64)"
    assert column["nullable"] is True


def test_cadence_stores_the_preference_and_nothing_derivable_from_it():
    """The cadence table holds the founder's *inputs* and only those.

    Storing `next_run_at`, `next_due_at` or `last_run_at` would put a fact in
    two places — the column and `idea_scout_runs.created_at` plus the interval
    — and the two would disagree the moment a founder changed the interval or
    deleted their most recent run. `service._derive_cadence_state` computes
    them on read instead, and this guard is what keeps the shortcut from being
    added back later "just for the query".
    """
    table = next(t for t in _raw()["tables"] if t["name"] == "idea_scout_cadence")
    assert {c["name"] for c in table["columns"]} == {
        "owner_sub",
        "enabled",
        "cadence_days",
    }


def test_cadence_scopes_by_owner_the_same_way_runs_do():
    """A cadence preference is as owner-private as a run is.

    Asserted against `idea_scout_runs` rather than against literals, so the two
    cannot drift: if the runs table's owner column or principal list ever
    changes, this fails rather than silently leaving cadence behind on the old
    contract.
    """
    tables = {t["name"]: t for t in _raw()["tables"]}
    runs, cadence = tables["idea_scout_runs"], tables["idea_scout_cadence"]

    assert cadence["owner_scoped_service"] == runs["owner_scoped_service"]
    assert cadence["permissions"] == runs["permissions"]
    owner = next(c for c in cadence["columns"] if c["name"] == "owner_sub")
    assert owner["type"] == "String(64)"
    assert owner["nullable"] is False
    assert cadence["indexes"][0]["columns"] == ["tenant_id", "owner_sub"]


def test_no_example_scaffolding_survives():
    """The repo was scaffolded from the plugin template's example widget plugin.
    Nothing of it should remain."""
    assert "widget" not in json.dumps(_raw()).lower()


def test_every_route_targets_a_declared_table():
    raw = _raw()
    table_names = {t["name"] for t in raw["tables"]}
    for route in raw["api_routes"]:
        assert route["table"] in table_names, route


def test_single_row_routes_take_an_id_and_collection_routes_do_not():
    """Core's route synthesis requires this pairing; getting it wrong is a 404
    at runtime rather than a validation error at install."""
    for route in _raw()["api_routes"]:
        has_id = "{id}" in route["path"]
        if route["operation"] in {"read", "update", "delete"}:
            assert has_id, route
        else:
            assert not has_id, route


def test_every_route_is_actually_permitted():
    """A route declared in api_routes but not allowed in its table's permissions
    silently 404s (ADR-0004 default-deny). Both must be set."""
    raw = _raw()
    permissions = {t["name"]: t["permissions"] for t in raw["tables"]}
    for route in raw["api_routes"]:
        allowed = permissions[route["table"]].get(route["operation"], {}).get("allowed")
        assert allowed is True, route


def test_no_route_exposes_an_owner_scoped_table():
    """Generic CRUD is tenant-scoped, not owner-scoped — serving these tables
    through it would let one founder read another's runs. They are reachable
    only through Core's owner-scoped service routes."""
    for route in _raw()["api_routes"]:
        assert route["table"] not in OWNER_SCOPED_TABLES, route


def test_reserved_columns_are_not_declared():
    """id/tenant_id/created_at/updated_at are auto-injected on every plugin
    table (ADR-0001); declaring one is a hard error at install time."""
    reserved = {"id", "tenant_id", "created_at", "updated_at"}
    for table in _raw()["tables"]:
        declared = {c["name"] for c in table["columns"]}
        assert not (declared & reserved), table["name"]


def test_columns_use_only_resolvable_types():
    """Core's plugin-table type map resolves only these base types; anything
    else is rejected — and there is deliberately no JSON type, which is why the
    JSON-bearing columns are Text."""
    allowed_bases = {"String", "Integer", "Text", "Boolean", "Float", "DateTime"}
    for table in _raw()["tables"]:
        for column in table["columns"]:
            base = column["type"].split("(")[0]
            assert base in allowed_bases, (table["name"], column)


def test_json_bearing_columns_are_text():
    """If one of these were declared String it would silently truncate a
    report; if it were declared JSON the type map would reject it."""
    json_columns = {
        "idea_scout_runs": {"research_run_ids", "profile_snapshot"},
        "idea_scout_candidates": {"scorecard", "sources"},
    }
    for table in _raw()["tables"]:
        expected = json_columns.get(table["name"], set())
        for column in table["columns"]:
            if column["name"] in expected:
                assert column["type"] == "Text", (table["name"], column)


def test_columns_with_no_db_default_are_nullable():
    """The generated migration DDL does not apply declared defaults — only the
    in-process model does. A column the service fills in after insert must
    therefore be nullable or the insert fails."""
    set_after_insert = {
        ("idea_scout_runs", "status"),
        ("idea_scout_runs", "deleted"),
        ("idea_scout_build_types", "active"),
        ("idea_scout_cadence", "enabled"),
        ("idea_scout_cadence", "cadence_days"),
    }
    for table in _raw()["tables"]:
        for column in table["columns"]:
            if (table["name"], column["name"]) in set_after_insert:
                assert column["nullable"] is True, (table["name"], column)


# ── Intentional ──────────────────────────────────────────────────────────────


def test_declares_exactly_the_expected_core_capabilities():
    assert set(_raw()["core_capabilities"]) == EXPECTED_CAPABILITIES


def test_every_capability_is_pinned_to_a_major():
    for capability, pin in _raw()["core_capabilities"].items():
        assert pin.startswith("^"), (capability, pin)


def test_owner_scoped_tables_are_owner_scoped_and_crud_denied():
    for table in _raw()["tables"]:
        if table["name"] not in OWNER_SCOPED_TABLES:
            continue
        scoped = table["owner_scoped_service"]
        assert scoped["owner_column"] == "owner_sub"
        assert scoped["allowed_principals"] == ["system:idea-scout"]
        assert all(not p.get("allowed") for p in table["permissions"].values()), table["name"]


def test_build_types_are_readable_by_founders_and_writable_only_by_admins():
    """The founder's run form needs the list; only an admin may change it."""
    table = next(t for t in _raw()["tables"] if t["name"] == "idea_scout_build_types")
    permissions = table["permissions"]
    for read_op in ("list", "read"):
        assert permissions[read_op]["allowed"] is True
        assert permissions[read_op]["required_role"] == []
    for write_op in ("create", "update", "delete"):
        assert permissions[write_op]["allowed"] is True
        assert permissions[write_op]["required_role"] == ["admin"]


# ── Ingress (added once the apps existed — M5) ───────────────────────────────


def test_every_declared_ingress_app_is_importable():
    """A manifest naming an import path that does not resolve deploys clean and
    404s at runtime, which is the worst time to find out."""
    import importlib

    raw = _raw()
    declared = [b for b in ("user_ingress", "admin_ingress") if b in raw]
    assert "user_ingress" in declared, "the founder-facing app is not optional"

    for block in declared:
        spec = raw[block]
        expected = {"user_ingress": "founder", "admin_ingress": "admin"}[block]
        assert spec["required_group"] == expected
        module_path, _, attr = spec["app"].partition(":")
        module = importlib.import_module(module_path)
        assert hasattr(module, attr), spec["app"]


def test_admin_ingress_is_only_declared_when_an_admin_ui_can_actually_be_served():
    """Declaring `admin_ingress` promises an admin UI, and the deploy will not
    say so if the promise is empty.

    This plugin declared it with no `web-admin/` anywhere in the repo (#22). The
    deploy step is `if jq -e '.admin_ingress' … && [ -d "$plugin_dir/web-admin" ]`
    — the second condition failed, the build-and-copy was **skipped with no error
    and no warning**, and `GET /admin/` 404'd. A CDN rule then rewrote that 404
    into the marketing portal's HTML, so the visible symptom was an admin URL
    apparently serving an unauthenticated page (biffo-template#647).

    So the manifest is not the place to state an intention. Re-adding
    `admin_ingress` requires the thing that makes it true, and this test is what
    couples the two.

    The path resolution is the second half of that (#22 defect 2): `__file__`
    lands one directory shallower in the deployed Lambda than in a checkout,
    because the deploy flattens `src/` into the task root, while the built assets
    go to `BIFFO_PLUGINS_ROOT/<name>/web-admin/dist`. Ideation hit exactly this
    and fixed it (biffo-template#627/#632); the copy here was never updated, so a
    `web-admin/` alone would still have 404'd. Anyone re-enabling this must port
    `_resolve_static_dir` rather than resurrect the `parent.parent.parent` form.
    """
    raw = _raw()
    if "admin_ingress" not in raw:
        return  # the current, honest state

    web_admin = _ROOT / "web-admin"
    assert web_admin.is_dir(), (
        "admin_ingress is declared but web-admin/ does not exist — the deploy "
        "will skip the UI build silently and GET /admin/ will 404 (#22)"
    )
    admin_source = (_ROOT / "src" / "idea_scout" / "admin_app.py").read_text()

    # Assert the PROPERTY (anchored on BIFFO_PLUGINS_ROOT), not the absence of a
    # substring. The first version of this guard banned "parent.parent.parent"
    # — and then rejected the correct fix, because ideation's proven
    # `_resolve_static_dir` keeps exactly that expression as its local-dev
    # fallback. The defect in #22 was never the string; it was that the string
    # was the *only* resolution, with no deployed anchor.
    assert "BIFFO_PLUGINS_ROOT" in admin_source, (
        "admin_app.py must resolve its static dir from BIFFO_PLUGINS_ROOT. The "
        "deploy flattens src/ into the Lambda task root, so a purely "
        "__file__-relative path lands one directory shallower than in a "
        "checkout and 404s — see biffo-template#627/#632 and #22 defect 2."
    )
    assert "_resolve_static_dir" in admin_source, (
        "keep the resolution in a named helper — it is the thing that has to be "
        "read and understood before anyone changes it"
    )


def test_the_founder_frontend_points_at_the_build_output():
    assert _raw()["user_frontend"] == {"dir": "web/dist", "required_group": "founder"}
