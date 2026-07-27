"""Tests for the plain data types — mostly the two behaviours that carry logic."""

from __future__ import annotations

from idea_scout import models as m


def test_a_founder_with_nothing_saved_reads_as_empty():
    """Drives whether the brief can personalise at all, so it must not be
    fooled by the all-defaults shape Core returns for an unsaved profile."""
    assert m.UserProfile().is_empty is True


def test_founder_before_alone_does_not_count_as_a_profile():
    """founder_before defaults to False and is a bool, so a naive `any()` over
    the fields would call an untouched profile non-empty the moment someone
    flipped the default."""
    assert m.UserProfile(founder_before=False).is_empty is True


def test_any_real_field_makes_a_profile_usable():
    assert m.UserProfile(headline="Fractional CTO").is_empty is False
    assert m.UserProfile(focus_areas=["fintech"]).is_empty is False
    assert m.UserProfile(years_experience=12).is_empty is False


def test_run_terminality_and_success_are_distinct():
    """A failed run is terminal — the fan-in must stop waiting on it — but not
    successful. Conflating the two hangs a run forever or silently drops it."""
    failed = m.AgentRunView(id="r", status=m.RUN_FAILED)
    assert failed.is_terminal is True
    assert failed.succeeded is False

    completed = m.AgentRunView(id="r", status=m.RUN_COMPLETED)
    assert completed.is_terminal is True
    assert completed.succeeded is True

    running = m.AgentRunView(id="r", status="running")
    assert running.is_terminal is False
    assert running.succeeded is False


def test_in_flight_statuses_are_the_non_terminal_run_statuses():
    assert m.IN_FLIGHT_STATUSES == m.STATUSES - {m.COMPLETE, m.FAILED}
