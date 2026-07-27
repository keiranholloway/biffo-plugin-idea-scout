"""Conformance: both implementations really do satisfy the ``CoreGateway`` port.

Nothing else checks this. The service is typed against the Protocol, but it is
only ever *constructed* with a fake in tests and with the real adapter in the
Lambda — so an adapter method whose signature drifts from the port fails at
runtime in production while every test stays green, and a fake that drifts makes
the tests prove something about a shape Core does not have.

The assignments below are the assertion: pyright checks Protocol conformance
structurally at the assignment, so a drifted signature is a type error, not a
surprise at 3am. The runtime asserts are a backstop for anyone running pytest
without pyright.
"""

from __future__ import annotations

import inspect

from fakes import FakeCoreGateway, FakeTransport

from idea_scout.adapter import CoreHttpGateway
from idea_scout.ports import CoreGateway


def test_the_http_adapter_satisfies_the_port():
    gateway: CoreGateway = CoreHttpGateway(FakeTransport())
    assert isinstance(gateway, CoreHttpGateway)


def test_the_fake_satisfies_the_port():
    """A fake that has drifted from the port is a test suite proving nothing."""
    gateway: CoreGateway = FakeCoreGateway()
    assert isinstance(gateway, FakeCoreGateway)


def test_the_fake_and_the_adapter_agree_on_every_signature():
    """Protocol conformance allows extra optional parameters, so two
    implementations can both satisfy the port while disagreeing with each other
    — and the service would then behave differently in tests than in production.
    """
    port_methods = [
        name
        for name, value in vars(CoreGateway).items()
        if callable(value) and not name.startswith("_")
    ]
    assert port_methods, "the port exposes no methods — has it been refactored?"

    for name in port_methods:
        adapter_sig = inspect.signature(getattr(CoreHttpGateway, name))
        fake_sig = inspect.signature(getattr(FakeCoreGateway, name))
        assert adapter_sig.parameters.keys() == fake_sig.parameters.keys(), name
