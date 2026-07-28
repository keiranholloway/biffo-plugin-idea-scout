/**
 * The Past scouts list shows when each scout was started.
 *
 * `started-at.test.ts` proves the formatter. This proves the sidebar actually
 * renders it — a formatter nothing calls is the failure mode a unit test cannot
 * see, and the whole point of the change is what a founder looks at.
 */

import { render, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listRuns = vi.fn();

// App calls `session?.getIdToken().getJwtToken()`, so the fake has to be that
// shape — a plain object silently yields "not signed in" and an empty sidebar,
// which is indistinguishable from the feature being broken.
vi.mock("./lib/auth", () => ({
  getCurrentSession: () =>
    Promise.resolve({
      getIdToken: () => ({ getJwtToken: () => "test-token" }),
    }),
}));

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    // Names taken from createApi itself, not guessed — a wrong name here fails
    // as "no rows rendered", which reads exactly like the feature being broken.
    createApi: () => ({
      listRuns,
      getBuildTypes: () =>
        Promise.resolve([
          { key: "micro-saas", label: "MicroSaaS", description: null },
        ]),
      getComplexityLevels: () =>
        Promise.resolve([{ value: 3, label: "moderate" }]),
      getRun: vi.fn(),
      startRun: vi.fn(),
      deleteRun: vi.fn(),
      getCandidates: vi.fn(),
    }),
  };
});

const { default: App } = await import("./App");

function run(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "r1",
    status: "complete",
    build_type: "micro-saas",
    complexity: 3,
    complexity_label: "moderate",
    created_at: "2026-07-28T12:55:23.240947Z",
    in_flight: false,
    failure_reason: null,
    ...overrides,
  };
}

describe("Past scouts — when each was started", () => {
  beforeEach(() => {
    listRuns.mockReset();
  });

  it("renders a machine-readable time carrying the original timestamp", async () => {
    listRuns.mockResolvedValue([run()]);

    render(<App />);

    // Found by role/semantics rather than by class: the <time> element with a
    // dateTime attribute is the contract, the CSS class is decoration.
    const el = await waitFor(() => {
      const t = document.querySelector("time.run-started");
      expect(t).not.toBeNull();
      return t as HTMLTimeElement;
    });
    expect(el.getAttribute("datetime")).toBe("2026-07-28T12:55:23.240947Z");
    expect(el.textContent?.trim()).not.toBe("");
  });

  it("distinguishes two scouts of the same build type", async () => {
    // The reason this change exists: three MicroSaaS runs previously rendered
    // as three identical rows.
    listRuns.mockResolvedValue([
      run({ run_id: "r1", created_at: "2026-07-28T12:55:23Z" }),
      run({ run_id: "r2", created_at: "2026-07-26T08:10:00Z" }),
    ]);

    render(<App />);

    await waitFor(() =>
      expect(document.querySelectorAll("time.run-started")).toHaveLength(2),
    );
    const [first, second] = [...document.querySelectorAll("time.run-started")];
    expect(first.textContent).not.toBe(second.textContent);
  });

  it("omits the time rather than rendering a placeholder when Core sent none", async () => {
    listRuns.mockResolvedValue([run({ created_at: null })]);

    render(<App />);

    // The row must still appear — a missing timestamp is not a reason to hide
    // a scout the founder ran. Scoped to the sidebar because the main panel
    // renders the same label, and an unscoped query matches both.
    const sidebar = await waitFor(() => {
      const el = document.querySelector("aside.sidebar");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    await waitFor(() =>
      expect(within(sidebar).getByText("MicroSaaS")).toBeTruthy(),
    );
    expect(sidebar.querySelector("time.run-started")).toBeNull();
  });
});
