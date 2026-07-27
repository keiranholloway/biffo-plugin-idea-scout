"""Idea Scout — identity-aware startup idea discovery for Biffo.

A user-facing plugin module (ADR-0017) mounted by the shared plugin host
(ADR-0021). It reads the founder's own profile through Core, dispatches three
angle-specific research agents over web search, and reconciles their findings
into a ranked, scored shortlist of candidate ideas — each promotable into the
Ideation Engine for pressure-testing.

Nothing is exported at package level. The host mounts the ASGI apps named in
``biffo.plugin.json`` by import path, and everything else here is internal to
the module — the same shape the Ideation Engine's own package has.
"""
