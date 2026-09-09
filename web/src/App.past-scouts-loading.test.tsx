/**
 * The Past scouts sidebar must not speak for a list it has not received.
 *
 * `App.tsx` already declares a `loaded` flag, with a comment explaining that an
 * unloaded app and one that loaded an empty list are otherwise
 * indistinguishable. Two call sites honour it; the sidebar did not, and told a
 * founder with eleven scouts that they had none (#53).
 *
 * Every other test in this suite awaits the resolved state, so none of them can
 * see this window. This one holds the list request open on purpose.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listRuns = vi.fn();

vi.mock("./lib/auth", () => ({
  getCurrentSession: () =>
    Promise.resolve({
      getIdToken: () => ({ getJwtToken: () => "test-token" }),
    }),
  getFreshIdToken: () => Promise.resolve("test-token"),
}));

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    createApi: () => ({
      listRuns,
      getFormOptions: () =>
        Promise.resolve({
          build_types: [
            { key: "micro-saas", label: "MicroSaaS", description: null },
          ],
          business_models: [],
          models: [],
          preferences: [],
          complexity_levels: [{ value: 3, label: "moderate" }],
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
      getRun: vi.fn(),
      startRun: vi.fn(),
      deleteRun: vi.fn(),
      getCandidates: vi.fn(),
    }),
  };
});

const { default: App } = await import("./App");

describe("Past scouts — before the list has returned", () => {
  beforeEach(() => {
    listRuns.mockReset();
  });

  it("does not claim there are no scouts while the list is still in flight", async () => {
    let release: (value: unknown) => void = () => {};
    listRuns.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );

    render(<App />);

    // The sidebar heading is up, so the shell has rendered — this is the
    // window in which the old code asserted "No scouts yet."
    await waitFor(() =>
      expect(screen.getByText("Past scouts")).toBeInTheDocument(),
    );
    expect(screen.queryByText("No scouts yet.")).not.toBeInTheDocument();

    // Once it answers with a genuinely empty list, the empty state is correct.
    release([]);
    await waitFor(() =>
      expect(screen.getByText("No scouts yet.")).toBeInTheDocument(),
    );
  });
});
