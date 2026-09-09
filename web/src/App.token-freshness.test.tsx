/**
 * biffo-plugin-ideation#69 / biffo-template#1492: `createApi(() => idToken)`
 * froze whatever token existed at mount inside React state that was set once
 * and never updated. A `CognitoUserSession` is immutable, so once that token
 * lapsed every call 401'd for the life of the page — no reload, no recovery.
 * This app polls every 5s for the life of an in-flight run, so a stale token
 * was not hypothetical: a run left open across an expiry stalled outright.
 *
 * The fix wires `createApi` to `getFreshIdToken`, which re-resolves the
 * session (and self-heals via the refresh token) on every call.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getFreshIdToken = vi.fn(() => Promise.resolve("test-token"));

vi.mock("./lib/auth", () => ({
  getCurrentSession: () =>
    Promise.resolve({ getIdToken: () => ({ getJwtToken: () => "test-token" }) }),
  getFreshIdToken,
}));

const createApiCalls: Array<() => string | null | Promise<string | null>> = [];

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    createApi: (getIdToken: () => string | null | Promise<string | null>) => {
      createApiCalls.push(getIdToken);
      return {
        getFormOptions: () =>
          Promise.resolve({
            build_types: [],
            business_models: [],
            models: [],
            preferences: [],
            complexity_levels: [],
      cadence: {
        enabled: true,
        cadence_days: 7,
        min_cadence_days: 1,
        max_cadence_days: 90,
        next_due_at: null,
        is_due: false,
      },
          }),
        getLastUsedModel: () => Promise.resolve(null),
        listRuns: () => Promise.resolve([]),
      };
    },
  };
});

const { default: App } = await import("./App");

describe("token freshness (biffo-plugin-ideation#69, biffo-template#1492)", () => {
  beforeEach(() => {
    createApiCalls.length = 0;
    getFreshIdToken.mockClear();
  });

  it("wires the API client to re-resolve the token per request, not a mount-time snapshot", async () => {
    render(<App />);
    await screen.findByText(/idea scout/i, {}, { timeout: 2000 }).catch(() => undefined);

    expect(createApiCalls).toHaveLength(1);
    const getIdToken = createApiCalls[0];

    getFreshIdToken.mockResolvedValueOnce("refreshed-token");
    await expect(getIdToken()).resolves.toBe("refreshed-token");
    expect(getFreshIdToken).toHaveBeenCalled();
  });
});
