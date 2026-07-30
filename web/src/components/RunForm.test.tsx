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
const BUSINESS_MODELS = [
  { key: "subscription", label: "Subscription / SaaS", description: "Recurring payment for access." },
  { key: "advertising", label: "Advertising / sponsorship", description: null },
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /build/i }), "mobile-app");
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    // The third argument is the preference selection — empty here because
    // nothing is pre-selected, which is the deliberate default (#34).
    expect(onStart).toHaveBeenCalledWith("mobile-app", 3, [], undefined, undefined);
  });

  it("shows the chosen type’s description, because it feeds the research brief", async () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /build/i }), "micro-saas");

    expect(screen.getByText("One narrow job.")).toBeInTheDocument();
  });

  it("renders the complexity wording served by the API, not its own", () => {
    // The words the founder reads must be the words the agents are briefed
    // with; a second copy here would drift.
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );

    await user.selectOptions(screen.getByRole("combobox", { name: /build/i }), "mobile-app");
    await user.click(screen.getByLabelText("Recurring revenue"));
    await user.click(screen.getByRole("button", { name: "Run now" }));

    expect(onStart).toHaveBeenCalledWith(
      "mobile-app",
      3,
      ["recurring-revenue"],
      undefined,
      undefined,
    );
  });

  it("separates prefer from avoid, because they are different questions", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={[]}
        models={[]}
        selectedModel={null}
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
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    expect(screen.getByText(/two to four minutes/i)).toBeTruthy();
    expect(screen.getByText(/will not sit there indefinitely/i)).toBeTruthy();
  });
});

describe("Model picker (M3)", () => {
  const MODELS = [
    { id: "m1", model_id: "anthropic/claude-sonnet-4:online", label: "Sonnet", is_default: false },
    { id: "m2", model_id: "anthropic/claude-opus-4:online", label: "Opus", is_default: true },
  ];

  it("offers exactly what GET /models returned", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={MODELS}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    const select = screen.getByRole("combobox", { name: /model/i }) as HTMLSelectElement;
    // Count the MODEL options — those with a value. The empty-valued option is
    // "no choice made", not an invented model, and it exists so the select can
    // never display a model it has not got. The property this test defends is
    // unchanged: the models offered are exactly the ones the API returned.
    const modelOptions = Array.from(select.options)
      .filter((opt) => opt.value !== "")
      .map((opt) => opt.textContent);
    expect(modelOptions).toContain("Sonnet");
    expect(modelOptions).toContain("Opus");
    expect(modelOptions).toHaveLength(2);
  });

  it("pre-selects the last-used model when there is one", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={MODELS}
        selectedModel="m1"
        busy={false}
        onStart={vi.fn()}
      />,
    );

    const select = screen.getByRole("combobox", { name: /model/i }) as HTMLSelectElement;
    expect(select.value).toBe("m1");
  });

  it("falls back to is_default when last-used is null", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={MODELS}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );

    const select = screen.getByRole("combobox", { name: /model/i }) as HTMLSelectElement;
    expect(select.value).toBe("m2");
  });

  it("does not render an empty dropdown or break when model list is empty", () => {
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );

    // Form should still work
    expect(screen.getByRole("button", { name: "Run now" })).not.toBeNull();
    expect(screen.queryByText(/model/i)).toBeNull();
  });

  it("includes model selection in run start, or omits it if no selection", async () => {
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={MODELS}
        selectedModel="m1"
        busy={false}
        onStart={onStart}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /build/i }), "mobile-app");
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    // With a model selected, should pass it
    expect(onStart).toHaveBeenCalledWith("mobile-app", 3, [], "m1", undefined);
  });

  it("omits research_model rather than sending empty string", async () => {
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /build/i }), "mobile-app");
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    // Without a model available/selected, should not include research_model param
    expect(onStart).toHaveBeenCalledWith("mobile-app", 3, [], undefined, undefined);
  });
});

  it("never displays a model as chosen when none is", async () => {
    // With no last-used model and no `is_default` in the catalog, `modelId` is
    // empty. A select whose value matches no option renders the FIRST one, so the
    // form claimed a model it did not hold — and submitted the wrong thing.
    // The explicit empty option makes "nothing chosen" look like nothing chosen.
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[
          {
            id: "m1",
            model_id: "anthropic/claude-sonnet-4:online",
            label: "Claude Sonnet 4 (web)",
            is_default: false,
          },
          {
            id: "m2",
            model_id: "deepseek/deepseek-v4-flash:online",
            label: "DeepSeek V4 Flash",
            is_default: false,
          },
        ]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );

    const modelSelect = screen.getByRole("combobox", { name: /model/i }) as HTMLSelectElement;
    expect(modelSelect.value).toBe("");
    expect(modelSelect.options[modelSelect.selectedIndex]?.text).not.toBe("Claude Sonnet 4 (web)");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: /build/i }), "micro-saas");
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));

    // No model argument at all, so the server applies its own default — rather
    // than the client sending something it never had.
    expect(onStart).toHaveBeenCalledWith("micro-saas", 3, [], undefined, undefined);
});

describe("business-model picker", () => {
  it("is optional: a run starts with no model chosen, and sends undefined", async () => {
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText(/looking to build/i), "micro-saas");
    await userEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(onStart).toHaveBeenCalledTimes(1);
    // 5th argument is business_model. Undefined, not "" — the api layer omits
    // the field entirely rather than sending an empty string.
    expect(onStart.mock.calls[0][4]).toBeUndefined();
  });

  it("passes the chosen key through", async () => {
    const onStart = vi.fn();
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={onStart}
      />,
    );
    await userEvent.selectOptions(screen.getByLabelText(/looking to build/i), "micro-saas");
    await userEvent.selectOptions(screen.getByLabelText(/make money/i), "advertising");
    await userEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(onStart.mock.calls[0][4]).toBe("advertising");
  });

  it("shows the description of the chosen model, and nothing when it has none", async () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    const picker = screen.getByLabelText(/make money/i);
    await userEvent.selectOptions(picker, "subscription");
    expect(screen.getByText("Recurring payment for access.")).toBeInTheDocument();

    await userEvent.selectOptions(picker, "advertising");
    expect(screen.queryByText("Recurring payment for access.")).not.toBeInTheDocument();
  });

  it("carries no price or multiple in any option or hint", async () => {
    // The founder-facing guard: the taxonomy came from asking prices with no
    // sold data, so a figure here would read as a valuation it is not. Mirrors
    // tests/test_idea_scout_seed_business_models.py on the backend.
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={BUSINESS_MODELS}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    const picker = screen.getByLabelText(/make money/i);
    await userEvent.selectOptions(picker, "subscription");
    const money = /[$£€]|\b\d+(?:\.\d+)?\s*[x×](?![a-z0-9])/i;
    expect(picker.parentElement?.textContent ?? "").not.toMatch(money);
  });

  it("hides entirely when the table is unseeded, rather than offering an empty picker", () => {
    render(
      <RunForm
        buildTypes={BUILD_TYPES}
        businessModels={[]}
        complexityLevels={LEVELS}
        preferences={PREFS}
        models={[]}
        selectedModel={null}
        busy={false}
        onStart={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText(/make money/i)).not.toBeInTheDocument();
  });
});
