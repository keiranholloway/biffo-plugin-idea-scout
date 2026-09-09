/** Guards the #79 fix: the page must not fan out on mount.
 *
 * Every `/api/v1/plugins/idea-scout/*` request is served by the shared plugin
 * host, which then calls Core — so each one costs two Lambda invocations. With
 * the account concurrency ceiling at 10, the old seven-call mount asked for
 * roughly fourteen at once and throttled itself into
 * `503 {"message":"Service Unavailable"}`.
 *
 * Counting calls rather than asserting a list of names on purpose: the point is
 * the *number* of round trips, which is what the ceiling constrains.
 */
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];
const track = <T,>(name: string, value: T) => () => {
  calls.push(name);
  return Promise.resolve(value);
};

vi.mock("./lib/auth", () => ({
  getCurrentSession: () =>
    Promise.resolve({ getIdToken: () => ({ getJwtToken: () => "test-token" }) }),
  getFreshIdToken: () => Promise.resolve("test-token"),
}));

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    // Names taken from createApi itself, not guessed — a wrong name here fails
    // as an unhandled rejection that reads like the feature being broken.
    createApi: () => ({
      getFormOptions: track("getFormOptions", {
        build_types: [{ key: "micro-saas", label: "MicroSaaS", description: null }],
        business_models: [],
        models: [],
        preferences: [],
        complexity_levels: [{ value: 3, label: "moderate" }],
        // Bootstrapped inside this response rather than fetched separately —
        // which is exactly what keeps the mount at three calls (#50/#79).
        cadence: {
          enabled: true,
          cadence_days: 7,
          min_cadence_days: 1,
          max_cadence_days: 90,
          next_due_at: null,
          is_due: false,
        },
      }),
      getLastUsedModel: track("getLastUsedModel", null),
      listRuns: track("listRuns", []),
      getRun: vi.fn(),
      startRun: vi.fn(),
      deleteRun: vi.fn(),
      getCandidates: vi.fn(),
      // Tracked, not stubbed silently: if the cadence were ever fetched on
      // mount again it would show up in the count below rather than hiding.
      getCadence: track("getCadence", {}),
      setCadence: vi.fn(),
    }),
  };
});

describe("request fan-out on mount (#79)", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("issues at most three requests", async () => {
    const { default: App } = await import("./App");
    render(<App />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    await waitFor(() => expect(calls).toContain("listRuns"));

    expect(calls.length).toBeLessThanOrEqual(3);
  });

  it("fetches the form's reference data in a single call", async () => {
    const { default: App } = await import("./App");
    render(<App />);
    await waitFor(() => expect(calls).toContain("getFormOptions"));

    expect(calls.filter((c) => c === "getFormOptions")).toHaveLength(1);
  });
});
