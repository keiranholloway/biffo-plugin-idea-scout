/** The PRD flow end to end through App: start, resume, send, cap, back. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const startPrd = vi.fn();
const sendPrdMessage = vi.fn();
const getCandidates = vi.fn();
const getPrd = vi.fn();

vi.mock("./lib/auth", () => ({
  getCurrentSession: () =>
    Promise.resolve({ getIdToken: () => ({ getJwtToken: () => "t" }) }),
  getFreshIdToken: () => Promise.resolve("t"),
}));

const RUN = {
  run_id: "r1",
  status: "complete",
  build_type: "micro-saas",
  complexity: 3,
  complexity_label: "moderate",
  created_at: "2026-07-28T12:55:23Z",
  in_flight: false,
  failure_reason: null,
  preferences: [],
};

vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return {
    ...actual,
    createApi: () => ({
      listRuns: () => Promise.resolve([RUN]),
      getFormOptions: () =>
        Promise.resolve({
          build_types: [{ key: "micro-saas", label: "MicroSaaS", description: null }],
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
      getCandidates,
      startPrd,
      getPrd,
      sendPrdMessage,
      getCadence: vi.fn(),
    }),
  };
});

const { default: App } = await import("./App");

const cand = (prd_status: string | null) => ({
  id: "c1",
  rank: 1,
  title: "Broker tooling",
  pitch: "pitch",
  scorecard: null,
  sources: [],
  prd_status,
});

const prdState = (over: Record<string, unknown> = {}) => ({
  id: "p1",
  candidate_id: "c1",
  run_id: "r1",
  status: "interviewing",
  thread_id: "t1",
  turn_count: 0,
  max_turns: 15,
  ...over,
});

async function openCandidates(status: string | null) {
  getCandidates.mockResolvedValue({ ...RUN, candidates: [cand(status)] });
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: /MicroSaaS/ }));
  await screen.findByText("Broker tooling");
}

describe("PRD view", () => {
  beforeEach(() => {
    startPrd.mockReset();
    sendPrdMessage.mockReset();
    getCandidates.mockReset();
    getPrd.mockReset();
    // The stored row mirrors whatever state the start call returned.
    getPrd.mockImplementation(async () => {
      const state = { ...(await startPrd.mock.results[0].value) };
      delete state.messages;
      return { ...state, compile_run_id: null, prd: null, failure_reason: null };
    });
  });

  it("starts a PRD: POST, then the view opens with the first reply", async () => {
    startPrd.mockResolvedValue({
      ...prdState(),
      messages: [{ role: "assistant", content: "I have read your pitch." }],
    });
    await openCandidates(null);
    fireEvent.click(screen.getByRole("button", { name: "Build a PRD" }));

    expect(await screen.findByText("I have read your pitch.")).toBeInTheDocument();
    expect(startPrd).toHaveBeenCalledWith("c1");
    expect(screen.getByRole("heading", { name: "Broker tooling" })).toBeInTheDocument();
    expect(screen.getByText("Turn 0 of 15")).toBeInTheDocument();
  });

  it("resumes a PRD with the stored transcript", async () => {
    startPrd.mockResolvedValue({
      ...prdState({ turn_count: 2 }),
      messages: [
        { role: "assistant", content: "First." },
        { role: "user", content: "My answer." },
        { role: "assistant", content: "Second." },
      ],
    });
    await openCandidates("interviewing");
    fireEvent.click(screen.getByRole("button", { name: "Open PRD" }));

    expect(await screen.findByText("My answer.")).toBeInTheDocument();
    expect(screen.getByText("Second.")).toBeInTheDocument();
  });

  it("sends a turn and shows the reply", async () => {
    startPrd.mockResolvedValue({ ...prdState(), messages: [{ role: "assistant", content: "Hi." }] });
    sendPrdMessage.mockResolvedValue({ ...prdState({ turn_count: 1 }), reply: "Got it." });
    await openCandidates(null);
    fireEvent.click(screen.getByRole("button", { name: "Build a PRD" }));
    await screen.findByText("Hi.");

    fireEvent.change(screen.getByLabelText("Your reply"), { target: { value: "For brokers" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Got it.")).toBeInTheDocument();
    expect(screen.getByText("For brokers")).toBeInTheDocument();
    expect(sendPrdMessage).toHaveBeenCalledWith("p1", "For brokers");
    expect(screen.getByText("Turn 1 of 15")).toBeInTheDocument();
  });

  it("disables the composer at the turn cap", async () => {
    startPrd.mockResolvedValue({
      ...prdState({ turn_count: 15 }),
      messages: [{ role: "assistant", content: "Done." }],
    });
    await openCandidates("interviewing");
    fireEvent.click(screen.getByRole("button", { name: "Open PRD" }));

    expect(await screen.findByText(/Turn limit reached/)).toBeInTheDocument();
    expect(screen.getByLabelText("Your reply")).toBeDisabled();
  });

  it("disables the composer while drafting", async () => {
    startPrd.mockResolvedValue({
      ...prdState({ status: "drafting", turn_count: 3 }),
      messages: [{ role: "assistant", content: "Working." }],
    });
    await openCandidates("drafting");
    fireEvent.click(screen.getByRole("button", { name: "Open PRD" }));

    await screen.findByText("Working.");
    expect(screen.getByLabelText("Your reply")).toBeDisabled();
  });

  it("the back link returns to the run's candidates", async () => {
    startPrd.mockResolvedValue({ ...prdState(), messages: [{ role: "assistant", content: "Hi." }] });
    await openCandidates(null);
    fireEvent.click(screen.getByRole("button", { name: "Build a PRD" }));
    await screen.findByText("Hi.");

    getCandidates.mockResolvedValue({ ...RUN, candidates: [cand("interviewing")] });
    fireEvent.click(screen.getByRole("button", { name: /Back to candidates/ }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Open PRD" })).toBeInTheDocument());
    expect(screen.getByText("Interviewing")).toBeInTheDocument();
  });
});
