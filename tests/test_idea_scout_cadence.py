"""The owner-scoped auto-scout cadence (#50, option A).

Three layers, because the feature has broken at each of them before in this
plugin and covering only the ends is how the seam between them goes missing
(#34 — the service was tested, the frontend was tested, and `app.py` dropped
the input in between):

1. **Derivation** — `is_due` and `next_due_at` computed from a stored interval
   and a run's `created_at`. This is the level-2 half: nothing writes the next
   due date down, so these assert the *rule*, not a stored value.
2. **The HTTP contract** — that the routes read and write what the surface
   needs, that an out-of-range interval is refused, and that one founder can
   neither read nor write another's.
3. **The adapter** — that the cadence row goes to Core's owner-scoped route
   with **no owner in the body or params**, because Core's stamping from the
   forwarded token is the thing actually keeping founders apart.

The load-bearing assertion in the whole file is
`test_turning_cadence_off_makes_nothing_due_however_old_the_last_run_is`: OFF
has to suppress the auto-start at the place that decides it, not merely hide a
control while the run still fires.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from biffo_plugin_sdk import ForwardedUser
from fakes import FakeCoreGateway, FakeTransport
from fastapi.testclient import TestClient

from idea_scout.adapter import CoreHttpGateway
from idea_scout.app import app, get_service, require_founder
from idea_scout.definitions import (
    DEFAULT_CADENCE_DAYS,
    MAX_CADENCE_DAYS,
    MIN_CADENCE_DAYS,
)
from idea_scout.models import CadencePreference, ScoutRun
from idea_scout.service import IdeaScoutService, InvalidCadenceError

OWNER = "founder-sub-abc"
OTHER = "founder-sub-xyz"

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def core() -> FakeCoreGateway:
    return FakeCoreGateway()


@pytest.fixture
def service(core: FakeCoreGateway) -> IdeaScoutService:
    return IdeaScoutService(core, research_model="research/m", synthesis_model="synthesis/m")


def _seed_run(
    core: FakeCoreGateway,
    *,
    owner_sub: str = OWNER,
    days_ago: float = 0,
    status: str = "complete",
    deleted: bool = False,
    created_at: str | None = None,
    run_id: str = "run-1",
) -> ScoutRun:
    """A finished run of a given age, written straight into the fake.

    Bypasses `start_run` deliberately: these tests are about the cadence rule,
    and going through the real start path would fire agent runs and fix
    `created_at` to the fake's own counter.
    """
    run = ScoutRun(
        id=run_id,
        owner_sub=owner_sub,
        build_type="micro-saas",
        complexity=3,
        chain_id="chain-1",
        status=status,
        created_at=(
            created_at if created_at is not None else (NOW - timedelta(days=days_ago)).isoformat()
        ),
        deleted=deleted,
    )
    core.runs[run.id] = run
    return run


# ── The default: nothing changes for a founder who never touches it ──────────


async def test_a_founder_with_no_stored_row_gets_the_built_in_default(service):
    """The whole compatibility claim of this change in one assertion.

    Before it, every founder was auto-scouted at a hardcoded 7 days. A founder
    who never opens the new control must still be, or shipping the preference
    would have silently changed behaviour for everyone.
    """
    preference = await service.get_cadence(owner_sub=OWNER)

    assert preference == CadencePreference(enabled=True, cadence_days=DEFAULT_CADENCE_DAYS, id=None)


async def test_the_default_still_makes_a_week_old_run_due(service, core):
    _seed_run(core, days_ago=DEFAULT_CADENCE_DAYS)

    state = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert state.is_due is True
    assert state.cadence_days == DEFAULT_CADENCE_DAYS


async def test_the_default_leaves_a_run_just_under_a_week_old_alone(service, core):
    _seed_run(core, days_ago=DEFAULT_CADENCE_DAYS - 0.01)

    assert (await service.cadence_state(owner_sub=OWNER, now=NOW)).is_due is False


# ── OFF genuinely suppresses the auto-start ──────────────────────────────────


async def test_turning_cadence_off_makes_nothing_due_however_old_the_last_run_is(service, core):
    """The point of the OFF state.

    A year-old run under a 1-day interval is as due as anything can get, so if
    OFF did not suppress at the decision itself this could not pass. A UI that
    merely hid the control would leave this true and start a scout anyway.
    """
    _seed_run(core, days_ago=365)
    await service.set_cadence(owner_sub=OWNER, enabled=False, cadence_days=1)

    state = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert state.enabled is False
    assert state.is_due is False
    assert state.next_due_at is None


async def test_turning_it_back_on_restores_the_interval_that_was_kept(service, core):
    """Off is not "forget what they chose". The interval rides through the
    toggle, so switching back on does not silently reset them to the default."""
    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=21)
    await service.set_cadence(owner_sub=OWNER, enabled=False, cadence_days=21)

    off = await service.get_cadence(owner_sub=OWNER)
    assert off.cadence_days == 21

    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=21)
    assert (await service.get_cadence(owner_sub=OWNER)).enabled is True


# ── The interval is actually used, in place of the constant ──────────────────


@pytest.mark.parametrize(
    ("cadence_days", "age_days", "expected_due"),
    [
        # A 3-day interval fires on a run the old 7-day constant would have
        # left alone — the direct evidence that the stored value is what is
        # consulted, not DEFAULT_CADENCE_DAYS.
        (3, 4, True),
        (3, 2, False),
        # A 30-day interval leaves alone a run the old constant would have
        # replaced. The opposite direction, which a one-sided test would miss.
        (30, 10, False),
        (30, 31, True),
        (MIN_CADENCE_DAYS, MIN_CADENCE_DAYS, True),
        (MAX_CADENCE_DAYS, MAX_CADENCE_DAYS - 1, False),
    ],
)
async def test_the_stored_interval_decides_staleness(
    service, core, cadence_days, age_days, expected_due
):
    _seed_run(core, days_ago=age_days)
    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=cadence_days)

    state = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert state.is_due is expected_due


async def test_next_due_is_the_last_run_plus_the_interval(service, core):
    """Derived, never stored — so changing the interval moves the due date with
    no write, and there is no column that can disagree with it."""
    _seed_run(core, days_ago=1)
    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=5)

    state = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert state.next_due_at == (NOW - timedelta(days=1) + timedelta(days=5)).isoformat()


async def test_changing_the_interval_moves_the_due_date_with_no_other_write(service, core):
    _seed_run(core, days_ago=1)
    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=5)
    first = await service.cadence_state(owner_sub=OWNER, now=NOW)

    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=10)
    second = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert second.next_due_at is not None and first.next_due_at is not None
    assert second.next_due_at > first.next_due_at


# ── The branches that must NOT start a run ───────────────────────────────────


async def test_a_founder_with_no_runs_is_not_due(service):
    """A founder who has never scouted is new, not "returning to a stale one" —
    and there would be nothing to replay the settings of anyway."""
    state = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert state.is_due is False
    assert state.next_due_at is None


@pytest.mark.parametrize("status", ["researching", "synthesising"])
async def test_an_in_flight_run_is_never_due(service, core, status):
    """The idempotency guard, read from server truth on every request: once a
    scout is running it is the most recent run, so a refresh or a second tab
    moments later sees this and does not fire a second one."""
    _seed_run(core, days_ago=365, status=status)

    assert (await service.cadence_state(owner_sub=OWNER, now=NOW)).is_due is False


async def test_a_deleted_run_does_not_hold_the_cadence_open(service, core):
    """The founder removed it, so it is no longer their last scout. Measured
    through `list_runs`, which already excludes soft-deleted rows — this asserts
    the cadence reads that filtered list rather than the raw one."""
    _seed_run(core, days_ago=1, deleted=True, run_id="deleted")
    _seed_run(core, days_ago=365, run_id="live")

    assert (await service.cadence_state(owner_sub=OWNER, now=NOW)).is_due is True


async def test_an_unreadable_timestamp_counts_as_due(service, core):
    """Core always stamps `created_at`, so this can only be a malformed value.
    "We do not know, so act as if it is old" costs at most one extra run;
    treating it as fresh would never offer that founder a scout again."""
    _seed_run(core, created_at="not-a-date")

    state = await service.cadence_state(owner_sub=OWNER, now=NOW)

    assert state.is_due is True
    assert state.next_due_at is None


async def test_an_unreadable_timestamp_is_still_not_due_when_off(service, core):
    """The tolerant branch above must not become a way round the OFF state."""
    _seed_run(core, created_at=None)
    await service.set_cadence(owner_sub=OWNER, enabled=False, cadence_days=7)

    assert (await service.cadence_state(owner_sub=OWNER, now=NOW)).is_due is False


# ── Validation ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("cadence_days", [0, -1, MAX_CADENCE_DAYS + 1, 500])
async def test_an_out_of_range_interval_is_refused(service, cadence_days):
    with pytest.raises(InvalidCadenceError):
        await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=cadence_days)


async def test_the_interval_is_validated_even_when_switching_off(service):
    """It is remembered across the toggle, so an out-of-range value accepted
    while off would come back the moment they switch on."""
    with pytest.raises(InvalidCadenceError):
        await service.set_cadence(owner_sub=OWNER, enabled=False, cadence_days=0)


async def test_a_refused_write_stores_nothing(service, core):
    with pytest.raises(InvalidCadenceError):
        await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=0)

    assert core.cadence == {}


# ── One row per founder ──────────────────────────────────────────────────────


async def test_saving_twice_patches_rather_than_inserting_a_second_row(service, core):
    """Core's owner-data routes have no upsert, so "one row per founder" is a
    service-layer invariant. If it broke, the read side would start answering
    with whichever row happened to come back first."""
    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=14)
    await service.set_cadence(owner_sub=OWNER, enabled=False, cadence_days=14)
    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=3)

    assert len(core.cadence) == 1
    assert (await service.get_cadence(owner_sub=OWNER)).cadence_days == 3


# ── Owner isolation, at the service ──────────────────────────────────────────


async def test_one_founder_does_not_read_anothers_preference(service, core):
    await service.set_cadence(owner_sub=OTHER, enabled=False, cadence_days=45)

    mine = await service.get_cadence(owner_sub=OWNER)

    assert mine.id is None, "read another founder's stored row"
    assert mine == CadencePreference(enabled=True, cadence_days=DEFAULT_CADENCE_DAYS)


async def test_one_founder_does_not_overwrite_anothers_preference(service, core):
    """The upsert reads before it writes. If that read were not owner-scoped it
    would find the other founder's row and PATCH it — silently changing what a
    stranger's surface does, with nothing failing."""
    await service.set_cadence(owner_sub=OTHER, enabled=False, cadence_days=45)

    await service.set_cadence(owner_sub=OWNER, enabled=True, cadence_days=2)

    assert len(core.cadence) == 2
    theirs = await service.get_cadence(owner_sub=OTHER)
    assert theirs.enabled is False
    assert theirs.cadence_days == 45


async def test_one_founders_runs_do_not_make_anothers_cadence_due(service, core):
    """The derivation reads the *caller's* runs. A leak here would auto-start a
    scout for a founder whose own history is empty — spending their budget on
    somebody else's staleness."""
    _seed_run(core, owner_sub=OTHER, days_ago=365)

    assert (await service.cadence_state(owner_sub=OWNER, now=NOW)).is_due is False


# ── The HTTP contract ────────────────────────────────────────────────────────


@contextmanager
def _as_founder(core: FakeCoreGateway, sub: str) -> Iterator[TestClient]:
    """A client bound to one founder, over the shared fake Core.

    The two isolation tests below swap between founders against the *same*
    gateway — which is the only arrangement in which a leak is observable at
    all. A separate fake per founder could not fail.
    """
    app.dependency_overrides[require_founder] = lambda: ForwardedUser(
        sub=sub, groups=["founder"], token="tok"
    )
    app.dependency_overrides[get_service] = lambda: IdeaScoutService(
        core, research_model="research/m", synthesis_model="synthesis/m"
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(core: FakeCoreGateway) -> Iterator[TestClient]:
    with _as_founder(core, OWNER) as bound:
        yield bound


def test_get_cadence_returns_everything_the_surface_renders(client):
    body = client.get("/cadence").json()

    assert body == {
        "enabled": True,
        "cadence_days": DEFAULT_CADENCE_DAYS,
        "min_cadence_days": MIN_CADENCE_DAYS,
        "max_cadence_days": MAX_CADENCE_DAYS,
        "next_due_at": None,
        "is_due": False,
    }


def test_the_bounds_served_are_the_bounds_enforced(client):
    """The number input's min/max come from this response. If they drifted from
    what the API accepts, the control would offer a value the save then 422s
    on — the two-copies failure this plugin already fixed for the complexity
    labels and the preference wording."""
    body = client.get("/cadence").json()

    assert (
        client.put(
            "/cadence", json={"enabled": True, "cadence_days": body["min_cadence_days"]}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/cadence", json={"enabled": True, "cadence_days": body["max_cadence_days"]}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/cadence", json={"enabled": True, "cadence_days": body["max_cadence_days"] + 1}
        ).status_code
        == 422
    )


def test_put_cadence_persists_and_echoes_the_recomputed_state(client, core):
    _seed_run(core, days_ago=4)

    body = client.put("/cadence", json={"enabled": True, "cadence_days": 3}).json()

    assert body["enabled"] is True
    assert body["cadence_days"] == 3
    # Recomputed from the value just saved, not echoed from the request — a
    # 4-day-old run is due under a 3-day cadence and was not under the default.
    assert body["is_due"] is True
    assert body["next_due_at"] is not None


def test_put_cadence_off_is_reflected_by_the_next_get(client, core):
    _seed_run(core, days_ago=365)

    client.put("/cadence", json={"enabled": False, "cadence_days": 7})
    body = client.get("/cadence").json()

    assert body["enabled"] is False
    assert body["is_due"] is False


@pytest.mark.parametrize("cadence_days", [0, MAX_CADENCE_DAYS + 1])
def test_the_route_refuses_an_out_of_range_interval(client, core, cadence_days):
    assert (
        client.put("/cadence", json={"enabled": True, "cadence_days": cadence_days}).status_code
        == 422
    )
    assert core.cadence == {}


def test_the_route_requires_both_halves_of_the_setting(client):
    """A PATCH-shaped partial write would leave the row in a state no screen
    ever showed the founder."""
    assert client.put("/cadence", json={"enabled": True}).status_code == 422
    assert client.put("/cadence", json={"cadence_days": 7}).status_code == 422


# ── Owner isolation, through the routes ──────────────────────────────────────


def test_a_founder_cannot_read_another_founders_cadence_through_the_route(core):
    with _as_founder(core, OTHER) as other:
        other.put("/cadence", json={"enabled": False, "cadence_days": 45})

    with _as_founder(core, OWNER) as mine:
        body = mine.get("/cadence").json()

    assert body["enabled"] is True, "saw another founder's OFF"
    assert body["cadence_days"] == DEFAULT_CADENCE_DAYS


def test_a_founder_cannot_write_another_founders_cadence_through_the_route(core):
    with _as_founder(core, OTHER) as other:
        other.put("/cadence", json={"enabled": False, "cadence_days": 45})

    with _as_founder(core, OWNER) as mine:
        mine.put("/cadence", json={"enabled": True, "cadence_days": 2})

    with _as_founder(core, OTHER) as other:
        theirs = other.get("/cadence").json()

    assert theirs == {
        "enabled": False,
        "cadence_days": 45,
        "min_cadence_days": MIN_CADENCE_DAYS,
        "max_cadence_days": MAX_CADENCE_DAYS,
        "next_due_at": None,
        "is_due": False,
    }


# ── The adapter: no owner ever crosses the wire ──────────────────────────────


async def test_the_cadence_read_hits_cores_owner_scoped_route_with_no_owner():
    """Core scopes this from the forwarded token. Sending an owner_sub would be
    a second, weaker filter that a later reader could mistake for the one doing
    the work — and this plugin's isolation would then rest on a query param."""
    transport = FakeTransport(
        {
            ("GET", "/api/v1/internal/owner-data/idea_scout_cadence"): [
                {"id": "c1", "enabled": True, "cadence_days": 14}
            ]
        }
    )

    preference = await CoreHttpGateway(transport).get_cadence(owner_sub=OWNER)

    call = transport.last("GET", "/api/v1/internal/owner-data/idea_scout_cadence")
    assert call["params"] is None
    assert call["json"] is None
    assert preference == CadencePreference(id="c1", enabled=True, cadence_days=14)


async def test_the_cadence_write_sends_no_owner_in_the_body():
    transport = FakeTransport(
        {
            ("POST", "/api/v1/internal/owner-data/idea_scout_cadence"): {
                "id": "c1",
                "enabled": True,
                "cadence_days": 14,
            }
        }
    )

    await CoreHttpGateway(transport).create_cadence(owner_sub=OWNER, enabled=True, cadence_days=14)

    body = transport.last("POST", "/api/v1/internal/owner-data/idea_scout_cadence")["json"]
    assert body == {"enabled": True, "cadence_days": 14}


async def test_a_patch_carries_both_columns_not_only_the_changed_one():
    transport = FakeTransport()

    await CoreHttpGateway(transport).update_cadence(cadence_id="c1", enabled=False, cadence_days=14)

    body = transport.last("PATCH", "/api/v1/internal/owner-data/idea_scout_cadence/c1")["json"]
    assert body == {"enabled": False, "cadence_days": 14}


async def test_no_stored_row_reads_as_none_rather_than_off():
    """`None` means "never touched the control" and becomes the default; `off`
    is a stored row. Collapsing the two would silently disable the auto-scout
    for every founder who has not used the new control."""
    assert await CoreHttpGateway(FakeTransport()).get_cadence(owner_sub=OWNER) is None


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {"id": "c1"},
            CadencePreference(id="c1", enabled=False, cadence_days=DEFAULT_CADENCE_DAYS),
        ),
        (
            {"id": "c1", "enabled": None, "cadence_days": None},
            CadencePreference(id="c1", enabled=False, cadence_days=DEFAULT_CADENCE_DAYS),
        ),
    ],
)
async def test_null_columns_read_as_off_at_the_default_interval(row, expected):
    """The generated DDL applies no defaults, so NULL is reachable. `cadence_days`
    must not read as 0 — that would mean "always due", the one interpretation
    that spends money on every page load."""
    transport = FakeTransport({("GET", "/api/v1/internal/owner-data/idea_scout_cadence"): [row]})

    assert await CoreHttpGateway(transport).get_cadence(owner_sub=OWNER) == expected


# ── The derivation is pure and total ─────────────────────────────────────────


def test_the_state_carries_the_preference_through_untouched(service):
    """A guard on shape rather than behaviour: `_derive_cadence_state` returns a
    new object, and dropping a field while building it would leave the control
    rendering a default over the founder's own setting."""
    from idea_scout.service import _derive_cadence_state

    preference = CadencePreference(id="c1", enabled=True, cadence_days=13)
    run = replace(
        ScoutRun(
            id="r",
            owner_sub=OWNER,
            build_type="micro-saas",
            complexity=3,
            chain_id="c",
            status="complete",
        ),
        created_at=NOW.isoformat(),
    )

    state = _derive_cadence_state(preference=preference, most_recent=run, now=NOW)

    assert (state.enabled, state.cadence_days) == (True, 13)
