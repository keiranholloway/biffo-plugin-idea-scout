import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RunForm } from "./RunForm";

const BUILD_TYPES = [
  { key: "micro-saas", label: "MicroSaaS", description: "One narrow job." },
  { key: "mobile-app", label: "Mobile Application", description: null },
];
const PREFS = [
  {
    key: "recurring-revenue",
    direction: "prefer" as const,
    label: "Recurring revenue",
  },
  {
    key: "regulated-markets",
    direction: "avoid" as const,
    label: "Regulated markets",
  },
];
const LEVELS = [
  { value: 1, label: "very small and niche" },
  { value: 3, label: "moderate" },
  { value: 5, label: "high-complexity" },
];

describe("RunForm", () => {
  it("cannot be submitted until a build type is chosen", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
  });

  it("starts a run with the chosen type and complexity", async () => {
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={onStart}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox"), "mobile-app");
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    // The third argument is the preference selection — empty here because
    // nothing is pre-selected, which is the deliberate default (#34).
    expect(onStart).toHaveBeenCalledWith("mobile-app", 3, []);
  });

  it("shows the chosen type’s description, because it feeds the research brief", async () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox"), "micro-saas");

    expect(screen.getByText("One narrow job.")).toBeInTheDocument();
  });

  it("renders the complexity wording served by the API, not its own", () => {
    // The words the founder reads must be the words the agents are briefed
    // with; a second copy here would drift.
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    expect(screen.getByText("moderate")).toBeInTheDocument();
  });

  it("says a scout cannot be started when no categories are configured", () => {
    // An empty list is an admin problem the founder cannot fix — better than an
    // empty picker that silently rejects every submission.
    render(
      <RunForm
        buildTypes={[]}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/No build types are configured/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run now" }),
    ).not.toBeInTheDocument();
  });

  it("tells the founder they can leave", () => {
    // The whole point of the fan-in work. If the UI does not say it, nobody
    // discovers it.
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    expect(screen.getByText(/close this tab/i)).toBeInTheDocument();
  });

  it("disables itself while a run is being started", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy
        onStart={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();
  });
});

describe("weight preferences (#34)", () => {
  it("starts with nothing selected, so a run is never shaped by an unmade choice", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    for (const box of screen.getAllByRole("checkbox")) {
      expect((box as HTMLInputElement).checked).toBe(false);
    }
  });

  it("sends the chosen keys, and only those", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={onStart}
      />,
    );

    await user.selectOptions(screen.getByRole("combobox"), "mobile-app");
    await user.click(screen.getByLabelText("Recurring revenue"));
    await user.click(screen.getByRole("button", { name: "Run now" }));

    expect(onStart).toHaveBeenCalledWith("mobile-app", 3, [
      "recurring-revenue",
    ]);
  });

  it("separates prefer from avoid, because they are different questions", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    // A flat list of ten made the founder read each label to work out which way
    // it pointed.
    expect(screen.getByText("Lean towards")).toBeTruthy();
    expect(screen.getByText("Steer away from")).toBeTruthy();
  });

  it("says they are preferences, not filters", () => {
    // The whole design rests on this: a strong idea that violates one still
    // appears. If the UI implies filtering, a founder will read a short list as
    // "there is nothing else" rather than "this is the ranking".
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    expect(screen.getByText(/not filters/i)).toBeTruthy();
  });

  it("renders nothing at all when the API offers no preferences", () => {
    // An older Core, or a deployment where the endpoint is absent. The form must
    // still work — preferences are optional by design.
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={[]}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Run now" })).toBeTruthy();
  });
});

describe("the promise made to a founder about waiting (#27)", () => {
  it('gives a bound rather than an open-ended "a few minutes"', () => {
    // A scout that hung for 255 minutes still said "finishes on its own", and a
    // founder had no way to tell a slow scout from a dead one. The reaper now
    // bounds it; the copy has to say so or the fix is invisible to them.
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        complexityLevels={LEVELS}
        preferences={PREFS}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    expect(screen.getByText(/two to four minutes/i)).toBeTruthy();
    expect(screen.getByText(/will not sit there indefinitely/i)).toBeTruthy();
  });
});
