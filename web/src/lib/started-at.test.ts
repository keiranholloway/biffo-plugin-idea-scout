import { describe, expect, it } from "vitest";

import { startedAt } from "./started-at";

describe("startedAt", () => {
  it("parses Core’s ISO string as UTC, not as local time", () => {
    // The exact shape the deployed API returns, verified against
    // /api/v1/admin/agent-runs: an explicit Z, microsecond precision.
    const result = startedAt("2026-07-28T12:55:23.240947Z");

    expect(result).not.toBeNull();
    // Asserted through Date rather than the formatted string, because the
    // formatted string is locale- and timezone-dependent and this assertion
    // must hold everywhere CI runs.
    expect(new Date(result!.iso).toISOString()).toBe(
      "2026-07-28T12:55:23.240Z",
    );
  });

  it("produces a label containing both a date and a time", () => {
    const result = startedAt("2026-07-28T12:55:23.240947Z");

    // Not asserting exact text: `toLocaleString` output varies by ICU version
    // and runner locale, and pinning it makes the test fail on a machine
    // difference rather than on a defect.
    expect(result!.label).toMatch(/\d/);
    expect(result!.label).toMatch(/:/); // a time is present
    expect(result!.label.length).toBeGreaterThan(5);
  });

  it("keeps the original string for the dateTime attribute", () => {
    const iso = "2026-07-28T12:55:23.240947Z";

    // `<time dateTime>` must carry the machine-readable original, not the
    // localised label — that is the whole point of the element.
    expect(startedAt(iso)!.iso).toBe(iso);
  });

  it('returns null rather than "Invalid Date" for an unparseable value', () => {
    // Showing a founder "Invalid Date" is worse than showing nothing, and this
    // is the case a defensive `+ 'Z'` would have created on an already-marked
    // string.
    expect(startedAt("2026-07-28T12:55:23.240947ZZ")).toBeNull();
    expect(startedAt("not a date")).toBeNull();
  });

  it("returns null for a missing value without throwing", () => {
    // `created_at` is typed `string | null`; the list renders before anything
    // guarantees Core supplied one.
    expect(startedAt(null)).toBeNull();
    expect(startedAt(undefined)).toBeNull();
    expect(startedAt("")).toBeNull();
  });

  it("does not treat an offset-bearing timestamp as local either", () => {
    // Core uses Z today, but the column is DateTime(timezone=True) and a
    // +00:00 form is equally valid ISO 8601. Both must resolve to the same
    // instant, or the sidebar would drift by the viewer's offset if Core's
    // serialisation ever changed shape.
    const withZ = startedAt("2026-07-28T12:55:23Z")!;
    const withOffset = startedAt("2026-07-28T13:55:23+01:00")!;

    expect(new Date(withZ.iso).getTime()).toBe(
      new Date(withOffset.iso).getTime(),
    );
  });
});
